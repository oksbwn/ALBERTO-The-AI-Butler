# Architecture & Design Plan: Alberto Local-First Model Registry & Provider Overhaul

## 1. Problem Statement & Motivation

### Current Issues:
1. **Cloud-First Bias**: The console displays 10+ unconfigured cloud models (OpenAI, Anthropic, Google, Groq, DeepSeek, Mistral) by default. In a local-first Home Butler (Alberto), this creates visual clutter and confusion.
2. **Disconnected Discovery**: Local engines (Ollama, LM Studio, vLLM) are treated as secondary "custom providers" separate from the main model list.
3. **No Attribute Tuning**: When models are discovered or configured, users cannot tune default parameters (context window, temperature, streaming, tool-calling flags, custom aliases) on a per-model basis.
4. **Picker Pollution**: Agents and workflow nodes display models that may have no working credentials or running local servers.

---

## 2. Core Architectural Principles

- **Zero-Phantom Policy**: No model appears in agent/workflow pickers unless it is explicitly registered and backed by a configured server (local or cloud).
- **Two-Tier Model**:
  1. **Servers / Providers (Hosts)**: Connection endpoint + credentials (e.g., `Ollama @ http://localhost:11434`, `LM Studio @ http://localhost:1234`, `OpenAI Cloud Gateway`).
  2. **Model Registry (Instances)**: Specific models hosted on a server, customized with user-defined attributes (context window, tool support, default temperature, alias, default flag).
- **Single Source of Truth**: All model pickers across Alberto (Chat, Agent Config, LLM nodes, Summarization) query the Active Model Registry.

---

## 3. Data Model

### A. Model Server / Provider (`ModelServer`)
Persisted under Tenant/Project configuration:
```json
{
  "id": "srv_ollama_local",
  "name": "Local Ollama",
  "type": "ollama", // "ollama" | "lm_studio" | "vllm" | "openai_compatible" | "cloud"
  "base_url": "http://localhost:11434",
  "api_key_ref": null, // or "secret://proj/openai_key" for cloud/secure proxies
  "status": "healthy", // "healthy" | "unreachable" | "untested"
  "last_synced_at": "2026-10-16T12:00:00Z"
}
```

### B. Registered Model (`RegisteredModel`)
```json
{
  "id": "model_llama3_q4",
  "server_id": "srv_ollama_local",
  "model_name": "llama3.2:latest", // Wire model identifier sent to LLM endpoint
  "display_name": "Llama 3.2 (Home Butler Default)",
  "is_default": true, // Designates project-wide default chat model
  "provider_type": "ollama",
  "attributes": {
    "context_window": 131072, // Context length in tokens
    "supports_tools": true,    // Enables ReAct agent function-calling
    "supports_vision": false,   // Multimodal vision support
    "temperature": 0.3,        // Default sampling temperature
    "top_p": 0.9,
    "max_tokens": 4096
  },
  "created_at": "2026-10-16T12:05:00Z"
}
```

---

## 4. Backend REST API (`forge.routers.models`)

### Server Management Endpoints
1. `GET /v1/models/servers`
   - Returns all registered local and cloud servers.
2. `POST /v1/models/servers`
   - Registers a new server (e.g., Ollama, LM Studio, Cloud provider).
3. `POST /v1/models/servers/test`
   - Validates connection to `base_url` + optional API key; probes `/v1/models` or `/api/tags`.
4. `POST /v1/models/servers/{server_id}/discover`
   - Probes the server and returns live available models currently running/installed.
5. `DELETE /v1/models/servers/{server_id}`
   - Removes a server and cascades removal of associated models from registry.

### Model Registry Endpoints
1. `GET /v1/models/registry`
   - Returns list of all active registered models with their attributes and `is_default` flag.
2. `POST /v1/models/registry`
   - Adds a model from a server to the registry with customized attributes.
3. `PATCH /v1/models/registry/{model_id}`
   - Updates model attributes (display name, context size, temperature, tools) or sets `is_default: true`.
4. `DELETE /v1/models/registry/{model_id}`
   - Removes model from registry.
5. `GET /v1/models` (Catalog Consumer)
   - Updated to return **only** registered models for agent/workflow dropdowns.

---

## 5. Frontend UI/UX Design

The current "Models & Providers" section in `Settings` is overhauled into a clean, modern registry interface:

### Screen Layout:
```
+-------------------------------------------------------------------------------+
| Models & Registry                                            [ + Add Model ]  |
+-------------------------------------------------------------------------------+
| Configured Models                                                             |
| Display Name         Server / Provider     Context   Caps     Default Actions |
| ----------------------------------------------------------------------------- |
| ★ Llama 3.2 8B       Ollama (localhost)    128k      Tools    [DEFAULT] [Edit] [X] |
|   Qwen 2.5 Coder     LM Studio (192.168.1) 32k       Tools    [Make Def] [Edit] [X]|
|   Claude 3.5 Sonnet  Anthropic Cloud       200k      Tools,Vis[Make Def] [Edit] [X]|
+-------------------------------------------------------------------------------+
| Registered Servers (3)                                       [ + Add Server ] |
| • Ollama (http://localhost:11434) - 2 models registered             [Sync] [Edit] |
| • LM Studio (http://localhost:1234) - 1 model registered            [Sync] [Edit] |
+-------------------------------------------------------------------------------+
```

### The "+ Add Model" Wizard (Modal):

#### Step 1: Select or Add Server
- Radio / Dropdown:
  - **Existing Server**: Select from already configured servers (`Ollama`, `LM Studio`, etc.).
  - **New Server**: Presets for:
    - `Ollama` (`http://localhost:11434`)
    - `LM Studio` (`http://localhost:1234/v1`)
    - `vLLM / LocalAI / OpenAI-Compatible`
    - `Cloud Provider` (OpenAI, Anthropic, Google, Groq, DeepSeek) with API Key field.
- Connection test indicator: green checkmark on reachability.

#### Step 2: Select Model from Server
- Automatically queries `/discover` on the chosen server.
- Dropdown or list populated with live models (e.g., `llama3.2:latest`, `mistral:7b`, `gpt-4o`).
- Manual entry option if model is loaded dynamically.

#### Step 3: Configure Attributes & Tuning
- **Display Name / Alias**: (e.g., "Home Butler Assistant (Fast)").
- **Context Length**: Slider / number (e.g., `8,192` to `131,072` tokens).
- **Capabilities toggles**:
  - `[x] Supports Tool / Function Calling` (critical for ReAct agents).
  - `[ ] Multimodal / Vision`.
- **Default Hyperparameters**:
  - Temperature (0.0 – 1.0, default 0.3).
  - Max Output Tokens.
- **Checkbox**: `[x] Make this the project default model`.
- Action: `[ Add to Active Registry ]`.

---

## 6. Execution Runtime Integration

In `backend/forge/engine/models.py`:
- `resolve_model(model_id, project_config)` looks up `model_id` in the active registry.
- Resolves server `base_url` and credentials.
- Injects tuned parameters (temperature, max_tokens) automatically into `ChatOpenAI`, `ChatOllama`, or `ChatAnthropic` instances.
- Replaces hardcoded model pricing and capability tables with user-configured attributes.

---

## 7. Migration & Backward Compatibility

- **Graceful Fallback**: If existing projects have `config.default_model` set to a legacy string like `openai:gpt-5.4` or `ollama:llama3`, the engine falls back to legacy resolution until user completes registry migration.
- **Auto-Discovery of Running Local Servers**: On first load, automatically probe `http://localhost:11434` (Ollama) and `http://localhost:1234` (LM Studio). If detected, display a prompt: *"Found local Ollama server running. Click to import models."*
