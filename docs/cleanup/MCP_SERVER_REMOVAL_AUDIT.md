# MCP Server Removal Audit

## Executive Summary

As part of transforming Forge into Alberto (a local-first AI Home Butler), this audit details all Model Context Protocol (MCP) functionality across the repository. Alberto functions as an AI assistant that consumes tools internally and may act as an MCP **client** to external servers. It does not need to expose its own internal tools, resources, workflows, or prompts as an MCP **server**.

This audit classifies all components into:
1. **MCP Server-Exclusive** (Candidates for removal)
2. **MCP Client** (Must be retained)
3. **Shared Internal Functionality** (Must be retained)
4. **Uncertain Dependencies / Database Artifacts** (Retained and reported)

---

## 1. Classification of Components

### Category 1: MCP Server-Exclusive (Candidates for Removal)

These components exist solely to host, authenticate, configure, or expose Alberto as an MCP server to external clients (e.g., Claude Desktop, Cursor, VS Code):

#### Backend Routes & Transports
- **`backend/forge/routers/mcp_server.py`**:
  - `ANY /v1/mcp/{project_id}`: Base endpoint exposing project tools as an MCP server.
  - `ANY /v1/mcp/{project_id}/toolset/{slug}`: Per-toolset scoped MCP endpoint.
  - Handlers:
    - Streamable HTTP transport (`StreamableHTTPServerTransport` from `mcp` SDK) for JSON and SSE streaming (`text/event-stream`).
    - Legacy HTTP POST JSON-RPC handler (`initialize`, `tools/list`, `tools/call`).
    - Project tools publisher (`mcp_expose_workflow`, `mcp_expose_knowledge`, `mcp_expose_faq`).
    - Tool filtering and flattening (`mcp_excluded_tools`, `toolset.exposed`).
- **`backend/forge/routers/mcp_oauth.py`**:
  - `GET /.well-known/oauth-authorization-server`: Authorization server metadata (RFC 8414).
  - `GET /.well-known/oauth-protected-resource/v1/mcp/{project_id}`: Protected resource metadata (RFC 9728).
  - `POST /v1/oauth/register`: Dynamic client registration (RFC 7591) for external MCP clients.
  - `GET /v1/oauth/authorize`: Server-rendered HTML consent login screen.
  - `POST /v1/oauth/authorize`: Authorization code issuance with PKCE validation.
  - `POST /v1/oauth/token`: Token exchange endpoint for access and refresh tokens.
- **`backend/forge/routers/mcp_tokens.py`**:
  - `GET /v1/projects/{project_id}/mcp-tokens`: List personal access tokens (PATs).
  - `POST /v1/projects/{project_id}/mcp-tokens`: Mint per-user PAT (`forge_pat_...`) scoped to project MCP server.
  - `DELETE /v1/projects/{project_id}/mcp-tokens/{token_id}`: Revoke PAT.

#### Backend Security & Config
- **`backend/forge/security.py`**:
  - `create_mcp_authorization_code()`: Minting OAuth 2.1 code for MCP authorization server.
  - `create_mcp_access_token()`: Minting audience-bound access token for MCP server.
  - `create_mcp_refresh_token()`: Minting refresh token for MCP server.
- **`backend/forge/config.py`**:
  - `mcp_oauth_enabled`: Setting gating the MCP server OAuth authorization server.
- **`backend/forge/schemas/dto.py`**:
  - `McpTokenOut`: DTO for PAT responses.
  - `McpTokenCreate`: DTO for PAT creation requests.

#### Backend Tests
- **`backend/tests/test_mcp_server.py`**: Tests for `/v1/mcp/{project_id}` endpoints and JSON-RPC dispatch.
- **`backend/tests/test_mcp_oauth.py`**: Tests for MCP server OAuth metadata, registration, and PKCE.
- **`backend/tests/test_mcp_streamable.py`**: Tests for Streamable HTTP transport of MCP server.
- **`backend/tests/test_tool_sets.py` (partial)**: Tests `test_mcp_personal_access_token_authorizes_as_user` and `test_mcp_token_api_crud` that hit `/v1/mcp/{pid}` and `/v1/projects/{pid}/mcp-tokens`.

#### Frontend UI & Clients
- **`frontend/components/screens/deploy.tsx`**:
  - `CONN_SECTIONS` item `"mcp"`: "MCP server" navigation entry.
  - `section === "mcp"` panel:
    - MCP server guide and documentation.
    - Server endpoint URL display (`/v1/mcp/{project_id}`).
    - API key generation and configuration (`mcp_api_key`).
    - PAT token management table and creation (`api.listMcpTokens`, `api.createMcpToken`, `api.revokeMcpToken`).
    - Claude Desktop / Cursor configuration generation block.
    - Project tools MCP toggles (`mcp_expose_workflow`, `mcp_expose_knowledge`, `mcp_expose_faq`).
    - Toolset exposure checkboxes (`ts.exposed`, `mcp_excluded_tools`).
    - Currently exposed tools summary.
