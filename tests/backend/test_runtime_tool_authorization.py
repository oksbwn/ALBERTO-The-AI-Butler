"""Security regression test suite for P0.4 - Actual Runtime Tool Authorization.

Verifies deterministic policy enforcement at execution time across:
1. Unassociated agent invokes a tool: DENIED.
2. Unauthorized workflow tool invocation: DENIED.
3. Tool call from another project: DENIED.
4. Direct API bypass attempt: DENIED.
5. Master agent delegation without permission: DENIED.
6. Retry after revoked permission: DENIED.
7. HITL resume without approval: DENIED.
8. Properly associated and approved tool invocation: ALLOWED.
9. Tool Manager-mediated execution preserves policy checks.
"""

import pytest
from alberto.db.base import SessionLocal
from alberto.models import Agent, Project, Tenant, Tool
from alberto.services.tool_manager import ToolManagerService
from alberto.services.tool_policy import ToolPolicyService
from alberto.services.tools import ToolService


@pytest.fixture
async def setup_auth_env():
    async with SessionLocal() as s:
        tenant = Tenant(name="T-Sec-Runtime")
        s.add(tenant)
        await s.commit()
        await s.refresh(tenant)

        proj_a = Project(tenant_id=tenant.id, name="Project-Alpha", slug="project-alpha")
        proj_b = Project(tenant_id=tenant.id, name="Project-Beta", slug="project-beta")
        s.add_all([proj_a, proj_b])
        await s.commit()
        await s.refresh(proj_a)
        await s.refresh(proj_b)

        # Create low-risk tool in Project Alpha
        tool_alpha = await ToolService.create(
            s,
            tenant.id,
            proj_a.id,
            name="query_analytics",
            kind="builtin",
            config={"description": "Query telemetry data", "effect": "read", "risk": "low"},
        )
        # Create high-risk tool requiring approval in Project Alpha
        tool_critical = await ToolService.create(
            s,
            tenant.id,
            proj_a.id,
            name="delete_database_cluster",
            kind="builtin",
            config={"description": "Drop database cluster", "effect": "delete", "risk": "critical", "requires_approval": True},
        )
        # Create tool in Project Beta
        tool_beta = await ToolService.create(
            s,
            tenant.id,
            proj_b.id,
            name="beta_internal_tool",
            kind="builtin",
            config={"description": "Beta tool", "effect": "read", "risk": "low"},
        )

        return tenant, proj_a, proj_b, tool_alpha, tool_critical, tool_beta


@pytest.mark.asyncio
async def test_1_unassociated_agent_invocation_denied(setup_auth_env):
    """Unassociated subagent invoking an external tool must be DENIED."""
    tenant, proj_a, _, tool_alpha, _, _ = setup_auth_env
    async with SessionLocal() as s:
        decision = await ToolPolicyService.evaluate_execution(
            tenant_id=tenant.id,
            project_id=proj_a.id,
            tool_id=tool_alpha.id,
            caller_type="subagent",
            caller_id="unassociated_worker",
            subagent_config={"tools": []},  # No association
            session=s,
        )
        assert decision.allowed is False
        assert "not explicitly associated" in decision.reason


@pytest.mark.asyncio
async def test_2_unauthorized_workflow_tool_invocation_denied(setup_auth_env):
    """Workflow node invoking an unassociated tool must be DENIED."""
    tenant, proj_a, _, tool_alpha, _, _ = setup_auth_env
    async with SessionLocal() as s:
        decision = await ToolPolicyService.evaluate_execution(
            tenant_id=tenant.id,
            project_id=proj_a.id,
            tool_id=tool_alpha.id,
            caller_type="workflow",
            caller_id="unauthorized_wf",
            workflow_def={"nodes": []},  # Tool not defined in workflow nodes
            session=s,
        )
        assert decision.allowed is False
        assert "not explicitly defined in workflow" in decision.reason


@pytest.mark.asyncio
async def test_3_tool_call_from_another_project_denied(setup_auth_env):
    """Attempting to invoke a tool belonging to another project must be DENIED."""
    tenant, proj_a, proj_b, _, _, tool_beta = setup_auth_env
    async with SessionLocal() as s:
        decision = await ToolPolicyService.evaluate_execution(
            tenant_id=tenant.id,
            project_id=proj_a.id,  # Caller is in Alpha
            tool_id=tool_beta.id,   # Tool is in Beta
            caller_type="tool_manager",
            caller_id="assistant",
            session=s,
        )
        assert decision.allowed is False
        assert "not registered in this project" in decision.reason


