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

            # Direct SQLite fallback if vector store yields no hits or is unavailable
            if not any(r.source == "chroma_memory" for r in results):
                try:
                    all_active = await MemoryService.list(session, tenant_id, project_id, status="active")
                    query_lower = query.lower()
                    query_words = {w for w in query_lower.split() if len(w) > 2}
                    for mem in all_active:
                        mem_lower = mem.text.lower()
                        mem_words = set(mem_lower.split())
                        if (query_words & mem_words) or (mem_lower in query_lower) or (query_lower in mem_lower):
                            results.append(
                                UnifiedMemoryRecord(
                                    source="sqlite_memory",
                                    record_id=mem.id,
                                    content=mem.text,
                                    metadata={"scope": mem.scope, "kind": mem.kind},
                                    provenance=mem.provenance,
                                )
                            )
                            if len(results) >= top_k:
                                break
                except Exception as e:
                    logger.warning("SQLite memory fallback recall error: %s", e)

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

        # 5. Markdown memory retrieval
        if "markdown" in enabled_sources or "notes" in enabled_sources:
            try:
                from alberto.services.markdown_memory import MarkdownMemoryService

                files = MarkdownMemoryService.list_files(tenant_id, project_id)
                q_lower = query.lower()
                for f_info in files:
                    content = MarkdownMemoryService.read_file(tenant_id, project_id, f_info["filename"])
                    if not content:
                        continue
                    for line in content.splitlines():
                        if line.startswith("- [mem:") and (q_lower in line.lower() or any(w in line.lower() for w in q_lower.split() if len(w) > 3)):
                            clean_text = line.lstrip("- ").strip()
                            results.append(
                                UnifiedMemoryRecord(
                                    source="markdown_memory",
                                    record_id=f"md_{f_info['filename']}",
                                    content=clean_text,
                                    score=0.9,
                                    metadata={"filename": f_info["filename"], "category": f_info["category"]},
                                    provenance=f"markdown:{f_info['filename']}",
                                )
                            )
                            if len(results) >= top_k * 2:
                                break
            except Exception as e:
                logger.warning("Markdown memory recall error: %s", e)

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
        confidence: float = 1.0,
        provenance: str = "manual",
        status: str = "active",
        entity_kind: str = "concept",
        entity_name: str | None = None,
    ) -> dict[str, Any]:
        """Deterministic explicit storage routing."""
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
                source=provenance,
                confidence=confidence,
            )
            saved = await adapter.create_or_update_entity(entity)
            return {"target": "graph", "id": saved.id, "kind": saved.kind, "name": saved.name}

        # Default target: SQLite long-term memory + ChromaDB + Markdown
        m = await MemoryService.remember(
            session,
            tenant_id,
            project_id,
            text,
            scope=scope,
            kind=kind,
            confidence=confidence,
            provenance=provenance,
            status=status,
        )

        # Sync into persistent Markdown memory
        try:
            from alberto.services.markdown_memory import MarkdownMemoryService

            MarkdownMemoryService.sync_memory(
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=m.id,
                text=m.text,
                kind=m.kind,
                confidence=m.confidence,
                status=m.status,
            )
        except Exception as e:
            logger.warning("Markdown memory sync warning: %s", e)

        return {"target": "memory", "id": m.id, "scope": m.scope, "text": m.text, "status": m.status}

    @staticmethod
    async def list_memories(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        *,
        scope: str | None = None,
        status: str | None = "active",
        kind: str | None = None,
    ) -> list[Memory]:
        """List authoritative memories with filtering."""
        return await MemoryService.list(
            session, tenant_id, project_id, scope=scope, status=status, kind=kind
        )

    @staticmethod
    async def get_memory(
        session: AsyncSession, tenant_id: str, project_id: str, memory_id: str
    ) -> Memory | None:
        """Get an authoritative memory record by ID."""
        return await MemoryService.get(session, tenant_id, project_id, memory_id)

    @staticmethod
    async def update_memory(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        memory_id: str,
        *,
        text: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        confidence: float | None = None,
    ) -> Memory | None:
        """Update/correct an authoritative memory and sync projections."""
        m = await MemoryService.update(
            session,
            tenant_id,
            project_id,
            memory_id,
            text=text,
            kind=kind,
            status=status,
            confidence=confidence,
        )
        if m:
            try:
                from alberto.services.markdown_memory import MarkdownMemoryService

                MarkdownMemoryService.sync_memory(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    memory_id=m.id,
                    text=m.text,
                    kind=m.kind,
                    confidence=m.confidence,
                    status=m.status,
                )
            except Exception as e:
                logger.warning("Markdown memory sync warning on update: %s", e)
        return m

    @staticmethod
    async def delete_memory(
        session: AsyncSession, tenant_id: str, project_id: str, memory_id: str
    ) -> bool:
        """Delete an authoritative memory, updating Chroma, Markdown, and LadybugDB."""
        m = await MemoryService.get(session, tenant_id, project_id, memory_id)
        if not m:
            return False
        kind = m.kind
        source_ref = m.source_ref
        deleted = await MemoryService.delete(session, tenant_id, project_id, memory_id)
        if deleted:
            try:
                from alberto.services.markdown_memory import MarkdownMemoryService

                MarkdownMemoryService.remove_memory(tenant_id, project_id, memory_id, kind=kind)
            except Exception as e:
                logger.warning("Markdown memory removal warning: %s", e)

            # Invalidate graph relationships supported exclusively by this memory's source_ref
            if source_ref and source_ref != "manual":
                try:
                    # Check if any other active memory still shares this source_ref
                    other_active = (
                        await session.execute(
                            select(Memory).where(
                                Memory.tenant_id == tenant_id,
                                Memory.project_id == project_id,
                                Memory.source_ref == source_ref,
                                Memory.status == "active",
                            )
                        )
                    ).scalars().first()

                    if not other_active:
                        adapter = get_graph_adapter()
                        res = adapter._execute(
                            """
                            MATCH ()-[r:RelatesTo]->()
                            WHERE r.tenant_id = $tenant_id AND r.project_id = $project_id AND r.source = $source
                            RETURN r.id
                            """,
                            {"tenant_id": tenant_id, "project_id": project_id, "source": source_ref},
                        )
                        rel_ids_to_delete = []
                        while res.has_next():
                            rel_ids_to_delete.append(res.get_next()[0])

                        for r_id in rel_ids_to_delete:
                            await adapter.delete_relationship(tenant_id, project_id, r_id)
                except Exception as e:
                    logger.warning("Graph relationship cleanup warning on delete: %s", e)

        return deleted

    @staticmethod
    async def get_learning_events(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        *,
        status: str | None = None,
    ) -> list[Any]:
        """List learning events for this project scope."""
        from alberto.models import MemoryLearningEvent

        q = select(MemoryLearningEvent).where(
            MemoryLearningEvent.tenant_id == tenant_id,
            MemoryLearningEvent.project_id == project_id,
        )
        if status:
            q = q.where(MemoryLearningEvent.status == status)
        res = await session.execute(q.order_by(MemoryLearningEvent.created_at.desc()))
        return list(res.scalars())

    @staticmethod
    async def approve_learning_event(
        session: AsyncSession, tenant_id: str, project_id: str, event_id: str
    ) -> Any | None:
        """Approve pending learning candidates in a review_required event."""
        from alberto.services.learning_coordinator import LearningCoordinator

        return await LearningCoordinator.approve_event(session, tenant_id, project_id, event_id)

    @staticmethod
    async def reject_learning_event(
        session: AsyncSession, tenant_id: str, project_id: str, event_id: str
    ) -> Any | None:
        """Reject pending learning candidates."""
        from alberto.services.learning_coordinator import LearningCoordinator

        return await LearningCoordinator.reject_event(session, tenant_id, project_id, event_id)

    @staticmethod
    def list_markdown_files(tenant_id: str, project_id: str) -> list[dict[str, Any]]:
        """List Markdown memory files in project scope."""
        from alberto.services.markdown_memory import MarkdownMemoryService

        return MarkdownMemoryService.list_files(tenant_id, project_id)

    @staticmethod
    def get_markdown_file(tenant_id: str, project_id: str, filename: str) -> str | None:
        """Read content of a Markdown memory file."""
        from alberto.services.markdown_memory import MarkdownMemoryService

        return MarkdownMemoryService.read_file(tenant_id, project_id, filename)

    @staticmethod
    async def get_storage_status(
        session: AsyncSession, tenant_id: str, project_id: str
    ) -> dict[str, Any]:
        """Inspect storage status across all four target memory systems."""
        # 1. SQLite
        mem_raw = await session.scalar(
            select(func.count()).select_from(Memory).where(
                Memory.tenant_id == tenant_id,
                Memory.project_id == project_id,
                Memory.status == "active",
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

        # 4. Markdown memory (Active Writer in Milestone 2.1)
        from alberto.services.markdown_memory import MarkdownMemoryService

        markdown_dir = settings.data_dir / "memory"
        md_files = MarkdownMemoryService.list_files(tenant_id, project_id)
        markdown_status = {
            "status": "active",
            "active_writer": True,
            "path": str(markdown_dir),
            "directory_exists": markdown_dir.exists(),
            "file_count": len(md_files),
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
