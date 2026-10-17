# Architectural Dependency Analysis: Forge to Alberto Migration

**Document Version:** 1.0.0  
**Refactoring Branch:** `refactor/forge-to-alberto`  
**Base Commit / Tag:** Master baseline (clean working tree)  
**Execution Context:** Python 3.13 / FastAPI, Next.js 14, LangGraph, SQLite, ChromaDB  

---

## 1. Executive Summary

This document provides the architectural dependency analysis and reference audit for refactoring the legacy **Forge** application identity and runtime namespaces to **Alberto** without breaking runtime execution, database persistence, external integrations, security boundaries, or user data.

Per the refactoring charter:
- **No global search-and-replace** is permitted.
- Refactoring proceeds in isolated, verifiable dependency stages.
- No source code edits are executed until this analysis is complete and validated.

---

## 2. Baseline Status & Verification Metrics

Prior to refactoring, the system was verified on the dedicated branch `refactor/forge-to-alberto`:

| Subsystem | Metric / Check | Baseline Value | Status |
| :--- | :--- | :--- | :--- |
| **Git Tree** | `git status` | Clean (`refactor/forge-to-alberto`) | Verified |
| **Backend Unit Tests** | `pytest tests/` | 578 passed, 8 skipped, 36 xfailed | Verified (0 failures, 0 errors) |
| **Frontend Unit Tests** | `vitest run` | 4 passed | Verified (100% pass) |
| **Frontend Build** | `next build` | Production build successful, 4 static routes + middleware | Verified |
| **FastAPI Routes** | Route inspection | 38 top-level router groups, full `/v1/*` OpenAPI paths | Verified |
| **SQLite Database** | `data/db/alberto.db` | 35 tables, 0 columns named `forge` | Verified |
| **Checkpoints Store** | `data/db/checkpoints.sqlite` | 51 checkpoints, 78 writes, msgpack serialized states | Verified |
| **ChromaDB Path** | `data/chroma/` | Persistent vector directory | Verified |
| **Python Environment** | `backend/.venv` | Python 3.13.14 venv with all required packages | Verified |

---

## 3. Reference Classification & Dependency Audit

