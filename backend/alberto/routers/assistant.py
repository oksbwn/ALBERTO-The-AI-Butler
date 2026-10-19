"""Forge Assistant endpoint - streams the meta-agent's narration + actions over SSE."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from alberto.db import SessionLocal
from alberto.deps import current_tenant_id, get_checkpointer
from alberto.services.assistant import AssistantService
from alberto.services.projects import ProjectService

router = APIRouter(prefix="/v1/projects/{project_id}/assistant", tags=["assistant"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


class AssistantMessage(BaseModel):
    role: str = "user"
    content: str


class AssistantIn(BaseModel):
    # Preferred: one new message + a stable thread_id (the checkpointer holds history,
    # todos, and files for the thread). `messages` remains for back-compat - when
    # thread_id is absent the full transcript is replayed statelessly.
    message: str | None = None
    thread_id: str | None = None
    messages: list[AssistantMessage] = []
    model: str | None = None
    thinking: bool = False
    persona: str | None = None


class AssistantResumeIn(BaseModel):
    thread_id: str
    decision: str = "approve"  # approve | reject
    model: str | None = None
    thinking: bool = False


@router.post("/stream")
async def assistant_stream(
    project_id: str,
    body: AssistantIn,
    tenant_id: str = Depends(current_tenant_id),
    checkpointer=Depends(get_checkpointer),
):
    # Ownership check (audit H4): scoped cleanly before streaming so DB connection does not linger
    async with SessionLocal() as session:
        if await ProjectService.get(session, tenant_id, project_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")

    if body.messages:
        messages = [m.model_dump() for m in body.messages]
        if body.message and (not messages or messages[-1].get("content") != body.message):
            messages.append({"role": "user", "content": body.message})
    elif body.message:
        messages = [{"role": "user", "content": body.message}]
    else:
        messages = []

    async def event_gen():
        async for frame in AssistantService.stream(
            tenant_id=tenant_id, project_id=project_id, messages=messages,
            thread_id=body.thread_id, checkpointer=checkpointer, model=body.model,
            thinking=body.thinking, persona=body.persona,
        ):
            yield {"event": frame["event"], "data": json.dumps(frame["data"], default=str)}

    return EventSourceResponse(event_gen(), headers=SSE_HEADERS)


@router.post("/resume")
async def assistant_resume(
    project_id: str,
    body: AssistantResumeIn,
    tenant_id: str = Depends(current_tenant_id),
    checkpointer=Depends(get_checkpointer),
):
    """Resume a paused assistant thread (HITL approval for destructive tools)."""
    async with SessionLocal() as session:
        if await ProjectService.get(session, tenant_id, project_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")

    async def event_gen():
        async for frame in AssistantService.resume(
            tenant_id=tenant_id, project_id=project_id, thread_id=body.thread_id,
            decision=body.decision, checkpointer=checkpointer, model=body.model,
            thinking=body.thinking,
        ):
            yield {"event": frame["event"], "data": json.dumps(frame["data"], default=str)}

    return EventSourceResponse(event_gen(), headers=SSE_HEADERS)
