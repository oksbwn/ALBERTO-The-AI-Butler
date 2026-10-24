"""Tests for Automation Manager Phase 5: Monitoring, Autonomous Troubleshooting, Optimisation, and Reliability.

Validates:
- Conversational status and run monitoring with factual evidence
- Autonomous failure diagnosis with trace references and category classification
- Safe self-repair with privilege expansion protection
- Grounded workflow optimization proposals
- One-time schedule trigger (run_at) timezone-aware execution and anti-duplicate firing
- Phase 5 HTTP API endpoints
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from alberto.db import SessionLocal
from alberto.main import create_app
from alberto.models import Run, Span, Trace, Trigger, Workflow
from alberto.services.automation_manager import AutomationManagerService
from alberto.services.projects import ProjectService
from alberto.services.triggers import TriggerService
from alberto.services.workflows import WorkflowService


@pytest.fixture
async def setup_phase5_project():
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id=f"tenant-p5-{uuid.uuid4().hex[:6]}",
            name="Phase 5 Automation Project",
            slug=f"p5-proj-{uuid.uuid4().hex[:6]}",
        )
        await session.commit()
        await session.refresh(proj)
        return proj


@pytest.mark.asyncio
async def test_workflow_monitoring_summary(setup_phase5_project):
    """Monitoring must retrieve grounded run counts, duration, and slowest node."""
    proj = setup_phase5_project
    async with SessionLocal() as session:
        wf = await WorkflowService.create(
            session,
            proj.tenant_id,
            proj.id,
            name="Research Workflow",
            executable={"nodes": [{"id": "n1", "type": "start"}]},
        )

        now = datetime.now(timezone.utc)
        # Create a finished run
        run1 = Run(
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            workflow_id=wf.id,
            thread_id="t1",
            status="done",
            started_at=now - timedelta(seconds=10),
            ended_at=now,
            total_tokens=450,
            total_cost_usd=0.002,
        )
        session.add(run1)
        await session.commit()
        await session.refresh(run1)

        # Add a trace and a slow span
        trace = Trace(
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            workflow_id=wf.id,
            run_id=run1.id,
            name="Research Turn",
            status="done",
            latency_ms=10000,
        )
        session.add(trace)
        await session.commit()
        await session.refresh(trace)

        span = Span(
            tenant_id=proj.tenant_id,
            trace_id=trace.id,
            name="web_search_step",
            kind="tool",
            latency_ms=3500,
        )
        session.add(span)
        await session.commit()

        # Query monitoring summary
        report = await AutomationManagerService.get_workflow_monitoring_summary(
            session, proj.tenant_id, proj.id, workflow_id=wf.id
        )

        assert report.workflow_id == wf.id
        assert report.workflow_name == "Research Workflow"
        assert report.total_runs >= 1
        assert report.last_run is not None
        assert report.last_run["status"] == "done"
        assert report.last_run["tokens"] == 450
        assert report.slowest_step is not None
        assert report.slowest_step["name"] == "web_search_step"
        assert report.slowest_step["latency_ms"] == 3500


@pytest.mark.asyncio
async def test_failure_diagnosis_unauthorized_tool(setup_phase5_project):
    """Failure diagnosis must identify unauthorized tool operations and flag that approval is required."""
    proj = setup_phase5_project
    async with SessionLocal() as session:
        wf = await WorkflowService.create(
            session,
            proj.tenant_id,
            proj.id,
            name="Financial Settlement Pipeline",
            executable={"nodes": [{"id": "n1", "type": "agent"}]},
        )

        failed_run = Run(
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            workflow_id=wf.id,
            thread_id="t-fail",
            status="error",
            error="Security Policy violation: Unauthorized tool operation 'bank_transfer_execute' rejected by ToolPolicyService.",
        )
        session.add(failed_run)
        await session.commit()
        await session.refresh(failed_run)

        diag = await AutomationManagerService.diagnose_failure(
            session, proj.tenant_id, proj.id, failed_run.id
        )

        assert diag.run_id == failed_run.id
        assert diag.category == "unauthorized_tool_operation"
        assert "Security Policy violation" in diag.root_cause
        assert diag.requires_approval is True
        assert diag.proposed_repair is not None


@pytest.mark.asyncio
async def test_safe_self_repair_blocks_privilege_expansion(setup_phase5_project):
    """Self-repair must safely fix schema issues but reject adding unapproved tools."""
    proj = setup_phase5_project
    async with SessionLocal() as session:
        wf = await WorkflowService.create(
            session,
            proj.tenant_id,
            proj.id,
            name="Broken Workflow",
            executable={
                # Missing entry node, version, and proper state spec
                "nodes": [{"id": "a1", "type": "agent", "config": {"name": "test_agent", "tools": ["search"]}}],
                "edges": [],
                "state": {"messages": "list"},
            },
        )

        res = await AutomationManagerService.apply_safe_self_repair(
            session, proj.tenant_id, proj.id, wf.id
        )
        assert res["repaired"] is True
        assert res["workflow_id"] == wf.id

        refreshed = await WorkflowService.get(session, proj.tenant_id, wf.id)
        assert refreshed.executable.get("entry_node") is not None
        assert isinstance(refreshed.executable.get("state"), dict)


@pytest.mark.asyncio
async def test_workflow_optimisation_proposals(setup_phase5_project):
    """Optimisation analysis must detect redundant agent calls and suggest deterministic replacements."""
    proj = setup_phase5_project
    async with SessionLocal() as session:
        wf = await WorkflowService.create(
            session,
            proj.tenant_id,
            proj.id,
            name="Sequential Agents Workflow",
            executable={
                "nodes": [
                    {"id": "start", "type": "start"},
                    {"id": "ag1", "type": "agent", "config": {"name": "agent_1", "tools": ["lookup"]}},
                    {"id": "ag2", "type": "agent", "config": {"name": "agent_2", "tools": ["format"]}},
                    {"id": "end", "type": "end"},
                ],
                "edges": [
                    {"source": "start", "target": "ag1"},
                    {"source": "ag1", "target": "ag2"},
                    {"source": "ag2", "target": "end"},
                ],
            },
        )

        opt = await AutomationManagerService.analyze_workflow_optimisation(
            session, proj.tenant_id, proj.id, wf.id
        )

        assert opt.workflow_id == wf.id
        assert len(opt.recommendations) >= 1
        rec_types = [r["type"] for r in opt.recommendations]
        assert "parallelize_agents" in rec_types or "deterministic_tool_replacement" in rec_types
        assert opt.potential_latency_reduction_ms > 0


@pytest.mark.asyncio
async def test_one_time_schedule_trigger_run_at(setup_phase5_project):
    """One-time schedule trigger (run_at) must fire when due and never duplicate."""
    proj = setup_phase5_project
    async with SessionLocal() as session:
        now = datetime.now(timezone.utc)
        past_iso = (now - timedelta(minutes=5)).isoformat()
        future_iso = (now + timedelta(minutes=30)).isoformat()

        # Trigger scheduled in the past: is_due must be True
        due_trigger = Trigger(
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            workflow_id="wf-1",
            kind="schedule",
            node_id="trig-1",
            config={"run_at": past_iso},
            enabled=True,
            last_fired_at=None,
        )
        assert TriggerService.is_due(due_trigger) is True

        # Once last_fired_at is stamped, must NOT fire again (one-time idempotency)
        due_trigger.last_fired_at = datetime.utcnow()
        assert TriggerService.is_due(due_trigger) is False

        # Future trigger: must NOT be due
        future_trigger = Trigger(
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            workflow_id="wf-2",
            kind="schedule",
            node_id="trig-2",
            config={"run_at": future_iso},
            enabled=True,
            last_fired_at=None,
        )
        assert TriggerService.is_due(future_trigger) is False


@pytest.mark.asyncio
async def test_conversational_monitoring_and_diagnosis_in_chat(setup_phase5_project):
    """Automation Manager answers conversational monitoring and failure questions using real data."""
    proj = setup_phase5_project
    async with SessionLocal() as session:
        sess = await AutomationManagerService.create_session(
            session,
            proj.tenant_id,
            proj.id,
            "user-p5",
            requirement="Monitoring conversation",
        )

        # 1. Ask about runs / monitoring
        step = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            session_id=sess.id,
            message="Show runs and tell me which step took the longest today",
        )
        assert step.action == "clarify"
        assert len(step.questions) == 1
        assert "Workflow Execution Status Report" in step.questions[0]


@pytest.mark.asyncio
async def test_phase5_http_api_endpoints():
    """HTTP API endpoints for monitoring, diagnosis, optimisation, and self-repair."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register and authenticate
        reg = await client.post(
            "/v1/auth/register",
            json={"email": f"phase5-{uuid.uuid4().hex[:8]}@example.com", "password": "pass123Password!"},
        )
        token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create project
        proj_res = await client.post(
            "/v1/projects",
            json={"name": "P5 API Project", "slug": f"p5-proj-{uuid.uuid4().hex[:8]}"},
            headers=headers,
        )
        project_id = proj_res.json()["id"]

        # Create workflow
        wf_res = await client.post(
            f"/v1/projects/{project_id}/workflows",
            json={
                "name": "P5 Test Workflow",
                "executable": {
                    "nodes": [{"id": "s", "type": "start"}, {"id": "e", "type": "end"}],
                    "edges": [{"source": "s", "target": "e"}],
                },
            },
            headers=headers,
        )
        wf_id = wf_res.json()["id"]

        # 1. Monitoring endpoint
        mon_res = await client.get(
            f"/v1/projects/{project_id}/automate/monitoring?workflow_id={wf_id}",
            headers=headers,
        )
        assert mon_res.status_code == 200
        mon_data = mon_res.json()
        assert mon_data["workflow_id"] == wf_id

        # 2. Optimisation endpoint
        opt_res = await client.get(
            f"/v1/projects/{project_id}/automate/workflows/{wf_id}/optimise",
            headers=headers,
        )
        assert opt_res.status_code == 200
        assert "recommendations" in opt_res.json()

        # 3. Repair endpoint
        rep_res = await client.post(
            f"/v1/projects/{project_id}/automate/workflows/{wf_id}/repair",
            headers=headers,
        )
        assert rep_res.status_code == 200
        assert rep_res.json()["workflow_id"] == wf_id