Every occurrence of `forge`, `Forge`, and `FORGE` across the codebase (1,910 matching lines) was traced and classified into six architectural categories:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Forge Reference Classification                       │
├────────────────────────┬─────────────────────────┬─────────────────────┤
│ Category               │ Example Identifiers     │ Migration Strategy  │
├────────────────────────┼─────────────────────────┼─────────────────────┤
│ A. Cosmetic Identity   │ Page titles, UI labels  │ Direct update       │
│ B. Python Namespace    │ backend/forge/ package  │ Coordinated rename  │
│ C. Internal Symbols    │ ForgeTracer, loggers    │ Rename with alias   │
│ D. Configuration       │ FORGE_* env vars        │ Dual-prefix support │
│ E. Persistence         │ DBs, checkpoints, salts │ Preserve / alias    │
│ F. API & Integrations  │ Headers, Next rewrites  │ Dual-path contracts │
└────────────────────────┴─────────────────────────┴─────────────────────┘
```

---

### Category A: Cosmetic Identity

Visible user-facing branding and human-readable text.

#### Matches Identified:
1. `README.md` & `backend/README.md`: Headings, descriptions, architectural overview.
2. `backend/forge/routers/auth.py`:
   - Invite email subject: `"You've been invited to Forge"` -> `"You've been invited to Alberto"`
   - Reset email subject: `"Reset your Forge password"` -> `"Reset your Alberto password"`
   - Verify email subject: `"Verify your Forge email"` -> `"Verify your Alberto email"`
3. `backend/forge/routers/oauth.py`:
   - OAuth completion HTML message: `"return to Forge"` -> `"return to Alberto"`
4. `frontend/components/screens/auth.tsx`:
   - Help text for `oauth2_client_credentials`: `"Forge trades a client id/secret..."` -> `"Alberto trades..."`
5. `frontend/components/screens/connectors.tsx`:
   - Copy: `"Not set up on this Forge deployment yet"` -> `"Not set up on this Alberto deployment yet"`
   - Copy: `"Whoever runs Forge registers one..."` -> `"Whoever runs Alberto registers one..."`
   - Copy: `"nobody types a secret into Forge"` -> `"nobody types a secret into Alberto"`
6. `frontend/components/screens/mcp.tsx`:
   - Copy: `"Forge connects and lists the server's tools..."` -> `"Alberto connects and lists the server's tools..."`
7. `frontend/components/screens/tools.tsx`:
   - Field help mentioning `FORGE_EGRESS_ALLOW_PRIVATE_HOSTS` updated to reference `ALBERTO_EGRESS_ALLOW_PRIVATE_HOSTS` (and legacy `FORGE_...`).
8. `frontend/app/globals.css`: Header comment tokens.

#### Dependencies & Risks:
- **Dependencies:** None.
- **Migration Risk:** Low (pure text changes).
- **Validation:** Frontend build compilation and visual inspection.

---

### Category B: Python Runtime Namespace

Active Python application package structure and import paths.

#### Matches Identified:
1. Directory: `backend/forge/` (contains 17 subdirectories, 9 root python modules).
2. Packaging:
   - `backend/pyproject.toml`:
     - `name = "forge-api"` -> `name = "alberto-api"`
     - `packages = ["forge"]` -> `packages = ["alberto"]`
     - `all = ["alberto-api[...]"]`
3. Entry Points & Invocation:
   - `start.sh`: `uvicorn forge.main:app` -> `uvicorn alberto.main:app`
   - `backend/Dockerfile`: `uvicorn forge.main:app`, stub package `alberto`, `COPY backend/alberto ./alberto`
   - `backend/alembic.ini`: `sqlalchemy.url = sqlite:///./.data/alberto.db`
   - `backend/migrations/env.py`: `import forge.models` -> `import alberto.models`, `from forge.config...` -> `from alberto.config...`
   - Background worker: `python -m alberto.worker`
4. Root Configuration:
   - `pytest.ini`: `pythonpath = backend`
   - `backend/pyproject.toml`: `testpaths = ["../tests/backend"]`, `pythonpath = ["."]`
5. Source Code Imports:
   - 566 import statements across `backend/` (`from forge...`, `import forge`).
   - 417 import statements across `tests/` (`from forge...`, `import forge`).

#### Dependencies & Risks:
- **Dependencies:**
  - Static imports in every backend router, service, node, engine, model, and utility.
  - Test suites importing directly from `forge.*`.
  - Dynamic imports (e.g. `importlib.import_module`, Alembic target metadata).
  - Serialized module paths if any pickled objects exist.
- **Migration Risk:** Medium-High if imports fall out of synchronization.
- **Mitigation Strategy:**
  1. Rename `backend/forge/` to `backend/alberto/`.
  2. Implement a Python runtime shim in `backend/alberto/__init__.py` and `backend/forge/__init__.py`:
     ```python
     # Compatibility alias so any existing reference to `forge.*` maps transparently to `alberto.*`
     import sys
     import alberto
     sys.modules.setdefault("forge", alberto)
     ```
  3. Surgically update all package imports from `forge` to `alberto`.
  4. Update `pyproject.toml`, Dockerfile, Alembic env, and launcher scripts in lockstep.
- **Validation:**
  - `python -c "import alberto.main; from alberto.main import app; print(len(app.routes))"` -> verify 38 routes.
  - Full pytest execution: all 578 unit tests pass without import errors.

---

### Category C: Internal Programmatic Identifiers

Classes, logger names, runtime context objects, and internal constants.

#### Matches Identified:
1. `ForgeTracer` in `backend/forge/tracing/tracer.py`:
   - Core callback handler recording spans for runs.
   - References across `backend/forge/services/runs.py`, `assistant.py`, `evals.py`, `test_tool_io_capture.py`, `test_embedding_spans.py`.
