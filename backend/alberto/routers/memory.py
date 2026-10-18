"""Unified Memory endpoints coordinating SQLite, LadybugDB, ChromaDB, and Markdown."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.config import settings
from alberto.deps import CurrentUser, current_tenant_id, get_session, require_role
from alberto.models import Agent, Project
from alberto.schemas.dto import (
    MemoryRecallIn,
    MemoryRecallOut,
    MemoryRecordOut,
    MemoryRememberIn,
    MemoryStatusOut,
)
from alberto.schemas.memory_curator import (
    LearningEventOut,
    MarkdownMemoryFileOut,
    MemoryLearningSettingsIn,
    MemoryLearningSettingsOut,
    MemoryRecordDetailOut,
    MemoryRecordUpdateIn,
)
from alberto.services.audit import AuditService
from alberto.services.memory_curator import MemoryCurator
from alberto.services.unified_memory import UnifiedMemoryManager

router = APIRouter(prefix="/v1/projects/{project_id}/memory", tags=["memory"])


@router.get("/status", response_model=MemoryStatusOut)
async def get_memory_status(
    project_id: str,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Get status and stats across all four memory mechanisms."""
    status = await UnifiedMemoryManager.get_storage_status(session, tenant_id, project_id)
    return MemoryStatusOut(**status)


