"""Unified Model Registry & Provider Management Router.

Pure controller delegating all database persistence and provider interactions
to ModelRegistryService.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.deps import CurrentUser, get_current_user, get_session, require_role
from alberto.engine.providers import (
    ProviderAdapter,
    get_adapter_for_server,
    normalize_base_url,
)
from alberto.services.governance.models import ModelRegistryService

log = logging.getLogger("forge.routers.models")
router = APIRouter(prefix="/v1/models", tags=["models"])


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
    api_key_configured: bool
    api_key_ref: str | None = None
    enabled: bool
    registered_models_count: int = 0
    status: str = "unknown"  # healthy | unreachable | unknown
    last_connected_at: str | None = None
    created_at: Any
    updated_at: Any


class ServerTestIn(BaseModel):
    provider_type: str
    base_url: str
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
    models: list[DiscoveredModelItem]
    error: str | None = None


class RegisteredModelCreate(BaseModel):
    server_id: str
    model_name: str
    display_name: str | None = None
    enabled: bool = True
    context_window_max: int | None = 131072
    context_window_configured: int | None = 32768
    supports_tools: bool | None = True
    supports_vision: bool | None = False
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
    availability: str = "available"
    created_at: Any
    updated_at: Any


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


# --- Server Management Routes ---

@router.get("/servers", response_model=list[ModelServerOut])
async def list_servers(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> list[ModelServerOut]:
    servers = await ModelRegistryService.list_servers(session, user.tenant_id)
    return [ModelServerOut(**s) for s in servers]


@router.post("/servers", response_model=ModelServerOut, status_code=status.HTTP_201_CREATED)
async def create_server(
    body: ModelServerCreate,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> ModelServerOut:
    server = await ModelRegistryService.create_server(
        session,
        user.tenant_id,
        name=body.name,
        provider_type=body.provider_type,
        base_url=body.base_url,
        api_key=body.api_key,
        api_key_ref=body.api_key_ref,
        enabled=body.enabled,
    )
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
    server = await ModelRegistryService.get_server(session, user.tenant_id, server_id)
    if not server:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model server not found")

    server = await ModelRegistryService.update_server(
        session,
        user.tenant_id,
        server,
        name=body.name,
        base_url=body.base_url,
        api_key=body.api_key,
        api_key_ref=body.api_key_ref,
        enabled=body.enabled,
    )

    models = await ModelRegistryService.list_registered_models(session, user.tenant_id)
    count = sum(1 for m in models if m["server_id"] == server.id)
    status_info = ModelRegistryService.get_runtime_status(server.id)

    return ModelServerOut(
        id=server.id,
        name=server.name,
        provider_type=server.provider_type,
        base_url=server.base_url,
        api_key_configured=bool(server.api_key_ref),
        api_key_ref=server.api_key_ref,
        enabled=server.enabled,
        registered_models_count=count,
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
    server = await ModelRegistryService.get_server(session, user.tenant_id, server_id)
    if not server:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model server not found")

    blocked_models = await ModelRegistryService.delete_server(session, user.tenant_id, server, force=force)
    if blocked_models:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot delete server '{server.name}': {len(blocked_models)} registered models depend on it. Remove models first or specify force=true."
        )


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
    server = await ModelRegistryService.get_server(session, user.tenant_id, server_id)
    if not server:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model server not found")

    items = await ModelRegistryService.discover_server_models(session, user.tenant_id, server)
    return ServerDiscoverOut(
        ok=True,
        server_id=server_id,
        models=[DiscoveredModelItem(**d) for d in items],
        error=None if items else "No models discovered at endpoint",
    )


# --- Model Registry Routes ---

@router.get("/registry", response_model=list[RegisteredModelOut])
async def list_registered_models(
    project_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> list[RegisteredModelOut]:
    models = await ModelRegistryService.list_registered_models(session, user.tenant_id, project_id)
    return [RegisteredModelOut(**m) for m in models]


@router.post("/registry", response_model=RegisteredModelOut, status_code=status.HTTP_201_CREATED)
async def register_model(
    body: RegisteredModelCreate,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> RegisteredModelOut:
    try:
        model = await ModelRegistryService.register_model(
            session,
            user.tenant_id,
            server_id=body.server_id,
            model_name=body.model_name,
            display_name=body.display_name,
            enabled=body.enabled,
            context_window_max=body.context_window_max,
            context_window_configured=body.context_window_configured,
            supports_tools=body.supports_tools,
            supports_vision=body.supports_vision,
            temperature=body.temperature,
            top_p=body.top_p,
            max_output_tokens=body.max_output_tokens,
            set_as_default=body.set_as_default,
            project_id=body.project_id,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except KeyError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    server = await ModelRegistryService.get_server(session, user.tenant_id, model.server_id)
    return RegisteredModelOut(
        id=model.id,
        server_id=server.id if server else model.server_id,
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
    model = await ModelRegistryService.get_model(session, user.tenant_id, model_id)
    if not model:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registered model not found")

    model = await ModelRegistryService.update_model(
        session,
        user.tenant_id,
        model,
        display_name=body.display_name,
        enabled=body.enabled,
        context_window_max=body.context_window_max,
        context_window_configured=body.context_window_configured,
        supports_tools=body.supports_tools,
        supports_vision=body.supports_vision,
        temperature=body.temperature,
        top_p=body.top_p,
        max_output_tokens=body.max_output_tokens,
        set_as_default=body.set_as_default,
        project_id=body.project_id,
    )

    server = await ModelRegistryService.get_server(session, user.tenant_id, model.server_id)
    default_id = await ModelRegistryService.get_default_model_id(session, user.tenant_id, body.project_id)

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
    model = await ModelRegistryService.get_model(session, user.tenant_id, model_id)
    if not model:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registered model not found")

    err = await ModelRegistryService.delete_model(session, user.tenant_id, model, force=force)
    if err:
        raise HTTPException(status.HTTP_409_CONFLICT, err)


@router.post("/registry/{model_id}/test-inference", response_model=TestInferenceOut)
async def test_model_inference(
    model_id: str,
    body: TestInferenceIn,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> TestInferenceOut:
    model = await ModelRegistryService.get_model(session, user.tenant_id, model_id)
    if not model:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registered model not found")

    server = await ModelRegistryService.get_server(session, user.tenant_id, model.server_id)
    if not server or not server.enabled:
        return TestInferenceOut(ok=False, error="Parent model server is disabled or unavailable")

    key = await ModelRegistryService.resolve_server_key(session, user.tenant_id, server)
    adapter = get_adapter_for_server(server, key)
    chat_model = adapter.build_chat_model(
        model_name=model.model_name,
        params={"temperature": model.temperature or 0.3, "max_tokens": 50},
    )

    t0 = time.perf_counter()
    ok, snippet, err = await adapter.test_inference(chat_model, prompt=body.prompt)
    latency = int((time.perf_counter() - t0) * 1000)

    return TestInferenceOut(ok=ok, latency_ms=latency, response_snippet=snippet, error=err)


@router.post("/registry/{model_id}/test-tools", response_model=TestToolsOut)
async def test_model_tool_calling(
    model_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> TestToolsOut:
    model = await ModelRegistryService.get_model(session, user.tenant_id, model_id)
    if not model:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registered model not found")

    server = await ModelRegistryService.get_server(session, user.tenant_id, model.server_id)
    if not server or not server.enabled:
        return TestToolsOut(ok=False, error="Parent model server is disabled or unavailable")

    key = await ModelRegistryService.resolve_server_key(session, user.tenant_id, server)
    adapter = get_adapter_for_server(server, key)
    chat_model = adapter.build_chat_model(
        model_name=model.model_name,
        params={"temperature": 0.1},
    )

    t0 = time.perf_counter()
    ok, tool_name, tool_args, err = await adapter.test_tool_calling(chat_model)
    latency = int((time.perf_counter() - t0) * 1000)

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


@router.put("/default")
async def set_default_model(
    body: SetDefaultModelIn,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
) -> dict[str, Any]:
    model = await ModelRegistryService.get_model(session, user.tenant_id, body.model_id)
    if not model:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registered model not found")
    if not model.enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot set disabled model as project default")

    await ModelRegistryService.set_default_model_id(session, user.tenant_id, model.id, body.project_id)
    return {"ok": True, "default_model_id": model.id}


@router.get("", response_model=UnifiedCatalogOut)
async def list_models(
    request: Request,
    project_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> UnifiedCatalogOut:
    """Unified Model Catalog."""
    try:
        user = await get_current_user(request)
        tenant_id = user.tenant_id
    except Exception:
        tenant_id = None

    catalog = await ModelRegistryService.get_unified_catalog(session, tenant_id, project_id)
    return UnifiedCatalogOut(
        chat=[ChatModelCatalogOut(**c) for c in catalog["chat"]],
        embedding=[EmbeddingModelOut(**e) for e in catalog["embedding"]],
        reranker=[RerankerModelOut(**r) for r in catalog["reranker"]],
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
    from alberto.knowledge.embeddings import check_embedding_model_status
    status = check_embedding_model_status(model_id)
    return EmbeddingModelStatusOut(**status)


@router.post("/embeddings/download")
async def download_embedding_model(
    body: EmbeddingModelDownloadIn,
    _: CurrentUser = Depends(require_role("editor")),
) -> dict[str, Any]:
    from alberto.knowledge.embeddings import download_embedding_model_weights
    try:
        return await download_embedding_model_weights(body.model_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
