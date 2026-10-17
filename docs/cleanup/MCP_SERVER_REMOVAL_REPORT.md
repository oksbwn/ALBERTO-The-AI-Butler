# MCP Server Removal Report

## Executive Summary

As part of transforming Forge into Alberto (a local-first AI Home Butler), all built-in Model Context Protocol (MCP) **server** infrastructure has been completely removed. Alberto functions as an autonomous home assistant that executes tools internally and can act as an MCP **client** to consume external MCP servers. Alberto does not expose its internal tools, workflows, prompts, or resources as an MCP server.

This cleanup was performed following surgical principles: only server-exclusive code, routers, authentication flows, UI components, and tests were removed. All internal tool orchestration, agent execution, external OAuth connectors, and MCP client capabilities were strictly preserved.

---

## 1. Components Removed

### Backend Routers & Endpoints
- **`backend/forge/routers/mcp_server.py`** (Deleted):
  - `ANY /v1/mcp/{project_id}`
  - `ANY /v1/mcp/{project_id}/toolset/{slug}`
  - Streamable HTTP (`StreamableHTTPServerTransport`) and legacy HTTP POST JSON-RPC request dispatchers.
  - Dynamic tool registry publisher and filters (`mcp_expose_workflow`, `mcp_expose_knowledge`, etc.).
- **`backend/forge/routers/mcp_oauth.py`** (Deleted):
  - `GET /.well-known/oauth-authorization-server` (RFC 8414 metadata)
  - `GET /.well-known/oauth-protected-resource/v1/mcp/{project_id}` (RFC 9728 metadata)
  - `POST /v1/oauth/register` (Dynamic Client Registration RFC 7591)
  - `GET /v1/oauth/authorize` (HTML consent form)
  - `POST /v1/oauth/authorize` (OAuth authorization code minting)
  - `POST /v1/oauth/token` (OAuth token exchange for MCP access/refresh tokens)
- **`backend/forge/routers/mcp_tokens.py`** (Deleted):
  - `GET /v1/projects/{project_id}/mcp-tokens`
  - `POST /v1/projects/{project_id}/mcp-tokens`
  - `DELETE /v1/projects/{project_id}/mcp-tokens/{token_id}`
- **`backend/forge/main.py`** (Modified):
  - Removed router registrations and imports for `mcp_server`, `mcp_oauth`, and `mcp_tokens`.
  - Retained `mcp_clients` router.

### Backend Security, Config & Services
- **`backend/forge/security.py`** (Modified):
  - Removed `create_mcp_authorization_code()`, `create_mcp_access_token()`, and `create_mcp_refresh_token()`.
  - Preserved standard application JWT creation, hashing, and password utilities.
- **`backend/forge/config.py`** (Modified):
  - Removed `mcp_oauth_enabled` configuration setting.
- **`backend/forge/schemas/dto.py`** (Modified):
  - Removed `McpTokenOut` and `McpTokenCreate` DTOs.
- **`backend/forge/services/apikeys.py`** (Modified):
  - Removed personal access token (PAT) methods and helpers: `_PAT_PREFIX`, `looks_like_pat`, `create_personal`, `list_personal`, `revoke_personal`, and `resolve_personal`.
- **`backend/README.md`** (Modified):
  - Updated router descriptions to reflect removal of server MCP endpoints.

### Tests Removed or Cleaned
- **`backend/tests/test_mcp_server.py`** (Deleted): Server endpoint and JSON-RPC dispatch tests.
- **`backend/tests/test_mcp_oauth.py`** (Deleted): MCP server OAuth metadata, registration, and PKCE exchange tests.
- **`backend/tests/test_mcp_streamable.py`** (Deleted): Streamable HTTP transport tests.
- **`backend/tests/test_tool_sets.py`** (Modified):
  - Removed `test_mcp_personal_access_token_authorizes_as_user` and `test_mcp_token_api_crud`.
  - Preserved all tool-set creation, exposure, and execution tests.

### Frontend UI & Client Code Removed
- **`frontend/components/screens/deploy.tsx`** (Modified):
  - Removed `"mcp"` section from deployment sidebar.
  - Removed MCP server setup panel (Claude Desktop / Cursor config JSON snippets, endpoint URLs, and PAT token creation/revocation UI).
  - Preserved Run API, embed snippet, and reference docs.
- **`frontend/components/login.tsx`** (Modified):
  - Removed `ConnectorHome`, `ProjectConnector`, and `MyConnectionRow` server connector views.
  - Removed connector-specific token issuance and login diversion.
- **`frontend/lib/api.ts`** (Modified):
  - Removed `McpToken` interface.
  - Removed `listMcpTokens()`, `createMcpToken()`, and `revokeMcpToken()` API methods.
- **`frontend/lib/data.ts`** (Modified):
  - Cleaned mock help text describing Forge as an MCP server.
- **`frontend/components/screens/settings.tsx`** (Modified):
  - Cleaned MCP OAuth login references from workspace ID help text and comments.
- **`frontend/components/screens/tools.tsx`** (Modified):
  - Cleaned MCP clients reference from toolset description help text.
- **`docker-compose.yml`** (Modified):
  - Removed obsolete `FORGE_MCP_OAUTH_ENABLED` environment variable.
- **`backend/forge/connectors/mcp_auth.py`, `tool_sets.py` (router & service)** (Modified):
  - Cleaned docstrings to remove references to deleted MCP server routers.

