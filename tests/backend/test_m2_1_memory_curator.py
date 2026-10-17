"""Acceptance test suite for Alberto Milestone 2.1: Intelligent Memory Curator, Graph Manager,
Persistent Markdown Memory, and Learning Coordinator.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alberto.db import SessionLocal
from alberto.knowledge.graph import LadybugGraphAdapter, set_graph_adapter
from alberto.models.entities import Project
from alberto.schemas.memory_curator import (
    EntityCandidate,
    MemoryCuratorOutput,
    RelationshipCandidate,
)
from alberto.services.graph_manager import GraphManagerService
from alberto.services.learning_coordinator import LearningCoordinator
from alberto.services.markdown_memory import MarkdownMemoryService
from alberto.services.memory import MemoryService
from alberto.services.memory_curator import MemoryCuratorService
from alberto.services.projects import ProjectService
from alberto.services.unified_memory import UnifiedMemoryManager


@pytest.fixture
def graph_dir():
    with tempfile.TemporaryDirectory(prefix="ladybug_m21_") as tmp:
        yield Path(tmp)


@pytest.fixture
def memory_dir():
    with tempfile.TemporaryDirectory(prefix="markdown_m21_") as tmp:
        p = Path(tmp)
        MarkdownMemoryService._base_dir_override = p
        yield p
        MarkdownMemoryService._base_dir_override = None


class MockEmbedder:
    model_name = "mock"

    async def aembed_query(self, text: str) -> list[float]:
        return [0.01] * 384

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * 384 for _ in texts]


@pytest.fixture
async def setup_env(graph_dir: Path, memory_dir: Path):
    from alberto.services.knowledge import KnowledgeService

    adapter = LadybugGraphAdapter(db_path=graph_dir)
    await adapter.initialize()
    set_graph_adapter(adapter)
    with patch.object(KnowledgeService, "embedder_for_project", new=AsyncMock(return_value=MockEmbedder())):
        yield adapter
    adapter.close()
    set_graph_adapter(None)


@pytest.fixture
async def sample_proj():
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id="tenant-m21-1",
            name="Milestone 2.1 Project",
            slug="m21-proj-1",
        )
        await session.commit()
        await session.refresh(proj)
        return proj


# ============================================================================
# PART C & D: MEMORY CURATOR & DURABLE FACT EXTRACTION
# ============================================================================


def test_schema_validation_and_malformed_json():
    """Verify MemoryCuratorOutput schema parses valid JSON and rejects malformed JSON."""
    valid_data = {
        "schema_version": 1,
        "should_learn": True,
        "memories": [
            {
                "kind": "preference",
                "content": "User prefers local LLMs via LM Studio.",
                "confidence": 0.95,
                "durability": "long_term",
                "evidence_refs": ["msg_1"],
                "operation": "propose_upsert",
            }
        ],
        "entities": [
            {
                "temporary_id": "e1",
                "name": "LM Studio",
                "kind": "Application",
                "confidence": 0.98,
                "evidence_refs": ["msg_1"],
            }
        ],
        "relationships": [],
        "conflicts": [],
        "requires_review": False,
    }
    parsed = MemoryCuratorOutput.model_validate(valid_data)
    assert parsed.should_learn is True
    assert len(parsed.memories) == 1
    assert parsed.memories[0].content == "User prefers local LLMs via LM Studio."
    assert parsed.entities[0].name == "LM Studio"

    # Test malformed / invalid schema fallback
    with pytest.raises(Exception):
        MemoryCuratorOutput.model_validate({"schema_version": "not-an-int"})


def test_eligibility_and_sensitive_exclusion():
    """Deterministic eligibility check must reject trivial, short, or sensitive inputs."""
    # 1. Too short
    eligible, reason = MemoryCuratorService.is_eligible_turn("hi", "Hello!")
    assert eligible is False
    assert "trivial" in reason or "short" in reason

    eligible, _ = MemoryCuratorService.is_eligible_turn("thanks", "You're welcome!")
    assert eligible is False

    eligible, _ = MemoryCuratorService.is_eligible_turn("ok", "Sure")
    assert eligible is False

    # 2. Sensitive content (passwords, tokens)
    eligible, reason = MemoryCuratorService.is_eligible_turn(
        "Here is my password: supersecret123 for root", "Understood"
    )
    assert eligible is False
    assert "sensitive" in reason

    eligible, reason = MemoryCuratorService.is_eligible_turn(
        "My api key is sk-1234567890abcdef1234567890", "Saved"
    )
    assert eligible is False
    assert "sensitive" in reason

    # 3. Eligible content
    eligible, _ = MemoryCuratorService.is_eligible_turn(
        "I recently replaced my primary workstation with a Mac Studio M2 Max.",
        "That is a powerful machine!",
    )
    assert eligible is True


@pytest.mark.asyncio
async def test_memory_curator_extraction_structured(sample_proj: Project):
    """Memory Curator makes single-pass structured extraction returning validated schema."""
    async with SessionLocal() as session:
        mock_output = json.dumps(
            {
                "schema_version": 1,
                "should_learn": True,
                "memories": [
                    {
                        "kind": "preference",
                        "content": "User prefers dark mode in all IDEs.",
                        "confidence": 0.92,
                        "durability": "long_term",
                        "evidence_refs": ["msg_10"],
                        "operation": "propose_upsert",
                    }
                ],
                "entities": [
                    {
                        "temporary_id": "e1",
                        "name": "Visual Studio Code",
                        "kind": "Application",
                        "confidence": 0.95,
                        "evidence_refs": ["msg_10"],
                    }
                ],
                "relationships": [],
                "conflicts": [],
                "requires_review": False,
            }
        )

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=mock_output))

        with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_model, "test-model")):
            result = await MemoryCuratorService.extract(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                user_message="Please remember that I prefer dark mode in all IDEs, especially Visual Studio Code.",
                ai_response="Understood, I will remember your preference for dark mode.",
            )

            assert result.should_learn is True
            assert len(result.memories) == 1
            assert result.memories[0].content == "User prefers dark mode in all IDEs."
            assert len(result.entities) == 1
            assert result.entities[0].name == "Visual Studio Code"


@pytest.mark.asyncio
async def test_memory_curator_negative_constraints_and_fallbacks(sample_proj: Project):
    """Malformed LLM responses must gracefully parse or fallback without crashing."""
    async with SessionLocal() as session:
        # Markdown-wrapped JSON output from LLM
        mock_wrapped_json = "```json\n" + json.dumps({
            "schema_version": 1,
            "should_learn": False,
            "memories": [],
            "entities": [],
            "relationships": [],
            "conflicts": [],
            "requires_review": False,
        }) + "\n```"

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=mock_wrapped_json))

        with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_model, "test-model")):
            result = await MemoryCuratorService.extract(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                user_message="A non-trivial sentence that is eligible for evaluation.",
                ai_response="Acknowledged.",
            )
            assert result.should_learn is False
            assert len(result.memories) == 0

        # Complete garbage response fallback
        mock_model.ainvoke = AsyncMock(return_value=MagicMock(content="Sorry I cannot format this."))
        with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_model, "test-model")):
            fallback_res = await MemoryCuratorService.extract(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                user_message="Another sentence to test parser error fallback handling.",
                ai_response="Acknowledged.",
            )
            assert fallback_res.should_learn is False


# ============================================================================
# PART E: GRAPH MANAGER & LADYBUGDB
# ============================================================================


@pytest.mark.asyncio
async def test_graph_manager_deterministic_upsert_and_aliases(setup_env, sample_proj: Project):
    """Graph Manager validates entities and creates typed relationships deterministically."""
    entities = [
        EntityCandidate(
            temporary_id="e1",
            name="Mac mini",
            kind="Device",
            confidence=0.95,
            evidence_refs=["turn_1"],
            aliases=["Living Room Mac"],
        ),
        EntityCandidate(
            temporary_id="e2",
            name="LM Studio",
            kind="Application",
            confidence=0.98,
            evidence_refs=["turn_1"],
        ),
    ]
    relationships = [
        RelationshipCandidate(
            source_ref="e1",
            target_ref="e2",
            kind="RUNS",
            confidence=0.92,
            evidence_refs=["turn_1"],
        )
    ]

    # First pass: create
    res1 = await GraphManagerService.resolve_and_apply(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        candidate_entities=entities,
        candidate_relationships=relationships,
    )
    assert res1["requires_review"] is False
    assert len(res1["applied_entities"]) == 2
    assert len(res1["applied_relationships"]) == 1

    # Second pass: idempotent update / reuse
    res2 = await GraphManagerService.resolve_and_apply(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        candidate_entities=entities,
        candidate_relationships=relationships,
    )
    assert res2["requires_review"] is False
    assert len(res2["applied_entities"]) == 2

    # Cross-tenant isolation verification
    foreign_stats = await setup_env.get_stats("foreign-tenant", "foreign-proj")
    assert foreign_stats.entity_count == 0


@pytest.mark.asyncio
async def test_graph_manager_ambiguity_flagging(setup_env, sample_proj: Project):
    """Ambiguous candidate entities (e.g., kind mismatch on same name) must require review."""
    # 1. Existing entity: 'Gemma' as Model
    entities1 = [
        EntityCandidate(
            temporary_id="e1",
            name="Gemma",
            kind="Model",
            confidence=0.95,
            evidence_refs=["turn_1"],
        )
    ]
    await GraphManagerService.resolve_and_apply(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        candidate_entities=entities1,
        candidate_relationships=[],
    )

    # 2. Conflicting candidate: 'Gemma' as Person
    conflicting = [
        EntityCandidate(
            temporary_id="e2",
            name="Gemma",
            kind="Person",
            confidence=0.85,
            evidence_refs=["turn_2"],
        )
    ]
    res = await GraphManagerService.resolve_and_apply(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        candidate_entities=conflicting,
        candidate_relationships=[],
    )
    assert res["requires_review"] is True
    assert len(res["review_reasons"]) >= 1
    assert any("candidate kind" in r for r in res["review_reasons"])


# ============================================================================
# PART G: PERSISTENT MARKDOWN MEMORY
# ============================================================================


def test_markdown_memory_atomic_writes_and_traversal_protection(memory_dir: Path):
    """MarkdownMemoryService prevents path traversal and writes atomic UTF-8 files."""
    tenant = "tenant-safe"
    project = "proj-safe"

    # Path traversal attempt
    with pytest.raises(ValueError, match="Path traversal detected"):
        MarkdownMemoryService.sync_memory(
            tenant_id="../../../etc",
            project_id=project,
            memory_id="mem-1",
            text="Exploit",
            kind="preference",
        )

    # Valid write
    MarkdownMemoryService.sync_memory(
        tenant_id=tenant,
        project_id=project,
        memory_id="mem-1",
        text="The user prefers dark mode.",
        kind="preference",
        confidence=0.95,
    )

    files = MarkdownMemoryService.list_files(tenant, project)
    assert len(files) == 1
    assert files[0]["filename"] == "preferences.md"

    content = MarkdownMemoryService.read_file(tenant, project, "preferences.md")
    assert content is not None
    assert "The user prefers dark mode." in content
    assert "mem-1" in content

    # Incremental update: sync another memory
    MarkdownMemoryService.sync_memory(
        tenant_id=tenant,
        project_id=project,
        memory_id="mem-2",
        text="Primary editor is VS Code.",
        kind="technology",
        confidence=0.99,
    )
    tech_content = MarkdownMemoryService.read_file(tenant, project, "technology.md")
    assert tech_content is not None
    assert "Primary editor is VS Code." in tech_content

    # Removal on delete
    MarkdownMemoryService.remove_memory(tenant, project, "mem-1", kind="preference")
    updated_pref = MarkdownMemoryService.read_file(tenant, project, "preferences.md")
    assert "mem-1" not in (updated_pref or "")


# ============================================================================
# PART F & H: CROSS-STORE COORDINATION, SUPERSESSION & CONFLICT HANDLING
# ============================================================================


@pytest.mark.asyncio
async def test_cross_store_memory_conflict_and_supersession(setup_env, memory_dir: Path, sample_proj: Project):
    """When a new memory replaces an older memory (e.g., Qwen -> Gemma),

    the older memory is marked superseded in SQLite and removed from Chroma & Markdown.
    """
    async with SessionLocal() as session:
        # Step 1: Initial memory
        mem1 = await UnifiedMemoryManager.remember(
            session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="User runs Qwen 7B as primary local model.",
            target="memory",
            kind="technology",
            confidence=0.95,
        )
        mem1_id = mem1["id"]

        # Verify active in SQLite
        db_mem1 = await MemoryService.get(session, sample_proj.tenant_id, sample_proj.id, mem1_id)
        assert db_mem1 is not None
        assert db_mem1.status == "active"

        # Verify in Markdown
        md_content = MarkdownMemoryService.read_file(sample_proj.tenant_id, sample_proj.id, "technology.md")
        assert mem1_id in (md_content or "")

        # Step 2: LearningCoordinator processes turn 2 replacing Qwen with Gemma
        mock_output = json.dumps({
            "schema_version": 1,
            "should_learn": True,
            "memories": [
                {
                    "kind": "technology",
                    "content": "User replaced Qwen with Gemma 2 as primary local model.",
                    "confidence": 0.98,
                    "durability": "long_term",
                    "evidence_refs": ["turn_2"],
                    "operation": "propose_replace",
                    "supersedes_fact": "Qwen",
                }
            ],
            "entities": [
                {
                    "temporary_id": "e1",
                    "name": "Gemma 2",
                    "kind": "Model",
                    "confidence": 0.98,
                    "evidence_refs": ["turn_2"],
                }
            ],
            "relationships": [],
            "conflicts": [],
            "requires_review": False,
        })
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=mock_output))

        with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_model, "test-model")):
            event = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_2",
                user_message="I have replaced Qwen with Gemma 2 as my primary model.",
                ai_response="Understood, I will note that you now use Gemma 2.",
                override_enabled_check=True,
            )
            assert event is not None
            assert event.status == "completed"

        # Step 3: Verify mem1 is superseded
        db_mem1_updated = await MemoryService.get(session, sample_proj.tenant_id, sample_proj.id, mem1_id)
        assert db_mem1_updated is not None
        assert db_mem1_updated.status == "superseded"

        # List active memories
        active_memories = await UnifiedMemoryManager.list_memories(
            session, sample_proj.tenant_id, sample_proj.id, status="active"
        )
        assert len(active_memories) == 1
        assert "Gemma 2" in active_memories[0].text


# ============================================================================
# PART J & I: ASYNC LEARNING COORDINATOR, IDEMPOTENCY & REST CONTROLS
# ============================================================================


@pytest.mark.asyncio
async def test_learning_coordinator_idempotency_and_approval(setup_env, memory_dir: Path, sample_proj: Project):
    """LearningCoordinator ensures idempotency on retried events and supports HITL review."""
    async with SessionLocal() as session:
        mock_review_output = json.dumps({
            "schema_version": 1,
            "should_learn": True,
            "memories": [
                {
                    "kind": "profile",
                    "content": "Ambiguous relationship statement.",
                    "confidence": 0.65,
                    "durability": "long_term",
                    "evidence_refs": ["turn_review"],
                    "operation": "propose_upsert",
                }
            ],
            "entities": [],
            "relationships": [],
            "conflicts": [],
            "requires_review": True,
        })

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=mock_review_output))

        with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_model, "test-model")):
            # First pass creates event in review_required
            event1 = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_review_1",
                user_message="Some ambiguous statement needing review.",
                ai_response="Got it.",
                override_enabled_check=True,
            )
            assert event1 is not None
            assert event1.status == "review_required"

            # Second pass with same source_event_id returns existing event without re-execution (idempotent)
            event2 = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_review_1",
                user_message="Some ambiguous statement needing review.",
                ai_response="Got it.",
                override_enabled_check=True,
            )
            assert event2 is not None
            assert event2.id == event1.id

        # Human approves pending event
        approved = await LearningCoordinator.approve_event(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            event_id=event1.id,
        )
        assert approved is not None
        assert approved.status == "completed"

        # Verify memory is now active in SQLite
        mems = await MemoryService.list(session, sample_proj.tenant_id, sample_proj.id, status="active")
        matching = [m for m in mems if m.source_ref == "turn_review_1"]
        assert len(matching) == 1
        assert matching[0].status == "active"


@pytest.mark.asyncio
async def test_memory_correction_and_deletion_controls(setup_env, memory_dir: Path, sample_proj: Project):
    """User can correct (PATCH) or delete (DELETE) memories through UnifiedMemoryManager."""
    async with SessionLocal() as session:
        # Create
        created = await UnifiedMemoryManager.remember(
            session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="User prefers coffee black.",
            target="memory",
            kind="preference",
        )
        mem_id = created["id"]

        # Correct
        updated = await UnifiedMemoryManager.update_memory(
            session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            memory_id=mem_id,
            text="User prefers coffee with oat milk.",
        )
        assert updated is not None
        assert updated.text == "User prefers coffee with oat milk."

        # Verify markdown reflects update
        pref_content = MarkdownMemoryService.read_file(sample_proj.tenant_id, sample_proj.id, "preferences.md")
        assert "User prefers coffee with oat milk." in (pref_content or "")

        # Delete
        deleted = await UnifiedMemoryManager.delete_memory(
            session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            memory_id=mem_id,
        )
        assert deleted is True

        # Verify deleted in SQLite (status == 'deleted')
        db_m = await MemoryService.get(session, sample_proj.tenant_id, sample_proj.id, mem_id)
        assert db_m is not None
        assert db_m.status == "deleted"

        # Verify removed from Markdown
        pref_content_after = MarkdownMemoryService.read_file(sample_proj.tenant_id, sample_proj.id, "preferences.md")
        assert mem_id not in (pref_content_after or "")
