"""Regression tests for P0.1 - Durable Autonomous Repair Protection."""

import pytest
from alberto.db.base import SessionLocal
from alberto.models import Project, Run, Tenant, Workflow, WorkflowRepairAttempt
from alberto.services.automation_manager import AutomationManagerService
from alberto.services.workflows import WorkflowService


@pytest.fixture
async def setup_repair_test():
    async with SessionLocal() as s:
        tenant = Tenant(name="T-Durable-Repair")
        s.add(tenant)
        await s.commit()
        await s.refresh(tenant)

        proj = Project(tenant_id=tenant.id, name="P-Durable-Repair", slug="p-durable-repair")
        s.add(proj)
        await s.commit()
        await s.refresh(proj)

        wf = await WorkflowService.create(
            s,
            tenant.id,
            proj.id,
            name="Repair Test Pipeline",
            executable={"nodes": [{"id": "s", "type": "start"}]},
        )
        return tenant, proj, wf


@pytest.mark.asyncio
async def test_repair_counter_survives_restart_and_enforces_limit(setup_repair_test):
    """Repair counter must persist in SQLite and enforce 2-attempt limit across simulated restarts."""
    tenant, proj, wf = setup_repair_test
    async with SessionLocal() as s:
        run = Run(
            tenant_id=tenant.id,
            project_id=proj.id,
            workflow_id=wf.id,
            thread_id="t-durable-1",
            status="error",
            error="RuntimeError: Connection timed out to node s",
        )
        s.add(run)
        await s.commit()
        await s.refresh(run)

    # Attempt 1: Durably records attempt 1 in SQLite
    d1 = await AutomationManagerService.on_run_failure(
        tenant_id=tenant.id,
        project_id=proj.id,
        workflow_id=wf.id,
        run_id=run.id,
        error=run.error,
    )
    assert d1 is not None

    async with SessionLocal() as s:
        attempts_rec = await AutomationManagerService.get_repair_attempt_count(
            s, wf.id, "some_fake_fingerprint"
        )
        # Verify durable SQLite row exists
        from sqlalchemy import select
        rows = (await s.execute(select(WorkflowRepairAttempt).where(WorkflowRepairAttempt.workflow_id == wf.id))).scalars().all()
        assert len(rows) == 1
        assert rows[0].attempt_count == 1
        assert rows[0].repair_status in ("repaired", "attempted", "blocked")

    # Simulate restart by clearing any class-level in-memory state
    AutomationManagerService._auto_repair_attempts.clear()

    # Attempt 2: Reads SQLite attempt_count=1, advances to attempt_count=2
    d2 = await AutomationManagerService.on_run_failure(
        tenant_id=tenant.id,
        project_id=proj.id,
        workflow_id=wf.id,
        run_id=run.id,
        error=run.error,
    )
    assert d2 is not None

    # Simulate another restart
    AutomationManagerService._auto_repair_attempts.clear()

    # Attempt 3: Reads SQLite attempt_count=2, halts auto-repair to prevent infinite loop
    d3 = await AutomationManagerService.on_run_failure(
        tenant_id=tenant.id,
        project_id=proj.id,
        workflow_id=wf.id,
        run_id=run.id,
        error=run.error,
    )
    assert d3 is None

    # Verify SQLite row preserved count 2
    async with SessionLocal() as s:
        rows = (await s.execute(select(WorkflowRepairAttempt).where(WorkflowRepairAttempt.workflow_id == wf.id))).scalars().all()
        assert len(rows) == 1
        assert rows[0].attempt_count == 2


@pytest.mark.asyncio
async def test_stale_revision_self_repair_rejected(setup_repair_test):
    """Self-repair must recheck workflow active version and reject stale revision."""
    tenant, proj, wf = setup_repair_test
    async with SessionLocal() as s:
        current_wf = await WorkflowService.get(s, tenant.id, wf.id)
        current_rev = current_wf.active_version or 1

        # Attempt safe repair specifying a stale expected_revision
        with pytest.raises(ValueError, match="Stale-revision"):
            await AutomationManagerService.apply_safe_self_repair(
                session=s,
                tenant_id=tenant.id,
                project_id=proj.id,
                workflow_id=wf.id,
                expected_revision=current_rev + 99,
            )


@pytest.mark.asyncio
async def test_privilege_expanding_self_repair_rejected(setup_repair_test):
    """Safe self-repair must reject silent addition of tools without human approval."""
    tenant, proj, wf = setup_repair_test
    async with SessionLocal() as s:
        # Patch self_correct_workflow to simulate malicious/speculative privilege addition
        orig_fn = AutomationManagerService.self_correct_workflow
        try:
            AutomationManagerService.self_correct_workflow = lambda ex, errs, caps: (
                {"nodes": [{"id": "n1", "type": "agent", "config": {"tools": ["drop_database_all"]}}], "edges": []},
                True,
                [],
            )
            with pytest.raises(ValueError, match="Security Invariant Violation"):
                await AutomationManagerService.apply_safe_self_repair(
                    session=s,
                    tenant_id=tenant.id,
                    project_id=proj.id,
                    workflow_id=wf.id,
                    require_approval_for_privileges=True,
                )
        finally:
            AutomationManagerService.self_correct_workflow = orig_fn
