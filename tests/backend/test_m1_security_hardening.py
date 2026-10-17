"""Milestone 1: Security & Privacy Hardening Regression & Validation Suite.

Covers:
- Task A: Tool Authorization Consistency (builtin + MCP tools vs REST/SQL/Code)
- Task B: Explicit Model Selection (no unintended cloud model fallback from credentials)
- Task C: Anonymous Authentication Privileges (no silent owner escalation for anonymous callers)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from alberto.config import Settings, settings
from alberto.db.base import SessionLocal
from alberto.deps import CurrentUser, get_current_user
from alberto.engine.context import CompileContext
from alberto.engine.models import resolve_model
from alberto.main import create_app
from alberto.models import Memory, ModelServer, RegisteredModel
from alberto.services.assistant import _assistant_model_ref, _default_agent_model
from alberto.services.runtime import make_runtime_ctx
from alberto.tools import mcp as mcp_mod
from alberto.tools.materialize import entitlement_denial, materialize_tool
from alberto.tools.mcp import load_mcp_tool


# ============================================================================
# Task A: Tool Authorization Consistency
# ============================================================================


@pytest.mark.asyncio
async def test_builtin_tool_entitlement_authorized():
    """Authorized user possessing required entitlement can invoke builtin tool (sync & async)."""
    ctx = make_runtime_ctx("t_m1", "p_m1")
    ctx.end_user = {"id": "u_auth", "roles": ["family_member"], "entitlements": ["family_member"]}

    cfg = {
        "name": "calc",
        "kind": "builtin",
        "builtin": "calculator",
        "required_entitlements": ["family_member"],
    }
    tool = materialize_tool(cfg, ctx)

    # Async invocation
    res_async = await tool.ainvoke({"expression": "10 + 5"})
    assert res_async == "15"

    # Sync invocation preserves contract
    res_sync = tool.invoke({"expression": "20 + 7"})
    assert res_sync == "27"


@pytest.mark.asyncio
async def test_builtin_tool_entitlement_unauthorized():
    """Unauthorized user lacking required entitlement receives immediate denial message."""
    ctx = make_runtime_ctx("t_m1", "p_m1")
    ctx.end_user = {"id": "u_guest", "roles": ["guest"], "entitlements": []}

    cfg = {
        "name": "calc",
        "kind": "builtin",
        "builtin": "calculator",
        "required_entitlements": ["family_member"],
    }
    tool = materialize_tool(cfg, ctx)

    # Async rejection
    res_async = await tool.ainvoke({"expression": "10 + 5"})
    assert "Not permitted" in res_async
    assert "family_member" in res_async

    # Sync rejection
    res_sync = tool.invoke({"expression": "10 + 5"})
    assert "Not permitted" in res_sync
    assert "family_member" in res_sync


@pytest.mark.asyncio
async def test_builtin_side_effect_prevented_when_unauthorized():
    """Side-effecting builtin tools (e.g. remember) execute NO database writes when denied."""
    t_id = f"t_se_{uuid.uuid4().hex[:6]}"
    p_id = f"p_se_{uuid.uuid4().hex[:6]}"
    ctx = make_runtime_ctx(t_id, p_id)
    ctx.end_user = {"id": "u_unauth", "roles": ["guest"], "entitlements": []}

    cfg = {
        "name": "remember",
        "kind": "builtin",
        "builtin": "remember",
        "required_entitlements": ["family_member"],
    }
    tool = materialize_tool(cfg, ctx)

    secret_fact = "Vault code is 987654321"
    res = await tool.ainvoke({"text": secret_fact})
    assert "Not permitted" in res
    assert "family_member" in res

    # Verify no memory records were created in the database
    async with SessionLocal() as s:
        mems = (
            await s.execute(select(Memory).where(Memory.tenant_id == t_id, Memory.project_id == p_id))
        ).scalars().all()
        assert len(mems) == 0, "Rejected invocation must produce NO side effects in memory store"

    # Now verify that when authorized, the write actually occurs
    ctx.end_user = {"id": "u_auth", "roles": ["family_member"], "entitlements": ["family_member"]}
    auth_tool = materialize_tool(cfg, ctx)
    auth_res = await auth_tool.ainvoke({"text": secret_fact})
    assert "Saved to long-term memory" in auth_res

    async with SessionLocal() as s:
        mems = (
            await s.execute(select(Memory).where(Memory.tenant_id == t_id, Memory.project_id == p_id))
        ).scalars().all()
        assert len(mems) == 1
        assert mems[0].text == secret_fact


@pytest.mark.asyncio
async def test_builtin_unconfigured_entitlements_preserves_permitted_behavior():
    """Builtin tools without required_entitlements execute normally for all callers."""
    ctx = make_runtime_ctx("t_m1", "p_m1")
    ctx.end_user = None  # anonymous / unconfigured

    cfg = {"name": "time_tool", "kind": "builtin", "builtin": "current_time"}
    tool = materialize_tool(cfg, ctx)
    now_res = await tool.ainvoke({})
    assert "T" in now_res  # valid ISO timestamp


@pytest.mark.asyncio
async def test_mcp_tool_entitlement_enforcement(monkeypatch):
    """MCP tools also enforce the shared entitlement gate when required_entitlements are declared."""
    from langchain_core.tools import StructuredTool
    from alberto.models import McpClient

    async with SessionLocal() as s:
        row = McpClient(
            tenant_id="t_mcp_m1",
            project_id="p_mcp_m1",
            name="mcp_srv",
            transport="streamable_http",
            url="https://mcp.local/sse",
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        cid = row.id

    def fake_remote():
        async def _run(arg: str) -> str:
            return f"remote_{arg}"
        return StructuredTool.from_function(coroutine=_run, name="remote_fn", description="demo")

    monkeypatch.setattr(mcp_mod, "_client_and_tools", lambda *a, **k: _fake_mcp(fake_remote()))

    ctx = make_runtime_ctx("t_mcp_m1", "p_mcp_m1")
    ctx.end_user = {"id": "u_guest", "entitlements": []}

    cfg = {
        "mcp_client_id": cid,
        "remote_tool_name": "remote_fn",
        "required_entitlements": ["admin"],
    }
    tool = await mcp_mod.load_mcp_tool(cfg, ctx)
    denied = await tool.ainvoke({"arg": "test"})
    assert "Not permitted" in denied

    # Authorized user
    ctx.end_user = {"id": "u_admin", "entitlements": ["admin"]}
    tool_auth = await mcp_mod.load_mcp_tool(cfg, ctx)
    allowed = await tool_auth.ainvoke({"arg": "test"})
    assert allowed == "remote_test"


async def _fake_mcp(tool):
    return object(), [tool]


# ============================================================================
# Task B: Explicit Model Selection
# ============================================================================


@pytest.mark.asyncio
async def test_local_model_selected_while_cloud_credentials_exist():
    """Local configured model is strictly selected even when cloud provider credentials exist."""
    srv = ModelServer(
        id="srv_local",
        tenant_id="t_m1",
        name="Local Server",
        provider_type="ollama",
        base_url="http://localhost:11434",
        enabled=True,
    )
    reg = RegisteredModel(
        id="mod_local",
        tenant_id="t_m1",
        server_id="srv_local",
        model_name="llama3.2:latest",
        display_name="Local Llama",
        enabled=True,
    )
    ctx = CompileContext(
        tenant_id="t_m1",
        project_id="p_m1",
        default_model="mod_local",
        default_model_id="mod_local",
        registered_models={reg.id: reg},
        model_servers={srv.id: srv},
        # Cloud API credentials present in project context
        provider_credentials={"openai": "sk-proj-supersecretkey", "anthropic": "sk-ant-key"},
    )

    # 1. resolve_model(None, ctx) selects mod_local, not OpenAI or Anthropic
    llm = resolve_model(None, ctx)
    assert getattr(llm, "model_name", None) == "llama3.2:latest"

    # 2. _assistant_model_ref(ctx) selects configured default, NOT cloud _STRONG
    ref = _assistant_model_ref(ctx)
    assert ref == "mod_local"


@pytest.mark.asyncio
async def test_explicit_cloud_model_selection(monkeypatch):
    """Explicitly selecting a cloud model ref remains fully supported."""
    ctx = CompileContext(
        tenant_id="t_m1",
        project_id="p_m1",
        provider_credentials={"openai": "sk-test-key"},
    )

    mock_init = MagicMock()
    mock_model = MagicMock()
    mock_init.return_value = mock_model
    monkeypatch.setattr("langchain.chat_models.init_chat_model", mock_init)

    res = resolve_model("openai:gpt-4o", ctx)
    assert res == mock_model
    mock_init.assert_called_once()
    assert mock_init.call_args[0][0] == "openai:gpt-4o"
    assert mock_init.call_args[1].get("api_key") == "sk-test-key"


def test_missing_default_model_raises_meaningful_error():
    """When no model is specified and no default model exists, a meaningful error is returned."""
    ctx = CompileContext(
        tenant_id="t_m1",
        project_id="p_m1",
        default_model=None,
        default_model_id=None,
        # Credentials present without model config must NOT cause implicit fallback
        provider_credentials={"openai": "sk-test-key"},
    )
    # Monkeypatch settings to ensure default_model is None
    orig = settings.default_model
    try:
        settings.default_model = None
        with pytest.raises(ValueError, match="No model configured or available"):
            resolve_model(None, ctx)
    finally:
        settings.default_model = orig


@pytest.mark.asyncio
async def test_disabled_model_raises_clear_error():
    """Disabled registered model or disabled server raises clear RuntimeError."""
    srv = ModelServer(
        id="srv_off",
        tenant_id="t_m1",
        name="Off Server",
        provider_type="ollama",
        base_url="http://localhost:11434",
        enabled=False,
    )
    reg = RegisteredModel(
        id="mod_off",
        tenant_id="t_m1",
        server_id="srv_off",
        model_name="llama3.2:latest",
        display_name="Disabled Model",
        enabled=True,
    )
    ctx = CompileContext(
        tenant_id="t_m1",
        project_id="p_m1",
        registered_models={reg.id: reg},
        model_servers={srv.id: srv},
    )

    with pytest.raises(RuntimeError, match="disabled"):
        resolve_model("mod_off", ctx)


def test_no_unintended_cloud_fallback_when_credentials_exist_in_assistant():
    """_assistant_model_ref must never select cloud models solely because credentials exist.
    When no model is configured, it raises ValueError instead of silently falling back to fake:offline or cloud."""
    ctx = CompileContext(
        tenant_id="t_m1",
        project_id="p_m1",
        provider_credentials={"openai": "sk-leaked-key", "anthropic": "sk-anthropic-key"},
    )
    ctx.project_config = {}

    orig = settings.default_model
    try:
        settings.default_model = None
        # With no model configured and cloud credentials present, MUST raise ValueError
        with pytest.raises(ValueError, match="No model configured or available"):
            _assistant_model_ref(ctx)
    finally:
        settings.default_model = orig

    # Explicitly configured test model in isolated test environment is preserved
    ctx.project_config = {"assistant_model": "fake:test-assistant"}
    assert _assistant_model_ref(ctx) == "fake:test-assistant"



# ============================================================================
# Task C: Anonymous Authentication Privileges
# ============================================================================


@pytest.mark.asyncio
async def test_anonymous_request_receives_viewer_role_when_auth_disabled():
    """Unauthenticated requests receive the unprivileged 'viewer' role by default in dev."""
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        # Settings: auth_required = False, dev_allow_anonymous_owner = False
        orig_auth = settings.auth_required
        orig_dev_owner = settings.dev_allow_anonymous_owner
        try:
            settings.auth_required = False
            settings.dev_allow_anonymous_owner = False

            # Anonymous request to /v1/auth/me
            me_resp = await c.get("/v1/auth/me")
            assert me_resp.status_code == 200
            data = me_resp.json()
            assert data["role"] == "viewer", f"Expected unprivileged viewer role, got: {data['role']}"
            assert data["id"] == "anonymous"

            # Anonymous request to privileged admin endpoint (POST /v1/projects) MUST be forbidden
            proj_resp = await c.post("/v1/projects", json={"name": "Attacker Project"})
            assert proj_resp.status_code == 403
            assert "requires role 'admin' or higher" in proj_resp.text
        finally:
            settings.auth_required = orig_auth
            settings.dev_allow_anonymous_owner = orig_dev_owner


@pytest.mark.asyncio
async def test_authenticated_owner_and_viewer_roles_respected():
    """Authenticated owner can access admin endpoints; authenticated viewer is forbidden."""
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        owner_email = f"o_{uuid.uuid4().hex[:8]}@example.com"
        viewer_email = f"v_{uuid.uuid4().hex[:8]}@example.com"

        # Register owner
        reg = await c.post("/v1/auth/register", json={"email": owner_email, "password": "password123!"})
        assert reg.status_code == 201
        owner_token = reg.json()["access_token"]
        oh = {"Authorization": f"Bearer {owner_token}"}

        # Owner creates project -> succeeds
        p_resp = await c.post("/v1/projects", json={"name": "Owner Project"}, headers=oh)
        assert p_resp.status_code == 201

        # Owner invites viewer
        inv_resp = await c.post(
            "/v1/team/members",
            json={"email": viewer_email, "role": "viewer", "password": "password123!"},
            headers=oh,
        )
        assert inv_resp.status_code == 201

        # Log in as viewer
        v_login = await c.post("/v1/auth/login", json={"email": viewer_email, "password": "password123!"})
        assert v_login.status_code == 200
        vh = {"Authorization": f"Bearer {v_login.json()['access_token']}"}

        # Viewer tries to create project (admin requirement) -> 403 Forbidden
        v_proj = await c.post("/v1/projects", json={"name": "Viewer Project"}, headers=vh)
        assert v_proj.status_code == 403


@pytest.mark.asyncio
async def test_dev_allow_anonymous_owner_explicit_shortcut():
    """Explicitly enabling dev_allow_anonymous_owner in dev grants owner to anonymous."""
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        orig_auth = settings.auth_required
        orig_dev_owner = settings.dev_allow_anonymous_owner
        try:
            settings.auth_required = False
            settings.dev_allow_anonymous_owner = True

            me_resp = await c.get("/v1/auth/me")
            assert me_resp.status_code == 200
            assert me_resp.json()["role"] == "owner"
            assert me_resp.json()["id"] == "system-dev"
        finally:
            settings.auth_required = orig_auth
            settings.dev_allow_anonymous_owner = orig_dev_owner


@pytest.mark.asyncio
async def test_production_mode_rejects_anonymous_even_if_dev_flag_set():
    """Outside local dev, anonymous requests are strictly rejected with 401."""
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        orig_auth = settings.auth_required
        orig_env = settings.environment
        orig_dev_owner = settings.dev_allow_anonymous_owner
        try:
            settings.auth_required = False
            settings.environment = "production"
            settings.dev_allow_anonymous_owner = True  # Attempting dev shortcut in production

            me_resp = await c.get("/v1/auth/me")
            assert me_resp.status_code == 401
            assert "authentication required" in me_resp.text
        finally:
            settings.auth_required = orig_auth
            settings.environment = orig_env
            settings.dev_allow_anonymous_owner = orig_dev_owner


def test_production_validator_rejects_dev_shortcuts():
    """validate_production() flags dev_allow_anonymous_owner as fatal misconfiguration."""
    s = Settings(
        environment="production",
        jwt_secret="strong-production-secret-1234567890",
        bootstrap_admin_password="strong-production-admin-password-1234567890",
        auth_required=True,
        dev_allow_anonymous_owner=True,
        trusted_hosts=["alberto.home"],
        public_base_url="https://alberto.home",
        public_console_url="https://alberto.home",
    )
    problems = s.validate_production()
    assert any("FORGE_DEV_ALLOW_ANONYMOUS_OWNER" in p for p in problems)


def test_entitlement_denial_fails_closed_when_context_lacks_checker():
    """When a tool requires entitlements, entitlement_denial fails closed if ctx is None or lacks has_entitlements."""
    cfg = {"required_entitlements": ["family:adult"]}
    # None context
    assert "Not permitted" in entitlement_denial(cfg, None)
    # Context without has_entitlements
    assert "Not permitted" in entitlement_denial(cfg, object())
    # Context with uncallable has_entitlements
    assert "Not permitted" in entitlement_denial(cfg, type("BadCtx", (), {"has_entitlements": "not_a_func"})())


@pytest.mark.asyncio
async def test_mcp_tool_sync_entitlement_enforcement(monkeypatch):
    """MCP tools with required_entitlements enforce denial on synchronous .invoke() as well."""
    from langchain_core.tools import StructuredTool

    inner_mock = MagicMock(return_value="inner called")

    def sync_fn(query: str = "") -> str:
        return inner_mock(query=query)

    raw_mcp_tool = StructuredTool.from_function(
        func=sync_fn,
        name="test_mcp_sync",
        description="Sync MCP test tool",
    )

    from alberto.models import McpClient

    async with SessionLocal() as s:
        row = McpClient(
            tenant_id="t_m1",
            project_id="p_m1",
            name="mcp_srv_sync",
            transport="streamable_http",
            url="https://mcp.local/sse",
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        cid = row.id

    monkeypatch.setattr(mcp_mod, "_client_and_tools", lambda *a, **k: _fake_mcp(raw_mcp_tool))

    cfg = {
        "mcp_client_id": cid,
        "remote_tool_name": "test_mcp_sync",
        "required_entitlements": ["admin:tools"],
    }

    ctx_unauth = make_runtime_ctx("t_m1", "p_m1")
    ctx_unauth.end_user = {"id": "u1", "entitlements": ["viewer"]}
    tool = await mcp_mod.load_mcp_tool(cfg, ctx_unauth)

    # Sync invocation MUST be denied and not call inner
    res = tool.invoke({"query": "hello"})
    assert "Not permitted" in str(res)
    inner_mock.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_startup_enforces_production_validation():
    """lifespan(app) in main.py must raise RuntimeError if started with unsafe production settings."""
    from alberto.main import lifespan
    app = create_app()

    orig_env = settings.environment
    orig_dev_owner = settings.dev_allow_anonymous_owner
    try:
        settings.environment = "production"
        settings.dev_allow_anonymous_owner = True

        with pytest.raises(RuntimeError, match="Unsafe production configuration"):
            async with lifespan(app):
                pass
    finally:
        settings.environment = orig_env
        settings.dev_allow_anonymous_owner = orig_dev_owner


@pytest.mark.asyncio
async def test_default_agent_model_raises_meaningful_error():
    """_default_agent_model raises ValueError when no model is configured anywhere."""
    from alberto.services.assistant import _default_agent_model

    orig = settings.default_model
    try:
        settings.default_model = None
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="No model configured or available"):
            await _default_agent_model(mock_session, "t_m1", "p_m1")
    finally:
        settings.default_model = orig

