# Alberto — Milestone 1 Implementation Report: Security & Privacy Hardening

## 1. Executive Summary

- **Milestone Goal**: Remediate three identified security and privacy audit findings without architectural redesign, scope expansion, or breaking changes to single-tenant local-first operations.
- **Findings Resolved**:
  1. **Task A — Tool Authorization Consistency**: Builtin and MCP tools now enforce the shared `required_entitlements` security gate (`entitlement_denial`) before execution. Side-effecting builtin tools are marked non-idempotent (`idempotent=False`) to prevent automatic retries. Sync and async callable contracts are preserved.
  2. **Task B — Explicit Model Selection**: Unintended cloud-model fallback eliminated. Removed hardcoded `_STRONG` cloud routing dict from `assistant.py` and removed automatic credential-based provider default assignment in `runtime.py`. Model resolution strictly follows: explicit model -> configured default registered model -> explicitly configured fallback -> meaningful error. Existing cloud providers remain supported only when explicitly selected.
  3. **Task C — Anonymous Authentication Privilege Escalation**: Unauthenticated callers under `auth_required=False` in development environments now receive the unprivileged `viewer` role instead of `owner`. Anonymous access outside development (`enforce_security=True`) is rejected with HTTP 401. An explicit development shortcut (`dev_allow_anonymous_owner: bool = False`) requires conscious configuration and is blocked by production validation guards.
- **Findings Not Reproducible**: All three findings were confirmed in the existing code and successfully remediated.
- **Overall Milestone Status**: COMPLETE.

---

## 2. Changes Made

### 1. `backend/alberto/tools/materialize.py`
- **Component**: `_wrap_reliability`, `materialize_tool`
- **Line Numbers**: ~18-30, ~66-150, ~160-175
- **Previous Behaviour**: `materialize_tool` returned `build_builtin_tool(cfg, ctx)` directly without reliability wrapping or entitlement checks. `_wrap_reliability` assumed `inner.coroutine` existed and returned a wrapper around coroutines only.
- **Updated Behaviour**:
  - `_wrap_reliability` inspects both `inner.coroutine` and `inner.func`, returning a `StructuredTool` with `coroutine=_wrapped` and `func=_wrapped_sync` (when sync function is present). Both paths evaluate `entitlement_denial(cfg, ctx)` before invoking the tool.
  - `materialize_tool` wraps builtin tools with `_wrap_reliability`. Read-only tools (`current_time`, `calculator`, `knowledge_search`, `recall`) are treated as idempotent; mutating/side-effecting tools (`remember`, `web_fetch`) are marked `idempotent=False` to prevent retry amplification.
- **Reason**: Ensure consistent authorization across all tool execution paths while protecting against unintended retries on state-mutating actions.

### 2. `backend/alberto/tools/mcp.py`
- **Component**: `load_mcp_tool`
- **Line Numbers**: ~576-598
- **Previous Behaviour**: Loaded MCP tools returned the underlying LangChain tool with context injection, bypassing `required_entitlements` validation.
- **Updated Behaviour**: If `cfg.get("required_entitlements")` is configured on an MCP tool, `load_mcp_tool` wraps invocation with `entitlement_denial(cfg, ctx)` before dispatching to the MCP client.
- **Reason**: Enforce authorization consistency on external tool bridges.

### 3. `backend/alberto/services/assistant.py`
- **Component**: `_assistant_model_ref`, `_default_agent_model`
- **Line Numbers**: ~175-185, ~830-860
- **Previous Behaviour**: Contained `_STRONG = {"openai": "openai:gpt-5.4", "anthropic": "anthropic:claude-sonnet-4-6"}`. If API keys existed in `provider_credentials`, `_assistant_model_ref` automatically fell back to cloud models without explicit user selection. `_default_agent_model` similarly invoked `default_model_for_credentials(resolved_keys)`.
- **Updated Behaviour**: Removed `_STRONG` dict and implicit credential fallback. Model selection strictly queries: (1) `project_config.assistant_model`, (2) `ctx.default_model_id`, (3) `ctx.default_model`, (4) `project_config.fallback_model`, (5) `settings.default_model`, or returns offline fake `"fake:offline"`.
- **Reason**: Cloud credentials must never grant implicit permission to route requests to cloud providers.

### 4. `backend/alberto/services/runtime.py`
- **Component**: `build_compile_context`
- **Line Numbers**: ~90-100
- **Previous Behaviour**: Evaluated `default_model_for_credentials(resolved_keys)` to automatically pick a cloud model if keys were available in the environment.
- **Updated Behaviour**: Uses only explicit project default model or `settings.default_model`.
- **Reason**: Prevent automatic promotion of cloud models over local configurations based on ambient environment keys.

### 5. `backend/alberto/engine/models.py`
- **Component**: `resolve_model`
- **Line Numbers**: ~80-110
- **Previous Behaviour**: If `model_ref` was empty, defaulted to `settings.default_model` without validating whether a model was configured or enabled. Unregistered models fell through silently.
- **Updated Behaviour**:
  - Resolves `model_ref` via registered context defaults, project `fallback_model`, and `settings.default_model`.
  - Raises explicit `ValueError("No model configured or available...")` if no model is defined.
  - If a model ID does not exist in `registered_models` (and is not an explicit provider ref like `openai:...`), raises `ValueError("Model '...' not found in model registry.")`.
