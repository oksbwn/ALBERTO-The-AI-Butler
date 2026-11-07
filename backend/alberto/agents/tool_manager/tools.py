"""Integration & Tool Manager StructuredTools."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import StructuredTool

from alberto.db.base import SessionLocal

AUTH_TEMPLATES: dict[str, dict] = {
    "bearer": {"kind": "bearer", "token_ref": "secret://proj/token", "header_name": "Authorization", "prefix": "Bearer "},
    "api_key": {"kind": "api_key", "in": "header", "name": "X-API-Key", "value_ref": "secret://proj/api_key"},
    "basic": {"kind": "basic", "username_ref": "secret://proj/user", "password_ref": "secret://proj/pass"},
    "oauth2_client_credentials": {
        "kind": "oauth2_client_credentials",
        "token_url": "https://idp.example.com/oauth/token",
        "scope": "read",
        "client_id_ref": "secret://proj/client_id",
        "client_secret_ref": "secret://proj/client_secret",
    },
    "csrf_session": {
        "kind": "csrf_session",
        "credentials_ref": "secret://proj/creds",
        "token_fetch": {
            "method": "POST",
            "url": "https://app.example.com/login",
            "headers": {"Content-Type": "application/json"},
            "body": {"username": "{{cred.username}}", "password": "{{cred.password}}"},
        },
        "extract": [{"name": "csrf", "from": "header", "header": "X-CSRF-Token"}],
        "inject": [{"to": "header", "name": "X-CSRF-Token", "value": "{{extracted.csrf}}"}],
        "cache_ttl_seconds": 1800,
        "refresh_on": [401, 403],
    },
}


def _split_csv(s: str) -> list[str]:
    """Comma-separated tool params -> a clean list of names."""
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def build_tool_manager_tools(tenant_id: str, project_id: str, mutated: list, current_user: Any = None) -> list:
    """Build Integration & Tool Manager StructuredTools for a project."""

    async def create_builtin_tool(name: str, builtin: str, description: str = "") -> str:
        """Create a builtin tool. `builtin` is one of: current_time, calculator, web_fetch,
        web_search, knowledge_search. knowledge_search lets an AGENT search the project
        knowledge base itself (docs + FAQs, optional folder filter) - attach it to one agent
        instead of a classifier→router when a question may have several parts."""
        from alberto.services.tools import ToolService

        if builtin not in ("current_time", "calculator", "web_fetch", "web_search", "knowledge_search", "remember", "recall"):
            return f"ERROR: unknown builtin '{builtin}'."
        async with SessionLocal() as s:
            t = await ToolService.create(
                s,
                tenant_id,
                project_id,
                name=name.strip().replace(" ", "_"),
                kind="builtin",
                config={"builtin": builtin, "description": description or f"{builtin} builtin"},
            )
        mutated.append({"kind": "tool", "name": t.name})
        return f"Created builtin tool '{t.name}' (id {t.id})."

    async def create_rest_tool(
        name: str,
        url_template: str,
        method: str = "GET",
        description: str = "",
        projection_jmespath: str = "",
        query_params: str = "",
        header_params: str = "",
        body_params: str = "",
    ) -> str:
        """Create a REST API tool. url_template may contain {placeholders} that become required
        path params. query_params / header_params / body_params are OPTIONAL comma-separated
        names that become LLM-visible query-string / header / JSON-body args (body_params implies
        a JSON body - use with method=POST/PUT/PATCH). projection_jmespath (optional) trims the
        response before it reaches the model."""
        from alberto.services.tools import ToolService

        def _fields(names: str, loc: str, required: bool) -> list[dict]:
            return [
                {"path": p, "type": "string", "in": loc, "required": required, "llm_visible": True, "description": p}
                for p in _split_csv(names)
            ]

        path_params = re.findall(r"\{(\w+)\}", url_template)
        fields = [
            {"path": p, "type": "string", "in": "path", "required": True, "llm_visible": True, "description": p}
            for p in path_params
        ]
        fields += _fields(query_params, "query", False) + _fields(header_params, "header", False) + _fields(body_params, "body", False)
        cfg: dict[str, Any] = {
            "description": description or f"{method} {url_template}",
            "request": {
                "method": method.upper(),
                "url_template": url_template,
                "fields": fields,
                "headers": [{"name": "Accept", "value": "application/json"}],
            },
            "response": {"projection_jmespath": projection_jmespath} if projection_jmespath else {},
            "timeout_seconds": 30,
        }
        async with SessionLocal() as s:
            t = await ToolService.create(s, tenant_id, project_id, name=name.strip().replace(" ", "_"), kind="rest_api", config=cfg)
        mutated.append({"kind": "tool", "name": t.name})
        return f"Created REST tool '{t.name}' ({method.upper()} {url_template}) with {len(fields)} param(s)."

    async def create_graphql_tool(
        name: str,
        endpoint: str,
        query: str,
        variables: str = "",
        description: str = "",
        projection_jmespath: str = "",
    ) -> str:
        """Create a GraphQL tool. `query` is the GraphQL document; `variables` is an OPTIONAL
        comma-separated list of variable names that become LLM-visible args, sent as the GraphQL
        `variables`. projection_jmespath (optional) trims the response before it reaches the model."""
        from alberto.services.tools import ToolService

        var_fields = [
            {"path": v, "type": "string", "required": True, "llm_visible": True, "description": v}
            for v in _split_csv(variables)
        ]
        cfg: dict[str, Any] = {
            "description": description or f"GraphQL {endpoint}",
            "endpoint": endpoint,
            "query": query,
            "variables": var_fields,
            "response": {"projection_jmespath": projection_jmespath} if projection_jmespath else {},
            "timeout_seconds": 30,
        }
        async with SessionLocal() as s:
            t = await ToolService.create(s, tenant_id, project_id, name=name.strip().replace(" ", "_"), kind="graphql", config=cfg)
        mutated.append({"kind": "tool", "name": t.name})
        return f"Created GraphQL tool '{t.name}' (POST {endpoint}) with {len(var_fields)} variable(s)."

    async def create_sql_tool(
        name: str,
        query: str,
        connection_ref: str = "",
        description: str = "",
        read_only: bool = True,
        max_rows: int = 100,
        arg_names: str = "",
    ) -> str:
        """Create a SQL tool that runs a parameterized `query` against a database. `connection_ref`
        is a secret ref (e.g. secret://proj/db_url) holding the connection URL - the user fills it
        in afterward. `arg_names` is an OPTIONAL comma-separated list of LLM-visible query-parameter
        names. read_only rejects writes; max_rows caps the result set."""
        from alberto.services.tools import ToolService

        nm = name.strip().replace(" ", "_")
        props = {a: {"type": "string"} for a in _split_csv(arg_names)}
        cfg: dict[str, Any] = {
            "name": nm,
            "description": description or "SQL query tool",
            "query": query,
            "read_only": bool(read_only),
            "max_rows": int(max_rows),
            "args_schema": {"type": "object", "properties": props, "required": list(props)} if props else {},
        }
        if connection_ref:
            cfg["connection_ref"] = connection_ref
        async with SessionLocal() as s:
            t = await ToolService.create(s, tenant_id, project_id, name=nm, kind="sql", config=cfg)
        mutated.append({"kind": "tool", "name": t.name})
        note = "" if connection_ref else " Add a connection secret (connection_ref) in Auth/Secrets before it can run."
        return f"Created SQL tool '{t.name}' (read_only={read_only}, max_rows={max_rows}, {len(props)} arg(s)).{note}"

    async def create_code_tool(
        name: str,
        source: str,
        description: str = "",
        arg_names: str = "",
        timeout_seconds: int = 5,
    ) -> str:
        """Create a sandboxed Python code tool. `source` is the Python body to execute; `arg_names`
        is an OPTIONAL comma-separated list of LLM-visible argument names available to the code. The
        code runs in the platform sandbox with a timeout."""
        from alberto.services.tools import ToolService

        nm = name.strip().replace(" ", "_")
        props = {a: {"type": "string"} for a in _split_csv(arg_names)}
        cfg: dict[str, Any] = {
            "name": nm,
            "description": description or "Python code tool",
            "language": "python",
            "source": source,
            "timeout_seconds": int(timeout_seconds),
            "args_schema": {"type": "object", "properties": props, "required": list(props)} if props else {},
        }
        async with SessionLocal() as s:
            t = await ToolService.create(s, tenant_id, project_id, name=nm, kind="code", config=cfg)
        mutated.append({"kind": "tool", "name": t.name})
        return f"Created code tool '{t.name}' (python, timeout {timeout_seconds}s, {len(props)} arg(s))."

    async def create_mcp_tool(name: str, url: str, transport: str = "http", headers_ref: str = "") -> str:
        """Register an EXTERNAL MCP server so its tools become available to agents. `url` is the
        server endpoint; `transport` is 'http' (default) or 'sse'; `headers_ref` (optional) is a
        secret ref for auth headers. The server's tools are discovered at run time and can be
        attached to an agent."""
        from alberto.models import McpClient

        nm = name.strip().replace(" ", "_")
        async with SessionLocal() as s:
            m = McpClient(
                tenant_id=tenant_id,
                project_id=project_id,
                name=nm,
                transport=(transport or "http"),
                url=url,
                headers_ref=headers_ref or None,
                enabled=True,
            )
            s.add(m)
            await s.commit()
            await s.refresh(m)
        mutated.append({"kind": "mcp_client", "name": m.name})
        return f"Registered MCP server '{m.name}' ({transport} {url}). Its tools are discovered at run time; attach them to an agent."

    async def create_auth_provider(name: str, kind: str = "bearer") -> str:
        """Create an auth provider from a template. kind: bearer, api_key, basic, oauth2_client_credentials, or csrf_session. The user can fill in secrets afterward."""
        from alberto.services.auth_providers import AuthProviderService

        cfg = AUTH_TEMPLATES.get(kind)
        if not cfg:
            return f"ERROR: unknown auth kind '{kind}'. Use one of: {', '.join(AUTH_TEMPLATES)}."
        async with SessionLocal() as s:
            ap = await AuthProviderService.create(
                s,
                tenant_id,
                project_id,
                name=name.strip().replace(" ", "_"),
                kind=kind,
                config=dict(cfg),
                credentials_ref=cfg.get("credentials_ref") or cfg.get("token_ref") or cfg.get("value_ref"),
            )
        mutated.append({"kind": "auth_provider", "name": ap.name})
        return f"Created '{kind}' auth provider '{ap.name}'. Open Auth Providers to add the secret values."

    async def delegate_tool_execution(
        tool_id_or_capability: str,
        parameters_json: str = "{}",
        approval_id: str = "",
    ) -> str:
        """Execute an external tool or query Home Assistant devices. For smart home or device queries (lights, switches, sensors, climate, states), pass tool_id_or_capability (e.g. 'ha_get_overview', 'ha_search', 'ha_eval_template', 'ha_get_state') and parameters_json."""
        from alberto.services.tool_manager import ToolManagerService

        try:
            params = json.loads(parameters_json) if parameters_json else {}
        except Exception:
            params = {}
        user_ctx = (
            {
                "user_id": getattr(current_user, "id", None),
                "tenant_id": getattr(current_user, "tenant_id", tenant_id),
                "role": getattr(current_user, "role", "assistant"),
                "email": getattr(current_user, "email", None),
            }
            if current_user
            else {"role": "assistant", "tenant_id": tenant_id}
        )
        exec_ctx = {"approval_id": approval_id} if approval_id else {}
        res = await ToolManagerService.execute_delegated_tool(
            tenant_id=tenant_id,
            project_id=project_id,
            tool_id_or_capability=tool_id_or_capability,
            parameters=params,
            user_context=user_ctx,
            execution_context=exec_ctx,
        )
        return json.dumps(res, default=str)

    def mk(fn, name):
        return StructuredTool.from_function(coroutine=fn, name=name, parse_docstring=False)

    return [
        mk(create_builtin_tool, "create_builtin_tool"),
        mk(create_rest_tool, "create_rest_tool"),
        mk(create_graphql_tool, "create_graphql_tool"),
        mk(create_sql_tool, "create_sql_tool"),
        mk(create_code_tool, "create_code_tool"),
        mk(create_mcp_tool, "create_mcp_tool"),
        mk(create_auth_provider, "create_auth_provider"),
        mk(delegate_tool_execution, "delegate_tool_execution"),
    ]

