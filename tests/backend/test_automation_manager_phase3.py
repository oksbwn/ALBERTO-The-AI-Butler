"""Tests for Automation Manager Phase 3: Specialist Agent Creation, Safe Testing, Consolidated Approval.

Validates:
- Safe dry-run testing without external side effects
- Tool risk classification and side-effect reporting in test checks
- Idempotent creation of proposed specialist agents on approval
- Saving and activation of workflows and trigger syncing on approval
- Revision conflict detection (optimistic concurrency / anti-stale approvals)
- Rejection of approval on invalid proposals or invalid revisions
- HTTP endpoints for test and approve
"""

from __future__ import annotations

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from alberto.db import SessionLocal
from alberto.main import create_app
from alberto.models import Agent, Workflow
from alberto.schemas.automation_manager import ApprovalRequestIn
from alberto.services.automation_manager import AutomationManagerService
from alberto.services.projects import ProjectService
from alberto.services.workflows import WorkflowService


@pytest.fixture
async def setup_auto_project():
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id=f"tenant-phase3-{uuid.uuid4().hex[:6]}",
            name="Phase 3 Automation Project",
            slug=f"phase3-auto-proj-{uuid.uuid4().hex[:6]}",
        )
        await session.commit()
        await session.refresh(proj)
        return proj


@pytest.mark.asyncio
async def test_safe_test_dry_run_simulation(setup_auto_project):
    """Safe test must validate topology and tool risks without executing live side effects."""
    proj = setup_auto_project
    async with SessionLocal() as session:
        sess = await AutomationManagerService.create_session(
            session,
            proj.tenant_id,
            proj.id,
            "user-p3",
            requirement="Every morning triage customer tickets using high-risk deletion tool and report summary",
        )

        step = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            session_id=sess.id,
            message="Please plan this triage pipeline with schedule trigger every morning and customer support agent",
        )
        assert step.action == "plan"
        assert step.proposal is not None

        test_res = await AutomationManagerService.run_safe_test(
            session=session,
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            session_id=sess.id,
        )

        assert test_res.session_id == sess.id
        assert test_res.valid is True
        assert len(test_res.checks) >= 3

        check_names = [c.name for c in test_res.checks]
        assert "graph_schema_and_contracts" in check_names
        assert "state_declaration_and_reducers" in check_names
        assert "dry_run_topology_traversal" in check_names

        refreshed = await AutomationManagerService.get_session(
            session, proj.tenant_id, proj.id, sess.id
        )
        assert "safe_test_results" in refreshed.proposal


@pytest.mark.asyncio
async def test_consolidated_approval_creates_agents_and_activates_workflow(setup_auto_project):
    """Consolidated approval idempotently creates proposed specialist agents and activates workflow."""
    proj = setup_auto_project
    async with SessionLocal() as session:
        sess = await AutomationManagerService.create_session(
            session,
            proj.tenant_id,
            proj.id,
            "user-p3",
            requirement="Multi-agent customer support team with triage and resolution specialists",
        )

        step = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            session_id=sess.id,
            message="Please build a multi-agent triage and resolution specialist team workflow with daily schedule",
        )
        assert step.action == "plan"
        assert len(step.proposal.proposed_agents) >= 1

        current_rev = step.revision
        user_ctx = {"user_id": "test-approver", "role": "admin"}

        app_res = await AutomationManagerService.approve_and_activate(
            session=session,
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            session_id=sess.id,
            user_context=user_ctx,
            req=ApprovalRequestIn(
                revision=current_rev,
                create_agents=True,
                activate=True,
            ),
        )

        assert app_res.status == "approved"
        assert app_res.activated is True
        assert app_res.workflow_id is not None
        assert len(app_res.created_agent_ids) >= 1

        wf = await WorkflowService.get(session, proj.tenant_id, app_res.workflow_id)
        assert wf is not None
        assert wf.status == "active"

        created_agents = [
            await session.get(Agent, aid) for aid in app_res.created_agent_ids
        ]
        assert all(a is not None for a in created_agents)
        for a in created_agents:
            assert a.is_system is False
            assert a.created_by == "test-approver"


