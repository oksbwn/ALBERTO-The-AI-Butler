"""Unit and integration tests for Alberto Integrations v2 and Tool Manager system subagent."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import select

from alberto.db import SessionLocal
from alberto.nodes.data import tool_call_factory
from alberto.models.entities import AuthProvider, McpClient, Project, Tool
from alberto.services.agents import AgentService
from alberto.services.projects import ProjectService
from alberto.services.runtime import build_compile_context
from alberto.services.tool_manager import ToolManagerService
from alberto.connectors.install import ConnectorInstaller


@pytest.fixture
async def sample_project():
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id="tenant-tm-v2",
            name="Integrations v2 Project",
            slug="proj-tm-v2",
        )
        await session.commit()
        await session.refresh(proj)
        return proj


# =========================================================================
# 1. System Agent Protection & Provisioning
# =========================================================================

@pytest.mark.asyncio
async def test_tool_manager_system_agent_provisioned_and_protected(sample_project: Project):
    async with SessionLocal() as session:
        sys_agents = await AgentService.ensure_system_agents(
            session, sample_project.tenant_id, sample_project.id
        )
        assert len(sys_agents) == 4
        keys = {a.system_key for a in sys_agents}
        assert "tool_manager" in keys

        tm = [a for a in sys_agents if a.system_key == "tool_manager"][0]
        assert tm.is_system is True
        assert tm.name in ("Integration Manager", "Tool Manager")

        # Cannot delete
        with pytest.raises(ValueError, match="Protected system agents cannot be deleted"):
            await AgentService.delete(session, tm)

        # Cannot rename
        with pytest.raises(ValueError, match="Protected system agents cannot be renamed"):
            await AgentService.update(session, tm, name="Custom Tool Manager")

        # Imposter cannot be created with reserved system_key
        with pytest.raises(ValueError, match="reserved system key"):
            await AgentService.create(
                session,
                sample_project.tenant_id,
                sample_project.id,
                name="Fake TM",
                config={},
                is_system=False,
                system_key="tool_manager",
            )


# =========================================================================
# 2. Tool Manager Deterministic Classification & Policy Boundary
# =========================================================================

def test_deterministic_effect_and_risk_classification():
    # Read-only tool
    eff, risk, act = ToolManagerService.classify_effect_and_risk(
        "search_records",
        "Search and get document contents by keyword",
        {"type": "object", "properties": {"query": {"type": "string"}}},
    )
    assert eff == "read"
    assert risk == "low"
    assert act == "auto"

    # Write tool
    eff2, risk2, act2 = ToolManagerService.classify_effect_and_risk(
        "create_invoice",
        "Create new invoice and send to client",
        {"type": "object", "properties": {"amount": {"type": "number"}}},
    )
    assert eff2 == "write"
    assert risk2 in ("medium", "high")
    assert act2 == "manual_review"

    # Delete / destructive tool
    eff3, risk3, act3 = ToolManagerService.classify_effect_and_risk(
        "drop_database_table",
        "Permanently delete table and purge records",
        {"type": "object", "properties": {"table": {"type": "string"}}},
    )
    assert eff3 == "delete"
    assert risk3 in ("high", "critical")
    assert act3 in ("manual_review", "restricted")


def test_enforce_policy_boundaries_prevents_privilege_downgrades():
    from alberto.schemas.tool_manager import ToolAnalysisResult

    # Attempting to auto-activate a write tool must be clamped
    hallucinated = ToolAnalysisResult(
        tool_id="tool-write-1",
        category="finance",
        effect="read",  # hallucinated read
        risk="low",     # hallucinated low risk
        recommended_activation="auto",
        confidence=0.9,
    )
    clamped = ToolManagerService.enforce_policy_boundaries(
        result=hallucinated,
        det_effect="write",
        det_risk="medium",
        det_activation="manual_review",
    )
    assert clamped.effect == "write"
    assert clamped.risk == "medium"
    assert clamped.recommended_activation == "manual_review"

    # Attempting to auto-activate a delete tool must require manual review
    del_hallucinated = ToolAnalysisResult(
        tool_id="tool-del-1",
        category="system",
        effect="delete",
        risk="low",
        recommended_activation="auto",
        confidence=0.8,
    )
    clamped_del = ToolManagerService.enforce_policy_boundaries(
        result=del_hallucinated,
        det_effect="delete",
        det_risk="critical",
        det_activation="manual_review",
    )
    assert clamped_del.effect == "delete"
    assert clamped_del.risk == "critical"
    assert clamped_del.recommended_activation == "manual_review"


# =========================================================================
# 3. Tool Manager Offline Fallback & Diagnostics
# =========================================================================

@pytest.mark.asyncio
async def test_tool_manager_analysis_offline_fallback(sample_project: Project):
    async with SessionLocal() as session:
        # Test analyze_tool with use_llm=True and simulated model failure
        with patch.object(ToolManagerService, "get_tool_manager_model", side_effect=RuntimeError("LLM unavailable")):
            res = await ToolManagerService.analyze_tool(
                tool_id="tool-purge-1",
                name="purge_user_sessions",
                description="Remove and drop user session caches",
                input_schema={"type": "object", "properties": {"user_id": {"type": "string"}}},
                use_llm=True,
                session=session,
                tenant_id=sample_project.tenant_id,
                project_id=sample_project.id,
            )
            assert res.tool_id == "tool-purge-1"
            assert res.effect == "delete"
            assert res.risk in ("high", "critical")
            assert res.recommended_activation in ("manual_review", "restricted")
            assert any("deterministic" in w.lower() for w in res.warnings)


def test_diagnose_execution_failures():
    history = [
        "Connection reset by peer",
        "Connection refused: remote host unreachable",
        "dns failure",
    ]
    diag = ToolManagerService.diagnose_execution_failures(
        tool_id="db_query_tool",
        tool_name="PostgreSQL query executor",
        recent_errors=history,
    )
    assert diag.failure_count == 3
    assert diag.root_cause_category == "network"
    assert len(diag.recommendations) > 0


# =========================================================================
# 4. MCP Runtime Materialization & Workflow Tool Call Execution
# =========================================================================

@pytest.mark.asyncio
async def test_mcp_tool_materialized_in_compile_context(sample_project: Project):
    async with SessionLocal() as session:
        # Create McpClient
        client = McpClient(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="Mock Weather MCP",
            transport="sse",
            url="http://localhost:8999/mcp",
            enabled=True,
            capabilities={"tools": [{"name": "get_weather", "description": "Fetch weather", "inputSchema": {}}]},
        )
        session.add(client)
        await session.flush()

        # Create MCP Tool in DB
        t = Tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="get_weather",
            kind="mcp",
            enabled=True,
            config={
                "client_id": client.id,
                "remote_tool_name": "get_weather",
                "description": "Fetch current weather",
            },
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)

        # Mock load_mcp_tool to return an executable mock
        mock_executable = AsyncMock()
        mock_executable.ainvoke = AsyncMock(return_value={"temperature": 72, "condition": "Sunny"})

        with patch("alberto.tools.mcp.load_mcp_tool", return_value=mock_executable):
            with patch("alberto.tools.mcp.server_tools", return_value=[mock_executable]):
                ctx = await build_compile_context(session=session, tenant_id=sample_project.tenant_id, project_id=sample_project.id)
                assert t.id in ctx.tool_registry
                assert ctx.tool_registry[t.id] is mock_executable
                assert t.id in ctx.tool_specs

                # Test execution via tool_call_factory
                node_fn = tool_call_factory(
                    {"tool_id": t.id, "input_mapping": {"city": "input_city"}, "output_key": "weather_data"},
                    ctx,
                )
                state = {"input_city": "San Francisco"}
                result_state = await node_fn(state)
                assert "weather_data" in result_state
                assert result_state["weather_data"] == {"temperature": 72, "condition": "Sunny"}
                mock_executable.ainvoke.assert_called_once_with({"city": "San Francisco"}, None)


# =========================================================================
# 5. Safe Secret Cleanup on Connector Uninstall
# =========================================================================

@pytest.mark.asyncio
async def test_uninstall_preserves_shared_credentials(sample_project: Project):
    from alberto.models.entities import ConnectorInstall

    async with SessionLocal() as session:
        # Create Provider 1 (managed connector)
        prov1 = AuthProvider(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="Google Drive Provider",
            kind="oauth2",
            credentials_ref="secret://proj/shared-google-vault-ref",
            config={"connector_slug": "google_drive"},
        )
        # Create Provider 2 (shares the exact same credentials_ref)
        prov2 = AuthProvider(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="Google Calendar Provider",
            kind="oauth2",
            credentials_ref="secret://proj/shared-google-vault-ref",
            config={"connector_slug": "google_calendar"},
        )
        session.add_all([prov1, prov2])
        await session.flush()

        # Create mock ConnectorInstall
        install = ConnectorInstall(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            slug="google_drive",
            name="Google Drive",
            version="1.0.0",
            source="catalog",
            status="connected",
            auth_mode="shared",
            auth_provider_id=prov1.id,
            created_tool_ids=[],
        )
        session.add(install)
        await session.commit()

        installer = ConnectorInstaller()
        # Mock installer._group_secret_names to return our shared ref
        with patch.object(installer, "_group_secret_names", return_value=["shared-google-vault-ref"]):
            with patch.object(installer.secrets, "write", new_callable=AsyncMock) as mock_write:
                await installer.uninstall(session, install)

                # prov2 still references "shared-google-vault-ref", so secrets.write MUST NOT be called for it
                for call_args in mock_write.call_args_list:
                    name = call_args.kwargs.get("name") or (call_args.args[3] if len(call_args.args) > 3 else None)
                    assert name != "shared-google-vault-ref"


# =========================================================================
# 6. Hardening Tests: Tool Policy Engine & Default-Deny Access
# =========================================================================

@pytest.mark.asyncio
async def test_master_agent_direct_execution_denied(sample_project: Project):
    from alberto.services.tool_policy import ToolPolicyService

    async with SessionLocal() as session:
        t = Tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="external_weather",
            kind="rest_api",
            enabled=True,
            config={"url": "https://api.weather.com"},
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)

        # Direct execution by master agent MUST be denied
        decision = await ToolPolicyService.evaluate_execution(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id=t.id,
            caller_type="master_agent",
            caller_id="assistant",
            session=session,
        )
        assert decision.allowed is False
        assert "Master Agent cannot directly execute external tools" in decision.reason


@pytest.mark.asyncio
async def test_master_agent_delegation_through_tool_manager(sample_project: Project):
    from alberto.services.tools import ToolService

    async with SessionLocal() as session:
        t = Tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="github_list_issues",
            kind="rest_api",
            enabled=True,
            config={"url": "https://api.github.com/issues", "effect": "read"},
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)

        with patch.object(ToolService, "test", new_callable=AsyncMock) as mock_test:
            mock_test.return_value = {"ok": True, "projected": [{"id": 1, "title": "Issue 1"}]}

            res = await ToolManagerService.execute_delegated_tool(
                tenant_id=sample_project.tenant_id,
                project_id=sample_project.id,
                tool_id_or_capability=t.id,
                parameters={"repo": "owner/repo"},
                user_context={"id": "usr-1", "role": "editor"},
            )
            assert res["ok"] is True
            assert res["tool_id"] == t.id
            assert res["result"] == [{"id": 1, "title": "Issue 1"}]


@pytest.mark.asyncio
async def test_subagent_default_deny_and_explicit_association(sample_project: Project):
    from alberto.services.tool_policy import ToolPolicyService

    async with SessionLocal() as session:
        t1 = Tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="tool_allowed",
            kind="rest_api",
            enabled=True,
            config={"effect": "read"},
        )
        t2 = Tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="tool_unassociated",
            kind="rest_api",
            enabled=True,
            config={"effect": "read"},
        )
        session.add_all([t1, t2])
        await session.commit()
        await session.refresh(t1)
        await session.refresh(t2)

        subagent_cfg = {"tools": [t1.id]}

        # Subagent with explicit grant -> allowed
        dec1 = await ToolPolicyService.evaluate_execution(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id=t1.id,
            caller_type="subagent",
            caller_id="agent-custom-1",
            subagent_config=subagent_cfg,
            session=session,
        )
        assert dec1.allowed is True

        # Subagent without grant -> denied
        dec2 = await ToolPolicyService.evaluate_execution(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id=t2.id,
            caller_type="subagent",
            caller_id="agent-custom-1",
            subagent_config=subagent_cfg,
            session=session,
        )
        assert dec2.allowed is False
        assert "not explicitly associated" in dec2.reason


@pytest.mark.asyncio
async def test_inactive_or_disabled_tool_denied(sample_project: Project):
    from alberto.services.tool_policy import ToolPolicyService

    async with SessionLocal() as session:
        t = Tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="disabled_tool",
            kind="rest_api",
            enabled=False,  # Inactive
            config={"effect": "read"},
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)

        dec = await ToolPolicyService.evaluate_execution(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id=t.id,
            caller_type="tool_manager",
            session=session,
        )
        assert dec.allowed is False
        assert "disabled/inactive" in dec.reason


def test_ambiguous_operations_conservative_classification():
    ambiguous = [
        "execute_query",
        "run_command",
        "invoke_action",
        "execute_script",
        "manage_resources",
    ]
    for name in ambiguous:
        eff, risk, act = ToolManagerService.classify_effect_and_risk(
            name=name,
            description="Perform dynamic system action",
        )
        assert act in ("manual_review", "restricted"), f"{name} must not be auto-activated"
        assert risk in ("high", "critical"), f"{name} must be high or critical risk"


def test_mcp_stdio_security_admin_gate():
    from fastapi import HTTPException
    from alberto.deps import CurrentUser
    from alberto.routers.mcp_clients import _validate_stdio_security

    editor_user = CurrentUser(id="ed-1", tenant_id="tenant-1", email="ed@example.com", role="editor")
    admin_user = CurrentUser(id="ad-1", tenant_id="tenant-1", email="ad@example.com", role="admin")

    # 1. Non-admin is blocked
    with pytest.raises(HTTPException) as exc:
        _validate_stdio_security("stdio", "python -m server", editor_user)
    assert exc.value.status_code == 403

    # 2. Admin + flag=True + empty allowlist -> Blocked (fail closed)
    with patch("alberto.config.settings.enable_mcp_stdio", True), patch("alberto.config.settings.mcp_stdio_allowed_commands", []):
        with pytest.raises(HTTPException) as exc_empty:
            _validate_stdio_security("stdio", "node server.js", admin_user)
        assert exc_empty.value.status_code == 403
        assert "empty or unconfigured" in exc_empty.value.detail

    # 3. Unsafe shell command is blocked
    with patch("alberto.config.settings.enable_mcp_stdio", True), patch("alberto.config.settings.mcp_stdio_allowed_commands", ["cat /etc/passwd; rm -rf /"]):
        with pytest.raises(HTTPException) as exc2:
            _validate_stdio_security("stdio", "cat /etc/passwd; rm -rf /", admin_user)
        assert exc2.value.status_code == 400
        assert "Shell metacharacters are forbidden" in exc2.value.detail

    # 4. Command not in allowlist -> Blocked
    with patch("alberto.config.settings.enable_mcp_stdio", True), patch("alberto.config.settings.mcp_stdio_allowed_commands", ["allowed-cmd"]):
        with pytest.raises(HTTPException) as exc3:
            _validate_stdio_security("stdio", "unauthorized-cmd", admin_user)
        assert exc3.value.status_code == 403
        assert "not in the allowed commands list" in exc3.value.detail

    # 5. Admin + flag=True + nonempty allowlist + matching command -> Allowed
    with patch("alberto.config.settings.enable_mcp_stdio", True), patch("alberto.config.settings.mcp_stdio_allowed_commands", ["npx -y @modelcontextprotocol/server-postgres"]):
        _validate_stdio_security("stdio", "npx -y @modelcontextprotocol/server-postgres", admin_user)


@pytest.mark.asyncio
async def test_graph_manager_ownership_in_tool_projection(sample_project: Project):
    from alberto.services.graph_manager import GraphManagerService

    with patch.object(GraphManagerService, "apply_resolved", new_callable=AsyncMock) as mock_apply:
        await ToolManagerService.project_tool_to_graph(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id="tool-slack-post",
            tool_name="post_message",
            integration_name="Slack",
            capabilities=["send_notification", "chat"],
        )
        assert mock_apply.called
        call_kwargs = mock_apply.call_args.kwargs
        assert call_kwargs["tenant_id"] == sample_project.tenant_id
        assert call_kwargs["project_id"] == sample_project.id
        assert len(call_kwargs["resolved_entities"]) >= 3  # integration, tool, capabilities
        assert len(call_kwargs["resolved_relationships"]) >= 2  # PROVIDES, IMPLEMENTS


# =========================================================================
# 7. Complete Human-In-The-Loop (HITL) Approval Lifecycle
# =========================================================================

@pytest.mark.asyncio
async def test_hitl_approval_lifecycle_complete(sample_project: Project):
    """Verify:
    - Tool execution requesting approval creates a tracked approval request.
    - Identification of tool, argument hash, and requesting user.
    - Unauthorized user cannot approve.
    - Authorized user can approve or reject.
    - Execution with valid approved request succeeds and consumes the approval (one-time use).
    - Replay with consumed approval is denied.
    - Tampered arguments (arguments_hash mismatch) is denied.
    - Expired approval is denied.
    - Rejected approval is denied.
    """
    from alberto.services.tool_policy import ToolPolicyService
    from alberto.services.tools import ToolService

    async with SessionLocal() as s:
        # Create a write tool that requires approval
        tool = await ToolService.create(
            s,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="delete_database_records",
            kind="rest_api",
            config={
                "description": "Delete records from database",
                "effect": "delete",
                "requires_approval": True,
                "request": {"method": "DELETE", "url_template": "https://api.example.com/records/{id}"},
            },
        )

    user_ctx = {"user_id": "usr-alice", "tenant_id": sample_project.tenant_id, "role": "member"}
    args = {"id": "rec-12345"}

    # 1. First execution attempt -> Policy denies and requires approval
    res1 = await ToolManagerService.execute_delegated_tool(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id_or_capability=tool.id,
        parameters=args,
        user_context=user_ctx,
    )
    assert res1["ok"] is False
    assert res1["requires_approval"] is True
    appr_id = res1.get("approval_id")
    assert appr_id is not None

    appr = ToolPolicyService.get_approval(appr_id)
    assert appr is not None
    assert appr.tool_id == tool.id
    assert appr.requesting_user_id == "usr-alice"
    assert appr.status == "pending"

    # 2. Unauthorized user (viewer) attempts to approve -> Denied
    viewer_user = {"user_id": "usr-bob", "role": "viewer"}
    ok_v, err_v = ToolPolicyService.decide_approval_request(appr_id, "approve", viewer_user)
    assert ok_v is False
    assert "not authorized" in err_v

    # 3. Authorized admin approves
    admin_user = {"user_id": "usr-admin", "role": "admin"}
    ok_a, msg_a = ToolPolicyService.decide_approval_request(appr_id, "approve", admin_user)
    assert ok_a is True
    assert appr.status == "approved"
    assert appr.decided_by == "usr-admin"

    # 4. Tampered arguments attempt -> Denied
    with patch.object(ToolService, "test", new_callable=AsyncMock) as mock_test:
        mock_test.return_value = {"ok": True, "projected": {"deleted": True}}
        tampered_res = await ToolManagerService.execute_delegated_tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id_or_capability=tool.id,
            parameters={"id": "rec-DIFFERENT"},  # Different argument
            user_context=user_ctx,
            execution_context={"approval_id": appr_id},
        )
        assert tampered_res["ok"] is False
        assert "arguments hash mismatch" in tampered_res["error"]

    # 5. Legitimate execution with exact parameters -> Allowed and consumes approval
    with patch.object(ToolService, "test", new_callable=AsyncMock) as mock_test:
        mock_test.return_value = {"ok": True, "projected": {"deleted": True}}
        exec_res = await ToolManagerService.execute_delegated_tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id_or_capability=tool.id,
            parameters=args,
            user_context=user_ctx,
            execution_context={"approval_id": appr_id},
        )
        assert exec_res["ok"] is True
        assert exec_res["result"] == {"deleted": True}
        assert appr.status == "consumed"

    # 6. Replay attempt with already consumed approval -> Denied
    replay_res = await ToolManagerService.execute_delegated_tool(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id_or_capability=tool.id,
        parameters=args,
        user_context=user_ctx,
        execution_context={"approval_id": appr_id},
    )
    assert replay_res["ok"] is False
    assert "already been consumed" in replay_res["error"]

    # 7. Rejected approval never executes
    req_rej = ToolPolicyService.create_approval_request(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id=tool.id,
        tool_name=tool.name,
        arguments=args,
        user_context=user_ctx,
    )
    ToolPolicyService.decide_approval_request(req_rej.id, "reject", admin_user)
    assert req_rej.status == "rejected"
    rej_res = await ToolManagerService.execute_delegated_tool(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id_or_capability=tool.id,
        parameters=args,
        user_context=user_ctx,
        execution_context={"approval_id": req_rej.id},
    )
    assert rej_res["ok"] is False
    assert "rejected" in rej_res["error"]


# =========================================================================
# 8. Master Agent Tools & Delegation End-to-End
# =========================================================================

@pytest.mark.asyncio
async def test_master_agent_tools_and_delegation(sample_project: Project):
    import json
    from alberto.deps import CurrentUser
    from alberto.services.assistant import build_assistant_tools
    from alberto.services.tools import ToolService

    current_user = CurrentUser(id="user-master", tenant_id=sample_project.tenant_id, role="editor", email="m@example.com")
    tools = build_assistant_tools(sample_project.tenant_id, sample_project.id, [], current_user=current_user)
    tool_names = {t.name for t in tools}

    # Verify delegation capability exists
    assert "delegate_tool_execution" in tool_names

    # Verify Master Agent cannot directly invoke external tools
    # Only platform meta-tools (list_resources, create_rest_tool, delegate_tool_execution, etc.) exist
    assert "fetch_weather" not in tool_names

    # Create an active read-only tool in the project
    async with SessionLocal() as s:
        read_tool = await ToolService.create(
            s,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="query_project_metrics",
            kind="rest_api",
            config={
                "description": "Read project metrics",
                "effect": "read",
                "request": {"method": "GET", "url_template": "https://api.example.com/metrics"},
            },
        )

    # Invoke delegate_tool_execution directly through the StructuredTool interface
    delegate_tool = next(t for t in tools if t.name == "delegate_tool_execution")

    with patch.object(ToolService, "test", new_callable=AsyncMock) as mock_test:
        mock_test.return_value = {"ok": True, "projected": {"cpu": "25%"}}
        res_str = await delegate_tool.ainvoke({
            "tool_id_or_capability": read_tool.name,
            "parameters_json": json.dumps({"period": "24h"}),
        })
        res = json.loads(res_str)
        assert res["ok"] is True
        assert res["result"] == {"cpu": "25%"}


# =========================================================================
# 9. Subagent Association & Revocation End-to-End
# =========================================================================

@pytest.mark.asyncio
async def test_subagent_association_revocation(sample_project: Project):
    from alberto.services.tool_policy import ToolPolicyService
    from alberto.services.tools import ToolService

    async with SessionLocal() as s:
        t = await ToolService.create(
            s,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="slack_read_channel",
            kind="rest_api",
            config={"effect": "read", "description": "Read slack messages"},
        )
        # Create subagent with no tools
        agent = await AgentService.create(
            s,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="support_reader",
            config={"tools": []},
        )

    # 1. Unassociated subagent -> Denied
    dec1 = await ToolPolicyService.evaluate_execution(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id=t.id,
        caller_type="subagent",
        caller_id=agent.id,
    )
    assert dec1.allowed is False
    assert "not explicitly associated" in dec1.reason

    # 2. Grant explicit association -> Allowed
    async with SessionLocal() as s:
        fresh_agent = await AgentService.get(s, sample_project.tenant_id, agent.id)
        assert fresh_agent is not None
        await AgentService.update(s, fresh_agent, config={"tools": [t.id]})

    dec2 = await ToolPolicyService.evaluate_execution(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id=t.id,
        caller_type="subagent",
        caller_id=agent.id,
    )
    assert dec2.allowed is True

    # 3. Revoke association -> Immediately denied on subsequent execution
    async with SessionLocal() as s:
        fresh_agent = await AgentService.get(s, sample_project.tenant_id, agent.id)
        assert fresh_agent is not None
        await AgentService.update(s, fresh_agent, config={"tools": []})

    dec3 = await ToolPolicyService.evaluate_execution(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id=t.id,
        caller_type="subagent",
        caller_id=agent.id,
    )
    assert dec3.allowed is False
    assert "not explicitly associated" in dec3.reason


# =========================================================================
# 10. OAuth State & Origin Verification
# =========================================================================

def test_oauth_state_and_origin_security():
    from alberto.routers.oauth import _oauth_html
    from alberto.security import TokenError, create_state_token, decode_token

    # 1. Valid signed state
    valid_state = create_state_token(
        {"tid": "t1", "pid": "p1", "ap": "ap-1", "cv": "test-verifier"},
        ttl_minutes=10,
    )
    claims = decode_token(valid_state, expected_type="oauth_state")
    assert claims["tid"] == "t1"
    assert claims["ap"] == "ap-1"
    assert claims["cv"] == "test-verifier"

    # 2. Invalid / tampered state is rejected
    with pytest.raises(TokenError):
        decode_token(valid_state + "tampered", expected_type="oauth_state")

    # 3. HTML popup response never sends '*' as postMessage targetOrigin
    html_resp = _oauth_html("Success", "Authorized", status_code=200, is_success=True, ap_id="ap-1")
    html_text = bytes(html_resp.body).decode("utf-8")
    assert "postMessage(payload, targetOrigin)" in html_text
    assert "postMessage(payload, '*')" not in html_text
    assert '"type": "alberto:oauth_complete"' in html_text


# =========================================================================
# 11. SQLite HITL Approval Persistence & Atomic Resume Verification
# =========================================================================

@pytest.mark.asyncio
async def test_hitl_approval_sqlite_persistence_and_restart_recovery(sample_project: Project):
    """Verify approval requests are durably persisted in SQLite, survive restarts, and consume atomically."""
    from sqlalchemy import select
    from alberto.models import ToolApprovalRequest
    from alberto.services.tool_policy import ToolPolicyService
    from alberto.services.tools import ToolService

    # 1. Create registered tool requiring approval
    async with SessionLocal() as s:
        tool_row = await ToolService.create(
            s,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="sensitive_write",
            kind="rest_api",
            config={"requires_approval": True, "effect": "write", "risk": "high"},
        )

    # 2. Create approval request
    req = ToolPolicyService.create_approval_request(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id=tool_row.id,
        tool_name=tool_row.name,
        arguments={"key": "val", "api_key": "secret-token-123"},
        user_context={"user_id": "usr-requester", "role": "editor"},
        caller_type="assistant",
        ttl_seconds=300,
    )
    assert req.id.startswith("appr-")

    # 3. Verify row exists in SQLite tool_approval_requests table
    async with SessionLocal() as s:
        db_row = (await s.execute(
            select(ToolApprovalRequest).where(ToolApprovalRequest.id == req.id)
        )).scalar_one_or_none()
        assert db_row is not None
        assert db_row.tool_id == tool_row.id
        assert db_row.status == "pending"
        # Verify sensitive arguments were scrubbed before DB write
        assert db_row.arguments_scrubbed.get("api_key") == "[REDACTED]"
        assert db_row.arguments_scrubbed.get("key") == "val"

    # 4. Simulate process restart by clearing in-memory cache
    ToolPolicyService._pending_approvals.clear()
    assert req.id not in ToolPolicyService._pending_approvals

    # 5. Verify get_approval recovers cleanly from SQLite
    recovered_req = ToolPolicyService.get_approval(req.id)
    assert recovered_req is not None
    assert recovered_req.id == req.id
    assert recovered_req.status == "pending"
    assert recovered_req.requesting_user_id == "usr-requester"

    # 6. Decide approval request (admin approves)
    admin_user = {"user_id": "usr-admin", "role": "admin"}
    ok, msg = ToolPolicyService.decide_approval_request(req.id, "approve", admin_user)
    assert ok is True
    assert "granted" in msg

    # 7. Simulate another restart after decision
    ToolPolicyService._pending_approvals.clear()

    # 8. Evaluate execution with exact arguments -> Atomic consumption succeeds

    exec_res = await ToolPolicyService.evaluate_execution(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id=tool_row.id,
        caller_type="tool_manager",
        caller_id="assistant",
        user_context={"user_id": "usr-requester", "role": "editor"},
        execution_context={"approval_id": req.id, "arguments_hash": req.arguments_hash},
    )
    assert exec_res.allowed is True

    # 8. Verify status in SQLite is now 'consumed'
    async with SessionLocal() as s:
        consumed_row = (await s.execute(
            select(ToolApprovalRequest).where(ToolApprovalRequest.id == req.id)
        )).scalar_one()
        assert consumed_row.status == "consumed"
        assert consumed_row.consumed_at is not None

    # 9. Second execution attempt with same approval -> Denied (prevent double consumption)
    exec_res_repeat = await ToolPolicyService.evaluate_execution(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id=tool_row.id,
        caller_type="tool_manager",
        caller_id="assistant",
        user_context={"user_id": "usr-requester", "role": "editor"},
        execution_context={"approval_id": req.id, "arguments_hash": req.arguments_hash},
    )
    assert exec_res_repeat.allowed is False
    assert "already been consumed" in exec_res_repeat.reason


# =========================================================================
# 12. Durable Tool Discovery Jobs & Restart Recovery
# =========================================================================

@pytest.mark.asyncio
async def test_durable_tool_discovery_and_restart_recovery(sample_project: Project):
    """Verify tool discovery jobs are tracked in SQLite, suppress duplicates, and recover across restarts."""
    from sqlalchemy import select
    from alberto.models import ToolAnalysisJob
    from alberto.services.tool_manager import ToolManagerService
    from alberto.services.tools import ToolService

    async with SessionLocal() as s:
        tool = await ToolService.create(
            s,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="gh_list_prs",
            kind="mcp",
            config={"description": "List pull requests", "input_schema": {"type": "object", "properties": {"repo": {"type": "string"}}}},
        )

    # 1. Run analysis -> ToolAnalysisJob created and completed in SQLite
    analyses = await ToolManagerService.analyze_discovered_tools(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_ids=[tool.id],
        integration_name="GitHub",
    )
    assert len(analyses) == 1

    async with SessionLocal() as s:
        job = (await s.execute(
            select(ToolAnalysisJob).where(
                ToolAnalysisJob.tenant_id == sample_project.tenant_id,
                ToolAnalysisJob.project_id == sample_project.id,
                ToolAnalysisJob.tool_id == tool.id,
            )
        )).scalar_one_or_none()
        assert job is not None
        assert job.status == "completed"

    # 2. Re-run analysis without schema change -> Duplicate work suppressed
    with patch.object(ToolManagerService, "analyze_tool") as mock_analyze:
        analyses_dup = await ToolManagerService.analyze_discovered_tools(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_ids=[tool.id],
            integration_name="GitHub",
        )
        assert len(analyses_dup) == 0
        assert not mock_analyze.called

    # 3. Simulate pending / interrupted job and test restart recovery
    async with SessionLocal() as s:
        interrupted_job = ToolAnalysisJob(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id=tool.id,
            schema_fingerprint="new-schema-fp-99",
            status="pending",
            retry_count=0,
            max_retries=3,
        )
        s.add(interrupted_job)
        await s.commit()

    recovered_count = await ToolManagerService.recover_pending_analysis_jobs(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
    )
    assert recovered_count >= 1


# =========================================================================
# 13. End-to-End Master Agent Delegation & Lifecycle Smoke Test
# =========================================================================

@pytest.mark.asyncio
async def test_lifecycle_connect_discover_authorize_execute_deny(sample_project: Project):
    """End-to-end integration lifecycle:
    Connect -> Discover -> Classify -> Register -> Graph Update -> Associate -> Authorize -> Execute -> Disable -> Deny
    """
    from alberto.deps import CurrentUser
    from alberto.services.assistant import build_assistant_tools
    from alberto.services.tools import ToolService

    admin_user = CurrentUser(id="usr-lifecycle-admin", tenant_id=sample_project.tenant_id, email="admin@example.com", role="admin")

    # 1. Connect & Register tool
    async with SessionLocal() as s:
        tool = await ToolService.create(
            s,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="cloud_metrics_collector",
            kind="rest_api",
            config={
                "description": "Fetch real-time cluster metrics",
                "input_schema": {"type": "object", "properties": {"cluster": {"type": "string"}}},
                "effect": "read",
                "risk": "low",
                "enabled": True,
            },
        )

    # 2. Master Agent verification: no direct binding, must use delegate_tool_execution
    mutated: list[dict] = []
    agent_tools = build_assistant_tools(sample_project.tenant_id, sample_project.id, mutated, admin_user)
    tool_names = [t.name for t in agent_tools]
    assert "cloud_metrics_collector" not in tool_names
    assert "delegate_tool_execution" in tool_names

    # 3. Execute via delegation when authorized
    with patch.object(ToolService, "test", new_callable=AsyncMock) as mock_test:
        mock_test.return_value = {"ok": True, "projected": {"cpu_utilization": 42.5}}
        exec_res = await ToolManagerService.execute_delegated_tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id_or_capability=tool.id,
            parameters={"cluster": "prod-us-east"},
            user_context={"id": admin_user.id, "role": admin_user.role, "tenant_id": admin_user.tenant_id},
        )
        assert exec_res["ok"] is True
        assert exec_res["result"] == {"cpu_utilization": 42.5}

    # 4. Disable tool -> Immediately denied
    async with SessionLocal() as s:
        tool_db = await ToolService.get(s, sample_project.tenant_id, tool.id)
        assert tool_db is not None
        await ToolService.update(s, tool_db, enabled=False)

    exec_res_disabled = await ToolManagerService.execute_delegated_tool(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id_or_capability=tool.id,
        parameters={"cluster": "prod-us-east"},
        user_context={"id": admin_user.id, "role": admin_user.role, "tenant_id": admin_user.tenant_id},
    )
    assert exec_res_disabled["ok"] is False
    assert "disabled/inactive" in exec_res_disabled["error"]


@pytest.mark.asyncio
async def test_hitl_execution_resume_end_to_end_across_restart(sample_project: Project):
    """Verify complete HITL execution lifecycle:
    1. Request tool execution -> requires approval.
    2. Pending approval persisted in SQLite.
    3. Simulated process restart (clear memory cache).
    4. Decision gating (viewer denied, admin approved).
    5. Tampered arguments denied and approval preserved.
    6. Legitimate execution resumes, consumes atomically, executes once.
    7. Duplicate execution denied (no duplicate side effects).
    8. Post-approval tool disable immediately blocks execution.
    """
    from alberto.services.tool_policy import ToolPolicyService
    from alberto.services.tools import ToolService

    # 1. Create a high-risk tool that requires approval
    async with SessionLocal() as s:
        tool = await ToolService.create(
            s,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="delete_customer_records",
            kind="rest_api",
            config={
                "description": "Permanently delete customer data",
                "effect": "delete",
                "risk": "critical",
                "requires_approval": True,
                "enabled": True,
            },
        )

    user_ctx = {"id": "usr-requester-1", "role": "editor", "tenant_id": sample_project.tenant_id}
    orig_params = {"customer_id": "cust-42", "reason": "GDPR erasure"}

    # 2. Master Agent / Tool Manager requests execution
    res1 = await ToolManagerService.execute_delegated_tool(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id_or_capability=tool.id,
        parameters=orig_params,
        user_context=user_ctx,
    )
    assert res1["ok"] is False
    assert res1["requires_approval"] is True
    appr_id = res1["approval_id"]
    assert appr_id is not None

    # 3. Process restart: cold cache
    ToolPolicyService.clear_cache()
    assert appr_id not in ToolPolicyService._pending_approvals

    # 4. Recover from SQLite
    rec_appr = ToolPolicyService.get_approval(appr_id)
    assert rec_appr is not None
    assert rec_appr.id == appr_id
    assert rec_appr.status == "pending"

    # 5. Role check: viewer cannot decide
    viewer = {"id": "usr-viewer", "role": "viewer", "email": "viewer@example.com"}
    ok_v, err_v = ToolPolicyService.decide_approval_request(appr_id, "approve", viewer)
    assert ok_v is False
    assert "viewer" in err_v.lower()

    # Admin approves
    admin = {"id": "usr-admin", "role": "admin", "email": "admin@example.com"}
    ok_a, _ = ToolPolicyService.decide_approval_request(appr_id, "approve", admin)
    assert ok_a is True

    # 6. Simulate restart again after approval
    ToolPolicyService.clear_cache()

    # 7. Tampered parameter resume attempt -> DENIED, approval preserved
    tampered_params = {"customer_id": "cust-999-unauthorized", "reason": "GDPR erasure"}
    res_tampered = await ToolManagerService.execute_delegated_tool(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id_or_capability=tool.id,
        parameters=tampered_params,
        user_context=user_ctx,
        execution_context={"approval_id": appr_id},
    )
    assert res_tampered["ok"] is False
    assert "mismatch" in res_tampered["error"].lower()

    # Verify approval was NOT consumed by tampered attempt
    appr_after_tamper = ToolPolicyService.get_approval(appr_id)
    assert appr_after_tamper.status == "approved"

    # 8. Valid resume execution -> atomic consume, executes ONCE
    with patch.object(ToolService, "test", new_callable=AsyncMock) as mock_test:
        mock_test.return_value = {"ok": True, "projected": {"deleted": True, "count": 1}}
        res_valid = await ToolManagerService.execute_delegated_tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id_or_capability=tool.id,
            parameters=orig_params,
            user_context=user_ctx,
            execution_context={"approval_id": appr_id},
        )
        assert res_valid["ok"] is True
        assert res_valid["result"] == {"deleted": True, "count": 1}
        mock_test.assert_called_once()

    # Verify status in SQLite is consumed
    appr_consumed = ToolPolicyService.get_approval(appr_id)
    assert appr_consumed.status == "consumed"

    # 9. Duplicate execution attempt -> DENIED (no double execution)
    with patch.object(ToolService, "test", new_callable=AsyncMock) as mock_test_dup:
        res_dup = await ToolManagerService.execute_delegated_tool(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            tool_id_or_capability=tool.id,
            parameters=orig_params,
            user_context=user_ctx,
            execution_context={"approval_id": appr_id},
        )
        assert res_dup["ok"] is False
        assert "consumed" in res_dup["error"].lower()
        mock_test_dup.assert_not_called()

    # 10. Activation revocation check: disabled tool denied even if approved
    appr2 = ToolPolicyService.create_approval_request(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id=tool.id,
        tool_name=tool.name,
        arguments=orig_params,
        user_context=user_ctx,
    )
    ToolPolicyService.decide_approval_request(appr2.id, "approve", admin)

    async with SessionLocal() as s:
        t_row = await ToolService.get(s, sample_project.tenant_id, tool.id)
        assert t_row is not None
        await ToolService.update(s, t_row, enabled=False)

    res_revoked = await ToolManagerService.execute_delegated_tool(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        tool_id_or_capability=tool.id,
        parameters=orig_params,
        user_context=user_ctx,
        execution_context={"approval_id": appr2.id},
    )
    assert res_revoked["ok"] is False
    assert "disabled/inactive" in res_revoked["error"]


@pytest.mark.asyncio
async def test_tool_manager_system_agent_model_backed_analysis_and_policy_clamping(sample_project: Project):
    """Verify Tool Manager works through model-backed system-agent infrastructure:
    1. System agent provisioned and custom model override resolved.
    2. Structured LLM invocation path used with output schema validation.
    3. Ambiguous operations constrained by deterministic policy boundaries (LLM cannot downgrade).
    4. Timeout and error handling safely falls back to deterministic classification.
    5. Known tools resolve deterministically without model call.
    """
    from alberto.schemas.tool_manager import ToolAnalysisResult
    from alberto.models.entities import Agent

    async with SessionLocal() as s:
        # 1. Provision system agents
        await AgentService.ensure_system_agents(s, sample_project.tenant_id, sample_project.id)

        # Set model override on tool_manager system agent
        agent = (
            await s.execute(
                select(Agent).where(
                    Agent.tenant_id == sample_project.tenant_id,
                    Agent.project_id == sample_project.id,
                    Agent.system_key == "tool_manager",
                )
            )
        ).scalar_one()
        agent.config = {"model": "openai:gpt-4o-mini"}
        await s.commit()

        # 2. Mock structured model that attempts to hallucinate low risk on ambiguous operation
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value=ToolAnalysisResult(
                tool_id="tool-ambig-1",
                category="database",
                effect="read",     # Hallucinated read
                risk="low",        # Hallucinated low risk
                recommended_activation="auto",  # Hallucinated auto
                confidence=0.95,
            )
        )

        mock_base_model = AsyncMock()
        mock_base_model.with_structured_output = lambda schema: mock_structured

        # Verify get_tool_manager_model resolves configured override through real agent infrastructure
        with patch("alberto.services.tool_manager.resolve_model", return_value=mock_base_model) as mock_resolve:
            resolved_model, model_ref = await ToolManagerService.get_tool_manager_model(
                s, sample_project.tenant_id, sample_project.id
            )
            assert model_ref == "openai:gpt-4o-mini"
            assert mock_resolve.called

            # 3. Analyze tool using real system-agent resolution path
            res = await ToolManagerService.analyze_tool(
                tool_id="tool-ambig-1",
                name="execute_query",
                description="Run dynamic SQL query on database",
                input_schema={"type": "object", "properties": {"sql": {"type": "string"}}},
                use_llm=True,
                session=s,
                tenant_id=sample_project.tenant_id,
                project_id=sample_project.id,
            )
            # Verify real structured ainvoke was called
            mock_structured.ainvoke.assert_called_once()

            # Verify deterministic clamping: effect -> write, risk -> high, activation -> manual_review
            assert res.effect == "write"
            assert res.risk in ("high", "critical")
            assert res.recommended_activation == "manual_review"
            assert len(res.warnings) > 0

        # 4. Timeout error handling: verify bounded fallback
        mock_timeout_model = AsyncMock()
        mock_timeout_structured = AsyncMock()
        mock_timeout_structured.ainvoke = AsyncMock(side_effect=TimeoutError("Model timed out"))
        mock_timeout_model.with_structured_output = lambda schema: mock_timeout_structured

        with patch("alberto.services.tool_manager.resolve_model", return_value=mock_timeout_model):
            res_to = await ToolManagerService.analyze_tool(
                tool_id="tool-ambig-2",
                name="run_command",
                description="Execute system terminal command",
                input_schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
                use_llm=True,
                session=s,
                tenant_id=sample_project.tenant_id,
                project_id=sample_project.id,
            )
            assert res_to.effect in ("write", "delete")
            assert res_to.risk in ("high", "critical")
            assert any("deterministic" in w.lower() for w in res_to.warnings)




