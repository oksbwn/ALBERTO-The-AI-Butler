"""Regression tests for Chat Context, Memory Learning, Knowledge Recall & Token Metrics fixes."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from alberto.db import SessionLocal
from alberto.models.entities import Project
from alberto.schemas.dto import TurnOut
from alberto.services.assistant import AssistantService
from alberto.services.conversations import ConversationService
from alberto.services.learning_coordinator import LearningCoordinator
from alberto.services.projects import ProjectService
from alberto.services.unified_memory import UnifiedMemoryManager
from alberto.tracing.tracer import AlbertoTracer, SpanRecord


@pytest.fixture
async def sample_project():
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id="tenant-chat-test",
            name="Chat Test Project",
            slug=f"chat-proj-{id(object())}",
        )
        await session.commit()
        await session.refresh(proj)
        return proj


@pytest.mark.asyncio
async def test_tracer_token_totals_and_breakdown():
    """Verify AlbertoTracer exposes separated prompt, completion and total tokens."""
    tracer = AlbertoTracer()
    span = SpanRecord(
        id="s1",
        parent_id=None,
        name="llm_call",
        kind="llm",
        start=time.monotonic(),
        end=time.monotonic() + 0.5,
        model="test-model",
        input_tokens=45,
        output_tokens=15,
    )
    tracer.spans["s1"] = span

    in_tok, out_tok, total_tok = tracer.token_totals()
    assert in_tok == 45
    assert out_tok == 15
    assert total_tok == 60
    assert tracer.has_token_counts() is True

    breakdown = tracer.token_breakdown()
    assert breakdown["prompt_tokens"] == 45
    assert breakdown["completion_tokens"] == 15
    assert breakdown["total_tokens"] == 60


@pytest.mark.asyncio
async def test_tracer_missing_tokens_handled_safely():
    """Verify tracer with missing tokens doesn't fabricate measurements."""
    tracer = AlbertoTracer()
    span = SpanRecord(
        id="s2",
        parent_id=None,
        name="tool_call",
        kind="tool",
        start=time.monotonic(),
        end=time.monotonic() + 0.1,
    )
    tracer.spans["s2"] = span

    in_tok, out_tok, total_tok = tracer.token_totals()
    assert in_tok == 0
    assert out_tok == 0
    assert total_tok == 0
    assert tracer.has_token_counts() is False


@pytest.mark.asyncio
async def test_memory_status_reflects_project_level_learning(sample_project: Project):
    """RC-5: Status endpoint reflects effective project configuration rather than global static."""
    async with SessionLocal() as session:
        # Default is False
        status_default = await UnifiedMemoryManager.get_storage_status(
            session, sample_project.tenant_id, sample_project.id
        )
        assert status_default["memory_learning_enabled"] is False

        # Enable at project level
        proj = (await session.execute(select(Project).where(Project.id == sample_project.id))).scalar_one()
        cfg = dict(proj.config or {})
        cfg["memory_learning_enabled"] = True
        proj.config = cfg
        await session.commit()

        status_enabled = await UnifiedMemoryManager.get_storage_status(
            session, sample_project.tenant_id, sample_project.id
        )
        assert status_enabled["memory_learning_enabled"] is True

        # Disable again
        cfg["memory_learning_enabled"] = False
        proj.config = cfg
        await session.commit()

        status_disabled = await UnifiedMemoryManager.get_storage_status(
            session, sample_project.tenant_id, sample_project.id
        )
        assert status_disabled["memory_learning_enabled"] is False


@pytest.mark.asyncio
async def test_persist_trace_stores_metadata_and_schedules_learning(sample_project: Project):
    """RC-3: Test trace persistence saves token_metrics and schedules learning when enabled."""
    thread_id = f"test-thread-meta-{id(object())}"
    tracer = AlbertoTracer()
    span = SpanRecord(
        id="s1",
        parent_id=None,
        name="agent_chat",
        kind="llm",
        start=time.monotonic(),
        end=time.monotonic() + 0.8,
        model="test-model",
        input_tokens=80,
        output_tokens=25,
    )
    tracer.spans["s1"] = span
    tracer._order.append("s1")

    metrics = {
        "prompt_tokens": 80,
        "completion_tokens": 25,
        "total_tokens": 105,
        "ttft_secs": 0.5,
        "decode_duration_secs": 2.0,
        "tokens_per_sec": 12.5,
    }

    with patch.object(LearningCoordinator, "schedule_turn_learning", new=AsyncMock()) as mock_learn:
        await AssistantService._persist_trace(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            thread_id=thread_id,
            tracer=tracer,
            user_message="I use a Mac for local LLM",
            ai_response="Understood, Mac is noted.",
            token_metrics=metrics,
            status="done",
        )

        assert mock_learn.called
        call_kwargs = mock_learn.call_args.kwargs
        assert call_kwargs["tenant_id"] == sample_project.tenant_id
        assert call_kwargs["project_id"] == sample_project.id
        assert call_kwargs["user_message"] == "I use a Mac for local LLM"
        assert call_kwargs["ai_response"] == "Understood, Mac is noted."

    # Verify Trace row in DB and meta retrieval
    async with SessionLocal() as session:
        turns = await ConversationService.turns(session, sample_project.tenant_id, sample_project.id, thread_id)
        assert len(turns) == 1
        turn = turns[0]
        assert turn.thread_id == thread_id
        assert turn.user_message == "I use a Mac for local LLM"
        assert turn.ai_response == "Understood, Mac is noted."
        assert turn.meta.get("token_metrics") == metrics

        turn_out = TurnOut(
            trace_id=turn.id,
            run_id=turn.run_id,
            source=turn.source or "",
            user_message=turn.user_message,
            ai_response=turn.ai_response,
            status=turn.status,
            error=turn.error,
            latency_ms=turn.latency_ms,
            total_tokens=turn.total_tokens,
            total_cost_usd=turn.total_cost_usd,
            started_at=turn.started_at,
            meta=turn.meta or {},
        )
        assert turn_out.meta["token_metrics"]["completion_tokens"] == 25
        assert turn_out.meta["token_metrics"]["tokens_per_sec"] == 12.5


