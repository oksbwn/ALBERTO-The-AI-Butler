"""Tool Policy Engine - Centralized Access Control and Execution Policy for Alberto.

Enforces:
- Default-deny tool access architecture.
- Built-in Tool Manager mediation for Master Agent.
- Explicit tool or ToolSet associations for Subagents and Workflows.
- Independent verification of:
    1. Tool registered
    2. Tool activated (enabled == True)
    3. Tool explicitly associated with caller
    4. Tool authorized for requesting user (entitlements/roles)
    5. Tool approved for current execution (HITL)
- Prevention of execution bypasses across all runtime entry points.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.config import settings
from alberto.db import SessionLocal
from alberto.models import Agent, Tool, Workflow

logger = logging.getLogger("alberto.services.tool_policy")


@dataclass
class PolicyDecision:
    """Outcome of a tool execution policy evaluation."""

    allowed: bool
    reason: str
    tool_id: str
    tool_name: str | None = None
    requires_approval: bool = False
    approval_request_id: str | None = None
    effect: str = "unknown"
    risk: str = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PendingApprovalRequest:
    """A persisted/tracked human-in-the-loop approval request for tool execution."""

    id: str
    tenant_id: str
    project_id: str
    tool_id: str
    tool_name: str
    arguments_hash: str
    requesting_user_id: str | None
    caller_type: str
    caller_id: str | None
    created_at: float
    expires_at: float
    status: str = "pending"  # pending | approved | rejected | consumed | expired
    decided_by: str | None = None


class ToolPolicyService:
    """Central policy engine for all tool resolution, discovery, and execution."""

    _pending_approvals: dict[str, PendingApprovalRequest] = {}

    @classmethod
    def _scrub_sensitive_dict(cls, data: Any) -> Any:
        """Recursively scrub sensitive arguments before writing to SQLite or logs."""
        if isinstance(data, dict):
            scrubbed = {}
            for k, v in data.items():
                k_lower = str(k).lower()
                if any(s in k_lower for s in ("password", "token", "secret", "api_key", "apikey", "auth", "credential", "private")):
                    scrubbed[k] = "[REDACTED]"
                else:
                    scrubbed[k] = cls._scrub_sensitive_dict(v)
            return scrubbed
        if isinstance(data, list):
            return [cls._scrub_sensitive_dict(item) for item in data]
        return data

    @classmethod
    def _get_sqlite_conn(cls) -> sqlite3.Connection | None:
        try:
            db_path = settings.database_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
            conn = sqlite3.connect(db_path, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.warning("Could not establish direct SQLite connection for tool policy: %s", e)
            return None

    @classmethod
    def clear_cache(cls) -> None:
        """Clear in-memory pending approvals cache (for testing / restart simulation)."""
        cls._pending_approvals.clear()

    @staticmethod
    def hash_arguments(arguments: dict[str, Any] | None) -> str:
        args_json = json.dumps(arguments or {}, sort_keys=True)
        return hashlib.sha256(args_json.encode()).hexdigest()

    @classmethod
    def create_approval_request(
        cls,
        tenant_id: str,
        project_id: str,
        tool_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        user_context: dict[str, Any] | None = None,
        caller_type: str = "assistant",
        caller_id: str | None = None,
        ttl_seconds: int = 900,
        operation: str | None = None,
        tool_version: str | None = None,
    ) -> PendingApprovalRequest:
        req_id = f"appr-{uuid.uuid4().hex[:12]}"
        args_hash = cls.hash_arguments(arguments)
        now_dt = datetime.now(UTC)
        exp_dt = now_dt + timedelta(seconds=ttl_seconds)
        now_ts = now_dt.timestamp()
        exp_ts = exp_dt.timestamp()
        user_context = user_context or {}
        user_id = user_context.get("user_id") or user_context.get("id")
        user_role = user_context.get("role") or "viewer"
        scrubbed = cls._scrub_sensitive_dict(arguments or {})

        req = PendingApprovalRequest(
            id=req_id,
            tenant_id=tenant_id,
            project_id=project_id,
            tool_id=tool_id,
            tool_name=tool_name,
            arguments_hash=args_hash,
            requesting_user_id=user_id,
            caller_type=caller_type,
            caller_id=caller_id,
            created_at=now_ts,
            expires_at=exp_ts,
            status="pending",
        )
        cls._pending_approvals[req_id] = req

        # Persist to SQLite
        conn = cls._get_sqlite_conn()
        if conn:
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO tool_approval_requests (
                            id, tenant_id, project_id, user_id, user_role,
                            originating_agent_id, originating_workflow_id,
                            caller_type, tool_id, tool_name, operation, tool_version,
                            arguments_hash, arguments_scrubbed, status, reason,
                            expires_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            req_id,
                            tenant_id,
                            project_id,
                            user_id,
                            user_role,
                            caller_id if caller_type in ("assistant", "subagent", "tool_manager") else None,
                            caller_id if caller_type == "workflow" else None,
                            caller_type,
                            tool_id,
                            tool_name,
                            operation,
                            tool_version,
                            args_hash,
                            json.dumps(scrubbed),
                            "pending",
                            None,
                            exp_dt.isoformat(),
                            now_dt.isoformat(),
                            now_dt.isoformat(),
                        ),
                    )
            except Exception as e:
                logger.warning("Failed to persist approval request '%s' to SQLite: %s", req_id, e)
            finally:
                conn.close()

        return req

    @classmethod
    def get_approval(cls, approval_id: str) -> PendingApprovalRequest | None:
        mem = cls._pending_approvals.get(approval_id)
        if mem:
            return mem

        # Recovery across process restart: read from SQLite
        conn = cls._get_sqlite_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tool_approval_requests WHERE id = ?", (approval_id,))
            row = cur.fetchone()
            if not row:
                return None
            try:
                exp_dt = datetime.fromisoformat(row["expires_at"])
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=UTC)
                exp_ts = exp_dt.timestamp()
            except Exception:
                exp_ts = time.time() + 900
            try:
                created_dt = datetime.fromisoformat(row["created_at"])
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=UTC)
                created_ts = created_dt.timestamp()
            except Exception:
                created_ts = time.time()

            req = PendingApprovalRequest(
                id=row["id"],
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                tool_id=row["tool_id"],
                tool_name=row["tool_name"],
                arguments_hash=row["arguments_hash"],
                requesting_user_id=row["user_id"],
                caller_type=row["caller_type"],
                caller_id=row["originating_agent_id"] or row["originating_workflow_id"],
                created_at=created_ts,
                expires_at=exp_ts,
                status=row["status"],
                decided_by=row["decided_by"],
            )
            cls._pending_approvals[approval_id] = req
            return req
        except Exception as e:
            logger.warning("Failed to read approval request '%s' from SQLite: %s", approval_id, e)
            return None
        finally:
            conn.close()

    @classmethod
    def decide_approval_request(
        cls,
        approval_id: str,
        decision: str,  # "approve" | "reject" | "cancel"
        deciding_user: dict[str, Any],
        decision_notes: str | None = None,
    ) -> tuple[bool, str]:
        req = cls.get_approval(approval_id)
        if not req:
            return False, f"Approval request '{approval_id}' not found."
        if req.status != "pending":
            return False, f"Approval request '{approval_id}' is already {req.status}."
        now_dt = datetime.now(UTC)
        if now_dt.timestamp() > req.expires_at:
            req.status = "expired"
            conn = cls._get_sqlite_conn()
            if conn:
                try:
                    with conn:
                        conn.execute(
                            "UPDATE tool_approval_requests SET status = 'expired', updated_at = ? WHERE id = ?",
                            (now_dt.isoformat(), approval_id),
                        )
                finally:
                    conn.close()
            return False, f"Approval request '{approval_id}' has expired."

        role = deciding_user.get("role", "")
        if role not in ("editor", "admin", "owner"):
            return False, f"User with role '{role}' is not authorized to decide approval requests."

        decided_by = deciding_user.get("user_id") or deciding_user.get("id") or deciding_user.get("email")
        req.decided_by = decided_by
        new_status = "approved" if decision == "approve" else ("cancelled" if decision == "cancel" else "rejected")
        req.status = new_status

        conn = cls._get_sqlite_conn()
        if conn:
            try:
                now_iso = now_dt.isoformat()
                with conn:
                    conn.execute(
                        """
                        UPDATE tool_approval_requests
                        SET status = ?, decided_by = ?, decided_at = ?, decision_notes = ?, updated_at = ?
                        WHERE id = ? AND status = 'pending'
                        """,
                        (new_status, decided_by, now_iso, decision_notes, now_iso, approval_id),
                    )
            except Exception as e:
                logger.warning("Failed to update approval decision for '%s' in SQLite: %s", approval_id, e)
            finally:
                conn.close()

        msg = "Approval granted." if decision == "approve" else f"Approval {decision}ed."
        return True, msg

    @classmethod
    def consume_approval(cls, approval_id: str) -> bool:
        """Mark an approved request as consumed upon execution."""
        req = cls.get_approval(approval_id)
        if not req:
            return False
        req.status = "consumed"
        conn = cls._get_sqlite_conn()
        if conn:
            try:
                now_iso = datetime.now(UTC).isoformat()
                with conn:
                    conn.execute(
                        "UPDATE tool_approval_requests SET status = 'consumed', updated_at = ? WHERE id = ?",
                        (now_iso, approval_id),
                    )
            except Exception as e:
                logger.warning("Failed to mark approval '%s' consumed in SQLite: %s", approval_id, e)
            finally:
                conn.close()
        return True

    @classmethod
    async def evaluate_execution(
        cls,
        tenant_id: str,
        project_id: str,
        tool_id: str,
        caller_type: str,  # "master_agent" | "subagent" | "workflow" | "tool_manager" | "test_endpoint" | "direct"
        caller_id: str | None = None,
        user_context: dict[str, Any] | None = None,
        workflow_def: dict[str, Any] | None = None,
        subagent_config: dict[str, Any] | None = None,
        execution_context: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> PolicyDecision:
        """Evaluate if tool execution is authorized for the given caller and context.

        Core invariant:
        Tool discovery != Tool activation != Tool association != Tool authorization != Tool approval.
        """
        user_context = user_context or {}
        execution_context = execution_context or {}

        # 1. Master Agent Rule: No direct external tool execution
        if caller_type == "master_agent" and caller_id != "tool_manager":
            return PolicyDecision(
                allowed=False,
                reason="Master Agent cannot directly execute external tools; execution must be delegated through Tool Manager.",
                tool_id=tool_id,
            )

        # 2. Intent Router Rule: No direct execution
        if caller_type == "intent_router":
            return PolicyDecision(
                allowed=False,
                reason="Intent Router cannot execute tools directly; it only classifies and routes.",
                tool_id=tool_id,
            )

        # 3. Retrieve and verify Tool Record
        async def _check(s: AsyncSession) -> PolicyDecision:
            tool_row = (
                await s.execute(
                    select(Tool).where(
                        Tool.tenant_id == tenant_id,
                        Tool.project_id == project_id,
                        Tool.id == tool_id,
                    )
                )
            ).scalar_one_or_none()

            if tool_row is None:
                # Also check by name if ID did not match
                tool_row = (
                    await s.execute(
                        select(Tool).where(
                            Tool.tenant_id == tenant_id,
                            Tool.project_id == project_id,
                            Tool.name == tool_id,
                        )
                    )
                ).scalar_one_or_none()

            if tool_row is None:
                return PolicyDecision(
                    allowed=False,
                    reason=f"Tool '{tool_id}' is not registered in this project.",
                    tool_id=tool_id,
                )

            # 4. Activation Check
            if not tool_row.enabled:
                return PolicyDecision(
                    allowed=False,
                    reason=f"Tool '{tool_row.name}' ({tool_row.id}) is disabled/inactive.",
                    tool_id=tool_row.id,
                    tool_name=tool_row.name,
                )

            cfg = dict(tool_row.config or {})
            from alberto.services.tool_manager import ToolManagerService

            effect, risk, _ = ToolManagerService.classify_effect_and_risk(
                name=tool_row.name,
                description=cfg.get("description", ""),
                input_schema=cfg.get("input_schema") or cfg.get("parameters"),
                cfg=cfg,
            )

            # 5. Caller Association Enforcement (Default-Deny)
            if caller_type == "subagent":
                # Must be explicitly associated via tools or toolsets
                granted_tool_ids: set[str] = set()

                if subagent_config:
                    granted_tool_ids.update(subagent_config.get("tools") or [])
                    # Resolve toolsets if present
                    toolsets = subagent_config.get("toolsets") or []
                    if toolsets:
                        from alberto.services.tool_sets import ToolSetService

                        members_map = await ToolSetService.members_map(s, tenant_id, project_id)
                        for sid in toolsets:
                            granted_tool_ids.update(members_map.get(sid, []))

                elif caller_id:
                    # Look up agent config from DB
                    agent_row = (
                        await s.execute(
                            select(Agent).where(
                                Agent.tenant_id == tenant_id,
                                Agent.project_id == project_id,
                                Agent.id == caller_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if agent_row and agent_row.config:
                        granted_tool_ids.update(agent_row.config.get("tools") or [])
                        toolsets = agent_row.config.get("toolsets") or []
                        if toolsets:
                            from alberto.services.tool_sets import ToolSetService

                            members_map = await ToolSetService.members_map(s, tenant_id, project_id)
                            for sid in toolsets:
                                granted_tool_ids.update(members_map.get(sid, []))

                if tool_row.id not in granted_tool_ids and tool_row.name not in granted_tool_ids:
                    return PolicyDecision(
                        allowed=False,
                        reason=f"Tool '{tool_row.name}' is not explicitly associated with subagent '{caller_id or 'unknown'}'.",
                        tool_id=tool_row.id,
                        tool_name=tool_row.name,
                        effect=effect,
                        risk=risk,
                    )

            elif caller_type == "workflow":
                # Must be explicitly referenced in workflow definition
                explicit_tools: set[str] = set()
                if workflow_def:
                    nodes = workflow_def.get("nodes") or []
                    for n in nodes:
                        if n.get("type") == "tool_call":
                            tid = (n.get("config") or {}).get("tool_id")
                            if tid:
                                explicit_tools.add(tid)
                elif caller_id:
                    wf_row = (
                        await s.execute(
                            select(Workflow).where(
                                Workflow.tenant_id == tenant_id,
                                Workflow.project_id == project_id,
                                Workflow.id == caller_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if wf_row and wf_row.executable:
                        for n in (wf_row.executable.get("nodes") or []):
                            if n.get("type") == "tool_call":
                                tid = (n.get("config") or {}).get("tool_id")
                                if tid:
                                    explicit_tools.add(tid)

                if tool_row.id not in explicit_tools and tool_row.name not in explicit_tools:
                    return PolicyDecision(
                        allowed=False,
                        reason=f"Tool '{tool_row.name}' is not explicitly defined in workflow '{caller_id or 'unknown'}'.",
                        tool_id=tool_row.id,
                        tool_name=tool_row.name,
                        effect=effect,
                        risk=risk,
                    )

            elif caller_type == "direct":
                return PolicyDecision(
                    allowed=False,
                    reason="Unauthenticated direct tool execution is prohibited under default-deny policy.",
                    tool_id=tool_row.id,
                    tool_name=tool_row.name,
                )

            # 6. Entitlements Verification (End-User Authorization)
            required_entitlements = cfg.get("required_entitlements") or []
            if required_entitlements:
                user_roles_and_entitlements = set(user_context.get("entitlements") or []) | set(
                    user_context.get("roles") or []
                )
                if not all(r in user_roles_and_entitlements for r in required_entitlements):
                    return PolicyDecision(
                        allowed=False,
                        reason=f"User lacks required entitlements: {', '.join(required_entitlements)}.",
                        tool_id=tool_row.id,
                        tool_name=tool_row.name,
                        effect=effect,
                        risk=risk,
                    )

            # 7. HITL / Runtime Approval Check
            needs_approval = bool(
                cfg.get("requires_approval")
                or effect == "delete"
                or risk == "critical"
            )

            is_approved = bool(execution_context.get("approved") or execution_context.get("approval_granted"))
            approval_id = execution_context.get("approval_id")

            if approval_id:
                now_dt = datetime.now(UTC)
                now_iso = now_dt.isoformat()
                consumed_in_db = False
                appr_status_from_db = None
                appr_row_data = None
                args_hash = execution_context.get("arguments_hash")
                if not args_hash and "arguments" in execution_context:
                    args_hash = cls.hash_arguments(execution_context.get("arguments"))

                conn = cls._get_sqlite_conn()
                if conn:
                    try:
                        with conn:
                            cur = conn.cursor()
                            # Atomic SQLite update: transitions approved -> consumed ONLY IF all invariants match
                            # Ensures tampered arguments, wrong tools, or wrong tenants do NOT consume the approval
                            cur.execute(
                                """
                                UPDATE tool_approval_requests
                                SET status = 'consumed', consumed_at = ?, updated_at = ?
                                WHERE id = ?
                                  AND status = 'approved'
                                  AND expires_at > ?
                                  AND tenant_id = ?
                                  AND project_id = ?
                                  AND tool_id IN (?, ?)
                                  AND (arguments_hash = ? OR ? IS NULL)
                                """,
                                (
                                    now_iso,
                                    now_iso,
                                    approval_id,
                                    now_iso,
                                    tenant_id,
                                    project_id,
                                    tool_row.id,
                                    tool_row.name,
                                    args_hash,
                                    args_hash,
                                ),
                            )
                            if cur.rowcount == 1:
                                consumed_in_db = True

                            cur.execute("SELECT * FROM tool_approval_requests WHERE id = ?", (approval_id,))
                            row = cur.fetchone()
                            if row:
                                appr_row_data = dict(row)
                                appr_status_from_db = row["status"]
                    except Exception as e:
                        logger.warning("Atomic SQLite approval consumption check error: %s", e)
                    finally:
                        conn.close()

                if consumed_in_db and appr_row_data:
                    if approval_id in cls._pending_approvals:
                        cls._pending_approvals[approval_id].status = "consumed"
                    is_approved = True

                else:
                    # Could not atomically consume: inspect reason
                    if appr_row_data is not None:
                        # 1. Tampered arguments check
                        if args_hash and appr_row_data["arguments_hash"] != args_hash:
                            return PolicyDecision(
                                allowed=False,
                                reason="Approval arguments hash mismatch: approved arguments differ from execution arguments.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        # 2. Tool mismatch
                        if appr_row_data["tool_id"] not in (tool_row.id, tool_row.name):
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval was granted for tool '{appr_row_data['tool_id']}', not '{tool_row.id}'.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        # 3. Tenant or project scope mismatch
                        if appr_row_data["tenant_id"] != tenant_id or appr_row_data["project_id"] != project_id:
                            return PolicyDecision(
                                allowed=False,
                                reason="Approval tenant or project scope mismatch.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        # 4. Status checks
                        if appr_status_from_db == "consumed":
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval request '{approval_id}' has already been consumed.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        if appr_status_from_db == "rejected":
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval request '{approval_id}' was rejected.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        if appr_status_from_db == "pending":
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval request '{approval_id}' is still pending human approval.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        if appr_status_from_db == "cancelled":
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval request '{approval_id}' was cancelled.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        # 5. Expiry check
                        try:
                            exp_dt = datetime.fromisoformat(appr_row_data["expires_at"])
                            if exp_dt.tzinfo is None:
                                exp_dt = exp_dt.replace(tzinfo=UTC)
                            if now_dt.timestamp() > exp_dt.timestamp():
                                return PolicyDecision(
                                    allowed=False,
                                    reason=f"Approval request '{approval_id}' has expired.",
                                    tool_id=tool_row.id,
                                    tool_name=tool_row.name,
                                    requires_approval=True,
                                    effect=effect,
                                    risk=risk,
                                )
                        except Exception:
                            pass

                        return PolicyDecision(
                            allowed=False,
                            reason=f"Approval request '{approval_id}' cannot be consumed (status: {appr_status_from_db}).",
                            tool_id=tool_row.id,
                            tool_name=tool_row.name,
                            requires_approval=True,
                            effect=effect,
                            risk=risk,
                        )
                    else:
                        # Fallback to in-memory if row not in DB
                        appr = cls.get_approval(approval_id)
                        if not appr:
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval request '{approval_id}' not found.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        if appr.status == "rejected":
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval request '{approval_id}' was rejected.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        if appr.status == "consumed":
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval request '{approval_id}' has already been consumed.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        if now_dt.timestamp() > appr.expires_at:
                            appr.status = "expired"
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval request '{approval_id}' has expired.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        if appr.status != "approved":
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval request '{approval_id}' is still {appr.status}.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        if appr.tool_id not in (tool_row.id, tool_row.name):
                            return PolicyDecision(
                                allowed=False,
                                reason=f"Approval was granted for tool '{appr.tool_id}', not '{tool_row.id}'.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        if args_hash and appr.arguments_hash != args_hash:
                            return PolicyDecision(
                                allowed=False,
                                reason="Approval arguments hash mismatch: approved arguments differ from execution arguments.",
                                tool_id=tool_row.id,
                                tool_name=tool_row.name,
                                requires_approval=True,
                                effect=effect,
                                risk=risk,
                            )
                        is_approved = True
                        appr.status = "consumed"

            if needs_approval and not is_approved:
                appr_req = cls.create_approval_request(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    tool_id=tool_row.id,
                    tool_name=tool_row.name,
                    arguments=execution_context.get("arguments"),
                    user_context=user_context,
                    caller_type=caller_type,
                    caller_id=caller_id,
                )
                return PolicyDecision(
                    allowed=False,
                    reason=f"Tool '{tool_row.name}' requires Human-in-the-Loop approval before execution.",
                    tool_id=tool_row.id,
                    tool_name=tool_row.name,
                    requires_approval=True,
                    approval_request_id=appr_req.id,
                    effect=effect,
                    risk=risk,
                )

            return PolicyDecision(
                allowed=True,
                reason="Policy authorization verified successfully.",
                tool_id=tool_row.id,
                tool_name=tool_row.name,
                requires_approval=needs_approval,
                effect=effect,
                risk=risk,
            )

        if session is not None:
            return await _check(session)
        async with SessionLocal() as s:
            return await _check(s)

    @classmethod
    def check_sync(
        cls,
        ctx: Any,
        tool_id: str,
        caller_type: str,
        caller_id: str | None = None,
        subagent_config: dict[str, Any] | None = None,
        workflow_def: dict[str, Any] | None = None,
    ) -> bool:
        """Synchronous fast-path check against materialized CompileContext."""
        # 1. Master Agent cannot execute tools directly
        if caller_type == "master_agent":
            return False

        # 2. Tool must exist in materialized registry (which only loads enabled tools)
        tool = getattr(ctx, "tool_registry", {}).get(tool_id)
        if tool is None:
            return False

        # 3. Subagent must have explicit association
        if caller_type == "subagent":
            if not subagent_config:
                return False
            explicit_ids = getattr(ctx, "resolve_tool_ids", lambda a, b: [])(
                subagent_config.get("tools"), subagent_config.get("toolsets")
            )
            if tool_id not in explicit_ids:
                return False

        # 4. Workflow must have explicit tool_call node
        if caller_type == "workflow" and workflow_def:
            nodes = workflow_def.get("nodes") or []
            explicit = {
                (n.get("config") or {}).get("tool_id")
                for n in nodes
                if n.get("type") == "tool_call"
            }
            if tool_id not in explicit:
                return False

        # 5. Check entitlements on ctx if available
        spec = getattr(ctx, "tool_specs", {}).get(tool_id) or {}
        cfg = spec.get("config") or {}
        req = cfg.get("required_entitlements") or []
        if req and hasattr(ctx, "has_entitlements") and not ctx.has_entitlements(req):
            return False

        return True
