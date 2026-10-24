"""Unit tests for agent-initiated tool call policy enforcement (GAP-SEC-01).

Verifies that when agents invoke tools, execution passes through ToolPolicyService:
1. Static entitlements and caller association are enforced.
2. Destructive operations (delete / critical / requires_approval) require HITL approval.
3. Unapproved agent calls are blocked and generate pending approval requests.
4. Approved execution consumes the approval atomically and proceeds.
5. Unassociated tools are denied under default-deny policy.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from alberto.db.base import SessionLocal
from alberto.models import Agent, Project, Tool
from alberto.services.projects import ProjectService
from alberto.services.tools import ToolService
from alberto.services.tool_policy import ToolPolicyService
from alberto.engine.context import CompileContext
from alberto.nodes.agent_node import _wrap_tool_for_agent, _resolve_and_secure_agent_tools
from langchain_core.tools import StructuredTool


@pytest.fixture
async def sample_project():
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id="tenant-agent-policy",
            name="Agent Policy Test Project",
            slug="agent-policy-proj",
        )
        await session.commit()
        await session.refresh(proj)
        return proj


@pytest.mark.asyncio
async def test_agent_tool_policy_hitl_enforcement(sample_project: Project):
    """Verify an agent cannot execute a delete tool without approval."""
    async with SessionLocal() as s:
        # Create a tool requiring approval
        tool = await ToolService.create(
            s,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="delete_account_data",
            kind="builtin",
            config={
                "builtin": "calculator",
                "effect": "delete",
                "requires_approval": True,
                "enabled": True,
            },
        )

    # Compile context
    ctx = CompileContext(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        end_user={"id": "usr-test", "roles": ["member"]},
    )
    called = {"count": 0}

    async def _impl(account_id: str = "") -> dict:
        called["count"] += 1
        return {"deleted": True}

    raw_tool = StructuredTool.from_function(
        coroutine=_impl,
        name="delete_account_data",
        description="Delete account data",
    )
    ctx.tool_registry[tool.id] = raw_tool
    ctx.tool_specs[tool.id] = {"config": {"effect": "delete", "requires_approval": True}}

    agent_cfg = {
        "name": "data_cleaner",
        "tools": [tool.id],
    }

    # Wrap tool for agent
    secured_tool = _wrap_tool_for_agent(raw_tool, tool.id, "data_cleaner", agent_cfg, ctx)

    # 1. First execution attempt -> Policy denies and generates approval request
    res = await secured_tool.ainvoke({"account_id": "acc-123"})
    assert isinstance(res, str)
    assert "requires Human-in-the-Loop approval" in res
    assert "Approval request created" in res
    assert called["count"] == 0

    # Extract approval ID from response
    appr_id = res.split("Approval request created: ")[1].split(".")[0].strip()
    appr = ToolPolicyService.get_approval(appr_id)
    assert appr is not None
    assert appr.tool_id == tool.id
    assert appr.status == "pending"

    # 2. Authorize approval request
    ok, _ = ToolPolicyService.decide_approval_request(
        appr_id, "approve", {"id": "admin-1", "role": "admin"}
    )
    assert ok is True

    # 3. Resume with approval ID in context -> Allowed and executed
    ctx.run_context = {"approval_id": appr_id}
    res_approved = await secured_tool.ainvoke({"account_id": "acc-123"})
    assert res_approved == {"deleted": True}
    assert called["count"] == 1

    # 4. Replay attempt with already consumed approval -> Denied
    res_replay = await secured_tool.ainvoke({"account_id": "acc-123"})
    assert isinstance(res_replay, str)
    assert "requires Human-in-the-Loop approval" in res_replay or "consumed" in res_replay


@pytest.mark.asyncio
async def test_agent_tool_policy_caller_association_denial(sample_project: Project):
    """Verify an agent cannot execute a tool not associated in its config."""
    async with SessionLocal() as s:
        tool = await ToolService.create(
            s,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="send_notification",
            kind="builtin",
            config={
                "builtin": "calculator",
                "effect": "read",
                "enabled": True,
            },
        )

    ctx = CompileContext(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        end_user={"id": "usr-test", "roles": ["member"]},
    )
    called = {"count": 0}

    async def _send(msg: str = "") -> dict:
        called["count"] += 1
        return {"sent": True}

    raw_tool = StructuredTool.from_function(
        coroutine=_send,
        name="send_notification",
        description="Send notification",
    )
    ctx.tool_registry[tool.id] = raw_tool

    # Agent config does NOT list tool.id in its tools or toolsets
    agent_cfg = {
        "name": "unauthorized_agent",
        "tools": ["some_other_tool"],
    }

    secured_tool = _wrap_tool_for_agent(raw_tool, tool.id, "unauthorized_agent", agent_cfg, ctx)

    res = await secured_tool.ainvoke({"msg": "hello"})
    assert isinstance(res, str)
    assert "Tool execution policy violation" in res
    assert "not explicitly associated" in res
    assert called["count"] == 0
