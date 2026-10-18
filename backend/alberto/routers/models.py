"""Unified Model Registry & Provider Management Router.

Exposes REST APIs for:
- ModelServer management (CRUD, reachability testing, model discovery)
- RegisteredModel management (CRUD, attribute tuning, inference testing, tool-calling validation)
- Default model assignment
- Unified model picker catalog (Zero-Phantom Policy)
- Backward compatibility for legacy endpoints
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from alberto.deps import CurrentUser, get_current_user, get_session, require_role
from alberto.engine.providers import (
    ProviderAdapter,
    get_adapter_for_server,
    normalize_base_url,
)
from alberto.model_catalog import EMBEDDING_MODELS, RERANKER_MODELS
from alberto.models.entities import (
    Agent,
    ModelServer,
    Project,
    RegisteredModel,
    Tenant,
)
from alberto.secrets.store import SecretStore

log = logging.getLogger("forge.routers.models")
router = APIRouter(prefix="/v1/models", tags=["models"])

# Lightweight in-memory runtime cache for server and model health (avoids continuous polling)
_RUNTIME_STATUS: dict[str, dict[str, Any]] = {}


# --- Pydantic Schemas ---

class ModelServerCreate(BaseModel):
    name: str
    provider_type: str = Field(description="ollama|lm_studio|vllm|openai_compatible|openai|anthropic|google|groq|deepseek|mistral")
    base_url: str = ""
    api_key: str | None = None
    api_key_ref: str | None = None
    enabled: bool = True


class ModelServerUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    api_key_ref: str | None = None
    enabled: bool | None = None


class ModelServerOut(BaseModel):
    id: str
    name: str
    provider_type: str
    base_url: str
    api_key_configured: bool = False
    api_key_ref: str | None = None
    enabled: bool = True
    registered_models_count: int = 0
    status: str = "unknown"
    last_connected_at: str | None = None
    created_at: datetime
    updated_at: datetime


class ServerTestIn(BaseModel):
    provider_type: str
    base_url: str = ""
    api_key: str | None = None


class ServerTestOut(BaseModel):
    ok: bool
    status_code: int | None = None
    latency_ms: int = 0
    discovered_count: int = 0
    error: str | None = None


class DiscoveredModelItem(BaseModel):
    model_name: str
    display_name: str
    context_window_max: int | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    is_registered: bool = False
    registered_model_id: str | None = None


class ServerDiscoverOut(BaseModel):
    ok: bool
    server_id: str
    models: list[DiscoveredModelItem] = []
    error: str | None = None


class RegisteredModelCreate(BaseModel):
    server_id: str
    model_name: str
    display_name: str | None = None
    enabled: bool = True
    context_window_max: int | None = None
    context_window_configured: int | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    temperature: float | None = 0.3
    top_p: float | None = 0.9
    max_output_tokens: int | None = 4096
    set_as_default: bool = False
    project_id: str | None = None


class RegisteredModelUpdate(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    context_window_max: int | None = None
    context_window_configured: int | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    set_as_default: bool | None = None
    project_id: str | None = None


class RegisteredModelOut(BaseModel):
    id: str
    server_id: str
    server_name: str
    provider_type: str
    model_name: str
    display_name: str
    enabled: bool = True
    context_window_max: int | None = None
    context_window_configured: int | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    is_default: bool = False
    availability: str = "available"  # available | unavailable | unknown
    created_at: datetime
    updated_at: datetime


class TestInferenceIn(BaseModel):
    prompt: str = "Say 'Alberto inference ok' in 4 words or less."


class TestInferenceOut(BaseModel):
    ok: bool
    latency_ms: int = 0
    response_snippet: str | None = None
    error: str | None = None


class TestToolsOut(BaseModel):
    ok: bool
    latency_ms: int = 0
    tool_called: str | None = None
    tool_args: Any = None
    error: str | None = None


class SetDefaultModelIn(BaseModel):
    model_id: str
    project_id: str | None = None


class ChatModelCatalogOut(BaseModel):
    id: str
    name: str
    provider: str
    ctx: str
    ctx_tokens: int = 32768
    tools: bool
    vision: bool
    is_default: bool = False
    available: bool = True


class EmbeddingModelOut(BaseModel):
    id: str
    name: str
    provider: str
    dim: int
    billed: bool
    default: bool


class RerankerModelOut(BaseModel):
    id: str
    name: str
    note: str
    default: bool


class UnifiedCatalogOut(BaseModel):
    chat: list[ChatModelCatalogOut]
    embedding: list[EmbeddingModelOut]
    reranker: list[RerankerModelOut]


# --- Helper Utilities ---

async def _resolve_server_key(session: AsyncSession, tenant_id: str, server: ModelServer) -> str | None:
    """Resolve API key plaintext from api_key_ref if configured."""
    if not server.api_key_ref:
        return None
    try:
        store = SecretStore()
        # Find any project for the tenant to read the secret
        proj = (await session.execute(select(Project).where(Project.tenant_id == tenant_id))).scalars().first()
        proj_id = proj.id if proj else "default"
        val = await store.read_ref(tenant_id=tenant_id, project_id=proj_id, ref=server.api_key_ref)
        if isinstance(val, dict):
            return str(val.get("key") or val.get("value") or "")
        return str(val) if val else None
    except Exception as e:
        log.warning("Could not resolve server secret ref %s: %s", server.api_key_ref, e)
        return None


async def _get_default_model_id(session: AsyncSession, tenant_id: str, project_id: str | None = None) -> str | None:
    """Retrieve the single default_model_id reference."""
    if project_id:
        proj = await session.get(Project, project_id)
        if proj and proj.config:
            d_id = proj.config.get("default_model_id") or proj.config.get("default_model")
            if d_id:
                return str(d_id)
    tenant = await session.get(Tenant, tenant_id)
    if tenant and tenant.settings:
        return tenant.settings.get("default_model_id") or tenant.settings.get("default_model")
    return None


async def _set_default_model_id(session: AsyncSession, tenant_id: str, model_id: str, project_id: str | None = None) -> None:
    """Persist default_model_id to project config (or tenant settings)."""
    if project_id:
        proj = await session.get(Project, project_id)
        if proj:
            cfg = dict(proj.config or {})
            cfg["default_model_id"] = model_id
            cfg["default_model"] = model_id
            proj.config = cfg
            flag_modified(proj, "config")
    tenant = await session.get(Tenant, tenant_id)
    if tenant:
        t_settings = dict(tenant.settings or {})
        t_settings["default_model_id"] = model_id
        t_settings["default_model"] = model_id
        tenant.settings = t_settings
        flag_modified(tenant, "settings")
    await session.commit()


async def _auto_migrate_legacy_providers(session: AsyncSession, tenant_id: str) -> None:
    """Auto-migrate legacy tenant.settings.model_providers into first-class SQLite tables."""
    try:
        tenant = await session.get(Tenant, tenant_id)
        if not tenant or not tenant.settings:
            return
        legacy_provs = tenant.settings.get("model_providers", [])
        if not legacy_provs:
            return

        existing_srv_count = (await session.execute(
            select(ModelServer).where(ModelServer.tenant_id == tenant_id)
        )).scalars().first()
        if existing_srv_count:
            return  # Already migrated

        for lp in legacy_provs:
            srv = ModelServer(
                id=lp.get("id") or f"srv_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name=lp.get("name", "Local Engine"),
                provider_type=lp.get("type", "openai_compatible"),
                base_url=lp.get("base_url", "http://localhost:11434"),
                api_key_ref=None,
                enabled=lp.get("enabled", True),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(srv)
            await session.flush()

            for dm in lp.get("discovered_models", []):
                m_name = dm.get("name") or dm.get("id", "model")
                if ":" in m_name and m_name.startswith("custom:"):
                    m_name = m_name.split(":")[-1]
                rm = RegisteredModel(
                    id=f"mod_{uuid.uuid4().hex[:8]}",
                    tenant_id=tenant_id,
                    server_id=srv.id,
                    model_name=m_name,
                    display_name=dm.get("name") or m_name,
                    enabled=True,
                    context_window_max=131072,
                    context_window_configured=32768,
                    supports_tools=dm.get("tools", True),
                    supports_vision=dm.get("vision", False),
                    temperature=0.3,
                    top_p=0.9,
                    max_output_tokens=4096,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                session.add(rm)
        await session.commit()
    except Exception as e:
        log.warning("Auto-migration of legacy model providers error: %s", e)


# --- Server Management Routes ---

@router.get("/servers", response_model=list[ModelServerOut])
async def list_servers(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> list[ModelServerOut]:
    await _auto_migrate_legacy_providers(session, user.tenant_id)
    servers = (await session.execute(
        select(ModelServer).where(ModelServer.tenant_id == user.tenant_id).order_by(ModelServer.created_at.desc())
    )).scalars().all()

    out: list[ModelServerOut] = []
    for s in servers:
        model_count = (await session.execute(
            select(RegisteredModel).where(RegisteredModel.tenant_id == user.tenant_id, RegisteredModel.server_id == s.id)
        )).scalars().all()
        status_info = _RUNTIME_STATUS.get(s.id, {})
        out.append(
            ModelServerOut(
                id=s.id,
                name=s.name,
                provider_type=s.provider_type,
                base_url=s.base_url,
                api_key_configured=bool(s.api_key_ref),
                api_key_ref=s.api_key_ref,
                enabled=s.enabled,
                registered_models_count=len(model_count),
                status="healthy" if status_info.get("reachable") else ("unreachable" if status_info.get("reachable") is False else "unknown"),
                last_connected_at=status_info.get("last_connected_at"),
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
        )
    return out


@router.post("/servers", response_model=ModelServerOut, status_code=status.HTTP_201_CREATED)
async def create_server(
    body: ModelServerCreate,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> ModelServerOut:
    norm_url = normalize_base_url(body.base_url, body.provider_type)
    server_id = f"srv_{uuid.uuid4().hex[:8]}"

    api_key_ref = body.api_key_ref
    if body.api_key and body.api_key.strip():
        # Persist to secret store
        store = SecretStore()
        proj = (await session.execute(select(Project).where(Project.tenant_id == user.tenant_id))).scalars().first()
        proj_id = proj.id if proj else "default"
        sec_name = f"model_server_{server_id}_key"
        await store.write(session, tenant_id=user.tenant_id, project_id=proj_id, name=sec_name, value=body.api_key.strip(), kind="api_key")
        api_key_ref = f"secret://proj/{sec_name}"

    now = datetime.now(UTC)
    server = ModelServer(
        id=server_id,
        tenant_id=user.tenant_id,
        name=body.name.strip(),
        provider_type=body.provider_type,
        base_url=norm_url,
        api_key_ref=api_key_ref,
        enabled=body.enabled,
        created_at=now,
        updated_at=now,
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)

    return ModelServerOut(
        id=server.id,
        name=server.name,
        provider_type=server.provider_type,
        base_url=server.base_url,
        api_key_configured=bool(server.api_key_ref),
        api_key_ref=server.api_key_ref,
        enabled=server.enabled,
        registered_models_count=0,
        status="unknown",
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


@router.patch("/servers/{server_id}", response_model=ModelServerOut)
async def update_server(
    server_id: str,
    body: ModelServerUpdate,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> ModelServerOut:
    server = await session.get(ModelServer, server_id)
    if not server or server.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model server not found")

    if body.name is not None:
        server.name = body.name.strip()
    if body.base_url is not None:
        server.base_url = normalize_base_url(body.base_url, server.provider_type)
    if body.enabled is not None:
        server.enabled = body.enabled

    if body.api_key is not None:
        if body.api_key.strip():
            store = SecretStore()
            proj = (await session.execute(select(Project).where(Project.tenant_id == user.tenant_id))).scalars().first()
            proj_id = proj.id if proj else "default"
            sec_name = f"model_server_{server_id}_key"
            await store.write(session, tenant_id=user.tenant_id, project_id=proj_id, name=sec_name, value=body.api_key.strip(), kind="api_key")
            server.api_key_ref = f"secret://proj/{sec_name}"
        else:
            server.api_key_ref = None
    elif body.api_key_ref is not None:
        server.api_key_ref = body.api_key_ref

    server.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(server)

    model_count = (await session.execute(
        select(RegisteredModel).where(RegisteredModel.tenant_id == user.tenant_id, RegisteredModel.server_id == server.id)
    )).scalars().all()

    status_info = _RUNTIME_STATUS.get(server.id, {})
    return ModelServerOut(
        id=server.id,
        name=server.name,
        provider_type=server.provider_type,
        base_url=server.base_url,
        api_key_configured=bool(server.api_key_ref),
        api_key_ref=server.api_key_ref,
        enabled=server.enabled,
        registered_models_count=len(model_count),
        status="healthy" if status_info.get("reachable") else ("unreachable" if status_info.get("reachable") is False else "unknown"),
        last_connected_at=status_info.get("last_connected_at"),
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: str,
    force: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> None:
    server = await session.get(ModelServer, server_id)
    if not server or server.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model server not found")

    models = (await session.execute(
        select(RegisteredModel).where(RegisteredModel.tenant_id == user.tenant_id, RegisteredModel.server_id == server_id)
    )).scalars().all()

    if models and not force:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot delete server '{server.name}': {len(models)} registered models depend on it. Remove models first or specify force=true."
        )

    # Clean up associated models if force
    if force and models:
        for m in models:
            await session.delete(m)

    await session.delete(server)
    await session.commit()
    _RUNTIME_STATUS.pop(server_id, None)


@router.post("/servers/test", response_model=ServerTestOut)
async def test_server_connectivity(
    body: ServerTestIn,
    _: CurrentUser = Depends(require_role("editor")),
) -> ServerTestOut:
    norm_url = normalize_base_url(body.base_url, body.provider_type)
    adapter = ProviderAdapter(provider_type=body.provider_type, base_url=norm_url, api_key=body.api_key)
    t0 = time.perf_counter()
    ok, status_code, count, err = await adapter.test_connection()
    latency = int((time.perf_counter() - t0) * 1000)
    return ServerTestOut(
        ok=ok,
        status_code=status_code,
        latency_ms=latency,
        discovered_count=count,
        error=err,
    )


@router.post("/servers/{server_id}/discover", response_model=ServerDiscoverOut)
async def discover_server_models(
    server_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> ServerDiscoverOut:
    server = await session.get(ModelServer, server_id)
    if not server or server.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model server not found")

    key = await _resolve_server_key(session, user.tenant_id, server)
    adapter = get_adapter_for_server(server, key)
    discovered = await adapter.discover_models()

    # Query currently registered models on this server to mark is_registered
    existing_models = (await session.execute(
        select(RegisteredModel).where(RegisteredModel.tenant_id == user.tenant_id, RegisteredModel.server_id == server_id)
    )).scalars().all()
    reg_by_name = {m.model_name: m.id for m in existing_models}

    items = []
    for d in discovered:
        m_name = d["model_name"]
        reg_id = reg_by_name.get(m_name)
        items.append(
            DiscoveredModelItem(
                model_name=m_name,
                display_name=d.get("display_name") or m_name,
                context_window_max=d.get("context_window_max"),
                supports_tools=d.get("supports_tools"),
                supports_vision=d.get("supports_vision"),
                is_registered=reg_id is not None,
                registered_model_id=reg_id,
            )
        )

    # Update runtime status
    _RUNTIME_STATUS[server_id] = {
        "reachable": len(items) > 0,
        "last_connected_at": datetime.now(UTC).isoformat(),
        "discovered_count": len(items),
    }

    return ServerDiscoverOut(
        ok=True,
        server_id=server_id,
        models=items,
        error=None if items else "No models discovered at endpoint",
    )


# --- Model Registry Routes ---

@router.get("/registry", response_model=list[RegisteredModelOut])
async def list_registered_models(
    project_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> list[RegisteredModelOut]:
    await _auto_migrate_legacy_providers(session, user.tenant_id)
    models = (await session.execute(
        select(RegisteredModel).where(RegisteredModel.tenant_id == user.tenant_id).order_by(RegisteredModel.created_at.desc())
    )).scalars().all()

    servers = {s.id: s for s in (await session.execute(
        select(ModelServer).where(ModelServer.tenant_id == user.tenant_id)
    )).scalars().all()}

    default_id = await _get_default_model_id(session, user.tenant_id, project_id)

    out: list[RegisteredModelOut] = []
    for m in models:
        srv = servers.get(m.server_id)
        srv_name = srv.name if srv else "Unknown Server"
        p_type = srv.provider_type if srv else "custom"
        avail = "available" if (srv and srv.enabled and m.enabled) else "unavailable"

        out.append(
            RegisteredModelOut(
                id=m.id,
                server_id=m.server_id,
                server_name=srv_name,
                provider_type=p_type,
                model_name=m.model_name,
                display_name=m.display_name,
                enabled=m.enabled,
                context_window_max=m.context_window_max,
                context_window_configured=m.context_window_configured,
                supports_tools=m.supports_tools,
                supports_vision=m.supports_vision,
                temperature=m.temperature,
                top_p=m.top_p,
                max_output_tokens=m.max_output_tokens,
                is_default=(m.id == default_id or m.model_name == default_id),
                availability=avail,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
        )
    return out


@router.post("/registry", response_model=RegisteredModelOut, status_code=status.HTTP_201_CREATED)
async def register_model(
    body: RegisteredModelCreate,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> RegisteredModelOut:
    server = await session.get(ModelServer, body.server_id)
    if not server or server.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model server not found")

    # Check for existing registration of same model on same server
    existing = (await session.execute(
        select(RegisteredModel).where(
            RegisteredModel.tenant_id == user.tenant_id,
            RegisteredModel.server_id == body.server_id,
            RegisteredModel.model_name == body.model_name.strip(),
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Model '{body.model_name}' is already registered on this server.")

    now = datetime.now(UTC)
    m_id = f"mod_{uuid.uuid4().hex[:8]}"
    model = RegisteredModel(
        id=m_id,
        tenant_id=user.tenant_id,
        server_id=body.server_id,
        model_name=body.model_name.strip(),
        display_name=(body.display_name or body.model_name).strip(),
        enabled=body.enabled,
        context_window_max=body.context_window_max,
        context_window_configured=body.context_window_configured or body.context_window_max or 32768,
        supports_tools=body.supports_tools,
        supports_vision=body.supports_vision,
        temperature=body.temperature,
        top_p=body.top_p,
        max_output_tokens=body.max_output_tokens,
        created_at=now,
        updated_at=now,
    )
    session.add(model)
    await session.commit()
    await session.refresh(model)

    if body.set_as_default:
        await _set_default_model_id(session, user.tenant_id, model.id, body.project_id)

    return RegisteredModelOut(
        id=model.id,
        server_id=server.id,
        server_name=server.name,
        provider_type=server.provider_type,
        model_name=model.model_name,
        display_name=model.display_name,
        enabled=model.enabled,
        context_window_max=model.context_window_max,
        context_window_configured=model.context_window_configured,
        supports_tools=model.supports_tools,
        supports_vision=model.supports_vision,
        temperature=model.temperature,
        top_p=model.top_p,
        max_output_tokens=model.max_output_tokens,
        is_default=body.set_as_default,
        availability="available",
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@router.patch("/registry/{model_id}", response_model=RegisteredModelOut)
async def update_registered_model(
    model_id: str,
    body: RegisteredModelUpdate,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> RegisteredModelOut:
    model = await session.get(RegisteredModel, model_id)
    if not model or model.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registered model not found")

    if body.display_name is not None:
        model.display_name = body.display_name.strip()
    if body.enabled is not None:
        model.enabled = body.enabled
    if body.context_window_max is not None:
        model.context_window_max = body.context_window_max
    if body.context_window_configured is not None:
        model.context_window_configured = body.context_window_configured
    if body.supports_tools is not None:
        model.supports_tools = body.supports_tools
    if body.supports_vision is not None:
        model.supports_vision = body.supports_vision
    if body.temperature is not None:
        model.temperature = body.temperature
    if body.top_p is not None:
        model.top_p = body.top_p
    if body.max_output_tokens is not None:
        model.max_output_tokens = body.max_output_tokens

    model.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(model)

    if body.set_as_default is True:
        await _set_default_model_id(session, user.tenant_id, model.id, body.project_id)

    server = await session.get(ModelServer, model.server_id)
    default_id = await _get_default_model_id(session, user.tenant_id, body.project_id)

    return RegisteredModelOut(
        id=model.id,
        server_id=model.server_id,
        server_name=server.name if server else "Unknown Server",
        provider_type=server.provider_type if server else "custom",
        model_name=model.model_name,
        display_name=model.display_name,
        enabled=model.enabled,
        context_window_max=model.context_window_max,
        context_window_configured=model.context_window_configured,
        supports_tools=model.supports_tools,
        supports_vision=model.supports_vision,
        temperature=model.temperature,
        top_p=model.top_p,
        max_output_tokens=model.max_output_tokens,
        is_default=(model.id == default_id or model.model_name == default_id),
        availability="available" if (server and server.enabled and model.enabled) else "unavailable",
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@router.delete("/registry/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registered_model(
    model_id: str,
    force: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> None:
    model = await session.get(RegisteredModel, model_id)
    if not model or model.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registered model not found")

    if not force:
        # Check if default
        default_id = await _get_default_model_id(session, user.tenant_id)
        if default_id in (model.id, model.model_name):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Model '{model.display_name}' is currently configured as the default model. Reassign default model before deleting."
            )

        # Check agents
        agents = (await session.execute(
            select(Agent).where(Agent.tenant_id == user.tenant_id)
        )).scalars().all()
        in_use_agents = [
            a.name for a in agents
            if (a.config or {}).get("model") in (model.id, model.model_name)
        ]
        if in_use_agents:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Model is in use by agent(s): {', '.join(in_use_agents)}. Reassign before deleting."
            )

    await session.delete(model)
    await session.commit()


# --- Model Testing Routes ---

@router.post("/registry/{model_id}/test-inference", response_model=TestInferenceOut)
async def test_model_inference(
    model_id: str,
    body: TestInferenceIn,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> TestInferenceOut:
    model = await session.get(RegisteredModel, model_id)
    if not model or model.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registered model not found")

    server = await session.get(ModelServer, model.server_id)
    if not server or not server.enabled:
        return TestInferenceOut(ok=False, error="Parent model server is disabled or unavailable")

    key = await _resolve_server_key(session, user.tenant_id, server)
    adapter = get_adapter_for_server(server, key)
    chat_model = adapter.build_chat_model(
        model_name=model.model_name,
        params={"temperature": model.temperature or 0.3, "max_tokens": 50},
    )

    t0 = time.perf_counter()
    ok, snippet, err = await adapter.test_inference(chat_model, prompt=body.prompt)
    latency = int((time.perf_counter() - t0) * 1000)

    # Store in runtime cache
    _RUNTIME_STATUS[model_id] = {
        "last_inference_test": {"ok": ok, "latency_ms": latency, "error": err, "timestamp": datetime.now(UTC).isoformat()}
    }

    return TestInferenceOut(ok=ok, latency_ms=latency, response_snippet=snippet, error=err)


@router.post("/registry/{model_id}/test-tools", response_model=TestToolsOut)
async def test_model_tool_calling(
    model_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> TestToolsOut:
    model = await session.get(RegisteredModel, model_id)
    if not model or model.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registered model not found")

    server = await session.get(ModelServer, model.server_id)
    if not server or not server.enabled:
        return TestToolsOut(ok=False, error="Parent model server is disabled or unavailable")

    key = await _resolve_server_key(session, user.tenant_id, server)
    adapter = get_adapter_for_server(server, key)
    chat_model = adapter.build_chat_model(
        model_name=model.model_name,
        params={"temperature": 0.1},
    )

    t0 = time.perf_counter()
    ok, tool_name, tool_args, err = await adapter.test_tool_calling(chat_model)
    latency = int((time.perf_counter() - t0) * 1000)

    # Update tool capability status in DB if verified
    if ok:
        model.supports_tools = True
        await session.commit()

    return TestToolsOut(
        ok=ok,
        latency_ms=latency,
        tool_called=tool_name,
        tool_args=tool_args,
        error=err,
    )


# --- Default Model Route ---

@router.put("/default")
async def set_default_model(
    body: SetDefaultModelIn,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> dict[str, Any]:
    model = await session.get(RegisteredModel, body.model_id)
    if not model or model.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registered model not found")
    if not model.enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot set disabled model as project default")

    await _set_default_model_id(session, user.tenant_id, model.id, body.project_id)
    return {"ok": True, "default_model_id": model.id}


# --- Unified Consumer API (Zero-Phantom Policy) ---

@router.get("", response_model=UnifiedCatalogOut)
async def list_models(
    request: Request,
    project_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> UnifiedCatalogOut:
    """Unified Model Catalog. Chat list contains ONLY explicitly registered models."""
    try:
        user = await get_current_user(request)
        tenant_id = user.tenant_id
        await _auto_migrate_legacy_providers(session, tenant_id)
    except Exception:
        tenant_id = None

    chat_models: list[ChatModelCatalogOut] = []
    if tenant_id:
        default_id = await _get_default_model_id(session, tenant_id, project_id)
        reg_models = (await session.execute(
            select(RegisteredModel).where(RegisteredModel.tenant_id == tenant_id, RegisteredModel.enabled.is_(True))
        )).scalars().all()

        servers = {s.id: s for s in (await session.execute(
            select(ModelServer).where(ModelServer.tenant_id == tenant_id)
        )).scalars().all()}

        for m in reg_models:
            srv = servers.get(m.server_id)
            if not srv or not srv.enabled:
                continue
            ctx_label = f"{m.context_window_configured // 1024}k" if m.context_window_configured else "32k"
            is_def = (m.id == default_id or m.model_name == default_id)
            chat_models.append(
                ChatModelCatalogOut(
                    id=m.id,
                    name=m.display_name,
                    provider=srv.name,
                    ctx=ctx_label,
                    ctx_tokens=m.context_window_configured or 32768,
                    tools=bool(m.supports_tools),
                    vision=bool(m.supports_vision),
                    is_default=is_def,
                    available=True,
                )
            )

    return UnifiedCatalogOut(
        chat=chat_models,
        embedding=[
            EmbeddingModelOut(id=m.id, name=m.name, provider=m.provider, dim=m.dim, billed=m.billed, default=m.default)
            for m in EMBEDDING_MODELS
        ],
        reranker=[
            RerankerModelOut(id=m.id, name=m.name, note=m.note, default=m.default)
            for m in RERANKER_MODELS
        ],
    )


# --- Backward Compatibility Endpoints ---

@router.post("/discover")
async def legacy_discover(
    body: ServerTestIn,
    user: CurrentUser = Depends(require_role("editor")),
) -> dict[str, Any]:
    adapter = ProviderAdapter(provider_type=body.provider_type or "openai_compatible", base_url=body.base_url, api_key=body.api_key)
    discovered = await adapter.discover_models()
    return {"ok": len(discovered) > 0, "models": discovered, "error": None if discovered else "No models discovered"}


# --- On-Demand Embedding Model Download & Status ---

class EmbeddingModelStatusOut(BaseModel):
    model_id: str
    is_local: bool
    cached: bool
    package_installed: bool
    approx_size: str | None = None
    cache_dir: str | None = None
    error: str | None = None


class EmbeddingModelDownloadIn(BaseModel):
    model_id: str


@router.get("/embeddings/status", response_model=EmbeddingModelStatusOut)
async def get_embedding_model_status(
    model_id: str = Query(...),
    _: CurrentUser = Depends(require_role("viewer")),
) -> EmbeddingModelStatusOut:
    """Check if model weights exist in data/models/fastembed for the selected embedding model."""
    from alberto.knowledge.embeddings import check_embedding_model_status
    status = check_embedding_model_status(model_id)
    return EmbeddingModelStatusOut(**status)


@router.post("/embeddings/download")
async def download_embedding_model(
    body: EmbeddingModelDownloadIn,
    _: CurrentUser = Depends(require_role("editor")),
) -> dict[str, Any]:
    """Download ONNX weights for ONLY the selected model into data/models/fastembed."""
    from alberto.knowledge.embeddings import download_embedding_model_weights
    try:
        return await download_embedding_model_weights(body.model_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
