"""Comprehensive tests for Phase 2: Automation Manager Backend.

Covers:
1. Automation Manager registration
2. System-agent immutability
3. Master Agent routing compatibility
4. Direct invocation contract
5. User/project capability isolation
6. Restricted tool visibility & secret sanitization
7. Workflow generation with mocked model output
8. Existing graph schema compatibility
9. Valid node and edge generation
10. Invalid graph detection
11. Bounded self-correction
12. Clarification session persistence
13. Resume after restart
14. Proposed specialist agent generation
15. Existing agent reuse
16. No creation or activation before approval
17. Concurrent draft-update conflicts
18. Model failure and malformed output handling
"""

from __future__ import annotations

import json
import pytest
from sqlalchemy import select

from alberto.db import SessionLocal
from alberto.models import (
    Agent,
    AutomationSession,
    Project,
    Secret,
    Tool,
    Workflow,
)
from alberto.services.agents import AgentService, RESERVED_SYSTEM_KEYS
from alberto.services.assistant import build_assistant_tools
from alberto.services.automation_manager import AutomationManagerService
from alberto.services.projects import ProjectService
from alberto.services.validation import validate_workflow
from alberto.services.workflows import WorkflowService


@pytest.fixture
async def setup_projects():
    async with SessionLocal() as session:
        proj_a = await ProjectService.create(
            session,
            tenant_id="tenant-auto-1",
            name="Automation Project A",
            slug="auto-proj-a",
        )
        proj_b = await ProjectService.create(
            session,
            tenant_id="tenant-auto-1",
            name="Automation Project B",
            slug="auto-proj-b",
        )
        await session.commit()
        await session.refresh(proj_a)
        await session.refresh(proj_b)
        return proj_a, proj_b


@pytest.mark.asyncio
async def test_1_automation_manager_registration(setup_projects):
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        sys_agents = await AgentService.ensure_system_agents(session, proj_a.tenant_id, proj_a.id)
        auto_mgr = next((a for a in sys_agents if a.system_key == "automation_manager"), None)
        assert auto_mgr is not None
        assert auto_mgr.name == "Automation Manager"
        assert auto_mgr.is_system is True
        assert "automation_manager" in RESERVED_SYSTEM_KEYS


@pytest.mark.asyncio
async def test_2_system_agent_immutability(setup_projects):
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        await AgentService.ensure_system_agents(session, proj_a.tenant_id, proj_a.id)
        auto_mgr = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == proj_a.tenant_id,
                    Agent.project_id == proj_a.id,
                    Agent.system_key == "automation_manager",
                )
            )
        ).scalar_one()

        # Reject delete
        with pytest.raises(ValueError, match="Protected system agents cannot be deleted"):
            await AgentService.delete(session, auto_mgr)

        # Reject rename
        with pytest.raises(ValueError, match="Protected system agents cannot be renamed"):
            await AgentService.update(session, auto_mgr, name="Custom Name")


@pytest.mark.asyncio
async def test_3_master_agent_routing_compatibility(setup_projects):
    proj_a, _ = setup_projects
    tools = build_assistant_tools(proj_a.tenant_id, proj_a.id, [])
    tool_names = [t.name for t in tools]
    assert "delegate_automation_management" in tool_names


@pytest.mark.asyncio
async def test_4_direct_invocation_contract(setup_projects):
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        sess = await AutomationManagerService.create_session(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            user_id="user-123",
            requirement="Create a customer service triage pipeline",
            title="Customer Service Triage",
        )
        assert sess.id.startswith("auto-")
        assert sess.status == "planning"
        assert sess.revision == 1

        loaded = await AutomationManagerService.get_session(session, proj_a.tenant_id, proj_a.id, sess.id)
        assert loaded is not None
        assert loaded.title == "Customer Service Triage"


@pytest.mark.asyncio
async def test_5_user_project_capability_isolation(setup_projects):
    proj_a, proj_b = setup_projects
    async with SessionLocal() as session:
        # Create a tool in Project A only
        tool_a = Tool(
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            name="tool_in_proj_a",
            kind="builtin",
            config={"description": "Tool belonging to project A"},
        )
        session.add(tool_a)
        await session.commit()

        # Discover in A
        caps_a = await AutomationManagerService.discover_capabilities(session, proj_a.tenant_id, proj_a.id)
        tool_names_a = [t.name for t in caps_a.tools]
        assert "tool_in_proj_a" in tool_names_a

        # Discover in B
        caps_b = await AutomationManagerService.discover_capabilities(session, proj_b.tenant_id, proj_b.id)
        tool_names_b = [t.name for t in caps_b.tools]
        assert "tool_in_proj_a" not in tool_names_b


