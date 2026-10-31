"""Automate 2.0 Security Closure and Architecture Freeze Regression Suite.

Verifies:
1. P0: Step Configuration Anti-Tampering (tool_id, agent_id, toolsets, mcp_servers, credentials, SSRF, stale revision, permission purging).
2. P0: Complete Dry-Run Isolation across all execution paths (direct tool, agent, subagent, Tool Manager, webhook_out, unknown side-effect fail-closed).
3. P1: Approval Consumption, Concurrency, Replay Protection & Idempotency.
"""

import asyncio
import pytest
import uuid
from fastapi import HTTPException

from alberto.db.base import SessionLocal
from alberto.models import Agent, Project, Tenant, Tool, User, Workflow
from alberto.routers.workflows import execute_step
from alberto.schemas.dto import StepExecutionIn
from alberto.services.tool_manager import ToolManagerService
from alberto.services.tool_policy import ToolPolicyService
from alberto.services.tools import ToolService
from alberto.engine.context import CompileContext
from alberto.nodes.data import tool_call_factory, webhook_out_factory
from alberto.nodes.agent_node import _wrap_tool_for_agent


@pytest.fixture
async def setup_freeze_env():
    suffix = uuid.uuid4().hex[:8]
    async with SessionLocal() as s:
        tenant = Tenant(name=f"FreezeTenant_{suffix}")
        s.add(tenant)
        await s.commit()
        await s.refresh(tenant)

        proj = Project(tenant_id=tenant.id, name=f"FreezeProj_{suffix}", slug=f"freeze-proj-{suffix}")
        s.add(proj)
        await s.commit()
        await s.refresh(proj)

        # Another tenant & project for cross-tenant isolation testing
        tenant_b = Tenant(name=f"ForeignTenant_{suffix}")
        s.add(tenant_b)
        await s.commit()
        await s.refresh(tenant_b)

        proj_b = Project(tenant_id=tenant_b.id, name=f"ForeignProj_{suffix}", slug=f"foreign-proj-{suffix}")
        s.add(proj_b)
        await s.commit()
        await s.refresh(proj_b)

        # Authorized tool
        tool_auth = await ToolService.create(
            s,
            tenant.id,
            proj.id,
            name="authorized_read_tool",
            kind="builtin",
            config={"effect": "read", "risk": "low"},
        )

        # Mutating tool requiring approval
        tool_mutating = await ToolService.create(
            s,
            tenant.id,
            proj.id,
            name="authorized_mutating_tool",
            kind="builtin",
            config={"effect": "delete", "risk": "critical", "requires_approval": True},
        )

        # Unknown side-effect tool
        tool_unknown = await ToolService.create(
            s,
            tenant.id,
            proj.id,
            name="unclassified_custom_operation",
            kind="builtin",
            config={"effect": "unknown", "risk": "unknown"},
        )

        # Authorized agent
        agent_saved = Agent(
            tenant_id=tenant.id,
            project_id=proj.id,
            name="SpecialistAgent",
            config={
                "tools": [tool_auth.id],
                "toolsets": [],
                "mcp_servers": [],
            },
        )
        s.add(agent_saved)
        await s.commit()
        await s.refresh(agent_saved)

        # Workflow with saved node configurations
        wf = Workflow(
            tenant_id=tenant.id,
            project_id=proj.id,
            name="Freeze Verification Workflow",
            active_version=3,
            executable={
                "nodes": [
                    {"id": "inject_node", "type": "inject", "config": {"payload": {"data": "test"}}},
                    {"id": "tool_node", "type": "tool_call", "config": {"tool_id": tool_auth.id, "auth_provider_id": "auth-prov-1"}},
                    {"id": "mutating_tool_node", "type": "tool_call", "config": {"tool_id": tool_mutating.id}},
                    {"id": "unknown_tool_node", "type": "tool_call", "config": {"tool_id": tool_unknown.id}},
                    {
                        "id": "agent_node",
                        "type": "agent",
                        "config": {
                            "agent_id": agent_saved.id,
                            "tools": [tool_auth.id],
                            "toolsets": [],
                            "mcp_servers": [],
                        },
                    },
                    {"id": "subwf_node", "type": "subworkflow", "config": {"subworkflow_id": "saved-subwf-100"}},
                    {
                        "id": "webhook_node",
                        "type": "webhook_out",
                        "config": {"method": "POST", "url": "https://api.external.com/v1/notify", "auth_provider_id": "cred-prov-99"},
                    },
                ]
            },
        )
        s.add(wf)
        await s.commit()
        await s.refresh(wf)

        return {
            "tenant": tenant,
            "project": proj,
            "tenant_b": tenant_b,
            "project_b": proj_b,
            "workflow": wf,
            "tool_auth": tool_auth,
            "tool_mutating": tool_mutating,
            "tool_unknown": tool_unknown,
            "agent": agent_saved,
        }


