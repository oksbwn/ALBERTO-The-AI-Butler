"""MCP client CRUD - register external MCP servers a project's tools can consume."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.deps import CurrentUser, current_tenant_id, get_current_user, get_session, require_role
from alberto.services.integrations.mcp_clients import McpClientService, serialize_mcp_client

log = logging.getLogger("alberto.routers.mcp_clients")
router = APIRouter(prefix="/v1/projects/{project_id}/mcp-clients", tags=["mcp-clients"])


class McpClientIn(BaseModel):
    name: str
    transport: str = "streamable_http"  # streamable_http | sse | stdio
    url: str | None = None
    command: str | None = None
    args: dict = {}
    headers_ref: str | None = None
    enabled: bool = True
    auth_provider_id: str | None = None
    learning_enabled: bool = False


class McpClientPatch(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    disabled_tools: list | None = None
    url: str | None = None
    headers_ref: str | None = None
    auth_provider_id: str | None = None
    learning_enabled: bool | None = None


class McpLearningToggleIn(BaseModel):
    learning_enabled: bool


def _validate_stdio_security(transport: str | None, command: str | None, user: CurrentUser) -> None:
    if transport == "stdio":
        from alberto.config import settings

        if not settings.enable_mcp_stdio:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "MCP stdio transport is disabled by deployment policy (FORGE_ENABLE_MCP_STDIO=false).",
            )
        if getattr(user, "role", None) != "admin":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Configuring MCP stdio executable commands requires administrator privileges.",
            )
        cmd = (command or "").strip()
        if not cmd or any(c in cmd for c in (";", "&", "|", "`", "$", ">", "<", "\n")):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Invalid or unsafe executable command for MCP stdio. Shell metacharacters are forbidden.",
            )
        if not settings.mcp_stdio_allowed_commands:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "MCP stdio configuration is blocked: mcp_stdio_allowed_commands is empty or unconfigured. A nonempty command allowlist is required.",
            )
        if cmd not in settings.mcp_stdio_allowed_commands:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"MCP stdio command {cmd!r} is not in the allowed commands list.",
            )


@router.get("")
async def list_clients(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
):
    """Registered MCP servers, each flagged with the connector that owns it (if any)."""
    return await McpClientService.list(session, tenant_id, project_id)


@router.post("", status_code=201)
async def create_client(
    project_id: str,
    body: McpClientIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    _validate_stdio_security(body.transport, body.command, user)
    m = await McpClientService.create(
        session,
        tenant_id,
        project_id,
        name=body.name,
        transport=body.transport,
        url=body.url,
        command=body.command,
        args=body.args,
        headers_ref=body.headers_ref,
        enabled=body.enabled,
        auth_provider_id=body.auth_provider_id,
    )
    try:
        from alberto.services.mcp_discovery import McpDiscoveryService
        await McpDiscoveryService.discover_and_update(
            session=session,
            client_row=m,
            tenant_id=tenant_id,
            project_id=project_id,
            context={"end_user_id": user.id},
        )
    except Exception as e:
        log.warning(f"Initial discovery failed for {m.name}: {e}")
    return serialize_mcp_client(m)


@router.patch("/{client_id}")
async def update_client(
    project_id: str,
    client_id: str,
    body: McpClientPatch,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    m = await McpClientService.get(session, tenant_id, client_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mcp client not found")
    if m.transport == "stdio":
        _validate_stdio_security(m.transport, m.command, user)

    m = await McpClientService.update(
        session,
        tenant_id,
        project_id,
        m,
        name=body.name,
        enabled=body.enabled,
        disabled_tools=body.disabled_tools,
        url=body.url,
        headers_ref=body.headers_ref,
        auth_provider_id=body.auth_provider_id,
        learning_enabled=body.learning_enabled,
    )
    return serialize_mcp_client(m)


@router.post("/{client_id}/refresh")
async def refresh_capabilities(
    project_id: str,
    client_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(get_current_user),
    _: CurrentUser = Depends(require_role("editor")),
):
    """Explicitly discover and refresh integration tool schemas, fingerprint, and graph representation."""
    from alberto.services.mcp_discovery import McpDiscoveryService
    from alberto.tools.mcp import McpUnavailable, describe_mcp_error

    row = await McpClientService.get(session, tenant_id, client_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mcp client not found")

    try:
        summary = await McpDiscoveryService.discover_and_update(
            session=session,
            client_row=row,
            tenant_id=tenant_id,
            project_id=project_id,
            context={"end_user_id": user.id},
        )
        return {"ok": True, "discovery": summary, "client": serialize_mcp_client(row)}
    except McpUnavailable as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Discovery failed: {describe_mcp_error(e)}"}


@router.patch("/{client_id}/learning")
async def update_learning_toggle(
    project_id: str,
    client_id: str,
    body: McpLearningToggleIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("editor")),
):
    """Toggle tool execution learning permission for this specific integration."""
    row = await McpClientService.get(session, tenant_id, client_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mcp client not found")

    row = await McpClientService.update(
        session,
        tenant_id,
        project_id,
        row,
        learning_enabled=body.learning_enabled,
    )
    return {"ok": True, "learning_enabled": row.learning_enabled}


@router.get("/{client_id}/capabilities")
async def get_capabilities(
    project_id: str,
    client_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
):
    """Retrieve cached discovery capabilities and fingerprint without triggering remote connection."""
    row = await McpClientService.get(session, tenant_id, client_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mcp client not found")

    return {
        "ok": True,
        "capabilities": row.capabilities or {},
        "schema_fingerprint": row.schema_fingerprint,
        "last_discovered_at": row.last_discovered_at.isoformat() if row.last_discovered_at else None,
        "learning_enabled": row.learning_enabled,
    }


@router.get("/{client_id}/tools")
async def list_remote_tools(
    project_id: str,
    client_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(get_current_user),
):
    """Connect to the server and list the tools it exposes."""
    from alberto.tools.mcp import McpUnavailable, describe_mcp_error, discover_tools

    row = await McpClientService.get(session, tenant_id, client_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mcp client not found")
    try:
        tools = await discover_tools(row, tenant_id, project_id, {"end_user_id": user.id})
    except McpUnavailable as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Could not connect: {describe_mcp_error(e)}"}
    return {"ok": True, "tools": tools}


@router.delete("/{client_id}")
async def delete_client(
    project_id: str,
    client_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("editor")),
):
    m = await McpClientService.get(session, tenant_id, client_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mcp client not found")

    usages = await McpClientService.delete(session, tenant_id, project_id, m)
    if usages:
        items_desc = ", ".join(f"{u['target_type']} '{u['target_name']}'" for u in usages[:5])
        if len(usages) > 5:
            items_desc += f" and {len(usages) - 5} more"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot remove integration: {len(usages)} workflow(s) or agent(s) ({items_desc}) are currently using its tools. Please remove or replace these tools before removing the integration.",
        )
    return {"ok": True}
