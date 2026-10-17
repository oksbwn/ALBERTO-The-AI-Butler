"""Unified Memory Manager: Lightweight facade coordinating SQLite, Markdown, ChromaDB, and LadybugDB.

Responsibilities:
- Unified memory retrieval with source identification and consistent metadata.
- Deterministic explicit storage routing (SQLite memory or LadybugDB graph).
- Status inspection across all 4 memory storage layers.
- Strict milestone boundaries: Automatic LLM extraction and learning remain disabled until Milestone 2.1.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.config import settings
from alberto.knowledge.graph import GraphEntity, get_graph_adapter, make_entity_id
from alberto.models import Memory, QaPair
from alberto.services.knowledge import KnowledgeService
from alberto.services.memory import MemoryService

logger = logging.getLogger("alberto.services.unified_memory")


@dataclass
class UnifiedMemoryRecord:
    source: str
    record_id: str
    content: str
    score: float | None = None
    metadata: dict[str, Any] | None = None
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StorageLayerStatus:
    name: str
    status: str
    record_count: int
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UnifiedMemoryManager:
    """Coordinates Alberto's 4 memory storage engines."""

    @staticmethod
    async def recall(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        query: str,
        *,
        sources: list[str] | None = None,
        scope: str = "default",
        top_k: int = 5,
    ) -> list[UnifiedMemoryRecord]:
        """Unified memory retrieval across active stores (SQLite, Chroma, LadybugDB).
        Scores are source-specific and kept distinct with source attribution."""
        enabled_sources = set(sources or ["memory", "graph"])
        results: list[UnifiedMemoryRecord] = []

        # 1. SQLite + Chroma persistent long-term memories
        if "memory" in enabled_sources or "sqlite" in enabled_sources:
            try:
                # Semantic recall via Chroma-backed MemoryService
                mem_texts = await MemoryService.recall(
                    session, tenant_id, project_id, query, scope=scope, top_k=top_k
                )
                for i, text in enumerate(mem_texts):
                    results.append(
                        UnifiedMemoryRecord(
                            source="chroma_memory",
                            record_id=f"mem_hit_{i}",
                            content=text,
                            metadata={"scope": scope},
                            provenance="semantic_recall",
                        )
                    )
            except Exception as e:
                logger.warning("MemoryService recall error: %s", e)

        # 2. LadybugDB Knowledge Graph
        if "graph" in enabled_sources or "ladybug" in enabled_sources:
            try:
                adapter = get_graph_adapter()
                # Find entities whose name or description matches query terms
                entities = await adapter.find_entities(tenant_id, project_id, limit=top_k * 2)
                query_lower = query.lower()
                for ent in entities:
                    if (
                        ent.name.lower() in query_lower
                        or query_lower in ent.name.lower()
                        or (ent.description and query_lower in ent.description.lower())
                    ):
                        results.append(
                            UnifiedMemoryRecord(
                                source="ladybug_graph",
                                record_id=ent.id,
                                content=f"Entity [{ent.kind}] {ent.name}: {ent.description}".strip(),
                                score=ent.confidence,
                                metadata={
                                    "kind": ent.kind,
                                    "name": ent.name,
                                    "canonical_name": ent.canonical_name,
                                },
                                provenance=ent.source,
                            )
                        )
                        if len(results) >= top_k * 2:
                            break
            except Exception as e:
                logger.warning("LadybugGraphAdapter recall error: %s", e)

        # 3. Curated Q&A pairs
        if "qa" in enabled_sources or "faq" in enabled_sources or "qa_pairs" in enabled_sources:
            try:
                qa_hits = await KnowledgeService.top_qa(
                    session, tenant_id, project_id, query, top_k=top_k
                )
                for i, qa in enumerate(qa_hits):
                    results.append(
                        UnifiedMemoryRecord(
                            source="qa_pairs",
                            record_id=f"qa_hit_{i}",
                            content=f"Q: {qa.get('question', '')}\nA: {qa.get('answer', '')}",
                            score=qa.get("score"),
                            metadata={
                                "kind": qa.get("kind"),
                                "question": qa.get("question"),
                                "answer": qa.get("answer"),
                            },
                            provenance="curated_qa",
                        )
                    )
            except Exception as e:
                logger.warning("KnowledgeService top_qa error: %s", e)

        # 4. Existing document / RAG retrieval
        if (
            "knowledge" in enabled_sources
            or "documents" in enabled_sources
            or "document" in enabled_sources
            or "rag" in enabled_sources
        ):
            try:
                doc_hits = await KnowledgeService.search(
                    session, tenant_id, project_id, query, top_k=top_k
                )
                for hit in doc_hits:
                    meta = hit.metadata or {}
                    source_id = meta.get("source_id", "unknown")
                    results.append(
                        UnifiedMemoryRecord(
                            source="knowledge_docs",
                            record_id=hit.id,
                            content=hit.text,
                            score=hit.score,
                            metadata=meta,
                            provenance=f"document_rag:{source_id}",
                        )
                    )
            except Exception as e:
                logger.warning("KnowledgeService search error: %s", e)

        max_allowed = top_k if len(enabled_sources) == 1 else top_k * len(enabled_sources)
        return results[:max_allowed]

    @staticmethod
    async def remember(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        text: str,
        *,
        target: str = "memory",
        scope: str = "default",
        kind: str = "note",
        entity_kind: str = "concept",
        entity_name: str | None = None,
    ) -> dict[str, Any]:
        """Explicit deterministic storage routing.
        No automated LLM extraction occurs in Milestone 2.0."""
        if target == "graph":
            adapter = get_graph_adapter()
            name = entity_name or text[:40].strip()
            entity_id = make_entity_id(entity_kind, name)
            entity = GraphEntity(
                id=entity_id,
                tenant_id=tenant_id,
                project_id=project_id,
                kind=entity_kind,
                name=name,
                canonical_name=name.lower(),
                description=text,
                source="manual",
                confidence=1.0,
            )
            saved = await adapter.create_or_update_entity(entity)
            return {"target": "graph", "id": saved.id, "kind": saved.kind, "name": saved.name}

        # Default target: SQLite long-term memory
        m = await MemoryService.remember(
            session, tenant_id, project_id, text, scope=scope, kind=kind
        )
        return {"target": "memory", "id": m.id, "scope": m.scope, "text": m.text}

    @staticmethod
    async def get_storage_status(
        session: AsyncSession, tenant_id: str, project_id: str
    ) -> dict[str, Any]:
        """Inspect storage status across all four target memory systems."""
        # 1. SQLite
        mem_raw = await session.scalar(
            select(func.count()).select_from(Memory).where(
                Memory.tenant_id == tenant_id, Memory.project_id == project_id
            )
        )
        qa_raw = await session.scalar(
            select(func.count()).select_from(QaPair).where(
                QaPair.tenant_id == tenant_id, QaPair.project_id == project_id
            )
        )
        mem_count = mem_raw or 0
        qa_count = qa_raw or 0

        # 2. LadybugDB
        graph_stats: dict[str, Any] = {"available": False, "entity_count": 0, "relationship_count": 0}
        try:
            adapter = get_graph_adapter()
            stats = await adapter.get_stats(tenant_id, project_id)
            graph_stats = {
                "available": True,
                "entity_count": stats.entity_count,
                "relationship_count": stats.relationship_count,
                "path": stats.storage_path,
            }
        except Exception as e:
            graph_stats["error"] = str(e)

        # 3. ChromaDB
        chroma_status = {
            "available": True,
            "path": settings.chroma_path,
        }

        # 4. Markdown memory
        markdown_dir = settings.data_dir / "memory"
        markdown_status = {
            "status": "planned",
            "active_writer": False,
            "deferred_milestone": "2.1",
            "path": str(markdown_dir),
            "directory_exists": markdown_dir.exists(),
        }

        return {
            "memory_learning_enabled": settings.memory_learning_enabled,
            "sqlite": {
                "status": "active",
                "memories_count": mem_count,
                "memory_count": mem_count,
                "qa_pairs_count": qa_count,
                "qa_count": qa_count,
            },
            "ladybug_graph": graph_stats,
            "chroma": chroma_status,
            "markdown": markdown_status,
        }
