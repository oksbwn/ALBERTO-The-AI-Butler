"""Provider Adapter Layer for Alberto's Unified Model Registry.

Handles connection testing, model discovery, model construction, inference testing,
and safe tool-calling validation for local engines (Ollama, LM Studio, vLLM,
OpenAI-compatible) and cloud providers (OpenAI, Anthropic, Google, Groq, DeepSeek, Mistral).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from alberto.config import settings

log = logging.getLogger("forge.providers")

DEFAULT_CLOUD_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com",
    "google_genai": "https://generativelanguage.googleapis.com",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
}


def normalize_base_url(url: str, provider_type: str) -> str:
    """Normalize endpoint origin and strip redundant paths/slashes."""
    u = (url or "").strip().rstrip("/")
    if not u and provider_type in DEFAULT_CLOUD_BASE_URLS:
        return DEFAULT_CLOUD_BASE_URLS[provider_type]

    if not u.startswith(("http://", "https://")):
        raise ValueError(f"Endpoint URL must start with http:// or https://: {url}")

    parsed = urlparse(u)
    if not parsed.netloc:
        raise ValueError(f"Invalid endpoint host: {url}")

    return u


def get_openai_compat_url(base_url: str) -> str:
    """Ensure base_url for ChatOpenAI compatibility ends with /v1 without duplicating."""
    clean = base_url.rstrip("/")
    if clean.endswith("/v1"):
        return clean
    return f"{clean}/v1"


class ProviderAdapter:
    """Base provider adapter interface."""

    def __init__(self, provider_type: str, base_url: str, api_key: str | None = None):
        self.provider_type = provider_type
        self.base_url = normalize_base_url(base_url, provider_type) if base_url else DEFAULT_CLOUD_BASE_URLS.get(provider_type, "")
        self.api_key = api_key

    async def test_connection(self) -> tuple[bool, int | None, int, str | None]:
        """Returns (ok, status_code, discovered_count, error)."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        candidate_eps = self._get_discovery_endpoints()
        last_error = None
        status_code = None

        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            for ep in candidate_eps:
                try:
                    res = await client.get(ep, headers=headers)
                    status_code = res.status_code
                    if res.status_code == 200:
                        models = self._parse_models_response(res.json())
                        return True, res.status_code, len(models), None
                    last_error = f"HTTP {res.status_code}: {res.text[:120]}"
                except Exception as e:
                    last_error = str(e)

        return False, status_code, 0, last_error or "Endpoint did not return 200 OK"

    async def discover_models(self) -> list[dict[str, Any]]:
        """Returns list of normalized model metadata dicts."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        candidate_eps = self._get_discovery_endpoints()
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for ep in candidate_eps:
                try:
                    res = await client.get(ep, headers=headers)
                    if res.status_code == 200:
                        parsed = self._parse_models_response(res.json())
                        if self.provider_type == "ollama":
                            await self._enrich_ollama(client, parsed, headers)
                        return parsed
                except Exception:
                    continue
        return []

    async def _enrich_ollama(self, client: httpx.AsyncClient, models: list[dict[str, Any]], headers: dict) -> None:
        """Query Ollama /api/show to fetch hardware/GGUF context_length or num_ctx."""
        import re
        u = self.base_url.rstrip("/")
        if u.endswith("/v1"):
            u = u[:-3]
        for m in models:
            m_name = m.get("model_name")
            if not m_name:
                continue
            try:
                res = await client.post(f"{u}/api/show", json={"name": m_name}, headers=headers, timeout=3.0)
                if res.status_code == 200:
                    info = res.json()
                    model_info = info.get("model_info") or {}
                    ctx = None
                    for k, v in model_info.items():
                        if k.endswith(".context_length") and isinstance(v, (int, float)) and v > 0:
                            ctx = int(v)
                            break
                    if not ctx and isinstance(info.get("parameters"), str):
                        match = re.search(r"num_ctx\s+(\d+)", info["parameters"])
                        if match:
                            ctx = int(match.group(1))
                    if ctx:
                        m["context_window_max"] = ctx
            except Exception:
                pass

    def _get_discovery_endpoints(self) -> list[str]:
        u = self.base_url.rstrip("/")
        if self.provider_type == "ollama":
            return [f"{u}/api/tags", f"{u}/v1/models", f"{u}/models"]
        if u.endswith("/v1"):
            return [f"{u}/models"]
        return [f"{u}/v1/models", f"{u}/models"]

    def _parse_models_response(self, data: Any) -> list[dict[str, Any]]:
        raw_list: list[Any] = []
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list):
                raw_list = data["data"]
            elif "models" in data and isinstance(data["models"], list):
                raw_list = data["models"]
        elif isinstance(data, list):
            raw_list = data

        def _extract_ctx(it: Any) -> int | None:
            if not isinstance(it, dict):
                return None
            # vLLM (max_model_len), LM Studio / OpenRouter (context_length), LocalAI (max_tokens / context_window)
            for key in ("max_model_len", "context_length", "max_context_length", "context_window", "max_tokens", "context_window_max"):
                v = it.get(key)
                if isinstance(v, (int, float)) and v > 0:
                    return int(v)
            meta = it.get("meta") or it.get("details") or {}
            if isinstance(meta, dict):
                for key in ("context_length", "max_model_len", "context_window"):
                    v = meta.get(key)
                    if isinstance(v, (int, float)) and v > 0:
                        return int(v)
            return None

        def _family_ctx(name_lower: str) -> int:
            if any(k in name_lower for k in ("gemini-1.5", "gemini-2.0", "gemini-2", "gemini-flash")):
                return 1048576  # 1M
            if any(k in name_lower for k in ("claude-3-5", "claude-3", "claude-3.5")):
                return 200000
            if any(k in name_lower for k in ("llama3", "llama-3", "qwen2", "qwen-2", "deepseek-r1", "deepseek-v3", "mistral-nemo", "codestral")):
                return 131072  # 128k
            if any(k in name_lower for k in ("gpt-4o", "gpt-4-turbo")):
                return 128000
            if any(k in name_lower for k in ("mistral", "mixtral")):
                return 32768
            if any(k in name_lower for k in ("gemma-2", "gemma2", "gemma")):
                return 8192
            if any(k in name_lower for k in ("phi-3-mini-4k", "phi-2")):
                return 4096
            return 32768

        results = []
        for item in raw_list:
            m_name = (
                item.get("id") or item.get("name") or item.get("model")
                if isinstance(item, dict)
                else str(item)
            )
            if not m_name or not isinstance(m_name, str):
                continue
            name_str = m_name.strip()
            name_lower = name_str.lower()
            is_vision = any(k in name_lower for k in ("vision", "llava", "pixtral", "vl", "omni", "gpt-4o", "gemini"))
            
            # 1. Direct provider reported context length (e.g. vLLM max_model_len, LM Studio context_length)
            direct_ctx = _extract_ctx(item)
            # 2. Family heuristic fallback
            ctx_max = direct_ctx or _family_ctx(name_lower)

            results.append({
                "model_name": name_str,
                "display_name": name_str,
                "context_window_max": ctx_max,
                "supports_tools": True,
                "supports_vision": is_vision,
            })
        return results

    def build_chat_model(
        self,
        model_name: str,
        params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        """Constructs the appropriate LangChain chat model."""
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}

        # Handle native thinking/reasoning flags
        thinking_flag = clean_params.pop("thinking", None)
        if thinking_flag is not None:
            name_lower = model_name.lower()
            is_reasoning_model = any(k in name_lower for k in ("o1", "o3", "o4", "r1", "qwq", "reason"))
            if is_reasoning_model:
                clean_params["reasoning_effort"] = "high" if thinking_flag else "low"
            if self.provider_type in ("anthropic", "claude") or "claude" in name_lower:
                if thinking_flag:
                    clean_params["thinking"] = {"type": "enabled", "budget_tokens": 2048}
                else:
                    clean_params["thinking"] = {"type": "disabled"}
            if self.provider_type in ("vllm", "lm_studio", "openai_compatible") and is_reasoning_model:
                extra = clean_params.setdefault("extra_body", {})
                extra["include_reasoning"] = bool(thinking_flag)

        # Ollama, LM Studio, vLLM, openai_compatible
        if self.provider_type in ("ollama", "lm_studio", "vllm", "openai_compatible"):
            from langchain_openai import ChatOpenAI
            compat_url = get_openai_compat_url(self.base_url)
            clean_params.setdefault("stream_usage", True)
            key = self.api_key or "local"
            return ChatOpenAI(
                model=model_name,
                base_url=compat_url,
                api_key=key,
                **clean_params,
            )

        # Cloud Providers
        from langchain.chat_models import init_chat_model

        provider_tag = "google_genai" if self.provider_type in ("google", "google_genai") else self.provider_type
        if self.api_key:
            key_param = "google_api_key" if provider_tag == "google_genai" else "api_key"
            clean_params.setdefault(key_param, self.api_key)

        if provider_tag == "openai":
            clean_params.setdefault("stream_usage", True)
            if settings.llm_http_keepalive and "http_async_client" not in clean_params:
                from alberto.util.http import shared_llm_async_client
                clean_params["http_async_client"] = shared_llm_async_client()

        model_ref = f"{provider_tag}:{model_name}" if ":" not in model_name else model_name
        return init_chat_model(model_ref, **clean_params)

    async def test_inference(self, chat_model: BaseChatModel, prompt: str = "Ping") -> tuple[bool, str | None, str | None]:
        """Test inference with a short prompt. Returns (ok, snippet, error)."""
        try:
            resp = await chat_model.ainvoke([HumanMessage(content=prompt)])
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            snippet = text.strip()[:100]
            return True, snippet, None
        except Exception as e:
            log.warning("Inference test failed: %s", e)
            return False, None, str(e)

    async def test_tool_calling(self, chat_model: BaseChatModel) -> tuple[bool, str | None, dict | None, str | None]:
        """Test tool calling with a safe dummy tool. Returns (ok, tool_name, tool_args, error)."""
        @tool
        def verify_alberto_diagnostic(check_code: str) -> str:
            """Harmless diagnostic tool used ONLY to test model tool-calling capability."""
            return f"verified:{check_code}"

        try:
            bound_model = chat_model.bind_tools([verify_alberto_diagnostic])
            prompt = (
                "You must call the verify_alberto_diagnostic tool with check_code='test_ok'. "
                "Do not reply with normal text. Invoke the tool now."
            )
            res = await bound_model.ainvoke([HumanMessage(content=prompt)])
            tool_calls = getattr(res, "tool_calls", None) or []
            if tool_calls:
                call = tool_calls[0]
                return True, call.get("name"), call.get("args"), None

            # Fallback check inside additional_kwargs
            add_kwargs = getattr(res, "additional_kwargs", {}) or {}
            raw_calls = add_kwargs.get("tool_calls", [])
            if raw_calls:
                fn = raw_calls[0].get("function", {})
                return True, fn.get("name"), fn.get("arguments"), None

            return False, None, None, "Model responded with text but did not execute a tool call."
        except Exception as e:
            log.warning("Tool calling test failed: %s", e)
            return False, None, None, str(e)


def get_adapter_for_server(server: Any, resolved_api_key: str | None = None) -> ProviderAdapter:
    """Instantiate ProviderAdapter for a ModelServer entity or dict."""
    p_type = str(getattr(server, "provider_type", None) or (server.get("provider_type") if isinstance(server, dict) else None) or "openai_compatible")
    b_url = str(getattr(server, "base_url", None) or (server.get("base_url") if isinstance(server, dict) else None) or "")
    return ProviderAdapter(provider_type=p_type, base_url=b_url, api_key=resolved_api_key)
