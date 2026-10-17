# Alberto — Unified Model Registry & Provider Architecture Design

## 1. Executive Summary

Alberto is a self-hosted AI Home Butler built on FastAPI, LangGraph, and Next.js. This document details the architectural overhaul that moves Alberto from a cloud-centric, static-catalog model to a unified, local-first model registry.

### Core Goals
- **Local-First Native**: Local inference engines (Ollama, LM Studio, vLLM, OpenAI-compatible local runtimes) are first-class execution providers.
- **Zero-Phantom Policy**: No model appears in agent, workflow, or chat selectors unless explicitly configured and registered. Static cloud lists are eliminated.
- **Explicit Two-Tier Abstraction**:
  1. `ModelServer`: Inference endpoints / cloud providers (credentials, connectivity, URL normalization, discovery).
  2. `RegisteredModel`: Specific model entries bound to a server with user-tuned execution parameters (context window, tool calling, vision, temperature, max tokens).
- **Single Source of Truth**: Centralized `resolve_model(model_ref, ctx)` used across agents, workflows, chat assistants, evals, and background tasks.

---

## 2. System Architecture

```
+-----------------------------------------------------------------------------------+
| Alberto Presentation Layer (Next.js / React Flow / Chat Console)                  |
| - Unified Settings Screen (Model Servers + Registered Models)                     |
| - Add Model Wizard (Select/Add Server -> Discover -> Tune -> Test & Save)         |
| - Execution Selectors (GET /v1/models -> Filtered to Active Registered Models)     |
+----------------------------------------+------------------------------------------+
                                         | REST API (FastAPI)
+----------------------------------------v------------------------------------------+
| Model Management Router (`forge.routers.models`)                                   |
| - Server CRUD (`/v1/models/servers`) & Connection/Discovery Probing               |
| - Registry CRUD (`/v1/models/registry`) & Inference/Tool Testing                 |
| - Default Model Binding (`/v1/models/default`)                                    |
| - Unified Catalog Consumer (`/v1/models`)                                         |
+-------------------+------------------------------------+--------------------------+
                    |                                    |
+-------------------v--------------------+ +-------------v--------------------------+
| SQLite Persistence (`forge.models`)    | | Provider Adapter Engine                |
| - `model_servers` Table                | | (`forge.engine.providers`)             |
| - `registered_models` Table            | | - OllamaAdapter                        |
| - Tenant / Project Scoping             | | - LMStudioAdapter                      |
| - Additive Migrations                  | | - VLLMAdapter / OpenAICompatibleAdapter|
+-------------------+--------------------+ | - OpenAIAdapter / AnthropicAdapter     |
                    |                      | - GoogleAdapter / Groq / DeepSeek      |
                    |                      +-------------+--------------------------+
+-------------------v------------------------------------v--------------------------+
| Runtime Resolution Layer (`forge.engine.models.resolve_model`)                    |
| - Resolves registered model ID -> fetches server -> resolves secrets               |
| - Applies effective inference parameters (temperature, max_output_tokens, top_p)  |
| - Constructs LangChain BaseChatModel client with connection pooling               |
| - Fallback compatibility layer for legacy references (logged, non-silent)         |
+-----------------------------------------------------------------------------------+
```

---

## 3. Core Abstractions

### A. ModelServer
Represents an inference host endpoint or cloud API provider.

- **Attributes**:
  - `id`: Unique identifier (e.g., `srv_ollama_local`, UUID).
  - `tenant_id`: Tenant/workspace ownership.
  - `name`: Human-readable label (e.g. "Living Room Mac Ollama", "Production Anthropic").
  - `provider_type`: `ollama` | `lm_studio` | `vllm` | `openai_compatible` | `openai` | `anthropic` | `google` | `groq` | `deepseek` | `mistral`.
  - `base_url`: Canonical endpoint origin (e.g., `http://localhost:11434`, `http://192.168.1.50:1234`). Managed cloud providers use fixed default origins.
  - `api_key_ref`: Secret reference (e.g., `secret://proj/openai_key`) or encrypted local secret.
  - `enabled`: Boolean toggle.
  - `created_at` / `updated_at`: Timestamps.

