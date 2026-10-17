"""Modular job queue for offloaded run execution.

Supports:
- AsyncInMemoryQueue: Zero-infra local-first queue backed by asyncio.Queue and in-process workers.
- InlineQueue: Synchronous fallback (queue disabled / tests).

By default, Alberto uses AsyncInMemoryQueue, achieving zero-infra background processing
with zero extra daemons.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import aiosqlite

log = logging.getLogger("forge.queue")


class BaseQueue(ABC):
    """Abstract queue interface."""

    @abstractmethod
    async def enqueue(self, run_id: str, tenant_id: str, project_id: str | None = None) -> bool:
        """Enqueue a run. Returns True if accepted, False otherwise."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Cleanly close/drain the queue."""
        ...

    @abstractmethod
    def is_enabled(self) -> bool:
        """Check if queue is enabled."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Queue backend identifier."""
        ...


class AsyncInMemoryQueue(BaseQueue):
    """Zero-infra in-process queue backed by asyncio.Queue with bounded workers."""

    def __init__(self, max_concurrency: int = 4, max_size: int = 1000, checkpointer: Any = None) -> None:
        self.max_concurrency = max_concurrency
        self.max_size = max_size
        self.checkpointer = checkpointer
        self._queue: asyncio.Queue[tuple[str, str, str | None]] | None = None
        self._workers: list[asyncio.Task] = []
        self._closed = False

    @property
    def name(self) -> str:
        return "in_memory"

    def is_enabled(self) -> bool:
        return not self._closed

    def _ensure_started(self) -> None:
        if self._closed:
            return
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self.max_size)
        if not self._workers or all(w.done() for w in self._workers):
            self._workers = [
                asyncio.create_task(self._worker_loop(i), name=f"alberto-queue-worker-{i}")
                for i in range(self.max_concurrency)
            ]

    async def enqueue(self, run_id: str, tenant_id: str, project_id: str | None = None) -> bool:
        if self._closed:
            return False
        self._ensure_started()
        try:
            assert self._queue is not None
            self._queue.put_nowait((run_id, tenant_id, project_id))
            log.info("enqueued run %s to in-memory queue (pending=%d)", run_id, self._queue.qsize())
            return True
        except asyncio.QueueFull:
            log.warning("in-memory queue full (%d items); falling back to inline", self.max_size)
            return False
        except Exception:
            log.exception("failed to enqueue run %s to in-memory queue", run_id)
            return False

    async def _worker_loop(self, worker_id: int) -> None:
        log.debug("started in-memory queue worker %d", worker_id)
        while not self._closed:
            try:
                assert self._queue is not None
                run_id, tenant_id, project_id = await self._queue.get()
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.1)
                continue

            try:
                from alberto.services.runs import RunService

                cp = self.checkpointer or _active_checkpointer
                run_service = RunService(checkpointer=cp)
                await run_service.run_to_completion(
                    run_id=run_id, tenant_id=tenant_id, project_id=project_id
                )
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("in-memory worker failed executing run %s", run_id)
            finally:
                self._queue.task_done()

    async def close(self) -> None:
        self._closed = True
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await w
        self._workers.clear()
        self._queue = None


class SqliteJobQueue(BaseQueue):
    """Separate SQLite-backed queue for independent background worker processes.

    Jobs are stored in a dedicated queue database file (settings.queue_db_path).
    Worker processes (python -m forge.worker) poll and claim jobs without contending
    with the main application database or API server event loop.
    """

    def __init__(self, db_path: str | None = None) -> None:
        from alberto.config import settings

        self.db_path = db_path or settings.queue_db_path
        self._init_done = False
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "sqlite"

    def is_enabled(self) -> bool:
        return True

    async def _ensure_table(self) -> None:
        if self._init_done:
            return
        async with self._lock:
            if self._init_done:
                return

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
            self._init_done = True

    async def enqueue(self, run_id: str, tenant_id: str, project_id: str | None = None) -> bool:
        try:
            await self._ensure_table()
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA busy_timeout=5000;")
                await db.execute(
                    """
                    INSERT INTO job_queue (run_id, tenant_id, project_id, status, available_at)
                    VALUES (?, ?, ?, 'queued', CURRENT_TIMESTAMP);
                    """,
                    (run_id, tenant_id, project_id),
                )
                await db.commit()
            log.info("enqueued run %s to sqlite job queue (%s)", run_id, self.db_path)
            return True
        except Exception:
            log.exception("failed to enqueue run %s to sqlite job queue", run_id)
            return False

    async def close(self) -> None:
        pass


class InlineQueue(BaseQueue):
    """Queue disabled; runs execute synchronously inline."""

    @property
    def name(self) -> str:
        return "inline"

    def is_enabled(self) -> bool:
        return False

    async def enqueue(self, run_id: str, tenant_id: str, project_id: str | None = None) -> bool:
        return False

    async def close(self) -> None:
        pass


_active_checkpointer: Any = None


def set_checkpointer(checkpointer: Any) -> None:
    """Register the checkpointer used by in-memory background queue workers."""
    global _active_checkpointer
    _active_checkpointer = checkpointer


def get_checkpointer() -> Any:
    """Return the active checkpointer for background queue workers."""
    return _active_checkpointer


_current_queue: BaseQueue | None = None


def get_queue() -> BaseQueue:
    """Return active queue singleton (in-memory async queue default; sqlite for workers; inline for tests)."""
    global _current_queue
    if _current_queue is None:
        backend = os.getenv("FORGE_QUEUE_BACKEND", "").lower()
        if backend == "inline":
            _current_queue = InlineQueue()
        elif backend in ("sqlite", "worker"):
            _current_queue = SqliteJobQueue()
        else:
            _current_queue = AsyncInMemoryQueue()
    return _current_queue


def set_queue(queue: BaseQueue) -> None:
    """Override the active queue instance (useful in testing / custom plugins)."""
    global _current_queue
    _current_queue = queue


# Backward compatibility helper functions
def queue_enabled() -> bool:
    """Return True if a queue backend is active."""
    return get_queue().is_enabled()


async def enqueue_run(run_id: str, tenant_id: str, project_id: str | None = None) -> bool:
    """Enqueue a run using the active queue backend."""
    return await get_queue().enqueue(run_id, tenant_id, project_id)


async def close_pool() -> None:
    """Close and clean up the active queue backend."""
    global _current_queue
    if _current_queue is not None:
        await _current_queue.close()
        _current_queue = None