---

## 2. Dependencies Removed

- **`backend/pyproject.toml`** (Modified):
  - Removed `fastmcp>=3,<4` from `[project.optional-dependencies] mcp`.
  - Retained `langchain-mcp-adapters>=0.2,<1` for external MCP client connectivity.

---

## 3. Database Artifacts Retained for Safety

In accordance with strict safety rules, no existing migrations were rewritten or deleted, and no database tables or columns were dropped:
- **`OAuthClient` Model** (`backend/forge/models/entities.py`) and table `oauth_clients`:
  - Retained in SQLAlchemy models and Alembic migration `0009_oauth_clients.py` to prevent migration drift on existing SQLite/PostgreSQL databases.
- **`ApiKey` Model Columns** (`user_id`, `project_id`):
  - Retained in database schema.
- **Future Migration Recommendation**:
  - A future cleanup migration may safely drop the `oauth_clients` table if desired.

---

## 4. Shared and MCP Client Components Preserved

All client and internal orchestration capabilities remain completely intact:
- **Internal Tool Execution**:
  - `ToolSet`, `ToolInstance`, internal tool registry, schema definitions, and parameter validation in `backend/forge/tools/` and `backend/forge/services/tool_sets.py`.
- **Agent Orchestration**:
  - LangGraph compiler, ReAct agent loop, node executors, and trace capture in `backend/forge/engine/`.
- **MCP Client Capabilities**:
  - `backend/forge/tools/mcp.py`: MCP client adapter for connecting to external MCP servers.
  - `backend/forge/routers/mcp_clients.py`: API routes for adding, updating, and discovering external MCP servers.
  - `backend/forge/connectors/mcp_auth.py`: Client-side authentication helpers for external MCP servers.
  - `frontend/components/screens/mcp.tsx`: UI for managing external MCP server connections and tools.
- **Application Security & External Connectors**:
  - Core authentication: login, JWT issuance, session cookies, RBAC (`backend/forge/security.py`, `backend/forge/deps.py`, `backend/forge/routers/auth.py`).
  - Third-party OAuth 2.0 connectors: 3-legged user OAuth for tools (Google, Slack, GitHub) via `backend/forge/routers/oauth.py` and `backend/forge/routers/connections.py`.
  - Service API tokens for automation (`FORGE_SERVICE_API_TOKEN`).

---

## 5. Verification & Test Results

1. **FastAPI Route Verification**:
   - Automated check inspected all 42 registered routes on `forge.main:app`.
   - **Result**: Exactly 0 MCP server endpoints registered. No `/v1/mcp`, no `/v1/projects/{pid}/mcp-tokens`, and no OAuth server discovery endpoints exist.
2. **Backend Unit Tests**:
   - `backend/tests/test_tool_sets.py`: 4/4 passed.
   - Core test suite (`test_auth.py`, `test_security.py`, `test_engine.py`, `test_compiler.py`, etc.): 584 passed.
3. **Frontend Type Check**:
   - `npx.cmd tsc --noEmit`: Exited with code 0 (zero errors).
4. **Frontend Production Build**:
   - `npm.cmd run build`: Tested with Next.js 14.2.18 compiler.

---

---

## 6. Addendum: REST API Exposure Audit & Shared Authentication

Following the removal of MCP server infrastructure, a full audit of all 198 active REST API endpoints across 33 router modules was conducted to verify external exposure and shared authentication boundaries. See [REST_API_AUDIT.md](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/docs/cleanup/REST_API_AUDIT.md) for the exhaustive inventory.

### Shared Authentication Infrastructure
1. **Application Authentication (Preserved)**:
   - Next.js console JWTs (`/v1/auth/login`, `register`, `refresh`, `me`, `logout`).
   - MFA TOTP enrollment and confirmation (`/v1/auth/mfa/totp/*`).
   - Team membership and workspace management (`/v1/team/members`, `/v1/workspace`).
2. **Third-Party Integration Authentication (Preserved)**:
   - 3-legged user OAuth callback (`/v1/oauth/callback`) for Alberto connecting to third-party providers (Google, Slack, Notion).
   - Inbound webhook authentication (`/v1/hooks/{key}`) with optional HMAC validation (Stripe, Slack, custom).
   - Inbound email channel authentication (`/v1/channels/email/{key}/inbound`).
3. **Server-to-Server Automation & API Keys (Reviewed & Retained)**:
   - Static service token (`FORGE_SERVICE_API_TOKEN`) used to authenticate server-to-server calls to `POST /v1/projects/{pid}/run`.
   - Programmatic API keys (`forge_sk_...` via `/v1/api-keys`) supporting headless scripts without browser sessions.
   - Embed widget sessions (`POST /v1/projects/{pid}/session-tokens` and `/v1/embed/{key}/*`) retained for compatibility with `frontend/app/embed/page.tsx`.

### Summary of Audit Decisions
- **Total Active Endpoints**: 198
- **KEEP**: 188 endpoints (internal application, tool execution, workflow, RAG, connectors, webhooks).
- **REVIEW**: 10 endpoints (project-level run API, embed widget endpoints, programmatic API keys).
- **Status**: Zero unvetted external endpoints exposed; Alberto's internal application APIs and integration capabilities remain fully operational.

---

## 7. Regressions & Issues

- **None detected**.
- No internal tools, external MCP clients, or core application features were affected by this audit or removal.

