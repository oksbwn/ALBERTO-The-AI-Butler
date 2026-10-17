import asyncio
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock
from alberto.worker import SQLiteWorker
from alberto.queue import SqliteJobQueue


@pytest.mark.asyncio
async def test_heartbeat_followed_by_successful_acknowledgement(tmp_path):
    """Heartbeat updates locked_at while preserving lease_token, allowing successful finish."""
    db_path = str(tmp_path / "queue.sqlite")
    queue = SqliteJobQueue(db_path=db_path)
    await queue.enqueue("run-hb-ack", "t1", "p1")

    worker = SQLiteWorker(db_path=db_path, worker_id="worker-hb", poll_interval=0.1)
    claimed = await worker._claim_next_job()
    assert claimed is not None
    job_id = claimed["id"]
    lease_token = claimed["lease_token"]
    assert lease_token is not None

    # Trigger heartbeat
    hb_stop = asyncio.Event()
    hb_task = asyncio.create_task(worker._heartbeat(claimed, hb_stop))
    await asyncio.sleep(0.05)
    hb_stop.set()
    await hb_task

    # Verify locked_at changed in DB, but lease_token remained unchanged
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT locked_at, lease_token, status FROM job_queue WHERE id = ?", (job_id,)).fetchone()
        assert row["status"] == "running"
        assert row["lease_token"] == lease_token

    # Acknowledgement using lease_token must succeed even though locked_at changed!
    finished = await worker._finish_job(job_id, "completed", lease_token=lease_token)
    assert finished is True

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, lease_token FROM job_queue WHERE id = ?", (job_id,)).fetchone()
        assert row["status"] == "completed"
        assert row["lease_token"] is None

    await queue.close()


@pytest.mark.asyncio
async def test_lease_expiry_and_reclamation_fences_old_worker(tmp_path):
    """When a job is reclaimed by worker-2 (new lease_token), old worker-1 cannot acknowledge."""
    db_path = str(tmp_path / "queue.sqlite")
    queue = SqliteJobQueue(db_path=db_path)
    await queue.enqueue("run-fence", "t1", "p1")

    worker1 = SQLiteWorker(db_path=db_path, worker_id="worker-1", poll_interval=0.1)
    claimed1 = await worker1._claim_next_job()
    assert claimed1 is not None
    job_id = claimed1["id"]
    old_token = claimed1["lease_token"]

    # Simulate worker-1 crash: lease expires
    stale_time = (datetime.utcnow() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE job_queue SET locked_at = ? WHERE id = ?", (stale_time, job_id))

    # Worker-2 recovers the job (idempotent)
    worker2 = SQLiteWorker(db_path=db_path, worker_id="worker-2", poll_interval=0.1)
    with patch.object(worker2, "_is_safe_to_retry", new=AsyncMock(return_value=True)):
        recovered = await worker2.recover_abandoned_jobs(lease_timeout_seconds=30)
        assert recovered == 1

    # Clear retry backoff delay so worker-2 can claim immediately
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE job_queue SET available_at = datetime('now', '-1 second') WHERE id = ?", (job_id,))

    # Worker-2 claims the reclaimed job
    claimed2 = await worker2._claim_next_job()
    assert claimed2 is not None
    new_token = claimed2["lease_token"]
    assert new_token != old_token

    # Zombie worker-1 wakes up and attempts to finish the job with its old lease_token
    finished1 = await worker1._finish_job(job_id, "completed", lease_token=old_token)
    assert finished1 is False  # Must be fenced out!

    # Worker-2 finishes with current lease_token
    finished2 = await worker2._finish_job(job_id, "completed", lease_token=new_token)
    assert finished2 is True

    await queue.close()


@pytest.mark.asyncio
async def test_concurrent_claims(tmp_path):
    """Multiple workers attempting to claim the same queued job simultaneously; only one succeeds."""
    db_path = str(tmp_path / "queue.sqlite")
    queue = SqliteJobQueue(db_path=db_path)
    await queue.enqueue("run-concurrent", "t1", "p1")

    workers = [
        SQLiteWorker(db_path=db_path, worker_id=f"worker-{i}", poll_interval=0.1)
        for i in range(5)
    ]

    claims = await asyncio.gather(*(w._claim_next_job() for w in workers))
    successful_claims = [c for c in claims if c is not None]
    assert len(successful_claims) == 1
    assert successful_claims[0]["lease_token"] is not None

    await queue.close()


@pytest.mark.asyncio
async def test_worker_lease_recovery_idempotent_job(tmp_path):
    db_path = str(tmp_path / "queue.sqlite")
    queue = SqliteJobQueue(db_path=db_path)

    await queue.enqueue("run-1", "t1", "p1")

    worker1 = SQLiteWorker(db_path=db_path, worker_id="worker-1", poll_interval=0.1)
    claimed = await worker1._claim_next_job()
    assert claimed is not None
    job_id = claimed["id"]

    stale_time = (datetime.utcnow() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE job_queue SET locked_at = ? WHERE id = ?", (stale_time, job_id))

    worker2 = SQLiteWorker(db_path=db_path, worker_id="worker-2", poll_interval=0.1)
    with patch.object(worker2, "_is_safe_to_retry", new=AsyncMock(return_value=True)):
        recovered = await worker2.recover_abandoned_jobs(lease_timeout_seconds=30)
        assert recovered == 1

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, attempts, available_at FROM job_queue WHERE id = ?", (job_id,)).fetchone()
        assert row["status"] == "queued"
        assert row["available_at"] is not None

    await queue.close()


@pytest.mark.asyncio
async def test_worker_lease_recovery_uncertain_side_effects(tmp_path):
    db_path = str(tmp_path / "queue.sqlite")
    queue = SqliteJobQueue(db_path=db_path)

    await queue.enqueue("run-uncertain", "t1", "p1")

    worker1 = SQLiteWorker(db_path=db_path, worker_id="worker-1", poll_interval=0.1)
    claimed = await worker1._claim_next_job()
    assert claimed is not None
    job_id = claimed["id"]

    stale_time = (datetime.utcnow() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE job_queue SET locked_at = ? WHERE id = ?", (stale_time, job_id))

    worker2 = SQLiteWorker(db_path=db_path, worker_id="worker-2", poll_interval=0.1)
    with patch("alberto.services.runs.RunService._mark_unfinished", new=AsyncMock()):
        recovered = await worker2.recover_abandoned_jobs(lease_timeout_seconds=30)
        assert recovered == 1

    # Uncertain job must be marked failed
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status, error FROM job_queue WHERE id = ?", (job_id,)).fetchone()
        assert row["status"] == "failed"
        assert "uncertain side-effecting outcome" in row["error"]

    await queue.close()