- **`frontend/components/login.tsx`**:
  - `ConnectorHome` and `ProjectConnector`: Minimal console for `me?.role === "connector"` that existed exclusively to display the project's MCP server endpoint and generate PATs.
- **`frontend/lib/api.ts`**:
  - `listMcpTokens`
  - `createMcpToken`
  - `revokeMcpToken`
  - Interface `McpToken`

---

### Category 2: MCP Client (Retain)

These components allow Alberto to connect to and consume tools from external MCP servers (e.g., GitHub, Slack, Notion, Postgres, filesystem). They must be preserved in full:

- **`backend/forge/tools/mcp.py`**:
  - Core MCP client implementation.
  - `_CLIENT_CACHE`: Connection pool for `MultiServerMCPClient`.
  - `_ProviderAuth`: Per-request authentication attachment using Alberto's AuthProviders.
  - `discover_tools()`: Introspecting external MCP servers for available tools.
  - `server_tools()`: Loading external tools to bind to LangGraph agents.
  - `load_mcp_tool()`: Runtime assembler for `kind="mcp"` tools.
  - `describe_mcp_error()`: Error formatting for external MCP connections.
  - `close_all()`: Graceful shutdown of external MCP client connections.
- **`backend/forge/routers/mcp_clients.py`**:
  - CRUD API for external MCP client configurations:
    - `GET /v1/projects/{project_id}/mcp-clients`
    - `POST /v1/projects/{project_id}/mcp-clients`
    - `PATCH /v1/projects/{project_id}/mcp-clients/{client_id}`
    - `DELETE /v1/projects/{project_id}/mcp-clients/{client_id}`
    - `GET /v1/projects/{project_id}/mcp-clients/{client_id}/tools`: Triggers `discover_tools()`.
- **`backend/forge/models/entities.py` (`McpClient`)**:
  - Table `mcp_clients`: Stores external server configurations (name, URL, transport, command, args, headers_ref, auth_provider_id, disabled_tools).
- **`backend/forge/connectors/mcp_auth.py`**:
  - Client-side OAuth discovery (RFC 9728, RFC 8414, RFC 7591) for connecting to third-party MCP servers (e.g. `mcp.slack.com`, Notion, Linear).
- **`backend/forge/connectors/catalog/`**:
  - Connector definitions with `"type": "mcp"` (Slack, Notion, Linear, Atlassian).
- **`backend/forge/connectors/manifest.py` & `install.py`**:
  - `McpBackend`: Parsing and installing MCP-backed connectors.
- **`backend/forge/config.py`**:
  - `enable_mcp_stdio`, `mcp_stdio_allowed_commands`: Security controls for local stdio MCP client connections.
- **`frontend/components/screens/mcp.tsx`**:
  - `McpClientsScreen`: The "External MCP" UI for managing external MCP server connections, discovering their tools, and toggling them on/off.
- **`frontend/lib/api.ts`**:
  - `listMcpClients`, `createMcpClient`, `updateMcpClient`, `deleteMcpClient`, `discoverMcpTools`, `McpClientT`.
- **`backend/tests/test_mcp.py` & `backend/tests/test_mcp_auth.py`**:
  - Test suites for MCP client execution and authentication.

---

### Category 3: Shared Internal Functionality (Retain)

These components are part of Alberto's core tool execution, agent orchestration, and general authentication:

- **Internal Tool Architecture**:
  - `backend/forge/tools/materialize.py`: Dispatches all tool kinds (`rest_api`, `graphql`, `sql`, `code`, `builtin`, `mcp`).
  - `backend/forge/tools/builtin.py`: Built-in tools (`calculator`, `web_fetch`, `knowledge_search`, etc.).
  - `backend/forge/services/tool_sets.py` & `backend/forge/routers/tool_sets.py`: ToolSet organization for agent tool assignment.
- **Application Authentication**:
  - `backend/forge/routers/auth.py`: User registration, login, JWT issuance, password reset, MFA.
  - `backend/forge/routers/oauth.py`: OAuth callback (`/v1/oauth/callback`) for external integrations.
  - `backend/forge/routers/connections.py`: Per-user downstream credentials (`/v1/projects/{project_id}/connections`).
  - `backend/forge/services/apikeys.py`: Service API keys and workspace keys.
- **Agent Orchestration**:
  - `backend/forge/services/runtime.py`: Compiles tools, agents, and subagents for LangGraph execution.
  - `backend/forge/services/runs.py`: Run lifecycle and streaming execution.

---

### Category 4: Uncertain Dependencies & Database Artifacts (Retained & Safe)

Per the strict rules of the project:
1. **Migrations**:
   - `backend/migrations/versions/0009_oauth_clients.py`: Creates `oauth_clients` table. Must be retained so existing database migration history remains intact.
   - `backend/migrations/versions/0010_toolset_exposed.py`: Adds `exposed` column to `tool_sets`. Retained intact.
   - `backend/migrations/versions/0008_apikey_user_scope.py`: Adds `user_id` and `project_id` to `api_keys`. Retained intact.
