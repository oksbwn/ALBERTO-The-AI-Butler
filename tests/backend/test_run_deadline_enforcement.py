import asyncio
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import select
from alberto.db.base import SessionLocal
from alberto.models import Run, Thread, Workflow
from alberto.services.runs import RunService


@pytest.mark.asyncio
async def test_run_to_completion_deadline_enforcement():
    tenant_id = "tenant-deadline-1"
    project_id = "proj-deadline-1"
    run_service = RunService()

    async with SessionLocal() as session:
        wf = Workflow(
            tenant_id=tenant_id,
            project_id=project_id,
            name="slow-wf",
            executable={"nodes": [{"id": "n1", "type": "agent"}]},
        )
        session.add(wf)
        await session.flush()

        th = Thread(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=wf.id,
            lg_thread_id=f"{tenant_id}:th-deadline",
        )
        session.add(th)
        await session.flush()

        run = Run(
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=wf.id,
            thread_id=th.id,
            status="queued",
            input={"messages": [{"role": "user", "content": "hello"}]},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id

    # Simulate slow graph execution that exceeds wall-clock deadline
    class HangingGraph:
        async def astream(self, *args, **kwargs):
            # Hang longer than the timeout
            await asyncio.sleep(2.0)
            yield (), "messages", {"content": "late"}

        async def aget_state(self, *args, **kwargs):
            return MagicMock(values={})

    with patch("alberto.services.runs.compile_workflow", return_value=HangingGraph()):
        with patch("alberto.services.runs.RUN_WALL_CLOCK_TIMEOUT_SECONDS", 0.1):
            result = await run_service.run_to_completion(
                run_id=run_id,
                tenant_id=tenant_id,
                project_id=project_id,
            )

    assert result["status"] == "error"
    assert "timeout" in str(result["error"]).lower()
    assert result.get("termination_reason") == "wall_clock_timeout"

    # Verify Run in database has termination_reason and status
    async with SessionLocal() as session:
        r = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one()
        assert r.status == "error"
        assert r.termination_reason == "wall_clock_timeout"
