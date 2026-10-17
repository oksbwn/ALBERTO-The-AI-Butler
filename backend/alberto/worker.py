"""Standalone SQLite background worker (zero-infra, no Redis / no arq).

Run it:
    python -m forge.worker

Picks up queued run jobs from the dedicated queue database (settings.queue_db_path),
executes them to completion with RunService and durable checkpoints, and writes status back.
Retries up to MAX_TRIES before dead-lettering.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
import signal
import sys
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timedelta
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
                    locked_by TEXT,
                    available_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            async with db.execute("PRAGMA table_info(job_queue);") as cursor:
                cols = [row[1] for row in await cursor.fetchall()]
            if "available_at" not in cols:
                await db.execute("ALTER TABLE job_queue ADD COLUMN available_at TIMESTAMP;")
                await db.execute("UPDATE job_queue SET available_at = CURRENT_TIMESTAMP WHERE available_at IS NULL;")
            if "lease_token" not in cols:
                await db.execute("ALTER TABLE job_queue ADD COLUMN lease_token TEXT;")
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_queue_status_created
                ON job_queue(status, created_at);
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_queue_status_avail
                ON job_queue(status, available_at);
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_queue_lease
                ON job_queue(id, lease_token);
            """)
            await db.commit()

    async def _is_safe_to_retry(self, job: dict[str, Any]) -> bool:
        """Determine if a job is safe to automatically retry after lease expiry.
        Only jobs with explicit idempotency guarantees are safe to retry;
        side-effecting jobs with uncertain outcomes must be preserved in failed state."""
        run_id = job.get("run_id")
        tenant_id = job.get("tenant_id")
        if not run_id or not tenant_id:
            return False
        try:
            from sqlalchemy import select

            from alberto.db.base import SessionLocal
            from alberto.models import Run, Workflow
            async with SessionLocal() as s:
                run = (await s.execute(select(Run).where(Run.tenant_id == tenant_id, Run.id == run_id))).scalar_one_or_none()
                if not run:
                    return False
                wf = (await s.execute(select(Workflow).where(Workflow.id == run.workflow_id))).scalar_one_or_none()
                if not wf or not wf.executable:
                    return False
                exec_data = wf.executable
                if exec_data.get("idempotent") is True or (exec_data.get("retry_policy") or {}).get("idempotent") is True:
                    return True
        except Exception:
            log.exception("error checking idempotency for run %s", run_id)
        return False

    async def recover_abandoned_jobs(self, lease_timeout_seconds: float | None = None) -> int:
        """Scan for jobs whose worker lease expired (crashed worker, reboot).
        Safe/idempotent jobs are re-queued with retry backoff.
        Uncertain side-effecting jobs are marked failed/abandoned to prevent duplicate execution."""
        lease_timeout = float(lease_timeout_seconds if lease_timeout_seconds is not None else settings.worker_lease_timeout_seconds)
        cutoff = (datetime.utcnow() - timedelta(seconds=lease_timeout)).strftime("%Y-%m-%d %H:%M:%S")
        recovered = 0
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA busy_timeout=5000;")
            async with db.execute(
                """
                SELECT id, run_id, tenant_id, project_id, attempts, max_attempts, locked_by, lease_token
                FROM job_queue
                WHERE status = 'running' AND locked_at < ?;
                """,
                (cutoff,),
            ) as cursor:
                stale_jobs = [dict(r) for r in await cursor.fetchall()]

        for job in stale_jobs:
            job_id = job["id"]
            run_id = job["run_id"]
            tenant_id = job["tenant_id"]
            attempts = int(job.get("attempts") or 0)
            max_attempts = int(job.get("max_attempts") or MAX_TRIES)
            locked_by = job.get("locked_by")
            lease_token = job.get("lease_token")
            safe = await self._is_safe_to_retry(job)

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA busy_timeout=5000;")
                if safe and attempts < max_attempts:
                    base = float(settings.worker_retry_backoff_base_seconds)
                    delay = min(60.0, base * (2 ** max(0, attempts - 1)) + random.uniform(0.1, 0.5))
                    avail = (datetime.utcnow() + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")
                    cur = await db.execute(
                        """
                        UPDATE job_queue
                        SET status = 'queued',
                            error = 're-queued after worker lease expired',
                            available_at = ?,
                            lease_token = NULL,
                            locked_at = NULL,
                            locked_by = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND status = 'running' AND (lease_token = ? OR (lease_token IS NULL AND (locked_by = ? OR locked_by IS NULL)));
                        """,
                        (avail, job_id, lease_token, locked_by),
                    )
                    await db.commit()
                    if cur.rowcount == 1:
                        log.info("re-queued safe abandoned job %d (run %s)", job_id, run_id)
                        recovered += 1
                else:
                    reason = "max retry attempts exceeded" if attempts >= max_attempts else "worker lease expired with uncertain side-effecting outcome"
                    cur = await db.execute(
                        """
                        UPDATE job_queue
                        SET status = 'failed',
                            error = ?,
                            lease_token = NULL,
                            locked_at = NULL,
                            locked_by = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND status = 'running' AND (lease_token = ? OR (lease_token IS NULL AND (locked_by = ? OR locked_by IS NULL)));
                        """,
                        (f"abandoned: {reason}", job_id, lease_token, locked_by),
                    )
                    await db.commit()
                    if cur.rowcount == 1:
                        log.warning("marked abandoned job %d failed (run %s): %s", job_id, run_id, reason)
                        try:
                            await RunService._mark_unfinished(
                                run_id, tenant_id, status="error", error=f"abandoned: {reason}"
                            )
                        except Exception:
                            pass
                        recovered += 1
        return recovered

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
        await self.recover_abandoned_jobs()
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
        """Atomically find and claim the oldest eligible queued job."""
        now_dt = datetime.utcnow()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA busy_timeout=5000;")
            async with db.execute(
                """
                SELECT id, run_id, tenant_id, project_id, attempts, max_attempts
                FROM job_queue
                WHERE status = 'queued' AND (available_at IS NULL OR available_at <= ?)
                ORDER BY id ASC
                LIMIT 1;
                """,
                (now_str,),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                job = dict(row)

            lease_token = str(uuid.uuid4())
            cursor = await db.execute(
                """
                UPDATE job_queue
                SET status = 'running',
                    locked_at = ?,
                    locked_by = ?,
                    lease_token = ?,
                    attempts = attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'queued';
                """,
                (now_str, self.worker_id, lease_token, job["id"]),
            )
            await db.commit()
            if cursor.rowcount == 1:
                job["status"] = "running"
                job["locked_at"] = now_str
                job["locked_by"] = self.worker_id
                job["lease_token"] = lease_token
                return job
        return None

    async def _finish_job(self, job_id: int, status: str, error: str | None = None, lease_token: str | None = None) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA busy_timeout=5000;")
            if lease_token is not None:
                cursor = await db.execute(
                    """
                    UPDATE job_queue
                    SET status = ?,
                        error = ?,
                        lease_token = NULL,
                        locked_at = NULL,
                        locked_by = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND lease_token = ? AND status = 'running';
                    """,
                    (status, error, job_id, lease_token),
                )
            else:
                cursor = await db.execute(
                    """
                    UPDATE job_queue
                    SET status = ?,
                        error = ?,
                        lease_token = NULL,
                        locked_at = NULL,
                        locked_by = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                    """,
                    (status, error, job_id),
                )
            await db.commit()
            if cursor.rowcount == 0 and lease_token is not None:
                log.warning("worker %s lost ownership of job %d (token %s); skipped finalizing with status %s", self.worker_id, job_id, lease_token, status)
                return False
            return True

    async def _heartbeat(self, job: dict[str, Any], stop_ev: asyncio.Event) -> None:
        interval = max(5.0, settings.worker_lease_timeout_seconds / 3.0)
        job_id = job["id"]
        lease_token = job.get("lease_token")
        while not stop_ev.is_set():
            try:
                await asyncio.wait_for(stop_ev.wait(), timeout=interval)
                break
            except TimeoutError:
                pass
            new_locked_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA busy_timeout=5000;")
                cursor = await db.execute(
                    """
                    UPDATE job_queue
                    SET locked_at = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND lease_token = ? AND status = 'running';
                    """,
                    (new_locked_at, job_id, lease_token),
                )
                await db.commit()
                if cursor.rowcount == 0:
                    log.warning("worker %s lost lease for job %d during heartbeat (token %s)", self.worker_id, job_id, lease_token)
                    break
                job["locked_at"] = new_locked_at

    async def execute_job(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        run_id = job["run_id"]
        tenant_id = job["tenant_id"]
        project_id = job["project_id"]
        attempts = int(job.get("attempts") or 0) + 1
        max_attempts = int(job.get("max_attempts") or MAX_TRIES)
        lease_token = job.get("lease_token")

        log.info("executing run %s (attempt %d/%d)", run_id, attempts, max_attempts)
        hb_stop = asyncio.Event()
        hb_task = asyncio.create_task(self._heartbeat(job, hb_stop))
        try:
            assert self.run_service is not None
            await self.run_service.run_to_completion(
                run_id=run_id, tenant_id=tenant_id, project_id=project_id
            )
            await self._finish_job(job_id, status="completed", lease_token=lease_token)
            log.info("run %s completed successfully", run_id)
        except Exception as e:
            log.exception("run %s failed on attempt %d: %s", run_id, attempts, e)
            if attempts >= max_attempts:
                log.error("run %s dead-lettered after %d attempts", run_id, attempts)
                await self._finish_job(job_id, status="failed", error=str(e), lease_token=lease_token)
                try:
                    await RunService._mark_unfinished(
                        run_id, tenant_id, status="error", error=f"dead-lettered: {e}"
                    )
                except Exception:
                    pass
            else:
                base = float(settings.worker_retry_backoff_base_seconds)
                delay = min(60.0, base * (2 ** (attempts - 1)) + random.uniform(0.1, 0.5))
                avail_time = datetime.utcnow() + timedelta(seconds=delay)
                avail_str = avail_time.strftime("%Y-%m-%d %H:%M:%S")
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("PRAGMA busy_timeout=5000;")
                    await db.execute(
                        """
                        UPDATE job_queue
                        SET status = 'queued',
                            error = ?,
                            available_at = ?,
                            lease_token = NULL,
                            locked_at = NULL,
                            locked_by = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND lease_token = ? AND status = 'running';
                        """,
                        (str(e), avail_str, job_id, lease_token),
                    )
                    await db.commit()
                log.info("re-queued run %s for retry in %.1fs", run_id, delay)
        finally:
            hb_stop.set()
            hb_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await hb_task

    async def run(self) -> None:
        await self.startup()
        tick = 0
        try:
            while not self._stop_event.is_set():
                try:
                    tick += 1
                    if tick % 10 == 0:
                        await self.recover_abandoned_jobs()
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
