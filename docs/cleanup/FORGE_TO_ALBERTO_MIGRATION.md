# Alberto — Controlled Semantic Refactoring Migration Report

## Executive Summary

This document details the completed controlled semantic refactoring of the legacy "Forge" identity to "Alberto" across the backend (FastAPI, LangGraph, SQLite, ChromaDB, Alembic), frontend (Next.js, React Flow, TypeScript API client), configuration, container definitions, and external API contracts.

In accordance with strict safety guidelines, this migration was executed **without global search-and-replace**, preserving existing database structures, WAL logs, serialized LangGraph checkpoints, and external integration contracts.

---

## 1. Architectural Scope & Refactoring Decisions

### A. Branding & User Interface
- **Changes**: Updated public application titles, navigation headers, logo copy, and documentation in `frontend/components/screens/` (`auth.tsx`, `connectors.tsx`, `mcp.tsx`, `tools.tsx`, `workflows.tsx`) and root READMEs.
- **Contract Preservation**: Preserved internal UI state structures and DOM IDs where automated tests or browser integrations attach.

### B. Python Runtime Namespace (`forge` → `alberto`)
- **Package Relocation**: Migrated `backend/forge/` to `backend/alberto/`.
- **Packaging**: Updated `backend/pyproject.toml` package definition to `alberto-api` and wheel package to `alberto`.
- **System Module & Import Shims**:
  - Implemented `backend/forge/__init__.py` and `sys.modules["forge"] = sys.modules["alberto"]` alias.
  - Implemented an import hook `_ForgeImportHook` on `sys.meta_path` mapping any dynamic or reflective `forge.<submodule>` import directly to `alberto.<submodule>`.
  - Added schema resolution in `backend/alberto/schemas/contracts.py` to resolve both `urn:alberto:schema:*` and `urn:forge:schema:*`.
  - Duplicated assistant skill directory `backend/alberto/assistant_skills/alberto-platform/` while keeping `forge-platform/` intact to prevent deserialization failure of 51 existing LangGraph checkpoints in `data/db/checkpoints.sqlite`.
- **Import Statements**: Systematically updated all 194 Python files in backend, migrations, and tests from `forge.*` to `alberto.*`.

### C. Internal Programmatic Identifiers
- **Tracer**: Introduced `AlbertoTracer` with `ForgeTracer = AlbertoTracer` backward-compatibility alias in `backend/alberto/tracing/tracer.py` and `__init__.py`.
- **Default CurrentUser**: Updated default service account identifier from `service@forge.local` to `service@alberto.local`.
- **React Flow Canvas**: Registered `nodeTypes = { alberto: ForgeNode, forge: ForgeNode }` in `frontend/components/screens/workflows.tsx` so legacy workflows stored in SQLite continue rendering without schema mutation.
- **Client Events & Auth Storage**:
  - Client dispatches both `alberto:counts-changed` / `forge:counts-changed` and `alberto:unauthorized` / `forge:unauthorized`.
  - `frontend/lib/api.ts` checks `alberto_access_token` first with graceful fallback to `forge_access_token`.

### D. Configuration Contracts
- **Pydantic Settings**:
  - Updated `backend/alberto/config.py` `Settings` class with `env_prefix="ALBERTO_"`.
  - Configured `settings_customise_sources` with a 5-tier fallback cascade:
    1. Explicit keyword arguments (`init_settings`).
    2. Environment variables with `ALBERTO_` prefix.
    3. Environment variables with legacy `FORGE_` prefix.
    4. `.env` file entries with `ALBERTO_` prefix.
    5. `.env` file entries with legacy `FORGE_` prefix.
- **Docker Compose**: Updated service configurations to prioritize `ALBERTO_*` with fallback interpolation `${FORGE_*:-...}`.
- **Startup Script**: Updated `start.sh` port detection to check `ALBERTO_PORT` before `FORGE_PORT`.

### E. Database & Persistent Identifiers
- **SQLite Database**: Existing database in `data/db/alberto.db` verified intact with 35 tables. 0 columns named forge; zero destructive migrations needed.
- **LangGraph Checkpoints**: Maintained serialized string compatibility for `b"forge-platform"` checkpoints.
- **ChromaDB Collections**: Explicitly preserved existing collection names (`forge_kb_*`, `forge_qa_*`, `forge_mem_*`, `forge_cache_*`) in `backend/alberto/memory/chroma.py` to prevent orphaning production vector embeddings.
- **API Keys**: Default generation prefix migrated to `alberto_sk_` while accepting and verifying legacy `forge_sk_` keys in `backend/alberto/services/apikeys.py`.

### F. API and Integration Contracts
- **HTTP Context Header**: `run_context` dependency in `backend/alberto/deps.py` reads `X-Alberto-Context` with fallback to `X-Forge-Context`.
- **Webhook Signatures**: `backend/alberto/api/v1/hooks.py` checks `X-Alberto-Signature` with fallback to `X-Forge-Signature`.
- **Connector Manifest Format**:
  - `backend/alberto/connectors/manifest.py` updated to default to `alberto.connector/1` while validating and accepting `forge.connector/1`.
  - Manifest `publisher` accepts `Literal["alberto", "forge", "community", "custom"]`.
