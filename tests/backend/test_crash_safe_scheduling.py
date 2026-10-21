"""Regression tests for P0.2 - Crash-Safe One-Time Scheduling."""

from datetime import datetime, timedelta, timezone
import pytest
from alberto.db.base import SessionLocal
from alberto.models import Project, Run, Tenant, Trigger, Workflow
from alberto.services.dispatch import run_due_schedules
from alberto.services.runs import RunService
from alberto.services.triggers import TriggerService
from alberto.services.workflows import WorkflowService


@pytest.fixture
async def setup_schedule_test():
    async with SessionLocal() as s:
        tenant = Tenant(name="T-Crash-Schedule")
        s.add(tenant)
        await s.commit()
        await s.refresh(tenant)

        proj = Project(tenant_id=tenant.id, name="P-Crash-Schedule", slug="p-crash-schedule")
        s.add(proj)
        await s.commit()
        await s.refresh(proj)

        wf = await WorkflowService.create(
            s,
            tenant.id,
            proj.id,
            name="Scheduled Pipeline",
            executable={"nodes": [{"id": "s", "type": "start"}, {"id": "e", "type": "end"}]},
        )
        return tenant, proj, wf


@pytest.mark.asyncio
async def test_onetime_schedule_atomic_claim_creates_durable_run(setup_schedule_test):
    """Claiming a one-time trigger must atomically create the Run record in SQLite."""
    tenant, proj, wf = setup_schedule_test
    past_due = (datetime.utcnow() - timedelta(minutes=5)).isoformat() + "Z"

    async with SessionLocal() as s:
        trig = Trigger(
            tenant_id=tenant.id,
            project_id=proj.id,
            workflow_id=wf.id,
            node_id="trig-onetime-1",
            kind="schedule",
            config={"run_at": past_due},
            enabled=True,
        )
        s.add(trig)
        await s.commit()
        await s.refresh(trig)
        trig_id = trig.id

    run_service = RunService()

    # Fire due schedules
    fired = await run_due_schedules(run_service)
    assert fired == 1

    # Verify trigger state and durable run record in SQLite
    async with SessionLocal() as s:
        t = await s.get(Trigger, trig_id)
        assert t is not None
        assert t.enabled is False
        assert t.last_fired_at is not None
        run_id = (t.meta or {}).get("one_time_run_id")
        assert run_id is not None

        # Verify run exists in SQLite database
        run = await s.get(Run, run_id)
        assert run is not None
        assert run.workflow_id == wf.id
        assert run.source == "schedule"


@pytest.mark.asyncio
async def test_repeated_polling_does_not_double_fire(setup_schedule_test):
    """Subsequent scheduler ticks must skip already-claimed one-time schedules."""
    tenant, proj, wf = setup_schedule_test
    past_due = (datetime.utcnow() - timedelta(minutes=10)).isoformat() + "Z"

    async with SessionLocal() as s:
        trig = Trigger(
            tenant_id=tenant.id,
            project_id=proj.id,
            workflow_id=wf.id,
            node_id="trig-onetime-2",
            kind="schedule",
            config={"run_at": past_due},
            enabled=True,
        )
        s.add(trig)
        await s.commit()
        await s.refresh(trig)

    run_service = RunService()

    # Tick 1: fires
    f1 = await run_due_schedules(run_service)
    assert f1 == 1

    # Tick 2: already claimed, fires 0
    f2 = await run_due_schedules(run_service)
    assert f2 == 0

    # Tick 3: fires 0
    f3 = await run_due_schedules(run_service)
    assert f3 == 0


@pytest.mark.asyncio
async def test_timezone_aware_run_at_evaluation(setup_schedule_test):
    """TriggerService.is_due must correctly parse and compare timezone offsets."""
    tenant, proj, wf = setup_schedule_test
    
    # 1 hour in future in UTC+5:30
    future_tz = (datetime.now(timezone.utc) + timedelta(hours=1)).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    ).isoformat()

    trig_future = Trigger(
        tenant_id=tenant.id,
        project_id=proj.id,
        workflow_id=wf.id,
        node_id="trig-tz-future",
        kind="schedule",
        config={"run_at": future_tz},
        enabled=True,
    )
    assert TriggerService.is_due(trig_future) is False

    # 1 hour in past in UTC-8:00
    past_tz = (datetime.now(timezone.utc) - timedelta(hours=1)).astimezone(
        timezone(timedelta(hours=-8))
    ).isoformat()

    trig_past = Trigger(
        tenant_id=tenant.id,
        project_id=proj.id,
        workflow_id=wf.id,
        node_id="trig-tz-past",
        kind="schedule",
        config={"run_at": past_tz},
        enabled=True,
    )
    assert TriggerService.is_due(trig_past) is True
