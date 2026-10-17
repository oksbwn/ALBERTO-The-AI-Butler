# Alberto — Milestone 1 Final Review & Targeted Corrections Validation Report

## A. Executive Summary

This report provides the targeted final validation for Milestone 1: Security & Privacy Hardening, addressing the three narrowly defined concerns identified during independent review:

1. **Remove Remaining Fake Model Fallback**: Confirmed that `backend/alberto/services/assistant.py` retained implicit fallback (`or "fake:offline"` in `_assistant_model_ref` and `or "fake:Configure a model..."` in `_default_agent_model`). Corrected by failing closed with explicit `ValueError` when no model is configured or available. Explicitly configured test models in test environments remain preserved.
2. **Verify Tool Authorization Boundaries & Trusted Identity**: Thoroughly audited identity origin, context lifecycle, tool materialization, and dispatch paths. Confirmed that authorization originates in authoritative caller authentication (`request -> CurrentUser -> Thread.meta["end_user"] -> CompileContext.end_user`). Verified that compile contexts and materialized tools are run-scoped (no cross-user privilege leakage). Strengthened `entitlement_denial` to fail closed if context or entitlement checker is missing, unified it with `rest.py`, and added synchronous `.invoke()` entitlement enforcement for MCP tools.
3. **Verify Development Authentication Safeguards**: Confirmed `dev_allow_anonymous_owner` defaults to `False`. Audited startup lifecycle and confirmed that `lifespan(app)` directly invokes `settings.validate_production()` during boot, refusing to start (`RuntimeError`) if development shortcuts are active in non-dev environments. In production, unauthenticated requests are unconditionally rejected with HTTP 401.

- **Issues Confirmed**: Remaining `fake:` model fallbacks in `assistant.py`; lack of sync invoke gating on MCP tools; inline duplicate entitlement check in `rest.py`.
- **Issues Corrected**: Removed all implicit fake model fallbacks; added sync invocation gating for MCP tools; centralized fail-closed `entitlement_denial` across REST, builtin, MCP, and code/sql tools.
- **Issues Already Handled**: Context propagation per run; `dev_allow_anonymous_owner` default `False`; production validation refusal at startup.
- **Remaining Risks**: None within Milestone 1 scope.
- **Final Milestone Status**: **COMPLETE**.

---

## B. Finding-by-Finding Assessment

### 1. Model Resolution: Elimination of Remaining Fake Model Fallback

- **Original Behaviour**:
  `_assistant_model_ref` and `_default_agent_model` in `backend/alberto/services/assistant.py` fell back to `"fake:offline"` and `"fake:Configure a model in the model registry."` when no model was configured.
- **Current Behaviour**:
  Both functions evaluate: (1) explicit model from project/agent config, (2) registered default model ID, (3) project default model, (4) explicit project fallback model, (5) global default model in settings. If no model is configured or available, they raise a clear `ValueError("No model configured or available. Please configure an assistant model or default registered model.")`. Explicitly configured fake models for tests (e.g., `assistant_model="fake:test"`) continue to function without disruption.
- **Source Files & Functions**:
  - `backend/alberto/services/assistant.py`: `_default_agent_model` (lines 122–134)
  - `backend/alberto/services/assistant.py`: `_assistant_model_ref` (lines 841–863)
  - `backend/alberto/engine/models.py`: `resolve_model` (lines 80–90)
- **Actual Verification Evidence**:
  Calling `_assistant_model_ref(ctx)` or `resolve_model(None, ctx)` with empty configuration raises `ValueError` with clear guidance. Cloud keys present in context are never automatically routed to.
- **Changes Made**:
  Replaced `"fake:..."` string fallbacks with explicit `ValueError` raises in `_default_agent_model` and `_assistant_model_ref`.
- **Corresponding Test Cases**:
  - `tests/backend/test_m1_security_hardening.py::test_missing_default_model_raises_meaningful_error`
  - `tests/backend/test_m1_security_hardening.py::test_no_unintended_cloud_fallback_when_credentials_exist_in_assistant`
  - `tests/backend/test_m1_security_hardening.py::test_default_agent_model_raises_meaningful_error`

---

### 2. Tool Authorization Boundaries & Trusted Execution Identity

- **Original Behaviour**:
  `entitlement_denial` in `materialize.py` only checked `ctx.has_entitlements` if present; if `ctx` lacked `has_entitlements`, it returned `None` (open). `rest.py` maintained an identical inline check. MCP tool wrapping in `mcp.py` only provided coroutine gating (`_gated_call`), leaving synchronous `.invoke()` ungated.
