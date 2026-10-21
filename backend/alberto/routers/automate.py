"""Automation Manager API endpoints.

Provides:
- Project and user-scoped capability discovery
- Authoring session creation, listing, retrieval
- Natural-language requirement and clarification processing
- Proposed graph validation reports
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.deps import CurrentUser, current_tenant_id, get_session, require_role
from alberto.schemas.automation_manager import (
    ApprovalRequestIn,
    ApprovalResultOut,
    AuthoringMessageIn,
    AuthoringSessionCreateIn,
    AuthoringSessionOut,
    AuthoringStepResult,
    CapabilityDiscoveryResult,
    SafeTestResult,
    WorkflowExecutionDiagnostic,
    WorkflowMonitoringReport,
    WorkflowOptimisationReport,
)
from alberto.services.automation_manager import AutomationManagerService
from alberto.services.validation import validate_workflow

router = APIRouter(prefix="/v1/projects/{project_id}/automate", tags=["automate"])
api_router = APIRouter(prefix="/api/projects/{project_id}/automate", tags=["automate"])


def _to_session_out(s: Any) -> AuthoringSessionOut:
    return AuthoringSessionOut(
        id=s.id,
        tenant_id=s.tenant_id,
        project_id=s.project_id,
        user_id=s.user_id,
        title=s.title,
        requirement=s.requirement,
        status=s.status,
        clarifications=s.clarifications or [],
        current_plan=s.current_plan,
        proposal=s.proposal,
        proposed_agents=s.proposed_agents or [],
        validation_status=s.validation_status,
        validation_errors=s.validation_errors or [],
        revision=s.revision,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@router.get("/capabilities", response_model=CapabilityDiscoveryResult)
@api_router.get("/capabilities", response_model=CapabilityDiscoveryResult)
async def discover_capabilities(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("viewer")),
):
    """Discover permitted platform capabilities within current project/user scope."""
    user_ctx = {
        "user_id": getattr(user, "id", None),
        "tenant_id": tenant_id,
        "role": getattr(user, "role", "viewer"),
    }
    return await AutomationManagerService.discover_capabilities(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        user_context=user_ctx,
    )


@router.post("/sessions", response_model=AuthoringSessionOut, status_code=status.HTTP_201_CREATED)
@api_router.post("/sessions", response_model=AuthoringSessionOut, status_code=status.HTTP_201_CREATED)
async def create_authoring_session(
    project_id: str,
    body: AuthoringSessionCreateIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Start a new persistent conversational authoring session."""
    user_id = getattr(user, "id", None)
    sess = await AutomationManagerService.create_session(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        requirement=body.requirement,
        title=body.title,
    )
    return _to_session_out(sess)