2. Logger Names:
   - `logging.getLogger("forge.main")`, `logging.getLogger("forge.reaper")`, `logging.getLogger("forge.retention")`, `logging.getLogger("forge.scheduler")`, `logging.getLogger("forge.config")`.
3. System Identity Defaults:
   - `CurrentUser(id="service", role="editor", email="service@forge.local")` in `backend/forge/deps.py`.
   - Default SMTP from: `"Forge <no-reply@forge.local>"` in `backend/forge/config.py`.
   - Crawler user agent: `_USER_AGENT = "ForgeKnowledgeBot"` in `backend/forge/knowledge/crawl.py`.
4. Frontend React Flow Canvas:
   - `ForgeNode` component in `frontend/components/canvas/ForgeNode.tsx`.
   - Node type map in `frontend/components/screens/workflows.tsx`: `nodeTypes = useMemo(() => ({ forge: ForgeNode }), [])`.
   - Canvas wrapper class: `.forge-canvas`.
5. Frontend State Events:
   - CustomEvent `"forge:counts-changed"` in `platform.tsx`, `shell.tsx`, `api.ts`.
   - CustomEvent `"forge:unauthorized"` in `api.ts`.

#### Dependencies & Risks:
- **Dependencies:**
  - Workflows stored in SQLite `workflows` table have `"nodes": [{"type": "forge", ...}]`. If React Flow `nodeTypes` only maps `alberto`, existing canvas graphs fail to render!
  - Logger subscriptions and tracing sinks.
- **Migration Risk:** Medium (breaking canvas rendering if `forge` node type dropped).
- **Mitigation Strategy:**
  1. Class Rename: `AlbertoTracer(BaseCallbackHandler)`. Add explicit alias:
     ```python
     ForgeTracer = AlbertoTracer  # Backward compatibility alias
     ```
  2. Canvas Node Types: Support BOTH in `nodeTypes`:
     ```typescript
     const nodeTypes = useMemo(() => ({
       alberto: AlbertoNode,
       forge: AlbertoNode, // Seamless rendering of existing workflows
     }), []);
     ```
  3. Events: Dispatch and listen for both `alberto:*` and `forge:*`.
  4. Context User: Support `service@alberto.local` with fallback to `service@forge.local`.
- **Validation:**
  - Verify canvas renders existing workflow from `data/db/alberto.db`.
  - Verify `AlbertoTracer` records spans accurately.

---

### Category D: Configuration Contracts

Environment variables, pydantic settings schema, and compose configuration.

#### Matches Identified:
1. Pydantic Settings Prefix:
   - `backend/forge/config.py`: `model_config = SettingsConfigDict(env_prefix="FORGE_", ...)`
2. Default Paths and Properties:
   - `_get_logical_data_root()`: checks `ALBERTO_DATA_DIR` or `FORGE_DATA_DIR`.
   - Database candidates: `root / "db" / "alberto.db"`, `root / "db" / "forge.db"`.
   - Checkpoint candidates: `root / "db" / "checkpoints.sqlite"`.
