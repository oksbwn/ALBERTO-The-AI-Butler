"""Acceptance test suite for Alberto memory recall accuracy (OLMX vs Ollama).
Validates Scenarios 1 through 7:
1. Immediate context retention
2. Cross-conversation recall of accepted persisted memory
3. Rejection of assistant hallucination contamination
4. Distinction and separation of similar product names (no accidental merge)
5. Memory correction and safe supersession of outdated facts
6. Local LLM prompt framing with verbatim technical name preservation
7. SQLite memory retrieval fallback when embedding/vector search is unavailable
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from alberto.db import SessionLocal
from alberto.knowledge.graph import LadybugGraphAdapter, set_graph_adapter
from alberto.models.entities import Project
from alberto.schemas.memory_curator import (
    EntityCandidate,
    MemoryCandidate,
    MemoryCuratorOutput,
)
from alberto.services.assistant import AssistantService
from alberto.services.context_assembler import ContextAssembler
from alberto.services.graph_manager import GraphManagerService
from alberto.services.learning_coordinator import LearningCoordinator
from alberto.services.markdown_memory import MarkdownMemoryService
from alberto.services.memory import MemoryService
from alberto.services.memory_curator import MemoryCuratorService
from alberto.services.projects import ProjectService
from alberto.services.unified_memory import UnifiedMemoryManager


@pytest.fixture
def graph_dir():
    with tempfile.TemporaryDirectory(prefix="ladybug_recall_") as tmp:
        yield Path(tmp)


@pytest.fixture
def memory_dir():
    with tempfile.TemporaryDirectory(prefix="markdown_recall_") as tmp:
        p = Path(tmp)
        MarkdownMemoryService._base_dir_override = p
        yield p
        MarkdownMemoryService._base_dir_override = None


class MockEmbedder:
    dim = 384
    model_name = "mock"

    async def aembed_query(self, text: str) -> list[float]:
        return [0.05] * 384

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.05] * 384 for _ in texts]


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
            tenant_id="tenant-recall-1",
            name="Recall Accuracy Project",
            slug="recall-proj-1",
        )
        await session.commit()
        await session.refresh(proj)
        return proj


# ============================================================================
# SCENARIO 1: Immediate context
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_1_immediate_context(sample_proj: Project, setup_env):
    """User states OLMX; follow-up in same conversation must maintain OLMX in context."""
    from langchain_core.messages import AIMessage

    messages = [
        {"role": "user", "content": "I use OLMX for inference."},
        {"role": "assistant", "content": "Understood, you use OLMX for inference."},
        {"role": "user", "content": "Which inference framework am I using?"},
    ]

    mock_model = MagicMock()

    captured_prompt = []

    async def mock_astream(msgs, config=None):
        for m in msgs:
            captured_prompt.append(getattr(m, "content", ""))
        yield AIMessage(content="You are using OLMX for inference.")

    mock_model.astream = mock_astream
    mock_model.bind_tools = MagicMock(return_value=mock_model)

    with patch("alberto.services.assistant.resolve_model", return_value=mock_model):
        frames = []
        async for frame in AssistantService._fast_stream(
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            messages=messages,
        ):
            frames.append(frame)

        text_output = "".join(f["data"]["content"] for f in frames if f.get("event") == "messages")
        assert "OLMX" in text_output
        assert "Ollama" not in text_output

        full_prompt_text = " ".join(captured_prompt)
        assert "OLMX" in full_prompt_text


# ============================================================================
# SCENARIO 2: New conversation cross-conversation recall
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_2_new_conversation_recall(sample_proj: Project, setup_env):
    """Learned OLMX memory must be retrieved in a brand-new conversation thread."""
    async with SessionLocal() as session:
        await MemoryService.remember(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="User uses OLMX for inference.",
            kind="technology",
            confidence=1.0,
            provenance="memory_curator",
            status="active",
        )

    async with SessionLocal() as session:
        recalled = await UnifiedMemoryManager.recall(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            query="Which inference framework am I using?",
            top_k=5,
        )

        assert len(recalled) > 0
        recalled_texts = [r.content for r in recalled]
        assert any("OLMX" in t for t in recalled_texts)

        context_block = ContextAssembler.assemble_context(recalled)
        assert "OLMX" in context_block
        assert "Preserve user-provided facts" in context_block


# ============================================================================
# SCENARIO 3: Assistant hallucination contamination prevented
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_3_assistant_hallucination_rejected(sample_proj: Project, setup_env):
    """Assistant speculation mentioning Ollama must not contaminate user memory."""
    async with SessionLocal() as session:
        curator_output = MemoryCuratorOutput(
            schema_version=1,
            should_learn=True,
            memories=[
                MemoryCandidate(
                    operation="propose_upsert",
                    kind="technology",
                    content="User uses Ollama for inference.",
                    confidence=0.9,
                    evidence_refs=["Ollama is a great choice on macOS for inference"],
                )
            ],
            entities=[
                EntityCandidate(
                    temporary_id="ent_1",
                    kind="software",
                    name="Ollama",
                    aliases=["OLMX"],
                    confidence=0.9,
                )
            ],
            relationships=[],
            conflicts=[],
            requires_review=False,
        )

        user_msg = "I use OLMX for inference."
        ai_resp = "Ollama is a great choice on macOS for inference."

        with patch.object(MemoryCuratorService, "extract", new=AsyncMock(return_value=curator_output)):
            event = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_hallucination_1",
                user_message=user_msg,
                ai_response=ai_resp,
                override_enabled_check=True,
            )

        assert event is not None
        assert event.requires_review is True
        assert event.status == "review_required"
        assert "Ungrounded evidence_refs" in (event.error or "") or "Ungrounded entity alias" in (event.error or "")

        active_mems = await MemoryService.list(session, sample_proj.tenant_id, sample_proj.id, status="active")
        assert not any("Ollama" in m.text for m in active_mems)


# ============================================================================
# SCENARIO 4: Similar product names (no accidental merge)
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_4_similar_product_names_not_merged(sample_proj: Project, setup_env):
    """OLMX and Ollama must remain distinct entities and never merge automatically."""
    cand_olmx = EntityCandidate(
        temporary_id="e_olmx",
        kind="software",
        name="OLMX",
        description="Inference runtime for Apple Silicon",
        confidence=0.95,
    )
    cand_ollama = EntityCandidate(
        temporary_id="e_ollama",
        kind="software",
        name="Ollama",
        description="Local LLM runner",
        confidence=0.95,
    )

    res_1 = await GraphManagerService.resolve_and_validate(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        candidate_entities=[cand_olmx],
        candidate_relationships=[],
    )
    assert not res_1["requires_review"]
    await GraphManagerService.apply_resolved(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        resolved_entities=res_1["resolved_entities"],
        resolved_relationships=[],
    )

    res_2 = await GraphManagerService.resolve_and_validate(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        candidate_entities=[cand_ollama],
        candidate_relationships=[],
    )
    assert not res_2["requires_review"]
    await GraphManagerService.apply_resolved(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        resolved_entities=res_2["resolved_entities"],
        resolved_relationships=[],
    )

    adapter = setup_env
    all_entities = await adapter.find_entities(sample_proj.tenant_id, sample_proj.id, limit=50)
    names = {e.name for e in all_entities}
    assert "OLMX" in names
    assert "Ollama" in names
    assert len(all_entities) >= 2


# ============================================================================
# SCENARIO 5: Memory correction and supersession
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_5_memory_correction_and_supersession(sample_proj: Project, setup_env):
    """User changes from OLMX to Ollama: old memory is superseded and not retrieved."""
    async with SessionLocal() as session:
        mem1 = await MemoryService.remember(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="User uses OLMX for inference.",
            kind="technology",
            confidence=1.0,
            status="active",
        )

        correction_output = MemoryCuratorOutput(
            schema_version=1,
            should_learn=True,
            memories=[
                MemoryCandidate(
                    operation="propose_replace",
                    kind="technology",
                    content="User uses Ollama for inference.",
                    confidence=0.95,
                    evidence_refs=["I have switched to Ollama for inference."],
                    supersedes_fact="OLMX",
                )
            ],
            entities=[],
            relationships=[],
            conflicts=[],
            requires_review=False,
        )

        with patch.object(MemoryCuratorService, "extract", new=AsyncMock(return_value=correction_output)):
            event = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_corr_1",
                user_message="I have switched to Ollama for inference.",
                ai_response="Understood, updated your inference framework to Ollama.",
                override_enabled_check=True,
            )

        assert event is not None
        assert event.status == "completed"

        await session.refresh(mem1)
        assert mem1.status == "superseded"
        assert mem1.superseded_by is not None

        active_mems = await MemoryService.list(session, sample_proj.tenant_id, sample_proj.id, status="active")
        active_texts = [m.text for m in active_mems]
        assert "User uses Ollama for inference." in active_texts
        assert "User uses OLMX for inference." not in active_texts

        hits = await UnifiedMemoryManager.recall(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            query="Which inference framework am I using?",
            top_k=5,
        )
        hit_texts = [h.content for h in hits]
        assert any("Ollama" in t for t in hit_texts)
        assert not any("OLMX" in t for t in hit_texts)


# ============================================================================
# SCENARIO 6: Local LLM prompt construction with verbatim evidence
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_6_local_llm_prompt_construction(sample_proj: Project, setup_env):
    """Local LLM prompt framing includes exact technical evidence and instructions."""
    async with SessionLocal() as session:
        await MemoryService.remember(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="User uses OLMX for inference.",
            kind="technology",
            confidence=1.0,
            status="active",
        )

    captured_system_prompt = []

    mock_model = MagicMock()

    async def mock_astream(msgs, config=None):
        for m in msgs:
            if hasattr(m, "content"):
                captured_system_prompt.append(m.content)
        yield MagicMock(content="Based on your configuration, you are using OLMX.")

    mock_model.astream = mock_astream
    mock_model.bind_tools = MagicMock(return_value=mock_model)

    with patch("alberto.services.assistant.resolve_model", return_value=mock_model):
        frames = []
        async for frame in AssistantService._fast_stream(
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            messages=[{"role": "user", "content": "Which inference framework am I using?"}],
        ):
            frames.append(frame)

        prompt_str = " ".join(captured_system_prompt)
        assert "User uses OLMX for inference." in prompt_str
        assert "Preserve user-provided facts, technical names, acronyms, and product identifiers verbatim" in prompt_str
        assert "Do NOT autocorrect, normalize, or substitute user technical identifiers" in prompt_str


# ============================================================================
# SCENARIO 7: Embedding unavailable SQLite fallback
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_7_embedding_unavailable_fallback(sample_proj: Project, setup_env):
    """Active SQLite memory is retrieved via keyword matching when vector search fails."""
    async with SessionLocal() as session:
        await MemoryService.remember(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="User uses OLMX for inference.",
            kind="technology",
            confidence=1.0,
            status="active",
        )

    async with SessionLocal() as session:
        with patch.object(MemoryService, "recall", new=AsyncMock(side_effect=RuntimeError("ChromaDB offline"))):
            records = await UnifiedMemoryManager._fetch_memory(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                query="Which inference framework am I using?",
                scope="default",
                top_k=5,
            )

            assert len(records) > 0
            assert records[0].source == "sqlite_memory"
            assert "OLMX" in records[0].content
            assert records[0].score is not None and records[0].score > 0


# ============================================================================
# SCENARIO 8: FallbackVectorCollection Restart Persistence & Durability
# ============================================================================


def test_scenario_8_fallback_vector_restart_persistence(tmp_path: Path):
    """Records written to FallbackVectorCollection survive re-instantiation."""
    from alberto.knowledge.store import FallbackVectorCollection

    persist_dir = str(tmp_path / "chroma_store")
    col1 = FallbackVectorCollection("test_persist_col", persist_path=persist_dir)
    assert col1.is_durable is True

    ids = ["doc_1", "doc_2"]
    embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    documents = ["User uses SGLang for serving.", "User runs Aphrodite Engine."]
    metadatas = [{"tenant_id": "t1", "project_id": "p1"}, {"tenant_id": "t1", "project_id": "p1"}]

    col1.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    assert col1.count() == 2

    # Simulate application restart: instantiate a fresh collection instance on the same path
    col2 = FallbackVectorCollection("test_persist_col", persist_path=persist_dir)
    assert col2.count() == 2

    doc1_record = col2.get(ids=["doc_1"], include=["embeddings"])
    assert doc1_record["ids"] == ["doc_1"]
    assert doc1_record["documents"] == ["User uses SGLang for serving."]
    assert doc1_record["metadatas"][0]["tenant_id"] == "t1"
    assert doc1_record["embeddings"][0] == [0.1, 0.2, 0.3]

    # Query survives and scores properly
    res = col2.query(query_embeddings=[[0.1, 0.2, 0.3]], n_results=1)
    assert res["ids"][0][0] == "doc_1"


# ============================================================================
# SCENARIO 9: Vector Store Degraded Status & No Silent Loss
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_9_degraded_status_and_no_silent_loss(sample_proj: Project, tmp_path: Path):
    """Inspect degraded vector status reporting and verify no silent persistence loss."""
    from alberto.knowledge.store import FallbackVectorCollection, get_vector_store_status

    # Durable disk fallback reports degraded with durable=True
    persist_dir = str(tmp_path / "chroma_degraded")
    status = get_vector_store_status(persist_dir)
    assert status["available"] is True
    assert status["durable"] is True
    assert status["mode"] in ("native", "fallback")

    # In-memory path reports degraded_in_memory with durable=False
    mem_status = get_vector_store_status(":memory:")
    assert mem_status["durable"] is False
    assert mem_status["status"] == "degraded_in_memory"

    # UnifiedMemoryManager.get_storage_status exposes vector store durability
    async with SessionLocal() as session:
        storage_status = await UnifiedMemoryManager.get_storage_status(
            session, sample_proj.tenant_id, sample_proj.id
        )
        assert "chroma" in storage_status
        assert storage_status["chroma"]["available"] is True
        assert "durable" in storage_status["chroma"]

    # No silent loss: if persist_path is configured but unwritable/invalid, _save() raises OSError
    bad_col = FallbackVectorCollection("test_bad", persist_path=persist_dir)
    # Point _file_path to a read-only or invalid condition
    with patch.object(bad_col, "_file_path", return_value=None):
        with pytest.raises(OSError, match="cannot persist"):
            bad_col.upsert(ids=["x"], embeddings=[[0.1]], documents=["test"], metadatas=[{}])


# ============================================================================
# SCENARIO 10: Alias Equivalence Safety (Substring vs Actual Equivalence)
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_10_alias_equivalence_safety(sample_proj: Project, setup_env):
    """Candidate aliases require explicit equivalence evidence, not mere co-occurrence."""
    from alberto.services.learning_coordinator import (
        has_alias_equivalence_evidence,
    )

    # 1. Co-occurrence in sentence does NOT constitute equivalence
    text_cooccur = "I use vLLM for serving and SGLang for batch inference."
    assert has_alias_equivalence_evidence("vLLM", "SGLang", text_cooccur) is False

    # 2. Explicit linguistic equivalence patterns succeed
    assert has_alias_equivalence_evidence("vLLM", "VirtualLLM", "I use vLLM (aka VirtualLLM).") is True
    assert has_alias_equivalence_evidence("Aphrodite", "Aphrodite Engine", "I use Aphrodite, also known as Aphrodite Engine.") is True
    assert has_alias_equivalence_evidence("TGI", "Text Generation Inference", "I run TGI (short for Text Generation Inference).") is True

    # 3. LearningCoordinator validation rejects ungrounded alias proposal
    cand_entity = EntityCandidate(
        temporary_id="ent_vllm",
        name="vLLM",
        kind="software",
        aliases=["SGLang"],  # Curator erroneously suggests SGLang as alias for vLLM
        confidence=0.9,
    )
    curator_output = MemoryCuratorOutput(
        schema_version=1,
        should_learn=True,
        memories=[
            MemoryCandidate(
                content="User uses vLLM for serving.",
                kind="technology",
                confidence=0.95,
                operation="propose_upsert",
                evidence_refs=["user:msg_1"],
            )
        ],
        entities=[cand_entity],
        relationships=[],
        requires_review=False,
    )

    async with SessionLocal() as session:
        with patch.object(MemoryCuratorService, "extract", new=AsyncMock(return_value=curator_output)):
            event = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_alias_test_1",
                user_message="I use vLLM for serving and SGLang for batch inference.",
                ai_response="Understood, vLLM for serving and SGLang for batching.",
                override_enabled_check=True,
            )

            assert event is not None
            assert event.status == "review_required"
            assert "equivalence evidence" in (event.error or "")


# ============================================================================
# SCENARIO 11: Supersession Safety (Second Tool Addition vs Replacement)
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_11_supersession_safety(sample_proj: Project, setup_env):
    """Adding a second tool must NOT supersede existing tools without explicit replacement evidence."""
    from alberto.services.learning_coordinator import has_replacement_evidence

    # Helper verification
    assert has_replacement_evidence("I also use PyTorch for fine-tuning.") is False
    assert has_replacement_evidence("I use vLLM for serving and Triton for inference.") is False
    assert has_replacement_evidence("I switched from OLMX to Aphrodite for serving.") is True
    assert has_replacement_evidence("Actually, use SGLang instead of vLLM.") is True
    assert has_replacement_evidence("Correction: I no longer use Ollama.") is True

    # Seed initial tool memory
    async with SessionLocal() as session:
        initial_mem = await MemoryService.remember(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="User uses OLMX for inference.",
            kind="technology",
            confidence=1.0,
            status="active",
        )

    # 1. User mentions a second tool: "I also use PyTorch for training."
    # Even if curator mistakenly emitted propose_replace, coordinator flags review and does not supersede
    cand_mem = MemoryCandidate(
        content="User uses PyTorch for training.",
        kind="technology",
        confidence=0.95,
        operation="propose_replace",  # Faulty curator tag
        evidence_refs=["user:msg_2"],
    )
    curator_output = MemoryCuratorOutput(
        schema_version=1,
        should_learn=True,
        memories=[cand_mem],
        entities=[],
        relationships=[],
        requires_review=False,
    )

    async with SessionLocal() as session:
        with patch.object(MemoryCuratorService, "extract", new=AsyncMock(return_value=curator_output)):
            event = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_add_second_tool",
                user_message="I also use PyTorch for deep learning training.",
                ai_response="Understood, PyTorch for deep learning.",
                override_enabled_check=True,
            )

            assert event is not None
            assert event.status == "review_required"
            assert "explicit correction/replacement evidence" in (event.error or "")

            # Ensure initial memory remains ACTIVE and not superseded
            refreshed_initial = await MemoryService.get(
                session, sample_proj.tenant_id, sample_proj.id, initial_mem.id
            )
            assert refreshed_initial is not None
            assert refreshed_initial.status == "active"
            assert refreshed_initial.superseded_by is None

        # 2. Explicit replacement: user says "I switched from OLMX to Aphrodite for inference."
        replacement_output = MemoryCuratorOutput(
            schema_version=1,
            should_learn=True,
            memories=[
                MemoryCandidate(
                    operation="propose_replace",
                    kind="technology",
                    content="User uses Aphrodite for inference.",
                    confidence=0.95,
                    evidence_refs=["I switched from OLMX to Aphrodite for inference."],
                    supersedes_fact="OLMX",
                )
            ],
            entities=[],
            relationships=[],
            requires_review=False,
        )

        with patch.object(MemoryCuratorService, "extract", new=AsyncMock(return_value=replacement_output)):
            rep_event = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_replace_tool",
                user_message="I switched from OLMX to Aphrodite for inference.",
                ai_response="Understood, updated to Aphrodite.",
                override_enabled_check=True,
            )
            assert rep_event is not None
            assert rep_event.status == "completed"

            refreshed_initial_2 = await MemoryService.get(
                session, sample_proj.tenant_id, sample_proj.id, initial_mem.id
            )
            assert refreshed_initial_2 is not None
            assert refreshed_initial_2.status == "superseded"
            assert refreshed_initial_2.superseded_by is not None


# ============================================================================
# SCENARIO 12: Generic Technical Identifier Preservation (Unfamiliar Names)
# ============================================================================


@pytest.mark.asyncio
async def test_scenario_12_generic_technical_identifier_preservation(sample_proj: Project, setup_env):
    """Unfamiliar technical names absent from prompts are preserved verbatim without normalization."""
    from langchain_core.messages import AIMessage

    unfamiliar_identifiers = ["Aphrodite", "SGLang", "DeepEP", "TGI"]

    for ident in unfamiliar_identifiers:
        async with SessionLocal() as session:
            await MemoryService.remember(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                text=f"User uses {ident} for serving.",
                kind="technology",
                confidence=1.0,
                status="active",
            )

        captured_system_prompt = []
        mock_model = MagicMock()

        async def mock_astream(msgs, config=None, _ident=ident):
            for m in msgs:
                if hasattr(m, "content"):
                    captured_system_prompt.append(m.content)
            yield AIMessage(content=f"You are using {_ident} for serving.")

        mock_model.astream = mock_astream
        mock_model.bind_tools = MagicMock(return_value=mock_model)

        with patch("alberto.services.assistant.resolve_model", return_value=mock_model):
            frames = []
            async for frame in AssistantService._fast_stream(
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                messages=[{"role": "user", "content": f"Which engine am I using for serving?"}],
            ):
                frames.append(frame)

            text_output = "".join(f["data"]["content"] for f in frames if f.get("event") == "messages")
            assert ident in text_output

            prompt_str = " ".join(captured_system_prompt)
            assert ident in prompt_str
            # Verify system prompt has no hardcoded OLMX/Ollama special casing
            assert "e.g. OLMX" not in prompt_str
            assert "such as Ollama" not in prompt_str


# ============================================================================
# SCENARIO 13: Empty or blank query shows all knowledge records by default
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_13_empty_query_recalls_all_knowledges(sample_proj):
    """Empty or whitespace query in recall retrieves all active memories and graph entities."""
    async with SessionLocal() as session:
        await MemoryService.remember(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="User prefers dark mode UI.",
            kind="preference",
            confidence=1.0,
            status="active",
        )
        await MemoryService.remember(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="MacStudio has 192GB unified RAM.",
            kind="hardware",
            confidence=1.0,
            status="active",
        )

        hits_empty = await UnifiedMemoryManager.recall(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            query="",
            sources=["sqlite_memory"],
            top_k=10,
        )
        contents = [h.content for h in hits_empty]
        assert "User prefers dark mode UI." in contents
        assert "MacStudio has 192GB unified RAM." in contents

        # Whitespace query also retrieves all
        hits_ws = await UnifiedMemoryManager.recall(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            query="   ",
            sources=["sqlite_memory"],
            top_k=10,
        )
        contents_ws = [h.content for h in hits_ws]
        assert "User prefers dark mode UI." in contents_ws
