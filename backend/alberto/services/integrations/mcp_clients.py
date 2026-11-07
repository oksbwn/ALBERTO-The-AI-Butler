"""Service for MCP Client persistence and lifecycle management."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.models import ConnectorInstall, McpClient, Tool, ToolSet, ToolSetMember
from alberto.services.tools import ToolService

log = logging.getLogger("alberto.services.mcp_clients")


def serialize_mcp_client(m: McpClient) -> dict[str, Any]:
    return {
        "id": m.id,
        "name": m.name,
        "transport": m.transport,
        "url": m.url,
        "command": m.command,
        "args": m.args,
        "headers_ref": m.headers_ref,
        "enabled": m.enabled,
        "disabled_tools": m.disabled_tools or [],
        "auth_provider_id": m.auth_provider_id,
        "capabilities": m.capabilities or {},
        "last_discovered_at": m.last_discovered_at.isoformat() if m.last_discovered_at else None,
        "schema_fingerprint": m.schema_fingerprint,
        "learning_enabled": m.learning_enabled,
    }


class McpClientService:
    @staticmethod
    async def list(session: AsyncSession, tenant_id: str, project_id: str) -> list[dict[str, Any]]:
        rows = list((await session.execute(
            select(McpClient).where(McpClient.tenant_id == tenant_id, McpClient.project_id == project_id)
        )).scalars())
        owned = {
            i.mcp_client_id: i.slug
            for i in (await session.execute(
                select(ConnectorInstall).where(
                    ConnectorInstall.tenant_id == tenant_id, ConnectorInstall.project_id == project_id,
                )
            )).scalars()
            if i.mcp_client_id
        }
        return [{**serialize_mcp_client(m), "connector_slug": owned.get(m.id)} for m in rows]

    @staticmethod
    async def get(session: AsyncSession, tenant_id: str, client_id: str) -> McpClient | None:
        return (await session.execute(
            select(McpClient).where(McpClient.tenant_id == tenant_id, McpClient.id == client_id)
        )).scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        *,
        name: str,
        transport: str,
        url: str | None = None,
        command: str | None = None,
        args: dict | None = None,
        headers_ref: str | None = None,
        enabled: bool = True,
        auth_provider_id: str | None = None,
    ) -> McpClient:
        m = McpClient(
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            transport=transport,
            url=url,
            command=command,
            args=args or {},
            headers_ref=headers_ref,
            enabled=enabled,
            auth_provider_id=auth_provider_id,
        )
        session.add(m)
        await session.commit()
        await session.refresh(m)
        return m

    @staticmethod
    async def update(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        m: McpClient,
        *,
        name: str | None = None,
        enabled: bool | None = None,
        disabled_tools: list | None = None,
        url: str | None = None,
        headers_ref: str | None = None,
        auth_provider_id: str | None = None,
        learning_enabled: bool | None = None,
    ) -> McpClient:
        if name is not None:
            m.name = name
        if enabled is not None:
            m.enabled = enabled
        if disabled_tools is not None:
            m.disabled_tools = disabled_tools
        if url is not None:
            m.url = url
        if headers_ref is not None:
            m.headers_ref = headers_ref
        if auth_provider_id is not None:
            m.auth_provider_id = auth_provider_id or None
        if learning_enabled is not None:
            m.learning_enabled = learning_enabled

        if enabled is not None or disabled_tools is not None:
            existing_tools = list((await session.execute(
                select(Tool).where(Tool.tenant_id == tenant_id, Tool.project_id == project_id, Tool.kind == "mcp")
            )).scalars().all())
            disabled_set = set(m.disabled_tools or [])
            client_enabled = m.enabled
            for t in existing_tools:
                if (t.config or {}).get("mcp_client_id") == m.id:
                    remote_name = (t.config or {}).get("remote_tool_name") or t.name
                    t.enabled = client_enabled and (remote_name not in disabled_set)

        await session.commit()
        await session.refresh(m)
        from alberto.tools.mcp import invalidate_client
        await invalidate_client(m.id)
        return m

    @staticmethod
    async def delete(session: AsyncSession, tenant_id: str, project_id: str, m: McpClient) -> list[dict[str, Any]] | None:
        """Deletes MCP client, associated tools, toolsets, and graph projections.
        Returns active usages list if deletion was blocked by active usages."""
        tools = list((await session.execute(
            select(Tool).where(Tool.tenant_id == tenant_id, Tool.project_id == project_id, Tool.kind == "mcp")
        )).scalars().all())

        mcp_tool_ids = [t.id for t in tools if (t.config or {}).get("mcp_client_id") == m.id]
        mcp_tool_names = [t.name for t in tools if (t.config or {}).get("mcp_client_id") == m.id]
        usages = await ToolService.get_tool_usages(session, tenant_id, project_id, mcp_tool_ids, mcp_tool_names)
        if usages:
            return usages

        for t in tools:
            if (t.config or {}).get("mcp_client_id") == m.id:
                await ToolService.delete(session, t)

        ts_slug = f"mcp-{m.id[:8]}"
        ts = (await session.execute(
            select(ToolSet).where(
                ToolSet.tenant_id == tenant_id,
                ToolSet.project_id == project_id,
                (ToolSet.slug == ts_slug) | (ToolSet.name == m.name),
            )
        )).scalars().first()
        if ts is not None:
            await session.execute(delete(ToolSetMember).where(ToolSetMember.tool_set_id == ts.id))
            await session.delete(ts)

        try:
            from alberto.knowledge.graph import get_graph_adapter, make_entity_id
            adapter = get_graph_adapter()
            await adapter.delete_entity(tenant_id, project_id, make_entity_id(tenant_id, project_id, m.name))
            await adapter.delete_entity(tenant_id, project_id, make_entity_id(tenant_id, project_id, f"int:{m.name}"))
            await adapter.delete_entities_by_source(tenant_id, project_id, f"mcp:{m.id}")
            await adapter.delete_entities_by_source(tenant_id, project_id, f"integration:{m.name}")
            for t in tools:
                if (t.config or {}).get("mcp_client_id") == m.id:
                    await adapter.delete_entities_by_source(tenant_id, project_id, f"tool:{t.id}")
                    await adapter.delete_entity(tenant_id, project_id, make_entity_id(tenant_id, project_id, f"tool:{t.name}"))
        except Exception as e:
            log.debug(f"Knowledge graph cleanup skipped/failed for integration {m.name}: {e}")

        await session.delete(m)
        await session.commit()
        from alberto.tools.mcp import invalidate_client
        await invalidate_client(m.id)
        return None