@pytest.mark.asyncio
async def test_failed_turn_does_not_schedule_learning(sample_project: Project):
    """Verify failed turns record trace error but do NOT schedule learning."""
    thread_id = f"test-thread-err-{id(object())}"
    tracer = AlbertoTracer()
    span = SpanRecord(
        id="s2",
        parent_id=None,
        name="agent_chat",
        kind="llm",
        start=time.monotonic(),
        end=time.monotonic() + 0.1,
        error="Connection reset",
    )
    tracer.spans["s2"] = span

    with patch.object(LearningCoordinator, "schedule_turn_learning", new=AsyncMock()) as mock_learn:
        await AssistantService._persist_trace(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            thread_id=thread_id,
            tracer=tracer,
            user_message="Hello",
            ai_response="",
            error="Connection reset",
            status="error",
        )
        assert not mock_learn.called


@pytest.mark.asyncio
async def test_assistant_multi_turn_history_restoration(sample_project: Project):
    """RC-2: Fast streaming receives previous conversation turns from DB given thread_id."""
    thread_id = f"test-thread-hist-{id(object())}"

    # Seed turn 1 in DB
    import uuid as _uuid
    span_id = f"span-{_uuid.uuid4()}"
    tracer1 = AlbertoTracer()
    span1 = SpanRecord(id=span_id, parent_id=None, name="llm", kind="llm", start=time.monotonic(), end=time.monotonic() + 0.1)
    tracer1.spans[span_id] = span1
    tracer1._order.append(span_id)
    await AssistantService._persist_trace(
        tenant_id=sample_project.tenant_id,
        project_id=sample_project.id,
        thread_id=thread_id,
        tracer=tracer1,
        user_message="I use a Mac to host my local LLM.",
        ai_response="Got it, you use a Mac.",
        status="done",
    )

    # Mock model
    captured_messages = []

    class DummyModel:
        def bind_tools(self, tools):
            return self

        async def astream(self, messages, config=None):
            captured_messages.extend(messages)
            from langchain_core.messages import AIMessageChunk
            yield AIMessageChunk(content="You use a Mac.")

    with patch("alberto.services.assistant.resolve_model", return_value=DummyModel()):
        chunks = []
        async for chunk in AssistantService._fast_stream(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            messages=[{"role": "user", "content": "What hardware do I use?"}],
            thread_id=thread_id,
        ):
            chunks.append(chunk)

    assert len(captured_messages) >= 4
    # 0: SystemMessage, 1: Turn 1 User, 2: Turn 1 AI, 3: Current User
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    assert isinstance(captured_messages[0], SystemMessage)
    assert isinstance(captured_messages[1], HumanMessage)
    assert captured_messages[1].content == "I use a Mac to host my local LLM."
    assert isinstance(captured_messages[2], AIMessage)
    assert captured_messages[2].content == "Got it, you use a Mac."
    assert isinstance(captured_messages[3], HumanMessage)
    assert captured_messages[3].content == "What hardware do I use?"


@pytest.mark.asyncio
async def test_assistant_memory_recall_integration(sample_project: Project):
    """RC-4: Fast assistant path invokes unified memory recall and injects relevant context."""
    from alberto.services.unified_memory import UnifiedMemoryRecord

    mock_memory = [
        UnifiedMemoryRecord(
            source="memory",
            record_id="mem-1",
            content="User prefers temperature set to 21C",
            score=0.95,
            provenance="preference",
        )
    ]

    captured_messages = []

    class DummyModel:
        def bind_tools(self, tools):
            return self

        async def astream(self, messages, config=None):
            captured_messages.extend(messages)
            from langchain_core.messages import AIMessageChunk
            yield AIMessageChunk(content="Setting temperature to 21C.")

    with (
        patch("alberto.services.assistant.resolve_model", return_value=DummyModel()),
        patch.object(UnifiedMemoryManager, "recall", new=AsyncMock(return_value=mock_memory)) as mock_recall,
    ):
        chunks = []
        async for chunk in AssistantService._fast_stream(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            messages=[{"role": "user", "content": "Set the temperature"}],
            thread_id=None,
        ):
            chunks.append(chunk)

        assert mock_recall.called
        assert len(captured_messages) >= 2
        sys_msg = captured_messages[0].content
        assert "[RECALLED MEMORY & KNOWLEDGE CONTEXT]" in sys_msg
        assert "User prefers temperature set to 21C" in sys_msg