- **Current Behaviour**:
  - **Fail-Closed Entitlement Gate**: `entitlement_denial` returns a denial if `required_entitlements` is non-empty and `ctx` is either `None`, missing `has_entitlements`, or `ctx.has_entitlements(required)` is `False`.
  - **Deduplication**: `rest.py` reuses `entitlement_denial(cfg, ctx)` from `materialize.py`.
  - **Complete Invocation Coverage**: `load_mcp_tool` wraps both `coroutine=_gated_call` and `func=_gated_sync`.
  - **Identity Provenance & Isolation**:
    1. Identity originates in `deps.py`: `get_current_user` validates JWT and extracts `CurrentUser(id, tenant_id, role)`.
    2. Runs originate in `RunService`: `end_user=(thread.meta or {}).get("end_user")` is extracted from the authoritative run metadata.
    3. Context creation: `build_compile_context` creates an ephemeral `CompileContext(..., end_user=end_user)`.
    4. Tool materialization: `materialize_tool` binds tools specifically to that per-run `CompileContext`. Tools are not shared across runs or across users.
    5. Cache partitioning: `_WRAP_CACHE` keys include `_context_fingerprint(ctx)` (hashing `run_context` and `end_user`), and the entitlement check executes *before* any cache lookup.
- **Source Files & Functions**:
  - `backend/alberto/tools/materialize.py`: `entitlement_denial` (lines 38–48), `_wrap_reliability` (lines 66–155)
  - `backend/alberto/tools/rest.py`: `_call` (lines 782–787)
  - `backend/alberto/tools/mcp.py`: `load_mcp_tool` (lines 582–605)
- **Actual Verification Evidence**:
  - Builtin tools (`calculator`, `current_time`, `remember`) tested under authorized and unauthorized states. Mutating tool side-effects are completely prevented on denial.
  - MCP tools tested across both async `.ainvoke()` and sync `.invoke()` paths.
  - Entitlement gate tested against `None` context, missing methods, and uncallable attributes.
- **Changes Made**:
  Updated `materialize.py` `entitlement_denial` to fail closed; refactored `rest.py` to reuse `entitlement_denial`; added `_gated_sync` in `mcp.py`.
- **Corresponding Test Cases**:
  - `tests/backend/test_m1_security_hardening.py::test_builtin_tool_entitlement_authorized`
  - `tests/backend/test_m1_security_hardening.py::test_builtin_tool_entitlement_unauthorized`
  - `tests/backend/test_m1_security_hardening.py::test_builtin_side_effect_prevented_when_unauthorized`
  - `tests/backend/test_m1_security_hardening.py::test_mcp_tool_entitlement_enforcement`
  - `tests/backend/test_m1_security_hardening.py::test_mcp_tool_sync_entitlement_enforcement`
  - `tests/backend/test_m1_security_hardening.py::test_entitlement_denial_fails_closed_when_context_lacks_checker`

---

### 3. Development Authentication Safeguards

- **Original Behaviour**:
  When `auth_required` was `False`, all unauthenticated callers received the `owner` role.
- **Current Behaviour**:
  - Default value of `dev_allow_anonymous_owner` is `False`.
  - In local development (`environment in ("development", "dev", "local", "test")`) with `auth_required=False`, anonymous requests receive `role="viewer"` (`CurrentUser(id="anonymous", role="viewer")`), preventing access to admin/mutating endpoints.
  - In production (`environment="production"` or any environment outside `_DEV_ENVIRONMENTS`), `enforce_security` is `True`.
  - `lifespan(app)` in `main.py` directly executes `settings.validate_production()`, which checks:
    ```python
    if self.dev_allow_anonymous_owner:
        problems.append("FORGE_DEV_ALLOW_ANONYMOUS_OWNER must be false outside local development.")
    ```
    If present, the server refuses to start with `RuntimeError("Unsafe production configuration: ...")`.
  - Even if started, `deps.py` immediately rejects anonymous requests with HTTP 401 when `enforce_security=True`.
- **Source Files & Functions**:
  - `backend/alberto/config.py`: `Settings.dev_allow_anonymous_owner` (line 253), `validate_production` (lines 533–550)
  - `backend/alberto/main.py`: `lifespan` (lines 156–161)
  - `backend/alberto/deps.py`: `get_current_user` (lines 96–120)
- **Actual Verification Evidence**:
  - Startup verified: `async with lifespan(app)` raises `RuntimeError` if `dev_allow_anonymous_owner=True` in production.
  - Endpoint verified: `/v1/auth/me` returns 401 in production when unauthenticated.
  - Role escalation verified: `/v1/projects` POST returns 403 Forbidden to anonymous callers in dev mode.