3. Configuration Keys:
   - `FORGE_JWT_SECRET` / `ALBERTO_JWT_SECRET`
   - `FORGE_DATABASE_URL` / `ALBERTO_DATABASE_URL`
   - `FORGE_CHECKPOINT_BACKEND` / `ALBERTO_CHECKPOINT_BACKEND`
   - `FORGE_ENABLE_SCHEDULER` / `ALBERTO_ENABLE_SCHEDULER`
   - `FORGE_SCHEDULER_LEADER` / `ALBERTO_SCHEDULER_LEADER`
   - `FORGE_BOOTSTRAP_ADMIN_EMAIL` / `ALBERTO_BOOTSTRAP_ADMIN_EMAIL`
   - `FORGE_BOOTSTRAP_ADMIN_PASSWORD` / `ALBERTO_BOOTSTRAP_ADMIN_PASSWORD`
   - `FORGE_PUBLIC_BASE_URL` / `ALBERTO_PUBLIC_BASE_URL`
   - `FORGE_PUBLIC_CONSOLE_URL` / `ALBERTO_PUBLIC_CONSOLE_URL`
   - `FORGE_CORS_ORIGINS` / `ALBERTO_CORS_ORIGINS`
   - `FORGE_SERVICE_API_TOKEN` / `ALBERTO_SERVICE_API_TOKEN`
   - `FORGE_EGRESS_ALLOW_PRIVATE_HOSTS` / `ALBERTO_EGRESS_ALLOW_PRIVATE_HOSTS`
   - `FORGE_TOOL_VARS` / `ALBERTO_TOOL_VARS`
   - `FORGE_CONNECTOR_OAUTH_APPS` / `ALBERTO_CONNECTOR_OAUTH_APPS`
   - `FORGE_DEFAULT_TOKEN_CTX_KEY` / `ALBERTO_DEFAULT_TOKEN_CTX_KEY`
4. Container & Orchestration Files:
   - `docker-compose.yml`: services `api` and `web`, env vars `FORGE_*`, volume `alberto-data`.
   - `start.sh`: `ALBERTO_DATA_DIR:-${FORGE_DATA_DIR...}`, ports `PORT:-${FORGE_PORT:-8000}`.
   - `.env.example`: documented environment variables.

#### Dependencies & Risks:
- **Dependencies:** Existing `.env` files, production deployments, container orchestration.
- **Migration Risk:** Critical if existing environment secrets or configs are silently ignored.
- **Mitigation Strategy:**
  - Implement a dual-prefix source loader in `Settings`:
    - Primary prefix: `ALBERTO_`
    - Fallback alias: `FORGE_`
    - Rule: Any setting specified as `ALBERTO_<KEY>` takes precedence; if unset, `FORGE_<KEY>` is read.
  - Update `docker-compose.yml` to define `ALBERTO_*` variables with `${ALBERTO_*:-${FORGE_*}}` fallback interpolation.
  - Update `.env.example` to document `ALBERTO_*` while clearly noting backward compatibility for `FORGE_*`.
- **Validation:**
  - Test setting precedence: verify `ALBERTO_PORT` overrides `FORGE_PORT`, and un-prefixed fallback works.

---

### Category E: Persistent Identifiers

Database files, schemas, serialized data, checkpoints, and vector collections.

#### Matches Identified:
1. Primary SQLite Database:
   - Current location: `data/db/alberto.db` (file size ~782 KB).
   - Current schema: 35 tables (`tenants`, `projects`, `workflows`, `users`, `traces`, `agents`, etc.).
   - Analysis: The physical DB file is ALREADY named `alberto.db`. No tables or columns contain `forge`.
2. Checkpoint Database:
   - Location: `data/db/checkpoints.sqlite` (file size ~172 KB, WAL ~292 KB).
   - Tables: `checkpoints` (51 rows), `writes` (78 rows).
   - Binary inspection: Checkpoints contain serialized msgpack blobs referencing `name: "forge-platform"` and `path: "/skills/forge-platform/SKILL.md"`.
3. In-Product Assistant Skills:
   - Directory: `backend/forge/assistant_skills/forge-platform/SKILL.md`.
   - Code: `backend/forge/services/assistant.py` mounts `/skills/` to `_SKILLS_DIR`.
4. ChromaDB Vector Collections:
   - In `backend/forge/services/knowledge.py`:
     - `forge_kb_{dim}` (document knowledge base chunks)
     - `forge_qa_{dim}` (Q&A pairs)
   - In `backend/forge/services/memory.py`:
     - `forge_mem_{dim}` (long-term memories)
   - In `backend/forge/services/semantic_cache.py`:
     - `forge_cache_{dim}` (agent semantic cache)
