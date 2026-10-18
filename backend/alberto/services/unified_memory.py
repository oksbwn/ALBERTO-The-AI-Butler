"""Unified Memory Manager: Lightweight facade coordinating SQLite, Markdown, ChromaDB, and LadybugDB.

Responsibilities:
- Unified memory retrieval with source identification and consistent metadata.
- Deterministic explicit storage routing (SQLite memory or LadybugDB graph).
- Status inspection across all 4 memory storage layers.
- Strict milestone boundaries: Automatic LLM extraction and learning remain disabled until Milestone 2.1.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.config import settings
from alberto.knowledge.graph import GraphEntity, get_graph_adapter, make_entity_id
from alberto.models import Memory, QaPair
from alberto.services.knowledge import KnowledgeService
from alberto.services.memory import MemoryService
from alberto.services.retrieval_policy import RetrievalPolicy

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


STOP_WORDS = {
    "the", "a", "an", "is", "am", "are", "was", "were", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "their", "our", "mine", "yours", "ours", "myself",
    "which", "what", "where", "when", "why", "how", "who", "whom",
    "this", "that", "these", "those", "for", "with", "at", "by", "from",
    "up", "about", "into", "over", "after", "to", "in", "on", "of", "and", "or",
    "but", "if", "then", "else", "so", "as", "do", "does", "did", "have", "has", "had",
}


def _extract_keywords(text: str) -> set[str]:
    words = re.findall(r"\b[a-zA-Z0-9_\-]+\b", (text or "").lower())
    return {w for w in words if w not in STOP_WORDS and len(w) > 1}


class UnifiedMemoryManager:
    """Coordinates Alberto's 4 memory storage engines."""

    @staticmethod
    async def _fetch_memory(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        query: str,
        scope: str,
        top_k: int,
    ) -> list[UnifiedMemoryRecord]:
        hits: list[UnifiedMemoryRecord] = []
        seen_texts: set[str] = set()

        try:
            mem_texts = await MemoryService.recall(
                session, tenant_id, project_id, query, scope=scope, top_k=top_k
            )
            for i, text in enumerate(mem_texts):
                norm = text.strip().lower()
                seen_texts.add(norm)
                hits.append(
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

        # Keyword and exact entity matching from authoritative SQLite memory
        # Ensures exact technical terms and identifiers are never lost to vector drift or embedding outages
        try:
            all_active = await MemoryService.list(session, tenant_id, project_id, status="active")
            query_lower = query.lower()
            query_words = _extract_keywords(query_lower)

            scored_candidates: list[tuple[float, Memory]] = []
            for mem in all_active:
                mem_lower = mem.text.lower()
                if mem_lower in seen_texts:
                    continue
                mem_words = _extract_keywords(mem_lower)
                overlap = query_words & mem_words
                overlap_score = len(overlap) / max(1, len(query_words)) if query_words else 0.0

                if mem_lower in query_lower or query_lower in mem_lower:
                    overlap_score += 1.0
                if any(w in mem_lower for w in query_words if len(w) >= 3):
                    overlap_score += 0.5

                if overlap_score > 0.0:
                    scored_candidates.append((overlap_score, mem))

            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            for score, mem in scored_candidates:
                if len(hits) >= top_k:
                    break
                seen_texts.add(mem.text.strip().lower())
                hits.append(
                    UnifiedMemoryRecord(
                        source="sqlite_memory",
                        record_id=mem.id,
                        content=mem.text,
                        score=round(score, 3),
                        metadata={"scope": mem.scope, "kind": mem.kind},
                        provenance=mem.provenance,
                    )
                )
        except Exception as e:
            logger.warning("SQLite memory keyword/fallback recall error: %s", e)

        return hits

    @staticmethod
    async def _fetch_graph(
        tenant_id: str,
        project_id: str,
        query: str,
        top_k: int,
    ) -> list[UnifiedMemoryRecord]:
        hits: list[UnifiedMemoryRecord] = []
        try:
            adapter = get_graph_adapter()
            entities = await adapter.find_entities(tenant_id, project_id, limit=top_k * 4)
            query_lower = query.lower()
            query_words = _extract_keywords(query_lower)
            for ent in entities:
                ent_name_lower = ent.name.lower()
                ent_desc_lower = (ent.description or "").lower()
                ent_words = _extract_keywords(f"{ent_name_lower} {ent_desc_lower}")
                if (
                    ent_name_lower in query_lower
                    or query_lower in ent_name_lower
                    or (ent.description and query_lower in ent_desc_lower)
                    or (query_words and (query_words & ent_words))
                ):
                    hits.append(
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
                    if len(hits) >= top_k * 2:
                        break
        except Exception as e:
            logger.warning("LadybugGraphAdapter recall error: %s", e)
        return hits

    @staticmethod
    async def _fetch_qa(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        query: str,
        top_k: int,
    ) -> list[UnifiedMemoryRecord]:
        hits: list[UnifiedMemoryRecord] = []
        try:
            qa_hits = await KnowledgeService.top_qa(
                session, tenant_id, project_id, query, top_k=top_k
            )
            for i, qa in enumerate(qa_hits):
                hits.append(
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
        return hits

    @staticmethod
    async def _fetch_knowledge(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        query: str,
        top_k: int,
    ) -> list[UnifiedMemoryRecord]:
        hits: list[UnifiedMemoryRecord] = []
        try:
            doc_hits = await KnowledgeService.search(
                session, tenant_id, project_id, query, top_k=top_k
            )
            for hit in doc_hits:
                meta = hit.metadata or {}
                source_id = meta.get("source_id", "unknown")
                hits.append(
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
        return hits

    @staticmethod
    async def _fetch_markdown(
        tenant_id: str,
        project_id: str,
        query: str,
        top_k: int,
    ) -> list[UnifiedMemoryRecord]:
        hits: list[UnifiedMemoryRecord] = []
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
                        hits.append(
                            UnifiedMemoryRecord(
                                source="markdown_memory",
                                record_id=f"md_{f_info['filename']}",
                                content=clean_text,
                                score=0.9,
                                metadata={"filename": f_info["filename"], "category": f_info["category"]},
                                provenance=f"markdown:{f_info['filename']}",
                            )
                        )
                        if len(hits) >= top_k * 2:
                            break
        except Exception as e:
            logger.warning("Markdown memory recall error: %s", e)
        return hits

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
        per_source_timeout: float = 4.0,
        overall_timeout: float = 8.0,
    ) -> list[UnifiedMemoryRecord]:
        """Unified memory retrieval across active stores (SQLite, Chroma, LadybugDB).
        Executes independent sources concurrently with per-source timeouts, bounded concurrency,
        staged dependency lookups, and bounded fallback."""
        start_time = time.monotonic()

        # 1. Source selection: respect explicit sources if provided, else apply RetrievalPolicy
        if sources is not None:
            enabled_sources = set(sources)
        else:
            selected = RetrievalPolicy.select_sources(query)
            # If policy returns empty (e.g. general question), return immediately with zero store queries
            if not selected:
                logger.info("Retrieval policy selected 0 sources for query %r (general question)", query[:50])
                return []
            enabled_sources = set(selected)

        logger.info("Executing retrieval for query %r with selected sources: %s", query[:50], list(enabled_sources))

        async def _run_with_timeout(coro, source_name: str) -> list[UnifiedMemoryRecord]:
            try:
                async with asyncio.timeout(per_source_timeout):
                    return await coro
            except TimeoutError:
                logger.warning("Retrieval source %s timed out after %.1fs", source_name, per_source_timeout)
                return []
            except Exception as e:
                logger.warning("Retrieval source %s failed: %s", source_name, e)
                return []

        async def _query_sources(target_sources: set[str]) -> list[UnifiedMemoryRecord]:
            tasks = []
            if "memory" in target_sources or "sqlite" in target_sources:
                tasks.append(_run_with_timeout(
                    UnifiedMemoryManager._fetch_memory(session, tenant_id, project_id, query, scope, top_k),
                    "memory",
                ))
            if "graph" in target_sources or "ladybug" in target_sources:
                tasks.append(_run_with_timeout(
                    UnifiedMemoryManager._fetch_graph(tenant_id, project_id, query, top_k),
                    "graph",
                ))
            if "qa" in target_sources or "faq" in target_sources or "qa_pairs" in target_sources:
                tasks.append(_run_with_timeout(
                    UnifiedMemoryManager._fetch_qa(session, tenant_id, project_id, query, top_k),
                    "qa",
                ))
            if any(s in target_sources for s in ("knowledge", "documents", "document", "rag")):
                tasks.append(_run_with_timeout(
                    UnifiedMemoryManager._fetch_knowledge(session, tenant_id, project_id, query, top_k),
                    "knowledge",
                ))
            if "markdown" in target_sources or "notes" in target_sources:
                tasks.append(_run_with_timeout(
                    UnifiedMemoryManager._fetch_markdown(tenant_id, project_id, query, top_k),
                    "markdown",
                ))

            if not tasks:
                return []

            collected: list[UnifiedMemoryRecord] = []
            try:
                async with asyncio.timeout(overall_timeout):
                    sub_results = await asyncio.gather(*tasks, return_exceptions=True)
                    for res in sub_results:
                        if isinstance(res, list):
                            collected.extend(res)
                        elif isinstance(res, Exception):
                            logger.warning("Error in concurrent source retrieval: %s", res)
            except TimeoutError:
                logger.warning("Overall retrieval timed out after %.1fs; returning partial results", overall_timeout)
            return collected

        # 2. Execute independent sources concurrently
        results = await _query_sources(enabled_sources)

        # 3. Staged dependency check:
        # If graph was queried or query implies entity relations, and memory recall returned entities
        # that graph didn't find directly from the user query text, do a targeted graph lookup.
        if ("graph" in enabled_sources or "ladybug" in enabled_sources) and results:
            graph_hits = [r for r in results if r.source == "ladybug_graph"]
            if not graph_hits:
                # Look for named devices/servers/entities in memory results
                entity_candidates: set[str] = set()
                for r in results:
                    if r.source in ("chroma_memory", "sqlite_memory"):
                        import re
                        words = re.findall(r"\b[A-Z][a-zA-Z0-9_\-\.]{2,}\b", r.content)
                        entity_candidates.update(words)
                for cand in list(entity_candidates)[:3]:
                    staged_hits = await _run_with_timeout(
                        UnifiedMemoryManager._fetch_graph(tenant_id, project_id, cand, top_k=2),
                        f"staged_graph:{cand}",
                    )
                    if staged_hits:
                        results.extend(staged_hits)
                        break

        # 4. Bounded Fallback:
        # If selected sources returned zero results, broaden retrieval using bounded fallback rules
        if not results:
            fallback_sources = set(RetrievalPolicy.get_fallback_sources(list(enabled_sources), 0)) - enabled_sources
            if fallback_sources:
                logger.info("Selected sources returned 0 results; running bounded fallback to: %s", list(fallback_sources))
                fallback_results = await _query_sources(fallback_sources)
                results.extend(fallback_results)

        # 5. Deduplicate results across sources based on content
        deduped: list[UnifiedMemoryRecord] = []
        seen_contents: set[str] = set()
        for r in results:
            clean = r.content.strip().lower()
            if clean and clean not in seen_contents:
                seen_contents.add(clean)
                deduped.append(r)

        elapsed = time.monotonic() - start_time
        max_allowed = top_k if len(enabled_sources) == 1 else top_k * max(1, len(enabled_sources))
        final_results = deduped[:max_allowed]
        logger.info(
            "UnifiedMemoryManager recall completed in %.3fs: %d results (max %d)",
            elapsed, len(final_results), max_allowed,
        )
        return final_results

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

        # Invalidate active per-turn retrieval cache on new memory
        try:
            from alberto.nodes.agent_node import MemoryRecallMiddleware
            MemoryRecallMiddleware.invalidate_cache(tenant_id=tenant_id, project_id=project_id)
        except Exception as e:
            logger.debug("MemoryRecallMiddleware cache invalidation note: %s", e)

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

            # Invalidate active per-turn retrieval cache on memory update
            try:
                from alberto.nodes.agent_node import MemoryRecallMiddleware
                MemoryRecallMiddleware.invalidate_cache(tenant_id=tenant_id, project_id=project_id)
            except Exception as e:
                logger.debug("MemoryRecallMiddleware cache invalidation note: %s", e)
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

            # Invalidate active per-turn retrieval cache
            try:
                from alberto.nodes.agent_node import MemoryRecallMiddleware
                MemoryRecallMiddleware.invalidate_cache(tenant_id=tenant_id, project_id=project_id)
            except Exception as e:
                logger.debug("MemoryRecallMiddleware cache invalidation note: %s", e)

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

        res = await LearningCoordinator.approve_event(session, tenant_id, project_id, event_id)
        try:
            from alberto.nodes.agent_node import MemoryRecallMiddleware
            MemoryRecallMiddleware.invalidate_cache(tenant_id=tenant_id, project_id=project_id)
        except Exception as e:
            logger.debug("MemoryRecallMiddleware cache invalidation note: %s", e)
        return res

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
        from alberto.knowledge.store import get_vector_store_status

        chroma_status = get_vector_store_status(settings.chroma_path)

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

        from alberto.services.learning_coordinator import LearningCoordinator
        learning_enabled = await LearningCoordinator.is_learning_enabled(session, tenant_id, project_id)

        return {
            "memory_learning_enabled": learning_enabled,
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
