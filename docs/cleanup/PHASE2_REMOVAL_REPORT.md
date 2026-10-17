# Phase 2: REST API & Supporting Infrastructure Cleanup Report

## Executive Summary

Phase 2 continues the simplification of Forge into Alberto, a local-first AI Home Butler. Following Phase 1 (MCP server removal), Phase 2 eliminates unnecessary Forge-specific features, including public chatbot embedding and external API key management endpoints, alongside their frontend screens, navigation, routers, authentication mechanisms, and rate limits.

All shared core capabilities—agent execution, tool invocation, knowledge ingestion, workflow automation, and local developer execution APIs—were preserved. No destructive database migrations or table drops occurred.

---

## Endpoint Metrics

| Metric | Count |
|---|---|
| **Phase 1 Endpoints (Post-MCP Removal)** | 198 |
| **Phase 2 Endpoints Removed** | 11 |
| **Phase 2 Active Endpoints Remaining** | 187 |
| **FastAPI Active Router Modules** | 31 |

---

## Detailed Removals

### 1. Endpoints Removed (11 Total)

#### Public Chatbot Embedding (`embed_public.py`) — 5 endpoints
- `GET /v1/embed/{key}/config` — Public configuration retrieval for embed widget.
- `GET /v1/embed/{key}/components` — Public component definition retrieval for embed widget.
- `POST /v1/embed/{key}/runs` — Unauthenticated/session-token agent run launcher.
- `GET /v1/embed/{key}/runs/{run_id}/stream` — Public SSE stream for agent run execution.
- `POST /v1/embed/{key}/runs/{run_id}/resume` — Public resumption of human-in-the-loop executions.

#### Embed Project Management (`embed.py`) — 3 endpoints
- `GET /v1/projects/{project_id}/embed` — Project embed settings read.
- `PUT /v1/projects/{project_id}/embed` — Project embed settings update.
- `POST /v1/projects/{project_id}/session-tokens` — Ephemeral session token generation for iframe embeds.

#### External API Key Management (`auth.py`) — 3 endpoints
- `GET /v1/api-keys` — List issued Forge programmatic API keys.
- `POST /v1/api-keys` — Issue new Forge programmatic API key.
- `DELETE /v1/api-keys/{key_id}` — Revoke programmatic API key.

---

### 2. Backend Modules & Code Removed

#### Modules Deleted
- `backend/forge/routers/embed.py`
- `backend/forge/routers/embed_public.py`

#### Modules Modified & Stripped
- **`backend/forge/main.py`**:
  - Removed router imports for `embed` and `embed_public`.
  - Unmounted `auth.apikeys_router`, `embed.router`, and `embed_public.router`.
- **`backend/forge/routers/auth.py`**:
  - Removed `apikeys_router`, `ApiKeyCreateIn`, `_apikey_out`, `list_api_keys`, `create_api_key`, `revoke_api_key`.
- **`backend/forge/config.py`**:
  - Removed `embed_rate_limit_per_minute` (default: 60).
  - Removed `embed_rate_limit_per_ip_per_minute` (default: 30).
  - Removed `embed_stream_limit_per_ip_per_minute` (default: 10).
- **`backend/forge/security.py`**:
  - Removed `create_session_token` helper (issued 1-hour HS256 tokens for embed sessions).
- **`backend/forge/services/budget.py`**:
  - Cleaned references to `embed_public` from comments.
- **`backend/forge/routers/project_run.py` & `backend/forge/routers/runs.py`**:
  - Cleaned references to public embed runs in docstrings.

---

### 3. Frontend Modules & Code Removed

#### Files Deleted
- `frontend/app/embed/page.tsx` — Standalone iframe route for embedded chat widget.
- `frontend/components/screens/embed.tsx` — `EmbedScreen` component for previewing/configuring embed widget.
- `frontend/public/launcher.js` — Embed launcher script loaded by external web pages.
- `frontend/components/screens/deploy.tsx` — Connect & Run API developer documentation screen (removed from UI; backend `/run` endpoint preserved).

#### Files Modified & Cleaned
- **`frontend/lib/api.ts`**:
  - Removed `EmbedSettings` interface.
  - Removed `getEmbed()` and `setEmbed()` client API methods.
- **`frontend/middleware.ts`**:
  - Removed `/embed` public path bypass.
  - Removed external embed token header forwarder.
  - Hardened Content Security Policy: set `frame-ancestors 'none'` and `X-Frame-Options: DENY` across all routes (prevents iframe clickjacking now that Alberto is not embeddable).
- **`frontend/app/page.tsx`**:
  - Removed `EmbedScreen` and `ConnectScreen` imports.
  - Removed `embed` and `connect` from screen routing table and `SCREEN_LABEL` dictionary.
- **`frontend/lib/data.ts`**:
  - Removed `connect` ("Connect & API") navigation entry from `PROJECT_NAV` in the `integrations` section.

---

### 4. Authentication & Security Changes

1. **Removed Embed Public Key Validation**:
   - Eliminated anonymous execution vectors via publishable embed keys.
2. **Removed Ephemeral Session Tokens**:
   - `create_session_token` removed from `backend/forge/security.py`.
