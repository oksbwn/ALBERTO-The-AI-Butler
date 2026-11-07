"""Integration / Tool Manager Sub-Agent specification."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from alberto.agents.base import AgentSpec

log = logging.getLogger("alberto.agents.tool_manager")
AGENT_DIR = Path(__file__).resolve().parent


async def build_integration_context(session: Any, tenant_id: str, project_id: str) -> str:
    """Assemble live MCP servers, connectors, and tool registry summary."""
    try:
        from alberto.models import ConnectorInstall, McpClient, Tool

        mcps = (
            await session.execute(
                select(McpClient).where(McpClient.tenant_id == tenant_id, McpClient.project_id == project_id)
            )
        ).scalars().all()
        conns = (
            await session.execute(
                select(ConnectorInstall).where(
                    ConnectorInstall.tenant_id == tenant_id, ConnectorInstall.project_id == project_id
                )
            )
        ).scalars().all()
        tools = (
            await session.execute(select(Tool).where(Tool.tenant_id == tenant_id, Tool.project_id == project_id))
        ).scalars().all()

        mcp_lines = []
        for m in mcps:
            is_ha = "8123" in (m.url or "") or m.name.upper() == "HA" or "homeassistant" in (m.url or "").lower()
            label = f"{m.name} (Home Assistant)" if is_ha else m.name
            status = "enabled" if m.enabled else "disabled"
            m_tools = [t.name for t in tools if t.kind == "mcp" and (t.name.startswith("ha_") if is_ha else True)]
            tool_sample = ", ".join(m_tools[:8]) + (f" (+{len(m_tools) - 8} more)" if len(m_tools) > 8 else "")
            mcp_lines.append(
                f"- MCP Client: {label} [{status}] | Transport: {m.transport} | URL: {m.url or '(none)'} "
                f"| Registered Tools ({len(m_tools)}): {tool_sample or '(none)'}"
            )

        conn_lines = [f"- Connector: {c.name or c.slug} [{c.status}] (version {c.version})" for c in conns]

        return (
            "\n\n[PROJECT REGISTERED INTEGRATIONS & MCP REGISTRY]\n"
            f"Active MCP Servers ({len(mcps)}):\n"
            + ("\n".join(mcp_lines) if mcp_lines else "None\n")
            + f"\nInstalled Connectors ({len(conns)}):\n"
            + ("\n".join(conn_lines) if conn_lines else "None\n")
            + f"\nTotal Registered Tools in Registry: {len(tools)}"
        )
    except Exception as ie:
        log.warning("Failed to build live integration context: %s", ie)
        return ""


def _select_tool_manager_tools(all_tools: list[Any], _user_msg: str = "") -> list[Any]:
    allowed = ("list_resources", "describe_workflow", "delegate_tool_execution", "delegate_automation_management")
    return [t for t in all_tools if t.name in allowed]


def build_tool_manager_spec() -> AgentSpec:
    return AgentSpec(
        id="tool_manager",
        display_name="Integration Manager",
        trace_name="tool_manager",
        actor_name="Integration Manager",
        agent_dir=AGENT_DIR,
        aliases=("integration_manager", "toolmanager", "integrationmanager"),
        recall_top_k=5,
        _select_tools_fn=_select_tool_manager_tools,
        _build_context_fn=build_integration_context,
    )