@router.get("/sessions", response_model=list[AuthoringSessionOut])
@api_router.get("/sessions", response_model=list[AuthoringSessionOut])
async def list_authoring_sessions(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("viewer")),
):
    """List all authoring sessions for this project."""
    sessions = await AutomationManagerService.list_sessions(session, tenant_id, project_id)
    return [_to_session_out(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=AuthoringSessionOut)
@api_router.get("/sessions/{session_id}", response_model=AuthoringSessionOut)
async def get_authoring_session(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("viewer")),
):
    """Retrieve an authoring session state by ID."""
    sess = await AutomationManagerService.get_session(session, tenant_id, project_id, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Authoring session not found.")
    return _to_session_out(sess)


@router.post("/sessions/{session_id}/messages", response_model=AuthoringStepResult)
@api_router.post("/sessions/{session_id}/messages", response_model=AuthoringStepResult)
async def send_session_message(
    project_id: str,
    session_id: str,
    body: AuthoringMessageIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Submit a requirement or clarification turn to the authoring session."""
    user_ctx = {
        "user_id": getattr(user, "id", None),
        "tenant_id": tenant_id,
        "role": getattr(user, "role", "editor"),
    }
    result = await AutomationManagerService.process_message(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        session_id=session_id,
        message=body.message,
        expected_revision=body.expected_revision,
        user_context=user_ctx,
    )
    if result.action == "error":
        if "Conflict" in (result.error_message or ""):
            raise HTTPException(status_code=409, detail=result.error_message)
        if "not found" in (result.error_message or ""):
            raise HTTPException(status_code=404, detail=result.error_message)
        raise HTTPException(status_code=400, detail=result.error_message)
    return result


@router.post("/sessions/{session_id}/validate")
@api_router.post("/sessions/{session_id}/validate")
async def validate_session_proposal(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("viewer")),
):
    """Deterministic validation of the current proposed workflow definition."""
    sess = await AutomationManagerService.get_session(session, tenant_id, project_id, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Authoring session not found.")
    proposal = sess.proposal or {}
    executable = proposal.get("executable") or {}
    res = validate_workflow(executable)
    sess.validation_status = "valid" if res.valid else "invalid"
    sess.validation_errors = res.errors
    sess.updated_at = datetime.utcnow()
    await session.commit()
    return {
        "valid": res.valid,
        "errors": res.errors,
        "warnings": res.warnings,
    }


@router.post("/sessions/{session_id}/test", response_model=SafeTestResult)
@api_router.post("/sessions/{session_id}/test", response_model=SafeTestResult)
async def test_session_proposal(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("viewer")),
):
    """Run an isolated safe dry-run test of the proposed workflow without live side effects."""
    try:
        return await AutomationManagerService.run_safe_test(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            session_id=session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/approve", response_model=ApprovalResultOut)
@api_router.post("/sessions/{session_id}/approve", response_model=ApprovalResultOut)
async def approve_session_proposal(
    project_id: str,
    session_id: str,
    body: ApprovalRequestIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Consolidated approval: creates specialist agents, persists workflow and activates triggers."""
    user_ctx = {
        "user_id": getattr(user, "id", None),
        "tenant_id": tenant_id,
        "role": getattr(user, "role", "editor"),
    }
    try:
        return await AutomationManagerService.approve_and_activate(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            session_id=session_id,
            user_context=user_ctx,
            req=body,
        )
    except ValueError as e:
        msg = str(e)
        if "Conflict" in msg:
            raise HTTPException(status_code=409, detail=msg)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)


@router.get("/monitoring", response_model=WorkflowMonitoringReport)
@api_router.get("/monitoring", response_model=WorkflowMonitoringReport)
async def get_monitoring_summary(
    project_id: str,
    workflow_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("viewer")),
):
    """Retrieve grounded execution metrics, run counts, active triggers, and slowest node."""
    return await AutomationManagerService.get_workflow_monitoring_summary(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        workflow_id=workflow_id,
    )


@router.get("/runs/{run_id}/diagnose", response_model=WorkflowExecutionDiagnostic)
@api_router.get("/runs/{run_id}/diagnose", response_model=WorkflowExecutionDiagnostic)
async def diagnose_run_failure(
    project_id: str,
    run_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("viewer")),
):
    """Inspect execution traces, identify root cause, and formulate safe repair recommendations."""
    try:
        return await AutomationManagerService.diagnose_failure(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/workflows/{workflow_id}/optimise", response_model=WorkflowOptimisationReport)
@api_router.get("/workflows/{workflow_id}/optimise", response_model=WorkflowOptimisationReport)
async def get_workflow_optimisation(
    project_id: str,
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("viewer")),
):
    """Analyze workflow execution history and propose grounded optimizations."""
    try:
        return await AutomationManagerService.analyze_workflow_optimisation(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=workflow_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/workflows/{workflow_id}/repair")
@api_router.post("/workflows/{workflow_id}/repair")
async def repair_workflow(
    project_id: str,
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Safely apply non-behavioral configuration self-repairs, rejecting unauthorized privilege expansions."""
    try:
        return await AutomationManagerService.apply_safe_self_repair(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            workflow_id=workflow_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
