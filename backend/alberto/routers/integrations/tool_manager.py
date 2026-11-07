"""Tool Manager API endpoints.

Provides:
- Tool capability, effect, and risk analysis
- Intent-based tool suggestion for agent reasoning
- Execution failure diagnostics
- Managed tool activation controls
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.deps import CurrentUser, current_tenant_id, get_session, require_role
from alberto.models import Tool
from alberto.schemas.tool_manager import (
    ToolAnalysisResult,
    ToolDiagnosticReport,
    ToolMatchSuggestion,
)
from alberto.services.tool_manager import ToolManagerService

router = APIRouter(prefix="/v1/projects/{project_id}/tool-manager", tags=["tool-manager"])
integration_router = APIRouter(prefix="/v1/projects/{project_id}/integration-manager", tags=["integration-manager"])


class AnalyzeToolIn(BaseModel):
    tool_id: str | None = None
    name: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    use_llm: bool = False


class SuggestToolsIn(BaseModel):
    intent: str
    top_k: int = Field(default=5, ge=1, le=20)


class DiagnoseToolIn(BaseModel):
    tool_id: str
    recent_errors: list[str] = Field(default_factory=list)


class ActivationIn(BaseModel):
    enabled: bool
    requires_approval: bool | None = None


class ApprovalDecisionIn(BaseModel):
    decision: str = Field(description="approve | reject | cancel")
    notes: str | None = None


@router.post("/analyze", response_model=ToolAnalysisResult)
@integration_router.post("/analyze", response_model=ToolAnalysisResult)
async def analyze_tool(
    project_id: str,
    body: AnalyzeToolIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Analyze a registered or candidate tool for capability, effect, and risk classification."""
    tool_row: Tool | None = None
    name = body.name or ""
    description = body.description or ""
    input_schema = body.input_schema or {}
    cfg: dict[str, Any] = {}

    if body.tool_id:
        tool_row = (
            await session.execute(
                select(Tool).where(
                    Tool.tenant_id == tenant_id,
                    Tool.project_id == project_id,
                    Tool.id == body.tool_id,
                )
            )
        ).scalar_one_or_none()
        if tool_row:
            name = name or tool_row.name
            cfg = tool_row.config or {}
            description = description or cfg.get("description", "")
            input_schema = input_schema or cfg.get("input_schema") or cfg.get("parameters") or {}

    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tool name or valid tool_id is required for analysis.")

    # Fetch existing tools for duplicate detection
    existing_tools_rows = (
        await session.execute(
            select(Tool).where(Tool.tenant_id == tenant_id, Tool.project_id == project_id)
        )
    ).scalars().all()
    existing_tools = [{"id": t.id, "name": t.name, "config": t.config} for t in existing_tools_rows]

    return await ToolManagerService.analyze_tool(
        tool_id=body.tool_id or f"temp:{name}",
        name=name,
        description=description,
        input_schema=input_schema,
        existing_tools=existing_tools,
        cfg=cfg,
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        use_llm=body.use_llm,
    )