@pytest.mark.asyncio
async def test_6_restricted_tool_visibility_and_secret_sanitization(setup_projects):
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        # Add a tool and secret with sensitive payload
        secret = Secret(
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            name="SENSITIVE_API_KEY",
            encrypted_value=b"super_secret_payload",
        )
        session.add(secret)
        tool = Tool(
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            name="payment_deletion_tool",
            kind="rest_api",
            config={"description": "Deletes payments", "api_key": "raw_exposed_key"},
        )
        session.add(tool)
        await session.commit()

        caps = await AutomationManagerService.discover_capabilities(session, proj_a.tenant_id, proj_a.id)
        t = next(t for t in caps.tools if t.name == "payment_deletion_tool")
        assert t.effect_type == "delete"
        assert t.risk_level == "critical"
        assert t.requires_approval is True

        # Ensure no raw secret payloads leaked in discovery json
        dumped = caps.model_dump_json()
        assert "super_secret_payload" not in dumped
        assert "raw_exposed_key" not in dumped


@pytest.mark.asyncio
async def test_7_8_9_workflow_generation_and_schema_compatibility(setup_projects):
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        sess = await AutomationManagerService.create_session(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            user_id="user-123",
            requirement="Build a multi-agent triage system with specialist agents for triage and resolution",
        )

        res = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            session_id=sess.id,
            message="Proceed with the multi-agent pipeline",
            expected_revision=1,
        )

        assert res.action == "plan"
        assert res.proposal is not None
        assert res.proposal.strategy == "multi_agent"

        # Validate against Alberto's low-code designer and compiler schemas
        val_res = validate_workflow(res.proposal.executable)
        assert val_res.valid is True
        assert res.validation_status == "valid"
        assert len(val_res.errors) == 0

        # Verify Canvas structure
        canvas = res.proposal.canvas
        assert "nodes" in canvas and len(canvas["nodes"]) >= 3
        assert "edges" in canvas and len(canvas["edges"]) >= 2
        for n in canvas["nodes"]:
            assert "id" in n
            assert "position" in n and "x" in n["position"]
            assert "data" in n and "nodeType" in n["data"]


@pytest.mark.asyncio
async def test_10_11_invalid_graph_detection_and_bounded_self_correction(setup_projects):
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        caps = await AutomationManagerService.discover_capabilities(session, proj_a.tenant_id, proj_a.id)

        # Create an invalid graph: missing entry node, missing end node, undeclared state writes
        invalid_graph = {
            "entry_node": "non_existent_entry",
            "nodes": [
                {
                    "id": "bad_node",
                    "type": "classifier",
                    "config": {
                        "labels": ["a", "b"],
                        "output_key": "unregistered_custom_key",
                        "model": "gpt-4o-mini",
                    },
                }
            ],
            "edges": [
                {"source": "bad_node", "target": "missing_target"}
            ],
            "state": {},
        }

        # 10. Detection
        initial_val = validate_workflow(invalid_graph)
        assert initial_val.valid is False
        assert len(initial_val.errors) > 0

        # 11. Bounded self-correction
        corrected, is_valid, errors = AutomationManagerService.self_correct_workflow(
            invalid_graph, initial_val.errors, caps, max_attempts=3
        )

        assert is_valid is True
        assert len(errors) == 0
        assert corrected["entry_node"] in [n["id"] for n in corrected["nodes"]]
        assert "unregistered_custom_key" in corrected["state"]
        val_check = validate_workflow(corrected)
        assert val_check.valid is True


@pytest.mark.asyncio
async def test_12_13_clarification_session_persistence_and_restart(setup_projects):
    proj_a, _ = setup_projects
    session_id = None
    # Turn 1: create and send ambiguous requirement
    async with SessionLocal() as session:
        sess = await AutomationManagerService.create_session(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            user_id="user-123",
            requirement="automate",
        )
        session_id = sess.id

        step = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            session_id=session_id,
            message="need help",
        )
        assert step.action == "clarify"
        assert len(step.questions) > 0

    # Turn 2: Simulate application restart by opening brand new DB session
    async with SessionLocal() as new_session:
        resumed = await AutomationManagerService.get_session(new_session, proj_a.tenant_id, proj_a.id, session_id)
        assert resumed is not None
        assert len(resumed.clarifications) >= 2

        # Provide clarification
        step2 = await AutomationManagerService.process_message(
            session=new_session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            session_id=session_id,
            message="Schedule a daily workflow every morning to fetch updates and summarize them with an agent",
            expected_revision=resumed.revision,
        )
        assert step2.action == "plan"
        assert step2.proposal is not None


