"""Tests for Unified Memory Manager coordinating SQLite, LadybugDB, ChromaDB, and Markdown."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from alberto.db import SessionLocal
from alberto.knowledge.graph import LadybugGraphAdapter, set_graph_adapter
from alberto.models.entities import Project
from alberto.services.projects import ProjectService
from alberto.services.unified_memory import UnifiedMemoryManager


@pytest.fixture
def graph_tmp_dir():
    with tempfile.TemporaryDirectory(prefix="ladybug_mem_") as tmp:
        yield Path(tmp)


@pytest.fixture
async def setup_unified_env(graph_tmp_dir: Path):
    adapter = LadybugGraphAdapter(db_path=graph_tmp_dir)
    await adapter.initialize()
    set_graph_adapter(adapter)
    yield adapter
    adapter.close()
    set_graph_adapter(None)


@pytest.fixture
async def sample_project():
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id="tenant-mem-1",
            name="Memory Project",
            slug="mem-proj-1",
        )
        await session.commit()
        await session.refresh(proj)
        return proj


@pytest.mark.asyncio
async def test_storage_status_across_engines(setup_unified_env, sample_project: Project):
    async with SessionLocal() as session:
        status = await UnifiedMemoryManager.get_storage_status(
            session, sample_project.tenant_id, sample_project.id
        )

        # 1. Learning disabled by default in Milestone 2.0
        assert status["memory_learning_enabled"] is False

        # 2. SQLite status
        assert "sqlite" in status
        assert "memories_count" in status["sqlite"]
        assert "qa_pairs_count" in status["sqlite"]

        # 3. LadybugDB status
        assert status["ladybug_graph"]["available"] is True
        assert status["ladybug_graph"]["entity_count"] == 0

        # 4. ChromaDB status
        assert status["chroma"]["available"] is True

        # 5. Markdown memory status (active writer in Milestone 2.1)
        assert status["markdown"]["status"] in ("planned", "active")
        if status["markdown"]["status"] == "active":
            assert status["markdown"]["active_writer"] is True
        else:
            assert status["markdown"]["active_writer"] is False
            assert status["markdown"]["deferred_milestone"] == "2.1"


@pytest.mark.asyncio
async def test_unified_remember_and_recall(setup_unified_env, sample_project: Project):
    async with SessionLocal() as session:
        # 1. Store structured memory in SQLite
        mem_res = await UnifiedMemoryManager.remember(
            session,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            text="User prefers temperature set to 21 degrees.",
            target="memory",
            kind="preference",
        )
        assert mem_res["target"] == "memory"
        assert "id" in mem_res

        # 2. Store entity in LadybugDB Knowledge Graph
        graph_res = await UnifiedMemoryManager.remember(
            session,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            text="Smart Living Room Thermostat",
            target="graph",
            entity_kind="Device",
            entity_name="Living Room Thermostat",
        )
        assert graph_res["target"] == "graph"
        assert graph_res["kind"] == "Device"

        # 3. Unified recall across sources
        results = await UnifiedMemoryManager.recall(
            session,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            query="thermostat temperature",
            sources=["memory", "graph"],
        )
        assert len(results) >= 1
        sources = {r.source for r in results}
        assert any(s in sources for s in ("sqlite_memory", "chroma_memory", "ladybug_graph", "memory", "graph"))

        # 4. Tenant isolation: foreign tenant recall returns zero
        foreign_results = await UnifiedMemoryManager.recall(
            session,
            tenant_id="foreign-tenant-999",
            project_id="foreign-proj-999",
            query="temperature",
            sources=["memory", "graph"],
        )
        assert len(foreign_results) == 0


@pytest.mark.asyncio
async def test_unified_recall_graph_standalone(setup_unified_env, sample_project: Project):
    async with SessionLocal() as session:
        # Store entity in LadybugDB
        await UnifiedMemoryManager.remember(
            session,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            text="High efficiency HVAC unit installed in master bedroom.",
            target="graph",
            entity_kind="Appliance",
            entity_name="HVAC Unit",
        )

        # Recall specifically from graph source
        results = await UnifiedMemoryManager.recall(
            session,
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            query="HVAC Unit",
            sources=["graph"],
        )
        assert len(results) == 1
        assert results[0].source == "ladybug_graph"
        assert "HVAC Unit" in results[0].content
        assert results[0].metadata is not None
        assert results[0].metadata["kind"] == "Appliance"


@pytest.mark.asyncio
async def test_unified_recall_qa_and_knowledge_sources(setup_unified_env, sample_project: Project):
    """P1 TEST:
    Verify UnifiedMemoryManager.recall supports curated Q&A pairs and document RAG
    with proper source attribution and distinct scores.
    """
    from unittest.mock import AsyncMock, patch

    from alberto.knowledge.store import Hit
    from alberto.services.knowledge import KnowledgeService

    async with SessionLocal() as session:
        mock_qa = [
            {"question": "How do I set the thermostat?", "answer": "Use the dial on wall.", "score": 0.88, "kind": "faq"}
        ]
        mock_hit = [
            Hit(
                id="doc_chunk_123",
                text="Thermostat user manual page 4: rotate clockwise to increase temperature.",
                score=0.92,
                metadata={"source_id": "src_manual_1", "embedding_model": "test"},
            )
        ]

        with (
            patch.object(KnowledgeService, "top_qa", new=AsyncMock(return_value=mock_qa)),
            patch.object(KnowledgeService, "search", new=AsyncMock(return_value=mock_hit)),
        ):
            # 1. Recall with sources=["qa"]
            qa_results = await UnifiedMemoryManager.recall(
                session, sample_project.tenant_id, sample_project.id, "thermostat", sources=["qa"]
            )
            assert len(qa_results) == 1
            assert qa_results[0].source == "qa_pairs"
            assert qa_results[0].score == 0.88
            assert "Use the dial on wall" in qa_results[0].content
            assert qa_results[0].provenance == "curated_qa"

            # 2. Recall with sources=["knowledge"]
            doc_results = await UnifiedMemoryManager.recall(
                session, sample_project.tenant_id, sample_project.id, "thermostat", sources=["knowledge"]
            )
            assert len(doc_results) == 1
            assert doc_results[0].source == "knowledge_docs"
            assert doc_results[0].score == 0.92
            assert "rotate clockwise" in doc_results[0].content
            assert doc_results[0].provenance == "document_rag:src_manual_1"

            # 3. Multi-source recall with source attribution
            multi_results = await UnifiedMemoryManager.recall(
                session, sample_project.tenant_id, sample_project.id, "thermostat", sources=["qa", "knowledge"]
            )
            assert len(multi_results) == 2
            sources = {r.source for r in multi_results}
            assert sources == {"qa_pairs", "knowledge_docs"}

