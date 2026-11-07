"""Main Alberto Butler ('assistant') specification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alberto.agents.automation_manager.agent import build_workflow_context
from alberto.agents.base import AgentSpec
from alberto.agents.tool_manager.agent import build_integration_context

AGENT_DIR = Path(__file__).resolve().parent


async def _build_butler_context(session: Any, tenant_id: str, project_id: str) -> str:
    int_ctx = await build_integration_context(session, tenant_id, project_id)
    wf_ctx = await build_workflow_context(session, tenant_id, project_id)
    return f"{int_ctx}{wf_ctx}"


def _select_butler_tools(all_tools: list[Any], user_msg: str = "") -> list[Any]:
    user_wants_resources = any(
        w in (user_msg or "").lower()
        for w in ("what tools", "list tools", "list resources", "what integrations", "what workflows")
    )
    allowed = ("delegate_tool_execution", "delegate_automation_management") + (
        ("list_resources", "describe_workflow") if user_wants_resources else ()
    )
    return [t for t in all_tools if t.name in allowed]


def build_butler_spec() -> AgentSpec:
    return AgentSpec(
        id="assistant",
        display_name="Alberto Butler",
        trace_name="assistant",
        actor_name="System",
        agent_dir=AGENT_DIR,
        aliases=("", "butler", "alberto"),
        recall_top_k=5,
        _select_tools_fn=_select_butler_tools,
        _build_context_fn=_build_butler_context,
    )