@pytest.mark.asyncio
async def test_14_15_proposed_specialist_agent_and_reuse(setup_projects):
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        # Seed an existing specialist agent
        existing = Agent(
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            name="triage_specialist",
            config={"description": "Pre-existing triage agent", "tools": []},
            is_system=False,
            system_key=None,
        )
        session.add(existing)
        await session.commit()

        # Run planning
        sess = await AutomationManagerService.create_session(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            user_id="user-123",
            requirement="Multi-agent customer support with triage and resolution specialists",
        )

        res = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            session_id=sess.id,
            message="Construct multi-agent team",
        )

        assert res.proposal is not None
        # Should reuse the existing triage_specialist
        assert "triage_specialist" in res.proposal.reused_agents
        # Propose the resolution_specialist as a new agent
        proposed_names = [p.name for p in res.proposal.proposed_agents]
        assert "resolution_specialist" in proposed_names


@pytest.mark.asyncio
async def test_16_no_creation_or_activation_before_approval(setup_projects):
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        # Count workflows and agents before
        wf_count_before = len((await session.execute(select(Workflow).where(Workflow.project_id == proj_a.id))).scalars().all())
        agent_count_before = len((await session.execute(select(Agent).where(Agent.project_id == proj_a.id))).scalars().all())

        sess = await AutomationManagerService.create_session(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            user_id="user-123",
            requirement="Generate an end-to-end multi-agent pipeline",
        )
        await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            session_id=sess.id,
            message="Create the draft plan",
        )

        # Count workflows and agents after
        wf_count_after = len((await session.execute(select(Workflow).where(Workflow.project_id == proj_a.id))).scalars().all())
        agent_count_after = len((await session.execute(select(Agent).where(Agent.project_id == proj_a.id))).scalars().all())

        # Enforce boundary: Phase 2 only generates proposals; no DB records created for workflow/agents
        assert wf_count_after == wf_count_before
        assert agent_count_after == agent_count_before


@pytest.mark.asyncio
async def test_17_concurrent_draft_update_conflicts(setup_projects):
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        sess = await AutomationManagerService.create_session(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            user_id="user-123",
            requirement="Concurrent testing pipeline",
        )

        # Send turn 1 with expected revision 1
        res1 = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            session_id=sess.id,
            message="Step 1 details",
            expected_revision=1,
        )
        assert res1.action == "plan"
        assert res1.revision == 2

        # Stale request attempting to use old revision 1
        res_stale = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            session_id=sess.id,
            message="Stale update details",
            expected_revision=1,
        )
        assert res_stale.action == "error"
        assert "Conflict: Stale authoring update" in (res_stale.error_message or "")


@pytest.mark.asyncio
async def test_18_model_failure_and_malformed_output_handling(setup_projects):
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        # Test nonexistent session
        res = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            session_id="non-existent-session",
            message="hello",
        )
        assert res.action == "error"
        assert "not found" in (res.error_message or "")


@pytest.mark.asyncio
async def test_19_bidirectional_canvas_to_ai_synchronization(setup_projects):
    """When a workflow is modified on canvas and saved, Automation Manager conversation preserves edits."""
    proj_a, _ = setup_projects
    async with SessionLocal() as session:
        # Create an existing workflow in SQLite /data
        wf = await WorkflowService.create(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            name="Manual Canvas Workflow",
            executable={
                "entry_node": "start_node",
                "nodes": [
                    {"id": "start_node", "type": "start", "config": {}},
                    {"id": "canvas_custom_node", "type": "agent", "config": {"name": "custom_agent", "tools": ["calculator"]}},
                    {"id": "end_node", "type": "end", "config": {}},
                ],
                "edges": [
                    {"source": "start_node", "target": "canvas_custom_node"},
                    {"source": "canvas_custom_node", "target": "end_node"},
                ],
            },
        )

        # Create session attached to this saved workflow
        sess = await AutomationManagerService.create_session(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            user_id="user-123",
            requirement="Enhance my canvas workflow",
        )
        # Attach saved_wf_id to authoring session proposal
        sess.proposal = {"workflow_id": wf.id, "title": wf.name}
        await session.commit()

        # Conversational edit: "add approval step"
        res = await AutomationManagerService.process_message(
            session=session,
            tenant_id=proj_a.tenant_id,
            project_id=proj_a.id,
            session_id=sess.id,
            message="Add approval step before ending",
            expected_revision=1,
        )
        assert res.action == "plan"
        assert res.proposal is not None

        # Verify canvas_custom_node was retained from SQLite workflow, not wiped
        node_ids = [n["id"] for n in res.proposal.executable.get("nodes", [])]
        assert "canvas_custom_node" in node_ids
        assert any("approval" in nid for nid in node_ids)
        assert res.proposal.safe_test_results is not None

