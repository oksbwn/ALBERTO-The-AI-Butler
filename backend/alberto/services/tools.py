"""Tool CRUD + the /test endpoint (raw vs projected payload + token delta)."""

from __future__ import annotations

import builtins
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.auth_providers.resolver import AuthResolver
from alberto.models import Tool, ToolSetMember
from alberto.secrets.store import SecretStore
from alberto.tools.graphql import execute_graphql
from alberto.tools.projection import estimate_tokens
from alberto.tools.rest import execute_rest, project_observation


class ToolService:
    @staticmethod
    async def list(session: AsyncSession, tenant_id: str, project_id: str) -> list[Tool]:
        rows = await session.execute(
            select(Tool).where(Tool.tenant_id == tenant_id, Tool.project_id == project_id)
        )
        return list(rows.scalars())

    @staticmethod
    async def ensure_builtins(session: AsyncSession, tenant_id: str, project_id: str) -> None:
        """Provision the platform's built-in tools into a project if any are missing. Idempotent:
        only creates builtins whose `config.builtin` isn't already present, so it's safe to call
        on every project create and every tools-list read. Built-ins are project defaults - always
        available, protected from deletion, and excluded from import/export bundles."""
        from alberto.tools.builtin import BUILTIN_DEFAULTS

        existing_tools = list((await session.execute(
            select(Tool).where(
                Tool.tenant_id == tenant_id, Tool.project_id == project_id, Tool.kind == "builtin"
            )
        )).scalars().all())
        have = {(t.config or {}).get("builtin"): t for t in existing_tools}
        for d in BUILTIN_DEFAULTS:
            b_key = d["builtin"]
            if b_key not in have:
                session.add(Tool(
                    tenant_id=tenant_id, project_id=project_id, name=b_key, kind="builtin",
                    config=dict(d),
                ))
            else:
                cur = have[b_key]
                cfg = dict(cur.config or {})
                if "input_schema" not in cfg and "input_schema" in d:
                    from sqlalchemy.orm.attributes import flag_modified
                    cfg["input_schema"] = d["input_schema"]
                    cur.config = cfg
                    flag_modified(cur, "config")
        await session.commit()

    @staticmethod
    async def ensure_mcp_tools(session: AsyncSession, tenant_id: str, project_id: str) -> None:
        """Provision or synchronize tools from connected MCP servers with discovered capabilities."""
        from alberto.models import McpClient
        from alberto.services.mcp_discovery import McpDiscoveryService

        mcp_clients = list((await session.execute(
            select(McpClient).where(McpClient.tenant_id == tenant_id, McpClient.project_id == project_id)
        )).scalars().all())

        for m in mcp_clients:
            caps = m.capabilities or {}
            tools = caps.get("tools") or []
            if tools:
                try:
                    await McpDiscoveryService.sync_tools_to_registry(session, m, tenant_id, project_id, tools)
                except Exception as e:
                    import logging
                    logging.getLogger("alberto.services.tools").warning("Failed to ensure MCP tools for %s: %s", m.name, e)

    @staticmethod
    async def get(session: AsyncSession, tenant_id: str, tool_id: str) -> Tool | None:
        row = await session.execute(select(Tool).where(Tool.tenant_id == tenant_id, Tool.id == tool_id))
        return row.scalar_one_or_none()

    @staticmethod
    async def create(session: AsyncSession, tenant_id: str, project_id: str, *, name: str, kind: str, config: dict, auth_provider_id: str | None = None) -> Tool:
        tool = Tool(
            tenant_id=tenant_id, project_id=project_id, name=name, kind=kind,
            config=config or {}, auth_provider_id=auth_provider_id or (config or {}).get("auth_provider_id"),
        )
        session.add(tool)
        await session.commit()
        await session.refresh(tool)
        return tool

    @staticmethod
    async def update(session: AsyncSession, tool: Tool, *, name: str | None = None, config: dict | None = None,
                     auth_provider_id: str | None = None, enabled: bool | None = None) -> Tool:
        if name is not None:
            tool.name = name
        if config is not None:
            tool.config = config
        if auth_provider_id is not None:
            tool.auth_provider_id = auth_provider_id or None
        if enabled is not None:
            tool.enabled = enabled
        await session.commit()
        await session.refresh(tool)
        return tool

    @staticmethod
    async def delete(session: AsyncSession, tool: Tool) -> None:
        """Delete a tool. Agents/workflows reference tools by id in their config; the
        compiler tolerates missing ids (tools_for skips them), so deletion is safe. Also
        remove the tool from any tool sets - membership rows have no DB-level cascade."""
        await session.execute(delete(ToolSetMember).where(ToolSetMember.tool_id == tool.id))
        await session.delete(tool)
        await session.commit()

        # Purge Knowledge Graph projections for this tool
        try:
            from alberto.knowledge.graph import get_graph_adapter, make_entity_id
            adapter = get_graph_adapter()
            await adapter.delete_entity(tool.tenant_id, tool.project_id, make_entity_id(tool.tenant_id, tool.project_id, f"tool:{tool.id}"))
            await adapter.delete_entity(tool.tenant_id, tool.project_id, make_entity_id(tool.tenant_id, tool.project_id, f"tool:{tool.name}"))
            await adapter.delete_entities_by_source(tool.tenant_id, tool.project_id, f"tool:{tool.id}")
        except Exception as e:
            import logging
            logging.getLogger("alberto.services.tools").debug(
                f"Knowledge graph cleanup skipped/failed for tool {tool.id}: {e}"
            )


    @staticmethod
    async def get_tool_usages(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        tool_ids: builtins.list[str],
        tool_names: builtins.list[str] | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Find workflows and agents currently referencing any of the specified tool ids or names."""
        from alberto.models import Agent, Workflow

        id_set = {tid for tid in (tool_ids or []) if tid}
        name_set = {tname for tname in (tool_names or []) if tname}

        if not id_set and not name_set:
            return []

        usages: builtins.list[dict[str, Any]] = []

        # 1. Check Workflows
        wfs = builtins.list((await session.execute(
            select(Workflow).where(Workflow.tenant_id == tenant_id, Workflow.project_id == project_id)
        )).scalars().all())

        for wf in wfs:
            matched_tools: set[str] = set()

            # Executable graph nodes
            exec_nodes = (wf.executable or {}).get("nodes") or []
            for n in exec_nodes:
                cfg = n.get("config") or {}
                t_id = cfg.get("tool_id") or n.get("tool_id")
                if t_id and (str(t_id) in id_set or str(t_id) in name_set):
                    matched_tools.add(str(t_id))

                for t_ref in (cfg.get("tools") or []):
                    if str(t_ref) in id_set or str(t_ref) in name_set:
                        matched_tools.add(str(t_ref))

            # Canvas graph nodes
            canvas_nodes = (wf.canvas or {}).get("nodes") or []
            for n in canvas_nodes:
                data = n.get("data") or {}
                cfg = data.get("config") or {}
                t_id = data.get("tool_id") or cfg.get("tool_id")
                if t_id and (str(t_id) in id_set or str(t_id) in name_set):
                    matched_tools.add(str(t_id))

                for t_ref in (cfg.get("tools") or data.get("tools") or []):
                    if str(t_ref) in id_set or str(t_ref) in name_set:
                        matched_tools.add(str(t_ref))

            if matched_tools:
                usages.append({
                    "target_type": "workflow",
                    "target_id": wf.id,
                    "target_name": wf.name or "Untitled Workflow",
                    "matched_tools": sorted(list(matched_tools)),
                })

        # 2. Check Agents
        agents = list((await session.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.project_id == project_id)
        )).scalars().all())

        for ag in agents:
            matched_tools = set()
            cfg = ag.config or {}
            for t_ref in (cfg.get("tools") or []):
                if str(t_ref) in id_set or str(t_ref) in name_set:
                    matched_tools.add(str(t_ref))

            for sa in (cfg.get("subagents") or []):
                for t_ref in (sa.get("tools") or []):
                    if str(t_ref) in id_set or str(t_ref) in name_set:
                        matched_tools.add(str(t_ref))

            if matched_tools:
                usages.append({
                    "target_type": "agent",
                    "target_id": ag.id,
                    "target_name": ag.name or "Untitled Agent",
                    "matched_tools": sorted(list(matched_tools)),
                })

        return usages


    @staticmethod
    async def record_test(session: AsyncSession, tool: Tool, result: dict) -> None:
        """Persist the last test (token delta + clipped payloads) on the tool, so the
        builder shows the real last raw/projected response on reopen instead of the
        sample placeholder."""
        import json as _json
        from datetime import UTC, datetime

        def _clip(value, limit=20_000):
            """Keep stored payloads bounded; oversized ones become truncated JSON text."""
            try:
                s = _json.dumps(value, default=str)
            except Exception:  # noqa: BLE001
                return str(value)[:limit]
            return value if len(s) <= limit else s[:limit] + "… (truncated)"

        cfg = dict(tool.config or {})
        if result.get("ok"):
            cfg["_last_test"] = {
                "raw_tokens": result.get("raw_tokens"),
                "projected_tokens": result.get("projected_tokens"),
                "status": result.get("status"),
                "latency_ms": result.get("latency_ms"),
                "raw": _clip(result.get("raw")),
                "projected": _clip(result.get("projected")),
                "final_url": result.get("final_url"),
                "redirect": result.get("redirect"),
                "at": datetime.now(UTC).isoformat(),
            }
            tool.last_tested = "pass"
        else:
            tool.last_tested = "fail"
        tool.config = cfg
        await session.commit()

    @staticmethod
    async def test(tenant_id: str, project_id: str, cfg: dict, args: dict, context: dict | None = None) -> dict:
        resolver = AuthResolver(SecretStore())
        kind = cfg.get("kind")
        try:
            if kind == "rest_api":
                res = await execute_rest(cfg, args, tenant_id=tenant_id, project_id=project_id, context=context, auth_resolver=resolver)
            elif kind == "graphql":
                res = await execute_graphql(cfg, args, tenant_id=tenant_id, project_id=project_id, context=context, auth_resolver=resolver)
            elif kind in ("builtin", "code", "sql"):
                from alberto.services.runtime import make_runtime_ctx
                ctx = make_runtime_ctx(tenant_id, project_id)
                if kind == "builtin":
                    from alberto.tools.builtin import build_builtin_tool
                    tool = build_builtin_tool(cfg, ctx)
                elif kind == "code":
                    from alberto.tools.code import build_code_tool
                    tool = build_code_tool(cfg, ctx)
                else:
                    from alberto.tools.sql import build_sql_tool
                    tool = build_sql_tool(cfg, ctx)
                out = await tool.ainvoke(args)
                res = {"raw": out, "projected": out, "status": 200, "latency_ms": 0}
            elif kind == "mcp":
                from alberto.services.runtime import make_runtime_ctx
                from alberto.tools.mcp import load_mcp_tool
                ctx = make_runtime_ctx(tenant_id, project_id)
                tool = await load_mcp_tool(cfg, ctx)
                out = await tool.ainvoke(args)
                res = {"raw": out, "projected": out, "status": 200, "latency_ms": 0}
            else:
                return {"ok": False, "error": f"Test {kind!r} tools by attaching them to an agent and running the workflow."}
        except Exception as e:  # noqa: BLE001 - surface failures (network/auth/etc.) to the UI
            return {"ok": False, "error": str(e)}

        # Preview exactly what the agent receives (rest.project_observation): the projection is
        # applied to the model observation, which on a redirect is the {"body", "redirect"} envelope
        # carrying the target URL. So an un-projected 3xx no longer reads as "" / 0 tok, and a
        # `redirect.location` projection previews as just the URL - with the meter counting both.
        observation, projected = project_observation(res, cfg)
        return {
            "ok": True,
            "status": res.get("status"),
            "latency_ms": res.get("latency_ms"),
            "raw": observation,
            "projected": projected,
            "raw_tokens": estimate_tokens(observation),
            "projected_tokens": estimate_tokens(projected),
            "final_url": res.get("final_url"),
            "redirect": res.get("redirect"),
        }