@pytest.mark.asyncio
async def test_4_direct_api_bypass_attempt_denied(setup_auth_env):
    """Direct unauthenticated tool call attempting to bypass gateway must be DENIED."""
    tenant, proj_a, _, tool_alpha, _, _ = setup_auth_env
    async with SessionLocal() as s:
        decision = await ToolPolicyService.evaluate_execution(
            tenant_id=tenant.id,
            project_id=proj_a.id,
            tool_id=tool_alpha.id,
            caller_type="direct",
            session=s,
        )
        assert decision.allowed is False
        assert "Unauthenticated direct tool execution is prohibited" in decision.reason


@pytest.mark.asyncio
async def test_5_master_agent_direct_execution_denied(setup_auth_env):
    """Master agent attempting direct external tool execution without Tool Manager must be DENIED."""
    tenant, proj_a, _, tool_alpha, _, _ = setup_auth_env
    async with SessionLocal() as s:
        decision = await ToolPolicyService.evaluate_execution(
            tenant_id=tenant.id,
            project_id=proj_a.id,
            tool_id=tool_alpha.id,
            caller_type="master_agent",
            caller_id="alberto_core",
            session=s,
        )
        assert decision.allowed is False
        assert "must be delegated through Tool Manager" in decision.reason


@pytest.mark.asyncio
async def test_6_retry_after_revoked_permission_denied(setup_auth_env):
    """If tool permission was revoked from agent, subsequent execution attempt must be DENIED."""
    tenant, proj_a, _, tool_alpha, _, _ = setup_auth_env
    async with SessionLocal() as s:
        # Agent config originally had permission, but caller revokes it
        agent_cfg_revoked = {"tools": ["some_other_tool"]}
        decision = await ToolPolicyService.evaluate_execution(
            tenant_id=tenant.id,
            project_id=proj_a.id,
            tool_id=tool_alpha.id,
            caller_type="subagent",
            caller_id="revoked_worker",
            subagent_config=agent_cfg_revoked,
            session=s,
        )
        assert decision.allowed is False
        assert "not explicitly associated" in decision.reason


@pytest.mark.asyncio
async def test_7_hitl_resume_without_approval_denied(setup_auth_env):
    """Critical/delete tool execution without human-in-the-loop approval must be DENIED."""
    tenant, proj_a, _, _, tool_critical, _ = setup_auth_env
    async with SessionLocal() as s:
        decision = await ToolPolicyService.evaluate_execution(
            tenant_id=tenant.id,
            project_id=proj_a.id,
            tool_id=tool_critical.id,
            caller_type="subagent",
            caller_id="dba_agent",
            subagent_config={"tools": [tool_critical.id]},
            execution_context={"approved": False, "approval_id": None},
            session=s,
        )
        assert decision.allowed is False
        assert decision.requires_approval is True


@pytest.mark.asyncio
async def test_8_properly_associated_and_approved_invocation_allowed(setup_auth_env):
    """Properly associated tool meeting policy requirements must be ALLOWED."""
    tenant, proj_a, _, tool_alpha, _, _ = setup_auth_env
    async with SessionLocal() as s:
        decision = await ToolPolicyService.evaluate_execution(
            tenant_id=tenant.id,
            project_id=proj_a.id,
            tool_id=tool_alpha.id,
            caller_type="subagent",
            caller_id="analytics_specialist",
            subagent_config={"tools": [tool_alpha.id]},
            session=s,
        )
        assert decision.allowed is True
        assert decision.tool_id == tool_alpha.id


@pytest.mark.asyncio
async def test_9_tool_manager_delegation_preserves_policy_checks(setup_auth_env):
    """Tool Manager execution gateway preserves full policy boundaries."""
    tenant, proj_a, _, _, tool_critical, _ = setup_auth_env
    # Attempting to execute critical tool through ToolManager without approval request
    result = await ToolManagerService.execute_delegated_tool(
        tenant_id=tenant.id,
        project_id=proj_a.id,
        tool_id_or_capability=tool_critical.name,
        parameters={"cluster_id": "prod-1"},
    )
    assert result["ok"] is False
    assert result["requires_approval"] is True
    assert result["approval_id"] is not None