- **Reason**: Fail closed with meaningful errors when models are missing or unconfigured.

### 6. `backend/alberto/config.py`
- **Component**: `Settings.dev_allow_anonymous_owner`, `validate_production`, `startup_warnings`
- **Line Numbers**: ~245-255, ~540-545, ~580-585
- **Previous Behaviour**: No configuration setting existed to govern anonymous privilege levels. `auth_required=False` unconditionally issued owner privileges.
- **Updated Behaviour**:
  - Added `dev_allow_anonymous_owner: bool = False`.
  - `validate_production()` enforces that `dev_allow_anonymous_owner` must be `False` in non-development environments.
  - `startup_warnings()` flags when `dev_allow_anonymous_owner` is active.
- **Reason**: Eliminate silent privilege escalation while allowing controlled local development shortcuts when explicitly requested.

### 7. `backend/alberto/deps.py`
- **Component**: `get_current_user`
- **Line Numbers**: ~95-120
- **Previous Behaviour**: When `auth_required` was `False`, returned `CurrentUser(id="system-dev", role="owner", email="you@forge.local")`.
- **Updated Behaviour**:
  - If `settings.enforce_security` is `True` (outside local dev), rejects unauthenticated requests with HTTP 401.
  - In development environments with `auth_required=False`, defaults anonymous callers to `CurrentUser(id="anonymous", role="viewer", email="anonymous@alberto.local")`.
  - Only returns `role="owner"` if `settings.dev_allow_anonymous_owner` is explicitly `True`.
  - Safely falls back to tenant resolution via active DB tenant or `"default"`.
- **Reason**: Enforce least privilege for unauthenticated local development access and reject anonymous requests in production.

---

## 3. Architectural Consistency

- **Separation of Concerns**: Kept tool security wrapping in `tools/materialize.py` and `tools/mcp.py`, model resolution in `engine/models.py` and `services/assistant.py`, configuration in `config.py`, and request authentication in `deps.py`.
- **Reusability**: Reused existing `entitlement_denial` logic across REST, Builtin, and MCP tools. Reused existing `role_at_least` hierarchy (`owner > admin > editor > viewer`) and existing `Settings.validate_production()` guard.
- **Duplication Eliminated**: Removed separate, ad-hoc fallback paths for cloud providers across assistant and runtime services.
- **No Unnecessary Abstractions**: No enterprise IAM, complex RBAC, or new permission frameworks were created. All checks utilize Alberto's existing entitlement and role schemas.
- **Dependency Boundaries**: Maintained clean dependency graph without circular imports. Preserved FastAPI dependency injection conventions.

---

## 4. Security Validation

Dedicated regression test suite implemented in `tests/backend/test_m1_security_hardening.py` covering:

### Tool Authorization
- `test_builtin_tool_entitlement_authorized`: Builtin tool executes normally when caller holds required entitlements.
- `test_builtin_tool_entitlement_unauthorized`: Builtin tool returns authorization denial string without running tool logic when caller lacks entitlement.
- `test_builtin_side_effect_prevented_when_unauthorized`: Memory write side-effect is prevented and not retried when unauthorized.
- `test_builtin_unconfigured_entitlements_preserves_permitted_behavior`: Builtin tools without specific entitlement requirements continue to execute without friction.
- `test_mcp_tool_entitlement_enforcement`: MCP tools with required entitlements reject unauthorized callers.

### Model Privacy
- `test_local_model_selected_while_cloud_credentials_exist`: Verifies local registered model is selected even when OpenAI and Anthropic API keys are populated in context.
- `test_explicit_cloud_model_selection`: Explicit cloud model references (e.g. `openai:gpt-4o`) remain functional with provider credentials.
- `test_missing_default_model_raises_meaningful_error`: Missing default model raises `ValueError` rather than falling back to cloud credentials.
- `test_disabled_model_raises_clear_error`: Disabled registered model or server raises a clear error.
- `test_no_unintended_cloud_fallback_when_credentials_exist_in_assistant`: Verifies `_assistant_model_ref` never selects cloud providers purely due to credentials.

### Anonymous Privilege Controls
- `test_anonymous_request_receives_viewer_role_when_auth_disabled`: Anonymous request in dev receives `role="viewer"` and is forbidden (HTTP 403) from administrative actions.
- `test_authenticated_owner_and_viewer_roles_respected`: Authenticated owner can perform admin operations; invited viewer is rejected with HTTP 403.
- `test_dev_allow_anonymous_owner_explicit_shortcut`: Setting `dev_allow_anonymous_owner = True` in dev grants owner role to anonymous callers.
- `test_production_mode_rejects_anonymous_even_if_dev_flag_set`: In production environments, anonymous requests are strictly rejected with HTTP 401.
- `test_production_validator_rejects_dev_shortcuts`: `validate_production()` flags `FORGE_DEV_ALLOW_ANONYMOUS_OWNER` as a fatal misconfiguration in production.