@router.post("/recall", response_model=MemoryRecallOut)
async def recall_memory(
    project_id: str,
    body: MemoryRecallIn,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Retrieve memories across configured storage sources."""
    results = await UnifiedMemoryManager.recall(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        query=body.query,
        sources=body.sources,
        scope=body.scope,
        top_k=body.top_k,
    )
    records = [
        MemoryRecordOut(
            source=r.source,
            record_id=r.record_id,
            content=r.content,
            score=r.score,
            metadata=r.metadata,
            provenance=r.provenance,
        )
        for r in results
    ]
    return MemoryRecallOut(query=body.query, results=records)


@router.post("/remember")
async def remember_memory(
    project_id: str,
    body: MemoryRememberIn,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_role("editor")),
) -> dict[str, Any]:
    """Store an explicit memory record deterministically in the requested store."""
    try:
        res = await UnifiedMemoryManager.remember(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            text=body.text,
            target=body.target,
            scope=body.scope,
            kind=body.kind,
            entity_kind=body.entity_kind,
            entity_name=body.entity_name,
        )
        return {"status": "stored", "details": res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# --- Milestone 2.1: Authoritative Memory Records Inspection & Correction ---

@router.get("/records", response_model=list[MemoryRecordDetailOut])
async def list_memory_records(
    project_id: str,
    status: str | None = "active",
    kind: str | None = None,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """List authoritative memories with filtering."""
    mems = await UnifiedMemoryManager.list_memories(
        session, tenant_id, project_id, status=status, kind=kind
    )
    return [
        MemoryRecordDetailOut(
            id=m.id,
            tenant_id=m.tenant_id,
            project_id=m.project_id,
            scope=m.scope,
            text=m.text,
            kind=m.kind,
            confidence=m.confidence,
            provenance=m.provenance,
            status=m.status,
            source_ref=m.source_ref,
            superseded_by=m.superseded_by,
            metadata=m.meta or {},
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in mems
    ]


@router.get("/records/{record_id}", response_model=MemoryRecordDetailOut)
async def get_memory_record(
    project_id: str,
    record_id: str,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Get single authoritative memory record."""
    m = await UnifiedMemoryManager.get_memory(session, tenant_id, project_id, record_id)
    if not m:
        raise HTTPException(status_code=404, detail="Memory record not found")
    return MemoryRecordDetailOut(
        id=m.id,
        tenant_id=m.tenant_id,
        project_id=m.project_id,
        scope=m.scope,
        text=m.text,
        kind=m.kind,
        confidence=m.confidence,
        provenance=m.provenance,
        status=m.status,
        source_ref=m.source_ref,
        superseded_by=m.superseded_by,
        metadata=m.meta or {},
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


@router.patch("/records/{record_id}", response_model=MemoryRecordDetailOut)
async def update_memory_record(
    project_id: str,
    record_id: str,
    body: MemoryRecordUpdateIn,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Correct or update an authoritative memory record."""
    m = await UnifiedMemoryManager.update_memory(
        session,
        tenant_id,
        project_id,
        record_id,
        text=body.text,
        kind=body.kind,
        status=body.status,
    )
    if not m:
        raise HTTPException(status_code=404, detail="Memory record not found")

    await AuditService.log(
        tenant_id=tenant_id,
        project_id=project_id,
        action="memory.correct",
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        resource_type="memory",
        resource_id=record_id,
        meta={"new_text": body.text, "new_kind": body.kind, "new_status": body.status},
    )
    return MemoryRecordDetailOut(
        id=m.id,
        tenant_id=m.tenant_id,
        project_id=m.project_id,
        scope=m.scope,
        text=m.text,
        kind=m.kind,
        confidence=m.confidence,
        provenance=m.provenance,
        status=m.status,
        source_ref=m.source_ref,
        superseded_by=m.superseded_by,
        metadata=m.meta or {},
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


@router.delete("/records/{record_id}", status_code=204)
async def delete_memory_record(
    project_id: str,
    record_id: str,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Delete an authoritative memory record and remove from projections."""
    deleted = await UnifiedMemoryManager.delete_memory(session, tenant_id, project_id, record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory record not found")

    await AuditService.log(
        tenant_id=tenant_id,
        project_id=project_id,
        action="memory.delete",
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        resource_type="memory",
        resource_id=record_id,
    )


# --- Milestone 2.1: Memory Learning Settings & Controls ---

@router.get("/learning/settings", response_model=MemoryLearningSettingsOut)
async def get_learning_settings(
    project_id: str,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Get conversation learning configuration, status, and effective models."""
    proj = (
        await session.execute(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.id == project_id,
            )
        )
    ).scalar_one_or_none()

    if proj and proj.config and "memory_learning_enabled" in proj.config:
        learning_enabled = bool(proj.config["memory_learning_enabled"])
    else:
        learning_enabled = getattr(settings, "memory_learning_enabled", False)

    tool_learning_enabled = bool(proj.config.get("tool_execution_learning_enabled", False)) if proj and proj.config else False

    curator = (
        await session.execute(
            select(Agent).where(
                Agent.tenant_id == tenant_id,
                Agent.project_id == project_id,
                Agent.system_key == "memory_curator",
            )
        )
    ).scalar_one_or_none()

    graph_mgr = (
        await session.execute(
            select(Agent).where(
                Agent.tenant_id == tenant_id,
                Agent.project_id == project_id,
                Agent.system_key == "graph_manager",
            )
        )
    ).scalar_one_or_none()

    curator_model = (curator.config.get("model") if curator and curator.config else "") or ""
    graph_model = (graph_mgr.config.get("model") if graph_mgr and graph_mgr.config else "") or ""

    _, eff_curator = await MemoryCurator.get_curator_model(session, tenant_id, project_id)

    operational_state = "active" if learning_enabled or tool_learning_enabled else "disabled"

    return MemoryLearningSettingsOut(
        memory_learning_enabled=learning_enabled,
        tool_execution_learning_enabled=tool_learning_enabled,
        memory_curator_model=curator_model,
        memory_curator_effective_model=curator_model or eff_curator,
        graph_manager_model=graph_model,
        graph_manager_effective_model=graph_model or eff_curator,
        operational_state=operational_state,
    )


@router.patch("/learning/settings", response_model=MemoryLearningSettingsOut)
async def update_learning_settings(
    project_id: str,
    body: MemoryLearningSettingsIn,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Update conversation learning configuration (toggle, model overrides). Persists to Project.config."""
    proj = (
        await session.execute(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.id == project_id,
            )
        )
    ).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    pcfg = dict(proj.config or {})
    modified = False

    if body.memory_learning_enabled is not None:
        pcfg["memory_learning_enabled"] = body.memory_learning_enabled
        modified = True

    if body.tool_execution_learning_enabled is not None:
        pcfg["tool_execution_learning_enabled"] = body.tool_execution_learning_enabled
        modified = True

    if modified:
        proj.config = pcfg
        await session.commit()

    # Model overrides
    if body.memory_curator_model is not None:
        curator = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.project_id == project_id,
                    Agent.system_key == "memory_curator",
                )
            )
        ).scalar_one_or_none()
        if curator:
            cfg = dict(curator.config)
            cfg["model"] = body.memory_curator_model.strip()
            curator.config = cfg
            await session.commit()

    if body.graph_manager_model is not None:
        graph_mgr = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.project_id == project_id,
                    Agent.system_key == "graph_manager",
                )
            )
        ).scalar_one_or_none()
        if graph_mgr:
            cfg = dict(graph_mgr.config)
            cfg["model"] = body.graph_manager_model.strip()
            graph_mgr.config = cfg
            await session.commit()

    learning_enabled = (
        bool(proj.config.get("memory_learning_enabled"))
        if proj.config and "memory_learning_enabled" in proj.config
        else getattr(settings, "memory_learning_enabled", False)
    )

    await AuditService.log(
        tenant_id=tenant_id,
        project_id=project_id,
        action="memory.settings.update",
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        resource_type="memory_settings",
        resource_id=project_id,
        meta={"memory_learning_enabled": learning_enabled},
    )

    return await get_learning_settings(project_id, tenant_id, session, user)


