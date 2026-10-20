"""Forge Assistant - a meta-agent whose tools are the Forge platform itself.

It can inspect a project and *build* into it: create tools, auth providers, Q&A,
knowledge, and workflows; and explain how the pieces fit together. It runs with the
project's own provider key (resolved from the secret store) and streams its narration
token-by-token over SSE, emitting `tool` events as it performs each action.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import select

from alberto.config import settings
from alberto.db.base import SessionLocal
from alberto.engine.models import resolve_model
from alberto.models import Agent, AuthProvider, KbSource, Project, QaPair, Tool, Workflow
from alberto.services.knowledge import KnowledgeService
from alberto.services.runtime import build_compile_context
from alberto.services.workflows import WorkflowService
from alberto.util.serialize import content_to_text, jsonable

log = logging.getLogger("alberto.services.assistant")

GROUNDING_PROMPT = (
    "You are the support assistant for this project. Be friendly, natural, and concise.\n"
    "- For greetings, thanks, goodbyes, or small talk (e.g. 'hi', 'thanks'), reply naturally and "
    "briefly and invite the user's question. Do NOT refuse these.\n"
    "- For questions about this project/product/company, answer using ONLY the KNOWLEDGE BASE "
    "context provided in the conversation (documents and FAQs). If that context does not contain "
    "the answer, say you don't have that information and offer to connect them with a human. Never "
    "invent facts or rely on outside knowledge for such questions.\n"
    "- You may use the prior conversation turns for context (e.g. follow-up questions)."
)

AUTH_TEMPLATES: dict[str, dict] = {
    "bearer": {"kind": "bearer", "token_ref": "secret://proj/token", "header_name": "Authorization", "prefix": "Bearer "},
    "api_key": {"kind": "api_key", "in": "header", "name": "X-API-Key", "value_ref": "secret://proj/api_key"},
    "basic": {"kind": "basic", "username_ref": "secret://proj/user", "password_ref": "secret://proj/pass"},
    "oauth2_client_credentials": {
        "kind": "oauth2_client_credentials", "token_url": "https://idp.example.com/oauth/token",
        "scope": "read", "client_id_ref": "secret://proj/client_id", "client_secret_ref": "secret://proj/client_secret",
    },
    "csrf_session": {
        "kind": "csrf_session", "credentials_ref": "secret://proj/creds",
        "token_fetch": {"method": "POST", "url": "https://app.example.com/login", "headers": {"Content-Type": "application/json"}, "body": {"username": "{{cred.username}}", "password": "{{cred.password}}"}},
        "extract": [{"name": "csrf", "from": "header", "header": "X-CSRF-Token"}],
        "inject": [{"to": "header", "name": "X-CSRF-Token", "value": "{{extracted.csrf}}"}],
        "cache_ttl_seconds": 1800, "refresh_on": [401, 403],
    },
}


def _node(nid: str, ntype: str, cfg: dict, x: int, y: int) -> dict:
    return {"id": nid, "type": ntype, "config": cfg, "position": {"x": x, "y": y}}


def _warn_note(warnings: list | None) -> str:
    if not warnings:
        return ""
    msgs = "; ".join(w.get("message", "") for w in warnings[:3])
    return f" VALIDATION WARNINGS (fix if unintended): {msgs}"


def _split_csv(s: str) -> list[str]:
    """Comma-separated tool params -> a clean list of names."""
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def _model_is_offline(model) -> bool:
    """True for the offline `fake:` chat model, so the build judge can report 'unverified'
    instead of a bogus 'pass' when no real provider model is configured (finding F7)."""
    try:
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
        return isinstance(model, GenericFakeChatModel)
    except Exception:  # noqa: BLE001
        return False


def _canvas(nodes: list[dict], edges: list[dict]) -> dict:
    # The frontend (canvasToFlow) reads node config from data.config and the node kind
    # from data.nodeType. Emitting the bare config as `data` (the old bug) made the
    # builder show every node as empty/unconfigured even though the executable was fine.
    by_id = {n["id"]: n for n in nodes}

    def source_handle(edge: dict) -> str | None:
        if edge.get("sourceHandle") or edge.get("source_handle"):
            return edge.get("sourceHandle") or edge.get("source_handle")
        source = by_id.get(edge["source"])
        if not source or source.get("type") != "router":
            return None
        cfg = source.get("config") or {}
        cases = cfg.get("cases") or {}
        label = edge.get("label")
        if label is not None and str(label) in cases:
            return f"case:{label}"
        for key, target in cases.items():
            if target == edge.get("target"):
                return f"case:{key}"
        if cfg.get("default") == edge.get("target"):
            return "case:__default__"
        return None

    return {
        "nodes": [
            {"id": n["id"], "type": "forge", "position": n["position"],
             "data": {"nodeType": n["type"], "config": n["config"]}}
            for n in nodes
        ],
        "edges": [
            {"id": f"e{i}", "source": e["source"], "target": e["target"],
             **({"sourceHandle": source_handle(e)} if source_handle(e) else {}),
             **({"label": str(e["label"])} if e.get("label") is not None else {})}
            for i, e in enumerate(edges)
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


async def _default_agent_model(session, tenant_id: str, project_id: str) -> str:
    """Pick a real model ref for created agents, based on project config."""
    proj = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    cfg = (proj.config or {}) if proj else {}
    explicit = cfg.get("default_model_id") or cfg.get("default_model")
    if explicit and not str(explicit).startswith("fake"):
        return explicit
    fallback = cfg.get("fallback_model")
    if fallback:
        return fallback
    if getattr(settings, "default_model", None):
        return settings.default_model
    raise ValueError("No model configured or available. Please configure a default model in project settings or model registry.")


def build_assistant_tools(tenant_id: str, project_id: str, mutated: list, current_user: Any = None) -> list:
    """StructuredTools bound to one project. `mutated` collects created-resource notes."""
    from langchain_core.tools import StructuredTool

    async def list_resources() -> str:
        """List everything in this project: MCP integrations, connectors, tools, workflows, agents, auth providers, knowledge sources, and Q&A pairs. Use this to answer 'what do I have' and before deciding what to build."""
        from alberto.models import ConnectorInstall, McpClient
        async with SessionLocal() as s:
            def names(rows, attr="name"):
                return [getattr(r, attr) for r in rows] or ["(none)"]
            mcps = (await s.execute(select(McpClient).where(McpClient.tenant_id == tenant_id, McpClient.project_id == project_id))).scalars().all()
            conns = (await s.execute(select(ConnectorInstall).where(ConnectorInstall.tenant_id == tenant_id, ConnectorInstall.project_id == project_id))).scalars().all()
            tools = (await s.execute(select(Tool).where(Tool.tenant_id == tenant_id, Tool.project_id == project_id))).scalars().all()
            wfs = (await s.execute(select(Workflow).where(Workflow.tenant_id == tenant_id, Workflow.project_id == project_id))).scalars().all()
            agents = (await s.execute(select(Agent).where(Agent.tenant_id == tenant_id, Agent.project_id == project_id))).scalars().all()
            aps = (await s.execute(select(AuthProvider).where(AuthProvider.tenant_id == tenant_id, AuthProvider.project_id == project_id))).scalars().all()
            srcs = (await s.execute(select(KbSource).where(KbSource.tenant_id == tenant_id, KbSource.project_id == project_id))).scalars().all()
            qas = (await s.execute(select(QaPair).where(QaPair.tenant_id == tenant_id, QaPair.project_id == project_id))).scalars().all()
            mcp_items = []
            for m in mcps:
                is_ha = "8123" in (m.url or "") or m.name.upper() == "HA" or "homeassistant" in (m.url or "").lower()
                label = f"{m.name} (Home Assistant)" if is_ha else m.name
                status_str = "enabled" if m.enabled else "disabled"
                mcp_items.append(f"{label} ({m.transport}, {m.url or 'local'}) [{status_str}]")
            conn_items = [f"{c.name or c.slug} [{c.status}] (version {c.version})" for c in conns] or ["(none)"]
            return json.dumps({
                "mcp_integrations": mcp_items or ["(none)"],
                "connectors": conn_items,
                "tools": [f"{t.name} ({t.kind})" for t in tools] or ["(none)"],
                "workflows": [f"{w.name} [{w.status}]" for w in wfs] or ["(none)"],
                "agents": names(agents), "auth_providers": [f"{a.name} ({a.kind})" for a in aps] or ["(none)"],
                "knowledge_sources": names(srcs), "qa_pairs": len(qas),
            })

    async def describe_workflow(name_or_id: str = "") -> str:
        """Describe a workflow's structure (its nodes and how they connect) so you can explain how it works. Pass a name or id; empty picks the active workflow."""
        async with SessionLocal() as s:
            wfs = (await s.execute(select(Workflow).where(Workflow.tenant_id == tenant_id, Workflow.project_id == project_id))).scalars().all()
            wf = None
            if name_or_id:
                wf = next((w for w in wfs if w.id == name_or_id or w.name.lower() == name_or_id.lower()), None)
            wf = wf or next((w for w in wfs if w.status == "active"), None) or (wfs[0] if wfs else None)
            if not wf:
                return "No workflows exist yet."
            ex = wf.executable or {}
            nodes = [{"id": n["id"], "type": n["type"], "config": {k: v for k, v in (n.get("config") or {}).items() if k in ("model", "name", "top_k", "expression")}} for n in ex.get("nodes", [])]
            edges = [f"{e['source']} → {e['target']}" for e in ex.get("edges", [])]
            return json.dumps({"name": wf.name, "status": wf.status, "nodes": nodes, "flow": edges})

    async def create_agent_preset(name: str, instructions: str, model: str = "", tool_names: str = "") -> str:
        """Create OR UPDATE (idempotent by name) a reusable agent preset with the given system
        `instructions`. `model` like 'openai:gpt-4o-mini' (empty = project default). `tool_names`
        is an optional comma-separated list of EXISTING project tool names to attach. The preset
        appears in the Agents screen and can be dropped into workflows."""
        from alberto.services.agents import AgentService
        async with SessionLocal() as s:
            mdl = model or await _default_agent_model(s, tenant_id, project_id)
            wanted = [t.strip() for t in tool_names.split(",") if t.strip()]
            tool_ids: list[str] = []
            missing: list[str] = []
            if wanted:
                rows = (await s.execute(select(Tool).where(Tool.project_id == project_id))).scalars().all()
                by_name = {t.name: t.id for t in rows}
                for w in wanted:
                    (tool_ids.append(by_name[w]) if w in by_name else missing.append(w))
            cfg = {"flavor": "agent", "model": mdl, "system_prompt": instructions, "tools": tool_ids, "middleware": []}
            existing = [a for a in await AgentService.list(s, tenant_id, project_id) if a.name == name]
            if existing:
                agent = await AgentService.update(s, existing[0], config=cfg)
                verb = "Updated existing"
            else:
                agent = await AgentService.create(s, tenant_id, project_id, name=name.strip().replace(" ", "_"), config=cfg)
                verb = "Created"
        mutated.append({"kind": "agent", "name": agent.name})
        note = f" (unknown tools skipped: {', '.join(missing)})" if missing else ""
        return f"{verb} agent preset '{agent.name}' on {mdl} with {len(tool_ids)} tool(s){note}. See the Agents screen."

    async def create_builtin_tool(name: str, builtin: str, description: str = "") -> str:
        """Create a builtin tool. `builtin` is one of: current_time, calculator, web_fetch,
        web_search, knowledge_search. knowledge_search lets an AGENT search the project
        knowledge base itself (docs + FAQs, optional folder filter) - attach it to one agent
        instead of a classifier→router when a question may have several parts."""
        from alberto.services.tools import ToolService
        if builtin not in ("current_time", "calculator", "web_fetch", "web_search", "knowledge_search", "remember", "recall"):
            return f"ERROR: unknown builtin '{builtin}'."
        async with SessionLocal() as s:
            t = await ToolService.create(s, tenant_id, project_id, name=name.strip().replace(" ", "_"), kind="builtin",
                                         config={"builtin": builtin, "description": description or f"{builtin} builtin"})
        mutated.append({"kind": "tool", "name": t.name})
        return f"Created builtin tool '{t.name}' (id {t.id})."

    async def create_rest_tool(name: str, url_template: str, method: str = "GET", description: str = "",
                               projection_jmespath: str = "", query_params: str = "", header_params: str = "",
                               body_params: str = "") -> str:
        """Create a REST API tool. url_template may contain {placeholders} that become required
        path params. query_params / header_params / body_params are OPTIONAL comma-separated
        names that become LLM-visible query-string / header / JSON-body args (body_params implies
        a JSON body - use with method=POST/PUT/PATCH). projection_jmespath (optional) trims the
        response before it reaches the model."""
        import re

        from alberto.services.tools import ToolService

        def _fields(names: str, loc: str, required: bool) -> list[dict]:
            return [{"path": p, "type": "string", "in": loc, "required": required, "llm_visible": True, "description": p}
                    for p in _split_csv(names)]

        path_params = re.findall(r"\{(\w+)\}", url_template)
        fields = [{"path": p, "type": "string", "in": "path", "required": True, "llm_visible": True, "description": p} for p in path_params]
        fields += _fields(query_params, "query", False) + _fields(header_params, "header", False) + _fields(body_params, "body", False)
        cfg: dict[str, Any] = {
            "description": description or f"{method} {url_template}",
            "request": {"method": method.upper(), "url_template": url_template, "fields": fields, "headers": [{"name": "Accept", "value": "application/json"}]},
            "response": {"projection_jmespath": projection_jmespath} if projection_jmespath else {},
            "timeout_seconds": 30,
        }
        async with SessionLocal() as s:
            t = await ToolService.create(s, tenant_id, project_id, name=name.strip().replace(" ", "_"), kind="rest_api", config=cfg)
        mutated.append({"kind": "tool", "name": t.name})
        return f"Created REST tool '{t.name}' ({method.upper()} {url_template}) with {len(fields)} param(s)."

    async def create_graphql_tool(name: str, endpoint: str, query: str, variables: str = "",
                                  description: str = "", projection_jmespath: str = "") -> str:
        """Create a GraphQL tool. `query` is the GraphQL document; `variables` is an OPTIONAL
        comma-separated list of variable names that become LLM-visible args, sent as the GraphQL
        `variables`. projection_jmespath (optional) trims the response before it reaches the model."""
        from alberto.services.tools import ToolService
        var_fields = [{"path": v, "type": "string", "required": True, "llm_visible": True, "description": v}
                      for v in _split_csv(variables)]
        cfg: dict[str, Any] = {
            "description": description or f"GraphQL {endpoint}",
            "endpoint": endpoint, "query": query, "variables": var_fields,
            "response": {"projection_jmespath": projection_jmespath} if projection_jmespath else {},
            "timeout_seconds": 30,
        }
        async with SessionLocal() as s:
            t = await ToolService.create(s, tenant_id, project_id, name=name.strip().replace(" ", "_"), kind="graphql", config=cfg)
        mutated.append({"kind": "tool", "name": t.name})
        return f"Created GraphQL tool '{t.name}' (POST {endpoint}) with {len(var_fields)} variable(s)."

    async def create_sql_tool(name: str, query: str, connection_ref: str = "", description: str = "",
                              read_only: bool = True, max_rows: int = 100, arg_names: str = "") -> str:
        """Create a SQL tool that runs a parameterized `query` against a database. `connection_ref`
        is a secret ref (e.g. secret://proj/db_url) holding the connection URL - the user fills it
        in afterward. `arg_names` is an OPTIONAL comma-separated list of LLM-visible query-parameter
        names. read_only rejects writes; max_rows caps the result set."""
        from alberto.services.tools import ToolService
        nm = name.strip().replace(" ", "_")
        props = {a: {"type": "string"} for a in _split_csv(arg_names)}
        cfg: dict[str, Any] = {
            "name": nm, "description": description or "SQL query tool", "query": query,
            "read_only": bool(read_only), "max_rows": int(max_rows),
            "args_schema": {"type": "object", "properties": props, "required": list(props)} if props else {},
        }
        if connection_ref:
            cfg["connection_ref"] = connection_ref
        async with SessionLocal() as s:
            t = await ToolService.create(s, tenant_id, project_id, name=nm, kind="sql", config=cfg)
        mutated.append({"kind": "tool", "name": t.name})
        note = "" if connection_ref else " Add a connection secret (connection_ref) in Auth/Secrets before it can run."
        return f"Created SQL tool '{t.name}' (read_only={read_only}, max_rows={max_rows}, {len(props)} arg(s)).{note}"

    async def create_code_tool(name: str, source: str, description: str = "", arg_names: str = "",
                               timeout_seconds: int = 5) -> str:
        """Create a sandboxed Python code tool. `source` is the Python body to execute; `arg_names`
        is an OPTIONAL comma-separated list of LLM-visible argument names available to the code. The
        code runs in the platform sandbox with a timeout."""
        from alberto.services.tools import ToolService
        nm = name.strip().replace(" ", "_")
        props = {a: {"type": "string"} for a in _split_csv(arg_names)}
        cfg: dict[str, Any] = {
            "name": nm, "description": description or "Python code tool", "language": "python",
            "source": source, "timeout_seconds": int(timeout_seconds),
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
            m = McpClient(tenant_id=tenant_id, project_id=project_id, name=nm, transport=(transport or "http"),
                          url=url, headers_ref=headers_ref or None, enabled=True)
            s.add(m)
            await s.commit()
            await s.refresh(m)
        mutated.append({"kind": "mcp_client", "name": m.name})
        return f"Registered MCP server '{m.name}' ({transport} {url}). Its tools are discovered at run time; attach them to an agent."

    async def create_component(name: str, html: str, title: str = "", description: str = "",
                               css: str = "", props_schema_json: str = "", sample_props_json: str = "") -> str:
        """Create OR UPDATE (idempotent by name) a generative-UI component: sandboxed HTML/CSS the
        agent renders as a widget. `props_schema_json` (a JSON-Schema object) describes the props
        the agent must supply; `sample_props_json` is example props for the preview. Attach it to
        an agent (config.components) so the model can call it as a widget-tool."""
        from alberto.models import Component
        from alberto.services.components import ComponentService
        nm = name.strip().replace(" ", "_")
        try:
            props_schema = json.loads(props_schema_json) if props_schema_json else {}
            sample = json.loads(sample_props_json) if sample_props_json else {}
        except json.JSONDecodeError as e:
            return f"ERROR: props_schema_json/sample_props_json must be valid JSON: {e}"
        async with SessionLocal() as s:
            existing = (await s.execute(select(Component).where(
                Component.tenant_id == tenant_id, Component.project_id == project_id, Component.name == nm
            ))).scalar_one_or_none()
            if existing:
                comp = await ComponentService.update(s, existing, title=title or None, description=description,
                                                     props_schema=props_schema, html=html, css=css, sample_props=sample)
                verb = "Updated"
            else:
                comp = await ComponentService.create(s, tenant_id, project_id, name=nm, title=title or None,
                                                     description=description, props_schema=props_schema, html=html,
                                                     css=css, sample_props=sample)
                verb = "Created"
        mutated.append({"kind": "component", "name": comp.name})
        return f"{verb} component '{comp.name}'. Attach it to an agent (config.components) to let the model render it as a widget."

    async def create_auth_provider(name: str, kind: str = "bearer") -> str:
        """Create an auth provider from a template. kind: bearer, api_key, basic, oauth2_client_credentials, or csrf_session. The user can fill in secrets afterward."""
        from alberto.services.auth_providers import AuthProviderService
        cfg = AUTH_TEMPLATES.get(kind)
        if not cfg:
            return f"ERROR: unknown auth kind '{kind}'. Use one of: {', '.join(AUTH_TEMPLATES)}."
        async with SessionLocal() as s:
            ap = await AuthProviderService.create(s, tenant_id, project_id, name=name.strip().replace(" ", "_"), kind=kind, config=dict(cfg), credentials_ref=cfg.get("credentials_ref") or cfg.get("token_ref") or cfg.get("value_ref"))
        mutated.append({"kind": "auth_provider", "name": ap.name})
        return f"Created '{kind}' auth provider '{ap.name}'. Open Auth Providers to add the secret values."

    async def add_qa_pair(question: str, answer: str, kind: str = "faq") -> str:
        """Add a Q&A pair to the knowledge base so the workflow can answer this question with
        this exact answer. `kind` is a free-form category - 'faq', 'error_workaround', or any
        custom kind the user wants (retrieval nodes and agent Q&A can filter by it)."""
        async with SessionLocal() as s:
            qa = await KnowledgeService.create_qa(s, tenant_id, project_id, question=question, answer=answer, kind=kind or "faq")
        mutated.append({"kind": "qa", "name": question[:40]})
        return f"Added Q&A pair ({qa.kind}): '{question[:60]}' (id {qa.id})."

    async def add_knowledge_text(name: str, text: str, folder: str = "") -> str:
        """Add a document of text to the knowledge base (it is split, embedded, and made
        searchable for grounding). `folder` (optional, free-form) organizes sources -
        retrieval nodes and knowledge_search tools can filter by folder."""
        async with SessionLocal() as s:
            src = await KnowledgeService.create_source(s, tenant_id, project_id, kind="text", name=name, text=text, folder=folder)
            src = await KnowledgeService.ingest(s, src)
        mutated.append({"kind": "knowledge", "name": name})
        if src.status != "ready":
            return f"ERROR ingesting '{name}': {(src.meta or {}).get('error', 'unknown')}."
        where = f" in folder '{folder}'" if folder else ""
        return f"Added knowledge source '{name}'{where} ({src.chunks} chunk(s), embedded)."

    def _auto_declare_state(nodes: list, state: dict) -> dict:
        """Declare the state keys nodes write (mirrors the canvas's nodeWrittenKeys) so
        generated definitions don't fail on undeclared-key writes."""
        out = dict(state or {})
        for n in nodes:
            cfg = n.get("config") or {}
            t = n.get("type")
            written: list[tuple[str, str]] = []
            if t == "classifier":
                written.append((cfg.get("output_key", "intent"), "list[str]" if cfg.get("multi_label") else "str"))
            elif t == "retrieval" and cfg.get("route_key"):
                written.append((cfg["route_key"], "str"))
            elif t == "human_input" and cfg.get("output_key"):
                written.append((cfg["output_key"], "str"))
            elif t == "transform":
                written.append((cfg.get("output_key", "data"), "json"))
            elif t in ("tool_call", "webhook_out") and cfg.get("output_key"):
                written.append((cfg["output_key"], "json"))
            for key, typ in written:
                if key and key not in out:
                    out[key] = {"type": typ, "reducer": "last"}
        return out

    async def _save_workflow(
        s, *, name: str, description: str, nodes: list, edges: list, state: dict,
        entry_node: str = "start",
    ) -> tuple[str, str, list]:
        """Validate + idempotently create/update a workflow by exact name.
        Returns (verb, error, warnings)."""
        ex = {"id": "wf", "version": 1, "state": _auto_declare_state(nodes, state), "entry_node": entry_node,
              "global_middleware": [{"type": "model_call_limit", "config": {"run_limit": 25}}],
              "nodes": nodes, "edges": edges}
        result = WorkflowService.validate(ex)
        if not result.valid:
            details = "; ".join(f"{e.get('pointer', '')}: {e.get('message', '')}" for e in result.errors)
            return "", "generated workflow failed validation: " + details, result.warnings
        existing = [w for w in await WorkflowService.list(s, tenant_id, project_id) if w.name == name]
        if existing:
            wf = existing[0]
            await WorkflowService.save_canvas(s, wf, _canvas(nodes, edges), ex)
            wf.status = "active"
            await s.commit()
            verb = "Updated existing"
        else:
            wf = await WorkflowService.create(s, tenant_id, project_id, name=name, description=description)
            await WorkflowService.save_canvas(s, wf, _canvas(nodes, edges), ex)
            wf.status = "active"
            await s.commit()
            verb = "Created and activated"
        mutated.append({"kind": "workflow", "name": name})
        return verb, "", result.warnings

    _CHAT_STATE = {"messages": {"type": "list[message]", "reducer": "add_messages"}, "intent": {"type": "str", "reducer": "last"}}

    async def create_grounded_workflow(name: str = "Grounded support", instructions: str = "", model: str = "",
                                       review_before_reply: bool = False, approve_tools: str = "") -> str:
        """Create OR UPDATE a grounded support workflow: start → retrieval → grounded agent → end.
        The retrieval node pulls BOTH the project's knowledge-base docs AND its Q&A pairs into
        context (include_qa), and the agent answers strictly from that context. Idempotent by name.
        `instructions` sets the agent's system prompt; `model` overrides the model.
        HUMAN-IN-THE-LOOP (real interrupts, not prompt text):
        - review_before_reply=True inserts a human_input node before end - the run PAUSES and a
          human must approve/reject the agent's draft before it is final.
        - approve_tools='tool_a, tool_b' attaches HumanInTheLoopMiddleware so those tool calls
          pause for approval before executing.
        Call list_resources first so you reuse a name instead of duplicating."""
        async with SessionLocal() as s:
            mdl = model or await _default_agent_model(s, tenant_id, project_id)
            agent_cfg: dict[str, Any] = {"flavor": "agent", "name": "support_agent", "model": mdl, "system_prompt": instructions or GROUNDING_PROMPT}
            # Default summarization so long conversations don't grow cost every turn
            # (triggers at ~6k tokens, keeps the last 6 messages). Users can remove it.
            agent_cfg["middleware"] = [{"type": "summarization", "enabled": True,
                                        "config": {"trigger": ["tokens", 6000], "keep": ["messages", 6]}}]
            tool_names = [t.strip() for t in approve_tools.split(",") if t.strip()]
            if tool_names:
                agent_cfg["middleware"].append({"type": "human_in_the_loop", "enabled": True,
                                                "config": {"interrupt_on": {t: True for t in tool_names}}})
            nodes = [
                _node("start", "start", {}, 40, 180),
                _node("retrieval_1", "retrieval", {"top_k": 4, "include_qa": True, "announce_empty": True, "min_score": 0.18}, 300, 180),
                _node("agent_1", "agent", agent_cfg, 560, 180),
            ]
            edges = [{"source": "start", "target": "retrieval_1"}, {"source": "retrieval_1", "target": "agent_1"}]
            if review_before_reply:
                nodes.append(_node("review_1", "human_input", {"prompt": "Review the agent's draft reply above and approve or reject it.", "allowed_decisions": ["approve", "reject"]}, 820, 180))
                nodes.append(_node("end", "end", {}, 1080, 180))
                edges += [{"source": "agent_1", "target": "review_1"}, {"source": "review_1", "target": "end"}]
            else:
                nodes.append(_node("end", "end", {}, 840, 180))
                edges += [{"source": "agent_1", "target": "end"}]
            verb, err, warns = await _save_workflow(s, name=name, description="Retrieval-grounded support agent over the project knowledge base + FAQs.", nodes=nodes, edges=edges, state=_CHAT_STATE)
        if err:
            return "ERROR: " + err
        hitl_note = " Includes a human review pause before the final reply." if review_before_reply else (
            f" Tool calls requiring approval: {', '.join(tool_names)}." if tool_names else "")
        return f"{verb} grounded workflow '{name}': start → retrieval (docs + Q&A) → agent → {'review → ' if review_before_reply else ''}end.{hitl_note}{_warn_note(warns)} Test it in the Playground."

    async def create_intent_router_workflow(name: str = "Intent router", intents: str = "", instructions: str = "", model: str = "") -> str:
        """Create OR UPDATE an intent-routing workflow (the classify-then-route pattern):
        start → classifier (structured output picks ONE intent label) → router (one case per
        intent) → a specialist agent per intent → end, plus a general agent for everything else.
        `intents` is a comma-separated list of labels, e.g. 'return_item, cancel_subscription,
        get_information'. `instructions` is appended to every specialist's prompt. Idempotent by
        name. Use this when the user wants different handling per request type."""
        labels = [i.strip().replace(" ", "_") for i in intents.split(",") if i.strip()]
        if len(labels) < 2:
            return "ERROR: pass at least 2 comma-separated intents, e.g. intents='return_item, cancel_subscription'."
        async with SessionLocal() as s:
            mdl = model or await _default_agent_model(s, tenant_id, project_id)
            base = instructions or "Be concise and helpful."
            nodes = [
                _node("start", "start", {}, 40, 220),
                _node("classify", "classifier", {"labels": labels, "output_key": "intent", "model": mdl}, 260, 220),
                _node("route", "router", {"expression": "intent", "cases": {label: f"{label}_agent" for label in labels}, "default": "general_agent"}, 520, 220),
            ]
            edges = [{"source": "start", "target": "classify"}, {"source": "classify", "target": "route"}]
            for i, label in enumerate(labels):
                agent_id = f"{label}_agent"
                nodes.append(_node(agent_id, "agent", {
                    "flavor": "agent", "name": agent_id, "model": mdl,
                    "system_prompt": f"You are the specialist for '{label.replace('_', ' ')}' requests. {base}",
                }, 800, 80 + i * 140))
                edges.append({"source": "route", "target": agent_id, "label": label})
                edges.append({"source": agent_id, "target": "end"})
            nodes.append(_node("general_agent", "agent", {
                "flavor": "agent", "name": "general_agent", "model": mdl,
                "system_prompt": f"You handle anything that doesn't fit a known category. {base}",
            }, 800, 80 + len(labels) * 140))
            edges.append({"source": "route", "target": "general_agent", "label": "else"})
            edges.append({"source": "general_agent", "target": "end"})
            nodes.append(_node("end", "end", {}, 1080, 220))
            verb, err, warns = await _save_workflow(s, name=name, description=f"Classifies into {', '.join(labels)} and routes to a specialist agent per intent.", nodes=nodes, edges=edges, state=_CHAT_STATE)
        if err:
            return "ERROR: " + err
        return f"{verb} intent-router workflow '{name}': classifier → router → one specialist per intent ({', '.join(labels)}) + a general fallback.{_warn_note(warns)} Test each intent in the Playground."

    async def add_human_review(workflow_name_or_id: str, prompt: str = "Review the draft reply and approve or reject.") -> str:
        """Insert a REAL human-approval pause (a human_input interrupt node) into an EXISTING
        workflow, right before it ends. The run will PAUSE in the Playground until a person
        approves or rejects. Use this whenever the user wants HITL/approval added to a workflow
        that already exists - never simulate approval through agent instructions. Idempotent:
        if the workflow already has a human_input node, only its prompt is updated."""
        async with SessionLocal() as s:
            wfs = await WorkflowService.list(s, tenant_id, project_id)
            wf = next((w for w in wfs if w.id == workflow_name_or_id), None) or next(
                (w for w in wfs if w.name.lower() == workflow_name_or_id.lower()), None)
            if not wf:
                return f"No workflow named or id '{workflow_name_or_id}'. Use list_resources first."
            ex = dict(wf.executable or {})
            nodes = [dict(n) for n in ex.get("nodes", [])]
            edges = [dict(e) for e in ex.get("edges", [])]
            existing = next((n for n in nodes if n["type"] == "human_input"), None)
            if existing:
                existing["config"] = {**(existing.get("config") or {}), "prompt": prompt}
            else:
                end_ids = {n["id"] for n in nodes if n["type"] == "end"}
                if not end_ids:
                    return f"Workflow '{wf.name}' has no end node - open it on the canvas first."
                first_end = next(n for n in nodes if n["type"] == "end")
                gate = _node("human_review", "human_input",
                             {"prompt": prompt, "allowed_decisions": ["approve", "reject"]},
                             max(0, first_end["position"]["x"] - 240), first_end["position"]["y"] + 120)
                for e in edges:
                    if e.get("target") in end_ids:
                        e["target"] = "human_review"
                for n in nodes:
                    if n["type"] == "router":
                        cfg = n.get("config") or {}
                        cfg["cases"] = {k: ("human_review" if v in end_ids else v) for k, v in (cfg.get("cases") or {}).items()}
                        if cfg.get("default") in end_ids:
                            cfg["default"] = "human_review"
                        n["config"] = cfg
                nodes.append(gate)
                edges.append({"source": "human_review", "target": first_end["id"]})
            verb, err, warns = await _save_workflow(s, name=wf.name, description=wf.description or "", nodes=nodes, edges=edges, state=ex.get("state") or _CHAT_STATE, entry_node=ex.get("entry_node") or "start")
        if err:
            return "ERROR: " + err
        return f"Added a human-review pause to '{wf.name}': every reply now stops at an approval gate before finishing.{_warn_note(warns)} Test it in the Playground - the run will pause with approve/reject buttons."

    async def test_workflow(name_or_id: str, message: str) -> str:
        """Run a workflow with a test message and return its final answer plus the nodes it
        visited. ALWAYS use this after building or changing a workflow to VERIFY it behaves
        correctly (e.g. test a greeting, an FAQ question, and an off-topic question). If the
        result is wrong, fix the workflow and test again until it is correct."""
        import uuid as _uuid

        from langgraph.checkpoint.memory import InMemorySaver

        from alberto.engine.compiler import compile_workflow

        async with SessionLocal() as s:
            wfs = await WorkflowService.list(s, tenant_id, project_id)
            wf = next((w for w in wfs if w.id == name_or_id), None) or next(
                (w for w in wfs if w.name.lower() == name_or_id.lower()), None)
            if not wf:
                return f"No workflow named or id '{name_or_id}'. Use list_resources first."
            ctx = await build_compile_context(
                s, tenant_id=tenant_id, project_id=project_id, checkpointer=InMemorySaver()
            )
            try:
                graph = compile_workflow(wf.executable or {}, ctx)
            except Exception as e:  # noqa: BLE001 - surface compile failures to the agent
                return f"COMPILE ERROR in '{wf.name}': {type(e).__name__}: {e}"
        visited: list[str] = []
        final = ""
        interrupted = False
        interrupt_payloads: list = []
        config = {"configurable": {"thread_id": f"assistant-test-{_uuid.uuid4()}"}, "recursion_limit": 50}
        try:
            async for ns, mode, chunk in graph.astream(
                {"messages": [{"role": "user", "content": message}]},
                config,
                stream_mode=["updates", "values"], subgraphs=True,
            ):
                if mode == "updates" and not ns and isinstance(chunk, dict):
                    visited.extend(k for k in chunk.keys() if k not in visited and k != "__interrupt__")
                    if "__interrupt__" in chunk:
                        interrupted = True
                        interrupt_payloads.append(jsonable(chunk["__interrupt__"]))
                        if "__interrupt__" not in visited:
                            visited.append("__interrupt__")
                if mode == "values" and isinstance(chunk, dict):
                    for m in chunk.get("messages", []):
                        if getattr(m, "type", "") == "ai" and getattr(m, "content", ""):
                            final = content_to_text(m.content)
            snapshot = await graph.aget_state(config)
            task_interrupts = [
                jsonable(getattr(t, "interrupts", None))
                for t in getattr(snapshot, "tasks", [])
                if getattr(t, "interrupts", None)
            ]
            if task_interrupts:
                interrupted = True
                interrupt_payloads.extend(task_interrupts)
        except Exception as e:  # noqa: BLE001
            return f"RUNTIME ERROR in '{wf.name}': {type(e).__name__}: {e}"
        return json.dumps({
            "workflow": wf.name,
            "nodes_visited": visited,
            "answer": final[:600] or "(no answer produced)",
            "interrupted": interrupted,
            "interrupts": interrupt_payloads,
        })

    async def list_node_types() -> str:
        """The LIVE catalog of workflow node types (type, label, category, description,
        config keys). Read this before composing a custom workflow so you only use node
        types and config fields that actually exist."""
        from alberto.engine.registry import all_specs
        from alberto.schemas import contracts

        out = []
        for spec in all_specs():
            schema = contracts.raw_schema(spec.schema_id) or {}
            out.append({
                "type": spec.type, "label": spec.label, "category": spec.category,
                "description": spec.description,
                "config_keys": sorted((schema.get("properties") or {}).keys()),
                "required": schema.get("required", []),
            })
        return json.dumps(out)

    async def get_node_schema(node_type: str) -> str:
        """Full JSON config schema for one node type - field types, defaults, and help
        text. Use when you need exact config details for a custom workflow."""
        from alberto.engine.registry import NODE_REGISTRY
        from alberto.schemas import contracts

        spec = NODE_REGISTRY.get(node_type)
        if not spec:
            return f"ERROR: unknown node type '{node_type}'. Call list_node_types first."
        return json.dumps(contracts.raw_schema(spec.schema_id) or {})

    async def list_middleware_types() -> str:
        """All agent middleware types with their config schemas (summarization, retries,
        fallback, PII, guardrails, budgets, HITL…). Attach via an agent node's
        config.middleware: [{type, config, enabled}]."""
        from alberto.schemas import contracts

        out = {t: contracts.middleware_config_schema(t) for t in contracts.middleware_types()}
        return json.dumps(out)

    async def create_custom_workflow(name: str, description: str, definition_json: str) -> str:
        """Build ANY workflow shape - not just the canned patterns. `definition_json` is a
        JSON object: {"state": {...}, "entry_node": "start", "nodes": [{id,type,config}...],
        "edges": [{source,target}...]}. Node positions are auto-laid-out if omitted. State
        keys written by known node configs are auto-declared. The definition is VALIDATED:
        on failure you get field-pointer errors - fix the definition and call again.
        Idempotent by name (same name = update in place). Use list_node_types /
        get_node_schema first so configs are correct, and ALWAYS test_workflow afterwards."""
        try:
            definition = json.loads(definition_json)
        except json.JSONDecodeError as e:
            return f"ERROR: definition_json is not valid JSON: {e}"
        if not isinstance(definition, dict):
            return "ERROR: definition_json must be a JSON object."
        nodes = [dict(n) for n in (definition.get("nodes") or []) if isinstance(n, dict)]
        edges = [dict(e) for e in (definition.get("edges") or []) if isinstance(e, dict)]
        if not nodes:
            return "ERROR: definition has no nodes."
        for i, n in enumerate(nodes):
            if not isinstance(n.get("position"), dict):
                n["position"] = {"x": 60 + (i % 5) * 250, "y": 80 + (i // 5) * 170}
        state = definition.get("state") or _CHAT_STATE
        entry = definition.get("entry_node") or next((n["id"] for n in nodes if n.get("type") == "start"), "start")
        async with SessionLocal() as s:
            verb, err, warns = await _save_workflow(
                s, name=name, description=description or "Custom workflow built by the assistant.",
                nodes=nodes, edges=edges, state=state, entry_node=entry,
            )
        if err:
            return "ERROR: " + err + " - fix the definition and call create_custom_workflow again."
        shape = " → ".join(n["id"] for n in nodes[:6]) + ("…" if len(nodes) > 6 else "")
        return f"{verb} custom workflow '{name}' ({len(nodes)} nodes: {shape}).{_warn_note(warns)} Now VERIFY it with test_workflow."

    async def evaluate_build(user_request: str, what_was_built: str, test_results: str) -> str:
        """LLM judge for your own work: grades whether what you built actually satisfies the
        user's request, given the test_workflow results. Returns {verdict: pass|fail|unverified,
        issues: [...], next_steps: [...]}. 'unverified' means NO real model was available to judge
        (offline) - it is NOT a pass. Call this AFTER test_workflow; if the verdict is 'fail', fix
        the issues and re-test before reporting success."""
        schema = {
            "title": "BuildEvaluation",
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["pass", "fail"]},
                "issues": {"type": "array", "items": {"type": "string"}},
                "next_steps": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["verdict", "issues"],
        }
        async with SessionLocal() as s:
            ctx = await build_compile_context(s, tenant_id=tenant_id, project_id=project_id, load_tools=False)
        model = resolve_model(_assistant_model_ref(ctx), ctx)
        # Offline (fake) model can't actually judge anything - returning 'pass' would be a false
        # green. Report 'unverified' so the caller knows the build was NOT independently checked (F7).
        if _model_is_offline(model):
            return json.dumps({
                "verdict": "unverified",
                "issues": ["No real model configured; ran on the offline model, so the build was NOT independently verified."],
                "next_steps": ["Add a provider API key in project settings, then re-run evaluate_build; meanwhile self-review the test_workflow results."],
            })
        prompt = (
            "You are a strict QA judge for an AI-workflow build. Decide if the build satisfies the request.\n"
            f"USER REQUEST:\n{user_request}\n\nWHAT WAS BUILT:\n{what_was_built}\n\n"
            f"TEST RESULTS (from running the workflow):\n{test_results}\n\n"
            "Fail if: any requested behavior is missing, a test answer is wrong/empty/off-topic, "
            "routing went to the wrong branch, a requested HITL pause did not interrupt, or "
            "parameters the user asked for (model, instructions, folders, kinds) were ignored."
        )
        try:
            res = await model.with_structured_output(schema).ainvoke(prompt)
            return json.dumps(res if isinstance(res, dict) else getattr(res, "__dict__", {"verdict": "fail", "issues": ["judge returned an unexpected shape"]}))
        except Exception as e:  # noqa: BLE001 - judge call errored; inconclusive, NOT a pass
            return json.dumps({"verdict": "unverified", "issues": [f"judge unavailable ({e}); self-review the test results instead"], "next_steps": []})

    async def delete_workflow(name_or_id: str) -> str:
        """Delete a workflow by its exact name or id (also removes its run history). Use this to
        clean up duplicates. If the name matches several workflows, this refuses and lists their
        ids so you can delete a specific one - never bulk-deletes on an ambiguous name."""
        async with SessionLocal() as s:
            wfs = await WorkflowService.list(s, tenant_id, project_id)
            by_id = next((w for w in wfs if w.id == name_or_id), None)
            matches = [by_id] if by_id else [w for w in wfs if w.name == name_or_id]
            if not matches:
                return f"No workflow named or id '{name_or_id}'. Use list_resources to see what exists."
            if len(matches) > 1:
                listing = "; ".join(f"{w.name} (id {w.id}, {w.status})" for w in matches)
                return (f"{len(matches)} workflows are named '{name_or_id}'. Re-call delete_workflow with a "
                        f"specific id to remove just one: {listing}")
            wf = matches[0]
            await WorkflowService.delete(s, wf)
        mutated.append({"kind": "workflow_deleted", "name": wf.name})
        return f"Deleted workflow '{wf.name}' (id {wf.id}) and its run history."

    async def delegate_tool_execution(tool_id_or_capability: str, parameters_json: str = "{}", approval_id: str = "") -> str:
        """Execute an external tool securely by delegating to the Tool Manager system agent.
        The Master Agent has NO direct external tool access; all external tool execution must be
        mediated by Tool Manager. Tool Manager resolves the tool, verifies activation, caller
        entitlements, and human approval before execution. Pass tool_id_or_capability, optional
        parameters_json, and optional approval_id if resuming an approved execution."""
        from alberto.services.tool_manager import ToolManagerService
        try:
            params = json.loads(parameters_json) if parameters_json else {}
        except Exception:
            params = {}
        user_ctx = {
            "user_id": getattr(current_user, "id", None),
            "tenant_id": getattr(current_user, "tenant_id", tenant_id),
            "role": getattr(current_user, "role", "assistant"),
            "email": getattr(current_user, "email", None),
        } if current_user else {"role": "assistant", "tenant_id": tenant_id}
        exec_ctx = {"approval_id": approval_id} if approval_id else {}
        res = await ToolManagerService.execute_delegated_tool(
            tenant_id=tenant_id,
            project_id=project_id,
            tool_id_or_capability=tool_id_or_capability,
            parameters=params,
            user_context=user_ctx,
            execution_context=exec_ctx,
        )
        return json.dumps(res)

    def mk(fn, name):
        return StructuredTool.from_function(coroutine=fn, name=name, parse_docstring=False)

    return [
        mk(list_resources, "list_resources"),
        mk(describe_workflow, "describe_workflow"),
        mk(list_node_types, "list_node_types"),
        mk(get_node_schema, "get_node_schema"),
        mk(list_middleware_types, "list_middleware_types"),
        mk(create_agent_preset, "create_agent_preset"),
        mk(create_builtin_tool, "create_builtin_tool"),
        mk(create_rest_tool, "create_rest_tool"),
        mk(create_graphql_tool, "create_graphql_tool"),
        mk(create_sql_tool, "create_sql_tool"),
        mk(create_code_tool, "create_code_tool"),
        mk(create_mcp_tool, "create_mcp_tool"),
        mk(create_component, "create_component"),
        mk(create_auth_provider, "create_auth_provider"),
        mk(add_qa_pair, "add_qa_pair"),
        mk(add_knowledge_text, "add_knowledge_text"),
        mk(create_grounded_workflow, "create_grounded_workflow"),
        mk(create_intent_router_workflow, "create_intent_router_workflow"),
        mk(create_custom_workflow, "create_custom_workflow"),
        mk(add_human_review, "add_human_review"),
        mk(test_workflow, "test_workflow"),
        mk(evaluate_build, "evaluate_build"),
        mk(delete_workflow, "delete_workflow"),
        mk(delegate_tool_execution, "delegate_tool_execution"),
    ]


SYSTEM_PROMPT = """You are the Forge Assistant - an expert copilot embedded in Forge, a platform for \
building, testing, and shipping AI agents and workflows. You help the user build INTO their current project \
by calling your tools, and you explain how Forge works.

What you can do (use your tools to actually do these - don't just describe them):
- Inspect the project (list_resources, describe_workflow) and the platform itself (list_node_types, get_node_schema, list_middleware_types - the LIVE node/middleware catalog; read these before building anything custom).
- Create tools of every kind: create_rest_tool (path/query/header/body params, any method), create_graphql_tool, create_sql_tool, create_code_tool (sandboxed Python), create_mcp_tool (register an external MCP server), and create_builtin_tool (builtins include knowledge_search, which lets an agent search the knowledge base itself). Also reusable agent presets (create_agent_preset - takes instructions/model/tools), auth providers (create_auth_provider), and generative-UI widgets (create_component - sandboxed HTML/CSS the agent renders, attached via an agent's config.components).
- Grow the knowledge base (add_qa_pair - `kind` is a free-form category; add_knowledge_text - `folder` organizes documents).
- Build workflows (all idempotent by name):
  • create_grounded_workflow - start → retrieval (BOTH docs + Q&A) → grounded agent → end. Use for "answer from my knowledge base" chatbots, including "check my Q&A/FAQs and the knowledge base" - the retrieval step pulls both. HITL options: review_before_reply=True (human approves the draft before it's final) and approve_tools='a, b' (those tool calls pause for approval).
  • create_intent_router_workflow - start → classifier (structured output picks ONE intent) → router (one case per intent) → a specialist agent per intent + a general fallback. Use when different request types need different handling AND each request has a single intent.
  • create_custom_workflow - ANY other shape, from a full definition JSON (state/entry_node/nodes/edges). It validates and returns field-pointer errors you must fix. Use for multi-intent fan-out (classifier multi_label + router multi + synthesizer agent), tool_call pipelines, webhook flows, or anything the canned builders can't express. Read the forge-platform skill first.
- GIVE AGENTS KNOWLEDGE DIRECTLY. An agent node can search the project knowledge base itself - set its config.knowledge: {"rag": {"enabled": true, "folders": [...], "top_k": 4}, "qa": {"enabled": true, "kinds": [...]}}. This compiles to agent-callable tools (search_knowledge_base for documents, lookup_faq for curated answers), each toggled and scoped independently. PREFER this over wiring a separate retrieval node OR creating a knowledge_search Tool whenever the agent is conversational or may get multi-part questions - the agent searches per sub-question with its own phrasing instead of one fixed search on the whole message. Use the fixed retrieval NODE only when grounding must be guaranteed (the agent can't skip it).
- MULTI-INTENT questions ("one message asks two things"): prefer ONE agent with config.knowledge enabled (rag and/or qa) - it searches each sub-question separately and composes one answer - over a classifier→router, which answers only one part. For parallel specialists, use classifier multi_label=true + router multi=true + a synthesizer agent before end (see the forge-platform skill).
- Verify and judge your own work (test_workflow, then evaluate_build).
- Delete a workflow to clean up duplicates (delete_workflow - the run PAUSES for human approval before deleting).
- Execute external tools via Tool Manager (delegate_tool_execution - pass tool_id_or_capability, optional parameters_json, and optional approval_id; the Master Agent has no direct external tool access, all external tool execution must be mediated by Tool Manager).

How Forge concepts work, so you can explain them:
- A WORKFLOW is a graph of nodes wired start → … → end. Messages flow through. Common nodes: \
'retrieval' (RAG - pulls relevant knowledge-base docs + Q&A pairs for the question), \
'agent' (a model with tools and a system prompt that reasons and replies), 'classifier' (structured output picks one \
intent label into state), 'router' (branches on a state value via cases), 'human_input' (PAUSES the run with a real \
LangGraph interrupt until a human approves/rejects in the Playground). The recommended grounded chatbot is \
start → retrieval → agent → end, where the agent's prompt restricts it to the retrieved knowledge.
- HUMAN-IN-THE-LOOP means a real interrupt: either a 'human_input' node in the graph (review_before_reply on \
create_grounded_workflow, or add_human_review for an EXISTING workflow) or HumanInTheLoopMiddleware on the agent \
(approve_tools). NEVER fake HITL by telling the agent to "ask for approval" or "reply yes/no" in its instructions - \
prompt text does not pause anything. If the user says HITL/approval/review and the workflow exists, call \
add_human_review; if building new, pass review_before_reply=True. Then VERIFY with test_workflow that the run \
pauses (nodes_visited ends in '__interrupt__').
- A TOOL is an external capability (REST/GraphQL/builtin) an agent can call; response projection trims the payload to save tokens.
- An AUTH PROVIDER holds a reusable credential/session strategy that tools attach to.
- KNOWLEDGE = documents + Q&A pairs that ground answers.

Rules:
- When the user asks you to build/add/create something, CALL the appropriate tool, then confirm in one or two plain sentences what you did and what to do next (e.g. 'Test it in the Playground').
- WORK UNTIL IT'S CORRECT. For any build or change: (1) plan the steps with write_todos, (2) inspect what exists with list_resources, (3) build with the right tool, (4) VERIFY with test_workflow - try a realistic question, a greeting, an off-topic question, and EVERY branch/intent, (5) JUDGE with evaluate_build (pass it the user's request, what you built, and the test results) - if the verdict is 'fail', fix the issues and re-verify. Do not report success until both verification and the judge passed.
- MATCH THE REQUEST. Read what the user actually described and pick the right builder + parameters - do NOT default everything to create_grounded_workflow. If they say "use my Q&A/FAQs and the knowledge base", that's still create_grounded_workflow - its retrieval step already pulls BOTH Q&A pairs and documents. If they give specific agent instructions, persona, or a model, pass them via `instructions`/`model`. Name the workflow after what they asked for.
- TRIAGE FIRST (design for real conversations). Real users open with greetings and meta questions ("hi", "what can you do?", "how can you help me?") as often as real support questions. Do NOT pipe those straight into retrieval - they miss and dead-end at a "no relevant data → create a ticket" path, which is a terrible first impression. For any support/Q&A/RAG/ticketing workflow you design with create_custom_workflow, put a triage step right after start: a classifier (e.g. labels: general, support) → router that sends greetings/smalltalk/meta/capability questions to a small friendly agent that answers directly ("here's what I can help with…") and ends, and routes ONLY genuine product/support questions into the retrieval/ticket pipeline. (A single front agent with config.knowledge enabled - so it both chats AND searches the KB per sub-question - is an acceptable, often simpler, alternative.) When you VERIFY, always test a greeting and a "what can you do?" message and confirm they get a friendly direct reply - never the ticket path.
- AVOID DUPLICATES. Before creating a workflow, call list_resources to see what already exists. If a suitable workflow is already there, UPDATE it (reuse the same name - the builders update in place) or point the user to it. Only create a new one when the user clearly wants an additional, distinct workflow. Never create the same workflow twice in a session.
- When the user asks how something works or to explain their setup, call list_resources / describe_workflow first, then explain clearly and briefly.
- If the user wants to remove something or clean up duplicates, use delete_workflow (by exact name or id). Confirm the specific target first if the name is ambiguous.
- Be concise and concrete. Prefer doing over talking. Never claim you did something you didn't do via a tool."""


# The orchestrating assistant juggles ~19 tools and a long policy prompt - small models
# routinely ignore parameters like review_before_reply. Prefer the provider's strong
# model for the assistant itself (workflow agents keep the cheaper project default).
# Skills directory for assistant capabilities
_SKILLS_DIR = Path(__file__).resolve().parents[1] / "assistant_skills"


def _assistant_model_ref(ctx) -> str:
    """The model ref the assistant (and its judge) should run on:
    1. Explicitly selected registered model / assistant_model from project config.
    2. Configured default registered model (default_model_id or default_model).
    3. Explicitly configured and permitted fallback_model, if supported.
    A cloud API key in configuration is NEVER used to automatically select a provider.
    """
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
    default_setting = getattr(settings, "default_model", None)
    if default_setting:
        return default_setting
    raise ValueError("No model configured or available. Please configure an assistant model or default registered model.")


class AssistantService:
    @staticmethod
    async def _build_agent(*, tenant_id: str, project_id: str, checkpointer, mutated: list, model_override: str | None = None, current_user: Any = None):
        # Deep agent: adds planning (write_todos), virtual files, summarization, skills,
        # and HITL on top of the Forge tools - so it can take a multi-step request,
        # build, verify with test_workflow, judge with evaluate_build, and keep
        # iterating until the result is actually correct.
        from deepagents import FilesystemPermission, create_deep_agent
        from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
        from langchain.agents.middleware import ModelFallbackMiddleware

        async with SessionLocal() as s:
            ctx = await build_compile_context(s, tenant_id=tenant_id, project_id=project_id, load_tools=False)
            proj = (await s.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
            ctx.project_config = (proj.config or {}) if proj else {}

        primary_ref = model_override or _assistant_model_ref(ctx)
        model = resolve_model(primary_ref, ctx, params={"thinking": True})
        middleware = []
        # If the strong model is unavailable at call time (bad ref, provider outage),
        # fall back to the project's default model instead of failing the assistant.
        fallback_ref = ctx.default_model
        if fallback_ref and fallback_ref != primary_ref and not str(fallback_ref).startswith("fake"):
            middleware.append(ModelFallbackMiddleware(resolve_model(fallback_ref, ctx)))

        # Optionally prune the (large) tool set per turn to cut tool-schema tokens.
        from alberto.config import settings as _settings
        if _settings.assistant_tool_selector:
            from langchain.agents.middleware import LLMToolSelectorMiddleware
            middleware.append(LLMToolSelectorMiddleware(model=model, max_tools=12))

        # Milestone 2.2: Contextual memory recall hook
        from alberto.nodes.agent_node import MemoryRecallMiddleware
        middleware.append(MemoryRecallMiddleware(tenant_id=tenant_id, project_id=project_id))

        tools = build_assistant_tools(tenant_id, project_id, mutated, current_user=current_user)
        kwargs: dict[str, Any] = {
            "model": model,
            "tools": tools,
            "system_prompt": SYSTEM_PROMPT,
            "middleware": middleware,
        }
        # The forge-platform skill (progressive disclosure: name+description at startup,
        # full guide read on demand) carries deep how-to knowledge without prompt bloat.
        if _SKILLS_DIR.exists():
            kwargs["backend"] = CompositeBackend(
                default=StateBackend(),
                routes={"/skills/": FilesystemBackend(root_dir=str(_SKILLS_DIR), virtual_mode=True)},
            )
            kwargs["skills"] = ["/skills/"]
            kwargs["permissions"] = [
                FilesystemPermission(operations=["write"], paths=["/skills/**"], mode="deny"),
            ]
        # Destructive ops pause for human approval - REAL interrupts (needs checkpointer).
        if checkpointer is not None:
            kwargs["checkpointer"] = checkpointer
            kwargs["interrupt_on"] = {"delete_workflow": True}
        return create_deep_agent(**kwargs)

    @staticmethod
    async def _persist_trace(
        *, tenant_id: str, project_id: str, thread_id: str | None, tracer,
        user_message: str = "", ai_response: str = "",
        token_metrics: dict | None = None,
        retrieval_meta: dict | None = None,
        error: str | None = None, status: str = "done",
        persona: str | None = None,
    ) -> None:
        """Persist one assistant turn as a Trace (name='assistant') + spans, so SPEND and
        the per-project reports include assistant usage like any workflow run. The turn is
        shown as a 'System' conversation in the Traces view (the Forge Assistant is internal)."""
        import uuid as _uuid
        from datetime import datetime

        from alberto.models import Span, Trace

        spans = tracer.ordered()
        if not spans:
            return
        tokens, cost = tracer.totals()
        started = min((s.start for s in spans), default=0.0)
        latency_ms = int((max((s.end or s.start for s in spans), default=started) - started) * 1000)
        trace_id = None
        try:
            async with SessionLocal() as s:
                trace_meta: dict[str, Any] = {}
                if token_metrics:
                    trace_meta["token_metrics"] = token_metrics
                if retrieval_meta:
                    trace_meta["retrieval"] = retrieval_meta
                is_curator = persona == "memory_curator"
                is_mgr = persona in ("tool_manager", "integration_manager")
                trace_name = "memory_curator" if is_curator else ("tool_manager" if is_mgr else "assistant")
                actor_name = "Memory Curator" if is_curator else ("Integration Manager" if is_mgr else "System")
                trace = Trace(
                    tenant_id=tenant_id, project_id=project_id, workflow_id=None,
                    run_id=f"assistant-{_uuid.uuid4()}", thread_id=thread_id,
                    name=trace_name, status=status,
                    started_at=datetime.utcnow(), ended_at=datetime.utcnow(),
                    latency_ms=latency_ms, total_tokens=tokens, total_cost_usd=cost,
                    source=trace_name,
                    actor=actor_name,
                    user_message=(user_message or None), ai_response=(ai_response or None),
                    error=(error or None),
                    meta=trace_meta,
                )
                s.add(trace)
                await s.flush()
                trace_id = trace.id
                for sr in spans:
                    s.add(Span(
                        id=sr.id, tenant_id=tenant_id, trace_id=trace.id,
                        parent_span_id=sr.parent_id, name=sr.name, kind=sr.kind,
                        latency_ms=sr.latency_ms, input=sr.input, output=sr.output, model=sr.model,
                        input_tokens=sr.input_tokens, output_tokens=sr.output_tokens,
                        cost_usd=sr.cost_usd, error=sr.error, attributes=sr.attributes,
                    ))
                await s.commit()

            # Schedule conversation learning asynchronously if turn completed successfully
            if status == "done" and user_message and ai_response and trace_id:
                try:
                    from alberto.services.learning_coordinator import LearningCoordinator
                    await LearningCoordinator.schedule_turn_learning(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_event_id=trace_id,
                        user_message=user_message,
                        ai_response=ai_response,
                    )
                except Exception as le:
                    log.warning("Failed to schedule assistant turn learning for trace %s: %s", trace_id, le)
        except Exception:  # noqa: BLE001 - tracing must never break the assistant
            pass

    @staticmethod
    async def _run(agent, payload, config, mutated: list) -> AsyncIterator[dict]:
        """Stream one agent turn: narration tokens, tool chips, todo updates, then either
        an interrupt frame (HITL approval needed) or done."""
        async for mode, chunk in agent.astream(payload, config, stream_mode=["messages", "updates"]):
            if mode == "messages":
                msg, _meta = chunk if isinstance(chunk, (list, tuple)) and len(chunk) == 2 else (chunk, {})
                # Only the agent's own narration - never echo tool-result or human messages.
                if getattr(msg, "type", "") not in ("ai", "AIMessageChunk"):
                    continue
                text = content_to_text(getattr(msg, "content", ""))
                if text:
                    # `id` segments the stream per AI message: the panel shows earlier
                    # segments as collapsible "thinking" and only the last as the answer.
                    yield {"event": "messages", "data": {"content": text, "id": getattr(msg, "id", None)}}
            elif mode == "updates" and isinstance(chunk, dict):
                for node_out in chunk.values():
                    if not isinstance(node_out, dict):
                        continue
                    # Plan visibility: surface write_todos state to the panel.
                    if node_out.get("todos") is not None:
                        yield {"event": "todos", "data": {"todos": jsonable(node_out["todos"])}}
                    for m in node_out.get("messages", []):
                        if getattr(m, "type", None) == "tool":
                            yield {"event": "tool", "data": {"name": getattr(m, "name", "tool"), "result": content_to_text(getattr(m, "content", ""))[:2000]}}

        snapshot = await agent.aget_state(config)
        interrupts = [
            jsonable(getattr(t, "interrupts", None))
            for t in getattr(snapshot, "tasks", [])
            if getattr(t, "interrupts", None)
        ]
        if interrupts:
            yield {"event": "interrupt", "data": {"interrupts": interrupts}}
        tracer_cb = next((cb for cb in config.get("callbacks", []) if hasattr(cb, "totals")), None)
        in_tok, out_tok, total_tok = tracer_cb.token_totals() if (tracer_cb and hasattr(tracer_cb, "token_totals")) else (0, 0, tracer_cb.totals()[0] if tracer_cb else 0)
        has_usage = tracer_cb.has_token_counts() if (tracer_cb and hasattr(tracer_cb, "has_token_counts")) else (total_tok > 0)
        yield {
            "event": "done",
            "data": {
                "mutated": mutated,
                "interrupted": bool(interrupts),
                "tokens": total_tok if has_usage else None,
                "prompt_tokens": in_tok if has_usage else None,
                "completion_tokens": out_tok if has_usage else None,
                "total_tokens": total_tok if has_usage else None,
            },
        }

    @staticmethod
    async def _fast_stream(
        *, tenant_id: str, project_id: str, messages: list[dict],
        thread_id: str | None = None, model: str | None = None,
        persona: str | None = None, current_user: Any = None,
    ) -> AsyncIterator[dict]:
        import time

        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from alberto.tracing.tracer import ForgeTracer

        tracer = ForgeTracer()
        async with SessionLocal() as s:
            ctx = await build_compile_context(s, tenant_id=tenant_id, project_id=project_id, load_tools=False)
            proj = (await s.execute(select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id))).scalar_one_or_none()
            ctx.project_config = (proj.config or {}) if proj else {}

            primary_ref = model or _assistant_model_ref(ctx)
            model_inst = resolve_model(primary_ref, ctx, params={"thinking": False})

            user_msg = next((m.get("content", "") for m in reversed(messages) if m.get("role") in ("user", "human")), "")
            user_lower = user_msg.lower()

            # Fast mode tool binding & live integration context
            is_tool_mgr = persona in ("tool_manager", "integration_manager")
            is_assistant = persona in (None, "", "assistant")

            tools_to_bind = []
            if is_tool_mgr or is_assistant:
                all_tools = build_assistant_tools(tenant_id, project_id, [], current_user=current_user)
                tools_to_bind = [t for t in all_tools if t.name in ("list_resources", "describe_workflow", "delegate_tool_execution")]

            runnable = model_inst.bind_tools(tools_to_bind) if tools_to_bind else model_inst

            integration_context = ""
            if is_tool_mgr or is_assistant:
                try:
                    from alberto.models import ConnectorInstall, McpClient, Tool
                    mcps = (await s.execute(select(McpClient).where(McpClient.tenant_id == tenant_id, McpClient.project_id == project_id))).scalars().all()
                    conns = (await s.execute(select(ConnectorInstall).where(ConnectorInstall.tenant_id == tenant_id, ConnectorInstall.project_id == project_id))).scalars().all()
                    tools = (await s.execute(select(Tool).where(Tool.tenant_id == tenant_id, Tool.project_id == project_id))).scalars().all()

                    mcp_lines = []
                    for m in mcps:
                        is_ha = "8123" in (m.url or "") or m.name.upper() == "HA" or "homeassistant" in (m.url or "").lower()
                        label = f"{m.name} (Home Assistant)" if is_ha else m.name
                        status = "enabled" if m.enabled else "disabled"
                        m_tools = [t.name for t in tools if t.kind == "mcp" and (t.name.startswith("ha_") if is_ha else True)]
                        tool_sample = ", ".join(m_tools[:8]) + (f" (+{len(m_tools) - 8} more)" if len(m_tools) > 8 else "")
                        mcp_lines.append(f"- MCP Client: {label} [{status}] | Transport: {m.transport} | URL: {m.url or '(none)'} | Registered Tools ({len(m_tools)}): {tool_sample or '(none)'}")

                    conn_lines = [f"- Connector: {c.name or c.slug} [{c.status}] (version {c.version})" for c in conns]

                    integration_context = (
                        "\n\n[PROJECT REGISTERED INTEGRATIONS & MCP REGISTRY]\n"
                        f"Active MCP Servers ({len(mcps)}):\n" + ("\n".join(mcp_lines) if mcp_lines else "None\n") +
                        f"\nInstalled Connectors ({len(conns)}):\n" + ("\n".join(conn_lines) if conn_lines else "None\n") +
                        f"\nTotal Registered Tools in Registry: {len(tools)}"
                    )
                except Exception as ie:
                    log.warning("Failed to build live integration context: %s", ie)

            if persona == "memory_curator":
                fast_sys_prompt = (
                    "You are Alberto's Memory Curator Sub-Agent. "
                    "Your duty is to curate, audit, explain, and organize durable memory records, user preferences, and knowledge graph entities. "
                    "You answer questions directly about stored facts, user details, hardware configurations, and system capabilities based on recalled memory. "
                    "Be clear, precise, and helpful. Always preserve technical terms, product names, acronyms, and specs verbatim. "
                    "When the user shares new durable facts, acknowledge them accurately so they can be persisted to long-term memory."
                )
            elif persona == "graph_manager":
                fast_sys_prompt = (
                    "You are Alberto's Knowledge Graph Manager Sub-Agent. "
                    "Your duty is to manage, inspect, and explain graph entities and relationships in Alberto's Knowledge Graph. "
                    "You answer questions directly about stored entities, relationship types, ontology classifications, and connected nodes based on recalled graph context. "
                    "Be clear, precise, and helpful. Always preserve node names, labels, and entity identifiers verbatim."
                )
            elif persona == "intent_router":
                fast_sys_prompt = (
                    "You are Alberto's Intent Router Sub-Agent. "
                    "Your duty is to classify user queries, analyze user requests, and explain how intents are routed across Alberto's tools and workflows. "
                    "Be clear, precise, and concise."
                )
            elif persona in ("tool_manager", "integration_manager"):
                fast_sys_prompt = (
                    "You are Alberto's Integration Manager Sub-Agent. "
                    "Your duty is to inspect, manage, and explain tools, MCP servers, connectors, "
                    "communication channels, and execution policies. "
                    "You help users test tool parameters, diagnose connectivity issues, verify authentication, "
                    "and understand Human-In-The-Loop approval requirements. "
                    "Be clear, precise, and technically accurate. Check the registered integrations and MCP servers list before answering."
                )
            elif persona and persona != "assistant":
                clean_name = persona.replace("_", " ").title()
                fast_sys_prompt = (
                    f"You are Alberto's {clean_name} Sub-Agent. "
                    "Be natural, helpful, and concise. Answer questions directly using recalled context."
                )
            else:
                fast_sys_prompt = (
                    "You are Alberto, a helpful, intelligent AI Home Butler. "
                    "Be natural, warm, and concise (1-3 sentences). Answer questions directly. "
                    "Always preserve user-provided technical terms, product names, acronyms, and model identifiers exactly as stated. "
                    "Never substitute, normalize, or autocorrect them with more common, popular, or phonetically similar alternatives unless the user explicitly tells you to. "
                    "SMART HOME CONTROL & INTEGRATIONS: You do NOT have a direct physical connection to devices. Instead, you delegate all device actions, light toggles, sensors, and external tools to the Integration Manager via the `delegate_tool_execution` tool. "
                    "For smart home actions with Home Assistant (HA), call `delegate_tool_execution(tool_id_or_capability='ha_manage_pipeline', parameters_json='{\"action\": \"process\", \"sentence\": \"<user command>\"}'). "
                    "If tool execution returns READ_ONLY_MODE, explain to the user that the Home Assistant MCP server has Read-Only Mode enabled and must be disabled in the ha-mcp add-on settings to allow smart home control. "
                    "If the user asks for multi-step automation design or deep reasoning, "
                    "mention they can toggle Deep Thinking mode or ask you to execute it."
                )

            if integration_context:
                fast_sys_prompt = f"{fast_sys_prompt}{integration_context}"

            # 1. Unified Knowledge & Memory Recall
            recalled_block = ""
            retrieval_meta: dict[str, Any] = {}
            if user_msg:
                try:
                    from alberto.services.context_assembler import ContextAssembler
                    from alberto.services.unified_memory import UnifiedMemoryManager

                    hits = await UnifiedMemoryManager.recall(
                        session=s,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        query=user_msg.strip(),
                        top_k=8 if persona == "memory_curator" else 5,
                    )
                    if hits:
                        recalled_block = ContextAssembler.assemble_context(hits)
                    retrieval_meta = {
                        "selected_sources": list(dict.fromkeys(h.source for h in hits)) if hits else [],
                        "matched_memory_ids": [h.record_id for h in hits],
                        "retrieved_context_items_count": len(hits),
                        "provenance": [h.provenance for h in hits if h.provenance],
                        "scores": [round(h.score, 3) for h in hits if h.score is not None],
                        "evidence_included": bool(recalled_block),
                    }
                except Exception as me:
                    log.warning("Assistant memory recall error: %s", me)
                    try:
                        await s.rollback()
                    except Exception:
                        pass

            if recalled_block:
                fast_sys_prompt = f"{fast_sys_prompt}\n\n{recalled_block}"

            # 2. Conversation History Retrieval & Context Window Budgeting
            history_turns: list[dict] = []
            if thread_id:
                from alberto.services.conversations import ConversationService

                try:
                    prior_traces = await ConversationService.turns(s, tenant_id, project_id, thread_id)
                    for pt in prior_traces:
                        if pt.user_message:
                            history_turns.append({"role": "user", "content": pt.user_message})
                        if pt.ai_response:
                            history_turns.append({"role": "assistant", "content": pt.ai_response})
                except Exception as he:
                    log.warning("Assistant history retrieval error: %s", he)
                    try:
                        await s.rollback()
                    except Exception:
                        pass

            if not history_turns and len(messages) > 1:
                # Explicit stateless messages sent by client
                history_turns = [m for m in messages if m.get("content")]
            elif user_msg:
                # Append current user prompt if not already present as the last turn
                if not (history_turns and history_turns[-1].get("role") == "user" and history_turns[-1].get("content") == user_msg):
                    history_turns.append({"role": "user", "content": user_msg})

            # Calculate context budget based on configured model context window
            reg = ctx.registered_models.get(primary_ref) or next((r for r in ctx.registered_models.values() if r.model_name == primary_ref), None)
            ctx_max = (reg.context_window_configured or reg.context_window_max or 32768) if reg else 32768
            max_output = (reg.max_output_tokens or 4096) if reg else 4096
            input_budget_chars = max(4000, (ctx_max - max_output) * 3)

            # Prioritize: (1) System prompt + (2) Current turn, then (3) Recent conversation turns
            if len(history_turns) > 1:
                current_turn_list = history_turns[-1:]
                older_turns = history_turns[:-1]
                base_chars = len(fast_sys_prompt) + len(current_turn_list[0].get("content", ""))
                available_chars = max(1000, input_budget_chars - base_chars)

                kept_older = []
                accum_chars = 0
                for m in reversed(older_turns):
                    c_len = len(m.get("content", ""))
                    if accum_chars + c_len > available_chars and kept_older:
                        break
                    kept_older.append(m)
                    accum_chars += c_len
                kept_older.reverse()
                final_turns = kept_older + current_turn_list
            else:
                final_turns = history_turns

            formatted_messages: list[Any] = [SystemMessage(content=fast_sys_prompt)]
            for m in final_turns:
                r = m.get("role", "user")
                c = m.get("content", "")
                if not c:
                    continue
                if r in ("user", "human"):
                    formatted_messages.append(HumanMessage(content=c))
                elif r in ("assistant", "ai"):
                    formatted_messages.append(AIMessage(content=c))

        config: Any = {"callbacks": [tracer]}
        final_text = ""
        err_msg: str | None = None
        t_start = time.monotonic()
        first_token_time: float | None = None
        last_token_time: float | None = None

        try:
            async for chunk in runnable.astream(formatted_messages, config=config):
                tool_calls = getattr(chunk, "tool_calls", None) or []
                if tool_calls:
                    for tc in tool_calls:
                        t_name = tc.get("name")
                        yield {"event": "tool", "data": {"name": t_name, "result": "running"}}
                        matched = next((t for t in tools_to_bind if t.name == t_name), None)
                        if matched:
                            try:
                                res = await matched.ainvoke(tc.get("args") or {})
                                yield {"event": "tool", "data": {"name": t_name, "result": str(res)}}
                                formatted_messages.append(AIMessage(content="", tool_calls=[tc]))
                                from langchain_core.messages import ToolMessage

                                formatted_messages.append(ToolMessage(tool_call_id=tc.get("id", "tc1"), content=str(res)))
                                async for follow_chunk in model_inst.astream(formatted_messages, config=config):
                                    txt = content_to_text(getattr(follow_chunk, "content", ""))
                                    if txt:
                                        if first_token_time is None:
                                            first_token_time = time.monotonic()
                                        last_token_time = time.monotonic()
                                        final_text += txt
                                        yield {"event": "messages", "data": {"content": txt}}
                            except Exception as te:
                                yield {"event": "error", "data": {"message": f"tool error: {te}"}}
                    continue

                txt = content_to_text(getattr(chunk, "content", ""))
                if txt:
                    if first_token_time is None:
                        first_token_time = time.monotonic()
                    last_token_time = time.monotonic()
                    final_text += txt
                    yield {"event": "messages", "data": {"content": txt}}

            in_tok, out_tok, total_tok = tracer.token_totals()
            has_usage = tracer.has_token_counts()
            yield {
                "event": "done",
                "data": {
                    "mutated": False,
                    "interrupted": False,
                    "tokens": total_tok if has_usage else None,
                    "prompt_tokens": in_tok if has_usage else None,
                    "completion_tokens": out_tok if has_usage else None,
                    "total_tokens": total_tok if has_usage else None,
                },
            }
        except Exception as e:
            err_msg = str(e)
            yield {"event": "error", "data": {"message": err_msg}}
        finally:
            ttft_s = (first_token_time - t_start) if first_token_time else None
            decode_s = (last_token_time - first_token_time) if (first_token_time and last_token_time) else None
            total_s = (time.monotonic() - t_start)
            in_tok, out_tok, total_tok = tracer.token_totals()
            has_usage = tracer.has_token_counts()
            tps = (out_tok / decode_s) if (has_usage and out_tok and decode_s and decode_s > 0.05) else None
            metrics = {
                "prompt_tokens": in_tok if has_usage else None,
                "completion_tokens": out_tok if has_usage else None,
                "total_tokens": total_tok if has_usage else None,
                "ttft_secs": round(ttft_s, 3) if ttft_s is not None else None,
                "decode_duration_secs": round(decode_s, 3) if decode_s is not None else None,
                "total_duration_secs": round(total_s, 3) if total_s is not None else None,
                "tokens_per_sec": round(tps, 1) if tps is not None else None,
            }
            await AssistantService._persist_trace(
                tenant_id=tenant_id, project_id=project_id, thread_id=thread_id, tracer=tracer,
                user_message=user_msg, ai_response=final_text,
                token_metrics=metrics,
                retrieval_meta=retrieval_meta,
                error=err_msg, status="error" if err_msg else "done",
                persona=persona,
            )

    @staticmethod
    async def stream(
        *, tenant_id: str, project_id: str, messages: list[dict],
        thread_id: str | None = None, checkpointer=None, model: str | None = None,
        thinking: bool = False, persona: str | None = None, current_user: Any = None,
    ) -> AsyncIterator[dict]:
        import time

        # Fast Butler Path: When thinking=False, skip heavy deep-agent loops & tool schemas
        if not thinking:
            async for frame in AssistantService._fast_stream(
                tenant_id=tenant_id, project_id=project_id, messages=messages,
                thread_id=thread_id, model=model, persona=persona, current_user=current_user,
            ):
                yield frame
            return

        mutated: list = []
        try:
            agent = await AssistantService._build_agent(
                tenant_id=tenant_id, project_id=project_id, checkpointer=checkpointer, mutated=mutated, model_override=model, current_user=current_user,
            )
        except Exception as e:  # noqa: BLE001
            yield {"event": "error", "data": {"message": f"assistant init failed: {e}"}}
            return

        lc_messages = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages if m.get("content")]
        # This turn's user text (for the Traces transcript).
        user_msg = next((m["content"] for m in reversed(lc_messages) if m.get("role", "user") in ("user", "human") and m.get("content")), "")
        final_text = ""
        from alberto.tracing.tracer import ForgeTracer

        tracer = ForgeTracer()
        # Generous recursion limit: the build→verify→judge→fix loop takes many steps.
        config: dict[str, Any] = {"recursion_limit": 100, "callbacks": [tracer]}
        if checkpointer is not None and thread_id:
            # Persistent conversation: the checkpointer holds history/todos/files for the
            # thread, so the frontend sends ONLY the new message.
            config["configurable"] = {"thread_id": f"assistant:{project_id}:{thread_id}"}
        t_start = time.monotonic()
        err_msg: str | None = None
        try:
            async for frame in AssistantService._run(agent, {"messages": lc_messages}, config, mutated):
                yield frame
            try:
                from alberto.services.runs import _last_ai_text

                snap = await agent.aget_state(config)
                final_text = _last_ai_text(getattr(snap, "values", {}) or {})
            except Exception:  # noqa: BLE001 - transcript capture must never break the turn
                pass
        except Exception as e:  # noqa: BLE001
            err_msg = str(e)
            yield {"event": "error", "data": {"message": str(e)}}
        finally:
            in_tok, out_tok, total_tok = tracer.token_totals()
            has_usage = tracer.has_token_counts()
            total_s = time.monotonic() - t_start
            metrics = {
                "prompt_tokens": in_tok if has_usage else None,
                "completion_tokens": out_tok if has_usage else None,
                "total_tokens": total_tok if has_usage else None,
                "total_duration_secs": round(total_s, 3),
            }
            await AssistantService._persist_trace(
                tenant_id=tenant_id, project_id=project_id, thread_id=thread_id, tracer=tracer,
                user_message=user_msg, ai_response=final_text,
                token_metrics=metrics,
                error=err_msg, status="error" if err_msg else "done",
                persona=persona,
            )

    @staticmethod
    async def resume(
        *, tenant_id: str, project_id: str, thread_id: str, decision: str = "approve",
        checkpointer=None, model: str | None = None,
        thinking: bool = False,
    ) -> AsyncIterator[dict]:
        """Resume after a HITL interrupt (e.g. delete_workflow approval)."""
        from langgraph.types import Command

        mutated: list = []
        if checkpointer is None or not thread_id:
            yield {"event": "error", "data": {"message": "resume requires a persistent assistant thread"}}
            return
        try:
            agent = await AssistantService._build_agent(
                tenant_id=tenant_id, project_id=project_id, checkpointer=checkpointer, mutated=mutated, model_override=model,
            )
        except Exception as e:  # noqa: BLE001
            yield {"event": "error", "data": {"message": f"assistant init failed: {e}"}}
            return
        from alberto.tracing.tracer import ForgeTracer

        tracer = ForgeTracer()
        config: dict[str, Any] = {
            "recursion_limit": 100,
            "configurable": {"thread_id": f"assistant:{project_id}:{thread_id}"},
            "callbacks": [tracer],
        }
        # HumanInTheLoopMiddleware resume shape: {"decisions": [{"type": "approve"|"reject"}]}.
        # If the paused turn had SEVERAL approval-gated tool calls, the middleware needs one
        # decision per call - expand the single UI decision to match (see _expand_hitl_decisions).
        from alberto.services.runs import _expand_hitl_decisions

        value: Any = {"decisions": [{"type": decision if decision in ("approve", "reject", "edit", "respond") else "approve"}]}
        value = await _expand_hitl_decisions(agent, config, value)
        try:
            async for frame in AssistantService._run(agent, Command(resume=value), config, mutated):
                yield frame
        except Exception as e:  # noqa: BLE001
            yield {"event": "error", "data": {"message": str(e)}}
        finally:
            await AssistantService._persist_trace(tenant_id=tenant_id, project_id=project_id, thread_id=thread_id, tracer=tracer)
