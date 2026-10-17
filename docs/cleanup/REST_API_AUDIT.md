# REST API Exposure Audit & Inventory

## Executive Summary

This document provides the definitive REST API inventory and exposure audit for **Alberto**, our local-first AI Home Butler. It tracks the transformation from the legacy multi-tenant SaaS Forge platform to Alberto's streamlined architecture.

### Audit Metrics (Phase 2 Post-Cleanup)

- **Total Active Unique Endpoints**: 187
- **CORE Endpoints**: 159 (Application UI, tools, workflows, knowledge, agents, health)
- **INTEGRATION Endpoints**: 28 (Connectors, OAuth callbacks, inbound webhooks, local Run API)
- **Total Endpoints Removed in Phase 2**: 11 (8 embed widget endpoints, 3 external API key endpoints)
- **Total Endpoints Removed in Phase 1 (MCP)**: 11 (MCP server JSON-RPC, OAuth server, PAT tokens)
- **Active FastAPI Router Modules**: 31

---

## 1. Classification Guidelines

- **CORE**: Required for internal Next.js communication, agent orchestration, tool execution, workflow management, RAG/knowledge systems, and background maintenance.
- **INTEGRATION**: Required for external device and third-party connectivity (inbound webhooks, 3-legged OAuth callbacks, Home Assistant / automation Run API).
- **LEGACY**: Forge-specific SaaS features that have been decommissioned and removed.
- **REVIEW / DEFER**: Multi-tenant SaaS features flagged for Phase 3 evaluation (eval datasets, multi-user invitations, pricing models).

---

## 2. Removed Endpoints Inventory

### A. Phase 2 Removed Endpoints (Public Embedding & API Key Issuance)

