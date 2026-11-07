"""Automation Manager Sub-Agent specification, context builder, and build-intent fallback."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from alberto.agents.base import AgentSpec

log = logging.getLogger("alberto.agents.automation_manager")
AGENT_DIR = Path(__file__).resolve().parent


async def build_workflow_context(session: Any, tenant_id: str, project_id: str) -> str:
    """Assemble the live Project Workflow Registry block."""
    try:
        from alberto.models import Workflow

        wfs = (
            await session.execute(
                select(Workflow).where(Workflow.tenant_id == tenant_id, Workflow.project_id == project_id)
            )
        ).scalars().all()
        wf_lines = [
            f"- Workflow '{w.name}' (ID: {w.id}) | Status: {w.status} | Version: {w.active_version or 1} "
            f"| Nodes: {len((w.executable or {}).get('nodes', []))}"
            for w in wfs
        ]
        return (
            "\n\n[PROJECT WORKFLOW REGISTRY]\n"
            f"Total Workflows in this Project: {len(wfs)}\n"
            + ("\n".join(wf_lines) if wf_lines else "No workflows exist in this project yet.\n")
        )
    except Exception as we:
        log.warning("Failed to build live workflow context: %s", we)
        return ""


def _select_automation_manager_tools(all_tools: list[Any], _user_msg: str = "") -> list[Any]:
    allowed = ("list_resources", "describe_workflow", "delegate_tool_execution", "delegate_automation_management")
    return [t for t in all_tools if t.name in allowed]


async def _automation_post_turn_fallback(
    *,
    user_msg: str,
    tools_to_bind: list[Any],
    mutated: list[Any],
    final_text: str,
) -> AsyncIterator[dict]:
    """Ensure build/authoring requests in Playground always generate a proposal even if the LLM omits tool_calls."""
    if mutated or not user_msg:
        return
    low_user = user_msg.strip().lower()
    is_query_only = any(
        q in low_user
        for q in (
            "how many",
            "what workflows",
            "list workflows",
            "show workflows",
            "which workflow is running",
            "show runs",
        )
    )
    is_build_intent = not is_query_only and any(
        k in low_user
        for k in (
            "build",
            "create",
            "design",
            "generate",
            "make",
            "draft",
            "propose",
            "setup",
            "set up",
            "construct",
            "automate",
            "workflow",
            "pipeline",
            "add approval",
            "add a ",
            "remove ",
            "replace ",
        )
    )
    delegate_tool = next((t for t in tools_to_bind if t.name == "delegate_automation_management"), None)
    if is_build_intent and delegate_tool:
        yield {"event": "tool", "data": {"name": "delegate_automation_management", "result": "running"}}
        try:
            res = await asyncio.wait_for(delegate_tool.ainvoke({"requirement": user_msg}), timeout=90.0)
            yield {"event": "tool", "data": {"name": "delegate_automation_management", "result": str(res)}}
            try:
                parsed = json.loads(res) if isinstance(res, str) else {}
                prop = parsed.get("proposal") or {}
                questions = parsed.get("questions") or []
                if prop.get("title"):
                    summary_note = (
                        f"\n\nI have generated the workflow proposal **'{prop['title']}'** "
                        f"(`{prop.get('strategy', 'single_agent')}` strategy) in the **Automate Workbench**. "
                        "You can inspect the Live Graph Preview and click **Approve & Activate** when ready."
                    )
                    yield {"event": "messages", "data": {"content": summary_note}}
                elif questions and questions[0] not in final_text:
                    q_note = f"\n\n{questions[0]}"
                    yield {"event": "messages", "data": {"content": q_note}}
            except Exception:
                pass
        except Exception as te:
            yield {"event": "tool", "data": {"name": "delegate_automation_management", "result": f"tool error: {te}"}}


def build_automation_manager_spec() -> AgentSpec:
    return AgentSpec(
        id="automation_manager",
        display_name="Automation Manager",
        trace_name="automation_manager",
        actor_name="Automation Manager",
        agent_dir=AGENT_DIR,
        aliases=("automate", "automationmanager", "workflow_manager"),
        recall_top_k=5,
        _select_tools_fn=_select_automation_manager_tools,
        _build_context_fn=build_workflow_context,
        _post_turn_fallback_fn=_automation_post_turn_fallback,
    )

