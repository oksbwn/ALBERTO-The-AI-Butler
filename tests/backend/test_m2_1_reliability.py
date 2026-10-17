"""Verification and reliability acceptance test suite for Alberto Milestone 2.1:
Reliability, Learning Safety & Cross-Store Consistency Verification.

Validates:
1. Durable queue admission, lifecycle tracking, and duplicate-event prevention.
2. Worker restart recovery and payload reuse.
3. Acceptance before graph mutation (no premature writes on low-confidence or ambiguous candidates).
4. Full rejection safety across all authoritative and projection stores.
5. Deterministic evidence and confidence validation.
6. Graph entity identity matching, generic label safeguards, and explicit alias resolution.
7. Cross-store correction, deletion, and shared provenance preservation.
8. Learning settings persistence in Project.config and strict tenant/project isolation.
9. Real chat memory recall: UnifiedMemoryManager integration with agent context and model invocation.
10. Local LLM timeout and malformed JSON error handling without false success reporting.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from alberto.config import settings
from alberto.db import SessionLocal
from alberto.knowledge.graph import (
    GraphEntity,
    GraphRelationship,
    LadybugGraphAdapter,
    make_relationship_id,
    set_graph_adapter,
)
from alberto.models import Memory, MemoryLearningEvent
from alberto.models.entities import Project
from alberto.nodes.agent_node import MemoryRecallMiddleware
from alberto.schemas.memory_curator import (
    EntityCandidate,
    MemoryCandidate,
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
    with tempfile.TemporaryDirectory(prefix="ladybug_rel_") as tmp:
        yield Path(tmp)


@pytest.fixture
def memory_dir():
    with tempfile.TemporaryDirectory(prefix="markdown_rel_") as tmp:
        p = Path(tmp)
        MarkdownMemoryService._base_dir_override = p
        yield p
        MarkdownMemoryService._base_dir_override = None


class MockEmbedder:
    model_name = "mock"
    dim: int = 384

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
    import uuid
    uid = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id=f"tenant-rel-{uid}",
            name=f"Reliability Project {uid}",
            slug=f"rel-proj-{uid}",
        )
        # Enable learning for this project
        pcfg = dict(proj.config or {})
        pcfg["memory_learning_enabled"] = True
        proj.config = pcfg
        await session.commit()
        await session.refresh(proj)
        session.expunge(proj)
        return proj


# ============================================================================
# 1. P0 — DURABLE ASYNCHRONOUS LEARNING & DUPLICATE PREVENTION
# ============================================================================


@pytest.mark.asyncio
async def test_durable_queue_admission_and_duplicate_prevention(setup_env, sample_proj: Project):
    """Confirm turn learning is durably recorded in SQLite before background processing,
    and duplicate invocations reuse the existing event row."""
    source_event_id = "turn_event_101"
    user_msg = "My primary workstation is an Ubuntu 24.04 desktop."
    ai_resp = "Got it, I will remember you use Ubuntu 24.04."

    with patch.object(LearningCoordinator, "_safe_run_turn_learning", new=AsyncMock()) as mock_bg:
        event = await LearningCoordinator.schedule_turn_learning(
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            source_event_id=source_event_id,
            user_message=user_msg,
            ai_response=ai_resp,
        )
        assert event is not None
        assert event.status == "pending"
        assert event.source_event_id == source_event_id
        mock_bg.assert_called_once()

    # Verify directly in SQLite
    async with SessionLocal() as session:
        db_event = (
            await session.execute(
                select(MemoryLearningEvent).where(
                    MemoryLearningEvent.tenant_id == sample_proj.tenant_id,
                    MemoryLearningEvent.project_id == sample_proj.id,
                    MemoryLearningEvent.source_event_id == source_event_id,
                )
            )
        ).scalar_one_or_none()
        assert db_event is not None
        assert db_event.status == "pending"
        payload = db_event.extraction_payload or {}
        assert payload.get("turn", {}).get("user_message") == user_msg

    # Second call with the same event ID must NOT create duplicate row
    with patch.object(LearningCoordinator, "_safe_run_turn_learning", new=AsyncMock()):
        dup_event = await LearningCoordinator.schedule_turn_learning(
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            source_event_id=source_event_id,
            user_message=user_msg,
            ai_response=ai_resp,
        )
        assert dup_event.id == event.id

    async with SessionLocal() as session:
        all_events = (
            await session.execute(
                select(MemoryLearningEvent).where(
                    MemoryLearningEvent.tenant_id == sample_proj.tenant_id,
                    MemoryLearningEvent.project_id == sample_proj.id,
                    MemoryLearningEvent.source_event_id == source_event_id,
                )
            )
        ).scalars().all()
        assert len(all_events) == 1


# ============================================================================
# 2. P0 — RESTART RECOVERY & SAVED EXTRACTION REUSE
# ============================================================================


@pytest.mark.asyncio
async def test_restart_recovery_and_payload_reuse(setup_env, sample_proj: Project):
    """Interrupted learning events are recovered on startup, and already-extracted
    payloads are reused without re-calling the LLM."""
    source_event_id = "turn_interrupted_202"
    user_msg = "My home lab server runs Proxmox VE."
    ai_resp = "Understood, Proxmox VE on home lab."

    # Simulate an event left in 'extracted' state before a crash
    saved_curator_output = MemoryCuratorOutput(
        schema_version=1,
        should_learn=True,
        memories=[
            MemoryCandidate(
                kind="technology",
                content="Home lab server runs Proxmox VE.",
                confidence=0.95,
                durability="long_term",
                evidence_refs=[user_msg],
                operation="propose_upsert",
            )
        ],
        entities=[
            EntityCandidate(
                temporary_id="e1",
                name="Proxmox VE",
                kind="application",
                confidence=0.95,
                evidence_refs=[user_msg],
            )
        ],
        relationships=[],
        requires_review=False,
    )

    async with SessionLocal() as session:
        event = MemoryLearningEvent(
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            source_event_id=source_event_id,
            source_type="conversation_turn",
            status="extracted",
            extraction_payload={
                "turn": {"user_message": user_msg, "ai_response": ai_resp},
                "curator_output": saved_curator_output.model_dump(),
            },
            retry_count=0,
        )
        session.add(event)
        await session.commit()

    # Simulate process restart calling recover_pending_events
    with patch.object(
        MemoryCuratorService,
        "extract",
        new=AsyncMock(
            return_value=MemoryCuratorOutput(
                schema_version=1,
                should_learn=False,
                memories=[],
                entities=[],
                relationships=[],
                requires_review=False,
            )
        ),
    ) as mock_extract:
        recovered_count = await LearningCoordinator.recover_pending_events(
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
        )
        assert recovered_count == 1
        # Extract was NOT called because saved extraction was reused!
        mock_extract.assert_not_called()

    # Verify event completed and memory persisted
    async with SessionLocal() as session:
        ev = (
            await session.execute(
                select(MemoryLearningEvent).where(
                    MemoryLearningEvent.tenant_id == sample_proj.tenant_id,
                    MemoryLearningEvent.project_id == sample_proj.id,
                    MemoryLearningEvent.source_event_id == source_event_id,
                )
            )
        ).scalar_one_or_none()
        assert ev.status == "completed"
        assert len(ev.applied_memory_ids) == 1

        mems = await MemoryService.list(session, sample_proj.tenant_id, sample_proj.id)
        assert any("Proxmox VE" in m.text for m in mems)


# ============================================================================
# 3. P0 — ACCEPTANCE BEFORE GRAPH MUTATION
# ============================================================================


@pytest.mark.asyncio
async def test_acceptance_before_mutation_invariant(setup_env, sample_proj: Project):
    """Invariant: If candidate requires review, LadybugDB and SQLite stores
    must NOT be mutated before explicit operator approval."""
    source_event_id = "turn_review_gated"
    user_msg = "Please delete my old server config."
    ai_resp = "I can propose that deletion."

    # Curator outputs propose_delete and low confidence
    mock_output = MemoryCuratorOutput(
        schema_version=1,
        should_learn=True,
        memories=[
            MemoryCandidate(
                kind="technology",
                content="Delete old server configuration.",
                confidence=0.60,  # Low confidence
                evidence_refs=[user_msg],
                operation="propose_delete",
            )
        ],
        entities=[
            EntityCandidate(
                temporary_id="e1",
                name="Old Server",
                kind="device",
                confidence=0.60,
                evidence_refs=[user_msg],
            )
        ],
        relationships=[],
        requires_review=True,
        review_reason="Proposed deletion with low confidence",
    )

    with patch.object(MemoryCuratorService, "extract", new=AsyncMock(return_value=mock_output)):
        async with SessionLocal() as session:
            event = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id=source_event_id,
                user_message=user_msg,
                ai_response=ai_resp,
                override_enabled_check=True,
            )
            assert event.status == "review_required"
            assert event.requires_review is True

    # STRICT INVARIANT VERIFICATION: LadybugDB must have 0 entities! SQLite must have 0 memories!
    entities = await setup_env.find_entities(sample_proj.tenant_id, sample_proj.id)
    assert len(entities) == 0

    async with SessionLocal() as session:
        mems = await MemoryService.list(session, sample_proj.tenant_id, sample_proj.id)
        assert len(mems) == 0

        # Now simulate authorized human approval
        approved = await LearningCoordinator.approve_event(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            event_id=event.id,
        )
        assert approved.status == "completed"
        assert approved.requires_review is False

    # After approval, stores are updated idempotently
    entities_post = await setup_env.find_entities(sample_proj.tenant_id, sample_proj.id)
    assert len(entities_post) == 1
    assert entities_post[0].name == "Old Server"


# ============================================================================
# 4. P0 — REJECTION PREVENTS ALL STORE MUTATIONS
# ============================================================================


@pytest.mark.asyncio
async def test_rejection_prevents_all_mutations(setup_env, sample_proj: Project):
    """When a pending review candidate is rejected, no records are written to any store."""
    source_event_id = "turn_reject_test"
    user_msg = "Maybe we should remember something uncertain."
    ai_resp = "I have noted it for review."

    mock_output = MemoryCuratorOutput(
        schema_version=1,
        should_learn=True,
        memories=[
            MemoryCandidate(
                kind="fact",
                content="Uncertain speculative assertion.",
                confidence=0.5,
                evidence_refs=[user_msg],
            )
        ],
        entities=[
            EntityCandidate(
                temporary_id="e1",
                name="Speculative Concept",
                kind="concept",
                confidence=0.5,
                evidence_refs=[user_msg],
            )
        ],
        relationships=[],
        requires_review=True,
    )

    with patch.object(MemoryCuratorService, "extract", new=AsyncMock(return_value=mock_output)):
        async with SessionLocal() as session:
            event = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id=source_event_id,
                user_message=user_msg,
                ai_response=ai_resp,
                override_enabled_check=True,
            )
            assert event.status == "review_required"

            rejected = await LearningCoordinator.reject_event(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                event_id=event.id,
            )
            assert rejected.status == "rejected"

    # Verify ZERO mutations in LadybugDB and SQLite
    entities = await setup_env.find_entities(sample_proj.tenant_id, sample_proj.id)
    assert len(entities) == 0

    async with SessionLocal() as session:
        mems = await MemoryService.list(session, sample_proj.tenant_id, sample_proj.id)
        assert len(mems) == 0


# ============================================================================
# 5. P1 — EVIDENCE AND CONFIDENCE VALIDATION
# ============================================================================


@pytest.mark.asyncio
async def test_evidence_and_confidence_validation(setup_env, sample_proj: Project):
    """Missing evidence, ungrounded evidence, or sensitive credentials must prevent auto-acceptance."""
    # Case A: Missing evidence_refs
    cand_no_evidence = MemoryCandidate(
        kind="preference",
        content="User likes dark theme.",
        confidence=0.95,
        evidence_refs=[],  # Empty!
    )
    mock_output_a = MemoryCuratorOutput(
        schema_version=1,
        should_learn=True,
        memories=[cand_no_evidence],
    )
    with patch.object(MemoryCuratorService, "extract", new=AsyncMock(return_value=mock_output_a)):
        async with SessionLocal() as session:
            ev = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_no_ev",
                user_message="Hello there.",
                ai_response="Hi!",
                override_enabled_check=True,
            )
            assert ev.status == "review_required"
            assert "Missing evidence_refs" in (ev.error or "")

    # Case B: Ungrounded fake evidence not in turn text
    cand_fake_evidence = MemoryCandidate(
        kind="fact",
        content="User owns a yacht.",
        confidence=0.99,
        evidence_refs=["I sail on my yacht every Sunday"],  # Not in user message!
    )
    mock_output_b = MemoryCuratorOutput(
        schema_version=1,
        should_learn=True,
        memories=[cand_fake_evidence],
    )
    with patch.object(MemoryCuratorService, "extract", new=AsyncMock(return_value=mock_output_b)):
        async with SessionLocal() as session:
            ev = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_fake_ev",
                user_message="Can you help me write Python?",
                ai_response="Sure!",
                override_enabled_check=True,
            )
            assert ev.status == "review_required"
            assert "Ungrounded evidence_refs" in (ev.error or "")

    # Case C: Sensitive credential pattern in extracted content
    cand_sensitive = MemoryCandidate(
        kind="fact",
        content="My token is sk-1234567890abcdef1234567890.",
        confidence=0.99,
        evidence_refs=["sk-1234567890abcdef1234567890"],
    )
    mock_output_c = MemoryCuratorOutput(
        schema_version=1,
        should_learn=True,
        memories=[cand_sensitive],
    )
    with patch.object(MemoryCuratorService, "extract", new=AsyncMock(return_value=mock_output_c)):
        async with SessionLocal() as session:
            ev = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_sensitive",
                user_message="Here is my token: sk-1234567890abcdef1234567890",
                ai_response="Received.",
                override_enabled_check=True,
            )
            assert ev.status == "review_required"
            assert "Sensitive credential pattern" in (ev.error or "")


# ============================================================================
# 6. P1 — GRAPH ENTITY IDENTITY, GENERIC LABELS & ALIASES
# ============================================================================


@pytest.mark.asyncio
async def test_graph_entity_identity_generic_labels_and_aliases(setup_env, sample_proj: Project):
    """Generic names (e.g. 'server', 'wife') must not silently merge with existing entities,
    and alias resolution requires explicit canonical aliases."""
    adapter = setup_env

    # Seed an existing generic entity "server"
    ent_server = GraphEntity(
        id="dev_server_1",
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        kind="device",
        name="server",
        canonical_name="server",
        description="First server in living room",
        confidence=1.0,
    )
    await adapter.create_or_update_entity(ent_server)

    # Candidate introduces another "server"
    cand_server = EntityCandidate(
        temporary_id="e_new",
        name="server",
        kind="device",
        confidence=0.9,
        description="Second backup server in attic",
    )

    res = await GraphManagerService.resolve_and_validate(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        candidate_entities=[cand_server],
        candidate_relationships=[],
    )
    # MUST flag ambiguity for review rather than auto-merging!
    assert res["requires_review"] is True
    assert any("Ambiguous generic entity label" in r for r in res["review_reasons"])

    # Alias resolution: test explicit alias vs arbitrary substring
    ent_laptop = GraphEntity(
        id="dev_laptop_1",
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        kind="device",
        name="MacBook Pro",
        canonical_name="macbook pro",
        description="Development machine [aliases: mbp, work-laptop]",
        confidence=1.0,
    )
    await adapter.create_or_update_entity(ent_laptop)

    # Alias candidate matching exact alias "mbp"
    cand_alias = EntityCandidate(
        temporary_id="e_mbp",
        name="mbp",
        kind="device",
        confidence=0.95,
    )
    res_alias = await GraphManagerService.resolve_and_validate(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        candidate_entities=[cand_alias],
        candidate_relationships=[],
    )
    # Exact alias resolves to dev_laptop_1
    assert res_alias["resolved_entities"][0].id == "dev_laptop_1"

    # 4. Unknown edge kind triggers human review
    cand_rel_unknown = RelationshipCandidate(
        source_ref="e_mbp",
        target_ref="dev_server_1",
        kind="HOSTS_BACKUP_ON",
        confidence=0.9,
    )
    res_edge = await GraphManagerService.resolve_and_validate(
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        candidate_entities=[cand_alias],
        candidate_relationships=[cand_rel_unknown],
    )
    assert res_edge["requires_review"] is True
    assert any("Unknown relationship kind 'HOSTS_BACKUP_ON'" in r for r in res_edge["review_reasons"])
    # Normalized kind is safely staged as RELATES_TO pending review
    assert res_edge["resolved_relationships"][0].kind == "RELATES_TO"


# ============================================================================
# 7. P1 — CROSS-STORE CORRECTION & GRAPH RELATIONSHIP INVALIDATION
# ============================================================================


@pytest.mark.asyncio
async def test_cross_store_graph_correction_and_shared_provenance(setup_env, memory_dir: Path, sample_proj: Project):
    """When a memory is deleted, exclusive graph relationships are invalidated,
    while shared entities and manual graph knowledge are strictly preserved."""
    adapter = setup_env
    source_ref = "turn:turn_shared_prov"

    # Create two entities in LadybugDB
    ent1 = GraphEntity(
        id="ent_mac",
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        kind="device",
        name="Mac mini",
        canonical_name="mac mini",
        source="manual",
    )
    ent2 = GraphEntity(
        id="ent_ollama",
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        kind="application",
        name="Ollama",
        canonical_name="ollama",
        source="manual",
    )
    await adapter.create_or_update_entity(ent1)
    await adapter.create_or_update_entity(ent2)

    # Create a relationship associated with the learned memory source_ref
    rel_id = make_relationship_id("ent_mac", "RUNS", "ent_ollama")
    rel = GraphRelationship(
        id=rel_id,
        source_id="ent_mac",
        target_id="ent_ollama",
        kind="RUNS",
        tenant_id=sample_proj.tenant_id,
        project_id=sample_proj.id,
        source=source_ref,
    )
    await adapter.create_or_update_relationship(rel)

    # Store corresponding memory in SQLite
    async with SessionLocal() as session:
        saved_mem = await MemoryService.remember(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="Mac mini runs Ollama.",
            kind="technology",
            source_ref=source_ref,
            status="active",
        )
        mem_id = saved_mem.id

    # Verify relationship exists before delete
    rels_before = await adapter.get_relationships(sample_proj.tenant_id, sample_proj.id, "ent_mac", direction="out")
    assert len(rels_before) == 1

    # Delete memory through UnifiedMemoryManager
    async with SessionLocal() as session:
        deleted = await UnifiedMemoryManager.delete_memory(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            memory_id=mem_id,
        )
        assert deleted is True

    # VERIFY: Relationship supported solely by this memory was removed!
    rels_after = await adapter.get_relationships(sample_proj.tenant_id, sample_proj.id, "ent_mac", direction="out")
    assert len(rels_after) == 0

    # VERIFY: Manual entities are PRESERVED!
    ent_mac_check = await adapter.get_entity(sample_proj.tenant_id, sample_proj.id, "ent_mac")
    assert ent_mac_check is not None
    ent_ollama_check = await adapter.get_entity(sample_proj.tenant_id, sample_proj.id, "ent_ollama")
    assert ent_ollama_check is not None


# ============================================================================
# 8. P1 — LEARNING SETTINGS PERSISTENCE & SCOPE ISOLATION
# ============================================================================


@pytest.mark.asyncio
async def test_learning_settings_persistence_and_tenant_isolation(setup_env):
    """Project-level learning toggle persists in Project.config and respects tenant/project boundaries."""
    async with SessionLocal() as session:
        # Create Project A
        proj_a = await ProjectService.create(session, tenant_id="tenant-iso-1", name="Proj A", slug="proj-a")
        # Create Project B
        proj_b = await ProjectService.create(session, tenant_id="tenant-iso-2", name="Proj B", slug="proj-b")
        proj_a_id = proj_a.id
        proj_a_tenant = proj_a.tenant_id
        proj_b_id = proj_b.id
        proj_b_tenant = proj_b.tenant_id

        # Enable learning on Proj A only
        pcfg_a = dict(proj_a.config or {})
        pcfg_a["memory_learning_enabled"] = True
        proj_a.config = pcfg_a
        await session.commit()

        # Verify Proj A has learning enabled
        is_a_enabled = await LearningCoordinator.is_learning_enabled(session, proj_a_tenant, proj_a_id)
        assert is_a_enabled is True

        # Verify Proj B has learning DISABLED (default fallback, no bleeding)
        is_b_enabled = await LearningCoordinator.is_learning_enabled(session, proj_b_tenant, proj_b_id)
        assert is_b_enabled is False

        # Simulate restart: reload Proj A from DB and check persisted setting
        session.expire_all()
        reloaded_a = (
            await session.execute(select(Project).where(Project.id == proj_a_id))
        ).scalar_one()
        assert reloaded_a.config.get("memory_learning_enabled") is True


# ============================================================================
# 9. P1 — REAL CHAT MEMORY RECALL IN CONTEXT
# ============================================================================


@pytest.mark.asyncio
async def test_end_to_end_chat_memory_recall(setup_env, sample_proj: Project):
    """End-to-end verification:
    1. Remember durable fact.
    2. MemoryRecallMiddleware intercepts conversation query.
    3. Retrieved memory is included in model context (system_message).
    4. Deleting memory removes it from future context."""
    # Step 1: Store memory
    async with SessionLocal() as session:
        mem = await MemoryService.remember(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            text="User's primary coding editor is Neovim.",
            kind="preference",
            status="active",
        )
        mem_id = mem.id

    # Step 2: Simulate chat turn asking about editor
    mw = MemoryRecallMiddleware(tenant_id=sample_proj.tenant_id, project_id=sample_proj.id)

    captured_request = {}

    async def mock_handler(request):
        captured_request["system_message"] = request.system_message
        captured_request["messages"] = request.messages
        return MagicMock(content="You use Neovim!")

    mock_req = MagicMock()
    mock_req.messages = [HumanMessage(content="What editor do I prefer for coding?")]
    mock_req.system_message = SystemMessage(content="You are Alberto Home Butler.")
    mock_req.system_prompt = "You are Alberto Home Butler."

    def fake_override(**kwargs):
        new_req = MagicMock()
        new_req.messages = mock_req.messages
        new_req.system_message = kwargs.get("system_message", mock_req.system_message)
        return new_req

    mock_req.override.side_effect = fake_override

    # Step 3: Run model call through middleware
    await mw.awrap_model_call(mock_req, mock_handler)

    # Step 4: Verify context inclusion
    injected_sys = captured_request.get("system_message")
    assert injected_sys is not None
    assert "[RECALLED MEMORY & KNOWLEDGE CONTEXT]" in injected_sys.content
    assert "Neovim" in injected_sys.content

    # Step 5: Delete memory
    async with SessionLocal() as session:
        await UnifiedMemoryManager.delete_memory(
            session=session,
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            memory_id=mem_id,
        )

    # Step 6: Next turn asking the same query must NOT include deleted memory
    captured_request.clear()
    await mw.awrap_model_call(mock_req, mock_handler)
    injected_sys_after = captured_request.get("system_message")
    assert "Neovim" not in (injected_sys_after.content if injected_sys_after else "")


# ============================================================================
# 10. P1 — LOCAL LLM TIMEOUT & MALFORMED JSON FAILURE
# ============================================================================


@pytest.mark.asyncio
async def test_local_llm_timeout_and_malformed_json_failure(setup_env, sample_proj: Project):
    """Timeouts and malformed JSON must fail safely with recorded error,
    increment retry count, and NEVER be reported as successful learning."""
    # Case A: Timeout
    async def slow_extract(*args, **kwargs):
        await asyncio.sleep(0.5)
        return MemoryCuratorOutput(should_learn=False)

    with patch.object(settings, "memory_learning_timeout_seconds", 0.05), patch.object(
        MemoryCuratorService, "extract", side_effect=slow_extract
    ):
        await LearningCoordinator._safe_run_turn_learning(
            tenant_id=sample_proj.tenant_id,
            project_id=sample_proj.id,
            source_event_id="turn_timeout_test",
            user_message="Tell me something long.",
            ai_response="Sure.",
        )

    async with SessionLocal() as session:
        ev_timeout = (
            await session.execute(
                select(MemoryLearningEvent).where(
                    MemoryLearningEvent.source_event_id == "turn_timeout_test"
                )
            )
        ).scalar_one_or_none()
        assert ev_timeout is not None
        assert ev_timeout.status == "failed"
        assert "timed out" in (ev_timeout.error or "").lower()
        assert ev_timeout.retry_count == 1

    # Case B: Malformed JSON output
    mock_bad_model = MagicMock()
    mock_bad_model.ainvoke = AsyncMock(return_value=MagicMock(content="This is not JSON at all! {broken}"))

    with patch.object(MemoryCuratorService, "get_curator_model", return_value=(mock_bad_model, "bad-model")):
        async with SessionLocal() as session:
            ev_json = await LearningCoordinator.process_learning_turn(
                session=session,
                tenant_id=sample_proj.tenant_id,
                project_id=sample_proj.id,
                source_event_id="turn_bad_json",
                user_message="Remember this fact please.",
                ai_response="I will.",
                override_enabled_check=True,
            )
            assert ev_json.status == "failed"
            assert "json" in (ev_json.error or "").lower()
            assert ev_json.retry_count == 1