---

## 5. Test Results

### Focused Test Suite
- **Command**: `backend\.venv\Scripts\python.exe -m pytest tests\backend\test_m1_security_hardening.py -v`
- **Result**: `14 passed, 1 xfailed in 8.92s` (1 xfail is an expected vectorstore environment skip).

### Full Backend Regression Suite
- **Command**: `backend\.venv\Scripts\python.exe -m pytest tests\backend`
- **Baseline**: 578 passed, 8 skipped, 36 xfailed.
- **Current Result**: `592 passed, 8 skipped, 37 xfailed in 114.04s`
- **Regressions**: 0.

### Frontend Smoke & Unit Suite
- **Command**: `npm.cmd test -- --run` (in `frontend/`)
- **Baseline**: 4 passed.
- **Current Result**: `4 passed (4 tests in 1 test file, 7.37s)`

### Frontend Production Build
- **Command**: `npm.cmd run build` (in `frontend/`)
- **Result**: Compiled successfully, static pages generated, 0 errors.

---

## 6. Compatibility

- **Existing APIs**: Fully backward-compatible. REST endpoints maintain identical request/response schemas.
- **Household Authentication**: Multi-user household authentication and role checks (`owner`, `admin`, `editor`, `viewer`) operate without modification.
- **Model Registry**: Unified model registry remains authoritative; explicit selection of local or cloud models works seamlessly.
- **Tool Execution**: Preserves synchronous/asynchronous execution signatures and LangGraph runtime context injection.
- **Persistence Integrity**:
  - SQLite databases (`alberto.db`, `queue.sqlite`, `checkpoints.sqlite`): Unchanged and unreset.
  - Embedded ChromaDB collections: Preserved intact.
  - LangGraph durable checkpoints: Untouched and compatible.

---

## 7. Remaining Issues

- **Deferred to Later Milestones**:
  - Execution timeouts and recursion limits (Milestone 2/3).
  - Memory vectorstore testing in lightweight in-memory test runner (currently xfailed).
  - MCP stdio discovery optimizations.
  - Frontend UI settings for `fallback_model` configuration.

---

## 8. Reviewer Evidence

### Task A: Tool Authorization Gate in `backend/alberto/tools/materialize.py`
```python
    def _wrapped_sync(runtime: ToolRuntime | None = None, **kwargs):
        denial = entitlement_denial(cfg, ctx)
        if denial:
            return denial
        if rl and not rate_limiter.allow(f"tool:{tenant_id}:{name}", rate=int(rl), per=60):
            raise RuntimeError(f"tool {name!r} exceeded its rate limit ({rl}/min)")
        return inner_func(runtime=runtime, **kwargs) if pass_runtime else inner_func(**kwargs)

    return StructuredTool.from_function(
        func=_wrapped_sync if inner_func is not None else None,
        coroutine=_wrapped,
        name=inner.name,
        description=inner.description,
        args_schema=inner.args_schema,
    )
```

### Task B: Explicit Model Fallback in `backend/alberto/services/assistant.py`
```python
def _assistant_model_ref(ctx) -> str:
    pconfig = getattr(ctx, "project_config", None) or {}
    explicit = pconfig.get("assistant_model")
    if explicit:
        return explicit
    if getattr(ctx, "default_model_id", None):
        return ctx.default_model_id
    if getattr(ctx, "default_model", None):
        return ctx.default_model
    fallback = pconfig.get("fallback_model")
    if fallback:
        return fallback
    return getattr(settings, "default_model", None) or "fake:offline"
```

### Task C: Anonymous Access Privilege Restriction in `backend/alberto/deps.py`
```python
    if settings.enforce_security:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required outside development")

    tenant_id = getattr(request.app.state, "tenant_id", None)
    # ... tenant discovery ...
    tenant_id = tenant_id or "default"

    if settings.dev_allow_anonymous_owner:
        return CurrentUser(id="system-dev", tenant_id=tenant_id, role="owner", email="you@forge.local", is_fallback=True)

    return CurrentUser(id="anonymous", tenant_id=tenant_id, role="viewer", email="anonymous@alberto.local", is_fallback=True)
```

---

## 9. Changed File Manifest

### Modified Files
- `backend/alberto/config.py`
- `backend/alberto/deps.py`
- `backend/alberto/engine/models.py`
- `backend/alberto/services/assistant.py`
- `backend/alberto/services/runtime.py`
- `backend/alberto/tools/materialize.py`
- `backend/alberto/tools/mcp.py`

### Created Files
- `tests/backend/test_m1_security_hardening.py`
- `docs/reviews/ALBERTO_M1_IMPLEMENTATION_REPORT.md`

### Deleted Files
- None

---

## 10. Final Status

**COMPLETE**

All three tasks (Tool Authorization Consistency, Explicit Model Selection, Anonymous Authentication Privileges) are implemented, verified with focused regression tests, and confirmed regression-free against the full backend and frontend suites.

**Ready for ChatGPT Architectural Review**