| HTTP Method | Path | Function | Router Module | Classification | Reason for Removal |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/embed/{key}/config` | `embed_config` | `forge.routers.embed_public` | **LEGACY** | Public embedding widget decommissioned. |
| `GET` | `/v1/embed/{key}/components` | `embed_components` | `forge.routers.embed_public` | **LEGACY** | Public embedding widget decommissioned. |
| `POST` | `/v1/embed/{key}/runs` | `embed_create_run` | `forge.routers.embed_public` | **LEGACY** | Public embedding widget decommissioned. |
| `GET` | `/v1/embed/{key}/runs/{run_id}/stream` | `embed_stream` | `forge.routers.embed_public` | **LEGACY** | Public embedding widget decommissioned. |
| `POST` | `/v1/embed/{key}/runs/{run_id}/resume` | `embed_resume` | `forge.routers.embed_public` | **LEGACY** | Public embedding widget decommissioned. |
| `POST` | `/v1/projects/{project_id}/session-tokens` | `mint_session_token` | `forge.routers.embed` | **LEGACY** | Server-to-server embed token minting decommissioned. |
| `GET` | `/v1/projects/{project_id}/embed` | `get_embed` | `forge.routers.embed` | **LEGACY** | Embed configuration settings decommissioned. |
| `PUT` | `/v1/projects/{project_id}/embed` | `set_embed` | `forge.routers.embed` | **LEGACY** | Embed configuration settings decommissioned. |
| `GET` | `/v1/api-keys` | `list_api_keys` | `forge.routers.auth.apikeys_router` | **LEGACY** | Developer API key issuance removed; unused by Alberto. |
| `POST` | `/v1/api-keys` | `create_api_key` | `forge.routers.auth.apikeys_router` | **LEGACY** | Developer API key issuance removed; unused by Alberto. |
| `DELETE` | `/v1/api-keys/{key_id}` | `revoke_api_key` | `forge.routers.auth.apikeys_router` | **LEGACY** | Developer API key issuance removed; unused by Alberto. |

### B. Phase 1 Removed Endpoints (MCP Server Infrastructure)

| HTTP Method | Path | Function | Router Module | Classification | Reason for Removal |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `ANY` | `/v1/mcp/{project_id}` | `mcp_dispatch` | `forge.routers.mcp_server` | **LEGACY** | Alberto consumes external MCP servers as client, does not act as server. |
| `ANY` | `/v1/mcp/{project_id}/toolset/{slug}` | `mcp_toolset` | `forge.routers.mcp_server` | **LEGACY** | Exposing toolsets over MCP server transport removed. |
| `GET` | `/.well-known/oauth-authorization-server` | `oauth_metadata` | `forge.routers.mcp_oauth` | **LEGACY** | RFC 8414 metadata for external MCP clients removed. |
| `GET` | `/.well-known/oauth-protected-resource/*` | `protected_resource` | `forge.routers.mcp_oauth` | **LEGACY** | RFC 9728 metadata for external MCP clients removed. |
| `POST` | `/v1/oauth/register` | `oauth_register` | `forge.routers.mcp_oauth` | **LEGACY** | Dynamic Client Registration (RFC 7591) for MCP removed. |
| `GET` | `/v1/oauth/authorize` | `oauth_authorize_page` | `forge.routers.mcp_oauth` | **LEGACY** | Consent UI for external MCP clients removed. |
| `POST` | `/v1/oauth/authorize` | `oauth_authorize` | `forge.routers.mcp_oauth` | **LEGACY** | Code minting for external MCP clients removed. |
| `POST` | `/v1/oauth/token` | `oauth_token` | `forge.routers.mcp_oauth` | **LEGACY** | Token exchange for external MCP clients removed. |
| `GET` | `/v1/projects/{pid}/mcp-tokens` | `list_mcp_tokens` | `forge.routers.mcp_tokens` | **LEGACY** | PAT minting for MCP server removed. |
| `POST` | `/v1/projects/{pid}/mcp-tokens` | `create_mcp_token` | `forge.routers.mcp_tokens` | **LEGACY** | PAT minting for MCP server removed. |
| `DELETE` | `/v1/projects/{pid}/mcp-tokens/{token_id}` | `revoke_mcp_token` | `forge.routers.mcp_tokens` | **LEGACY** | PAT revocation for MCP server removed. |

---

## 3. Preserved External Automation & Integration Surfaces

### A. Local Automation Run API (`POST /v1/projects/{project_id}/run`)

- **Router**: `forge.routers.project_run`
- **Classification**: **INTEGRATION** (Preserved)
- **Purpose**: Single project-level execution endpoint that executes the configured workflow. Used by local automation scripts, Home Assistant routines, and terminal curl calls.
- **Auth**: Bearer token via `FORGE_SERVICE_API_TOKEN` static secret or user JWT.
- **UI Documentation**: Documented in `frontend/components/screens/deploy.tsx` under Connect & API screen with sanitized Alberto branding.

### B. Inbound Webhooks (`POST /v1/hooks/{key}`)

- **Router**: `forge.routers.hooks`
- **Classification**: **INTEGRATION** (Preserved)
- **Purpose**: Ingests external HTTP events (GitHub, Slack, Stripe, IoT devices) with secret path key and HMAC signature verification.
- **UI Documentation**: Documented in `frontend/components/screens/platform.tsx` (`TriggersScreen`).

### C. Email Channel Inbound (`POST /v1/channels/email/{key}/inbound`)

- **Router**: `forge.routers.channels.public`
- **Classification**: **INTEGRATION** (Preserved)
- **Purpose**: Receives parsed emails from transactional email providers (SendGrid, Postmark) to drive conversational workflows.

### D. Third-Party OAuth Callback (`GET /v1/oauth/callback`)

- **Router**: `forge.routers.oauth`
- **Classification**: **INTEGRATION** (Preserved)
- **Purpose**: 3-legged user OAuth callback for Alberto connecting to third-party services (Google Calendar/Gmail, Notion, Slack, GitHub).

---

## 4. Complete Inventory of Active Endpoints (187 Endpoints)

### Module: `forge.routers.agents` (8 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/agents` | `list_agents` | Session JWT (User) | **CORE** | List agents endpoint |
| `POST` | `/v1/projects/{project_id}/agents` | `create_agent` | Session JWT (Editor/User) | **CORE** | Create agent endpoint |
| `POST` | `/v1/projects/{project_id}/agents/export` | `export_agents` | Session JWT (User) | **CORE** | Serialize the selected agent presets (full config) into a downloadable bundle. |
| `POST` | `/v1/projects/{project_id}/agents/import` | `import_agents` | Session JWT (Editor/User) | **CORE** | Create agent presets from an uploaded bundle in THIS project (auto-renamed on collision). |
| `POST` | `/v1/projects/{project_id}/agents/validate` | `validate_agent` | Session JWT (User) | **CORE** | Validate agent endpoint |
| `DELETE` | `/v1/projects/{project_id}/agents/{agent_id}` | `delete_agent` | Session JWT (User) | **CORE** | Delete agent endpoint |
| `GET` | `/v1/projects/{project_id}/agents/{agent_id}` | `get_agent` | Session JWT (User) | **CORE** | Get agent endpoint |
| `PATCH` | `/v1/projects/{project_id}/agents/{agent_id}` | `update_agent` | Session JWT (Editor/User) | **CORE** | Update agent endpoint |

### Module: `forge.routers.assistant` (2 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `POST` | `/v1/projects/{project_id}/assistant/resume` | `assistant_resume` | Session JWT (User) | **CORE** | Resume a paused assistant thread (HITL approval for destructive tools). |
| `POST` | `/v1/projects/{project_id}/assistant/stream` | `assistant_stream` | Session JWT (User) | **CORE** | Assistant stream endpoint |

### Module: `forge.routers.audit` (3 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/audit` | `list_audit` | Session JWT (User) | **CORE** | Filtered, keyset-paginated audit list (newest first). Returns a JSON array (unchanged |
| `GET` | `/v1/audit/export` | `export_audit` | Session JWT (User) | **CORE** | Stream ALL matching audit rows as newline-delimited JSON (oldest first), paged internally |
| `GET` | `/v1/audit/metrics` | `metrics` | Session JWT (User) | **CORE** | In-process resilience counters (swallowed-failure visibility). |

### Module: `forge.routers.auth` (23 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `POST` | `/v1/auth/accept-invite` | `accept_invite` | Credentials / Refresh Token (Public Auth) | **CORE** | Public: redeem an invite token, set the first password, and log the user in. |
| `GET` | `/v1/auth/invite-info` | `invite_info` | Session JWT (User) | **CORE** | Public: validate an invite token and return who it's for (for the accept screen). |
| `POST` | `/v1/auth/login` | `login` | Credentials / Refresh Token (Public Auth) | **CORE** | Login endpoint |
| `POST` | `/v1/auth/logout` | `logout` | Session JWT (User) | **CORE** | Revoke the presented refresh token (this device/session). Unauthenticated: possession of |
| `POST` | `/v1/auth/logout-all` | `logout_all` | Session JWT (Editor/User) | **CORE** | Sign out every session for the current user (all devices) by advancing their revocation |
| `GET` | `/v1/auth/me` | `me` | Session JWT (Editor/User) | **CORE** | Me endpoint |
| `POST` | `/v1/auth/mfa/totp/confirm` | `totp_confirm` | Session JWT (Editor/User) | **CORE** | Totp confirm endpoint |
| `POST` | `/v1/auth/mfa/totp/disable` | `totp_disable` | Session JWT (Editor/User) | **CORE** | Disable MFA. Requires a current code so a hijacked session can't silently turn it off. |
| `POST` | `/v1/auth/mfa/totp/enroll` | `totp_enroll` | Session JWT (Editor/User) | **CORE** | Generate a TOTP secret (NOT yet active - confirm a code to enable). Returns the secret |
| `POST` | `/v1/auth/refresh` | `refresh` | Credentials / Refresh Token (Public Auth) | **CORE** | Refresh endpoint |
| `POST` | `/v1/auth/register` | `register` | Credentials / Refresh Token (Public Auth) | **CORE** | Register endpoint |
| `POST` | `/v1/auth/request-email-verification` | `request_email_verification` | Session JWT (Editor/User) | **CORE** | Request email verification endpoint |
| `POST` | `/v1/auth/request-password-reset` | `request_password_reset` | Credentials / Refresh Token (Public Auth) | **CORE** | Public: email a signed reset link. Always returns ok (never reveals whether the address |
| `POST` | `/v1/auth/reset-password` | `reset_password` | Credentials / Refresh Token (Public Auth) | **CORE** | Public: redeem a reset token, set a new password, and sign out all existing sessions. |
| `POST` | `/v1/auth/set-password` | `set_my_password` | Session JWT (Editor/User) | **CORE** | Set my password endpoint |
| `POST` | `/v1/auth/verify-email` | `verify_email` | Credentials / Refresh Token (Public Auth) | **CORE** | Verify email endpoint |
| `GET` | `/v1/team/members` | `list_members` | Session JWT (User) | **CORE** | List members endpoint |
| `POST` | `/v1/team/members` | `invite_member` | Session JWT (Admin) | **CORE** | Invite member endpoint |
| `DELETE` | `/v1/team/members/{user_id}` | `deactivate_member` | Session JWT (Admin) | **CORE** | Deactivate member endpoint |
| `PATCH` | `/v1/team/members/{user_id}` | `update_member` | Session JWT (Admin) | **CORE** | Update member endpoint |
| `DELETE` | `/v1/workspace` | `delete_workspace` | Session JWT (Owner) | **CORE** | Owner-only, name-confirmed, cascading workspace deletion (finding k). Irreversible. |
| `GET` | `/v1/workspace` | `get_workspace` | Session JWT (User) | **CORE** | Get workspace endpoint |
| `PATCH` | `/v1/workspace` | `update_workspace` | Session JWT (Owner) | **CORE** | Owner-only: rename, change plan, or adjust quota limits (finding k). |

### Module: `forge.routers.auth_providers` (9 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/auth-providers` | `list_aps` | Session JWT (User) | **CORE** | List aps endpoint |
| `POST` | `/v1/projects/{project_id}/auth-providers` | `create_ap` | Session JWT (Editor/User) | **CORE** | Create ap endpoint |
| `DELETE` | `/v1/projects/{project_id}/auth-providers/{ap_id}` | `delete_ap` | Session JWT (User) | **CORE** | Delete ap endpoint |
| `GET` | `/v1/projects/{project_id}/auth-providers/{ap_id}` | `get_ap` | Session JWT (User) | **CORE** | Get ap endpoint |
| `PATCH` | `/v1/projects/{project_id}/auth-providers/{ap_id}` | `update_ap` | Session JWT (Editor/User) | **CORE** | Update ap endpoint |
| `DELETE` | `/v1/projects/{project_id}/auth-providers/{ap_id}/connections/{end_user_id}` | `delete_user_connection` | Session JWT (User) | **CORE** | Delete user connection endpoint |
| `GET` | `/v1/projects/{project_id}/auth-providers/{ap_id}/connections/{end_user_id}` | `get_user_connection` | Session JWT (User) | **CORE** | Get user connection endpoint |
| `PUT` | `/v1/projects/{project_id}/auth-providers/{ap_id}/connections/{end_user_id}` | `set_user_connection` | Session JWT (User) | **CORE** | Set user connection endpoint |
| `POST` | `/v1/projects/{project_id}/auth-providers/{ap_id}/test` | `test_ap` | Session JWT (Editor/User) | **CORE** | Test ap endpoint |

### Module: `forge.routers.channels` (5 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `POST` | `/v1/channels/email/{key}/inbound` | `email_inbound` | Channel Key (Public Inbound) | **INTEGRATION** | Email inbound endpoint |
| `GET` | `/v1/projects/{project_id}/channels` | `list_channels` | Session JWT (User) | **INTEGRATION** | List channels endpoint |
| `POST` | `/v1/projects/{project_id}/channels` | `create_channel` | Session JWT (User) | **INTEGRATION** | Create channel endpoint |
| `DELETE` | `/v1/projects/{project_id}/channels/{channel_id}` | `delete_channel` | Session JWT (User) | **INTEGRATION** | Delete channel endpoint |
| `PATCH` | `/v1/projects/{project_id}/channels/{channel_id}` | `update_channel` | Session JWT (User) | **INTEGRATION** | Update channel endpoint |

### Module: `forge.routers.components` (7 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/components` | `list_components` | Session JWT (User) | **CORE** | List components endpoint |
| `POST` | `/v1/projects/{project_id}/components` | `create_component` | Session JWT (Editor/User) | **CORE** | Create component endpoint |
| `POST` | `/v1/projects/{project_id}/components/export` | `export_components` | Session JWT (User) | **CORE** | Serialize the selected components (HTML/CSS/props/actions) into a downloadable bundle. |
| `POST` | `/v1/projects/{project_id}/components/import` | `import_components` | Session JWT (Editor/User) | **CORE** | Create components from an uploaded bundle in THIS project (auto-renamed on collision). |
| `DELETE` | `/v1/projects/{project_id}/components/{component_id}` | `delete_component` | Session JWT (User) | **CORE** | Delete component endpoint |
| `GET` | `/v1/projects/{project_id}/components/{component_id}` | `get_component` | Session JWT (User) | **CORE** | Get component endpoint |
| `PATCH` | `/v1/projects/{project_id}/components/{component_id}` | `update_component` | Session JWT (Editor/User) | **CORE** | Update component endpoint |

### Module: `forge.routers.connections` (4 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/connections` | `list_my_connections` | Session JWT (Editor/User) | **CORE** | The per-user providers this project defines, each with whether the CALLER has connected it. |
| `DELETE` | `/v1/projects/{project_id}/connections/{ap_id}` | `clear_my_connection` | Session JWT (Editor/User) | **CORE** | Clear my connection endpoint |
| `GET` | `/v1/projects/{project_id}/connections/{ap_id}` | `my_connection_status` | Session JWT (Editor/User) | **CORE** | My connection status endpoint |
| `PUT` | `/v1/projects/{project_id}/connections/{ap_id}` | `set_my_connection` | Session JWT (Editor/User) | **CORE** | Set my connection endpoint |

### Module: `forge.routers.connectors` (13 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/connectors` | `list_installed` | Session JWT (Editor/User) | **INTEGRATION** | List installed endpoint |
| `GET` | `/v1/projects/{project_id}/connectors/catalog` | `list_catalog` | Session JWT (User) | **INTEGRATION** | The bundled catalog, each entry flagged with whether this project already has it. |
| `GET` | `/v1/projects/{project_id}/connectors/catalog/{slug}` | `get_catalog_entry` | Session JWT (User) | **INTEGRATION** | Get catalog entry endpoint |
| `POST` | `/v1/projects/{project_id}/connectors/custom` | `install_custom` | Session JWT (User) | **INTEGRATION** | Install a manifest the user supplied. Same validator, same install path, same rows - |
| `GET` | `/v1/projects/{project_id}/connectors/examples` | `list_examples` | Session JWT (User) | **INTEGRATION** | Ready-made manifests for services that CAN'T be one-click: an API key, a bot token or a |
| `POST` | `/v1/projects/{project_id}/connectors/validate` | `validate_manifest` | Session JWT (User) | **INTEGRATION** | Dry-run a manifest so the paste-a-manifest form can show errors before anything is |
| `DELETE` | `/v1/projects/{project_id}/connectors/{slug}` | `uninstall_connector` | Session JWT (User) | **INTEGRATION** | Uninstall connector endpoint |
| `POST` | `/v1/projects/{project_id}/connectors/{slug}/connect` | `connect_connector` | Session JWT (Editor/User) | **INTEGRATION** | Begin the OAuth consent for this connector and return the URL to open. |
| `PUT` | `/v1/projects/{project_id}/connectors/{slug}/credentials` | `set_credentials` | Session JWT (User) | **INTEGRATION** | Update the connector's stored setup values (rotate a client secret, fix a typo'd key). |
| `POST` | `/v1/projects/{project_id}/connectors/{slug}/disconnect` | `disconnect_connector` | Session JWT (Editor/User) | **INTEGRATION** | Revoke the stored token WITHOUT uninstalling: the tools stay wired into workflows and |
| `POST` | `/v1/projects/{project_id}/connectors/{slug}/install` | `install_connector` | Session JWT (User) | **INTEGRATION** | Add a catalog connector without connecting to it yet. |
| `GET` | `/v1/projects/{project_id}/connectors/{slug}/status` | `connector_status` | Session JWT (Editor/User) | **INTEGRATION** | Whether this connector is usable right now - and for a per-user connector, whether the |
| `POST` | `/v1/projects/{project_id}/connectors/{slug}/sync` | `sync_connector` | Session JWT (Editor/User) | **INTEGRATION** | Bring a connector's actions back in line with its manifest. |

### Module: `forge.routers.conversations` (4 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/conversations` | `list_conversations` | Session JWT (User) | **CORE** | List conversations endpoint |
| `GET` | `/v1/projects/{project_id}/conversations/facets` | `conversation_facets` | Session JWT (User) | **CORE** | Conversation facets endpoint |
| `POST` | `/v1/projects/{project_id}/conversations/purge` | `purge_conversations` | Session JWT (Admin) | **CORE** | Manual retention control (admin only). Nothing is auto-deleted. |
| `GET` | `/v1/projects/{project_id}/conversations/{thread_id}` | `get_conversation` | Session JWT (User) | **CORE** | Get conversation endpoint |

### Module: `forge.routers.evals` (8 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/datasets` | `list_datasets` | Session JWT (User) | **CORE** | List datasets endpoint |
| `POST` | `/v1/projects/{project_id}/datasets` | `create_dataset` | Session JWT (User) | **CORE** | Create dataset endpoint |
| `DELETE` | `/v1/projects/{project_id}/datasets/{dataset_id}` | `delete_dataset` | Session JWT (User) | **CORE** | Delete dataset endpoint |
| `PATCH` | `/v1/projects/{project_id}/datasets/{dataset_id}` | `update_dataset` | Session JWT (User) | **CORE** | Update dataset endpoint |
| `POST` | `/v1/projects/{project_id}/datasets/{dataset_id}/run` | `run_dataset` | Session JWT (Editor/User) | **CORE** | Run dataset endpoint |
| `POST` | `/v1/projects/{project_id}/datasets/{dataset_id}/run/stream` | `run_dataset_stream` | Session JWT (Editor/User) | **CORE** | Same as /run, but streams SSE frames (start / item / done / error) so the console can |
| `GET` | `/v1/projects/{project_id}/datasets/{dataset_id}/runs` | `list_eval_runs` | Session JWT (User) | **CORE** | Persisted eval-run history for a dataset (newest first) - quality trend + regression view. |
| `GET` | `/v1/projects/{project_id}/datasets/{dataset_id}/runs/{eval_run_id}/results` | `list_eval_results` | Session JWT (User) | **CORE** | Per-item outcomes for one persisted eval run (for per-example diffing). |

### Module: `forge.routers.handoff` (2 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/handoffs` | `list_handoffs` | Session JWT (User) | **CORE** | List handoffs endpoint |
| `POST` | `/v1/projects/{project_id}/handoffs/{handoff_id}/reply` | `reply_handoff` | Session JWT (Editor/User) | **CORE** | Reply handoff endpoint |

### Module: `forge.routers.health` (5 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/health` | `health` | None (Public probe) | **CORE** | Liveness: the process is up and serving. Cheap and dependency-free. |
| `GET` | `/livez` | `health` | None (Public probe) | **CORE** | Liveness: the process is up and serving. Cheap and dependency-free. |
| `GET` | `/metrics` | `metrics` | None (Public probe) | **CORE** | Prometheus text-format exposition of the in-process counters so operators can scrape |
| `GET` | `/readyz` | `readyz` | None (Public probe) | **CORE** | Readiness: can this instance actually serve traffic? Checks the DB, the durable |
| `GET` | `/version` | `version_info` | None (Public probe) | **CORE** | Version info endpoint |

### Module: `forge.routers.hooks` (1 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `POST` | `/v1/hooks/{key}` | `inbound_webhook` | Webhook Key + HMAC (Public) | **INTEGRATION** | Inbound webhook endpoint |

### Module: `forge.routers.knowledge` (18 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/knowledge/chunk` | `chunk_detail` | Session JWT (User) | **CORE** | Full text (+ light metadata) of a single chunk, fetched on demand when a dot is selected |
| `POST` | `/v1/projects/{project_id}/knowledge/dedupe` | `dedupe_chunks` | Session JWT (User) | **CORE** | Remove exact-duplicate chunks (identical text) project-wide, keeping one copy of each. |
| `GET` | `/v1/projects/{project_id}/knowledge/folders` | `list_folders` | Session JWT (User) | **CORE** | List folders endpoint |
| `GET` | `/v1/projects/{project_id}/knowledge/health` | `embedding_health` | Session JWT (User) | **CORE** | Embedding-dimension health: flags sources embedded with a different model than the |
| `POST` | `/v1/projects/{project_id}/knowledge/map` | `chunk_map` | Session JWT (User) | **CORE** | Chunk-map visualizer: 2-D (PCA) projection of the project's chunk vectors, colored by |
| `POST` | `/v1/projects/{project_id}/knowledge/search` | `search` | Session JWT (User) | **CORE** | Search endpoint |
| `GET` | `/v1/projects/{project_id}/knowledge/sources` | `list_sources` | Session JWT (User) | **CORE** | List sources endpoint |
| `POST` | `/v1/projects/{project_id}/knowledge/sources` | `add_source` | Session JWT (Editor/User) | **CORE** | Add source endpoint |
| `POST` | `/v1/projects/{project_id}/knowledge/sources/rechunk` | `rechunk_sources` | Session JWT (User) | **CORE** | Re-chunk a multi-selected set of sources with one shared set of overrides |
| `POST` | `/v1/projects/{project_id}/knowledge/sources/upload` | `upload_source` | Session JWT (Editor/User) | **CORE** | Upload a document file (.txt/.md/.pdf and other text formats) into the knowledge base. |
| `DELETE` | `/v1/projects/{project_id}/knowledge/sources/{source_id}` | `delete_source` | Session JWT (Editor/User) | **CORE** | Delete source endpoint |
| `PATCH` | `/v1/projects/{project_id}/knowledge/sources/{source_id}` | `update_source` | Session JWT (User) | **CORE** | Move a source between folders (the only mutable field; content requires re-ingest). |
| `POST` | `/v1/projects/{project_id}/knowledge/sources/{source_id}/reingest` | `reingest_source` | Session JWT (User) | **CORE** | Re-fetch + re-embed a source (re-crawl a site, or re-embed under the current model). |
| `GET` | `/v1/projects/{project_id}/qa-pairs` | `list_qa` | Session JWT (User) | **CORE** | List qa endpoint |
| `POST` | `/v1/projects/{project_id}/qa-pairs` | `add_qa` | Session JWT (Editor/User) | **CORE** | Add qa endpoint |
| `GET` | `/v1/projects/{project_id}/qa-pairs/kinds` | `list_qa_kinds` | Session JWT (User) | **CORE** | List qa kinds endpoint |
| `DELETE` | `/v1/projects/{project_id}/qa-pairs/{qa_id}` | `delete_qa` | Session JWT (Editor/User) | **CORE** | Delete qa endpoint |
| `PATCH` | `/v1/projects/{project_id}/qa-pairs/{qa_id}` | `update_qa` | Session JWT (Editor/User) | **CORE** | Update qa endpoint |

### Module: `forge.routers.mcp_clients` (5 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/mcp-clients` | `list_clients` | Session JWT (User) | **CORE** | Registered MCP servers, each flagged with the connector that owns it (if any). |
| `POST` | `/v1/projects/{project_id}/mcp-clients` | `create_client` | Session JWT (User) | **CORE** | Create client endpoint |
| `DELETE` | `/v1/projects/{project_id}/mcp-clients/{client_id}` | `delete_client` | Session JWT (User) | **CORE** | Delete client endpoint |
| `PATCH` | `/v1/projects/{project_id}/mcp-clients/{client_id}` | `update_client` | Session JWT (User) | **CORE** | Update client endpoint |
| `GET` | `/v1/projects/{project_id}/mcp-clients/{client_id}/tools` | `list_remote_tools` | Session JWT (Editor/User) | **CORE** | Connect to the server and list the tools it exposes - drives the 'pick which to add' UI. |

### Module: `forge.routers.models` (6 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/models` | `list_models` | Session JWT (User) | **CORE** | List models endpoint |
| `POST` | `/v1/models/discover` | `discover_models` | Session JWT (User) | **CORE** | Discover models endpoint |
| `GET` | `/v1/models/providers` | `list_providers` | Session JWT (Editor/User) | **CORE** | List providers endpoint |
| `POST` | `/v1/models/providers` | `create_provider` | Session JWT (Editor/User) | **CORE** | Create provider endpoint |
| `DELETE` | `/v1/models/providers/{provider_id}` | `delete_provider` | Session JWT (Editor/User) | **CORE** | Delete provider endpoint |
| `PATCH` | `/v1/models/providers/{provider_id}` | `update_provider` | Session JWT (Editor/User) | **CORE** | Update provider endpoint |

### Module: `forge.routers.nodes` (1 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/node-types` | `list_node_types` | Session JWT (User) | **CORE** | List node types endpoint |

### Module: `forge.routers.oauth` (3 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/oauth/callback` | `oauth_callback` | OAuth State / Auth Code (Public Callback) | **INTEGRATION** | Oauth callback endpoint |
| `POST` | `/v1/projects/{project_id}/auth-providers/{ap_id}/oauth/start` | `oauth_start` | Session JWT (User) | **INTEGRATION** | Oauth start endpoint |
| `GET` | `/v1/projects/{project_id}/auth-providers/{ap_id}/oauth/status` | `oauth_status` | Session JWT (User) | **INTEGRATION** | Oauth status endpoint |

### Module: `forge.routers.pricing` (2 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/pricing` | `list_pricing` | Session JWT (User) | **CORE** | List pricing endpoint |
| `PUT` | `/v1/pricing/{model}` | `set_pricing` | Session JWT (User) | **CORE** | Set pricing endpoint |

### Module: `forge.routers.project_run` (1 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `POST` | `/v1/projects/{project_id}/run` | `project_run` | Bearer (FORGE_SERVICE_API_TOKEN or User JWT) | **INTEGRATION** | Project run endpoint |

### Module: `forge.routers.projects` (9 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects` | `list_projects` | Session JWT (User) | **CORE** | List projects endpoint |
| `POST` | `/v1/projects` | `create_project` | Session JWT (Editor/User) | **CORE** | Create project endpoint |
| `DELETE` | `/v1/projects/{project_id}` | `delete_project` | Session JWT (User) | **CORE** | Delete project endpoint |
| `GET` | `/v1/projects/{project_id}` | `get_project` | Session JWT (User) | **CORE** | Get project endpoint |
| `PATCH` | `/v1/projects/{project_id}` | `update_project` | Session JWT (Editor/User) | **CORE** | Update project endpoint |
| `GET` | `/v1/projects/{project_id}/counts` | `project_counts` | Session JWT (User) | **CORE** | Lightweight per-resource counts for the project sidebar badges |
| `GET` | `/v1/projects/{project_id}/members` | `list_project_members` | Session JWT (User) | **CORE** | List project members endpoint |
| `DELETE` | `/v1/projects/{project_id}/members/{user_id}` | `remove_project_member` | Session JWT (Admin) | **CORE** | Remove project member endpoint |
| `PUT` | `/v1/projects/{project_id}/members/{user_id}` | `set_project_member` | Session JWT (Admin) | **CORE** | Grant/update a user's role ON THIS PROJECT. Elevates their tenant-wide role for this |

### Module: `forge.routers.runs` (5 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `POST` | `/v1/projects/{project_id}/workflows/{workflow_id}/runs` | `create_run` | Session JWT (Editor/User) | **CORE** | Create run endpoint |
| `POST` | `/v1/projects/{project_id}/workflows/{workflow_id}/runs/{run_id}/cancel` | `cancel_run` | Session JWT (Editor/User) | **CORE** | Cancel a run: mark it canceled and cooperatively stop it (frees the tenant-concurrency |
| `POST` | `/v1/projects/{project_id}/workflows/{workflow_id}/runs/{run_id}/rerun` | `rerun` | Session JWT (User) | **CORE** | Replay a past run: create a new run with the same input (fresh thread). |
| `POST` | `/v1/projects/{project_id}/workflows/{workflow_id}/runs/{run_id}/resume` | `resume_run` | Session JWT (User) | **CORE** | Resume run endpoint |
| `GET` | `/v1/projects/{project_id}/workflows/{workflow_id}/runs/{run_id}/stream` | `stream_run` | Session JWT (User) | **CORE** | Stream run endpoint |

### Module: `forge.routers.secrets` (4 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/secrets` | `list_secrets` | Session JWT (User) | **CORE** | List secrets endpoint |
| `POST` | `/v1/projects/{project_id}/secrets` | `create_secret` | Session JWT (User) | **CORE** | Create secret endpoint |
| `DELETE` | `/v1/projects/{project_id}/secrets/{name}` | `delete_secret` | Session JWT (User) | **CORE** | Delete secret endpoint |
| `GET` | `/v1/projects/{project_id}/secrets/{name}/usage` | `secret_usage` | Session JWT (User) | **CORE** | Secret usage endpoint |

### Module: `forge.routers.stats` (3 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/stats/dashboard` | `dashboard` | Session JWT (User) | **CORE** | Dashboard endpoint |
| `GET` | `/v1/stats/projects/{project_id}` | `project_stats` | Session JWT (User) | **CORE** | Project-scoped rollups + report rows (per workflow + Forge Assistant). |
| `GET` | `/v1/stats/projects/{project_id}/analytics` | `project_analytics` | Session JWT (User) | **CORE** | Time-series + breakdowns for the project Analytics dashboard, over the last `days`. |

### Module: `forge.routers.tool_sets` (7 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/tool-sets` | `list_tool_sets` | Session JWT (User) | **CORE** | List tool sets endpoint |
| `POST` | `/v1/projects/{project_id}/tool-sets` | `create_tool_set` | Session JWT (User) | **CORE** | Create tool set endpoint |
| `DELETE` | `/v1/projects/{project_id}/tool-sets/{set_id}` | `delete_tool_set` | Session JWT (User) | **CORE** | Delete tool set endpoint |
| `GET` | `/v1/projects/{project_id}/tool-sets/{set_id}` | `get_tool_set` | Session JWT (User) | **CORE** | Get tool set endpoint |
| `PATCH` | `/v1/projects/{project_id}/tool-sets/{set_id}` | `update_tool_set` | Session JWT (User) | **CORE** | Update tool set endpoint |
| `DELETE` | `/v1/projects/{project_id}/tool-sets/{set_id}/tools/{tool_id}` | `remove_tool_from_set` | Session JWT (User) | **CORE** | Remove tool from set endpoint |
| `POST` | `/v1/projects/{project_id}/tool-sets/{set_id}/tools/{tool_id}` | `add_tool_to_set` | Session JWT (User) | **CORE** | Add tool to set endpoint |

### Module: `forge.routers.tools` (8 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/tools` | `list_tools` | Session JWT (User) | **CORE** | List tools endpoint |
| `POST` | `/v1/projects/{project_id}/tools` | `create_tool` | Session JWT (Editor/User) | **CORE** | Create tool endpoint |
| `POST` | `/v1/projects/{project_id}/tools/export` | `export_tools` | Session JWT (User) | **CORE** | Serialize the selected tools into a downloadable single-type bundle. |
| `POST` | `/v1/projects/{project_id}/tools/import` | `import_tools` | Session JWT (Editor/User) | **CORE** | Create tools from an uploaded bundle in THIS project (new ids, auto-renamed on collision). |
| `DELETE` | `/v1/projects/{project_id}/tools/{tool_id}` | `delete_tool` | Session JWT (User) | **CORE** | Delete tool endpoint |
| `GET` | `/v1/projects/{project_id}/tools/{tool_id}` | `get_tool` | Session JWT (User) | **CORE** | Get tool endpoint |
| `PATCH` | `/v1/projects/{project_id}/tools/{tool_id}` | `update_tool` | Session JWT (Editor/User) | **CORE** | Update tool endpoint |
| `POST` | `/v1/projects/{project_id}/tools/{tool_id}/test` | `test_tool` | Session JWT (Editor/User) | **CORE** | Test tool endpoint |

### Module: `forge.routers.traces` (2 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/traces` | `list_traces` | Session JWT (User) | **CORE** | List traces endpoint |
| `GET` | `/v1/projects/{project_id}/traces/{trace_id}` | `get_trace` | Session JWT (User) | **CORE** | Get trace endpoint |

### Module: `forge.routers.triggers` (3 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/triggers` | `list_triggers` | Session JWT (Editor/User) | **CORE** | Project triggers, plus your own personal ones. |
| `PUT` | `/v1/projects/{project_id}/triggers/{trigger_id}/run-as` | `set_run_as` | Session JWT (Editor/User) | **CORE** | Point this trigger at a person's connected accounts. |
| `PUT` | `/v1/projects/{project_id}/triggers/{trigger_id}/scope` | `set_scope` | Session JWT (Editor/User) | **CORE** | Move a trigger between "the team's" and "mine". |

### Module: `forge.routers.versions` (5 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/versions/project/{project_id}/activity` | `project_activity` | Session JWT (User) | **CORE** | Read-only project-wide activity feed for knowledge sources + Q&A pairs (added / changed / |
| `GET` | `/v1/versions/project/{project_id}/config-history` | `project_config_history` | Session JWT (User) | **CORE** | Full project snapshots (newest first, incl. the snapshot body) so the Settings > History |
| `GET` | `/v1/versions/{entity_type}/{entity_id}` | `list_versions` | Session JWT (User) | **CORE** | List versions endpoint |
| `POST` | `/v1/versions/{entity_type}/{entity_id}/restore` | `restore_version` | Session JWT (Editor/User) | **CORE** | Restore version endpoint |
| `GET` | `/v1/versions/{entity_type}/{entity_id}/{version_no}` | `get_version` | Session JWT (User) | **CORE** | Get version endpoint |

### Module: `forge.routers.workflows` (11 endpoints)

| Method | Path | Function | Auth Mechanism | Classification | Purpose |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `GET` | `/v1/projects/{project_id}/workflows` | `list_workflows` | Session JWT (User) | **CORE** | List workflows endpoint |
| `POST` | `/v1/projects/{project_id}/workflows` | `create_workflow` | Session JWT (Editor/User) | **CORE** | Create workflow endpoint |
| `POST` | `/v1/projects/{project_id}/workflows/export` | `export_workflows` | Session JWT (User) | **CORE** | Serialize the selected workflows (canvas + executable) into a downloadable bundle. |
| `POST` | `/v1/projects/{project_id}/workflows/import` | `import_workflows` | Session JWT (Editor/User) | **CORE** | Create workflows from an uploaded bundle in THIS project (imported as drafts). |
| `POST` | `/v1/projects/{project_id}/workflows/validate` | `validate_executable` | Session JWT (User) | **CORE** | Validate executable endpoint |
| `DELETE` | `/v1/projects/{project_id}/workflows/{workflow_id}` | `delete_workflow` | Session JWT (User) | **CORE** | Delete workflow endpoint |
| `GET` | `/v1/projects/{project_id}/workflows/{workflow_id}` | `get_workflow` | Session JWT (User) | **CORE** | Get workflow endpoint |
| `PATCH` | `/v1/projects/{project_id}/workflows/{workflow_id}` | `update_workflow` | Session JWT (Editor/User) | **CORE** | Update workflow endpoint |
| `PUT` | `/v1/projects/{project_id}/workflows/{workflow_id}/canvas` | `save_canvas` | Session JWT (Editor/User) | **CORE** | Save canvas endpoint |
| `PUT` | `/v1/projects/{project_id}/workflows/{workflow_id}/executable` | `update_executable` | Session JWT (Editor/User) | **CORE** | Update executable endpoint |
| `POST` | `/v1/projects/{project_id}/workflows/{workflow_id}/publish` | `publish_workflow` | Session JWT (Editor/User) | **CORE** | Validate the stored executable and mark the workflow active (a published version). |