3. **Removed Public API Key CRUD**:
   - External developer API key creation endpoints (`/v1/api-keys`) removed.
   - Internal API token resolution (`ApiKeyService.resolve`) retained for backward compatibility with existing tokens.
4. **Hardened Clickjacking Defense**:
   - `frontend/middleware.ts` now enforces `frame-ancestors 'none'` and `X-Frame-Options: DENY`.

---

## Preserved Infrastructure

### 1. Automation Execution (`POST /v1/projects/{project_id}/run`)
- Retained programmatic workflow and agent execution endpoint for local scripts, cron jobs, and home automation integrations.
- Authentication verified: Protected by `FORGE_SERVICE_API_TOKEN` bearer header check via `require_service_token` dependency (`backend/forge/routers/project_run.py`).
- Fallback allows authenticated session users to trigger runs directly.

### 2. Core Alberto Capabilities Preserved
- **AI & Agent Orchestration**: LangGraph runtime, ReAct tools, subagents, conversation threads, streaming runs, and human-in-the-loop approvals (`/v1/runs`, `/v1/agents`, `/v1/threads`).
- **Tools & MCP Integrations**: Internal tool registry, MCP client runtime, connectors, OAuth callbacks (`/v1/tools`, `/v1/connectors`).
- **Knowledge & Memory**: Document processing, vector ingestion, ChromaDB collections, hybrid retrieval (`/v1/knowledge`).
- **Workflows & Automation**: Workflow definitions, node execution graphs, cron scheduler, webhook listeners (`/v1/workflows`, `/v1/triggers`, `/v1/webhooks`).
- **App Platform**: LLM provider credentials, user session JWT, secrets management, health checks (`/v1/auth`, `/v1/providers`, `/v1/secrets`, `/health`).

### 3. Database Artifacts Intentionally Retained
To comply with strict data safety requirements (no destructive migrations or table drops):
- **`api_keys` Table**: Kept intact in SQLite database. `ApiKey` ORM model preserved in `backend/forge/models/entities.py`.
- **`Project.embed_key` Column**: Kept intact in SQLAlchemy model to prevent schema mismatch against existing SQLite databases.
- **Data Persistence**: `/data` directory, SQLite database files (`dev.db`, `auth.db`), and ChromaDB collections preserved without modification.

---

## Step 6: Review of Other Forge SaaS Functionality (Phase 3 Recommendations)

| Feature Area | Endpoints / Modules | Classification | Phase 3 Recommendation | Technical Rationale |
|---|---|---|---|---|
| **Multi-User Team Invitations** | `/v1/organizations/{org_id}/invitations`, `backend/forge/routers/invitations.py` | LEGACY | **REMOVE** | Alberto is a local home butler for single-family or single-operator households. Self-registration and public invitation tokens are SaaS artifacts. Removal simplifies auth and prevents external invite vulnerabilities. |
| **Workspace / Organization Administration** | `/v1/organizations/*`, `backend/forge/routers/organizations.py` | REVIEW | **DEFER** | User accounts and projects currently link through `organization_id` foreign keys. Flattening to a single-tenant structure requires careful DB migration; defer until schema simplification phase. |
| **Multi-Project Management** | `/v1/projects/*`, `backend/forge/routers/projects.py` | CORE | **KEEP** | Projects act as namespaces for distinct household domains (e.g. "Home Automation", "Family Schedule", "Research Assistant"). Alberto frontend depends heavily on active project context. |
| **Evaluation Datasets & Benchmarks** | `/v1/evaluations/*`, `backend/forge/routers/evaluations.py` | REVIEW | **DEFER** | Used to benchmark prompt quality and agent reasoning across LLMs. While built for SaaS enterprise testing, home butler optimization can benefit from evals. Defer until agent stabilization. |
| **Commercial Usage & Billing / Budgets** | `/v1/budgets/*`, `backend/forge/routers/budgets.py` | REVIEW | **KEEP (Rebrand)** | Local-first butler needs token budget tracking to prevent runaway API spend across local/cloud LLMs. Keep budget controls; remove enterprise multi-seat billing references. |
| **Audit Logs & Enterprise Compliance** | `/v1/audit-logs/*`, `backend/forge/routers/audit_logs.py` | REVIEW | **KEEP (Local)** | Essential for butler observability—debugging tool execution, tracking home device commands, and diagnosing failures locally. |

---

## Validation & Verification

### 1. Frontend Typecheck
- Executed `npx.cmd tsc --noEmit` from `frontend/`.
- Result: **0 errors (exited 0)**.

### 2. Backend Automated Tests
- Executed Pytest suite using isolated test database:
  - `backend/tests/test_platform_hardening.py`
  - `backend/tests/test_service_token_egress.py`
  - `backend/tests/test_project_run_endpoint.py`
  - `backend/tests/test_security_hardening.py`
- Result: **47 passed in 14.18s (0 failures, 0 warnings)**.

### 3. Route Verification
- FastAPI route extraction confirms active route count dropped from 198 to **187**.
- Verified zero occurrences of `/v1/embed` or `/v1/api-keys` in OpenAPI schema / route registry.
