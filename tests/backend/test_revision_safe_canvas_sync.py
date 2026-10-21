"""Regression tests for P0.3 - Revision-Safe AI and Canvas Synchronization."""

import pytest
from alberto.db.base import SessionLocal
from alberto.models import Project, Tenant, Workflow
from alberto.schemas.automation_manager import ApprovalRequestIn
from alberto.services.automation_manager import AutomationManagerService
from alberto.services.workflows import WorkflowService


@pytest.fixture
async def setup_sync_test():
    async with SessionLocal() as s:
        tenant = Tenant(name="T-Sync-Test")
        s.add(tenant)
        await s.commit()
        await s.refresh(tenant)

        proj = Project(tenant_id=tenant.id, name="P-Sync-Test", slug="p-sync-test")
        s.add(proj)
        await s.commit()
        await s.refresh(proj)

        wf = await WorkflowService.create(
            s,
            tenant.id,
            proj.id,
            name="Original Canvas Pipeline",
            executable={
                "nodes": [
                    {"id": "entry", "type": "start"},
                    {"id": "n1", "type": "agent", "config": {"name": "InitialAgent"}},
                    {"id": "end", "type": "end"},
                ],
                "edges": [
                    {"source": "entry", "target": "n1"},
                    {"source": "n1", "target": "end"},
                ],
            },
            canvas={
                "nodes": [
                    {"id": "entry", "position": {"x": 0, "y": 0}},
                    {"id": "n1", "position": {"x": 100, "y": 200}},
                    {"id": "end", "position": {"x": 300, "y": 200}},
                ]
            },
        )
        return tenant, proj, wf


@pytest.mark.asyncio
async def test_concurrent_canvas_edit_invalidates_stale_approval(setup_sync_test):
    """If user edits workflow in Canvas, approving an earlier AI proposal must be rejected."""
    tenant, proj, wf = setup_sync_test
    async with SessionLocal() as s:
        # 1. Start AI session proposing modification based on initial revision
        auth_session = await AutomationManagerService.create_session(
            session=s,
            tenant_id=tenant.id,
            project_id=proj.id,
            user_id="test_user",
            requirement=f"Optimize workflow {wf.id} to add logging",
        )
        # Bind saved_wf_id so proposal tracks base workflow
        auth_session.proposal = {"workflow_id": wf.id}
        await s.commit()

        # Generate proposal
        step = await AutomationManagerService.process_message(
            s,
            tenant.id,
            proj.id,
            auth_session.id,
            message="Add logging to workflow and optimize pipeline",
        )
        assert step.action in ("plan", "propose")
        assert step.proposal is not None
        assert step.proposal.base_workflow_revision == wf.active_version

        # 2. Simulate concurrent user editing in Canvas, advancing active_version
        user_canvas = {"nodes": [{"id": "entry", "position": {"x": 50, "y": 50}}]}
        user_exec = {
            "nodes": [
                {"id": "entry", "type": "start"},
                {"id": "n1", "type": "agent", "config": {"name": "UserEditedAgent"}},
                {"id": "end", "type": "end"},
            ],
            "edges": [{"source": "entry", "target": "n1"}, {"source": "n1", "target": "end"}],
        }
        wf_db = await s.get(Workflow, wf.id)
        assert wf_db is not None
        await WorkflowService.save_canvas(s, wf_db, user_canvas, user_exec)
        assert (wf_db.active_version or 1) > (step.proposal.base_workflow_revision or 0)

        # 3. User attempts to approve the earlier proposal
        with pytest.raises(ValueError, match="Conflict: Workflow .* was modified concurrently in Canvas"):
            await AutomationManagerService.approve_and_activate(
                s,
                tenant.id,
                proj.id,
                auth_session.id,
                user_context={"user_id": "test_user"},
                req=ApprovalRequestIn(revision=auth_session.revision, create_agents=False, activate=True),
            )


@pytest.mark.asyncio
async def test_ai_reconciliation_updates_to_latest_canvas_revision(setup_sync_test):
    """Re-processing after Canvas edits updates proposal base revision and allows approval."""
    tenant, proj, wf = setup_sync_test
    async with SessionLocal() as s:
        auth_session = await AutomationManagerService.create_session(
            session=s,
            tenant_id=tenant.id,
            project_id=proj.id,
            user_id="test_user",
            requirement=f"Optimize workflow {wf.id}",
        )
        auth_session.proposal = {"workflow_id": wf.id}
        await s.commit()

        # Step 1 proposal
        await AutomationManagerService.process_message(
            s, tenant.id, proj.id, auth_session.id, message="First proposal draft"
        )

        # User saves on Canvas
        wf_db = await s.get(Workflow, wf.id)
        assert wf_db is not None
        await WorkflowService.save_canvas(s, wf_db, {"nodes": []}, wf.executable)
        new_canvas_ver = wf_db.active_version

        # AI session re-runs turn, reconciling with new canvas revision
        step2 = await AutomationManagerService.process_message(
            s,
            tenant.id,
            proj.id,
            auth_session.id,
            message="Reconcile with Canvas and finalize pipeline",
            expected_revision=auth_session.revision,
        )
        assert step2.proposal is not None
        assert step2.proposal.base_workflow_revision == new_canvas_ver

        # Now approval succeeds
        appr = await AutomationManagerService.approve_and_activate(
            s,
            tenant.id,
            proj.id,
            auth_session.id,
            user_context={"user_id": "test_user"},
            req=ApprovalRequestIn(revision=auth_session.revision, create_agents=False, activate=True),
        )
        assert appr.status == "approved"
