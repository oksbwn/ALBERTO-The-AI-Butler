"""MCP Capability Discovery Service.

Discovers, fingerprints, tracks schema changes, and optionally projects
integration capabilities into the LadybugDB Knowledge Graph.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from alberto.models import McpClient

logger = logging.getLogger("alberto.services.mcp_discovery")


class McpDiscoveryService:
    """Orchestrates metadata discovery and capability representation for MCP integrations."""

    @classmethod
    def compute_fingerprint(cls, tool_dicts: list[dict[str, Any]]) -> str:
        """Compute stable SHA-256 fingerprint for tool definitions and their schemas."""
        sorted_tools = sorted(tool_dicts, key=lambda t: t.get("name", ""))
        payload = json.dumps(sorted_tools, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def extract_tool_schema(cls, tool: Any) -> dict[str, Any]:
        """Extract schema dictionary from LangChain or MCP StructuredTool."""
        args_schema = getattr(tool, "args_schema", None)
        if args_schema is not None:
            if hasattr(args_schema, "model_json_schema"):
                try:
                    return args_schema.model_json_schema()
                except Exception:
                    pass
            elif hasattr(args_schema, "schema"):
                try:
                    return args_schema.schema()
                except Exception:
                    pass
            elif isinstance(args_schema, dict):
                return args_schema

        # Fallback to direct schema attributes if present
        input_schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
        if isinstance(input_schema, dict):
            return input_schema

        return {"type": "object", "properties": {}}

    @classmethod
    async def discover_tools(
        cls,
        client_row: McpClient,
        tenant_id: str,
        project_id: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Connect to MCP client and return full tool metadata (name, description, schema)."""
        from alberto.tools.mcp import (
            _aclose,
            _connection_for,
            _require_adapters,
            invalidate_client,
        )

        await invalidate_client(client_row.id)
        MultiServerMCPClient = _require_adapters()
        conn = await _connection_for(client_row, tenant_id, project_id, context)
        client = MultiServerMCPClient({client_row.name: conn})

        try:
            tools = await client.get_tools()
            tool_list = []
            for t in tools:
                schema = cls.extract_tool_schema(t)
                tool_list.append({
                    "name": t.name,
                    "description": (getattr(t, "description", "") or "").strip(),
                    "input_schema": schema,
                })
            return tool_list
        finally:
            await _aclose(client)

    @classmethod
    async def discover_and_update(
        cls,
        session: AsyncSession,
        client_row: McpClient,
        tenant_id: str,
        project_id: str,
        discovered_tools: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Discover tools, fingerprint schemas, detect changes, and project to LadybugDB."""
        if discovered_tools is None:
            discovered_tools = await cls.discover_tools(client_row, tenant_id, project_id, context)

        fingerprint = cls.compute_fingerprint(discovered_tools)
        now = datetime.now(UTC)

        # Detect changes against prior discovery
        old_caps = client_row.capabilities or {}
        old_tools_map = {t["name"]: t for t in old_caps.get("tools", [])}
        new_tools_map = {t["name"]: t for t in discovered_tools}

        old_names = set(old_tools_map.keys())
        new_names = set(new_tools_map.keys())

        added_tools = sorted(list(new_names - old_names))
        removed_tools = sorted(list(old_names - new_names))
        changed_tools: list[str] = []

        for name in (old_names & new_names):
            old_hash = hashlib.sha256(json.dumps(old_tools_map[name], sort_keys=True).encode("utf-8")).hexdigest()
            new_hash = hashlib.sha256(json.dumps(new_tools_map[name], sort_keys=True).encode("utf-8")).hexdigest()
            if old_hash != new_hash:
                changed_tools.append(name)
        changed_tools = sorted(changed_tools)

        # Update McpClient metadata
        updated_caps = {
            "tools": discovered_tools,
            "tools_count": len(discovered_tools),
            "added_tools": added_tools,
            "removed_tools": removed_tools,
            "changed_tools": changed_tools,
            "last_fingerprint": fingerprint,
            "last_discovered_at": now.isoformat(),
        }

        client_row.capabilities = updated_caps
        client_row.schema_fingerprint = fingerprint
        client_row.last_discovered_at = now
        await session.commit()
        await session.refresh(client_row)

        # Synchronize discovered tools to the Tool registry and ToolSet
        try:
            await cls.sync_tools_to_registry(
                session=session,
                client_row=client_row,
                tenant_id=tenant_id,
                project_id=project_id,
                discovered_tools=discovered_tools,
            )
        except Exception as e:
            logger.warning("Failed to sync MCP tools to registry: %s", e)

        # Project capabilities into LadybugDB Knowledge Graph via GraphManagerService
        try:
            from alberto.knowledge.graph import (
                GraphEntity,
                GraphRelationship,
                make_entity_id,
                make_relationship_id,
            )
            from alberto.services.graph_manager import GraphManagerService

            entities: list[GraphEntity] = []
            relationships: list[GraphRelationship] = []

            # 1. Integration entity node
            integration_ent = GraphEntity(
                id=make_entity_id(tenant_id, project_id, client_row.name),
                tenant_id=tenant_id,
                project_id=project_id,
                name=client_row.name,
                canonical_name=client_row.name.strip().lower(),
                kind="integration",
                description=f"MCP Integration: {client_row.name} ({client_row.transport})",
                source=f"mcp:{client_row.id}",
                confidence=1.0,
            )
            entities.append(integration_ent)

            # 2. Capability entity nodes and PROVIDES relationships
            for t in discovered_tools:
                cap_name = f"{client_row.name}: {t['name']}"
                cap_ent = GraphEntity(
                    id=make_entity_id(tenant_id, project_id, cap_name),
                    tenant_id=tenant_id,
                    project_id=project_id,
                    name=cap_name,
                    canonical_name=cap_name.strip().lower(),
                    kind="capability",
                    description=t.get("description") or f"Capability {t['name']}",
                    source=f"mcp:{client_row.id}:{t['name']}",
                    confidence=1.0,
                )
                entities.append(cap_ent)

                rel = GraphRelationship(
                    id=make_relationship_id(tenant_id, project_id, integration_ent.id, cap_ent.id, "PROVIDES"),
                    source_id=integration_ent.id,
                    target_id=cap_ent.id,
                    kind="PROVIDES",
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source=f"mcp:{client_row.id}",
                    confidence=1.0,
                )
                relationships.append(rel)

            await GraphManagerService.apply_resolved(
                tenant_id=tenant_id,
                project_id=project_id,
                resolved_entities=entities,
                resolved_relationships=relationships,
            )
        except Exception as e:
            logger.warning("Failed to project MCP capabilities to LadybugDB via GraphManagerService: %s", e)

        # Trigger event-driven tool analysis in background if tools are present
        try:
            import asyncio

            from sqlalchemy import select

            from alberto.models import Tool
            from alberto.services.tool_manager import ToolManagerService

            t_rows = (await session.execute(
                select(Tool.id).where(
                    Tool.tenant_id == tenant_id,
                    Tool.project_id == project_id,
                    Tool.kind == "mcp",
                )
            )).scalars().all()
            if t_rows:
                asyncio.create_task(
                    ToolManagerService.analyze_discovered_tools(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        tool_ids=list(t_rows),
                        integration_name=client_row.name,
                    )
                )
        except Exception as e:
            logger.debug("Could not schedule MCP Tool Manager analysis: %s", e)

        return {
            "client_id": client_row.id,
            "name": client_row.name,
            "tools_count": len(discovered_tools),
            "fingerprint": fingerprint,
            "added_tools": added_tools,
            "removed_tools": removed_tools,
            "changed_tools": changed_tools,
            "last_discovered_at": now.isoformat(),
        }

    @classmethod
    async def sync_tools_to_registry(
        cls,
        session: AsyncSession,
        client_row: McpClient,
        tenant_id: str,
        project_id: str,
        discovered_tools: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """Materialize or update discovered MCP tools in the project Tool table and ToolSet."""
        from sqlalchemy import select
        from alberto.models import Tool, ToolSet, ToolSetMember

        if discovered_tools is None:
            caps = client_row.capabilities or {}
            discovered_tools = caps.get("tools") or []

        if not discovered_tools:
            return []

        # 1. Ensure ToolSet exists for this MCP integration
        ts_slug = f"mcp-{client_row.id[:8]}"
        ts = (await session.execute(
            select(ToolSet).where(
                ToolSet.tenant_id == tenant_id,
                ToolSet.project_id == project_id,
                (ToolSet.slug == ts_slug) | (ToolSet.name == client_row.name),
            )
        )).scalars().first()

        if ts is None:
            ts = ToolSet(
                tenant_id=tenant_id,
                project_id=project_id,
                name=client_row.name,
                slug=ts_slug,
                description=f"Tools discovered from MCP integration {client_row.name}",
                icon="plug-zap",
                is_default=False,
                exposed=True,
            )
            session.add(ts)
            await session.flush()

        # 2. Query existing Tool rows for this MCP client
        existing_tools = list((await session.execute(
            select(Tool).where(
                Tool.tenant_id == tenant_id,
                Tool.project_id == project_id,
                Tool.kind == "mcp",
            )
        )).scalars().all())

        have_by_remote = {
            (t.config or {}).get("remote_tool_name"): t
            for t in existing_tools
            if (t.config or {}).get("mcp_client_id") == client_row.id
        }

        disabled_set = set(client_row.disabled_tools or [])
        materialized_tool_ids: list[str] = []

        for t in discovered_tools:
            remote_name = t.get("name") or ""
            if not remote_name:
                continue
            desc = (t.get("description") or "").strip()
            schema = t.get("input_schema") or {}
            is_enabled = client_row.enabled and (remote_name not in disabled_set)

            tool = have_by_remote.get(remote_name)
            if tool is not None:
                cfg = dict(tool.config or {})
                cfg.update({
                    "description": desc,
                    "mcp_client_id": client_row.id,
                    "remote_tool_name": remote_name,
                    "input_schema": schema,
                })
                tool.config = cfg
                tool.auth_provider_id = client_row.auth_provider_id
                tool.enabled = is_enabled
                materialized_tool_ids.append(tool.id)
            else:
                new_tool = Tool(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    name=remote_name,
                    kind="mcp",
                    config={
                        "name": remote_name,
                        "kind": "mcp",
                        "description": desc,
                        "mcp_client_id": client_row.id,
                        "remote_tool_name": remote_name,
                        "input_schema": schema,
                    },
                    auth_provider_id=client_row.auth_provider_id,
                    enabled=is_enabled,
                )
                session.add(new_tool)
                await session.flush()
                materialized_tool_ids.append(new_tool.id)

        # 3. Ensure membership in ToolSet
        if materialized_tool_ids and ts:
            existing_members = set((await session.execute(
                select(ToolSetMember.tool_id).where(
                    ToolSetMember.tenant_id == tenant_id,
                    ToolSetMember.tool_set_id == ts.id,
                )
            )).scalars().all())

            for tid in materialized_tool_ids:
                if tid not in existing_members:
                    session.add(ToolSetMember(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        tool_set_id=ts.id,
                        tool_id=tid,
                    ))

        await session.commit()
        return materialized_tool_ids