5. Historical Traces:
   - In `alberto.db` table `traces`, column `ai_response`: Contains historical message text ("Hello! I'm the Forge Assistant...").
6. API Key Prefix:
   - In `backend/forge/services/apikeys.py`: `_KEY_PREFIX = "forge_sk_"`.

#### Dependencies & Risks:
- **Dependencies:**
  - Existing Chroma collections will be orphaned if collection names are changed.
  - Existing LangGraph checkpoints will fail on resume if `forge-platform` skill path is missing.
  - Existing issued API keys will fail auth if `forge_sk_` prefix is rejected.
  - Historical traces must remain intact per Rule 9.
- **Migration Risk:** High (risk of data loss or thread corruption if changed).
- **Mitigation Strategy:**
  1. Chroma Collections: Keep existing collection names `forge_kb_*`, `forge_qa_*`, `forge_mem_*`, `forge_cache_*` for all existing and default collections. Do not rename active vector collections.
  2. Assistant Skills: Keep `forge-platform` available (create `alberto-platform` and maintain compatibility symlink/duplicate so `/skills/forge-platform/SKILL.md` resolves).
  3. API Keys: Update new key prefix to `alberto_sk_`, while accepting BOTH in `looks_like_api_key`:
     ```python
     _KEY_PREFIX = "alberto_sk_"
     _LEGACY_KEY_PREFIX = "forge_sk_"

     def looks_like_api_key(token: str) -> bool:
         return token.startswith(_KEY_PREFIX) or token.startswith(_LEGACY_KEY_PREFIX)
     ```
  4. Historical Data: No modifications to existing rows in `alberto.db` or `checkpoints.sqlite`.
- **Validation:**
  - Verify existing checkpoint resume works.
  - Verify existing API key format validation passes for both prefixes.

---

### Category F: API and Integration Contracts

External HTTP endpoints, headers, proxies, tokens, and payloads.

#### Matches Identified:
1. Next.js Frontend Rewrites:
   - `frontend/next.config.mjs`:
     ```javascript
     return [{ source: "/api/forge/:path*", destination: `${api}/:path*` }];
     ```
2. Frontend API Client:
   - `frontend/lib/api.ts`: `const BASE = "/api/forge";`
   - `NEXT_PUBLIC_FORGE_API_URL` / `NEXT_PUBLIC_ALBERTO_API_URL`
   - Local storage keys: `forge_access_token`, `forge_refresh_token`
3. Request Headers:
   - Per-run context: `X-Forge-Context` (`backend/forge/deps.py` line 142)
   - Webhook signature: `X-Forge-Signature` (`backend/forge/routers/hooks.py`)
   - Custom test headers: `X-Forge-Client-Id`, `X-Forge-Service-Token`
4. Connector Manifest Specification:
   - Format identifier: `FORMAT = "forge.connector/1"` in `backend/forge/connectors/manifest.py`.
   - Catalog manifests: 12 vendor JSON files declare `"format": "forge.connector/1"` and `"publisher": "forge"`.
5. Generative UI Component Markers:
   - `[[forge:component:<instance_id>]]` in `backend/forge/tools/components.py` and `frontend/lib/chat-parts.ts`.
6. JSON Schema Registry URIs:
   - `backend/forge/schemas/contracts.py`: `BASE = "https://forge.dev/schemas/"` and schemas located in `backend/schemas/forge/`.

#### Dependencies & Risks:
- **Dependencies:**
  - External webhook senders might already send `X-Forge-Signature`.
  - External callers might send `X-Forge-Context`.
  - Browser local storage contains active `forge_access_token` sessions.
  - Custom connectors or catalog entries authored as `forge.connector/1`.