- **Changes Made**:
  Audited startup invocation in `main.py`; verified fail-closed behavior; added lifespan boot test.
- **Corresponding Test Cases**:
  - `tests/backend/test_m1_security_hardening.py::test_anonymous_request_receives_viewer_role_when_auth_disabled`
  - `tests/backend/test_m1_security_hardening.py::test_dev_allow_anonymous_owner_explicit_shortcut`
  - `tests/backend/test_m1_security_hardening.py::test_production_mode_rejects_anonymous_even_if_dev_flag_set`
  - `tests/backend/test_m1_security_hardening.py::test_production_validator_rejects_dev_shortcuts`
  - `tests/backend/test_m1_security_hardening.py::test_lifespan_startup_enforces_production_validation`

---

## C. Architecture Quality

- **Separation of Concerns**: Kept tool authorization in `materialize.py`/`mcp.py`/`rest.py`, model selection in `models.py`/`assistant.py`/`runtime.py`, startup validation in `main.py`/`config.py`, and request authentication in `deps.py`.
- **Reusability**: Reused `entitlement_denial` across all tool implementations (REST, Builtin, MCP, Code, SQL, Components). Reused `CompileContext.has_entitlements` and `validate_production`.
- **Elimination of Duplication**: Replaced inline entitlement check in `rest.py` with shared `entitlement_denial`.
- **No Unnecessary Refactoring**: Zero renames, zero file moves, zero database schema changes, zero new permission frameworks.
- **No New Architectural Dependencies**: Used native Python standard library and existing LangChain/Pydantic facilities.

---

## D. Test Results

### 1. Focused Milestone 1 Regression Suite
- **Command**:
  ```bash
  backend\.venv\Scripts\python.exe -m pytest tests\backend\test_m1_security_hardening.py -v
  ```
- **Result**:
  `18 passed, 1 xfailed in 9.22s`
  *(1 xfail is the pre-existing in-memory ChromaDB vectorstore test-runner limitation)*

### 2. Full Backend Regression Suite
- **Command**:
  ```bash
  backend\.venv\Scripts\python.exe -m pytest tests\backend
  ```
- **Baseline**: 592 passed, 8 skipped, 37 xfailed.
- **Current Result**:
  `596 passed, 8 skipped, 37 xfailed in 113.14s`
- **Regressions**: **0**.

### 3. Frontend Test Suite
- **Command**:
  ```bash
  npm.cmd test -- --run
  ```
- **Result**:
  `4 passed (4 tests in 1 test file, 6.07s)`

### 4. Frontend Production Build
- **Command**:
  ```bash
  npm.cmd run build
  ```
- **Result**:
  Compiled successfully, static optimization verified, 0 errors.

---

## E. File Changes

| File | Change Description |
|---|---|
| `backend/alberto/services/assistant.py` | Removed `"fake:..."` fallback in `_default_agent_model` and `_assistant_model_ref`; raises `ValueError` on unconfigured model. |
| `backend/alberto/tools/materialize.py` | Updated `entitlement_denial` to fail closed if `ctx` is None or lacks a callable `has_entitlements`. |
| `backend/alberto/tools/rest.py` | Replaced duplicate inline entitlement check with shared `entitlement_denial`. |
| `backend/alberto/tools/mcp.py` | Added synchronous `_gated_sync` wrapper so `.invoke()` enforces entitlements alongside `.ainvoke()`. |
| `backend/alberto/config.py` | Preserved `dev_allow_anonymous_owner: bool = False` with production validation guard. |
| `backend/alberto/deps.py` | Preserved unprivileged `viewer` role for anonymous dev callers and 401 rejection outside dev. |
| `backend/alberto/engine/models.py` | Preserved strict `resolve_model` order with `ValueError` on missing/unregistered models. |
| `backend/alberto/services/runtime.py` | Preserved credential-free model resolution in `build_compile_context`. |
| `tests/backend/test_m1_security_hardening.py` | Added targeted tests for fail-closed entitlement checks, sync MCP invocation, lifespan startup guard, and assistant model errors. |

---

## F. Final Milestone Status

**COMPLETE**

All three review concerns (eliminating remaining fake model fallbacks, verifying tool authorization boundaries and identity provenance, and confirming development authentication safeguards) have been verified, implemented surgically, and validated with zero regressions across the backend and frontend suites.

**Ready for ChatGPT M1 Final Approval**
