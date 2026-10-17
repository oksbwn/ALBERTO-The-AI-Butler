import asyncio
import pytest

from alberto.queue import (
    AsyncInMemoryQueue,
    BaseQueue,
    InlineQueue,
    get_queue,
    set_queue,
    enqueue_run,
    queue_enabled,
    close_pool,
    set_checkpointer,
    get_checkpointer,
)


@pytest.mark.asyncio
async def test_inline_queue():
    q = InlineQueue()
    assert q.name == "inline"
    assert not q.is_enabled()
    res = await q.enqueue("r1", "t1")
    assert res is False


@pytest.mark.asyncio
async def test_in_memory_queue():
    q = AsyncInMemoryQueue(max_concurrency=2, max_size=10)
    assert q.name == "in_memory"
    assert q.is_enabled()
    res = await q.enqueue("r1", "t1", "p1")
    assert res is True
    await q.close()
    assert not q.is_enabled()



@pytest.mark.asyncio
async def test_queue_registry_and_helpers():
    mock_q = InlineQueue()
    set_queue(mock_q)
    assert get_queue() is mock_q
    assert not queue_enabled()
    assert await enqueue_run("r2", "t2") is False
    await close_pool()


def test_checkpointer_registration():
    marker = object()
    set_checkpointer(marker)
    assert get_checkpointer() is marker
    set_checkpointer(None)
    assert get_checkpointer() is None


@pytest.mark.asyncio
async def test_sqlite_job_queue_and_worker(tmp_path):
    import aiosqlite
    from alberto.queue import SqliteJobQueue
    from alberto.worker import SQLiteWorker

    db_path = str(tmp_path / "queue.sqlite")
    q = SqliteJobQueue(db_path=db_path)
    assert q.name == "sqlite"
    assert q.is_enabled()

    enqueued = await q.enqueue("run-abc", "tenant-xyz", "proj-123")
    assert enqueued is True

    # Verify directly in SQLite table
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM job_queue WHERE run_id = 'run-abc'") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row["tenant_id"] == "tenant-xyz"
            assert row["project_id"] == "proj-123"
            assert row["status"] == "queued"
            job_id = row["id"]

    # Test worker claiming job
    worker = SQLiteWorker(db_path=db_path, worker_id="test-worker")
    claimed = await worker._claim_next_job()
    assert claimed is not None
    assert claimed["run_id"] == "run-abc"

    # Verify status changed to running
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT status, locked_by FROM job_queue WHERE id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
            assert row["status"] == "running"
            assert row["locked_by"] == "test-worker"

    # Finish job
    await worker._finish_job(job_id, status="completed")
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT status FROM job_queue WHERE id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
            assert row["status"] == "completed"