- **Migration Risk:** High for external integrations and active sessions.
- **Mitigation Strategy:**
  1. Next.js Proxy: Rewrite BOTH `/api/alberto/:path*` AND `/api/forge/:path*` to backend.
  2. Request Context Header: Accept `X-Alberto-Context` first; fall back to `X-Forge-Context`:
     ```python
     raw = request.headers.get("x-alberto-context") or request.headers.get("x-forge-context")
     ```
  3. Webhook Signature Header: Accept `X-Alberto-Signature` first; fall back to `X-Forge-Signature` and `X-Hub-Signature-256`.
  4. Local Storage Tokens: `getToken()` reads `alberto_access_token` || `forge_access_token`. `setToken()` writes both. `clearTokens()` removes both.
  5. Connector Manifest: Support both `alberto.connector/1` (default) and `forge.connector/1` (legacy).
  6. Generative UI Markers: Regex supports both `[[alberto:component:...]]` and `[[forge:component:...]]`.
  7. Schema Registry: Maintain schema loading from `backend/schemas/alberto` and fallback `backend/schemas/forge` with URI normalization.
- **Validation:**
  - Automated test verifying both `X-Alberto-Context` and `X-Forge-Context` are processed.
  - Automated test verifying both signature headers validate.
  - Connector parsing test for both manifest versions.

---

## 4. Refactoring Risk Matrix

| Risk ID | Scope | Likelihood | Impact | Severity | Mitigation Measure |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R1** | Broken Python package imports (`forge` -> `alberto`) | Medium | High | **HIGH** | Coordinated rename + `sys.modules["forge"] = alberto` fallback shim |
| **R2** | React Flow canvas rendering failure for existing workflows | High | High | **HIGH** | Map both `{ alberto: AlbertoNode, forge: AlbertoNode }` in `nodeTypes` |
| **R3** | External webhook verification failure (`X-Forge-Signature`) | Medium | High | **HIGH** | Header inspection accepts both `x-alberto-signature` and `x-forge-signature` |
| **R4** | Existing user logout due to token key rename | High | Medium | **MEDIUM** | Read `alberto_access_token` with fallback to `forge_access_token` |
| **R5** | Loss of historical Chroma embeddings or vectors | Low | Critical | **CRITICAL** | Preserve Chroma collection names `forge_kb_*`, `forge_qa_*`, `forge_mem_*` |
| **R6** | Resumed LangGraph checkpoint crash on missing skill | Medium | High | **HIGH** | Maintain `forge-platform` skill alongside `alberto-platform` |
| **R7** | Connector manifest rejection during custom install | Medium | High | **HIGH** | Accept both `alberto.connector/1` and `forge.connector/1` in validator |
| **R8** | Deployment failure from unmapped `FORGE_*` env vars | Medium | High | **HIGH** | Implement `ALBERTO_*` with `FORGE_*` fallback in Pydantic settings |

---

## 5. Staged Execution Plan & Verification Gates

Refactoring must proceed across isolated stages with strict verification gates:

```
[Phase 1: Dependency Analysis] (Complete)
           │
           ▼
[Stage A: Product Branding] ────────────► Gate A: Frontend build & vitest pass
           │
           ▼
[Stage B: Backend Package Rename] ──────► Gate B: pytest 578+ pass, uvicorn boots
           │
           ▼
[Stage C: Internal Programmatic IDs] ───► Gate C: Tracing, NodeTypes & Canvas pass
           │
           ▼
[Stage D: Configuration & Env Vars] ────► Gate D: Dual-prefix settings verified
           │
           ▼
[Stage E: Database & Persistence] ──────► Gate E: alberto.db & checkpoints verified
           │
           ▼
[Stage F: API & External Contracts] ────► Gate F: Headers, Next rewrites verified
           │
           ▼
[Phase 6: E2E Regression Verification] ──► All suites clean, zero functional regressions
```

---

## 6. Sign-off & Conclusion

The dependency analysis proves that a controlled semantic refactoring from Forge to Alberto is structurally viable and safe when executed with compatibility shims for persistent identifiers, serialized checkpoints, and external API headers.

**Source code modification is cleared to proceed to Stage A.**
