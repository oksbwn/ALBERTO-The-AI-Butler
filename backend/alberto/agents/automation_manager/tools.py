"""Automation Manager & Workflow Authoring StructuredTools."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import StructuredTool
from sqlalchemy import select

from alberto.config import settings
from alberto.db.base import SessionLocal
from alberto.engine.models import resolve_model
from alberto.models import Project, Workflow
from alberto.services.runtime import build_compile_context
from alberto.services.workflows import WorkflowService
from alberto.util.serialize import content_to_text, jsonable

log = logging.getLogger("alberto.agents.automation_manager.tools")

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

_CHAT_STATE = {
    "messages": {"type": "list[message]", "reducer": "add_messages"},
    "intent": {"type": "str", "reducer": "last"},
}


def _node(nid: str, ntype: str, cfg: dict, x: int, y: int) -> dict:
    return {"id": nid, "type": ntype, "config": cfg, "position": {"x": x, "y": y}}


def _warn_note(warnings: list | None) -> str:
    if not warnings:
        return ""
    msgs = "; ".join(w.get("message", "") for w in warnings[:3])
    return f" VALIDATION WARNINGS (fix if unintended): {msgs}"


def _model_is_offline(model) -> bool:
    """True for the offline `fake:` chat model, so the build judge can report 'unverified'
    instead of a bogus 'pass' when no real provider model is configured (finding F7)."""
    try:
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        return isinstance(model, GenericFakeChatModel)
    except Exception:  # noqa: BLE001
        return False


def _canvas(nodes: list[dict], edges: list[dict]) -> dict:
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
            {
                "id": n["id"],
                "type": "forge",
                "position": n["position"],
                "data": {"nodeType": n["type"], "config": n["config"]},
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": f"e{i}",
                "source": e["source"],
                "target": e["target"],
                **({"sourceHandle": source_handle(e)} if source_handle(e) else {}),
                **({"label": str(e["label"])} if e.get("label") is not None else {}),
            }
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


def _assistant_model_ref(ctx) -> str:
    """The model ref the assistant (and its judge) should run on."""
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


def build_automation_manager_tools(tenant_id: str, project_id: str, mutated: list, current_user: Any = None) -> list:
    """Build Workflow Authoring, Inspection, and Delegation StructuredTools for a project."""

    async def describe_workflow(name_or_id: str = "") -> str:
        """Describe a workflow's structure (its nodes and how they connect) so you can explain how it works. Pass a name or id; empty picks the active workflow."""
        async with SessionLocal() as s:
            wfs = (
                await s.execute(select(Workflow).where(Workflow.tenant_id == tenant_id, Workflow.project_id == project_id))
            ).scalars().all()
            wf = None
            if name_or_id:
                wf = next((w for w in wfs if w.id == name_or_id or w.name.lower() == name_or_id.lower()), None)
            wf = wf or next((w for w in wfs if w.status == "active"), None) or (wfs[0] if wfs else None)
            if not wf:
                return "No workflows exist yet."
            ex = wf.executable or {}
            nodes = [
                {
                    "id": n["id"],
                    "type": n["type"],
                    "config": {k: v for k, v in (n.get("config") or {}).items() if k in ("model", "name", "top_k", "expression")},
                }
                for n in ex.get("nodes", [])
            ]
            edges = [f"{e['source']} → {e['target']}" for e in ex.get("edges", [])]
            return json.dumps({"name": wf.name, "status": wf.status, "nodes": nodes, "flow": edges})

    def _auto_declare_state(nodes: list, state: dict) -> dict:
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
        s,
        *,
        name: str,
        description: str,
        nodes: list,
        edges: list,
        state: dict,
        entry_node: str = "start",
    ) -> tuple[str, str, list]:
        ex = {
            "id": "wf",
            "version": 1,
            "state": _auto_declare_state(nodes, state),
            "entry_node": entry_node,
            "global_middleware": [{"type": "model_call_limit", "config": {"run_limit": 25}}],
            "nodes": nodes,
            "edges": edges,
        }
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
        try:
            from alberto.services.automation_manager import AutomationManagerService

            sessions = await AutomationManagerService.list_sessions(s, tenant_id, project_id)
            target_sess = next(
                (
                    sess
                    for sess in sessions
                    if sess.status in ("planning", "clarifying") and not (sess.proposal and sess.proposal.get("executable"))
                ),
                None,
            )
            if not target_sess:
                target_sess = await AutomationManagerService.create_session(
                    session=s,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    user_id=getattr(current_user, "id", None),
                    requirement=f"{name}: {description}",
                )
            canvas_obj = _canvas(nodes, edges)
            target_sess.proposal = {
                "workflow_id": wf.id,
                "title": name,
                "strategy": "single_agent",
                "description": description,
                "executable": ex,
                "canvas": canvas_obj,
                "proposed_agents": [],
                "reused_agents": [],
                "reused_tools": [],
                "missing_capabilities": [],
                "explanation": description,
                "validation": {"valid": True, "errors": [], "warnings": result.warnings},
            }
            target_sess.validation_status = "valid"
            target_sess.status = "activated"
            target_sess.revision = (target_sess.revision or 1) + 1
            await s.commit()
        except Exception as sync_err:
            log.warning("Failed to sync workflow save to automation session: %s", sync_err)
        return verb, "", result.warnings

    async def create_grounded_workflow(
        name: str = "Grounded support",
        instructions: str = "",
        model: str = "",
        review_before_reply: bool = False,
        approve_tools: str = "",
    ) -> str:
        """Create OR UPDATE a grounded support workflow: start → retrieval → grounded agent → end."""
        async with SessionLocal() as s:
            mdl = model or await _default_agent_model(s, tenant_id, project_id)
            agent_cfg: dict[str, Any] = {
                "flavor": "agent",
                "name": "support_agent",
                "model": mdl,
                "system_prompt": instructions or GROUNDING_PROMPT,
                "middleware": [
                    {
                        "type": "summarization",
                        "enabled": True,
                        "config": {"trigger": ["tokens", 6000], "keep": ["messages", 6]},
                    }
                ],
            }
            tool_names = [t.strip() for t in approve_tools.split(",") if t.strip()]
            if tool_names:
                agent_cfg["middleware"].append(
                    {
                        "type": "human_in_the_loop",
                        "enabled": True,
                        "config": {"interrupt_on": {t: True for t in tool_names}},
                    }
                )
            nodes = [
                _node("start", "start", {}, 40, 180),
                _node("retrieval_1", "retrieval", {"top_k": 4, "include_qa": True, "announce_empty": True, "min_score": 0.18}, 300, 180),
                _node("agent_1", "agent", agent_cfg, 560, 180),
            ]
            edges = [{"source": "start", "target": "retrieval_1"}, {"source": "retrieval_1", "target": "agent_1"}]
            if review_before_reply:
                nodes.append(
                    _node(
                        "review_1",
                        "human_input",
                        {"prompt": "Review the agent's draft reply above and approve or reject it.", "allowed_decisions": ["approve", "reject"]},
                        820,
                        180,
                    )
                )
                nodes.append(_node("end", "end", {}, 1080, 180))
                edges += [{"source": "agent_1", "target": "review_1"}, {"source": "review_1", "target": "end"}]
            else:
                nodes.append(_node("end", "end", {}, 840, 180))
                edges += [{"source": "agent_1", "target": "end"}]
            verb, err, warns = await _save_workflow(
                s,
                name=name,
                description="Retrieval-grounded support agent over the project knowledge base + FAQs.",
                nodes=nodes,
                edges=edges,
                state=_CHAT_STATE,
            )
        if err:
            return "ERROR: " + err
        hitl_note = (
            " Includes a human review pause before the final reply."
            if review_before_reply
            else (f" Tool calls requiring approval: {', '.join(tool_names)}." if tool_names else "")
        )
        return f"{verb} grounded workflow '{name}': start → retrieval (docs + Q&A) → agent → {'review → ' if review_before_reply else ''}end.{hitl_note}{_warn_note(warns)} Test it in the Playground."

    async def create_intent_router_workflow(
        name: str = "Intent router",
        intents: str = "",
        instructions: str = "",
        model: str = "",
    ) -> str:
        """Create OR UPDATE an intent-routing workflow (the classify-then-route pattern)."""
        labels = [i.strip().replace(" ", "_") for i in intents.split(",") if i.strip()]
        if len(labels) < 2:
            return "ERROR: pass at least 2 comma-separated intents, e.g. intents='return_item, cancel_subscription'."
        async with SessionLocal() as s:
            mdl = model or await _default_agent_model(s, tenant_id, project_id)
            base = instructions or "Be concise and helpful."
            nodes = [
                _node("start", "start", {}, 40, 220),
                _node("classify", "classifier", {"labels": labels, "output_key": "intent", "model": mdl}, 260, 220),
                _node(
                    "route",
                    "router",
                    {"expression": "intent", "cases": {label: f"{label}_agent" for label in labels}, "default": "general_agent"},
                    520,
                    220,
                ),
            ]
            edges = [{"source": "start", "target": "classify"}, {"source": "classify", "target": "route"}]
            for i, label in enumerate(labels):
                agent_id = f"{label}_agent"
                nodes.append(
                    _node(
                        agent_id,
                        "agent",
                        {
                            "flavor": "agent",
                            "name": agent_id,
                            "model": mdl,
                            "system_prompt": f"You are the specialist for '{label.replace('_', ' ')}' requests. {base}",
                        },
                        800,
                        80 + i * 140,
                    )
                )
                edges.append({"source": "route", "target": agent_id, "label": label})
                edges.append({"source": agent_id, "target": "end"})
            nodes.append(
                _node(
                    "general_agent",
                    "agent",
                    {
                        "flavor": "agent",
                        "name": "general_agent",
                        "model": mdl,
                        "system_prompt": f"You handle anything that doesn't fit a known category. {base}",
                    },
                    800,
                    80 + len(labels) * 140,
                )
            )
            edges.append({"source": "route", "target": "general_agent", "label": "else"})
            edges.append({"source": "general_agent", "target": "end"})
            nodes.append(_node("end", "end", {}, 1080, 220))
            verb, err, warns = await _save_workflow(
                s,
                name=name,
                description=f"Classifies into {', '.join(labels)} and routes to a specialist agent per intent.",
                nodes=nodes,
                edges=edges,
                state=_CHAT_STATE,
            )
        if err:
            return "ERROR: " + err
        return f"{verb} intent-router workflow '{name}': classifier → router → one specialist per intent ({', '.join(labels)}) + a general fallback.{_warn_note(warns)} Test each intent in the Playground."

    async def add_human_review(
        workflow_name_or_id: str,
        prompt: str = "Review the draft reply and approve or reject.",
    ) -> str:
        """Insert a REAL human-approval pause (a human_input interrupt node) into an EXISTING workflow."""
        async with SessionLocal() as s:
            wfs = await WorkflowService.list(s, tenant_id, project_id)
            wf = next((w for w in wfs if w.id == workflow_name_or_id), None) or next(
                (w for w in wfs if w.name.lower() == workflow_name_or_id.lower()), None
            )
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
                gate = _node(
                    "human_review",
                    "human_input",
                    {"prompt": prompt, "allowed_decisions": ["approve", "reject"]},
                    max(0, first_end["position"]["x"] - 240),
                    first_end["position"]["y"] + 120,
                )
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
            verb, err, warns = await _save_workflow(
                s,
                name=wf.name,
                description=wf.description or "",
                nodes=nodes,
                edges=edges,
                state=ex.get("state") or _CHAT_STATE,
                entry_node=ex.get("entry_node") or "start",
            )
        if err:
            return "ERROR: " + err
        return f"Added a human-review pause to '{wf.name}': every reply now stops at an approval gate before finishing.{_warn_note(warns)} Test it in the Playground - the run will pause with approve/reject buttons."

    async def test_workflow(name_or_id: str, message: str) -> str:
        """Run a workflow with a test message and return its final answer plus the nodes it visited."""
        import uuid as _uuid

        from langgraph.checkpoint.memory import InMemorySaver

        from alberto.engine.compiler import compile_workflow

        async with SessionLocal() as s:
            wfs = await WorkflowService.list(s, tenant_id, project_id)
            wf = next((w for w in wfs if w.id == name_or_id), None) or next(
                (w for w in wfs if w.name.lower() == name_or_id.lower()), None
            )
            if not wf:
                return f"No workflow named or id '{name_or_id}'. Use list_resources first."
            ctx = await build_compile_context(s, tenant_id=tenant_id, project_id=project_id, checkpointer=InMemorySaver())
            try:
                graph = compile_workflow(wf.executable or {}, ctx)
            except Exception as e:  # noqa: BLE001
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
                stream_mode=["updates", "values"],
                subgraphs=True,
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
        return json.dumps(
            {
                "workflow": wf.name,
                "nodes_visited": visited,
                "answer": final[:600] or "(no answer produced)",
                "interrupted": interrupted,
                "interrupts": interrupt_payloads,
            }
        )

    async def list_node_types() -> str:
        """The LIVE catalog of workflow node types."""
        from alberto.engine.registry import all_specs
        from alberto.schemas import contracts

        out = []
        for spec in all_specs():
            schema = contracts.raw_schema(spec.schema_id) or {}
            out.append(
                {
                    "type": spec.type,
                    "label": spec.label,
                    "category": spec.category,
                    "description": spec.description,
                    "config_keys": sorted((schema.get("properties") or {}).keys()),
                    "required": schema.get("required", []),
                }
            )
        return json.dumps(out)

    async def get_node_schema(node_type: str) -> str:
        """Full JSON config schema for one node type."""
        from alberto.engine.registry import NODE_REGISTRY
        from alberto.schemas import contracts

        spec = NODE_REGISTRY.get(node_type)
        if not spec:
            return f"ERROR: unknown node type '{node_type}'. Call list_node_types first."
        return json.dumps(contracts.raw_schema(spec.schema_id) or {})

    async def list_middleware_types() -> str:
        """All agent middleware types with their config schemas."""
        from alberto.schemas import contracts

        out = {t: contracts.middleware_config_schema(t) for t in contracts.middleware_types()}
        return json.dumps(out)

    async def create_custom_workflow(name: str, description: str, definition_json: str) -> str:
        """Build ANY workflow shape from a full definition JSON."""
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
                s,
                name=name,
                description=description or "Custom workflow built by the assistant.",
                nodes=nodes,
                edges=edges,
                state=state,
                entry_node=entry,
            )
        if err:
            return "ERROR: " + err + " - fix the definition and call create_custom_workflow again."
        shape = " → ".join(n["id"] for n in nodes[:6]) + ("…" if len(nodes) > 6 else "")
        return f"{verb} custom workflow '{name}' ({len(nodes)} nodes: {shape}).{_warn_note(warns)} Now VERIFY it with test_workflow."

    async def evaluate_build(user_request: str, what_was_built: str, test_results: str) -> str:
        """LLM judge for your own work."""
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
        if _model_is_offline(model):
            return json.dumps(
                {
                    "verdict": "unverified",
                    "issues": ["No real model configured; ran on the offline model, so the build was NOT independently verified."],
                    "next_steps": ["Add a provider API key in project settings, then re-run evaluate_build; meanwhile self-review the test_workflow results."],
                }
            )
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
            return json.dumps(
                res
                if isinstance(res, dict)
                else getattr(res, "__dict__", {"verdict": "fail", "issues": ["judge returned an unexpected shape"]})
            )
        except Exception as e:  # noqa: BLE001
            return json.dumps(
                {
                    "verdict": "unverified",
                    "issues": [f"judge unavailable ({e}); self-review the test results instead"],
                    "next_steps": [],
                }
            )

    async def delete_workflow(name_or_id: str) -> str:
        """Delete a workflow by its exact name or id."""
        async with SessionLocal() as s:
            wfs = await WorkflowService.list(s, tenant_id, project_id)
            by_id = next((w for w in wfs if w.id == name_or_id), None)
            matches = [by_id] if by_id else [w for w in wfs if w.name == name_or_id]
            if not matches:
                return f"No workflow named or id '{name_or_id}'. Use list_resources to see what exists."
            if len(matches) > 1:
                listing = "; ".join(f"{w.name} (id {w.id}, {w.status})" for w in matches)
                return (
                    f"{len(matches)} workflows are named '{name_or_id}'. Re-call delete_workflow with a "
                    f"specific id to remove just one: {listing}"
                )
            wf = matches[0]
            await WorkflowService.delete(s, wf)
        mutated.append({"kind": "workflow_deleted", "name": wf.name})
        return f"Deleted workflow '{wf.name}' (id {wf.id}) and its run history."

    async def delegate_automation_management(requirement: str, session_id: str = "") -> str:
        """Delegate workflow design, authoring, validation, or troubleshooting to the Automation Manager system subagent."""
        from alberto.services.automation_manager import AutomationManagerService

        async with SessionLocal() as s:
            if not session_id:
                existing_sessions = await AutomationManagerService.list_sessions(s, tenant_id, project_id)
                if existing_sessions:
                    latest = existing_sessions[0]
                    is_unfinished = latest.status in ("planning", "clarifying") and not (
                        latest.proposal and latest.proposal.get("executable")
                    )
                    req_low = requirement.lower()
                    is_edit = (
                        latest.status in ("proposed", "needs_repair")
                        and any(k in req_low for k in ("add ", "remove ", "delete ", "replace ", "change ", "update ", "modify ", "approval"))
                        and not any(k in req_low for k in ("new workflow", "another workflow", "build a ", "create a "))
                    )
                    if is_unfinished or is_edit:
                        session_id = latest.id
                        if (
                            latest.clarifications
                            and len(latest.clarifications) == 1
                            and latest.clarifications[0].get("content")
                            in ("New Automations Draft", "Design a new intelligent workflow pipeline")
                        ):
                            latest.clarifications = []
                            await s.commit()
            if not session_id:
                auth_sess = await AutomationManagerService.create_session(
                    session=s,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    user_id=getattr(current_user, "id", None),
                    requirement=requirement,
                )
                session_id = auth_sess.id
            result = await AutomationManagerService.process_message(
                session=s,
                tenant_id=tenant_id,
                project_id=project_id,
                session_id=session_id,
                message=requirement,
            )
            mutated.append({"kind": "automation_session", "name": session_id})
            return json.dumps(result.model_dump(mode="json"), default=str)

    def mk(fn, name):
        return StructuredTool.from_function(coroutine=fn, name=name, parse_docstring=False)

    return [
        mk(describe_workflow, "describe_workflow"),
        mk(list_node_types, "list_node_types"),
        mk(get_node_schema, "get_node_schema"),
        mk(list_middleware_types, "list_middleware_types"),
        mk(create_grounded_workflow, "create_grounded_workflow"),
        mk(create_intent_router_workflow, "create_intent_router_workflow"),
        mk(create_custom_workflow, "create_custom_workflow"),
        mk(add_human_review, "add_human_review"),
        mk(test_workflow, "test_workflow"),
        mk(evaluate_build, "evaluate_build"),
        mk(delete_workflow, "delete_workflow"),
        mk(delegate_automation_management, "delegate_automation_management"),
    ]

