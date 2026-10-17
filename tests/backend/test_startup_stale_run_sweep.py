import sqlite3
import pytest
from datetime import datetime, timedelta
from sqlalchemy import select
from alberto.config import settings
from alberto.db.base import SessionLocal
from alberto.models import Run, Thread, Workflow
from alberto.queue import SqliteJobQueue
from alberto.services.runs import RunService


@pytest.mark.asyncio
async def test_startup_stale_run_sweep_distinguishes_abandoned_and_active(tmp_path):
    tenant_id = "tenant-sweep-2"
    project_id = "proj-sweep-2"
    run_service = RunService()

    now = datetime.utcnow()
    stale_time = now - timedelta(seconds=600)
    fresh_time = now - timedelta(seconds=10)

    # Use a dedicated queue db
    queue_db = str(tmp_path / "queue.sqlite")
    settings.queue_db_path = queue_db
    queue = SqliteJobQueue(db_path=queue_db)
    await queue._ensure_table()

    async with SessionLocal() as session:
        wf = Workflow(
            tenant_id=tenant_id,
            project_id=project_id,
            name="sweep-wf",
            executable={"nodes": [{"id": "n1", "type": "start"}]},
        )
        session.add(wf)
        await session.flush()

        th = Thread(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=wf.id,
            lg_thread_id=f"{tenant_id}:th-sweep-2",
        )
        session.add(th)
        await session.flush()

        # 1. Truly abandoned running run (no queue lease, old)
        run_abandoned = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=wf.id,
            thread_id=th.id,
            status="running",
            started_at=stale_time,
        )
        # 2. Active running run (has active unexpired worker lease in queue.sqlite)
        run_active = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=wf.id,
            thread_id=th.id,
            status="running",
            started_at=stale_time,  # started earlier, but still active via worker lease
        )
        # 3. Legitimately queued run waiting in queue.sqlite
        run_queued_legit = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=wf.id,
            thread_id=th.id,
            status="queued",
            created_at=stale_time,
        )
        # 4. Paused HITL run awaiting human decision
        run_hitl = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=wf.id,
            thread_id=th.id,
            status="interrupted",
            started_at=stale_time,
            ended_at=now - timedelta(hours=1),  # paused 1 hour ago (within 24h approval deadline)
        )
        # 5. Completed run
        run_done = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=wf.id,
            thread_id=th.id,
            status="done",
            started_at=stale_time,
            ended_at=fresh_time,
        )

        session.add_all([run_abandoned, run_active, run_queued_legit, run_hitl, run_done])
        await session.commit()
        await session.refresh(run_abandoned)
        await session.refresh(run_active)
        await session.refresh(run_queued_legit)
        await session.refresh(run_hitl)
        await session.refresh(run_done)

        abandoned_id = run_abandoned.id
        active_id = run_active.id
        queued_id = run_queued_legit.id
        hitl_id = run_hitl.id
        done_id = run_done.id

    # Populate active queue entries
    with sqlite3.connect(queue_db) as conn:
        # Active lease for run_active
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO job_queue (run_id, tenant_id, status, locked_at, locked_by, lease_token) VALUES (?, ?, 'running', ?, 'worker-live', 'token-live')",
            (active_id, tenant_id, now_str),
        )
        # Queued job for run_queued_legit
        conn.execute(
            "INSERT INTO job_queue (run_id, tenant_id, status) VALUES (?, ?, 'queued')",
            (queued_id, tenant_id),
        )
        conn.commit()

    # Execute startup reap with running_max_age_s=300, queued_max_age_s=300
    reaped = await run_service.reap_stale_runs(queued_max_age_s=300, running_max_age_s=300)
    assert reaped >= 1

    # Verify outcomes
    async with SessionLocal() as session:
        r_abandoned = (await session.execute(select(Run).where(Run.id == abandoned_id))).scalar_one()
        assert r_abandoned.status == "error"
        assert r_abandoned.termination_reason == "stale_running_reaped"

        r_active = (await session.execute(select(Run).where(Run.id == active_id))).scalar_one()
        assert r_active.status == "running"  # Preserved! Active worker lease protected it

        r_queued = (await session.execute(select(Run).where(Run.id == queued_id))).scalar_one()
        assert r_queued.status == "queued"  # Preserved! Legitimate queued work protected

        r_hitl = (await session.execute(select(Run).where(Run.id == hitl_id))).scalar_one()
        assert r_hitl.status == "interrupted"  # Preserved! HITL paused approval state protected

        r_done = (await session.execute(select(Run).where(Run.id == done_id))).scalar_one()
        assert r_done.status == "done"  # Preserved!

    # Idempotent re-run
    reaped_again = await run_service.reap_stale_runs(queued_max_age_s=300, running_max_age_s=300)
    assert reaped_again == 0

    await queue.close()
