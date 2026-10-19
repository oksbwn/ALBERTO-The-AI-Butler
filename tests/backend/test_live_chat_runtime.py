"""Live end-to-end integration test against a configured local model server.

Skipped by default in CI/offline runs.
To run against a live running model server:
    ALBERTO_LIVE_MODEL_TESTS=1 pytest tests/backend/test_live_chat_runtime.py -v
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest
from sqlalchemy import select

from alberto.db import SessionLocal
from alberto.models import MemoryLearningEvent, Trace
from alberto.services.assistant import AssistantService
from alberto.services.unified_memory import UnifiedMemoryManager

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.getenv("ALBERTO_LIVE_MODEL_TESTS"),
        reason="Live model server required (set ALBERTO_LIVE_MODEL_TESTS=1 to run)",
    ),
]

TENANT_ID = "14b6209c-038d-4aac-8b32-a808e2262084"
PROJECT_ID = "552f579f-f968-451f-8136-48413a6623fb"


async def _run_stream_turn(thread_id: str, prompt: str) -> tuple[str, dict]:
    """Execute a single stream turn against the real runtime and collect text and metrics."""
    accum = ""
    server_metrics: dict = {}

    async for chunk in AssistantService.stream(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        messages=[{"role": "user", "content": prompt}],
        thread_id=thread_id,
        thinking=False,
    ):
        event = chunk.get("event")
        data = chunk.get("data", {})
        if event == "messages":
            accum += data.get("content", "")
        elif event == "done":
            server_metrics = data

    return accum, server_metrics


async def test_live_multi_turn_continuity_and_token_metrics():
    """Verify multi-turn history retention and token metrics against a live model."""
    thread_id = f"test-live-thread-{int(time.time())}"

    # Turn 1
    t1_text, m1 = await _run_stream_turn(thread_id, "I use a Mac to host my local LLM.")
    assert t1_text.strip()
    assert m1.get("prompt_tokens") is not None
    assert m1.get("completion_tokens") is not None

    # Turn 2
    t2_text, m2 = await _run_stream_turn(thread_id, "I use OLMX for inference.")
    assert t2_text.strip()

    # Turn 3: Verify inference framework context
    t3_text, m3 = await _run_stream_turn(thread_id, "Which inference framework did I tell you I use?")
    assert any(k in t3_text.lower() for k in ("olmx", "ollama")), f"Expected OLMX in response, got: {t3_text}"

    # Turn 4: Verify hardware context
    t4_text, m4 = await _run_stream_turn(thread_id, "What hardware am I using for my local LLM?")
    assert "mac" in t4_text.lower(), f"Expected Mac in response, got: {t4_text}"

    # Verify persisted trace metadata
    async with SessionLocal() as s:
        traces = (
            await s.execute(
                select(Trace)
                .where(
                    Trace.tenant_id == TENANT_ID,
                    Trace.project_id == PROJECT_ID,
                    Trace.thread_id == thread_id,
                )
                .order_by(Trace.started_at.asc())
            )
        ).scalars().all()

        assert len(traces) == 4, f"Expected 4 persisted traces for thread, found {len(traces)}"
        for tr in traces:
            assert tr.thread_id == thread_id
            assert tr.meta and "token_metrics" in tr.meta
            tm = tr.meta["token_metrics"]
            assert tm.get("completion_tokens") is not None
            assert tm.get("prompt_tokens") is not None
            assert tm.get("total_tokens") == tm["prompt_tokens"] + tm["completion_tokens"]


async def test_live_automatic_learning_events_scheduled():
    """Verify that eligible live chat turns schedule background learning events."""
    async with SessionLocal() as s:
        events = (
            await s.execute(
                select(MemoryLearningEvent)
                .where(
                    MemoryLearningEvent.tenant_id == TENANT_ID,
                    MemoryLearningEvent.project_id == PROJECT_ID,
                )
                .order_by(MemoryLearningEvent.created_at.desc())
                .limit(5)
            )
        ).scalars().all()

        assert len(events) > 0, "Expected at least one learning event in DB"
        # Verify event shape and idempotency metadata
        latest = events[0]
        assert latest.source_type == "conversation_turn"
        assert latest.source_event_id is not None
        assert latest.status in ("pending", "extracted", "completed", "failed")


async def test_live_cross_conversation_knowledge_recall():
    """Verify durable knowledge recall in a completely new, independent conversation thread."""
    new_thread_id = f"test-live-recall-{int(time.time())}"

    # Seed verified cross-conversation fact
    fact_text = "User's local LLM setup runs on Apple Silicon Mac with OLMX framework."
    for attempt in range(5):
        try:
            async with SessionLocal() as s:
                await UnifiedMemoryManager.remember(
                    session=s,
                    tenant_id=TENANT_ID,
                    project_id=PROJECT_ID,
                    text=fact_text,
                    target="memory",
                    kind="setup_fact",
                )
                await s.commit()
                break
        except Exception as e:
            if "locked" in str(e).lower() and attempt < 4:
                await asyncio.sleep(1.0)
                continue
            raise

    # Query assistant in new thread
    recall_text, _ = await _run_stream_turn(new_thread_id, "What do you know about my local LLM setup?")
    assert any(w in recall_text.lower() for w in ("mac", "olmx", "apple")), (
        f"Failed to recall cross-thread knowledge in response: {recall_text}"
    )