@router.post("/suggest", response_model=list[ToolMatchSuggestion])
@integration_router.post("/suggest", response_model=list[ToolMatchSuggestion])
async def suggest_tools(
    project_id: str,
    body: SuggestToolsIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Suggest registered tools suitable for a user intent."""
    tools_rows = (
        await session.execute(
            select(Tool).where(
                Tool.tenant_id == tenant_id,
                Tool.project_id == project_id,
                Tool.enabled.is_(True),
            )
        )
    ).scalars().all()

    tool_dicts = [
        {
            "id": t.id,
            "name": t.name,
            "description": (t.config or {}).get("description", ""),
            "config": t.config or {},
        }
        for t in tools_rows
    ]

    return ToolManagerService.suggest_tools_for_intent(
        intent=body.intent,
        tools=tool_dicts,
        top_k=body.top_k,
    )


@router.post("/diagnose", response_model=ToolDiagnosticReport)
@integration_router.post("/diagnose", response_model=ToolDiagnosticReport)
async def diagnose_tool(
    project_id: str,
    body: DiagnoseToolIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Diagnose execution errors or status degradation for a tool."""
    tool_row = (
        await session.execute(
            select(Tool).where(
                Tool.tenant_id == tenant_id,
                Tool.project_id == project_id,
                Tool.id == body.tool_id,
            )
        )
    ).scalar_one_or_none()
    if tool_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tool {body.tool_id} not found")

    return ToolManagerService.diagnose_execution_failures(
        tool_id=tool_row.id,
        tool_name=tool_row.name,
        recent_errors=body.recent_errors,
        last_tested_status=tool_row.last_tested,
    )


@router.patch("/tools/{tool_id}/activation")
@integration_router.patch("/tools/{tool_id}/activation")
async def update_tool_activation(
    project_id: str,
    tool_id: str,
    body: ActivationIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("editor")),
):
    """Update activation state of a tool, enforcing policy boundaries."""
    tool_row = (
        await session.execute(
            select(Tool).where(
                Tool.tenant_id == tenant_id,
                Tool.project_id == project_id,
                Tool.id == tool_id,
            )
        )
    ).scalar_one_or_none()
    if tool_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Tool {tool_id} not found")

    cfg = dict(tool_row.config or {})
    effect, risk, rec_act = ToolManagerService.classify_effect_and_risk(
        name=tool_row.name,
        description=cfg.get("description", ""),
        cfg=cfg,
    )

    # If activating a destructive or restricted tool, require explicit approval flag
    if body.enabled and (effect == "delete" or risk == "critical"):
        if body.requires_approval is False:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Critical or destructive tools cannot disable requires_approval.",
            )

    tool_row.enabled = body.enabled
    if body.requires_approval is not None:
        cfg["requires_approval"] = body.requires_approval
        tool_row.config = cfg

    await session.commit()
    await session.refresh(tool_row)
    return {
        "id": tool_row.id,
        "name": tool_row.name,
        "enabled": tool_row.enabled,
        "effect": effect,
        "risk": risk,
        "requires_approval": cfg.get("requires_approval", False),
    }


@router.post("/diagnose-channel/{channel_id}")
@integration_router.post("/diagnose-channel/{channel_id}")
async def diagnose_channel_endpoint(
    project_id: str,
    channel_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Integration Manager diagnostic report for a channel (connectivity, webhook, pairing)."""
    from alberto.models import Channel

    ch = await session.get(Channel, channel_id)
    if ch is None or ch.tenant_id != tenant_id or ch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Channel {channel_id} not found")
    return await ToolManagerService.diagnose_channel(session, ch)


@router.get("/approvals/{approval_id}")
@integration_router.get("/approvals/{approval_id}")
async def get_approval_request(
    project_id: str,
    approval_id: str,
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Retrieve an approval request state."""
    from alberto.services.tool_policy import ToolPolicyService

    appr = ToolPolicyService.get_approval(approval_id)
    if not appr or appr.tenant_id != tenant_id or appr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Approval request {approval_id} not found")
    return {
        "id": appr.id,
        "tool_id": appr.tool_id,
        "tool_name": appr.tool_name,
        "status": appr.status,
        "created_at": appr.created_at,
        "expires_at": appr.expires_at,
        "caller_type": appr.caller_type,
        "decided_by": appr.decided_by,
    }


@router.post("/approvals/{approval_id}/decide")
@integration_router.post("/approvals/{approval_id}/decide")
async def decide_approval_request_endpoint(
    project_id: str,
    approval_id: str,
    body: ApprovalDecisionIn,
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Decide a pending tool approval request (approve | reject | cancel)."""
    from alberto.services.tool_policy import ToolPolicyService

    appr = ToolPolicyService.get_approval(approval_id)
    if not appr or appr.tenant_id != tenant_id or appr.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Approval request {approval_id} not found")

    ok, msg = ToolPolicyService.decide_approval_request(
        approval_id=approval_id,
        decision=body.decision,
        deciding_user={"user_id": user.id, "email": user.email, "role": user.role},
        decision_notes=body.notes,
    )
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg)
    return {"ok": True, "message": msg, "approval_id": approval_id, "status": appr.status}
