"""Butler Project-Level & Aggregated Assistant StructuredTools."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from sqlalchemy import select

from alberto.agents.automation_manager.tools import (
    _default_agent_model,
    build_automation_manager_tools,
)
from alberto.agents.memory_curator.tools import build_memory_curator_tools
from alberto.agents.tool_manager.tools import build_tool_manager_tools
from alberto.db.base import SessionLocal
from alberto.models import Agent, AuthProvider, KbSource, QaPair, Tool, Workflow


def build_butler_tools(tenant_id: str, project_id: str, mutated: list, current_user: Any = None) -> list:
    """Build project discovery, agent preset, and UI component tools."""

    async def list_resources() -> str:
        """List everything in this project: MCP integrations, connectors, tools, workflows, agents, auth providers, knowledge sources, and Q&A pairs."""
        from alberto.models import ConnectorInstall, McpClient

        async with SessionLocal() as s:

            def names(rows, attr="name"):
                return [getattr(r, attr) for r in rows] or ["(none)"]

            mcps = (
                await s.execute(select(McpClient).where(McpClient.tenant_id == tenant_id, McpClient.project_id == project_id))
            ).scalars().all()
            conns = (
                await s.execute(
                    select(ConnectorInstall).where(
                        ConnectorInstall.tenant_id == tenant_id, ConnectorInstall.project_id == project_id
                    )
                )
            ).scalars().all()
            tools = (await s.execute(select(Tool).where(Tool.tenant_id == tenant_id, Tool.project_id == project_id))).scalars().all()
            wfs = (
                await s.execute(select(Workflow).where(Workflow.tenant_id == tenant_id, Workflow.project_id == project_id))
            ).scalars().all()
            agents = (await s.execute(select(Agent).where(Agent.tenant_id == tenant_id, Agent.project_id == project_id))).scalars().all()
            aps = (
                await s.execute(select(AuthProvider).where(AuthProvider.tenant_id == tenant_id, AuthProvider.project_id == project_id))
            ).scalars().all()
            srcs = (
                await s.execute(select(KbSource).where(KbSource.tenant_id == tenant_id, KbSource.project_id == project_id))
            ).scalars().all()
            qas = (await s.execute(select(QaPair).where(QaPair.tenant_id == tenant_id, QaPair.project_id == project_id))).scalars().all()
            mcp_items = []
            for m in mcps:
                is_ha = "8123" in (m.url or "") or m.name.upper() == "HA" or "homeassistant" in (m.url or "").lower()
                label = f"{m.name} (Home Assistant)" if is_ha else m.name
                status_str = "enabled" if m.enabled else "disabled"
                mcp_items.append(f"{label} ({m.transport}, {m.url or 'local'}) [{status_str}]")
            conn_items = [f"{c.name or c.slug} [{c.status}] (version {c.version})" for c in conns] or ["(none)"]
            return json.dumps(
                {
                    "mcp_integrations": mcp_items or ["(none)"],
                    "connectors": conn_items,
                    "tools": [f"{t.name} ({t.kind})" for t in tools] or ["(none)"],
                    "workflows": [f"{w.name} [{w.status}]" for w in wfs] or ["(none)"],
                    "agents": names(agents),
                    "auth_providers": [f"{a.name} ({a.kind})" for a in aps] or ["(none)"],
                    "knowledge_sources": names(srcs),
                    "qa_pairs": len(qas),
                }
            )

    async def create_agent_preset(name: str, instructions: str, model: str = "", tool_names: str = "") -> str:
        """Create OR UPDATE (idempotent by name) a reusable agent preset."""
        from alberto.services.agents import AgentService

        async with SessionLocal() as s:
            mdl = model or await _default_agent_model(s, tenant_id, project_id)
            wanted = [t.strip() for t in tool_names.split(",") if t.strip()]
            tool_ids: list[str] = []
            missing: list[str] = []
            if wanted:
                rows = (await s.execute(select(Tool).where(Tool.project_id == project_id))).scalars().all()
                by_name = {t.name: t.id for t in rows}
                for w in wanted:
                    (tool_ids.append(by_name[w]) if w in by_name else missing.append(w))
            cfg = {"flavor": "agent", "model": mdl, "system_prompt": instructions, "tools": tool_ids, "middleware": []}
            existing = [a for a in await AgentService.list(s, tenant_id, project_id) if a.name == name]
            if existing:
                agent = await AgentService.update(s, existing[0], config=cfg)
                verb = "Updated existing"
            else:
                agent = await AgentService.create(s, tenant_id, project_id, name=name.strip().replace(" ", "_"), config=cfg)
                verb = "Created"
        mutated.append({"kind": "agent", "name": agent.name})
        note = f" (unknown tools skipped: {', '.join(missing)})" if missing else ""
        return f"{verb} agent preset '{agent.name}' on {mdl} with {len(tool_ids)} tool(s){note}. See the Agents screen."

    async def create_component(
        name: str,
        html: str,
        title: str = "",
        description: str = "",
        css: str = "",
        props_schema_json: str = "",
        sample_props_json: str = "",
    ) -> str:
        """Create OR UPDATE (idempotent by name) a generative-UI component."""
        from alberto.models import Component
        from alberto.services.components import ComponentService

        nm = name.strip().replace(" ", "_")
        try:
            props_schema = json.loads(props_schema_json) if props_schema_json else {}
            sample = json.loads(sample_props_json) if sample_props_json else {}
        except json.JSONDecodeError as e:
            return f"ERROR: props_schema_json/sample_props_json must be valid JSON: {e}"
        async with SessionLocal() as s:
            existing = (
                await s.execute(
                    select(Component).where(
                        Component.tenant_id == tenant_id, Component.project_id == project_id, Component.name == nm
                    )
                )
            ).scalar_one_or_none()
            if existing:
                comp = await ComponentService.update(
                    s,
                    existing,
                    title=title or None,
                    description=description,
                    props_schema=props_schema,
                    html=html,
                    css=css,
                    sample_props=sample,
                )
                verb = "Updated"
            else:
                comp = await ComponentService.create(
                    s,
                    tenant_id,
                    project_id,
                    name=nm,
                    title=title or None,
                    description=description,
                    props_schema=props_schema,
                    html=html,
                    css=css,
                    sample_props=sample,
                )
                verb = "Created"
        mutated.append({"kind": "component", "name": comp.name})
        return f"{verb} component '{comp.name}'. Attach it to an agent (config.components) to let the model render it as a widget."

    def mk(fn, name):
        return StructuredTool.from_function(coroutine=fn, name=name, parse_docstring=False)

    return [
        mk(list_resources, "list_resources"),
        mk(create_agent_preset, "create_agent_preset"),
        mk(create_component, "create_component"),
    ]


def build_assistant_tools(tenant_id: str, project_id: str, mutated: list, current_user: Any = None) -> list:
    """Assemble the complete platform toolset across all decoupled built-in sub-agents."""
    butler_map = {t.name: t for t in build_butler_tools(tenant_id, project_id, mutated, current_user=current_user)}
    auto_map = {t.name: t for t in build_automation_manager_tools(tenant_id, project_id, mutated, current_user=current_user)}
    tool_map = {t.name: t for t in build_tool_manager_tools(tenant_id, project_id, mutated, current_user=current_user)}
    mem_map = {t.name: t for t in build_memory_curator_tools(tenant_id, project_id, mutated, current_user=current_user)}
    combined = {**butler_map, **auto_map, **tool_map, **mem_map}
    canonical_order = [
        "list_resources",
        "describe_workflow",
        "list_node_types",
        "get_node_schema",
        "list_middleware_types",
        "create_agent_preset",
        "create_builtin_tool",
        "create_rest_tool",
        "create_graphql_tool",
        "create_sql_tool",
        "create_code_tool",
        "create_mcp_tool",
        "create_component",
        "create_auth_provider",
        "add_qa_pair",
        "add_knowledge_text",
        "create_grounded_workflow",
        "create_intent_router_workflow",
        "create_custom_workflow",
        "add_human_review",
        "test_workflow",
        "evaluate_build",
        "delete_workflow",
        "delegate_tool_execution",
        "delegate_automation_management",
    ]
    return [combined[name] for name in canonical_order if name in combined]