- **Responsibilities**:
  - Connection reachability testing (`POST /v1/models/servers/test`).
  - Active model discovery (`POST /v1/models/servers/{server_id}/discover`).
  - URL normalization and SSRF validation.
  - Safe credential resolution without leaking secrets in API responses.

### B. RegisteredModel
Represents an explicitly registered model that Alberto can execute.

- **Attributes**:
  - `id`: Immutable unique registry ID (UUID).
  - `tenant_id`: Tenant/workspace ownership.
  - `server_id`: Foreign key referencing parent `ModelServer.id`.
  - `model_name`: Upstream model identifier (e.g., `llama3.2:latest`, `claude-3-5-sonnet-20241022`).
  - `display_name`: Human-readable alias (e.g., "Home Butler Default (Fast)").
  - `enabled`: Boolean toggle.
  - `context_window_max`: Maximum context advertised or tested.
  - `context_window_configured`: Effective context limit assigned by user.
  - `supports_tools`: Tri-state capability (`True` / `False` / `None` [unknown]).
  - `supports_vision`: Tri-state capability (`True` / `False` / `None` [unknown]).
  - `temperature`: Default sampling temperature (float).
  - `top_p`: Default nucleus sampling parameter (float).
  - `max_output_tokens`: Output token ceiling (int).
  - `created_at` / `updated_at`: Timestamps.

- **Responsibilities**:
  - Exposing customized runtime parameters to the model resolution engine.
  - Ensuring execution selectors only present verified, registered models.
  - Providing independent inference and tool-calling validation.

---

## 4. Runtime Resolution & Lifecycle

### Resolution Precedence
When an agent or workflow executes:
1. `model_id` is resolved:
   - If explicit `registered_model_id` is specified on the node/agent, look up in registry.
   - If unset, resolve project's `default_model_id` (or fallback `default_model`).
   - If legacy string (e.g., `openai:gpt-4o` or `custom:...`), compatibility resolver matches existing registered models or legacy provider config with warning.
2. Verified enabled status: Disabled models raise an explicit `ModelExecutionError` (no silent substitution).
3. Associated `ModelServer` is loaded:
   - Server must be enabled.
   - Credential ref is resolved via `SecretStore`.
4. Provider adapter builds `BaseChatModel`:
   - Adapter injects `base_url`, `api_key`, parameter overrides (temperature, top_p, max_tokens).
   - Reuses client connection pools (`shared_llm_async_client`).
5. Execution proceeds with LangChain/LangGraph.

### Ephemeral Health Caching
To maintain high responsiveness on self-hosted devices:
- Runtime health is cached in-memory with a short TTL (e.g., 60 seconds).
- Background polling loops are avoided.
- Connectivity tests, inference tests, and discovery occur only upon user demand or explicitly triggered verification actions.

---

## 5. Security & Network Considerations

1. **SSRF Guardrails**:
   - Remote URL schemes are restricted to `http://` and `https://`.
   - Localhost and LAN IPs (e.g., `127.0.0.1`, `localhost`, `192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`) are permitted specifically for local inference engines (Ollama, LM Studio, vLLM).
   - Arbitrary public cloud redirects are prevented.
2. **Credential Safety**:
   - Provider API keys are written to the encrypted secret store (`SecretStore` with Fernet encryption).
   - Outbound REST payloads never expose plaintext credentials.
   - Keys are never logged in logs, traces, or error messages.
3. **URL Normalization**:
   - Strips trailing slashes and handles `/v1` endpoints consistently across Ollama (`/api/tags`), LM Studio (`/v1/models`), and standard OpenAI-compatible gateways.
