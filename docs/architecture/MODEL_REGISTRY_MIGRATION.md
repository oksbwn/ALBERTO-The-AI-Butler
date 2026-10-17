# Alberto — Model Registry Migration & Backward Compatibility Strategy

## 1. Objectives

1. Preserve all existing provider configurations and secrets.
2. Prevent existing workflows and agents from breaking if they reference legacy model strings (e.g. `openai:gpt-4.1-mini`, `anthropic:claude-sonnet-4-6`, `custom:prov_xxx:llama3`).
3. Transition storage cleanly from ad-hoc JSON blobs in `tenant.settings` to structured SQLite tables (`model_servers` and `registered_models`).
4. Ensure zero loss of user credentials, prompt templates, or historical execution traces.

---

## 2. Database Schema & Migration Execution

### Additive SQLite Migration
SQLite does not support altering foreign keys or dropping columns easily without recreation. We follow the existing Alberto schema upgrade convention:
1. Define ORM entities `ModelServer` and `RegisteredModel` in `forge.models.entities`.
2. Update `forge.db.base.init_db()` to automatically execute `Base.metadata.create_all()` and ensure indexes.
3. Write an Alembic migration script `0015_model_registry.py` matching the current sequence.

### Table Schema Definitions

#### `model_servers`
- `id`: VARCHAR(36) PRIMARY KEY
- `tenant_id`: VARCHAR(36) INDEX NOT NULL
- `name`: VARCHAR(120) NOT NULL
- `provider_type`: VARCHAR(40) NOT NULL
- `base_url`: VARCHAR(500) NOT NULL
- `api_key_ref`: VARCHAR(200) NULLABLE
- `enabled`: BOOLEAN NOT NULL DEFAULT 1
- `created_at`: DATETIME NOT NULL
- `updated_at`: DATETIME NOT NULL

#### `registered_models`
- `id`: VARCHAR(36) PRIMARY KEY
- `tenant_id`: VARCHAR(36) INDEX NOT NULL
- `server_id`: VARCHAR(36) NOT NULL (FK `model_servers.id`)
- `model_name`: VARCHAR(200) NOT NULL
- `display_name`: VARCHAR(200) NOT NULL
- `enabled`: BOOLEAN NOT NULL DEFAULT 1
- `context_window_max`: INTEGER NULLABLE
- `context_window_configured`: INTEGER NULLABLE
- `supports_tools`: BOOLEAN NULLABLE
- `supports_vision`: BOOLEAN NULLABLE
- `temperature`: FLOAT NULLABLE
- `top_p`: FLOAT NULLABLE
- `max_output_tokens`: INTEGER NULLABLE
- `created_at`: DATETIME NOT NULL
- `updated_at`: DATETIME NOT NULL

Unique Constraint: `(tenant_id, server_id, model_name)`

---

## 3. Data Migration from Legacy State

### Automatic Seed / Ingestion of Existing Providers
On startup during `init_db()` / startup lifespan:
1. Scan `tenants.settings.model_providers`:
   - If present, migrate each provider entry to `model_servers`.
   - For each discovered model previously stored in `discovered_models`, create a `registered_models` row linked to the server.
2. Scan `projects.config.provider_credentials`:
   - If cloud keys exist (`openai`, `anthropic`, `google`, etc.), create a corresponding `model_servers` entry for that cloud provider with `api_key_ref` set to the project credential secret reference.
3. If no models or servers exist at all, do NOT seed dozens of phantom cloud models. If the system is brand new, provide a clean empty state with one-click presets for Ollama, LM Studio, or Cloud.
4. Mark migrated JSON items so duplicate migrations do not occur.

---

## 4. Runtime Compatibility Layer

### Compatibility Resolver in `resolve_model()`
When `resolve_model(model_ref, ctx)` is invoked:
1. If `model_ref` matches an active registered model ID (`RegisteredModel.id`):
   - Fetch model record and parent server.
   - Inject configured parameters (`temperature`, `max_output_tokens`, `top_p`, `context_window_configured`).
   - Construct adapter client.
2. If `model_ref` is `None` or empty:
   - Check `project.config["default_model_id"]` or `tenant.settings["default_model_id"]`.
   - If found, resolve that registered model.
3. If `model_ref` is a legacy string:
   - Example 1: `custom:<provider_id>:<model_name>`. Look up server by legacy ID or migrated ID, resolve corresponding model or fallback to dynamic client.
   - Example 2: `openai:gpt-4o` or `anthropic:claude-3-5-sonnet`. Match against registered models with that wire `model_name`. If not yet registered, fall back to legacy `init_chat_model` using resolved project credentials, and log:
     ```
     [COMPAT] Legacy model reference 'openai:gpt-4o' used without explicit registry entry. Please register in Settings -> Models.
     ```
   - Example 3: `fake:...` or `fake`. Unconditionally resolves offline fake model for tests and playground dry-runs.

### Deprecation Path
1. Phase 1: Deploy new registry, dual-read compatibility.
2. Phase 2: Provide UI banner/notice prompting migration of unmapped legacy references.
3. Phase 3: Deprecate static fallback after all active workflows are migrated.
