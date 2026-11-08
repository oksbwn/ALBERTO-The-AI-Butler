"""Service for Model Server & Registered Model management."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from alberto.engine.providers import (
    get_adapter_for_server,
    normalize_base_url,
)
from alberto.model_catalog import EMBEDDING_MODELS, RERANKER_MODELS
from alberto.models import Agent, ModelServer, Project, RegisteredModel, Tenant
from alberto.secrets.store import SecretStore

log = logging.getLogger("alberto.services.models")

# Lightweight in-memory runtime cache for server and model health
_RUNTIME_STATUS: dict[str, dict[str, Any]] = {}


class ModelRegistryService:
    @staticmethod
    def get_runtime_status(key: str) -> dict[str, Any]:
        return _RUNTIME_STATUS.get(key, {})

    @staticmethod
    def pop_runtime_status(key: str) -> None:
        _RUNTIME_STATUS.pop(key, None)

    @staticmethod
    async def resolve_server_key(session: AsyncSession, tenant_id: str, server: ModelServer) -> str | None:
        if not server.api_key_ref:
            return None
        try:
            store = SecretStore()
            proj = (await session.execute(select(Project).where(Project.tenant_id == tenant_id))).scalars().first()
            proj_id = proj.id if proj else "default"
            val = await store.read_ref(tenant_id=tenant_id, project_id=proj_id, ref=server.api_key_ref)
            if isinstance(val, dict):
                return str(val.get("key") or val.get("value") or "")
            return str(val) if val else None
        except Exception as e:
            log.warning("Could not resolve server secret ref %s: %s", server.api_key_ref, e)
            return None

    @staticmethod
    async def get_default_model_id(session: AsyncSession, tenant_id: str, project_id: str | None = None) -> str | None:
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

    @staticmethod
    async def set_default_model_id(session: AsyncSession, tenant_id: str, model_id: str, project_id: str | None = None) -> None:
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

    @staticmethod
    async def auto_migrate_legacy_providers(session: AsyncSession, tenant_id: str) -> None:
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
                return

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

    @staticmethod
    async def list_servers(session: AsyncSession, tenant_id: str) -> list[dict[str, Any]]:
        await ModelRegistryService.auto_migrate_legacy_providers(session, tenant_id)
        servers = (await session.execute(
            select(ModelServer).where(ModelServer.tenant_id == tenant_id).order_by(ModelServer.created_at.desc())
        )).scalars().all()

        out: list[dict[str, Any]] = []
        for s in servers:
            model_count = (await session.execute(
                select(RegisteredModel).where(RegisteredModel.tenant_id == tenant_id, RegisteredModel.server_id == s.id)
            )).scalars().all()
            status_info = _RUNTIME_STATUS.get(s.id, {})
            out.append({
                "id": s.id,
                "name": s.name,
                "provider_type": s.provider_type,
                "base_url": s.base_url,
                "api_key_configured": bool(s.api_key_ref),
                "api_key_ref": s.api_key_ref,
                "enabled": s.enabled,
                "registered_models_count": len(model_count),
                "status": "healthy" if status_info.get("reachable") else ("unreachable" if status_info.get("reachable") is False else "unknown"),
                "last_connected_at": status_info.get("last_connected_at"),
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            })
        return out

    @staticmethod
    async def get_server(session: AsyncSession, tenant_id: str, server_id: str) -> ModelServer | None:
        s = await session.get(ModelServer, server_id)
        if s and s.tenant_id == tenant_id:
            return s
        return None

    @staticmethod
    async def create_server(
        session: AsyncSession,
        tenant_id: str,
        *,
        name: str,
        provider_type: str,
        base_url: str = "",
        api_key: str | None = None,
        api_key_ref: str | None = None,
        enabled: bool = True,
    ) -> ModelServer:
        norm_url = normalize_base_url(base_url, provider_type)
        server_id = f"srv_{uuid.uuid4().hex[:8]}"

        if api_key and api_key.strip():
            store = SecretStore()
            proj = (await session.execute(select(Project).where(Project.tenant_id == tenant_id))).scalars().first()
            proj_id = proj.id if proj else "default"
            sec_name = f"model_server_{server_id}_key"
            await store.write(session, tenant_id=tenant_id, project_id=proj_id, name=sec_name, value=api_key.strip(), kind="api_key")
            api_key_ref = f"secret://proj/{sec_name}"

        now = datetime.now(UTC)
        server = ModelServer(
            id=server_id,
            tenant_id=tenant_id,
            name=name.strip(),
            provider_type=provider_type,
            base_url=norm_url,
            api_key_ref=api_key_ref,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        session.add(server)
        await session.commit()
        await session.refresh(server)
        return server

    @staticmethod
    async def update_server(
        session: AsyncSession,
        tenant_id: str,
        server: ModelServer,
        *,
        name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_ref: str | None = None,
        enabled: bool | None = None,
    ) -> ModelServer:
        if name is not None:
            server.name = name.strip()
        if base_url is not None:
            server.base_url = normalize_base_url(base_url, server.provider_type)
        if enabled is not None:
            server.enabled = enabled

        if api_key is not None:
            if api_key.strip():
                store = SecretStore()
                proj = (await session.execute(select(Project).where(Project.tenant_id == tenant_id))).scalars().first()
                proj_id = proj.id if proj else "default"
                sec_name = f"model_server_{server.id}_key"
                await store.write(session, tenant_id=tenant_id, project_id=proj_id, name=sec_name, value=api_key.strip(), kind="api_key")
                server.api_key_ref = f"secret://proj/{sec_name}"
            else:
                server.api_key_ref = None
        elif api_key_ref is not None:
            server.api_key_ref = api_key_ref

        server.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(server)
        return server

    @staticmethod
    async def delete_server(session: AsyncSession, tenant_id: str, server: ModelServer, force: bool = False) -> list[RegisteredModel] | None:
        models = (await session.execute(
            select(RegisteredModel).where(RegisteredModel.tenant_id == tenant_id, RegisteredModel.server_id == server.id)
        )).scalars().all()

        if models and not force:
            return list(models)

        if force and models:
            for m in models:
                await session.delete(m)

        await session.delete(server)
        await session.commit()
        _RUNTIME_STATUS.pop(server.id, None)
        return None

    @staticmethod
    async def discover_server_models(session: AsyncSession, tenant_id: str, server: ModelServer) -> list[dict[str, Any]]:
        key = await ModelRegistryService.resolve_server_key(session, tenant_id, server)
        adapter = get_adapter_for_server(server, key)
        discovered = await adapter.discover_models()

        existing_models = (await session.execute(
            select(RegisteredModel).where(RegisteredModel.tenant_id == tenant_id, RegisteredModel.server_id == server.id)
        )).scalars().all()
        reg_by_name = {m.model_name: m.id for m in existing_models}

        items = []
        for d in discovered:
            m_name = d["model_name"]
            reg_id = reg_by_name.get(m_name)
            items.append({
                "model_name": m_name,
                "display_name": d.get("display_name") or m_name,
                "context_window_max": d.get("context_window_max"),
                "supports_tools": d.get("supports_tools"),
                "supports_vision": d.get("supports_vision"),
                "is_registered": reg_id is not None,
                "registered_model_id": reg_id,
            })

        _RUNTIME_STATUS[server.id] = {
            "reachable": len(items) > 0,
            "last_connected_at": datetime.now(UTC).isoformat(),
            "discovered_count": len(items),
        }
        return items

    @staticmethod
    async def list_registered_models(session: AsyncSession, tenant_id: str, project_id: str | None = None) -> list[dict[str, Any]]:
        await ModelRegistryService.auto_migrate_legacy_providers(session, tenant_id)
        models = (await session.execute(
            select(RegisteredModel).where(RegisteredModel.tenant_id == tenant_id).order_by(RegisteredModel.created_at.desc())
        )).scalars().all()

        servers = {s.id: s for s in (await session.execute(
            select(ModelServer).where(ModelServer.tenant_id == tenant_id)
        )).scalars().all()}

        default_id = await ModelRegistryService.get_default_model_id(session, tenant_id, project_id)

        out: list[dict[str, Any]] = []
        for m in models:
            srv = servers.get(m.server_id)
            srv_name = srv.name if srv else "Unknown Server"
            p_type = srv.provider_type if srv else "custom"
            avail = "available" if (srv and srv.enabled and m.enabled) else "unavailable"

            out.append({
                "id": m.id,
                "server_id": m.server_id,
                "server_name": srv_name,
                "provider_type": p_type,
                "model_name": m.model_name,
                "display_name": m.display_name,
                "enabled": m.enabled,
                "context_window_max": m.context_window_max,
                "context_window_configured": m.context_window_configured,
                "supports_tools": m.supports_tools,
                "supports_vision": m.supports_vision,
                "temperature": m.temperature,
                "top_p": m.top_p,
                "max_output_tokens": m.max_output_tokens,
                "is_default": (m.id == default_id or m.model_name == default_id),
                "availability": avail,
                "created_at": m.created_at,
                "updated_at": m.updated_at,
            })
        return out

    @staticmethod
    async def get_model(session: AsyncSession, tenant_id: str, model_id: str) -> RegisteredModel | None:
        m = await session.get(RegisteredModel, model_id)
        if m and m.tenant_id == tenant_id:
            return m
        return None

    @staticmethod
    async def register_model(
        session: AsyncSession,
        tenant_id: str,
        *,
        server_id: str,
        model_name: str,
        display_name: str | None = None,
        enabled: bool = True,
        context_window_max: int | None = None,
        context_window_configured: int | None = None,
        supports_tools: bool | None = None,
        supports_vision: bool | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_output_tokens: int | None = None,
        set_as_default: bool = False,
        project_id: str | None = None,
    ) -> RegisteredModel:
        server = await session.get(ModelServer, server_id)
        if not server or server.tenant_id != tenant_id:
            raise ValueError("Model server not found")

        existing = (await session.execute(
            select(RegisteredModel).where(
                RegisteredModel.tenant_id == tenant_id,
                RegisteredModel.server_id == server_id,
                RegisteredModel.model_name == model_name.strip(),
            )
        )).scalar_one_or_none()
        if existing:
            raise KeyError(f"Model '{model_name}' is already registered on this server.")

        now = datetime.now(UTC)
        m_id = f"mod_{uuid.uuid4().hex[:8]}"
        model = RegisteredModel(
            id=m_id,
            tenant_id=tenant_id,
            server_id=server_id,
            model_name=model_name.strip(),
            display_name=(display_name or model_name).strip(),
            enabled=enabled,
            context_window_max=context_window_max,
            context_window_configured=context_window_configured or context_window_max or 32768,
            supports_tools=supports_tools,
            supports_vision=supports_vision,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
            created_at=now,
            updated_at=now,
        )
        session.add(model)
        await session.commit()
        await session.refresh(model)

        if set_as_default:
            await ModelRegistryService.set_default_model_id(session, tenant_id, model.id, project_id)

        return model

    @staticmethod
    async def update_model(
        session: AsyncSession,
        tenant_id: str,
        model: RegisteredModel,
        *,
        display_name: str | None = None,
        enabled: bool | None = None,
        context_window_max: int | None = None,
        context_window_configured: int | None = None,
        supports_tools: bool | None = None,
        supports_vision: bool | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_output_tokens: int | None = None,
        set_as_default: bool | None = None,
        project_id: str | None = None,
    ) -> RegisteredModel:
        if display_name is not None:
            model.display_name = display_name.strip()
        if enabled is not None:
            model.enabled = enabled
        if context_window_max is not None:
            model.context_window_max = context_window_max
        if context_window_configured is not None:
            model.context_window_configured = context_window_configured
        if supports_tools is not None:
            model.supports_tools = supports_tools
        if supports_vision is not None:
            model.supports_vision = supports_vision
        if temperature is not None:
            model.temperature = temperature
        if top_p is not None:
            model.top_p = top_p
        if max_output_tokens is not None:
            model.max_output_tokens = max_output_tokens

        model.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(model)

        if set_as_default is True:
            await ModelRegistryService.set_default_model_id(session, tenant_id, model.id, project_id)

        return model

    @staticmethod
    async def delete_model(session: AsyncSession, tenant_id: str, model: RegisteredModel, force: bool = False) -> str | None:
        if not force:
            default_id = await ModelRegistryService.get_default_model_id(session, tenant_id)
            if default_id in (model.id, model.model_name):
                return f"Model '{model.display_name}' is currently configured as the default model. Reassign default model before deleting."

            agents = (await session.execute(
                select(Agent).where(Agent.tenant_id == tenant_id)
            )).scalars().all()
            in_use_agents = [
                a.name for a in agents
                if (a.config or {}).get("model") in (model.id, model.model_name)
            ]
            if in_use_agents:
                return f"Model is in use by agent(s): {', '.join(in_use_agents)}. Reassign before deleting."

        await session.delete(model)
        await session.commit()
        return None

    @staticmethod
    async def get_unified_catalog(session: AsyncSession, tenant_id: str | None, project_id: str | None = None) -> dict[str, Any]:
        chat_models = []
        if tenant_id:
            await ModelRegistryService.auto_migrate_legacy_providers(session, tenant_id)
            default_id = await ModelRegistryService.get_default_model_id(session, tenant_id, project_id)
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
                chat_models.append({
                    "id": m.id,
                    "name": m.display_name,
                    "provider": srv.name,
                    "ctx": ctx_label,
                    "ctx_tokens": m.context_window_configured or 32768,
                    "tools": bool(m.supports_tools),
                    "vision": bool(m.supports_vision),
                    "is_default": is_def,
                    "available": True,
                })

        return {
            "chat": chat_models,
            "embedding": [
                {"id": m.id, "name": m.name, "provider": m.provider, "dim": m.dim, "billed": m.billed, "default": m.default}
                for m in EMBEDDING_MODELS
            ],
            "reranker": [
                {"id": m.id, "name": m.name, "note": m.note, "default": m.default}
                for m in RERANKER_MODELS
            ],
        }

