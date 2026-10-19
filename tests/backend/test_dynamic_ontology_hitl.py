"""Comprehensive tests for Alberto Dynamic Knowledge Graph Ontology,
Human-in-the-Loop (HITL) Approval, and Memory Curator Advisory Suggestions.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alberto.db import SessionLocal
from alberto.knowledge.graph import LadybugGraphAdapter, set_graph_adapter
from alberto.models import MemoryLearningEvent
from alberto.models.entities import Project
from alberto.schemas.memory_curator import (
    EdgeApprovalEdit,
    EntityCandidate,
    LearningEventApprovalIn,
    MemoryCandidate,
    MemoryCuratorOutput,
    NodeApprovalEdit,
    RelationshipCandidate,
)
from alberto.services.graph_manager import GraphManagerService
from alberto.services.learning_coordinator import LearningCoordinator
from alberto.services.memory_curator import MemoryCuratorService
from alberto.services.ontology_registry import OntologyRegistryService
from alberto.services.projects import ProjectService


@pytest.fixture
def graph_dir():
    with tempfile.TemporaryDirectory(prefix="ladybug_dyn_ont_") as tmp:
        yield Path(tmp)


@pytest.fixture
async def adapter(graph_dir: Path):
    ad = LadybugGraphAdapter(db_path=graph_dir)
    await ad.initialize()
    set_graph_adapter(ad)
    yield ad
    ad.close()
    set_graph_adapter(None)


@pytest.fixture
async def test_project():
    uid = uuid.uuid4().hex[:8]
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id=f"tenant-dyn-{uid}",
            name=f"Dynamic Project {uid}",
            slug=f"dyn-proj-{uid}",
        )
        pcfg = dict(proj.config or {})
        pcfg["memory_learning_enabled"] = True
        proj.config = pcfg
        await session.commit()
        await session.refresh(proj)
        session.expunge(proj)
        return proj


@pytest.mark.asyncio
async def test_ontology_registry_seed_and_novel_types(test_project, adapter):
    """Test seed definitions, alias resolution, and registering novel types."""
    async with SessionLocal() as session:
        # Ensure seeds initialized
        await OntologyRegistryService.ensure_seed_definitions(
            session=session,
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
        )

        # 1. Verify seed entity types
        ent_types = await OntologyRegistryService.list_entity_types(
            session=session,
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
        )
        canon_ent_keys = {et.canonical_key for et in ent_types}
        assert "operating_system" in canon_ent_keys
        assert "container_runtime" in canon_ent_keys
        assert "inference_framework" in canon_ent_keys

        # 2. Verify seed relationship types
        rel_types = await OntologyRegistryService.list_relationship_types(
            session=session,
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
        )
        canon_rel_keys = {rt.canonical_key for rt in rel_types}
        assert "DEPLOYED_VIA" in canon_rel_keys
        assert "RUNS_ON" in canon_rel_keys

        # 3. Register a novel entity type
        novel_ent = await OntologyRegistryService.register_entity_type(
            session=session,
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
            canonical_key="vector_database",
            display_name="Vector Database",
            description="Database optimized for high-dimensional vector search",
            provenance="test",
        )
        assert novel_ent.canonical_key == "vector_database"

        # 4. Resolve exact and alias
        canon_res, status = await OntologyRegistryService.resolve_entity_type(
            session=session,
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
            raw_kind="vector_database",
        )
        assert canon_res == "vector_database"
        assert status == "approved"

        # 5. Seed entity mappings check
        mapping = await OntologyRegistryService.get_entity_mapping(
            session=session,
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
            entity_name="macOS",
        )
        assert mapping == "operating_system"


@pytest.mark.asyncio
async def test_discovery_unknown_type_flags_review(test_project, adapter):
    """Unknown entity or relationship types must be flagged for review rather than blindly written."""
    cand_entities = [
        EntityCandidate(
            temporary_id="ent:quantum_server",
            name="QuantumServer",
            kind="quantum_compute_cluster",  # novel, unapproved type
            description="Experimental quantum device",
            confidence=0.88,
            evidence_refs=["turn:1"],
        )
    ]
    cand_relationships = []

    val = await GraphManagerService.resolve_and_validate(
        tenant_id=test_project.tenant_id,
        project_id=test_project.id,
        candidate_entities=cand_entities,
        candidate_relationships=cand_relationships,
        source_ref="turn:1",
    )

    assert val["requires_review"] is True
    assert any("quantum_compute_cluster" in r for r in val["review_reasons"])


@pytest.mark.asyncio
async def test_human_approval_with_node_and_edge_edits(test_project, adapter):
    """Reviewer can edit node type, description, edge type, and direction during approval."""
    async with SessionLocal() as session:
        curator_output = MemoryCuratorOutput(
            memories=[
                MemoryCandidate(
                    kind="fact",
                    content="User runs Alberto on Docker.",
                    confidence=0.9,
                    evidence_refs=["turn:dyn-test-1"],
                )
            ],
            entities=[
                EntityCandidate(
                    temporary_id="ent:alberto",
                    name="Alberto",
                    kind="concept",  # Initial proposal: concept
                    description="Personal butler",
                    confidence=0.9,
                    evidence_refs=["turn:dyn-test-1"],
                ),
                EntityCandidate(
                    temporary_id="ent:docker",
                    name="Docker",
                    kind="tool",  # Initial proposal: tool
                    description="Virtualization tool",
                    confidence=0.9,
                    evidence_refs=["turn:dyn-test-1"],
                ),
            ],
            relationships=[
                RelationshipCandidate(
                    source_ref="Docker",
                    target_ref="Alberto",
                    kind="USES",  # Backwards direction: Docker USES Alberto
                    confidence=0.85,
                    evidence_refs=["turn:dyn-test-1"],
                )
            ],
        )

        event = MemoryLearningEvent(
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
            source_event_id="turn:dyn-test-1",
            source_type="chat_turn",
            status="review_required",
            requires_review=True,
            extraction_payload=curator_output.model_dump(),
            error="Ambiguous relationship and broad types.",
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        # Prepare reviewer edits:
        # 1. Edit Alberto to 'application'
        # 2. Edit Docker to 'container_runtime'
        # 3. Edit edge: direction reversed (Alberto -> Docker) and kind changed to 'DEPLOYED_VIA'
        edits = LearningEventApprovalIn(
            node_edits=[
                NodeApprovalEdit(
                    temporary_id="ent:alberto",
                    kind="application",
                    description="Autonomous AI butler application",
                ),
                NodeApprovalEdit(
                    temporary_id="ent:docker",
                    kind="container_runtime",
                    description="Container engine",
                ),
            ],
            edge_edits=[
                EdgeApprovalEdit(
                    source_ref="Docker",
                    target_ref="Alberto",
                    direction="reverse",  # reverse: source Alberto, target Docker
                    kind="DEPLOYED_VIA",
                )
            ],
        )

        approved = await LearningCoordinator.approve_event(
            session=session,
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
            event_id=event.id,
            edits=edits,
        )

        assert approved is not None
        assert approved.status == "completed"
        assert len(approved.applied_graph_entity_ids) == 2
        assert len(approved.applied_graph_rel_ids) == 1

        # Verify persisted graph state in LadybugDB
        alberto_node = await adapter.get_entity(test_project.tenant_id, test_project.id, approved.applied_graph_entity_ids[0])
        docker_node = await adapter.get_entity(test_project.tenant_id, test_project.id, approved.applied_graph_entity_ids[1])
        assert alberto_node is not None
        assert docker_node is not None
        assert alberto_node.kind == "application"
        assert docker_node.kind == "container_runtime"

        # Verify relationship direction and kind
        paths = await adapter.get_neighbors(test_project.tenant_id, test_project.id, alberto_node.id, direction="out")
        assert len(paths) >= 1
        rel = paths[0].relationships[0]
        assert rel is not None
        assert rel.kind == "DEPLOYED_VIA"
        assert rel.source_id == alberto_node.id
        assert rel.target_id == docker_node.id

        # Verify audit history preserved in extraction_payload
        assert "original_proposal" in approved.extraction_payload
        assert "human_edits" in approved.extraction_payload


@pytest.mark.asyncio
async def test_persistent_learning_from_human_correction(test_project, adapter):
    """When a reviewer corrects an entity's type, future resolution uses the learned mapping."""
    async with SessionLocal() as session:
        # Stage event where CustomPlatform is classified as 'device'
        curator_output = MemoryCuratorOutput(
            memories=[],
            entities=[
                EntityCandidate(
                    temporary_id="ent:customplat",
                    name="CustomPlatform",
                    kind="device",  # incorrect classification
                    confidence=0.8,
                    evidence_refs=["turn:dyn-test-learn-1"],
                )
            ],
            relationships=[],
        )

        event = MemoryLearningEvent(
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
            source_event_id="turn:dyn-test-learn-1",
            source_type="chat_turn",
            status="review_required",
            requires_review=True,
            extraction_payload=curator_output.model_dump(),
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        # Human approves and corrects CustomPlatform -> operating_system
        edits = LearningEventApprovalIn(
            node_edits=[
                NodeApprovalEdit(
                    temporary_id="ent:customplat",
                    kind="operating_system",
                )
            ]
        )
        await LearningCoordinator.approve_event(
            session=session,
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
            event_id=event.id,
            edits=edits,
        )

        # Verify ontology registry learned the mapping
        learned = await OntologyRegistryService.get_entity_mapping(
            session=session,
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
            entity_name="CustomPlatform",
        )
        assert learned == "operating_system"

        # On next turn, GraphManagerService resolves CustomPlatform to operating_system automatically
        cand2 = EntityCandidate(
            temporary_id="ent:customplat_next",
            name="CustomPlatform",
            kind="device",
            confidence=0.9,
            evidence_refs=["turn:dyn-test-learn-2"],
        )
        await GraphManagerService.resolve_and_validate(
            tenant_id=test_project.tenant_id,
            project_id=test_project.id,
            candidate_entities=[cand2],
            candidate_relationships=[],
            source_ref="turn:dyn-test-learn-2",
            session=session,
        )
        assert cand2.kind == "operating_system"


@pytest.mark.asyncio
async def test_memory_curator_advisory_suggestion_and_caching(test_project):
    """Memory Curator generates structured advisory suggestions and caches them."""
    mock_llm_json = json.dumps([
        {
            "target_type": "entity",
            "target_ref": "macOS",
            "suggested_kind": "operating_system",
            "explanation": "macOS is an operating system, not hardware.",
            "evidence_refs": ["turn:1"],
            "uncertainty": 0.05,
            "requires_new_ontology_definition": False,
        }
    ])

    mock_model = AsyncMock()
    mock_model.ainvoke.return_value = MagicMock(content=mock_llm_json)

    async with SessionLocal() as session:
        with patch.object(MemoryCuratorService, "get_curator_model", new=AsyncMock(return_value=(mock_model, "mock_model"))):
            cand_ent = EntityCandidate(
                temporary_id="ent:macos",
                name="macOS",
                kind="device",
                confidence=0.8,
                evidence_refs=["turn:1"],
            )

            # First call triggers model
            suggs_1 = await MemoryCuratorService.suggest_review_correction(
                session=session,
                tenant_id=test_project.tenant_id,
                project_id=test_project.id,
                review_reasons=["Potential misclassification."],
                candidate_entities=[cand_ent],
                candidate_relationships=[],
            )

            assert len(suggs_1) == 1
            assert suggs_1[0].suggested_kind == "operating_system"
            assert mock_model.ainvoke.call_count == 1

            # Second call with same parameters hits cache, no second LLM invocation
            suggs_2 = await MemoryCuratorService.suggest_review_correction(
                session=session,
                tenant_id=test_project.tenant_id,
                project_id=test_project.id,
                review_reasons=["Potential misclassification."],
                candidate_entities=[cand_ent],
                candidate_relationships=[],
            )

            assert len(suggs_2) == 1
            assert mock_model.ainvoke.call_count == 1  # Bounded to 1 call!


@pytest.mark.asyncio
async def test_regression_macos_and_olmx_distinct(test_project, adapter):
    """Ensure macOS is not classified as hardware, and OLMX is recognized as application."""
    # macOS entity mapping check
    cand_macos = EntityCandidate(
        temporary_id="ent:macos",
        name="macOS Sequoia",
        kind="hardware",
        confidence=0.9,
        evidence_refs=["turn:1"],
    )
    await GraphManagerService.resolve_and_validate(
        tenant_id=test_project.tenant_id,
        project_id=test_project.id,
        candidate_entities=[cand_macos],
        candidate_relationships=[],
        source_ref="turn:1",
    )
    assert cand_macos.kind == "operating_system"
    assert cand_macos.kind != "hardware"

    # OLMX entity mapping check
    cand_olmx = EntityCandidate(
        temporary_id="ent:olmx",
        name="OLMX",
        kind="unknown_software",
        confidence=0.9,
        evidence_refs=["turn:1"],
    )
    await GraphManagerService.resolve_and_validate(
        tenant_id=test_project.tenant_id,
        project_id=test_project.id,
        candidate_entities=[cand_olmx],
        candidate_relationships=[],
        source_ref="turn:1",
    )
    assert cand_olmx.kind == "application"