2. **Database Models**:
   - `OAuthClient` in `backend/forge/models/entities.py`: Retained as an ORM class to match historical schema and avoid ORM reflection discrepancies. All application-level routes and queries referencing it are removed.
   - `ApiKey.user_id` and `ApiKey.project_id`: Columns in `entities.py` retained.
3. **Dependencies in `pyproject.toml`**:
   - `fastmcp>=3,<4`: Server-exclusive framework, not used anywhere in the repository. Removed.
   - `mcp>=1.9`: Official SDK used by the server transport. Can be removed from top-level `mcp` extra or replaced with `langchain-mcp-adapters>=0.2,<1` (which manages its own client requirements).

---

## 2. Authentication Boundary Summary

| Authentication Surface | Role | Action | Rationale |
| :--- | :--- | :--- | :--- |
| `/.well-known/oauth-authorization-server` | MCP Server OAuth Discovery | **Remove** | Only needed when external clients authenticate to Alberto's MCP server. |
| `/.well-known/oauth-protected-resource/*` | MCP Server Protected Resource Metadata | **Remove** | Specific to RFC 9728 for external MCP clients calling Alberto. |
| `/v1/oauth/register` | Dynamic Client Registration (RFC 7591) | **Remove** | Exclusively registers external MCP clients. |
| `/v1/oauth/authorize` | Server OAuth Consent & Code Issuance | **Remove** | Only used for external clients accessing Alberto via MCP. |
| `/v1/oauth/token` | Server OAuth Token Exchange | **Remove** | Only exchanges codes/refresh tokens for Alberto MCP access. |
| `/v1/projects/{pid}/mcp-tokens` | MCP Server PAT Minting & Revocation | **Remove** | PATs existed only to authenticate to `/v1/mcp/{pid}`. |
| `/v1/oauth/callback` | External 3-Legged OAuth Callback | **Preserve** | Used by Alberto to connect to third-party services (Google, Slack, Notion). |
| `/v1/projects/{pid}/connections` | Per-user External Credentials | **Preserve** | Stores user tokens for downstream tools. |
| `/v1/auth/*` | Main User Authentication | **Preserve** | Core user login, session management, and JWTs. |
| Service API Tokens (`FORGE_SERVICE_API_TOKEN`) | Server-to-Server Backend Auth | **Preserve** | Secures `/v1/projects/{pid}/run` for host backend. |

---

## 3. Removal Execution Plan

1. **Backend Removal**:
   - Delete router `backend/forge/routers/mcp_server.py`.
   - Delete router `backend/forge/routers/mcp_oauth.py`.
   - Delete router `backend/forge/routers/mcp_tokens.py`.
   - Unregister these three routers from `backend/forge/main.py`.
   - Remove `mcp_oauth_enabled` from `backend/forge/config.py`.
   - Remove unused MCP token helper functions (`create_mcp_authorization_code`, `create_mcp_access_token`, `create_mcp_refresh_token`) from `backend/forge/security.py`.
   - Remove `McpTokenCreate` and `McpTokenOut` DTOs from `backend/forge/schemas/dto.py`.
   - Delete MCP server-exclusive test files:
     - `backend/tests/test_mcp_server.py`
     - `backend/tests/test_mcp_oauth.py`
     - `backend/tests/test_mcp_streamable.py`
   - Clean up MCP server tests from `backend/tests/test_tool_sets.py`.
2. **Frontend Removal**:
   - In `frontend/components/screens/deploy.tsx`, remove the `"mcp"` section from `CONN_SECTIONS` and delete the `section === "mcp"` UI panel, removing unused state/handlers (`mcpTokens`, `apiKey`, `exposeWf`, etc.).
   - In `frontend/components/login.tsx`, simplify `ConnectorHome` to standard user home or remove MCP-server specific text and PAT generation.
   - In `frontend/lib/api.ts`, remove `listMcpTokens`, `createMcpToken`, `revokeMcpToken`, and `McpToken`.
   - In `frontend/lib/data.ts`, update any mock descriptions mentioning MCP server.
3. **Dependency Cleanup**:
   - In `backend/pyproject.toml`, clean up `[project.optional-dependencies] mcp`: remove `fastmcp>=3,<4` and retain client dependency `langchain-mcp-adapters>=0.2,<1`.
4. **Verification**:
   - Run pytest suite with python in `.venv`. (PASSED)
   - Run Next.js build / lint checks. (PASSED)
   - Verify server startup and route registration. (PASSED: 0 MCP server endpoints registered)

---

## 4. Execution Status

**Status: COMPLETED**

All removal actions outlined above have been executed surgically. Full removal details, verification results, preserved client/shared components, and regression assessment are documented in [MCP_SERVER_REMOVAL_REPORT.md](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/docs/cleanup/MCP_SERVER_REMOVAL_REPORT.md).
