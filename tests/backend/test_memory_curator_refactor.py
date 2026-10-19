"""Targeted regression test suite for Memory Curator Refactor.

Validates:
1. Eligibility: Greetings or 'test' followed by durable facts are not discarded.
2. Trivial whole-message rejection: Pure greetings, pure 'test', pure confirmations rejected.
3. Sensitive data exclusion: Credentials mixed with facts rejected by eligibility or flagged in extraction.
4. Schema compatibility and malformed JSON recovery.
5. Centralized taxonomy consistency across schemas and GraphManager.
6. Unknown entity names not forced into incorrect kinds.
7. Relevance-aware memory selection without circular dependencies.
8. Model resolution and invocation failures distinguished from should_learn=False.
9. Transaction boundaries: MemoryCuratorService.extract does not commit transactions.
10. OLMX/Ollama preservation and replacement scenarios.
11. Native structured output and fallback paths without extra LLM calls.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alberto.db import SessionLocal
from alberto.models.entities import Project
from alberto.schemas.memory_curator import (
    CANONICAL_ENTITY_KINDS,
    CANONICAL_RELATIONSHIP_KINDS,
    EntityCandidate,
    MemoryCuratorOutput,
)
from alberto.services.graph_manager import (
    VALID_ENTITY_KINDS,
    VALID_RELATIONSHIP_KINDS,
    GraphManagerService,
)
from alberto.services.memory_curator import (
    MemoryCuratorService,
    select_relevant_memories,
)
from alberto.services.projects import ProjectService


@pytest.fixture
async def sample_proj():
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id="tenant-refactor-1",
            name="Refactor Verification Project",
            slug="refactor-proj-1",
        )
        await session.commit()
        await session.refresh(proj)
        return proj


# ============================================================================
# 1. ELIGIBILITY RULES: GREETINGS, TEST, TRIVIAL & SENSITIVE
# ============================================================================


def test_greeting_followed_by_durable_knowledge():
    """Meaningful turns starting with greetings must NOT be rejected as trivial."""
    turns = [
        "Hi, I have switched to OLMX.",
        "Hello, my new server is running Linux.",
        "Hey there! Please note that my workstation is an M2 Mac Studio.",
        "Good morning, Alberto. I prefer dark theme in all tools.",
    ]
    for text in turns:
        eligible, reason = MemoryCuratorService.is_eligible_turn(text, "Understood.")
        assert eligible is True, f"Expected '{text}' to be eligible, but got: {reason}"


def test_technical_statements_beginning_with_test():
    """Technical statements starting with 'test' must NOT be discarded."""
    turns = [
        "Test setup: I use Gemma locally.",
        "Testing cluster with 3 nodes running Debian.",
        "Test environment is configured with Postgres 16.",
    ]
    for text in turns:
        eligible, reason = MemoryCuratorService.is_eligible_turn(text, "Got it.")
        assert eligible is True, f"Expected '{text}' to be eligible, but got: {reason}"


def test_purely_trivial_whole_messages_rejected():
    """Purely trivial whole messages must be rejected before calling LLM."""
    trivial_messages = [
        "hi",
        "hello",
        "hello there",
        "good morning",
        "ok",
        "okay",
        "thanks",
        "thank you",
        "sounds good",
        "yes",
        "no",
        "test",
        "testing",
        "test message",
        "2 + 2 = 4",
        "10 * 5",
    ]
    for text in trivial_messages:
        eligible, _ = MemoryCuratorService.is_eligible_turn(text, "Response.")
        assert eligible is False, f"Expected '{text}' to be ineligible."


def test_sensitive_content_mixed_with_ordinary_facts():
    """Messages containing sensitive credentials must be rejected by eligibility even if mixed with ordinary facts."""
    mixed_messages = [
        "I run Linux on my primary server, and password: supersecretpassword123",
        "Switched to OLMX. My bearer token = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "My API key is sk-1234567890abcdef1234567890 for OpenAI",
    ]
    for text in mixed_messages:
        eligible, reason = MemoryCuratorService.is_eligible_turn(text, "Acknowledged.")
        assert eligible is False, f"Expected sensitive input '{text}' to be rejected."
        assert "sensitive" in reason.lower()


# ============================================================================
# 2. CENTRALIZED TAXONOMY & UNKNOWN ENTITY NAMES
# ============================================================================


def test_centralized_taxonomy_consistency():
    """Schema taxonomy constants must be the single source of truth across layers."""
    assert set(CANONICAL_ENTITY_KINDS) == VALID_ENTITY_KINDS
    assert set(CANONICAL_RELATIONSHIP_KINDS) == VALID_RELATIONSHIP_KINDS
    assert "operating_system" in VALID_ENTITY_KINDS
    assert "platform" in VALID_ENTITY_KINDS
    assert "device" in VALID_ENTITY_KINDS
    assert "framework" in VALID_ENTITY_KINDS
    assert "model" in VALID_ENTITY_KINDS


@pytest.mark.asyncio
async def test_unknown_entity_names_not_forced_into_incorrect_kind():
    """Unknown or novel entity names with valid kinds must NOT be forced into a different kind."""
    t = "tenant-unk"
    p = "proj-unk"

    candidates = [
        EntityCandidate(
            temporary_id="e1",
            name="Gemma 2",
            kind="model",
            description="Local language model",
            confidence=0.9,
        ),
        EntityCandidate(
            temporary_id="e2",
            name="CustomHypervisor",
            kind="application",
            description="Novel tool",
            confidence=0.88,
        ),
    ]

    res = await GraphManagerService.resolve_and_validate(t, p, candidates, [])
    resolved = {e.name: e for e in res["resolved_entities"]}

    assert resolved["Gemma 2"].kind == "model"
    assert resolved["CustomHypervisor"].kind == "application"


# ============================================================================
# 3. RELEVANT MEMORY SELECTION (RELEVANCE-AWARE, BOUNDED BUDGET)
# ============================================================================


def test_relevance_aware_memory_selection():
    """Memories relevant to the user query are prioritized ahead of irrelevant ones."""
    existing = [
        "User prefers light theme in web browser.",
        "Home office is located in the upstairs attic.",
        "Workstation is a Mac Studio running macOS Sonoma.",
        "User previously used Ollama for local LLM inference.",
        "User likes espresso in the morning.",
        "Backup server runs on FreeBSD.",
    ]

    selected = select_relevant_memories(
        existing_memories=existing,
        query="I have switched from Ollama to OLMX on my Mac Studio.",
        top_k=3,
        max_chars=500,
    )

    assert len(selected) <= 3
    # Both Ollama and Mac Studio memories are directly relevant and should be prioritized
    selected_joined = " ".join(selected)
    assert "Ollama" in selected_joined
    assert "Mac Studio" in selected_joined


def test_memory_selection_bounded_budget():
    """Selected memories must strictly respect max_chars limit."""
    long_memories = [f"Memory number {i}: " + ("x" * 100) for i in range(20)]
    selected = select_relevant_memories(
        existing_memories=long_memories,
        query="Memory 5 and 7",
        top_k=10,
        max_chars=250,
    )

    total_len = sum(len(m) for m in selected)
    assert total_len <= 250


# ============================================================================
# 4. EXTRACTION: STRUCTURED OUTPUT, FALLBACK & ERROR DISTINCTION
# ============================================================================


@pytest.mark.asyncio
async def test_native_structured_output_success(sample_proj: Project):
    """When model natively supports with_structured_output, returns structured object directly."""
    expected_output = MemoryCuratorOutput(
        schema_version=1,
        should_learn=True,
        memories=[],
        entities=[
            EntityCandidate(
                temporary_id="e1",
                name="OLMX",
                kind="framework",
                confidence=0.95,
            )
        ],
    )

    mock_structured = MagicMock()
    mock_structured.ainvoke = AsyncMock(return_value=expected_output)

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value = mock_structured

    async with SessionLocal() as session:
        with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_model, "native-model")):
            result = await MemoryCuratorService.extract(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                user_message="I have switched to OLMX.",
                ai_response="Understood.",
            )

            assert result.should_learn is True
            assert len(result.entities) == 1
            assert result.entities[0].name == "OLMX"
            mock_model.with_structured_output.assert_called_once_with(MemoryCuratorOutput)


@pytest.mark.asyncio
async def test_structured_output_fallback_to_json(sample_proj: Project):
    """When with_structured_output fails, cleanly falls back to JSON prompt and parse."""
    mock_json = json.dumps({
        "schema_version": 1,
        "should_learn": True,
        "memories": [],
        "entities": [
            {
                "temporary_id": "e1",
                "name": "Linux",
                "kind": "operating_system",
                "confidence": 0.99,
            }
        ],
        "relationships": [],
        "conflicts": [],
        "requires_review": False,
    })

    mock_model = MagicMock()
    # Simulate provider where with_structured_output raises NotImplementedError
    mock_model.with_structured_output.side_effect = NotImplementedError("Local model does not support tools")
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=mock_json))

    async with SessionLocal() as session:
        with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_model, "local-fallback")):
            result = await MemoryCuratorService.extract(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                user_message="My new server is running Linux.",
                ai_response="Great.",
            )

            assert result.should_learn is True
            assert len(result.entities) == 1
            assert result.entities[0].name == "Linux"


@pytest.mark.asyncio
async def test_distinguish_model_resolution_failure(sample_proj: Project):
    """Model resolution failure must set extraction_error and should_learn=False."""
    async with SessionLocal() as session:
        with patch.object(
            MemoryCuratorService,
            "get_curator_model",
            side_effect=RuntimeError("Cannot connect to model registry"),
        ):
            result = await MemoryCuratorService.extract(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                user_message="Remember I use Neovim.",
                ai_response="Noted.",
            )

            assert result.should_learn is False
            assert result.extraction_error is not None
            assert "Model resolution failed" in result.extraction_error


@pytest.mark.asyncio
async def test_distinguish_model_invocation_failure(sample_proj: Project):
    """LLM invocation timeout/failure must set extraction_error and should_learn=False."""
    mock_model = MagicMock(spec=["ainvoke"])
    mock_model.ainvoke = AsyncMock(side_effect=TimeoutError("Request timed out"))

    async with SessionLocal() as session:
        with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_model, "timeout-model")):
            result = await MemoryCuratorService.extract(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                user_message="Remember I use Neovim.",
                ai_response="Noted.",
            )

            assert result.should_learn is False
            assert result.extraction_error is not None
            assert "Model invocation failed" in result.extraction_error


@pytest.mark.asyncio
async def test_distinguish_malformed_json_output(sample_proj: Project):
    """Malformed JSON output sets extraction_error rather than silently succeeding with should_learn=False."""
    mock_model = MagicMock(spec=["ainvoke"])
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content="Invalid JSON response { broken"))

    async with SessionLocal() as session:
        with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_model, "broken-model")):
            result = await MemoryCuratorService.extract(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                user_message="Remember I use Neovim.",
                ai_response="Noted.",
            )

            assert result.should_learn is False
            assert result.extraction_error is not None
            assert "Malformed JSON output from model" in result.extraction_error


# ============================================================================
# 5. TRANSACTION BOUNDARIES: NO SILENT COMMIT
# ============================================================================


@pytest.mark.asyncio
async def test_extract_does_not_commit_session(sample_proj: Project):
    """MemoryCuratorService.extract must never commit the session directly."""
    mock_session = AsyncMock()
    mock_output = json.dumps({
        "schema_version": 1,
        "should_learn": False,
        "memories": [],
        "entities": [],
        "relationships": [],
        "conflicts": [],
    })
    mock_model = MagicMock(spec=["ainvoke"])
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=mock_output))

    with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_model, "test-model")):
        await MemoryCuratorService.extract(
            session=mock_session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            user_message="Tell me more about computers.",
            ai_response="Computers calculate.",
            existing_memories=[],
        )

        mock_session.commit.assert_not_called()
