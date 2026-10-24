"""Automation Manager Service.

Provides:
- Deterministic platform capability discovery for project/user scope
- Natural-language workflow planning (deterministic, single-agent, multi-agent, hybrid)
- Strict compliance with Alberto's low-code designer and LangGraph compiler schemas
- Persistent conversational authoring sessions with optimistic concurrency control
- Structured specialist agent proposals (deferred creation pending Phase 3 approval)
- Bounded self-correction for graph schema and validation errors
- Protection against unauthorized tool execution and credential leaks
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

import alberto.nodes  # noqa: F401 (ensure all node types are registered in NODE_REGISTRY)
from alberto.engine.models import resolve_model
from alberto.engine.registry import NODE_REGISTRY
from alberto.models import (
    Agent,
    AutomationSession,
    Channel,
    ConnectorInstall,
    McpClient,
    ModelServer,
    Project,
    RegisteredModel,
    Run,
    Span,
    Tool,
    ToolSet,
    Trace,
    Trigger,
)
from alberto.schemas.automation_manager import (
    AgentProposal,
    ApprovalRequestIn,
    ApprovalResultOut,
    AuthoringStepResult,
    CapabilityDiscoveryResult,
    DiscoveredAgent,
    DiscoveredChannel,
    DiscoveredIntegration,
    DiscoveredModelInfo,
    DiscoveredNode,
    DiscoveredTool,
    DiscoveredToolSet,
    DiscoveredWorkflow,
    PlanningStrategy,
    SafeTestCheck,
    SafeTestResult,
    WorkflowExecutionDiagnostic,
    WorkflowMonitoringReport,
    WorkflowOptimisationReport,
    WorkflowProposal,
)
from alberto.services.agents import AgentService
from alberto.services.runtime import make_runtime_ctx
from alberto.services.validation import validate_workflow
from alberto.services.workflows import WorkflowService

logger = logging.getLogger("alberto.services.automation_manager")
log = logger

MAX_SELF_CORRECTION_ATTEMPTS = 3


class AutomationManagerService:
    """Core service for Automation Manager subagent and conversational workflow authoring."""

    @classmethod
    async def get_automation_manager_model(
        cls, session: AsyncSession, tenant_id: str, project_id: str
    ) -> tuple[Any, str | None]:
        """Resolve the model configured for Automation Manager or fall back to project default."""
        agent_row = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.project_id == project_id,
                    Agent.system_key == "automation_manager",
                )
            )
        ).scalar_one_or_none()

        model_ref: str | None = None
        if agent_row and agent_row.config:
            model_ref = agent_row.config.get("model") or None

        ctx = make_runtime_ctx(tenant_id, project_id)
        resolved = resolve_model(model_ref, ctx)
        return resolved, model_ref or ctx.default_model

    @classmethod
    async def discover_capabilities(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        user_context: dict[str, Any] | None = None,
    ) -> CapabilityDiscoveryResult:
        """Discover platform capabilities available strictly within the project and user scope.

        Excludes credentials, secrets, API keys, and inaccessible tools.
        Metadata is structured and machine-readable for LLM planning.
        """
        # 1. Existing Workflows
        wfs = await WorkflowService.list(session, tenant_id, project_id)
        discovered_wfs = [
            DiscoveredWorkflow(
                id=w.id,
                name=w.name,
                description=w.description,
                status=getattr(w, "status", "draft") or "draft",
                node_count=len((w.executable or {}).get("nodes", [])) if w.executable else 0,
            )
            for w in wfs
        ]

        # 2. Existing Agents (Specialists vs Protected System Agents)
        agents = await AgentService.list(session, tenant_id, project_id)
        specialist_agents: list[DiscoveredAgent] = []
        system_agents: list[DiscoveredAgent] = []

        for a in agents:
            cfg = a.config or {}
            desc = cfg.get("description")
            da = DiscoveredAgent(
                id=a.id,
                name=a.name,
                description=desc,
                system_key=a.system_key,
                is_system=bool(a.is_system or a.system_key),
                model=cfg.get("model"),
                tools=list(cfg.get("tools") or []),
            )
            if a.is_system or a.system_key:
                system_agents.append(da)
            else:
                specialist_agents.append(da)

        # 3. Available Workflow Node Catalog & Schemas
        node_catalog: list[DiscoveredNode] = []
        for _ntype, spec in sorted(NODE_REGISTRY.items()):
            in_ports = [
                {"id": p.id, "io_type": p.io_type, "direction": p.direction, "required": p.required}
                for p in spec.input_ports
            ]
            out_ports = [
                {"id": p.id, "io_type": p.io_type, "direction": p.direction, "required": p.required}
                for p in spec.output_ports
            ]
            node_catalog.append(
                DiscoveredNode(
                    type=spec.type,
                    category=spec.category,
                    label=spec.label or spec.type,
                    description=spec.description or "",
                    allows_cycle=spec.allows_cycle,
                    input_ports=in_ports,
                    output_ports=out_ports,
                )
            )

        # 4. Registered Tools & Safety Classifications (Strictly Sanitized)
        tools_query = select(Tool).where(Tool.tenant_id == tenant_id, Tool.project_id == project_id)
        tool_rows = (await session.execute(tools_query)).scalars().all()
        discovered_tools: list[DiscoveredTool] = []
        for t in tool_rows:
            cfg = t.config or {}
            t_desc = cfg.get("description")
            is_ro = bool(cfg.get("read_only", False) or t.kind == "builtin")
            from alberto.services.tool_manager import ToolManagerService
            effect, risk, _ = ToolManagerService.classify_effect_and_risk(t.name, t_desc or "", cfg=cfg)
            if any(term in t.name.lower() or term in (t_desc or "").lower() for term in ("delete", "deletion", "remove", "drop", "destroy", "purge", "terminate")):
                effect = "delete"
                risk = "critical"
            req_appr = (risk in ("high", "critical") or effect == "delete" or bool(cfg.get("requires_approval")))

            discovered_tools.append(
                DiscoveredTool(
                    id=t.id,
                    name=t.name,
                    description=t_desc,
                    kind=t.kind,
                    effect_type=effect,
                    risk_level=risk,
                    requires_approval=req_appr,
                    read_only=is_ro,
                )
            )

        # 5. Tool Sets
        tool_sets_query = select(ToolSet).where(ToolSet.tenant_id == tenant_id, ToolSet.project_id == project_id)
        tool_set_rows = (await session.execute(tool_sets_query)).scalars().all()
        discovered_tool_sets = [
            DiscoveredToolSet(
                id=ts.id,
                name=ts.name,
                description=ts.description,
                tool_ids=list(ts.tool_ids or []) if hasattr(ts, "tool_ids") else [],
            )
            for ts in tool_set_rows
        ]

        # 6. Integrations (MCP Clients and Connectors — credentials excluded)
        mcps = (
            await session.execute(
                select(McpClient).where(McpClient.tenant_id == tenant_id, McpClient.project_id == project_id)
            )
        ).scalars().all()
        conns = (
            await session.execute(
                select(ConnectorInstall).where(
                    ConnectorInstall.tenant_id == tenant_id, ConnectorInstall.project_id == project_id
                )
            )
        ).scalars().all()

        integrations: list[DiscoveredIntegration] = []
        for m in mcps:
            integrations.append(
                DiscoveredIntegration(
                    name=m.name,
                    type="mcp",
                    status="enabled" if m.enabled else "disabled",
                    detail=f"transport: {m.transport}",
                )
            )
        for c in conns:
            integrations.append(
                DiscoveredIntegration(
                    name=c.name or c.slug,
                    type="connector",
                    status=c.status or "active",
                    detail=f"slug: {c.slug}, version: {c.version}",
                )
            )

        # 7. Configured Channels
        channels_query = select(Channel).where(Channel.tenant_id == tenant_id, Channel.project_id == project_id)
        channel_rows = (await session.execute(channels_query)).scalars().all()
        discovered_channels = [
            DiscoveredChannel(
                name=ch.name,
                type=ch.type,
                enabled=ch.enabled,
            )
            for ch in channel_rows
        ]

        # 8. Models
        proj = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        p_cfg = (proj.config or {}) if proj else {}
        def_model = str(p_cfg.get("default_model_id") or p_cfg.get("default_model") or "gpt-4o-mini")

        reg_models = (
            await session.execute(
                select(RegisteredModel).where(RegisteredModel.tenant_id == tenant_id)
            )
        ).scalars().all()
        servers = (
            await session.execute(
                select(ModelServer).where(ModelServer.tenant_id == tenant_id)
            )
        ).scalars().all()

        model_info = DiscoveredModelInfo(
            default_model=def_model,
            registered_models=[rm.model_name for rm in reg_models],
            servers=[s.name for s in servers],
        )

        return CapabilityDiscoveryResult(
            project_id=project_id,
            workflows=discovered_wfs,
            specialist_agents=specialist_agents,
            system_agents=system_agents,
            node_catalog=node_catalog,
            tools=discovered_tools,
            tool_sets=discovered_tool_sets,
            integrations=integrations,
            channels=discovered_channels,
            models=model_info,
        )

    @classmethod
    async def create_session(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        user_id: str | None,
        requirement: str,
        title: str | None = None,
    ) -> AutomationSession:
        """Create a new persistent conversational authoring session."""
        session_id = f"auto-{uuid.uuid4().hex[:12]}"
        clean_title = (title or requirement[:40] or "New Automation Plan").strip()
        auth_session = AutomationSession(
            id=session_id,
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
            title=clean_title,
            requirement=requirement,
            status="planning",
            clarifications=[
                {
                    "role": "user",
                    "content": requirement,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ],
            current_plan={},
            proposal={},
            proposed_agents=[],
            validation_status="pending",
            validation_errors=[],
            revision=1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(auth_session)
        await session.commit()
        await session.refresh(auth_session)
        return auth_session

    @classmethod
    async def get_session(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        session_id: str,
    ) -> AutomationSession | None:
        """Retrieve an authoring session scoped to tenant and project."""
        stmt = select(AutomationSession).where(
            AutomationSession.tenant_id == tenant_id,
            AutomationSession.project_id == project_id,
            AutomationSession.id == session_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def list_sessions(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
    ) -> list[AutomationSession]:
        """List all authoring sessions for a project ordered by last update."""
        stmt = (
            select(AutomationSession)
            .where(
                AutomationSession.tenant_id == tenant_id,
                AutomationSession.project_id == project_id,
            )
            .order_by(desc(AutomationSession.updated_at))
        )
        return list((await session.execute(stmt)).scalars().all())

    @classmethod
    def compute_canvas(cls, nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
        """Build React Flow canvas layout matching Alberto's low-code designer contract."""
        by_id = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}

        def source_handle(edge: dict) -> str | None:
            if edge.get("sourceHandle") or edge.get("source_handle"):
                return edge.get("sourceHandle") or edge.get("source_handle")
            source = by_id.get(edge.get("source"))
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

        # Determine node positions if missing
        positioned_nodes = []
        for i, n in enumerate(nodes):
            nid = n.get("id", f"node_{i}")
            ntype = n.get("type", "transform")
            pos = n.get("position")
            if not pos or not isinstance(pos, dict):
                # Auto-layout in a clean multi-column canvas
                if ntype in ("start", "schedule", "webhook_in", "email_in", "app_event", "inject"):
                    pos = {"x": 60, "y": 200 + i * 80}
                elif ntype in ("classifier", "router"):
                    pos = {"x": 360, "y": 200 + i * 80}
                elif ntype in ("agent", "deep_agent", "llm"):
                    pos = {"x": 680, "y": 120 + i * 140}
                elif ntype in ("tool_call", "transform", "human_input", "delay"):
                    pos = {"x": 980, "y": 180 + i * 100}
                elif ntype in ("end", "debug"):
                    pos = {"x": 1280, "y": 220 + i * 80}
                else:
                    pos = {"x": 200 + (i * 240), "y": 220}
            positioned_nodes.append(
                {
                    "id": nid,
                    "type": "forge",
                    "position": pos,
                    "data": {
                        "nodeType": ntype,
                        "config": n.get("config", {}) or {},
                    },
                }
            )

        canvas_edges = []
        for i, e in enumerate(edges):
            sh = source_handle(e)
            edge_dict: dict[str, Any] = {
                "id": f"e{i}",
                "source": e.get("source"),
                "target": e.get("target"),
            }
            if sh:
                edge_dict["sourceHandle"] = sh
            if e.get("label") is not None:
                edge_dict["label"] = str(e["label"])
            canvas_edges.append(edge_dict)

        return {
            "nodes": positioned_nodes,
            "edges": canvas_edges,
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }

    @classmethod
    def self_correct_workflow(
        cls,
        executable: dict[str, Any],
        errors: list[dict[str, Any]],
        capabilities: CapabilityDiscoveryResult,
        max_attempts: int = MAX_SELF_CORRECTION_ATTEMPTS,
    ) -> tuple[dict[str, Any], bool, list[dict[str, Any]]]:
        """Bounded self-correction of graph definition against Alberto's validation contracts."""
        curr = dict(executable)
        if "id" not in curr:
            curr["id"] = f"wf-{uuid.uuid4().hex[:8]}"
        if "version" not in curr:
            curr["version"] = 1

        for _ in range(max_attempts):
            res = validate_workflow(curr)
            if res.valid:
                return curr, True, []

            # Deterministic surgical repairs
            nodes = [dict(n) for n in curr.get("nodes", []) if isinstance(n, dict)]
            edges = [dict(e) for e in curr.get("edges", []) if isinstance(e, dict)]
            allowed_state_types = {"list[message]", "list[str]", "list[json]", "str", "int", "float", "bool", "json"}
            raw_state = dict(curr.get("state", {}) or {})
            repaired_state: dict[str, Any] = {}
            for k, v in raw_state.items():
                if isinstance(v, dict):
                    v_type = v.get("type", "str")
                    if v_type in ("dict", "object", "any"):
                        v_type = "json"
                    elif v_type not in allowed_state_types:
                        v_type = "str"
                    repaired_state[k] = {"type": v_type, "reducer": v.get("reducer", "last")}
                else:
                    v_str = str(v).lower()
                    v_type = "json" if v_str in ("dict", "json") else ("str" if v_str not in allowed_state_types else v_str)
                    repaired_state[k] = {"type": v_type, "reducer": "last"}
            if "messages" not in repaired_state:
                repaired_state["messages"] = {"type": "list[message]", "reducer": "add_messages"}
            node_ids = {n["id"] for n in nodes}

            # Repair agent / llm nodes missing model
            default_model = (capabilities.models.default_model if capabilities else "") or "gpt-4o-mini"
            for n in nodes:
                if n.get("type") in ("agent", "deep_agent", "llm"):
                    cfg = n.setdefault("config", {})
                    if not cfg.get("model") and not cfg.get("agent_ref"):
                        cfg["model"] = default_model

            # 1. Ensure Start / Entry Node
            if not nodes:
                nodes.append({"id": "start", "type": "start", "config": {}})
                nodes.append({"id": "end", "type": "end", "config": {}})
                edges.append({"source": "start", "target": "end"})
                node_ids.update({"start", "end"})

            entry = curr.get("entry_node")
            if not entry or entry not in node_ids:
                has_start = any(n["type"] == "start" for n in nodes)
                if has_start:
                    curr["entry_node"] = next(n["id"] for n in nodes if n["type"] == "start")
                else:
                    curr["entry_node"] = nodes[0]["id"]

            # 2. Ensure End Node and terminal connectivity
            has_end = any(n["type"] == "end" for n in nodes)
            if not has_end:
                nodes.append({"id": "end", "type": "end", "config": {}})
                node_ids.add("end")

            # 3. Fix unknown targets in edges and connect orphan terminal nodes
            cleaned_edges = []
            sources_with_outgoing = set()
            for e in edges:
                src, tgt = e.get("source"), e.get("target")
                if src in node_ids:
                    if tgt not in node_ids and tgt != "end":
                        e["target"] = "end"
                    cleaned_edges.append(e)
                    sources_with_outgoing.add(src)
            edges = cleaned_edges

            for n in nodes:
                if n["type"] != "end" and n["id"] not in sources_with_outgoing:
                    edges.append({"source": n["id"], "target": "end"})
                    sources_with_outgoing.add(n["id"])

            # 4. Repair undeclared state writes
            for err in res.errors:
                msg = err.get("message", "")
                if "writes state key" in msg and "not declared in the workflow State" in msg:
                    # Extract key name: Node 'xyz' writes state key 'abc', which is not declared
                    try:
                        key_part = msg.split("writes state key ")[1].split(",")[0].strip("'\"")
                        if key_part and key_part not in repaired_state:
                            repaired_state[key_part] = {"type": "str", "reducer": "last"}
                    except Exception:
                        pass

            # 5. Fix branching edges without conditions
            for e in edges:
                if e.get("branches") and not str(e.get("condition") or "").strip():
                    e["condition"] = "intent"

            curr["nodes"] = nodes
            curr["edges"] = edges
            curr["state"] = repaired_state

            # Re-evaluate
            res = validate_workflow(curr)
            if res.valid:
                return curr, True, []

        final_res = validate_workflow(curr)
        return curr, final_res.valid, final_res.errors

    @classmethod
    async def process_message(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        session_id: str,
        message: str,
        expected_revision: int | None = None,
        model_override: str | None = None,
        user_context: dict[str, Any] | None = None,
    ) -> AuthoringStepResult:
        """Process a conversational authoring turn with optimistic concurrency control."""
        auth_session = await cls.get_session(session, tenant_id, project_id, session_id)
        if not auth_session:
            return AuthoringStepResult(
                action="error",
                session_id=session_id,
                revision=0,
                error_message=f"Authoring session '{session_id}' not found.",
            )

        # Optimistic Concurrency Check
        if expected_revision is not None and auth_session.revision != expected_revision:
            return AuthoringStepResult(
                action="error",
                session_id=session_id,
                revision=auth_session.revision,
                error_message=(
                    f"Conflict: Stale authoring update. Expected revision {expected_revision}, "
                    f"but session is at revision {auth_session.revision}."
                ),
            )

        # Record incoming message in clarifications
        clarifications = list(auth_session.clarifications or [])
        clarifications.append(
            {
                "role": "user",
                "content": message,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        # Discover capabilities (sanitized)
        capabilities = await cls.discover_capabilities(session, tenant_id, project_id, user_context)

        # Detect conversational Monitoring, Diagnosis, or Optimisation requests
        low_msg = message.strip().lower()
        if any(k in low_msg for k in ("why did", "failed", "failure", "diagnos", "troubleshoot", "why last run")):
            # Retrieve latest failed run in project
            failed_run = (
                await session.execute(
                    select(Run)
                    .where(Run.tenant_id == tenant_id, Run.project_id == project_id, Run.status.in_(("error", "interrupted")))
                    .order_by(desc(Run.created_at))
                    .limit(1)
                )
            ).scalar_one_or_none()

            if failed_run:
                diag = await cls.diagnose_failure(session, tenant_id, project_id, failed_run.id)
                ans = (
                    f"**Failure Diagnosis for Run `{diag.run_id}` (Workflow: '{diag.workflow_name}')**:\n"
                    f"- **Category**: `{diag.category}`\n"
                    f"- **Root Cause**: {diag.root_cause}\n"
                    f"- **Longest Step**: {diag.longest_step.get('name') if diag.longest_step else 'N/A'} "
                    f"({diag.longest_step.get('latency_ms', 0) if diag.longest_step else 0}ms)\n"
                    f"- **Proposed Safe Repair**: {diag.proposed_repair}\n"
                    f"- **Requires Approval**: {'Yes (Privilege / Tool Change)' if diag.requires_approval else 'No (Safe Config Repair)'}"
                )
            else:
                ans = "No recent failed runs were found in this project. All recent workflow executions completed successfully."

            clarifications.append({"role": "assistant", "content": ans, "timestamp": datetime.utcnow().isoformat()})
            auth_session.clarifications = clarifications
            auth_session.revision += 1
            auth_session.updated_at = datetime.utcnow()
            await session.commit()
            return AuthoringStepResult(
                action="clarify",
                session_id=session_id,
                revision=auth_session.revision,
                questions=[ans],
                proposal=None,
            )

        if any(k in low_msg for k in ("run today", "show runs", "which workflow is running", "status of", "step took the longest", "monitoring")):
            report = await cls.get_workflow_monitoring_summary(session, tenant_id, project_id)
            lr = report.last_run or {}
            ans = (
                f"**Workflow Execution Status Report**:\n"
                f"- **Total Runs Recorded**: {report.total_runs}\n"
                f"- **Currently Active Runs**: {report.active_runs}\n"
                f"- **Overall Success Rate**: {report.success_rate * 100:.1f}%\n"
                f"- **Last Run Status**: `{lr.get('status', 'none')}` (Duration: {lr.get('duration_ms', 0)}ms, Tokens: {lr.get('tokens', 0)})\n"
                f"- **Slowest Step**: {report.slowest_step.get('name') if report.slowest_step else 'None recorded'} "
                f"({report.slowest_step.get('latency_ms', 0) if report.slowest_step else 0}ms)\n"
                f"- **Configured Triggers**: {len(report.triggers)} active trigger(s)"
            )
            clarifications.append({"role": "assistant", "content": ans, "timestamp": datetime.utcnow().isoformat()})
            auth_session.clarifications = clarifications
            auth_session.revision += 1
            auth_session.updated_at = datetime.utcnow()
            await session.commit()
            return AuthoringStepResult(
                action="clarify",
                session_id=session_id,
                revision=auth_session.revision,
                questions=[ans],
                proposal=None,
            )

        # Check for ambiguity requiring clarification questions
        saved_wf_id = (auth_session.proposal or {}).get("workflow_id")
        has_proposal = bool(saved_wf_id or (auth_session.proposal and auth_session.proposal.get("executable")))
        full_text = " ".join(c.get("content", "") for c in clarifications).strip().lower()
        words = full_text.split()
        is_clear = (
            len(words) >= 6
            and any(
                k in full_text
                for k in (
                    "schedule", "webhook", "email", "agent", "trigger",
                    "daily", "pipeline", "team", "triage", "support",
                    "multi", "router", "classifier", "customer"
                )
            )
        )
        if not has_proposal and not is_clear:
            # Insufficient detail to plan a meaningful workflow
            question = (
                "Could you describe the main triggers (e.g. scheduled, webhook, or manual) "
                "and what specific actions or specialist agents should be involved?"
            )
            clarifications.append(
                {
                    "role": "assistant",
                    "content": question,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
            auth_session.clarifications = clarifications
            auth_session.revision += 1
            auth_session.updated_at = datetime.utcnow()
            await session.commit()
            return AuthoringStepResult(
                action="clarify",
                session_id=session_id,
                revision=auth_session.revision,
                questions=[question],
            )

        existing_exec = (auth_session.proposal or {}).get("executable")
        saved_wf_id = (auth_session.proposal or {}).get("workflow_id") or (auth_session.metadata_json or {}).get("saved_wf_id")
        base_workflow_revision = None
        if saved_wf_id:
            from alberto.models import Workflow
            saved_wf = await session.get(Workflow, saved_wf_id)
            if saved_wf:
                base_workflow_revision = (saved_wf.active_version or 1)
                if saved_wf.executable:
                    existing_exec = saved_wf.executable

        # Formulate structured plan and executable graph
        proposal = await cls._generate_workflow_proposal(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            conversation=clarifications,
            capabilities=capabilities,
            model_override=model_override,
            existing_executable=existing_exec,
        )
        if saved_wf_id and not proposal.workflow_id:
            proposal.workflow_id = saved_wf_id
        if base_workflow_revision is not None:
            proposal.base_workflow_revision = base_workflow_revision

        # Run bounded self-correction against Alberto's validator
        corrected_exec, is_valid, validation_errors = cls.self_correct_workflow(
            proposal.executable,
            proposal.validation.get("errors", []),
            capabilities,
        )
        proposal.executable = corrected_exec
        proposal.canvas = cls.compute_canvas(corrected_exec.get("nodes", []), corrected_exec.get("edges", []))
        import hashlib
        proposal.content_fingerprint = hashlib.sha256(json.dumps(corrected_exec, sort_keys=True).encode()).hexdigest()[:16]
        proposal.validation = {
            "valid": is_valid,
            "errors": validation_errors,
        }

        # Automatic Safe Testing Before Approval
        safe_test = await cls.run_safe_test(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            session_id=session_id,
            custom_executable=corrected_exec,
        )
        proposal.safe_test_results = safe_test

        # Persist session state under Alberto's /data SQLite storage
        auth_session.clarifications = clarifications
        auth_session.current_plan = {
            "strategy": proposal.strategy,
            "title": proposal.title,
            "description": proposal.description,
            "reused_agents": proposal.reused_agents,
            "reused_tools": proposal.reused_tools,
        }
        auth_session.proposal = proposal.model_dump(mode="json")
        auth_session.proposed_agents = [p.model_dump() for p in proposal.proposed_agents]
        auth_session.validation_status = "valid" if is_valid else "needs_repair"
        auth_session.validation_errors = validation_errors
        auth_session.status = "proposed" if is_valid else "needs_repair"
        auth_session.revision += 1
        auth_session.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(auth_session)

        return AuthoringStepResult(
            action="plan",
            session_id=session_id,
            revision=auth_session.revision,
            proposal=proposal,
            validation_status=auth_session.validation_status,
            validation_errors=validation_errors,
        )

    @classmethod
    async def _generate_workflow_proposal(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        conversation: list[dict[str, Any]],
        capabilities: CapabilityDiscoveryResult,
        model_override: str | None = None,
        existing_executable: dict[str, Any] | None = None,
    ) -> WorkflowProposal:
        """Construct a structured workflow proposal conforming to Alberto's low-code schema."""
        conv_text = " ".join(c.get("content", "") for c in conversation).lower()
        latest_msg = (conversation[-1].get("content") or "").strip().lower() if conversation else ""

        # Incremental Conversational Workflow Modifications
        if existing_executable and existing_executable.get("nodes"):
            nodes = [dict(n) for n in existing_executable.get("nodes", [])]
            edges = [dict(e) for e in existing_executable.get("edges", [])]

            if "approval" in latest_msg or "human" in latest_msg:
                approval_id = f"approval_{uuid.uuid4().hex[:4]}"
                nodes.append({
                    "id": approval_id,
                    "type": "human_input",
                    "config": {"prompt": "Approve execution step before proceeding."},
                })
                new_edges = []
                rewired = False
                for e in edges:
                    if e.get("target") == "end" and not rewired:
                        new_edges.append({"source": e.get("source"), "target": approval_id})
                        new_edges.append({"source": approval_id, "target": "end"})
                        rewired = True
                    else:
                        new_edges.append(e)
                if not rewired:
                    new_edges.append({"source": approval_id, "target": "end"})
                existing_executable["nodes"] = nodes
                existing_executable["edges"] = new_edges
                v_res = validate_workflow(existing_executable)
                return WorkflowProposal(
                    title=existing_executable.get("name", "Workflow Modification"),
                    strategy="hybrid",
                    description="Updated workflow with human approval step.",
                    executable=existing_executable,
                    canvas=cls.compute_canvas(nodes, new_edges),
                    proposed_agents=[],
                    reused_agents=[],
                    reused_tools=[],
                    explanation="Added human approval gate before final workflow completion.",
                    validation={"valid": v_res.valid, "errors": v_res.errors},
                )

            if any(k in latest_msg for k in ("schedule", "monday", "cron", "daily", "hourly")):
                for n in nodes:
                    if n.get("type") == "schedule":
                        cfg = n.setdefault("config", {})
                        if "monday" in latest_msg:
                            cfg["cron"] = "0 9 * * 1"
                        elif "daily" in latest_msg:
                            cfg["cron"] = "0 9 * * *"
                        elif "hour" in latest_msg:
                            cfg["cron"] = "0 * * * *"
                existing_executable["nodes"] = nodes
                v_res = validate_workflow(existing_executable)
                return WorkflowProposal(
                    title=existing_executable.get("name", "Workflow Modification"),
                    strategy="deterministic",
                    description="Updated workflow schedule configuration.",
                    executable=existing_executable,
                    canvas=cls.compute_canvas(nodes, edges),
                    proposed_agents=[],
                    reused_agents=[],
                    reused_tools=[],
                    explanation="Updated schedule trigger frequency per conversation.",
                    validation={"valid": v_res.valid, "errors": v_res.errors},
                )

            if "replace" in latest_msg and "tool" in latest_msg:
                tname = capabilities.tools[0].name if capabilities.tools else "calculator"
                for n in nodes:
                    if n.get("type") == "agent":
                        n["type"] = "tool"
                        n["config"] = {"name": tname, "tool_name": tname, "operation": "execute"}
                        break
                existing_executable["nodes"] = nodes
                v_res = validate_workflow(existing_executable)
                return WorkflowProposal(
                    title=existing_executable.get("name", "Workflow Modification"),
                    strategy="deterministic",
                    description="Replaced agent step with deterministic tool call.",
                    executable=existing_executable,
                    canvas=cls.compute_canvas(nodes, edges),
                    proposed_agents=[],
                    reused_agents=[],
                    reused_tools=[tname],
                    explanation="Converted autonomous agent reasoning step into a direct deterministic tool call.",
                    validation={"valid": v_res.valid, "errors": v_res.errors},
                )

            if "remove" in latest_msg or "delete" in latest_msg:
                for n in list(nodes):
                    nid = n.get("id", "")
                    ntype = n.get("type", "")
                    nname = (n.get("config") or {}).get("name", "")
                    if (nid in latest_msg or ntype in latest_msg or (nname and nname.lower() in latest_msg)) and ntype not in ("start", "end", "trigger_schedule"):
                        nodes.remove(n)
                        srcs = [e.get("source") for e in edges if e.get("target") == nid]
                        tgts = [e.get("target") for e in edges if e.get("source") == nid]
                        edges = [e for e in edges if e.get("source") != nid and e.get("target") != nid]
                        for s_id in srcs:
                            for t_id in tgts:
                                edges.append({"source": s_id, "target": t_id})
                        break
                existing_executable["nodes"] = nodes
                existing_executable["edges"] = edges
                v_res = validate_workflow(existing_executable)
                return WorkflowProposal(
                    title=existing_executable.get("name", "Workflow Modification"),
                    strategy="single_agent",
                    description="Removed requested node from workflow pipeline.",
                    executable=existing_executable,
                    canvas=cls.compute_canvas(nodes, edges),
                    proposed_agents=[],
                    reused_agents=[],
                    reused_tools=[],
                    explanation="Removed step and reconnected upstream/downstream flow.",
                    validation={"valid": v_res.valid, "errors": v_res.errors},
                )

        # Determine strategy
        is_multi = any(k in conv_text for k in ("multi", "specialist", "agents", "handoff", "team", "triage"))
        is_scheduled = any(k in conv_text for k in ("schedule", "daily", "hourly", "cron", "every morning"))
        is_router = any(k in conv_text for k in ("classify", "route", "branch", "category", "intent"))

        strategy: PlanningStrategy = "multi_agent" if is_multi else ("hybrid" if is_router else "single_agent")

        title = "AI Automation Workflow"
        first_msg = conversation[0].get("content", "") if conversation else ""
        if first_msg:
            title = first_msg[:35].strip().title()

        # Check existing specialist agents for reuse
        reused_agents: list[str] = []
        proposed_agents: list[AgentProposal] = []
        default_model = capabilities.models.default_model or "gpt-4o-mini"

        # Check for tools that can be reused
        reused_tools: list[str] = [t.name for t in capabilities.tools[:3]]

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        state: dict[str, Any] = {
            "messages": {"type": "list[message]", "reducer": "add_messages"},
            "intent": {"type": "str", "reducer": "last"},
            "result": {"type": "json", "reducer": "last"},
        }

        # 1. Triggers / Entry
        if is_scheduled:
            nodes.append({
                "id": "trigger_schedule",
                "type": "schedule",
                "config": {"cron": "0 9 * * *", "timezone": "UTC"},
            })
            entry_id = "trigger_schedule"
        else:
            nodes.append({"id": "start", "type": "start", "config": {}})
            entry_id = "start"

        if strategy == "multi_agent":
            # Propose specialist agent 1 & 2 if no existing match
            spec1_name = "triage_specialist"
            spec2_name = "resolution_specialist"

            matching1 = next((a for a in capabilities.specialist_agents if a.name.lower() == spec1_name), None)
            if matching1:
                reused_agents.append(matching1.name)
            else:
                proposed_agents.append(
                    AgentProposal(
                        name=spec1_name,
                        responsibility="Analyze incoming requests, classify complexity, and extract key entities.",
                        system_prompt="You are the Triage Specialist. Classify inputs and prepare structured summaries.",
                        model=default_model,
                        tools=reused_tools[:1],
                        tool_permissions=["read"],
                        risk_info={"risk_level": "low"},
                        intended_workflow_association=title,
                    )
                )

            matching2 = next((a for a in capabilities.specialist_agents if a.name.lower() == spec2_name), None)
            if matching2:
                reused_agents.append(matching2.name)
            else:
                proposed_agents.append(
                    AgentProposal(
                        name=spec2_name,
                        responsibility="Execute operations and generate finalized customer-facing responses.",
                        system_prompt="You are the Resolution Specialist. Solve customer requests accurately.",
                        model=default_model,
                        tools=reused_tools,
                        tool_permissions=["read", "write"],
                        risk_info={"risk_level": "medium"},
                        intended_workflow_association=title,
                    )
                )

            nodes.append({
                "id": "triage_node",
                "type": "agent",
                "config": {
                    "flavor": "agent",
                    "name": spec1_name,
                    "model": default_model,
                    "system_prompt": "Analyze incoming requests and triage.",
                    "tools": reused_tools[:1],
                },
            })
            nodes.append({
                "id": "resolution_node",
                "type": "agent",
                "config": {
                    "flavor": "agent",
                    "name": spec2_name,
                    "model": default_model,
                    "system_prompt": "Fulfill request and summarize output.",
                    "tools": reused_tools,
                },
            })
            nodes.append({"id": "end", "type": "end", "config": {}})

            edges.append({"source": entry_id, "target": "triage_node"})
            edges.append({"source": "triage_node", "target": "resolution_node"})
            edges.append({"source": "resolution_node", "target": "end"})

        elif strategy == "hybrid":
            # Classifier -> Router -> Agent + End
            nodes.append({
                "id": "classify_step",
                "type": "classifier",
                "config": {
                    "labels": ["inquiry", "escalation"],
                    "output_key": "intent",
                    "model": default_model,
                },
            })
            nodes.append({
                "id": "route_step",
                "type": "router",
                "config": {
                    "expression": "intent",
                    "cases": {"inquiry": "agent_worker", "escalation": "human_review"},
                    "default": "agent_worker",
                },
            })
            nodes.append({
                "id": "agent_worker",
                "type": "agent",
                "config": {
                    "flavor": "agent",
                    "name": "inquiry_worker",
                    "model": default_model,
                    "system_prompt": "Resolve standard customer inquiries concisely.",
                    "tools": reused_tools,
                },
            })
            nodes.append({
                "id": "human_review",
                "type": "human_input",
                "config": {
                    "prompt": "Review escalated case and approve resolution.",
                },
            })
            nodes.append({"id": "end", "type": "end", "config": {}})

            edges.append({"source": entry_id, "target": "classify_step"})
            edges.append({"source": "classify_step", "target": "route_step"})
            edges.append({"source": "route_step", "target": "agent_worker", "label": "inquiry"})
            edges.append({"source": "route_step", "target": "human_review", "label": "escalation"})
            edges.append({"source": "agent_worker", "target": "end"})
            edges.append({"source": "human_review", "target": "end"})

            proposed_agents.append(
                AgentProposal(
                    name="inquiry_worker",
                    responsibility="Handle general inquiries with standard tool access.",
                    system_prompt="Resolve standard customer inquiries concisely.",
                    model=default_model,
                    tools=reused_tools,
                    tool_permissions=["read"],
                    risk_info={"risk_level": "low"},
                    intended_workflow_association=title,
                )
            )

        else:
            # Single Agent Pipeline
            spec_name = "primary_assistant"
            matching = next((a for a in capabilities.specialist_agents if a.name.lower() == spec_name), None)
            if matching:
                reused_agents.append(matching.name)
            else:
                proposed_agents.append(
                    AgentProposal(
                        name=spec_name,
                        responsibility="Execute workflow steps using registered platform tools.",
                        system_prompt="You are an autonomous assistant for this workflow.",
                        model=default_model,
                        tools=reused_tools,
                        tool_permissions=["read"],
                        risk_info={"risk_level": "low"},
                        intended_workflow_association=title,
                    )
                )

            nodes.append({
                "id": "agent_node",
                "type": "agent",
                "config": {
                    "flavor": "agent",
                    "name": spec_name,
                    "model": default_model,
                    "system_prompt": "Execute workflow steps accurately.",
                    "tools": reused_tools,
                },
            })
            nodes.append({"id": "end", "type": "end", "config": {}})

            edges.append({"source": entry_id, "target": "agent_node"})
            edges.append({"source": "agent_node", "target": "end"})

        executable = {
            "id": f"wf-{uuid.uuid4().hex[:8]}",
            "version": 1,
            "entry_node": entry_id,
            "nodes": nodes,
            "edges": edges,
            "state": state,
        }

        # Initial validation run
        v_res = validate_workflow(executable)
        canvas = cls.compute_canvas(nodes, edges)

        return WorkflowProposal(
            title=title,
            strategy=strategy,
            description=f"Generated {strategy} automation graph satisfying requirements.",
            executable=executable,
            canvas=canvas,
            proposed_agents=proposed_agents,
            reused_agents=reused_agents,
            reused_tools=reused_tools,
            explanation=(
                f"Configured a {strategy} pipeline with entry node '{entry_id}'. "
                f"Proposed {len(proposed_agents)} specialist agent(s) and reused {len(reused_agents)} existing agent(s)."
            ),
            validation={
                "valid": v_res.valid,
                "errors": v_res.errors,
            },
        )

    @classmethod
    async def run_safe_test(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        session_id: str,
        custom_executable: dict[str, Any] | None = None,
    ) -> SafeTestResult:
        """Validate and safely simulate workflow execution without executing live side effects."""
        auth_session = await cls.get_session(session, tenant_id, project_id, session_id)
        if not auth_session and not custom_executable:
            raise ValueError(f"Authoring session '{session_id}' not found.")

        proposal = (auth_session.proposal or {}) if auth_session else {}
        executable = custom_executable or proposal.get("executable") or {}
        if not executable:
            return SafeTestResult(
                session_id=session_id,
                valid=False,
                status="failed",
                checks=[
                    SafeTestCheck(
                        name="executable_exists",
                        status="failed",
                        detail="No executable workflow proposal found in this authoring session.",
                    )
                ],
                risks_identified=["Missing executable workflow graph."],
                side_effects=[],
            )

        # 1. Validation check
        val = validate_workflow(executable)
        checks: list[SafeTestCheck] = [
            SafeTestCheck(
                name="graph_schema_and_contracts",
                status="passed" if val.valid else "failed",
                detail=(
                    "Workflow structure and node configurations conform to Alberto's schema."
                    if val.valid
                    else f"Schema errors: {', '.join(e.get('message', '') for e in val.errors[:3])}"
                ),
            )
        ]

        # 2. State schema and reducers check
        state = executable.get("state") or {}
        has_messages = "messages" in state
        checks.append(
            SafeTestCheck(
                name="state_declaration_and_reducers",
                status="passed" if has_messages else "warning",
                detail=(
                    f"State schema declares {len(state)} keys with valid reducers."
                    if has_messages
                    else "State schema does not declare a standard 'messages' channel."
                ),
            )
        )

        # 3. Dry-run graph traversal simulation (safe, zero external side effects)
        nodes = {n.get("id"): n for n in executable.get("nodes", [])}
        edges = executable.get("edges", [])
        entry_node = executable.get("entry_node")
        traversed: list[str] = []
        if entry_node and entry_node in nodes:
            adj: dict[str, list[str]] = {}
            for e in edges:
                adj.setdefault(e.get("source"), []).append(e.get("target"))
            queue = [entry_node]
            visited = set()
            while queue:
                curr = queue.pop(0)
                if curr in visited:
                    continue
                visited.add(curr)
                for nxt in adj.get(curr, []):
                    if nxt and nxt not in visited:
                        queue.append(nxt)
            traversed = list(visited)

        reachability = len(traversed) == len(nodes)
        checks.append(
            SafeTestCheck(
                name="dry_run_topology_traversal",
                status="passed" if reachability else "warning",
                detail=(
                    f"Successfully traversed {len(traversed)}/{len(nodes)} nodes from entry '{entry_node}' in dry-run simulation."
                    if reachability
                    else f"Graph has unreachable nodes ({len(nodes) - len(traversed)} unvisited from '{entry_node}')."
                ),
            )
        )

        # 4. Tool & Security Risk Analysis
        risks_identified: list[str] = []
        side_effects: list[str] = []
        from alberto.services.tool_manager import ToolManagerService

        for node in nodes.values():
            ntype = node.get("type")
            cfg = node.get("config", {})
            if ntype == "agent":
                agent_tools = cfg.get("tools", [])
                for tname in agent_tools:
                    effect, risk, _ = ToolManagerService.classify_effect_and_risk(tname)
                    if effect in ("write", "delete") or risk in ("high", "critical"):
                        risks_identified.append(
                            f"Agent '{cfg.get('name', 'unnamed')}' invokes tool '{tname}' ({effect} effect, {risk} risk)."
                        )
                        side_effects.append(f"Tool '{tname}': {effect} operations on external resources.")
            elif ntype == "tool":
                tname = cfg.get("tool_name") or cfg.get("name") or "tool"
                effect, risk, _ = ToolManagerService.classify_effect_and_risk(tname)
                if effect in ("write", "delete") or risk in ("high", "critical"):
                    risks_identified.append(f"Deterministic tool '{tname}' ({effect} effect, {risk} risk).")
                    side_effects.append(f"Tool '{tname}': {effect} operations on external resources.")
            elif ntype == "schedule":
                side_effects.append(f"Scheduled cron trigger: will execute periodically ({cfg.get('cron', 'unspecified')}).")

        checks.append(
            SafeTestCheck(
                name="security_and_tool_policy_audit",
                status="warning" if risks_identified else "passed",
                detail=(
                    f"Identified {len(risks_identified)} risk item(s) requiring runtime policy enforcement."
                    if risks_identified
                    else "All tools and nodes operate with low-risk read-only access."
                ),
            )
        )

        overall_valid = val.valid
        overall_status: Any = "passed" if (overall_valid and not any(c.status == "failed" for c in checks)) else "failed"
        if overall_valid and any(c.status == "warning" for c in checks):
            overall_status = "warning"

        result = SafeTestResult(
            session_id=session_id,
            valid=overall_valid,
            status=overall_status,
            checks=checks,
            risks_identified=risks_identified,
            side_effects=side_effects,
        )

        if auth_session is not None:
            proposal["safe_test_results"] = result.model_dump(mode="json")
            auth_session.proposal = proposal
            auth_session.updated_at = datetime.utcnow()
            await session.commit()
        return result

    @classmethod
    async def approve_and_activate(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        session_id: str,
        user_context: dict[str, Any],
        req: ApprovalRequestIn,
    ) -> ApprovalResultOut:
        """Consolidated authorization to create proposed specialist agents and activate workflow."""
        auth_session = await cls.get_session(session, tenant_id, project_id, session_id)
        if not auth_session:
            raise ValueError(f"Authoring session '{session_id}' not found.")

        # Revision check (optimistic concurrency / stale approval prevention)
        if req.revision != auth_session.revision:
            raise ValueError(
                f"Conflict: Stale approval. Request revision was {req.revision}, "
                f"but session proposal is at revision {auth_session.revision}."
            )

        proposal = auth_session.proposal or {}
        executable = proposal.get("executable") or {}
        canvas = proposal.get("canvas") or {}
        if not executable:
            raise ValueError("Cannot approve session without an executable workflow proposal.")

        # Validate executable before committing
        val = validate_workflow(executable)
        if not val.valid:
            err_msg = ", ".join(e.get("message", "") for e in val.errors[:3])
            raise ValueError(f"Cannot approve invalid workflow proposal: {err_msg}")

        user_id = user_context.get("user_id")
        created_agent_ids: list[str] = []

        # 1. Idempotently create proposed specialist agents through AgentService
        if req.create_agents:
            proposed_agents = auth_session.proposed_agents or proposal.get("proposed_agents", [])
            for pa in proposed_agents:
                aname = pa.get("name")
                if not aname:
                    continue
                existing_agents = await AgentService.list(session, tenant_id, project_id)
                found = next((a for a in existing_agents if a.name.lower() == aname.lower()), None)
                if found:
                    created_agent_ids.append(found.id)
                else:
                    agent_cfg = {
                        "name": aname,
                        "description": pa.get("responsibility", ""),
                        "system_prompt": pa.get("system_prompt", ""),
                        "model": pa.get("model", ""),
                        "tools": pa.get("tools", []),
                        "toolsets": pa.get("tool_sets", []),
                        "status": "active",
                    }
                    new_agent = await AgentService.create(
                        session=session,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        name=aname,
                        config=agent_cfg,
                        created_by=user_id,
                    )
                    created_agent_ids.append(new_agent.id)

        # 2. Idempotently create or update Workflow through WorkflowService
        wf_title = proposal.get("title") or auth_session.title or "AI Generated Workflow"
        existing_wf_id = proposal.get("workflow_id")
        wf = None
        if existing_wf_id:
            wf = await WorkflowService.get(session, tenant_id, existing_wf_id)
            if wf:
                expected_ver = proposal.get("base_workflow_revision")
                if expected_ver is not None and (wf.active_version or 1) != expected_ver:
                    raise ValueError(
                        f"Conflict: Workflow '{wf.name}' was modified concurrently in Canvas "
                        f"(current version {wf.active_version}, proposal based on {expected_ver}). "
                        "Please regenerate or reconcile proposed changes before approving."
                    )

        if wf:
            await WorkflowService.save_canvas(
                session=session,
                wf=wf,
                canvas=canvas,
                executable=executable,
                owner=user_id,
            )
            wf.name = wf_title
            wf.description = proposal.get("description", "")
            if req.activate:
                wf.status = "active"
            await session.commit()
            await session.refresh(wf)
        else:
            wf = await WorkflowService.create(
                session=session,
                tenant_id=tenant_id,
                project_id=project_id,
                name=wf_title,
                description=proposal.get("description", ""),
                executable=executable,
                canvas=canvas,
            )
            if req.activate:
                wf.status = "active"
                await session.commit()
                await session.refresh(wf)
                await WorkflowService._sync_triggers(session, wf, owner=user_id)

        # 3. Update session status and record approval metadata
        proposal["workflow_id"] = wf.id
        auth_session.proposal = proposal
        auth_session.status = "approved"
        auth_session.revision += 1
        auth_session.updated_at = datetime.utcnow()
        await session.commit()

        return ApprovalResultOut(
            session_id=session_id,
            status="approved",
            revision=auth_session.revision,
            workflow_id=wf.id,
            workflow_name=wf.name,
            created_agent_ids=created_agent_ids,
            activated=req.activate,
            approved_by=user_id,
            message=(
                f"Successfully approved workflow '{wf.name}' (ID: {wf.id}). "
                f"Created/associated {len(created_agent_ids)} specialist agent(s). "
                f"Workflow status: {'active' if req.activate else 'draft'}."
            ),
        )

    @classmethod
    async def get_workflow_monitoring_summary(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        workflow_id: str | None = None,
    ) -> WorkflowMonitoringReport:
        """Deterministically query actual persisted run history, status, and node performance."""
        wf_name: str | None = None
        if workflow_id:
            wf = await WorkflowService.get(session, tenant_id, workflow_id)
            if wf:
                wf_name = wf.name

        runs_query = (
            select(Run)
            .where(Run.tenant_id == tenant_id, Run.project_id == project_id)
            .order_by(desc(Run.created_at))
        )
        if workflow_id:
            runs_query = runs_query.where(Run.workflow_id == workflow_id)

        runs_rows = list((await session.execute(runs_query.limit(50))).scalars())
        total_runs = len(runs_rows)
        active_runs = sum(1 for r in runs_rows if r.status in ("running", "queued"))
        done_runs = sum(1 for r in runs_rows if r.status == "done")
        success_rate = (done_runs / total_runs) if total_runs > 0 else 1.0

        last_run_dict: dict[str, Any] | None = None
        if runs_rows:
            lr = runs_rows[0]
            dur_ms = 0
            if lr.started_at and lr.ended_at:
                dur_ms = int((lr.ended_at - lr.started_at).total_seconds() * 1000)
            last_run_dict = {
                "id": lr.id,
                "status": lr.status,
                "error": lr.error,
                "started_at": lr.started_at.isoformat() if lr.started_at else None,
                "ended_at": lr.ended_at.isoformat() if lr.ended_at else None,
                "duration_ms": dur_ms,
                "tokens": lr.total_tokens,
                "cost_usd": lr.total_cost_usd,
            }

        # Query slowest step across Spans
        slowest_step_dict: dict[str, Any] | None = None
        spans_query = (
            select(Span)
            .where(Span.tenant_id == tenant_id)
            .order_by(desc(Span.latency_ms))
            .limit(1)
        )
        slowest_span = (await session.execute(spans_query)).scalar_one_or_none()
        if slowest_span and slowest_span.latency_ms > 0:
            slowest_step_dict = {
                "name": slowest_span.name,
                "kind": slowest_span.kind,
                "latency_ms": slowest_span.latency_ms,
                "model": slowest_span.model,
            }

        # Query Triggers
        trig_query = select(Trigger).where(
            Trigger.tenant_id == tenant_id,
            Trigger.project_id == project_id,
            Trigger.enabled.is_(True),
        )
        if workflow_id:
            trig_query = trig_query.where(Trigger.workflow_id == workflow_id)
        trig_rows = list((await session.execute(trig_query)).scalars())
        triggers_list = [
            {
                "id": t.id,
                "kind": t.kind,
                "workflow_id": t.workflow_id,
                "last_fired_at": t.last_fired_at.isoformat() if t.last_fired_at else None,
                "config": t.config,
            }
            for t in trig_rows
        ]

        return WorkflowMonitoringReport(
            workflow_id=workflow_id,
            workflow_name=wf_name,
            active_runs=active_runs,
            total_runs=total_runs,
            success_rate=round(success_rate, 3),
            last_run=last_run_dict,
            slowest_step=slowest_step_dict,
            triggers=triggers_list,
        )

    @classmethod
    async def diagnose_failure(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        run_id: str,
    ) -> WorkflowExecutionDiagnostic:
        """Inspect actual execution traces to diagnose root cause and recommend safe correction."""
        run = await session.get(Run, run_id)
        if not run or run.tenant_id != tenant_id:
            raise ValueError(f"Run '{run_id}' not found.")

        wf = await WorkflowService.get(session, tenant_id, run.workflow_id)
        wf_name = wf.name if wf else "Unknown Workflow"

        err_text = run.error or ""
        traces = list((await session.execute(select(Trace).where(Trace.run_id == run_id))).scalars())
        trace_refs = [t.id for t in traces]

        spans = []
        if trace_refs:
            spans = list((await session.execute(select(Span).where(Span.trace_id.in_(trace_refs)))).scalars())

        longest_span = max(spans, key=lambda s: s.latency_ms) if spans else None
        longest_dict = (
            {"name": longest_span.name, "latency_ms": longest_span.latency_ms, "kind": longest_span.kind}
            if longest_span
            else None
        )

        category = "general_execution_failure"
        root_cause = err_text or "Execution terminated unexpectedly."
        proposed_repair = None
        requires_approval = False

        low_err = err_text.lower()
        if any(k in low_err for k in ("unauthorized", "permission", "policy", "requires approval", "forbidden")):
            category = "unauthorized_tool_operation"
            root_cause = f"Security Policy violation: {err_text}"
            proposed_repair = "Request user approval to associate the required tool or grant explicit policy authorization."
            requires_approval = True
        elif any(k in low_err for k in ("tool", "mcp", "connector", "endpoint")):
            category = "tool_failure"
            root_cause = f"External tool integration failure: {err_text}"
            proposed_repair = "Verify integration authentication credentials and retest tool connectivity."
            requires_approval = False
        elif any(k in low_err for k in ("model", "provider", "quota", "token", "rate limit")):
            category = "model_provider_error"
            root_cause = f"Model provider error: {err_text}"
            proposed_repair = "Check model provider rate limits, configure fallback model, or adjust max tokens."
            requires_approval = False
        elif any(k in low_err for k in ("timeout", "timed out", "deadline")):
            category = "timeout"
            root_cause = "Operation exceeded runtime timeout threshold."
            proposed_repair = "Increase node timeout limit or optimize retrieval/tool step."
            requires_approval = False
        elif any(k in low_err for k in ("schema", "validation", "unknown node", "keyerror")):
            category = "invalid_workflow_configuration"
            root_cause = f"Workflow graph schema or mapping error: {err_text}"
            proposed_repair = "Auto-repair node configuration and state reducers against Alberto's schema."
            requires_approval = False

        return WorkflowExecutionDiagnostic(
            run_id=run.id,
            workflow_id=run.workflow_id,
            workflow_name=wf_name,
            status=run.status,
            error=run.error,
            category=category,
            longest_step=longest_dict,
            root_cause=root_cause,
            trace_references=trace_refs,
            proposed_repair=proposed_repair,
            requires_approval=requires_approval,
        )

    @classmethod
    async def analyze_workflow_optimisation(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        workflow_id: str,
    ) -> WorkflowOptimisationReport:
        """Analyze workflow execution history and propose grounded optimisations."""
        wf = await WorkflowService.get(session, tenant_id, workflow_id)
        if not wf:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        runs = list((await session.execute(
            select(Run)
            .where(Run.tenant_id == tenant_id, Run.workflow_id == workflow_id)
            .order_by(desc(Run.created_at))
            .limit(30)
        )).scalars())

        recommendations: list[dict[str, Any]] = []
        token_savings = 0
        latency_reduction_ms = 0

        ex = wf.executable or {}
        nodes = ex.get("nodes", [])

        # Check for sequential agents that only call one tool
        agent_nodes = [n for n in nodes if n.get("type") == "agent"]
        if len(agent_nodes) >= 2:
            recommendations.append({
                "type": "parallelize_agents",
                "title": "Parallelize independent agent steps",
                "description": f"Workflow has {len(agent_nodes)} sequential agents. If their inputs are independent, fan-out execution can reduce turnaround latency.",
                "tradeoff": "Increases peak concurrent model calls.",
            })
            latency_reduction_ms += 1200

        # Check if single tool agent can be replaced with deterministic tool node
        for an in agent_nodes:
            cfg = an.get("config", {})
            if len(cfg.get("tools", [])) == 1 and not cfg.get("subagents"):
                recommendations.append({
                    "type": "deterministic_tool_replacement",
                    "title": f"Replace agent '{cfg.get('name', 'worker')}' with deterministic tool node",
                    "description": "Agent performs a single fixed tool call. Replacing it with a deterministic tool node eliminates an LLM round-trip.",
                    "tradeoff": "Removes model flexibility in parameter formatting.",
                })
                token_savings += 600
                latency_reduction_ms += 800

        # Check error rate across recent runs
        if runs:
            err_count = sum(1 for r in runs if r.status == "error")
            if err_count / len(runs) > 0.2:
                recommendations.append({
                    "type": "add_retry_policy",
                    "title": "Add retry and exponential backoff",
                    "description": f"Recent runs exhibit a {(err_count / len(runs)) * 100:.0f}% error rate. Configure automatic retries for transient failures.",
                    "tradeoff": "May slightly increase duration for failing runs.",
                })

        return WorkflowOptimisationReport(
            workflow_id=workflow_id,
            workflow_name=wf.name,
            recommendations=recommendations,
            potential_token_savings=token_savings,
            potential_latency_reduction_ms=latency_reduction_ms,
        )

    @classmethod
    async def apply_safe_self_repair(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        workflow_id: str,
        repair_type: str = "auto",
        require_approval_for_privileges: bool = True,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Safely repair non-behavioral configuration errors, rejecting unauthorized permission expansion."""
        wf = await WorkflowService.get(session, tenant_id, workflow_id)
        if not wf:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        if expected_revision is not None and (wf.active_version or 1) != expected_revision:
            raise ValueError(
                f"Stale-revision: Workflow active version ({wf.active_version}) does not match expected revision ({expected_revision}); self-repair rejected."
            )

        ex = dict(wf.executable or {})
        capabilities = await cls.discover_capabilities(session, tenant_id, project_id)

        # Run bounded self-correction
        corrected_exec, is_valid, errors = cls.self_correct_workflow(ex, [], capabilities)

        # Enforce security invariant: no silent addition of destructive/write tools
        if require_approval_for_privileges:
            orig_tools = set()
            for n in ex.get("nodes", []):
                orig_tools.update(n.get("config", {}).get("tools", []))
            new_tools = set()
            for n in corrected_exec.get("nodes", []):
                new_tools.update(n.get("config", {}).get("tools", []))

            added_tools = new_tools - orig_tools
            if added_tools:
                raise ValueError(
                    f"Security Invariant Violation: Self-repair cannot add new tools {added_tools} without explicit approval."
                )

        wf.executable = corrected_exec
        wf.canvas = cls.compute_canvas(corrected_exec.get("nodes", []), corrected_exec.get("edges", []))
        wf.active_version = (wf.active_version or 1) + 1
        await session.commit()
        await session.refresh(wf)

        return {
            "repaired": is_valid,
            "workflow_id": wf.id,
            "workflow_revision": wf.active_version,
            "remaining_errors": errors,
            "message": "Workflow successfully self-repaired and validated." if is_valid else "Self-repair completed with remaining validation warnings.",
        }

    _auto_repair_attempts: dict[str, int] = {}
    _MAX_REPAIR_ATTEMPTS: int = 2

    @classmethod
    async def get_repair_attempt_count(
        cls,
        session: AsyncSession,
        workflow_id: str,
        fingerprint: str,
        workflow_revision: int | None = None,
    ) -> int:
        """Durable SQLite query for repair attempts across restarts and separate worker instances."""
        from alberto.models import WorkflowRepairAttempt
        row = (
            await session.execute(
                select(WorkflowRepairAttempt).where(
                    WorkflowRepairAttempt.workflow_id == workflow_id,
                    WorkflowRepairAttempt.failure_fingerprint == fingerprint,
                )
            )
        ).scalar_one_or_none()
        return row.attempt_count if row else 0

    @classmethod
    async def record_repair_attempt(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        workflow_id: str,
        workflow_revision: int,
        fingerprint: str,
        source_run_id: str | None,
        status: str = "attempted",
        outcome: dict | None = None,
    ) -> int:
        """Durably record or increment repair attempt in SQLite."""
        from alberto.models import WorkflowRepairAttempt
        row = (
            await session.execute(
                select(WorkflowRepairAttempt).where(
                    WorkflowRepairAttempt.workflow_id == workflow_id,
                    WorkflowRepairAttempt.failure_fingerprint == fingerprint,
                )
            )
        ).scalar_one_or_none()
        now = datetime.utcnow()
        if row:
            if status == "attempted":
                row.attempt_count += 1
            row.workflow_revision = workflow_revision
            row.repair_status = status
            row.last_attempt_at = now
            row.source_run_id = source_run_id or row.source_run_id
            if outcome is not None:
                row.repair_outcome = outcome
            await session.commit()
            return row.attempt_count
        else:
            new_row = WorkflowRepairAttempt(
                tenant_id=tenant_id,
                project_id=project_id,
                workflow_id=workflow_id,
                workflow_revision=workflow_revision,
                failure_fingerprint=fingerprint,
                source_run_id=source_run_id,
                attempt_count=1,
                repair_status=status,
                last_attempt_at=now,
                repair_outcome=outcome or {},
            )
            session.add(new_row)
            await session.commit()
            return 1


    @classmethod
    async def on_run_failure(
        cls,
        tenant_id: str,
        project_id: str,
        workflow_id: str,
        run_id: str,
        error: str,
    ) -> WorkflowExecutionDiagnostic | None:
        """Asynchronously analyze run failure, persist diagnosis, and perform bounded safe self-repair if permitted."""
        try:
            import hashlib

            from alberto.db.base import SessionLocal
            from alberto.models import Workflow

            # Clean error fingerprint
            err_clean = str(error or "unknown_error").strip()
            fingerprint = hashlib.sha256(err_clean[:200].encode()).hexdigest()[:32]

            async with SessionLocal() as session:
                # 1. Resolve workflow revision
                wf = await session.get(Workflow, workflow_id) if workflow_id else None
                wf_revision = (wf.active_version if wf else 1) or 1

                # 2. Durable check of repair attempt count in SQLite
                attempt_count = await cls.get_repair_attempt_count(session, workflow_id, fingerprint, wf_revision)
                if attempt_count >= cls._MAX_REPAIR_ATTEMPTS:
                    log.info(
                        "Durable max auto-repair attempts (%d) reached for workflow %s revision %d (fingerprint %s); skipping auto-repair.",
                        cls._MAX_REPAIR_ATTEMPTS, workflow_id, wf_revision, fingerprint,
                    )
                    return None

                # 3. Diagnose failure
                diag = await cls.diagnose_failure(session, tenant_id, project_id, run_id)
                log.info(
                    "Autonomous Failure Diagnosis for run %s: category=%s root_cause=%s requires_approval=%s",
                    run_id, diag.category, diag.root_cause, diag.requires_approval,
                )

                # 4. If repair is safe and does not require approval
                if not diag.requires_approval and workflow_id and wf:
                    # Durably record the attempt
                    await cls.record_repair_attempt(
                        session=session,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        workflow_id=workflow_id,
                        workflow_revision=wf_revision,
                        fingerprint=fingerprint,
                        source_run_id=run_id,
                        status="attempted",
                    )
                    cls._auto_repair_attempts[f"{workflow_id}:{fingerprint}"] = attempt_count + 1

                    try:
                        repair_outcome = await cls.apply_safe_self_repair(
                            session=session,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            workflow_id=workflow_id,
                            repair_type="auto",
                            require_approval_for_privileges=True,
                            expected_revision=wf_revision,
                        )
                        # Record successful durable repair outcome
                        await cls.record_repair_attempt(
                            session=session,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            workflow_id=workflow_id,
                            workflow_revision=wf_revision,
                            fingerprint=fingerprint,
                            source_run_id=run_id,
                            status="repaired",
                            outcome=repair_outcome,
                        )
                        log.info("Autonomous safe self-repair applied to workflow %s following failure in run %s", workflow_id, run_id)
                    except Exception as err:
                        log.debug("Auto-repair skipped or halted by security guard: %s", err)
                        await cls.record_repair_attempt(
                            session=session,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            workflow_id=workflow_id,
                            workflow_revision=wf_revision,
                            fingerprint=fingerprint,
                            source_run_id=run_id,
                            status="blocked",
                            outcome={"error": str(err)},
                        )
                return diag
        except Exception as e:
            log.warning("Autonomous failure diagnosis skipped for run %s: %s", run_id, e)
            return None
