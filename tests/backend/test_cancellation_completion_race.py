import asyncio
import pytest
from datetime import datetime
from unittest.mock import MagicMock
from sqlalchemy import select
from alberto.db.base import SessionLocal
from alberto.models import Run, Thread, Trace, Workflow
from alberto.services.runs import RunService
from alberto.tracing.tracer import ForgeTracer


async def _create_test_run(tenant_id: str, project_id: str, status: str = "running") -> str:
    async with SessionLocal() as session:
        wf = Workflow(
            tenant_id=tenant_id,
            project_id=project_id,
            name="test-wf",
            executable={"nodes": [{"id": "n1", "type": "start"}]},
        )
        session.add(wf)
        await session.flush()

        th = Thread(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=wf.id,
            lg_thread_id=f"{tenant_id}:th-{status}",
        )
        session.add(th)
        await session.flush()

        run = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=wf.id,
            thread_id=th.id,
            status=status,
            started_at=datetime.utcnow(),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


@pytest.mark.asyncio
async def test_cancellation_winning_race_against_finalize():
    """Barrier test: cancellation commits first; racing finalize must not overwrite 'canceled'."""
    tenant_id = "tenant-barrier-win"
    project_id = "proj-barrier-win"
    run_service = RunService()
    run_id = await _create_test_run(tenant_id, project_id)

    barrier_cancel = asyncio.Event()
    barrier_finalize = asyncio.Event()

    async def do_cancel():
        await barrier_cancel.wait()
        res = await run_service.cancel_run(run_id=run_id, tenant_id=tenant_id)
        assert res["ok"] is True
        assert res["status"] == "canceled"
        barrier_finalize.set()

    async def do_finalize():
        async with SessionLocal() as session:
            r = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
            tracer = ForgeTracer()
            snapshot = MagicMock(values={"answer": "completion result"})
            barrier_cancel.set()
            await barrier_finalize.wait()
            # Race _finalize
            await run_service._finalize(session, r, tracer, snapshot, status="done")

    await asyncio.gather(do_cancel(), do_finalize())

    async with SessionLocal() as session:
        r = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
        assert r.status == "canceled"
        assert r.termination_reason == "canceled"

        # Verify Trace matches committed DB outcome
        trace = (await session.execute(select(Trace).where(Trace.run_id == run_id))).scalars().first()
        assert trace is not None
        assert trace.status == "canceled"


@pytest.mark.asyncio
async def test_completion_winning_race_against_cancellation():
    """Barrier test: finalize commits first; racing cancellation must return already done."""
    tenant_id = "tenant-done-win"
    project_id = "proj-done-win"
    run_service = RunService()
    run_id = await _create_test_run(tenant_id, project_id)

    barrier_finalize = asyncio.Event()
    barrier_cancel = asyncio.Event()
    cancel_result = {}

    async def do_finalize():
        await barrier_finalize.wait()
        async with SessionLocal() as session:
            r = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
            tracer = ForgeTracer()
            snapshot = MagicMock(values={"answer": "winning completion"})
            await run_service._finalize(session, r, tracer, snapshot, status="done")
        barrier_cancel.set()

    async def do_cancel():
        barrier_finalize.set()
        await barrier_cancel.wait()
        res = await run_service.cancel_run(run_id=run_id, tenant_id=tenant_id)
        cancel_result.update(res)

    await asyncio.gather(do_finalize(), do_cancel())

    # Cancellation must not overwrite completion
    assert cancel_result["ok"] is False
    assert cancel_result["status"] == "done"

    async with SessionLocal() as session:
        r = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
        assert r.status == "done"
        assert r.termination_reason == "completed"


@pytest.mark.asyncio
async def test_error_racing_cancellation():
    """Barrier test: error finalize does not overwrite cancellation."""
    tenant_id = "tenant-err-race"
    project_id = "proj-err-race"
    run_service = RunService()
    run_id = await _create_test_run(tenant_id, project_id)

    # Cancel first
    res = await run_service.cancel_run(run_id=run_id, tenant_id=tenant_id)
    assert res["ok"] is True

    # Error finalize arrives late
    async with SessionLocal() as session:
        r = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
        tracer = ForgeTracer()
        await run_service._finalize_error(session, r, tracer, error="fatal boom")

    async with SessionLocal() as session:
        r = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
        assert r.status == "canceled"
        assert r.termination_reason == "canceled"


@pytest.mark.asyncio
async def test_repeated_cancellation_idempotency():
    """Repeated cancellations must succeed idempotently without error."""
    tenant_id = "tenant-idempotent-cancel"
    project_id = "proj-idempotent-cancel"
    run_service = RunService()
    run_id = await _create_test_run(tenant_id, project_id)

    res1 = await run_service.cancel_run(run_id=run_id, tenant_id=tenant_id)
    assert res1["ok"] is True
    assert res1["status"] == "canceled"

    # Second cancellation: idempotent no-op returns ok=False, status=canceled
    res2 = await run_service.cancel_run(run_id=run_id, tenant_id=tenant_id)
    assert res2["ok"] is False
    assert res2["status"] == "canceled"
    assert "already canceled" in res2.get("detail", "")