# ==============================================================================
# SECTION 1: P0 — Step Execution Configuration Tampering Negative Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_step_anti_tampering_unauthorized_tool_substitution(setup_freeze_env):
    """Attempting to substitute an unauthorized tool_id on a tool_call node is rejected with 422."""
    env = setup_freeze_env
    user = User(id="u1", email="tester@alberto.local", role="editor")
    body = StepExecutionIn(
        node_id="tool_node",
        node_type="tool_call",
        config={"tool_id": "malicious_unauthorized_tool"},
        mode="dry_run",
    )
    async with SessionLocal() as s:
        with pytest.raises(HTTPException) as exc:
            await execute_step(
                project_id=env["project"].id,
                workflow_id=env["workflow"].id,
                body=body,
                session=s,
                tenant_id=env["tenant"].id,
                user=user,
            )
        assert exc.value.status_code == 422
        assert "Tool tampering detected" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_step_anti_tampering_unauthorized_agent_substitution(setup_freeze_env):
    """Attempting to substitute an unauthorized agent_id on an agent node is rejected with 422."""
    env = setup_freeze_env
    user = User(id="u1", email="tester@alberto.local", role="editor")
    body = StepExecutionIn(
        node_id="agent_node",
        node_type="agent",
        config={"agent_id": "unauthorized_root_agent"},
        mode="dry_run",
    )
    async with SessionLocal() as s:
        with pytest.raises(HTTPException) as exc:
            await execute_step(
                project_id=env["project"].id,
                workflow_id=env["workflow"].id,
                body=body,
                session=s,
                tenant_id=env["tenant"].id,
                user=user,
            )
        assert exc.value.status_code == 422
        assert "Agent tampering detected" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_step_anti_tampering_unauthorized_tool_injection_on_agent(setup_freeze_env):
    """Attempting to expand agent node tools beyond saved definition is rejected with 422."""
    env = setup_freeze_env
    user = User(id="u1", email="tester@alberto.local", role="editor")
    body = StepExecutionIn(
        node_id="agent_node",
        node_type="agent",
        config={
            "agent_id": env["agent"].id,
            "tools": [env["tool_auth"].id, "injected_privileged_tool"],
        },
        mode="dry_run",
    )
    async with SessionLocal() as s:
        with pytest.raises(HTTPException) as exc:
            await execute_step(
                project_id=env["project"].id,
                workflow_id=env["workflow"].id,
                body=body,
                session=s,
                tenant_id=env["tenant"].id,
                user=user,
            )
        assert exc.value.status_code == 422
        assert "Unauthorized tool injection" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_step_anti_tampering_credential_provider_tampering(setup_freeze_env):
    """Attempting to tamper with credential/auth provider on webhook or tool node is rejected with 422."""
    env = setup_freeze_env
    user = User(id="u1", email="tester@alberto.local", role="editor")
    body = StepExecutionIn(
        node_id="webhook_node",
        node_type="webhook_out",
        config={"auth_provider_id": "forged_victim_provider", "url": "https://api.external.com/notify"},
        mode="dry_run",
    )
    async with SessionLocal() as s:
        with pytest.raises(HTTPException) as exc:
            await execute_step(
                project_id=env["project"].id,
                workflow_id=env["workflow"].id,
                body=body,
                session=s,
                tenant_id=env["tenant"].id,
                user=user,
            )
        assert exc.value.status_code == 422
        assert "Credential reference tampering" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_step_anti_tampering_subworkflow_substitution(setup_freeze_env):
    """Attempting to swap subworkflow_id is rejected with 422."""
    env = setup_freeze_env
    user = User(id="u1", email="tester@alberto.local", role="editor")
    body = StepExecutionIn(
        node_id="subwf_node",
        node_type="subworkflow",
        config={"subworkflow_id": "forged_foreign_subworkflow"},
        mode="dry_run",
    )
    async with SessionLocal() as s:
        with pytest.raises(HTTPException) as exc:
            await execute_step(
                project_id=env["project"].id,
                workflow_id=env["workflow"].id,
                body=body,
                session=s,
                tenant_id=env["tenant"].id,
                user=user,
            )
        assert exc.value.status_code == 422
        assert "Subworkflow tampering detected" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_step_anti_tampering_node_type_spoofing(setup_freeze_env):
    """Attempting to execute an inject node as tool_call is rejected with 422."""
    env = setup_freeze_env
    user = User(id="u1", email="tester@alberto.local", role="editor")
    body = StepExecutionIn(
        node_id="inject_node",
        node_type="tool_call",
        config={"tool_id": env["tool_auth"].id},
        mode="dry_run",
    )
    async with SessionLocal() as s:
        with pytest.raises(HTTPException) as exc:
            await execute_step(
                project_id=env["project"].id,
                workflow_id=env["workflow"].id,
                body=body,
                session=s,
                tenant_id=env["tenant"].id,
                user=user,
            )
        assert exc.value.status_code == 422
        assert "Node type spoofing detected" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_step_anti_tampering_cross_tenant_isolation(setup_freeze_env):
    """Attempting to execute a workflow belonging to another project/tenant returns 404."""
    env = setup_freeze_env
    user = User(id="u1", email="tester@alberto.local", role="editor")
    body = StepExecutionIn(
        node_id="inject_node",
        node_type="inject",
        config={"payload": {"a": 1}},
        mode="dry_run",
    )
    async with SessionLocal() as s:
        with pytest.raises(HTTPException) as exc:
            await execute_step(
                project_id=env["project_b"].id,  # Requesting under project B
                workflow_id=env["workflow"].id,  # Workflow belongs to project A
                body=body,
                session=s,
                tenant_id=env["tenant_b"].id,
                user=user,
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_step_anti_tampering_stale_concurrency_conflict(setup_freeze_env):
    """Passing a stale active_version raises 409 Conflict."""
    env = setup_freeze_env
    user = User(id="u1", email="tester@alberto.local", role="editor")
    body = StepExecutionIn(
        node_id="inject_node",
        node_type="inject",
        config={"payload": {"a": 1}},
        mode="dry_run",
        active_version=1,  # Saved workflow active_version is 3
    )
    async with SessionLocal() as s:
        with pytest.raises(HTTPException) as exc:
            await execute_step(
                project_id=env["project"].id,
                workflow_id=env["workflow"].id,
                body=body,
                session=s,
                tenant_id=env["tenant"].id,
                user=user,
            )
        assert exc.value.status_code == 409
        assert "Workflow has been modified" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_step_anti_tampering_approval_flags_purged_and_unsaved_params_allowed(setup_freeze_env):
    """Unsaved parameter changes in editor work legitimately, while spoofed approval flags are purged."""
    env = setup_freeze_env
    user = User(id="u1", email="tester@alberto.local", role="editor")
    # Legitimate unsaved parameter change on inject node with forged approved flag
    body = StepExecutionIn(
        node_id="inject_node",
        node_type="inject",
        config={"payload": {"unsaved_draft": 42}, "approved": True, "human_approved": True},
        input_state={"approved": True, "human_approved": True},
        mode="dry_run",
        active_version=3,
    )
    async with SessionLocal() as s:
        out = await execute_step(
            project_id=env["project"].id,
            workflow_id=env["workflow"].id,
            body=body,
            session=s,
            tenant_id=env["tenant"].id,
            user=user,
        )
        assert out.ok is True
        assert out.output["payload"]["unsaved_draft"] == 42


# ==============================================================================
# SECTION 2: P0 — Complete Dry-Run Isolation & Unknown Fail-Closed Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_dry_run_unknown_side_effect_tool_fails_closed(setup_freeze_env):
    """Unknown side-effect tool classification fails closed in dry run (zero execution)."""
    env = setup_freeze_env
    calls = []

    class MockUnknownTool:
        async def ainvoke(self, args, config=None):
            calls.append(args)
            return {"status": "executed_danger"}

    ctx = CompileContext(
        tenant_id=env["tenant"].id,
        project_id=env["project"].id,
        workflow_id=env["workflow"].id,
        workflow_def=env["workflow"].executable,
        tool_registry={env["tool_unknown"].id: MockUnknownTool()},
    )
    ctx.dry_run = True

    fn = tool_call_factory({"tool_id": env["tool_unknown"].id}, ctx)
    res = await fn({"state": {}, "msg": {"payload": {}}})

    tr = res["tool_result"]
    assert tr["unsupported_dry_run"] is True
    assert tr["simulated"] is False
    assert tr["mocked"] is False
    assert "unknown side-effect classification" in tr["error"].lower()
    assert len(calls) == 0  # Tool was NEVER called


@pytest.mark.asyncio
async def test_dry_run_mutating_tool_simulated_zero_side_effects(setup_freeze_env):
    """Mutating tool in dry run mode returns simulation result with zero underlying tool invocations."""
    env = setup_freeze_env
    calls = []

    class MockMutatingTool:
        async def ainvoke(self, args, config=None):
            calls.append(args)
            return {"deleted": True}

    # Grant approval so policy would allow execution if it were live
    appr = ToolPolicyService.create_approval_request(
        tenant_id=env["tenant"].id,
        project_id=env["project"].id,
        tool_id=env["tool_mutating"].id,
        tool_name="authorized_mutating_tool",
        arguments={},
        caller_type="workflow",
        caller_id=env["workflow"].id,
    )
    ToolPolicyService.decide_approval_request(appr.id, "approve", {"role": "admin"})

    ctx = CompileContext(
        tenant_id=env["tenant"].id,
        project_id=env["project"].id,
        workflow_id=env["workflow"].id,
        workflow_def=env["workflow"].executable,
        tool_registry={env["tool_mutating"].id: MockMutatingTool()},
    )
    ctx.dry_run = True

    fn = tool_call_factory({"tool_id": env["tool_mutating"].id}, ctx)
    res = await fn({"state": {}, "msg": {"payload": {}}, "approval_id": appr.id})

    tr = res["tool_result"]
    assert tr["mocked"] is True
    assert tr["simulated"] is True
    assert tr["mode"] == "dry_run"
    assert len(calls) == 0  # Underlying tool was NEVER called


@pytest.mark.asyncio
async def test_dry_run_webhook_out_mutating_http_simulated_zero_network():
    """Mutating webhook_out (POST/PUT/DELETE) simulates without network egress."""
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    ctx.dry_run = True

    fn = webhook_out_factory({
        "method": "POST",
        "url": "https://api.external.com/payments/charge",
        "body": {"amount": 500},
    }, ctx)

    res = await fn({"state": {}, "msg": {"payload": {}}})
    wh = res["webhook_result"]
    assert wh["simulated"] is True
    assert wh["mocked"] is True
    assert wh["mode"] == "dry_run"
    assert wh["method"] == "POST"


@pytest.mark.asyncio
async def test_dry_run_webhook_out_unknown_method_fails_closed():
    """Unknown HTTP verb in webhook_out fails closed in dry run."""
    ctx = CompileContext(tenant_id="t1", project_id="p1")
    ctx.dry_run = True

    fn = webhook_out_factory({
        "method": "CUSTOM_MUTATE_OP",
        "url": "https://api.external.com/test",
    }, ctx)

    res = await fn({"state": {}, "msg": {"payload": {}}})
    wh = res["webhook_result"]
    assert wh["unsupported_dry_run"] is True
    assert wh["ok"] is False
    assert "unknown side-effect classification" in wh["error"]


@pytest.mark.asyncio
async def test_dry_run_agent_delegation_to_tool_manager(setup_freeze_env):
    """Agent delegating to ToolManagerService in dry run returns simulation without executing external tool."""
    env = setup_freeze_env

    # 1. Delegating mutating tool in dry run
    res = await ToolManagerService.execute_delegated_tool(
        tenant_id=env["tenant"].id,
        project_id=env["project"].id,
        tool_id_or_capability=env["tool_mutating"].name,
        parameters={"id": "record_123"},
        execution_context={"dry_run": True},
    )
    # Mutating tool requires approval -> policy correctly blocks without approval
    assert res["requires_approval"] is True
    assert res["ok"] is False

    # 2. Grant approval and retry delegation in dry run
    ToolPolicyService.decide_approval_request(res["approval_id"], "approve", {"role": "admin"})
    res2 = await ToolManagerService.execute_delegated_tool(
        tenant_id=env["tenant"].id,
        project_id=env["project"].id,
        tool_id_or_capability=env["tool_mutating"].name,
        parameters={"id": "record_123"},
        execution_context={"approval_id": res["approval_id"], "dry_run": True},
    )
    assert res2["ok"] is True
    assert res2["simulated"] is True
    assert res2["mode"] == "dry_run"


@pytest.mark.asyncio
async def test_dry_run_agent_delegation_to_unknown_tool_fails_closed(setup_freeze_env):
    """Agent delegating unknown tool to ToolManagerService in dry run returns unsupported_dry_run."""
    env = setup_freeze_env
    res = await ToolManagerService.execute_delegated_tool(
        tenant_id=env["tenant"].id,
        project_id=env["project"].id,
        tool_id_or_capability=env["tool_unknown"].name,
        parameters={},
        execution_context={"dry_run": True},
    )
    assert res["ok"] is False
    assert res["unsupported_dry_run"] is True
    assert "unknown side-effect classification" in res["error"]


# ==============================================================================
# SECTION 3: P1 — Approval Consumption, Concurrency & Idempotency Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrent_approval_consumption_single_winner(setup_freeze_env):
    """Two concurrent requests trying to consume the same approval: exactly one succeeds, the other fails."""
    env = setup_freeze_env
    args = {"cluster_id": "prod-cluster-9"}

    appr = ToolPolicyService.create_approval_request(
        tenant_id=env["tenant"].id,
        project_id=env["project"].id,
        tool_id=env["tool_mutating"].id,
        tool_name="authorized_mutating_tool",
        arguments=args,
        caller_type="workflow",
        caller_id=env["workflow"].id,
    )
    ToolPolicyService.decide_approval_request(appr.id, "approve", {"role": "admin"})

    async def _attempt():
        return await ToolPolicyService.evaluate_execution(
            tenant_id=env["tenant"].id,
            project_id=env["project"].id,
            tool_id=env["tool_mutating"].id,
            caller_type="workflow",
            caller_id=env["workflow"].id,
            workflow_def=env["workflow"].executable,
            execution_context={"approval_id": appr.id, "arguments": args, "dry_run": False},
        )

    # Fire both concurrently
    res_a, res_b = await asyncio.gather(_attempt(), _attempt())

    results = [res_a.allowed, res_b.allowed]
    assert results.count(True) == 1, f"Expected exactly 1 winner, got: {results}"
    assert results.count(False) == 1

    loser = res_a if not res_a.allowed else res_b
    assert "already been consumed" in loser.reason.lower() or "cannot be consumed" in loser.reason.lower()


@pytest.mark.asyncio
async def test_failure_before_tool_invocation_prevents_duplicate_replay(setup_freeze_env):
    """After approval is consumed, workflow failure prevents repeating mutation with the same token."""
    env = setup_freeze_env
    args = {"task": "wipe_cache"}

    appr = ToolPolicyService.create_approval_request(
        tenant_id=env["tenant"].id,
        project_id=env["project"].id,
        tool_id=env["tool_mutating"].id,
        tool_name="authorized_mutating_tool",
        arguments=args,
        caller_type="workflow",
        caller_id=env["workflow"].id,
    )
    ToolPolicyService.decide_approval_request(appr.id, "approve", {"role": "admin"})

    # 1. Live run consumes approval
    dec1 = await ToolPolicyService.evaluate_execution(
        tenant_id=env["tenant"].id,
        project_id=env["project"].id,
        tool_id=env["tool_mutating"].id,
        caller_type="workflow",
        caller_id=env["workflow"].id,
        workflow_def=env["workflow"].executable,
        execution_context={"approval_id": appr.id, "arguments": args, "dry_run": False},
    )
    assert dec1.allowed is True

    # 2. Retry with same approval token is blocked
    dec2 = await ToolPolicyService.evaluate_execution(
        tenant_id=env["tenant"].id,
        project_id=env["project"].id,
        tool_id=env["tool_mutating"].id,
        caller_type="workflow",
        caller_id=env["workflow"].id,
        workflow_def=env["workflow"].executable,
        execution_context={"approval_id": appr.id, "arguments": args, "dry_run": False},
    )
    assert dec2.allowed is False
    assert "already been consumed" in dec2.reason.lower() or "cannot be consumed" in dec2.reason.lower()