# --- Milestone 2.1: Learning Events & Review Queue ---

@router.get("/learning/events", response_model=list[LearningEventOut])
async def list_learning_events(
    project_id: str,
    status: str | None = None,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """List background learning events and pending review items."""
    events = await UnifiedMemoryManager.get_learning_events(session, tenant_id, project_id, status=status)
    return [
        LearningEventOut(
            id=e.id,
            tenant_id=e.tenant_id,
            project_id=e.project_id,
            source_event_id=e.source_event_id,
            source_type=e.source_type,
            status=e.status,
            extraction_payload=e.extraction_payload or {},
            error=e.error,
            retry_count=e.retry_count,
            requires_review=e.requires_review,
            applied_memory_ids=e.applied_memory_ids or [],
            applied_graph_entity_ids=e.applied_graph_entity_ids or [],
            applied_graph_rel_ids=e.applied_graph_rel_ids or [],
            created_at=e.created_at,
            updated_at=e.updated_at,
        )
        for e in events
    ]


@router.post("/learning/events/{event_id}/approve", response_model=LearningEventOut)
async def approve_learning_event(
    project_id: str,
    event_id: str,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Approve candidate knowledge in a review_required event."""
    ev = await UnifiedMemoryManager.approve_learning_event(session, tenant_id, project_id, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Learning event not found or not in review_required status")

    await AuditService.log(
        tenant_id=tenant_id,
        project_id=project_id,
        action="memory.learning_event.approve",
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        resource_type="memory_learning_event",
        resource_id=event_id,
    )
    return LearningEventOut(
        id=ev.id,
        tenant_id=ev.tenant_id,
        project_id=ev.project_id,
        source_event_id=ev.source_event_id,
        source_type=ev.source_type,
        status=ev.status,
        extraction_payload=ev.extraction_payload or {},
        error=ev.error,
        retry_count=ev.retry_count,
        requires_review=ev.requires_review,
        applied_memory_ids=ev.applied_memory_ids or [],
        applied_graph_entity_ids=ev.applied_graph_entity_ids or [],
        applied_graph_rel_ids=ev.applied_graph_rel_ids or [],
        created_at=ev.created_at,
        updated_at=ev.updated_at,
    )


@router.post("/learning/events/{event_id}/reject", response_model=LearningEventOut)
async def reject_learning_event(
    project_id: str,
    event_id: str,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Reject candidate knowledge in a learning event."""
    ev = await UnifiedMemoryManager.reject_learning_event(session, tenant_id, project_id, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Learning event not found")

    await AuditService.log(
        tenant_id=tenant_id,
        project_id=project_id,
        action="memory.learning_event.reject",
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        resource_type="memory_learning_event",
        resource_id=event_id,
    )
    return LearningEventOut(
        id=ev.id,
        tenant_id=ev.tenant_id,
        project_id=ev.project_id,
        source_event_id=ev.source_event_id,
        source_type=ev.source_type,
        status=ev.status,
        extraction_payload=ev.extraction_payload or {},
        error=ev.error,
        retry_count=ev.retry_count,
        requires_review=ev.requires_review,
        applied_memory_ids=ev.applied_memory_ids or [],
        applied_graph_entity_ids=ev.applied_graph_entity_ids or [],
        applied_graph_rel_ids=ev.applied_graph_rel_ids or [],
        created_at=ev.created_at,
        updated_at=ev.updated_at,
    )


# --- Milestone 2.1: Persistent Markdown Memory Inspection ---

@router.get("/markdown", response_model=list[MarkdownMemoryFileOut])
async def list_markdown_memory_files(
    project_id: str,
    filename: str | None = Query(default=None, description="Optional filename to fetch full content"),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """List markdown memory files under /data/memory/<tenant_id>/<project_id>/."""
    files = UnifiedMemoryManager.list_markdown_files(tenant_id, project_id)
    results = []
    for f in files:
        content = None
        if filename and filename == f["filename"]:
            content = UnifiedMemoryManager.get_markdown_file(tenant_id, project_id, filename)
        results.append(
            MarkdownMemoryFileOut(
                filename=f["filename"],
                category=f["category"],
                size_bytes=f["size_bytes"],
                updated_at=f["updated_at"],
                content=content,
            )
        )
    return results