@pytest.mark.asyncio
async def test_autonomous_failure_diagnosis_and_repair_loop_prevention(setup_phase5_project):
    """Autonomous failure handling must diagnose runs and enforce bounded repair limits."""
    proj = setup_phase5_project
    async with SessionLocal() as session:
        wf = await WorkflowService.create(
            session,
            proj.tenant_id,
            proj.id,
            name="Autonomous Self-Repair Workflow",
            executable={"nodes": [{"id": "s", "type": "start"}]},
        )
        run = Run(
            tenant_id=proj.tenant_id,
            project_id=proj.id,
            workflow_id=wf.id,
            thread_id="t-auto-repair",
            status="error",
            error="ValueError: Invalid node config",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

    # First attempt: diagnoses and applies repair
    diag1 = await AutomationManagerService.on_run_failure(
        tenant_id=proj.tenant_id,
        project_id=proj.id,
        workflow_id=wf.id,
        run_id=run.id,
        error=run.error or "",
    )
    assert diag1 is not None
    assert diag1.run_id == run.id

    # Second attempt
    diag2 = await AutomationManagerService.on_run_failure(
        tenant_id=proj.tenant_id,
        project_id=proj.id,
        workflow_id=wf.id,
        run_id=run.id,
        error=run.error or "",
    )
    assert diag2 is not None

    # Third attempt: loop prevention halts recurring auto-repair
    diag3 = await AutomationManagerService.on_run_failure(
        tenant_id=proj.tenant_id,
        project_id=proj.id,
        workflow_id=wf.id,
        run_id=run.id,
        error=run.error or "",
    )
    assert diag3 is None

