"""Tool Manager Service.

System subagent responsible for:
1. Tool catalog intelligence, classification, recommendations, and diagnostics.
2. Deterministic effect (read/write/delete) and risk (low/medium/high/critical) classification.
3. Strict deterministic policy enforcement (LLM cannot independently approve sensitive capabilities).
4. Safe fallback when LLM model is unavailable or offline.
5. Identifying duplicate/overlapping capabilities across tools.
6. Intent-based tool suggestion for agent reasoning.
7. Diagnostics for execution failures.
8. LadybugDB Knowledge Graph projection handoff.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.engine.models import resolve_model
from alberto.models import Agent
from alberto.schemas.tool_manager import (
    ToolActivationRecommendation,
    ToolAnalysisResult,
    ToolDiagnosticReport,
    ToolEffect,
    ToolMatchSuggestion,
    ToolRiskLevel,
)

logger = logging.getLogger("alberto.services.tool_manager")

READ_VERBS = {
    "get", "fetch", "read", "list", "search", "find", "query", "check",
    "describe", "inspect", "show", "view", "status", "lookup", "calculate",
    "count", "probe", "recall", "browse", "scan", "preview",
}

WRITE_VERBS = {
    "create", "post", "send", "put", "update", "edit", "write", "set",
    "insert", "add", "append", "modify", "patch", "upload", "submit",
    "publish", "trigger", "sync", "execute", "run", "store", "save",
    "remember", "start", "stop", "restart", "connect",
}

DELETE_VERBS = {
    "delete", "remove", "drop", "destroy", "purge", "clear", "wipe",
    "format", "reset", "erase", "cancel", "kill", "unlink", "disconnect",
    "uninstall",
}

# Ambiguous operations that must never be assumed read-only or auto-activated
AMBIGUOUS_OPERATIONS = {
    "execute_query", "run_command", "invoke_action", "execute_script",
    "manage_resources", "command", "script", "query_exec", "eval", "manage", "action",
}

SENSITIVE_KEYWORDS = {
    "password", "secret", "token", "key", "credential", "auth", "payment",
    "credit", "money", "billing", "transfer", "reboot", "shutdown",
    "database", "drop", "sudo", "root", "admin", "unlock", "door", "lock",
}

CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "communication": {"email", "mail", "message", "chat", "slack", "sms", "notify", "teams", "discord"},
    "smart_home": {"light", "switch", "sensor", "thermostat", "camera", "door", "lock", "home", "hass", "device"},
    "productivity": {"calendar", "event", "task", "todo", "jira", "linear", "note", "notion", "sheet", "doc"},
    "data": {"database", "sql", "query", "table", "postgres", "mysql", "airtable", "record", "export"},
    "system": {"file", "system", "command", "process", "memory", "graph", "cpu", "disk", "shell", "config"},
    "development": {"git", "github", "repo", "commit", "issue", "branch", "pr", "deploy", "build"},
}


class ToolManagerService:
    """Coordinates tool intelligence, classification, recommendations, and diagnostics."""

    @classmethod
    async def get_tool_manager_model(
        cls, session: AsyncSession, tenant_id: str, project_id: str
    ) -> tuple[Any, str | None]:
        """Resolve the model configured for the Tool Manager system agent, or fall back to context default."""
        agent_row = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.project_id == project_id,
                    Agent.system_key == "tool_manager",
                )
            )
        ).scalar_one_or_none()

        model_ref: str | None = None
        if agent_row and agent_row.config:
            model_ref = agent_row.config.get("model") or None

        from alberto.services.runtime import make_runtime_ctx
        ctx = make_runtime_ctx(tenant_id, project_id)
        resolved = resolve_model(model_ref, ctx)
        return resolved, model_ref or ctx.default_model

    @classmethod
    def classify_effect_and_risk(
        cls,
        name: str,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> tuple[ToolEffect, ToolRiskLevel, ToolActivationRecommendation]:
        """Deterministic policy evaluation for tool effect, risk, and activation recommendation.

        Guarantees:
        - Read-only tools can be safely recommended for 'auto' activation.
        - Ambiguous operations (execute_query, run_command, invoke_action, execute_script, manage_resources)
          default to high-risk and manual_review; NEVER auto-activated.
        - Destructive (delete) tools are classified as high/critical risk and require review.
        - Write tools require review before activation.
        - Tools with required_entitlements or requires_approval can NEVER be 'auto'.
        """
        clean_name = name.lower()
        combined_text = f"{name} {description}".lower()
        tokens = set(re.findall(r"\b[a-z0-9_\-]+\b", combined_text))

        # Check ambiguous operations first
        is_ambiguous = any(op in clean_name for op in AMBIGUOUS_OPERATIONS) or bool(tokens & AMBIGUOUS_OPERATIONS)

        # Check verb matches
        has_delete = bool(tokens & DELETE_VERBS) or any(v in clean_name for v in DELETE_VERBS)
        has_write = bool(tokens & WRITE_VERBS) or any(v in clean_name for v in WRITE_VERBS)
        has_read = bool(tokens & READ_VERBS) or any(v in clean_name for v in READ_VERBS)
        has_sensitive = bool(tokens & SENSITIVE_KEYWORDS)

        # Explicit overrides in config
        if cfg:
            if cfg.get("effect") in ("read", "write", "delete"):
                has_delete = cfg["effect"] == "delete"
                has_write = cfg["effect"] == "write"
                has_read = cfg["effect"] == "read"
            if cfg.get("requires_approval") or cfg.get("required_entitlements"):
                has_sensitive = True

        effect: ToolEffect = "unknown"
        risk: ToolRiskLevel = "medium"
        activation: ToolActivationRecommendation = "manual_review"

        if is_ambiguous:
            # Ambiguous operations: default to conservative write / high risk
            effect = "write" if not has_delete else "delete"
            risk = "critical" if has_sensitive or "script" in clean_name or "command" in clean_name else "high"
            activation = "restricted" if has_sensitive else "manual_review"
        elif has_delete:
            effect = "delete"
            risk = "critical" if has_sensitive else "high"
            activation = "restricted" if has_sensitive else "manual_review"
        elif has_write:
            effect = "write"
            risk = "high" if has_sensitive else "medium"
            activation = "manual_review"
        elif has_read and not has_write and not has_delete:
            effect = "read"
            risk = "medium" if has_sensitive else "low"
            activation = "manual_review" if has_sensitive else "auto"
        else:
            effect = "unknown"
            risk = "medium"
            activation = "manual_review"

        # Hard invariant: any tool requiring entitlements or approval can NEVER be auto-activated
        if cfg and (cfg.get("required_entitlements") or cfg.get("requires_approval")):
            if activation == "auto":
                activation = "manual_review"
        return effect, risk, activation

    @classmethod
    def infer_category(cls, name: str, description: str = "") -> str:
        """Infer functional category based on keywords."""
        combined_text = f"{name} {description}".lower()
        tokens = set(re.findall(r"\b[a-z0-9_\-]+\b", combined_text))

        best_cat = "utilities"
        max_matches = 0
        for cat, keywords in CATEGORY_KEYWORDS.items():
            matches = len(tokens & keywords)
            if matches > max_matches:
                max_matches = matches
                best_cat = cat

        return best_cat if max_matches > 0 else "utilities"

    @classmethod
    def enforce_policy_boundaries(
        cls,
        result: ToolAnalysisResult,
        det_effect: ToolEffect,
        det_risk: ToolRiskLevel,
        det_activation: ToolActivationRecommendation,
        cfg: dict[str, Any] | None = None,
    ) -> ToolAnalysisResult:
        """Clamp model-suggested risk/activation against deterministic policy boundaries.

        Rules:
        - LLM cannot downgrade 'delete' or 'write' effect to 'read'.
        - LLM cannot downgrade 'high' or 'critical' risk to 'low'.
        - LLM cannot upgrade sensitive or write/delete tools to 'auto' activation.
        """
        # Effect enforcement
        if det_effect == "delete" and result.effect != "delete":
            result.warnings.append(f"Effect clamped to 'delete' from '{result.effect}' by deterministic policy.")
            result.effect = "delete"
        elif det_effect == "write" and result.effect == "read":
            result.warnings.append("Effect clamped to 'write' from 'read' by deterministic policy.")
            result.effect = "write"

        # Risk enforcement: risk order low < medium < high < critical
        risk_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        if risk_rank.get(result.risk, 2) < risk_rank.get(det_risk, 2):
            result.warnings.append(f"Risk level raised to '{det_risk}' from '{result.risk}' by deterministic policy.")
            result.risk = det_risk

        # Activation enforcement: auto is prohibited for non-read or sensitive tools
        if result.effect in ("write", "delete") or result.risk in ("high", "critical"):
            if result.recommended_activation == "auto":
                result.warnings.append("Activation recommendation clamped to 'manual_review' due to side effects.")
                result.recommended_activation = "manual_review"

        if cfg and (cfg.get("required_entitlements") or cfg.get("requires_approval")):
            if result.recommended_activation == "auto":
                result.recommended_activation = "manual_review"

        return result

    @classmethod
    async def analyze_tool(
        cls,
        tool_id: str,
        name: str,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        existing_tools: list[dict[str, Any]] | None = None,
        cfg: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
        tenant_id: str | None = None,
        project_id: str | None = None,
        use_llm: bool = False,
    ) -> ToolAnalysisResult:
        """Analyze a tool and return structured classification and recommendations.

        Deterministic-first, with optional LLM reasoning when requested.
        Guarantees safe fallback if the LLM is unavailable.
        """
        det_effect, det_risk, det_activation = cls.classify_effect_and_risk(
            name=name, description=description, input_schema=input_schema, cfg=cfg
        )
        category = cls.infer_category(name, description)

        # Detect similar/overlapping tools by name/category token overlap
        similar_ids: list[str] = []
        if existing_tools:
            name_tokens = set(re.findall(r"\b[a-z0-9]+\b", name.lower()))
            for other in existing_tools:
                other_id = other.get("id") or other.get("tool_id")
                if not other_id or other_id == tool_id:
                    continue
                other_name = other.get("name", "").lower()
                other_tokens = set(re.findall(r"\b[a-z0-9]+\b", other_name))
                if len(name_tokens & other_tokens) >= 2 or (name_tokens & other_tokens and name_tokens == other_tokens):
                    similar_ids.append(other_id)

        base_capabilities: list[str] = []
        for verb in set(re.findall(r"\b[a-z0-9_\-]+\b", f"{name} {description}".lower())):
            if verb in READ_VERBS or verb in WRITE_VERBS or verb in DELETE_VERBS:
                base_capabilities.append(verb)
        if not base_capabilities and category:
            base_capabilities.append(category)

        result = ToolAnalysisResult(
            tool_id=tool_id,
            category=category,
            capabilities=sorted(list(set(base_capabilities))),
            effect=det_effect,
            risk=det_risk,
            description=description or f"Tool providing {name}",
            similar_tool_ids=similar_ids,
            recommended_activation=det_activation,
            confidence=0.85,
            warnings=[],
        )

        if not use_llm or session is None or not tenant_id or not project_id:
            return result

        # On-demand LLM enhancement
        try:
            model, _ = await cls.get_tool_manager_model(session, tenant_id, project_id)
            if hasattr(model, "with_structured_output") and callable(getattr(model, "with_structured_output", None)):
                structured_model = model.with_structured_output(ToolAnalysisResult)
                prompt = (
                    f"Analyze this tool for capability classification:\n"
                    f"Tool ID: {tool_id}\n"
                    f"Name: {name}\n"
                    f"Description: {description}\n"
                    f"Input Schema: {json.dumps(input_schema or {})}\n"
                    f"Return structured ToolAnalysisResult JSON."
                )
                async with asyncio.timeout(30.0):
                    llm_res = await structured_model.ainvoke([
                        SystemMessage(content="You are Alberto's Tool Manager. Provide accurate tool classification."),
                        HumanMessage(content=prompt),
                    ])
                if isinstance(llm_res, ToolAnalysisResult):
                    # Enforce deterministic policy boundaries
                    return cls.enforce_policy_boundaries(llm_res, det_effect, det_risk, det_activation, cfg=cfg)
        except Exception as e:
            logger.info("LLM tool analysis fallback to deterministic rules: %s", e)
            result.warnings.append("LLM analysis unavailable; deterministic classification applied.")

        return result

    @classmethod
    def suggest_tools_for_intent(
        cls,
        intent: str,
        tools: list[dict[str, Any]],
        top_k: int = 5,
    ) -> list[ToolMatchSuggestion]:
        """Suggest suitable registered tools for a given user intent using deterministic metadata matching."""
        intent_lower = intent.lower()
        intent_tokens = set(re.findall(r"\b[a-z0-9_\-]+\b", intent_lower))

        suggestions: list[ToolMatchSuggestion] = []
        for t in tools:
            tid = str(t.get("id") or t.get("tool_id") or "")
            tname = str(t.get("name") or "")
            tdesc = str(t.get("description") or "")
            cfg = t.get("config") or {}
            caps = cfg.get("capabilities") or [tname]

            score = 0.0
            reasons: list[str] = []

            # Name match
            if tname.lower() in intent_lower:
                score += 0.5
                reasons.append("Exact name match")

            # Token overlap
            t_tokens = set(re.findall(r"\b[a-z0-9_\-]+\b", f"{tname} {tdesc}".lower()))
            overlap = intent_tokens & t_tokens
            if overlap:
                score += min(0.4, len(overlap) * 0.1)
                reasons.append(f"Matched keywords: {', '.join(sorted(list(overlap))[:4])}")

            # Capability match
            for cap in caps:
                if cap.lower() in intent_lower:
                    score += 0.3
                    reasons.append(f"Matches capability '{cap}'")
                    break

            if score > 0.1:
                effect, risk, _ = cls.classify_effect_and_risk(tname, tdesc, cfg=cfg)
                suggestions.append(
                    ToolMatchSuggestion(
                        tool_id=tid,
                        tool_name=tname,
                        score=min(1.0, round(score, 2)),
                        reason="; ".join(reasons) or "General capability match",
                        capabilities=caps,
                        effect=effect,
                        risk=risk,
                    )
                )

        suggestions.sort(key=lambda x: x.score, reverse=True)
        return suggestions[:top_k]

    @classmethod
    def diagnose_execution_failures(
        cls,
        tool_id: str,
        tool_name: str,
        recent_errors: list[str] | None = None,
        last_tested_status: str | None = None,
    ) -> ToolDiagnosticReport:
        """Diagnose repeated execution failures or connection issues for a tool."""
        errors = recent_errors or []
        combined_errors = " ".join(errors).lower()

        root_cause = "none"
        health = "healthy" if (not errors and last_tested_status != "fail") else "degraded"
        recommendations: list[str] = []

        if any(w in combined_errors for w in ("401", "403", "unauthorized", "forbidden", "token expired", "invalid_grant")):
            root_cause = "auth"
            health = "error"
            recommendations.append("Authentication expired or invalid. Reconnect account or refresh credentials.")
        elif any(w in combined_errors for w in ("429", "rate limit", "too many requests")):
            root_cause = "rate_limit"
            health = "degraded"
            recommendations.append("Integration rate limit exceeded. Verify rate limit configuration or backoff.")
        elif any(w in combined_errors for w in ("timeout", "timed out", "connection timed out")):
            root_cause = "timeout"
            health = "degraded"
            recommendations.append("Remote endpoint timed out. Increase timeout_seconds or check provider availability.")
        elif any(w in combined_errors for w in ("validation error", "missing field", "invalid input", "schema")):
            root_cause = "schema_mismatch"
            health = "degraded"
            recommendations.append("Schema mismatch: required arguments are missing or invalid in call.")
        elif any(w in combined_errors for w in ("connection refused", "econnrefused", "name resolution", "dns", "unreachable")):
            root_cause = "network"
            health = "error"
            recommendations.append("Network host unreachable. Verify endpoint URL and egress policy.")
        elif errors:
            root_cause = "internal_error"
            health = "error"
            recommendations.append(f"Review error trace: {errors[-1][:120]}")

        summary = (
            f"Tool '{tool_name}' diagnosed with root cause: {root_cause}."
            if root_cause != "none"
            else f"Tool '{tool_name}' has no active errors."
        )

        return ToolDiagnosticReport(
            tool_id=tool_id,
            tool_name=tool_name,
            health_status=health,
            failure_count=len(errors),
            root_cause_category=root_cause,  # type: ignore[arg-type]
            summary=summary,
            recommendations=recommendations,
        )

    @classmethod
    async def project_tool_to_graph(
        cls,
        tenant_id: str,
        project_id: str,
        tool_id: str,
        tool_name: str,
        integration_name: str,
        capabilities: list[str],
        description: str = "",
    ) -> None:
        """Project Tool IMPLEMENTS Capability and Integration PROVIDES Capability into LadybugDB via GraphManagerService."""
        try:
            from alberto.knowledge.graph import (
                GraphEntity,
                GraphRelationship,
                make_entity_id,
                make_relationship_id,
            )
            from alberto.services.graph_manager import GraphManagerService

            entities: list[GraphEntity] = []
            relationships: list[GraphRelationship] = []

            # 1. Integration entity
            int_id = make_entity_id(tenant_id, project_id, integration_name)
            int_ent = GraphEntity(
                id=int_id,
                tenant_id=tenant_id,
                project_id=project_id,
                name=integration_name,
                canonical_name=integration_name.strip().lower(),
                kind="integration",
                description=f"Integration: {integration_name}",
                source=f"integration:{integration_name}",
                confidence=1.0,
            )
            entities.append(int_ent)

            # 2. Tool entity
            t_eid = make_entity_id(tenant_id, project_id, f"tool:{tool_name}")
            tool_ent = GraphEntity(
                id=t_eid,
                tenant_id=tenant_id,
                project_id=project_id,
                name=tool_name,
                canonical_name=tool_name.strip().lower(),
                kind="tool",
                description=description or f"Tool {tool_name}",
                source=f"tool:{tool_id}",
                confidence=1.0,
            )
            entities.append(tool_ent)

            # 3. Capability entities and relationships
            for cap in capabilities:
                cap_id = make_entity_id(tenant_id, project_id, f"cap:{cap}")
                cap_ent = GraphEntity(
                    id=cap_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    name=cap,
                    canonical_name=cap.strip().lower(),
                    kind="capability",
                    description=f"Capability: {cap}",
                    source=f"tool:{tool_id}",
                    confidence=1.0,
                )
                entities.append(cap_ent)

                # Integration PROVIDES Capability
                rel_prov = GraphRelationship(
                    id=make_relationship_id(tenant_id, project_id, int_ent.id, cap_ent.id, "PROVIDES"),
                    source_id=int_ent.id,
                    target_id=cap_ent.id,
                    kind="PROVIDES",
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source=f"integration:{integration_name}",
                    confidence=1.0,
                )
                relationships.append(rel_prov)

                # Tool IMPLEMENTS Capability
                rel_impl = GraphRelationship(
                    id=make_relationship_id(tenant_id, project_id, tool_ent.id, cap_ent.id, "IMPLEMENTS"),
                    source_id=tool_ent.id,
                    target_id=cap_ent.id,
                    kind="IMPLEMENTS",
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source=f"tool:{tool_id}",
                    confidence=1.0,
                )
                relationships.append(rel_impl)

            # Delegate Knowledge Graph mutation to GraphManagerService
            await GraphManagerService.apply_resolved(
                tenant_id=tenant_id,
                project_id=project_id,
                resolved_entities=entities,
                resolved_relationships=relationships,
            )
        except Exception as e:
            logger.warning("Could not project tool %s to Knowledge Graph via GraphManagerService: %s", tool_name, e)

    @classmethod
    async def execute_delegated_tool(
        cls,
        tenant_id: str,
        project_id: str,
        tool_id_or_capability: str,
        parameters: dict[str, Any] | None = None,
        user_context: dict[str, Any] | None = None,
        execution_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a tool via Master Agent delegation through Tool Manager.

        Preserves:
        - Originating user identity and project scope.
        - Entitlement and authorization context.
        - Deterministic resolution when tool is known/unambiguous.
        - Runtime activation and approval policy checks.
        """
        from alberto.db import SessionLocal
        from alberto.models import Tool
        from alberto.services.tool_policy import ToolPolicyService
        from alberto.services.tools import ToolService

        parameters = parameters or {}
        user_context = user_context or {}
        execution_context = execution_context or {}

        async with SessionLocal() as s:
            # 1. Deterministic resolution: ID match or exact name match
            tool_row = (
                await s.execute(
                    select(Tool).where(
                        Tool.tenant_id == tenant_id,
                        Tool.project_id == project_id,
                        (Tool.id == tool_id_or_capability) | (Tool.name == tool_id_or_capability),
                    )
                )
            ).scalar_one_or_none()

            # 2. Semantic capability match if not exact match
            if tool_row is None:
                tools_rows = (
                    await s.execute(
                        select(Tool).where(
                            Tool.tenant_id == tenant_id,
                            Tool.project_id == project_id,
                            Tool.enabled.is_(True),
                        )
                    )
                ).scalars().all()
                tools_list = [
                    {
                        "id": t.id,
                        "name": t.name,
                        "description": (t.config or {}).get("description", ""),
                        "config": t.config,
                    }
                    for t in tools_rows
                ]
                suggestions = cls.suggest_tools_for_intent(tool_id_or_capability, tools_list, top_k=1)
                if suggestions:
                    best_id = suggestions[0].tool_id
                    tool_row = next((t for t in tools_rows if t.id == best_id), None)

            if tool_row is None:
                return {
                    "ok": False,
                    "error": f"Tool Manager could not resolve any registered tool matching '{tool_id_or_capability}'.",
                }

            # 3. Policy Engine Evaluation
            exec_ctx = dict(execution_context or {})
            if "arguments_hash" not in exec_ctx:
                import hashlib
                args_json = json.dumps(parameters or {}, sort_keys=True)
                exec_ctx["arguments_hash"] = hashlib.sha256(args_json.encode()).hexdigest()

            decision = await ToolPolicyService.evaluate_execution(
                tenant_id=tenant_id,
                project_id=project_id,
                tool_id=tool_row.id,
                caller_type="tool_manager",
                caller_id="assistant",
                user_context=user_context,
                execution_context=exec_ctx,
                session=s,
            )

            if not decision.allowed:
                appr_id = None
                if decision.requires_approval:
                    appr_req = ToolPolicyService.create_approval_request(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        tool_id=tool_row.id,
                        tool_name=tool_row.name,
                        arguments=parameters,
                        user_context=user_context,
                        caller_type="tool_manager",
                        caller_id="assistant",
                    )
                    appr_id = appr_req.id
                return {
                    "ok": False,
                    "error": decision.reason,
                    "requires_approval": decision.requires_approval,
                    "approval_id": appr_id,
                    "tool_id": decision.tool_id,
                    "tool_name": decision.tool_name,
                    "effect": decision.effect,
                    "risk": decision.risk,
                }

            # 4. Secured Execution Runtime
            cfg = {
                **(tool_row.config or {}),
                "name": tool_row.name,
                "kind": tool_row.kind,
                "auth_provider_id": tool_row.auth_provider_id or (tool_row.config or {}).get("auth_provider_id"),
            }
            ctx = {"end_user_id": user_context.get("id"), **(user_context.get("context") or {})}
            res = await ToolService.test(tenant_id, project_id, cfg, parameters, ctx)
            return {
                "ok": res.get("ok", False),
                "tool_id": tool_row.id,
                "tool_name": tool_row.name,
                "result": res.get("projected") if res.get("ok") else None,
                "error": res.get("error"),
                "status": res.get("status"),
            }

    @classmethod
    async def analyze_discovered_tools(
        cls,
        tenant_id: str,
        project_id: str,
        tool_ids: list[str],
        integration_name: str = "integration",
    ) -> list[ToolAnalysisResult]:
        """Event-driven durable analysis of newly discovered or updated tools.

        Runs deterministic analysis, updates Knowledge Graph via Graph Manager,
        suppresses duplicate work via schema fingerprints, and recovers across restarts.
        """
        from alberto.db import SessionLocal
        from alberto.models import Tool, ToolAnalysisJob

        results: list[ToolAnalysisResult] = []
        if not tool_ids:
            return results

        try:
            async with SessionLocal() as s:
                rows = (
                    await s.execute(
                        select(Tool).where(
                            Tool.tenant_id == tenant_id,
                            Tool.project_id == project_id,
                            Tool.id.in_(tool_ids),
                        )
                    )
                ).scalars().all()

                for tool in rows:
                    cfg = dict(tool.config or {})
                    schema = cfg.get("input_schema") or cfg.get("parameters") or {}
                    schema_json = json.dumps(schema, sort_keys=True)
                    fingerprint = hashlib.sha256(schema_json.encode()).hexdigest()[:16]

                    # Deduplication check: suppress duplicate work if already completed
                    job = (
                        await s.execute(
                            select(ToolAnalysisJob).where(
                                ToolAnalysisJob.tenant_id == tenant_id,
                                ToolAnalysisJob.project_id == project_id,
                                ToolAnalysisJob.tool_id == tool.id,
                                ToolAnalysisJob.schema_fingerprint == fingerprint,
                            )
                        )
                    ).scalar_one_or_none()

                    if job and job.status == "completed":
                        continue

                    if job is None:
                        job = ToolAnalysisJob(
                            tenant_id=tenant_id,
                            project_id=project_id,
                            tool_id=tool.id,
                            schema_fingerprint=fingerprint,
                            status="running",
                        )
                        s.add(job)
                        await s.commit()
                        await s.refresh(job)
                    else:
                        job.status = "running"
                        await s.commit()

                    try:
                        analysis = await cls.analyze_tool(
                            tool_id=tool.id,
                            name=tool.name,
                            description=cfg.get("description", ""),
                            input_schema=schema,
                            cfg=cfg,
                            session=s,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            use_llm=False,
                        )
                        results.append(analysis)

                        cfg["capabilities"] = analysis.capabilities
                        cfg["effect"] = analysis.effect
                        cfg["risk"] = analysis.risk
                        if analysis.recommended_activation in ("manual_review", "restricted"):
                            cfg["requires_approval"] = True
                        tool.config = cfg

                        await cls.project_tool_to_graph(
                            tenant_id=tenant_id,
                            project_id=project_id,
                            tool_id=tool.id,
                            tool_name=tool.name,
                            integration_name=integration_name,
                            capabilities=analysis.capabilities,
                            description=analysis.description,
                        )

                        job.status = "completed"
                        job.result_summary = {
                            "effect": analysis.effect,
                            "risk": analysis.risk,
                            "capabilities": analysis.capabilities,
                        }
                        job.error_message = None
                        await s.commit()
                    except Exception as ex:
                        logger.warning("Tool analysis failed for tool '%s': %s", tool.id, ex)
                        job.retry_count += 1
                        if job.retry_count >= job.max_retries:
                            job.status = "failed"
                            job.error_message = str(ex)
                        else:
                            job.status = "pending"
                        cfg["effect"] = "unknown"
                        cfg["risk"] = "high"
                        cfg["requires_approval"] = True
                        tool.config = cfg
                        await s.commit()

        except Exception as e:
            logger.warning("Event-driven tool analysis failed: %s", e)

        return results

    @classmethod
    async def recover_pending_analysis_jobs(
        cls,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """Scan and recover tool analysis jobs that were interrupted by process restart."""
        from alberto.db import SessionLocal
        from alberto.models import ToolAnalysisJob

        recovered = 0
        try:
            async with SessionLocal() as s:
                q = select(ToolAnalysisJob).where(
                    ToolAnalysisJob.status.in_(["pending", "running"]),
                )
                if tenant_id:
                    q = q.where(ToolAnalysisJob.tenant_id == tenant_id)
                if project_id:
                    q = q.where(ToolAnalysisJob.project_id == project_id)

                jobs = (await s.execute(q)).scalars().all()
                tool_ids_by_scope: dict[tuple[str, str], list[str]] = {}
                for job in jobs:
                    if job.retry_count >= job.max_retries:
                        job.status = "failed"
                        job.error_message = f"Exceeded max retries ({job.max_retries}) after restart."
                    else:
                        job.retry_count += 1
                        job.status = "pending"
                        tool_ids_by_scope.setdefault((job.tenant_id, job.project_id), []).append(job.tool_id)
                        recovered += 1
                await s.commit()

                for (t_id, p_id), t_ids in tool_ids_by_scope.items():
                    await cls.analyze_discovered_tools(
                        tenant_id=t_id,
                        project_id=p_id,
                        tool_ids=t_ids,
                    )
        except Exception as e:
            logger.warning("Failed to recover pending tool analysis jobs: %s", e)
        return recovered

    @classmethod
    async def diagnose_channel(
        cls,
        session: AsyncSession,
        channel: Any,
    ) -> dict[str, Any]:
        """Diagnose communication channel connectivity, authentication, routing, and delivery status."""
        from alberto.models import Agent, ChannelEvent, Workflow

        issues: list[str] = []
        recommendations: list[str] = []
        health = "healthy"

        if not channel.enabled:
            health = "degraded"
            issues.append("Channel is currently disabled.")
            recommendations.append("Enable the channel to resume processing inbound communication.")

        if channel.routing_state == "needs_review":
            health = "degraded"
            issues.append("Channel routing requires review. Legacy implicit fallback has been removed.")
            recommendations.append("Confirm an explicit destination (Master Agent, Subagent, or Workflow) in Routing settings.")

        # Check target validity
        target_valid = True
        if channel.target_type == "workflow":
            wf_id = channel.target_id or channel.workflow_id
            if not wf_id:
                target_valid = False
                issues.append("Channel is configured to route to a Workflow, but no workflow ID is bound.")
                recommendations.append("Select an active workflow in channel routing configuration.")
            else:
                wf = (
                    await session.execute(
                        select(Workflow).where(
                            Workflow.id == wf_id,
                            Workflow.tenant_id == channel.tenant_id,
                            Workflow.project_id == channel.project_id,
                        )
                    )
                ).scalar_one_or_none()
                if wf is None:
                    target_valid = False
                    issues.append(f"Bound workflow '{wf_id}' not found in project.")
                    recommendations.append("Re-bind a valid workflow or change destination to Master Agent.")
                elif wf.status != "active":
                    target_valid = False
                    issues.append(f"Bound workflow '{wf.name}' is inactive (status: {wf.status}).")
                    recommendations.append("Activate the workflow or change destination to Master Agent.")
        elif channel.target_type == "subagent":
            if not channel.target_id:
                target_valid = False
                issues.append("Channel is configured to route to a Subagent, but no subagent ID is bound.")
                recommendations.append("Select an active subagent in channel routing configuration.")
            else:
                ag = (
                    await session.execute(
                        select(Agent).where(
                            Agent.id == channel.target_id,
                            Agent.tenant_id == channel.tenant_id,
                            Agent.project_id == channel.project_id,
                        )
                    )
                ).scalar_one_or_none()
                if ag is None:
                    target_valid = False
                    issues.append("Bound subagent not found in project.")
                    recommendations.append("Select a valid subagent in channel routing configuration.")
                elif (ag.config or {}).get("status") == "inactive":
                    target_valid = False
                    issues.append(f"Bound subagent '{ag.name}' is inactive.")
                    recommendations.append("Activate the subagent in Agents settings.")

        if not target_valid and health == "healthy":
            health = "error"

        # Check provider specifics
        cfg = channel.config or {}
        st = channel.state or {}
        if channel.type == "telegram":
            if not cfg.get("bot_token_ref"):
                issues.append("Telegram bot token reference is missing.")
                recommendations.append("Configure a Telegram bot token in channel settings.")
                health = "error"
            if st.get("connected") is False:
                last_err = st.get("last_error") or "Unknown connection error"
                issues.append(f"Telegram connection error: {last_err}")
                recommendations.append("Check bot token validity and network connectivity.")
                if health != "error":
                    health = "degraded"
        elif channel.type == "email":
            smtp = cfg.get("smtp") or {}
            if not smtp.get("host"):
                issues.append("SMTP outbound configuration is incomplete.")
                recommendations.append("Configure SMTP server details to enable automated email replies.")
                if health == "healthy":
                    health = "degraded"
            verif = cfg.get("verification") or {}
            if not verif.get("provider"):
                issues.append("Inbound webhook signature verification is not configured.")
                recommendations.append("Configure webhook verification (Mailgun, Basic Auth, or Shared Secret) to prevent spoofing.")

        # Check recent failures in ChannelEvent ledger
        recent_events = (
            await session.execute(
                select(ChannelEvent)
                .where(
                    ChannelEvent.channel_id == channel.id,
                    ChannelEvent.tenant_id == channel.tenant_id,
                )
                .order_by(ChannelEvent.created_at.desc())
                .limit(20)
            )
        ).scalars().all()

        fail_statuses = {"delivery_failed", "failed", "rejected", "quarantined", "interrupted"}
        failures = [ev for ev in recent_events if ev.status in fail_statuses]
        if failures and health == "healthy":
            health = "degraded"

        summary = (
            f"Channel '{channel.name}' is {health}."
            if not issues
            else f"Channel '{channel.name}' has {len(issues)} issue(s) detected: {'; '.join(issues[:2])}."
        )

        return {
            "channel_id": channel.id,
            "channel_name": channel.name,
            "type": channel.type,
            "enabled": channel.enabled,
            "health_status": health,
            "routing_state": channel.routing_state,
            "target_type": channel.target_type or "master_agent",
            "target_id": channel.target_id,
            "target_valid": target_valid,
            "issues": issues,
            "recommendations": recommendations,
            "recent_failure_count": len(failures),
            "summary": summary,
        }


# Aliasing ToolManagerService as IntegrationManagerService for v3 compatibility
IntegrationManagerService = ToolManagerService