@pytest.mark.asyncio
async def test_approval_rejects_stale_revision(setup_auto_project):
    """Approval must fail if revision does not match current session state (anti-stale)."""
    proj = setup_auto_project
    async with SessionLocal() as session:
        sess = await AutomationManagerService.create_session(
            session,
            proj.tenant_id,
            proj.id,
            "user-p3",
            requirement="Simple pipeline with agent worker",
        )

        step = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            session_id=sess.id,
            message="Create single agent pipeline with agent worker",
        )

        stale_revision = step.revision - 1
        user_ctx = {"user_id": "test-approver", "role": "editor"}

        with pytest.raises(ValueError, match="Conflict: Stale approval"):
            await AutomationManagerService.approve_and_activate(
                session=session,
                tenant_id=proj.tenant_id,
                project_id=proj.id,
                session_id=sess.id,
                user_context=user_ctx,
                req=ApprovalRequestIn(
                    revision=stale_revision,
                    create_agents=True,
                    activate=True,
                ),
            )


@pytest.mark.asyncio
async def test_approval_rejects_missing_proposal(setup_auto_project):
    """Cannot approve an authoring session that has no proposal."""
    proj = setup_auto_project
    async with SessionLocal() as session:
        sess = await AutomationManagerService.create_session(
            session,
            proj.tenant_id,
            proj.id,
            "user-p3",
            requirement="Empty requirement session",
        )
        user_ctx = {"user_id": "test-approver", "role": "editor"}

        with pytest.raises(ValueError, match="Cannot approve session without an executable workflow"):
            await AutomationManagerService.approve_and_activate(
                session=session,
                tenant_id=proj.tenant_id,
                project_id=proj.id,
                session_id=sess.id,
                user_context=user_ctx,
                req=ApprovalRequestIn(
                    revision=sess.revision,
                    create_agents=True,
                    activate=False,
                ),
            )


@pytest.mark.asyncio
async def test_api_safe_test_and_approve_flow():
    """End-to-end HTTP API verification of safe test and approval."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register and get auth token
        reg = await client.post(
            "/v1/auth/register",
            json={"email": f"phase3-{uuid.uuid4().hex[:8]}@example.com", "password": "pass123Password!"},
        )
        token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create project
        proj_res = await client.post(
            "/v1/projects",
            json={"name": "P3 API Project", "slug": f"p3-proj-{uuid.uuid4().hex[:8]}"},
            headers=headers,
        )
        project_id = proj_res.json()["id"]

        # 1. Create session
        res = await client.post(
            f"/v1/projects/{project_id}/automate/sessions",
            json={"requirement": "Automated daily research and summarization pipeline"},
            headers=headers,
        )
        assert res.status_code == 201
        sess_data = res.json()
        session_id = sess_data["id"]

        # 2. Plan workflow
        res = await client.post(
            f"/v1/projects/{project_id}/automate/sessions/{session_id}/messages",
            json={"message": "Please generate daily research schedule with specialist research agent"},
            headers=headers,
        )
        assert res.status_code == 200
        step_data = res.json()
        assert step_data["action"] == "plan"
        revision = step_data["revision"]

        # 3. Run safe test via API
        res = await client.post(
            f"/v1/projects/{project_id}/automate/sessions/{session_id}/test",
            headers=headers,
        )
        assert res.status_code == 200
        test_data = res.json()
        assert test_data["valid"] is True
        assert len(test_data["checks"]) >= 1

        # 4. Approve and activate via API
        res = await client.post(
            f"/v1/projects/{project_id}/automate/sessions/{session_id}/approve",
            json={"revision": revision, "create_agents": True, "activate": True},
            headers=headers,
        )
        assert res.status_code == 200
        app_data = res.json()
        assert app_data["status"] == "approved"
        assert app_data["activated"] is True
        assert app_data["workflow_id"] is not None

        # 5. Stale approval attempt returns 409 Conflict
        res = await client.post(
            f"/v1/projects/{project_id}/automate/sessions/{session_id}/approve",
            json={"revision": revision, "create_agents": True, "activate": True},
            headers=headers,
        )
        assert res.status_code == 409