- **Generative UI Component Markers**: Updated regex in `backend/alberto/services/components.py` and `frontend/lib/chat-parts.ts` to parse both `[[alberto:component:...]]` and `[[forge:component:...]]`.
- **Next.js Reverse Proxy**: `frontend/next.config.mjs` proxies both `/api/alberto/:path*` and `/api/forge/:path*` to backend destination.
- **Frontend Client**: `frontend/lib/api.ts` updated to route requests via `/api/alberto`.

---

## 2. Changed Modules Inventory

| Area | Path | Key Changes |
|---|---|---|
| **Backend Package** | `backend/alberto/` | Root package renamed from `backend/forge/` |
| **Compatibility Shims** | `backend/forge/__init__.py`<br>`backend/alberto/__init__.py` | Package alias, `_ForgeImportHook` on `sys.meta_path`, `ForgeTracer` alias |
| **Packaging & Build** | `backend/pyproject.toml`<br>`backend/Dockerfile`<br>`docker-compose.yml` | Package `alberto-api`, module `alberto`, env mapping `ALBERTO_*` |
| **Migrations** | `backend/migrations/env.py` | Import metadata from `alberto.models` |
| **Schemas & Skills** | `backend/alberto/schemas/contracts.py`<br>`backend/alberto/assistant_skills/` | Added `urn:alberto:schema:*` and `alberto-platform/` skill |
| **Configuration** | `backend/alberto/config.py` | `ALBERTO_` prefix + 5-tier fallback cascade for `FORGE_` |
| **API Endpoints & Security** | `backend/alberto/deps.py`<br>`backend/alberto/api/v1/hooks.py`<br>`backend/alberto/services/apikeys.py` | Dual headers (`X-Alberto-*`/`X-Forge-*`), dual API key prefixes (`alberto_sk_`/`forge_sk_`) |
| **Connectors & Tools** | `backend/alberto/connectors/manifest.py`<br>`backend/alberto/services/components.py` | Manifest formats (`alberto.connector/1`/`forge.connector/1`), component markers |
| **Frontend Config & Client** | `frontend/next.config.mjs`<br>`frontend/lib/api.ts` | Dual proxy rewrites (`/api/alberto/*` & `/api/forge/*`), `BASE = "/api/alberto"`, dual token lookup |
| **Frontend UI** | `frontend/components/screens/*.tsx`<br>`frontend/lib/chat-parts.ts` | Alberto branding, dual event handling, dual canvas nodeTypes |
| **Tests** | `tests/backend/*.py`<br>`tests/frontend/*.tsx` | Updated imports to `alberto.*`, verified against unchanged contracts |

---

## 3. Preserved Runtime Contracts & Data Compatibility

1. **Active Checkpoints**: `checkpoints.sqlite` continues loading historical LangGraph runs without pickle or JSON deserialization errors.
2. **Persistent ChromaDB**: Zero vectors invalidated or re-embedded.
3. **Existing API Keys**: Third-party scripts or integrations using `forge_sk_*` continue working without revocation.
4. **Active Client Tokens**: Users with `forge_access_token` in `localStorage` remain authenticated.
5. **Webhooks & Integrations**: External callers signing payloads with `X-Forge-Signature` or sending `X-Forge-Context` are verified without interruption.
6. **Existing Manifests & Catalog**: Existing connector definitions using `forge.connector/1` load and validate without alteration.

---

## 4. Test Execution & Regressions Resolved

- **Backend Pytest Suite**:
  - Baseline: 578 passed, 8 skipped, 36 xfailed.
  - Post-Refactoring: **578 passed, 8 skipped, 36 xfailed (100% parity, 0 regressions)**.
- **Frontend Vitest Suite**:
  - Baseline: 4 passed.
  - Post-Refactoring: **4 passed (100% parity)**.
- **Frontend Next.js Production Build**:
  - `next build` executed with exit code 0.
  - Zero type errors, zero bundle generation errors.

### Regressions Encountered and Corrected During Migration
1. **Dynamic Import Hook**: Initial package move broke reflective imports of `forge.*` in isolated tests. Resolved by installing `_ForgeImportHook` on `sys.meta_path`.
2. **Contract Schema Resolution**: Schemas requesting `urn:forge:schema:*` failed schema validation. Resolved by duplicating schema catalog to `backend/schemas/alberto` and mapping both URI prefixes in `contracts.py`.
3. **Pydantic Env Precedence**: Pydantic v2 `settings_customise_sources` requires custom ordering to prioritize `ALBERTO_` while retaining `FORGE_`. Resolved via explicit `(init_settings, EnvSettingsSource(ALBERTO_), EnvSettingsSource(FORGE_), ...)` tuple.

---

## 5. Follow-Up Migration Opportunities (Future Phases)

- **Phase X (Deferred Deprecation)**: In a future major release, introduce telemetry warnings when `FORGE_*` environment variables or `forge_sk_` keys are used.
- **Phase Y (ChromaDB Migration Script)**: If unified collection naming is desired, provide an offline migration utility to re-index collections from `forge_*` to `alberto_*`.
