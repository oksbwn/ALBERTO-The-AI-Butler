# Alberto — Model Registry & Provider API Specification

## 1. Overview
This document specifies the REST API contracts for Alberto's Model Server Management, Model Registry, Testing, and Unified Model Consumption. All endpoints are hosted under `/v1/models` and require authenticated tenant access.

---

## 2. Server Management Endpoints

### 2.1 List Configured Servers
- **Endpoint**: `GET /v1/models/servers`
- **Auth**: Requires `viewer` role or above.
- **Response**: `200 OK`
```json
[
  {
    "id": "srv_ollama_local",
    "name": "Local Ollama",
    "provider_type": "ollama",
    "base_url": "http://localhost:11434",
    "api_key_ref": null,
    "enabled": true,
    "registered_models_count": 2,
    "status": "healthy",
    "created_at": "2026-10-16T12:00:00Z",
    "updated_at": "2026-10-16T12:00:00Z"
  }
]
```

### 2.2 Register a Server
- **Endpoint**: `POST /v1/models/servers`
- **Auth**: Requires `editor` role or above.
- **Request Body**:
```json
{
  "name": "Local Ollama",
  "provider_type": "ollama",
  "base_url": "http://localhost:11434",
  "api_key": null,
  "enabled": true
}
```
- **Response**: `201 Created` with created `ModelServerOut`.

### 2.3 Update a Server
- **Endpoint**: `PATCH /v1/models/servers/{server_id}`
- **Auth**: Requires `editor` role or above.
- **Request Body**:
```json
{
  "name": "Updated Server Name",
  "base_url": "http://192.168.1.100:11434",
  "api_key": "optional_new_key",
  "enabled": true
}
```
- **Response**: `200 OK` with updated `ModelServerOut`.

### 2.4 Delete a Server
- **Endpoint**: `DELETE /v1/models/servers/{server_id}`
- **Auth**: Requires `editor` role or above.
- **Behavior**: Checks for active model dependencies and configuration references. Refuses deletion if models on this server are referenced by active agents or as the project default, unless forced or dependencies are reassigned.
- **Response**: `204 No Content`

### 2.5 Test Server Reachability
- **Endpoint**: `POST /v1/models/servers/test`
- **Auth**: Requires `editor` role or above.
- **Request Body**:
```json
{
  "provider_type": "ollama",
  "base_url": "http://localhost:11434",
  "api_key": null
}
```
- **Response**: `200 OK`
```json
{
  "ok": true,
  "status_code": 200,
  "latency_ms": 14,
  "discovered_count": 3,
  "error": null
}
```

### 2.6 Discover Models on Server
- **Endpoint**: `POST /v1/models/servers/{server_id}/discover`
- **Auth**: Requires `editor` role or above.
- **Response**: `200 OK`
```json
{
  "ok": true,
  "server_id": "srv_ollama_local",
  "models": [
    {
      "model_name": "llama3.2:latest",
      "display_name": "llama3.2:latest",
      "context_window_max": 131072,
      "supports_tools": true,
      "supports_vision": false,
      "is_registered": true,
      "registered_model_id": "mod_12345"
    }
  ],
  "error": null
}
```

---

## 3. Model Registry Endpoints

### 3.1 List Registered Models
- **Endpoint**: `GET /v1/models/registry`
- **Auth**: Requires `viewer` role or above.
- **Response**: `200 OK`
```json
[
  {
    "id": "mod_12345",
    "server_id": "srv_ollama_local",
    "server_name": "Local Ollama",
    "provider_type": "ollama",
    "model_name": "llama3.2:latest",
    "display_name": "Home Butler Llama 3.2",
    "enabled": true,
    "context_window_max": 131072,
    "context_window_configured": 32768,
    "supports_tools": true,
    "supports_vision": false,
    "temperature": 0.3,
    "top_p": 0.9,
    "max_output_tokens": 4096,
    "is_default": true,
    "availability": "available",
    "created_at": "2026-10-16T12:00:00Z",
    "updated_at": "2026-10-16T12:00:00Z"
  }
]
```

### 3.2 Register a Model
- **Endpoint**: `POST /v1/models/registry`
- **Auth**: Requires `editor` role or above.
- **Request Body**:
```json
{
  "server_id": "srv_ollama_local",
  "model_name": "llama3.2:latest",
  "display_name": "Home Butler Llama 3.2",
  "enabled": true,
  "context_window_max": 131072,
  "context_window_configured": 32768,
  "supports_tools": true,
  "supports_vision": false,
  "temperature": 0.3,
  "top_p": 0.9,
  "max_output_tokens": 4096,
  "set_as_default": true
}
```
- **Response**: `201 Created`

### 3.3 Update Registered Model
- **Endpoint**: `PATCH /v1/models/registry/{model_id}`
- **Auth**: Requires `editor` role or above.
- **Request Body**:
```json
{
  "display_name": "Home Butler Llama 3.2 (Tuned)",
  "enabled": true,
  "context_window_configured": 65536,
  "supports_tools": true,
  "supports_vision": false,
  "temperature": 0.2,
  "top_p": 0.95,
  "max_output_tokens": 8192,
  "set_as_default": false
}
```
- **Response**: `200 OK`

### 3.4 Delete Registered Model
- **Endpoint**: `DELETE /v1/models/registry/{model_id}`
- **Auth**: Requires `editor` role or above.
- **Behavior**: Validates whether the model is referenced as default or by active agent nodes. Rejects deletion if dependencies exist without reassignment.
- **Response**: `204 No Content`

---

## 4. Model Testing Endpoints

### 4.1 Test Inference
- **Endpoint**: `POST /v1/models/registry/{model_id}/test-inference`
- **Auth**: Requires `editor` role or above.
- **Request Body**: Optional `{ "prompt": "Ping" }`.
- **Response**: `200 OK`
```json
{
  "ok": true,
  "latency_ms": 128,
  "response_snippet": "Pong! Local inference running smoothly.",
  "error": null
}
```

### 4.2 Test Tool Calling
- **Endpoint**: `POST /v1/models/registry/{model_id}/test-tools`
- **Auth**: Requires `editor` role or above.
- **Behavior**: Binds a safe dummy tool (`check_device_status(device_name: string)`), invokes the model with an instruction demanding the tool call, and verifies the tool call payload without running real device hardware.
- **Response**: `200 OK`
```json
{
  "ok": true,
  "latency_ms": 210,
  "tool_called": "check_device_status",
  "tool_args": { "device_name": "living_room_light" },
  "error": null
}
```

---

## 5. Project Default Model & Unified Consumer API

### 5.1 Set Default Model
- **Endpoint**: `PUT /v1/models/default`
- **Auth**: Requires `editor` role or above.
- **Request Body**:
```json
{
  "model_id": "mod_12345"
}
```
- **Response**: `200 OK`

### 5.2 Unified Model Picker API
- **Endpoint**: `GET /v1/models`
- **Auth**: Requires `viewer` role or above.
- **Response**: `200 OK`
```json
{
  "chat": [
    {
      "id": "mod_12345",
      "name": "Home Butler Llama 3.2",
      "provider": "Ollama",
      "ctx": "32k",
      "tools": true,
      "vision": false,
      "is_default": true,
      "available": true
    }
  ],
  "embedding": [...],
  "reranker": [...]
}
```
*Note*: No phantom models appear in `chat`. Only registered and enabled models are returned.
