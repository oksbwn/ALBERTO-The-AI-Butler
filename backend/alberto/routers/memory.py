"""Unified Memory endpoints coordinating SQLite, LadybugDB, ChromaDB, and Markdown."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.deps import CurrentUser, current_tenant_id, get_session, require_role
from alberto.schemas.dto import (
    MemoryRecallIn,
    MemoryRecallOut,
    MemoryRecordOut,
    MemoryRememberIn,
    MemoryStatusOut,
)
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
