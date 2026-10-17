# Implementation Plan: Unified Models Page & Dynamic Local Model Registry

## 1. Objective

Transform Alberto's model management to be **local-first and self-hoster friendly**:
1. **Consolidate Model Settings**: Merge fragmented settings (*Default Model* from General, *Model Providers* from API Keys, and *Knowledge & Embeddings* from Knowledge) into a single, cohesive **Models** settings page.
2. **Support Local & OpenAI-Compatible Endpoints**: Allow users to configure self-hosted endpoints (Ollama, LM Studio, vLLM, LocalAI, llama.cpp, OpenRouter, Groq, DeepSeek) via custom `base_url` + optional API key.
3. **Auto-Discovery of Models**: Query `/v1/models` from configured endpoints to automatically populate available chat and embedding models in dropdowns without code edits.
4. **Dynamic Model Registry**: Maintain a unified list of active models across the butler workspace with per-model capabilities (tools, vision, context window).

---

## 2. Architecture & Data Model

### Zero-Migration Storage Pattern
To adhere to Alberto's stability rules, no database schema migration or table deletion is needed:
- Provider definitions and discovered models are stored workspace-wide in `Tenant.settings["model_providers"]` (backed by the existing JSON column on `tenants`). This makes all local and cloud models automatically available to all Butler projects.
- Encrypted provider API keys continue to use the encrypted `SecretStore` or server environment variables.
- Default models are configured workspace-wide in `Tenant.settings["default_model"]` and `Tenant.settings["rag_defaults"]` (with optional project-level fallbacks).

### Provider Configuration Schema (`Tenant.settings["model_providers"]`)
Starts empty. When user adds a provider (e.g. local Ollama or vLLM):
```json
[
  {
    "id": "ollama_home",
    "name": "Ollama Home Server",
    "type": "openai_compatible",
    "base_url": "http://192.168.1.100:11434/v1",
    "api_key_ref": "", 
    "enabled": true,
    "discovered_models": [
      {
        "id": "custom:ollama_home:llama3.2:latest",
        "name": "llama3.2:latest",
        "provider": "Ollama Home Server",
        "ctx": "128k",
        "tools": true,
        "vision": false
      }
    ]
  }
]
```

---

## 3. Detailed Phases

### Phase 1: Backend Auto-Discovery & Dynamic Model Catalog

#### 1.1 Discovery Endpoint (`backend/forge/routers/models.py`)
- Add `POST /v1/models/discover`:
  - Input: `{ base_url: str, api_key?: str, provider_name?: str }`
  - SSRF-guarded request (using `guarded_request` with local host allowance `http://localhost:*`, `http://127.0.0.1:*`, `http://host.docker.internal:*`, private LAN IPs).
  - Calls `{base_url}/models` (OpenAI format).
  - Returns standardized model list: `[{ id, name, owned_by }]`.

#### 1.2 Tenant-Scoped Models Endpoints (`backend/forge/routers/models.py`)
- Add `GET /v1/workspace/model-providers`: lists configured providers & discovered models.
- Add `POST /v1/workspace/model-providers`: creates a new provider and triggers discovery.
- Add `PATCH /v1/workspace/model-providers/{id}`: updates provider (enable/disable, refresh discovery).
- Add `DELETE /v1/workspace/model-providers/{id}`: removes provider.
- Update `GET /v1/models`:
  - Returns built-in cloud models (OpenAI, Anthropic, Google) + local FastEmbed.
  - Merges workspace-discovered models from `Tenant.settings["model_providers"]`.
  - Format conforms to `ModelCatalog` interface (`chat`, `embedding`, `reranker`).

### Phase 2: Engine Dispatch for Custom Providers (`backend/forge/engine/models.py`)

#### 2.1 Custom Model Resolution
- When an agent or node requests model `custom:<provider_id>:<model_name>`:
  - Looks up `<provider_id>` in `ctx.model_providers`.
  - Extracts `base_url` and resolves `api_key` from secret/env.
  - Instantiates `ChatOpenAI(model=model_name, base_url=base_url, api_key=api_key or "local", ...)` or LangChain `init_chat_model` with `openai_api_base`.
- Preserves keep-alive HTTP connection pooling and stream usage handling.

### Phase 3: Frontend Settings Consolidation

#### 3.1 New Unified "Models" Screen (`frontend/components/screens/settings.tsx`)
Replace scattered tabs with a dedicated **Models** section containing:

1. **Default Models Card**:
   - Default Chat Model (dropdown of all built-in + discovered models).
   - Embedding Model (FastEmbed local + OpenAI + discovered local embeddings).
   - Reranker Model (MiniLM-L6, BAAI bge-reranker).

2. **Cloud Model Providers Card**:
   - OpenAI, Anthropic, Google Gemini (API key inputs, Fernet-encrypted).

3. **Local & OpenAI-Compatible Endpoints Card**:
   - List of user-added providers with status indicators.
   - "+ Add Provider" button opening a clean modal:
     - Name (e.g. "Local Ollama", "vLLM Home Server")
     - Base URL (e.g. `http://localhost:11434/v1` or `http://192.168.1.100:8000/v1`)
     - API Key (optional)
     - "Test & Discover Models" button
   - Live status pill (`Connected · 4 models discovered` or error details).

4. **Active Model Registry Table**:
   - Shows all active models available across workflows.
   - Tags indicating source (`Cloud`, `Local`, `Discovered`), Tool Support (`tools`), Vision support (`vision`).

#### 3.2 Cleanup of Other Settings Tabs
- **General Tab**: Focuses on Project Name, Description, Project ID, Workspace ID, and Delete Project. Removes redundant "Default model" card.
- **API Keys Tab**: Renamed/focused on **Secrets & Credentials** (generic project secrets, DB passwords, integration tokens). Moves Model Providers to the Models tab.
- **Knowledge Tab**: Retains Chunking strategy, hybrid search ratios, and crawler options; references the embedding model set in Models.

---

## 4. Verification & Validation Steps

1. **Backend Tests**:
   - Unit test for `/v1/models/discover` with mocked local endpoint.
   - Unit test for `engine/models.py` verifying `ChatOpenAI` configuration with custom `base_url`.
   - Unit test for `GET /v1/models` dynamic catalog merging.
2. **Local API Testing**:
   - Test against a local Ollama instance (`http://localhost:11434/v1`).
   - Confirm discovered models appear in the Agent canvas model dropdown.
   - Run a test agent turn using a local model (e.g. `llama3.2`).
3. **Frontend Compilation**:
   - Verify `npx tsc --noEmit` and `npm run build` succeed with zero errors.

---

## 5. Rollback & Safety

- No database tables are altered.
- All configuration is backward-compatible with fallback to `settings.default_model`.
- Built-in cloud providers (OpenAI, Anthropic, Google) continue to work seamlessly even if no local providers are configured.
