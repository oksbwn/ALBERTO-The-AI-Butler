"""Standalone SQLite background worker (zero-infra, no Redis / no arq).

Run it:
    python -m forge.worker

Picks up queued run jobs from the dedicated queue database (settings.queue_db_path),
executes them to completion with RunService and durable checkpoints, and writes status back.
Retries up to MAX_TRIES before dead-lettering.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import aiosqlite

from alberto.config import settings
from alberto.services.runs import RunService

log = logging.getLogger("forge.worker")

MAX_TRIES = 3


class SQLiteWorker:
    """Dedicated background worker polling the separate queue.sqlite database."""

    def __init__(
        self,
        db_path: str | None = None,
        poll_interval: float | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.db_path = db_path or settings.queue_db_path
        self.poll_interval = poll_interval if poll_interval is not None else settings.queue_poll_interval
        self.worker_id = worker_id or f"worker-{os.getpid()}"
        self._stop_event = asyncio.Event()
        self._stack: AsyncExitStack | None = None
        self.run_service: RunService | None = None

    async def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS job_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    locked_at TIMESTAMP,
                    locked_by TEXT
                );
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_queue_status_created
                ON job_queue(status, created_at);
            """)
            await db.commit()

    async def startup(self) -> None:
        from alberto.main import _make_checkpointer

        if settings.prefer_ipv4_egress:
            from alberto.util.netfix import install_prefer_ipv4_dns

            install_prefer_ipv4_dns()

        settings.ensure_dirs()
        problems = settings.validate_production()
        if problems:
            raise RuntimeError("Unsafe production configuration:\n  - " + "\n  - ".join(problems))
        for warn in settings.startup_warnings():
            log.warning("INSECURE CONFIG: %s", warn)

        await self._init_db()

        self._stack = AsyncExitStack()
        checkpointer = await _make_checkpointer(self._stack)
        self.run_service = RunService(checkpointer=checkpointer, store=None)
        log.info(
            "forge worker started [id=%s, queue_db=%s, poll=%.1fs]",
            self.worker_id,
            self.db_path,
            self.poll_interval,
        )

    async def shutdown(self) -> None:
        log.info("shutting down forge worker [id=%s]...", self.worker_id)
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        log.info("forge worker shutdown complete")

    async def _claim_next_job(self) -> dict[str, Any] | None:
        """Atomically find and claim the oldest queued job."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA busy_timeout=5000;")
            async with db.execute(
                """
                SELECT id, run_id, tenant_id, project_id, attempts, max_attempts
                FROM job_queue
                WHERE status = 'queued'
                ORDER BY id ASC
                LIMIT 1;
                """
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                job = dict(row)

            # Atomically claim it
            cursor = await db.execute(
                """
                UPDATE job_queue
                SET status = 'running',
                    locked_at = CURRENT_TIMESTAMP,
                    locked_by = ?,
                    attempts = attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'queued';
                """,
                (self.worker_id, job["id"]),
            )
            await db.commit()
            if cursor.rowcount == 1:
                return job
        return None

    async def _finish_job(self, job_id: int, status: str, error: str | None = None) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute(
                """
                UPDATE job_queue
                SET status = ?,
                    error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
                """,
                (status, error, job_id),
            )
            await db.commit()

    async def execute_job(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        run_id = job["run_id"]
        tenant_id = job["tenant_id"]
        project_id = job["project_id"]
        attempts = int(job.get("attempts") or 0) + 1
        max_attempts = int(job.get("max_attempts") or MAX_TRIES)

        log.info("executing run %s (attempt %d/%d)", run_id, attempts, max_attempts)
        try:
            assert self.run_service is not None
            await self.run_service.run_to_completion(
                run_id=run_id, tenant_id=tenant_id, project_id=project_id
            )
            await self._finish_job(job_id, status="completed")
            log.info("run %s completed successfully", run_id)
        except Exception as e:
            log.exception("run %s failed on attempt %d: %s", run_id, attempts, e)
            if attempts >= max_attempts:
                log.error("run %s dead-lettered after %d attempts", run_id, attempts)
                await self._finish_job(job_id, status="failed", error=str(e))
                try:
                    await RunService._mark_unfinished(
                        run_id, tenant_id, status="error", error=f"dead-lettered: {e}"
                    )
                except Exception:
                    pass
            else:
                # Requeue for retry
                await self._finish_job(job_id, status="queued", error=str(e))

    async def run(self) -> None:
        await self.startup()
        try:
            while not self._stop_event.is_set():
                try:
                    job = await self._claim_next_job()
                    if job:
                        await self.execute_job(job)
                        continue
                except Exception:
                    log.exception("error in worker poll loop")

                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
                except TimeoutError:
                    pass
        finally:
            await self.shutdown()

    def stop(self) -> None:
        self._stop_event.set()


async def run_worker() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    worker = SQLiteWorker()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        await worker.run()
    except (asyncio.CancelledError, KeyboardInterrupt):
        worker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
