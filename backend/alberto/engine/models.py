"""Resolve a model-ref string to a chat model.

Unified model resolution layer:
- Resolves registered models by ID from Alberto's Model Registry
- Enforces enabled state of model and parent server (no silent substitutions)
- Injects user-tuned parameters (temperature, max_output_tokens, top_p)
- Supports provider-specific adapters and connection keep-alive
- Provides backward compatibility for legacy strings (fake:, custom:, provider:model)
"""

from __future__ import annotations

import itertools
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from alberto.config import settings

if TYPE_CHECKING:
    from alberto.engine.context import CompileContext

log = logging.getLogger("forge.engine.models")

_PROVIDER_DEFAULT_MODEL: dict[str, str] = {
    "openai": "openai:gpt-4.1-mini",
    "anthropic": "anthropic:claude-sonnet-4-6",
    "google_genai": "google_genai:gemini-2.5-flash",
    "google": "google_genai:gemini-2.5-flash",
}


def default_model_for_credentials(creds: dict | None) -> str | None:
    """Pick a real model ref for a project that has provider keys but no explicit default."""
    for provider in ("openai", "anthropic", "google_genai", "google"):
        if provider in (creds or {}):
            return _PROVIDER_DEFAULT_MODEL[provider]
    return None


_PROVIDER_CHEAP_MODEL: dict[str, str] = {
    "openai": "openai:gpt-4.1-nano",
    "anthropic": "anthropic:claude-haiku-4-5",
    "google_genai": "google_genai:gemini-2.5-flash",
    "google": "google_genai:gemini-2.5-flash",
}


def cheap_model_for_credentials(creds: dict | None) -> str | None:
    """The cheapest model for a project's configured provider."""
    for provider in ("openai", "anthropic", "google_genai", "google"):
        if provider in (creds or {}):
            return _PROVIDER_CHEAP_MODEL[provider]
    return None


def make_fake_model(reply: str | None = None) -> BaseChatModel:
    """An offline chat model that returns a fixed final answer on every call."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class _ToolTolerantFake(GenericFakeChatModel):
        def bind_tools(self, tools=None, **kwargs):  # type: ignore[override]
            return self

    text = reply or "Hello from Alberto's offline model. Register a model to go live."
    return _ToolTolerantFake(messages=itertools.cycle([AIMessage(content=text)]))


def resolve_model(
    model_ref: str | BaseChatModel | None,
    ctx: CompileContext | None = None,
    params: dict[str, Any] | None = None,
) -> BaseChatModel:
    # 1. Already a constructed model (injected by test or middleware)
    if isinstance(model_ref, BaseChatModel):
        return model_ref

    # 2. Empty ref -> resolve project/context default
    if not model_ref:
        model_ref = (
            getattr(ctx, "default_model_id", None)
            or getattr(ctx, "default_model", None)
            or (getattr(ctx, "project_config", None) or {}).get("fallback_model")
            or getattr(settings, "default_model", None)
        )
    if not model_ref:
        raise ValueError("No model configured or available. Please configure a default model in the model registry.")

    # 3. Offline fake model
    if isinstance(model_ref, str) and (model_ref == "fake" or model_ref.startswith("fake:")):
        _, _, reply = model_ref.partition(":")
        return make_fake_model(reply or None)

    # 4. Check Alberto Model Registry (RegisteredModel)
    if isinstance(model_ref, str) and ctx:
        reg_model = (getattr(ctx, "registered_models", None) or {}).get(model_ref)
        # Also allow matching by model_name if unique among registered models
        if not reg_model:
            for rm in (getattr(ctx, "registered_models", None) or {}).values():
                if getattr(rm, "model_name", None) == model_ref or getattr(rm, "display_name", None) == model_ref:
                    reg_model = rm
                    break

        if not reg_model and ":" not in str(model_ref) and getattr(ctx, "registered_models", None):
            raise ValueError(f"Model '{model_ref}' not found in model registry.")

        if reg_model:
            if not getattr(reg_model, "enabled", True):
                raise RuntimeError(f"Registered model '{getattr(reg_model, 'display_name', model_ref)}' is disabled in registry.")

            server_id = getattr(reg_model, "server_id", None)
            server = (getattr(ctx, "model_servers", None) or {}).get(server_id)
            if server and not getattr(server, "enabled", True):
                raise RuntimeError(f"Model server '{getattr(server, 'name', server_id)}' is disabled.")

            from alberto.engine.providers import get_adapter_for_server

            # Resolve server key: check server_id, then provider_type
            creds = getattr(ctx, "provider_credentials", None) or {}
            key = creds.get(server_id) or (creds.get(getattr(server, "provider_type", "")) if server else None)
            adapter = get_adapter_for_server(server, key)

            # Parameter precedence:
            # 1. Explicit runtime override (params)
            # 2. Registered model configuration (temperature, top_p, max_output_tokens)
            # 3. Provider default
            eff_params: dict[str, Any] = {}
            if getattr(reg_model, "temperature", None) is not None:
                eff_params["temperature"] = reg_model.temperature
            if getattr(reg_model, "top_p", None) is not None:
                eff_params["top_p"] = reg_model.top_p
            if getattr(reg_model, "max_output_tokens", None) is not None:
                eff_params["max_tokens"] = reg_model.max_output_tokens

            if params:
                for k, v in params.items():
                    if v is not None:
                        eff_params[k] = v

            wire_name = getattr(reg_model, "model_name", model_ref)
            return adapter.build_chat_model(model_name=wire_name, params=eff_params)

    # 5. Legacy custom provider ref (custom:<provider_id>:<model_name>)
    if isinstance(model_ref, str) and model_ref.startswith("custom:"):
        parts = model_ref.split(":", 2)
        prov_id = parts[1] if len(parts) > 1 else ""
        model_name = parts[2] if len(parts) > 2 else parts[-1]

        prov = (getattr(ctx, "model_providers", None) or {}).get(prov_id, {})
        base_url = prov.get("base_url") or "http://localhost:11434/v1"
        api_key = prov.get("api_key") or "local"

        from langchain_openai import ChatOpenAI

        clean = {k: v for k, v in (params or {}).items() if v is not None}
        clean.setdefault("stream_usage", True)
        return ChatOpenAI(model=model_name, base_url=base_url, api_key=api_key, **clean)

    # 6. Legacy provider string compatibility fallback (e.g. "openai:gpt-4o", "anthropic:claude-3-5-sonnet")
    log.warning("[COMPAT] Legacy model reference '%s' resolved via compatibility layer.", model_ref)
    from langchain.chat_models import init_chat_model

    clean = {k: v for k, v in (params or {}).items() if v is not None}

    provider = model_ref.split(":", 1)[0] if ":" in str(model_ref) else None
    creds = getattr(ctx, "provider_credentials", None) or {}
    key = creds.get(provider) if provider else None
    if key:
        param = "google_api_key" if provider in ("google_genai", "google") else "api_key"
        clean.setdefault(param, key)

    if provider == "openai":
        clean.setdefault("stream_usage", True)

    if (
        settings.llm_http_keepalive
        and provider == "openai"
        and "http_async_client" not in clean
    ):
        from alberto.util.http import shared_llm_async_client

        clean["http_async_client"] = shared_llm_async_client()

    return init_chat_model(str(model_ref), **clean)
