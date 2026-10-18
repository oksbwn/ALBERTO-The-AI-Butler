"""MemoryService - persistent long-term memory with semantic recall.

Unlike the per-thread checkpointer (which holds one conversation), memories persist
across threads/channels and are recalled by meaning. Stored in a `memories` row + a
dim-keyed vector collection (`forge_mem_<dim>`); scoped per project (+ optional `scope`
key for per-user/per-conversation memory passed from runtime context).
"""

from __future__ import annotations

from sqlalchemy import select

from alberto.knowledge.store import make_store
from alberto.models import Memory
from alberto.services.knowledge import KnowledgeService


class MemoryService:
    @staticmethod
    def _store(embedder):
        return make_store(collection=f"forge_mem_{embedder.dim}")

    @staticmethod
    async def remember(
        session,
        tenant_id: str,
        project_id: str,
        text: str,
        *,
        scope: str = "default",
        kind: str = "note",
        confidence: float = 1.0,
        provenance: str = "manual",
        status: str = "active",
        source_ref: str | None = None,
        superseded_by: str | None = None,
        meta: dict | None = None,
    ) -> Memory:
        embedder = await KnowledgeService.embedder_for_project(session, tenant_id, project_id)
        emb = await embedder.aembed_query(text)
        m = Memory(
            tenant_id=tenant_id,
            project_id=project_id,
            scope=scope or "default",
            text=text,
            kind=kind,
            confidence=confidence,
            provenance=provenance,
            status=status,
            source_ref=source_ref,
            superseded_by=superseded_by,
            meta=meta or {},
        )
        session.add(m)
        await session.commit()
        await session.refresh(m)
        if status == "active":
            try:
                MemoryService._store(embedder).upsert(
                    ids=[m.id],
                    embeddings=[emb],
                    documents=[text],
                    metadatas=[{
                        "record_id": m.id,
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "scope": m.scope,
                        "kind": m.kind,
                        "status": m.status,
                        "provenance": m.provenance,
                        "source_ref": m.source_ref or "",
                    }],
                )
            except Exception:  # noqa: BLE001 - store unavailable; row still persists
                pass
        return m

    @staticmethod
    async def recall(
        session,
        tenant_id: str,
        project_id: str,
        query: str,
        *,
        scope: str = "default",
        top_k: int = 5,
    ) -> list[str]:
        from alberto.config import settings

        embedder = await KnowledgeService.embedder_for_project(session, tenant_id, project_id)
        emb = await embedder.aembed_query(query)
        # Push tenant_id, project_id, scope, and status=active directly to vector store query
        where = {"$and": [
            {"tenant_id": {"$eq": tenant_id}},
            {"project_id": {"$eq": project_id}},
            {"scope": {"$eq": scope or "default"}},
            {"status": {"$eq": "active"}},
        ]}
        try:
            hits = MemoryService._store(embedder).query_where(embedding=emb, where=where, top_k=top_k * 2)
        except Exception:  # noqa: BLE001
            hits = []

        # Backward compatibility for legacy collections indexed without status metadata
        if not hits:
            legacy_where = {"$and": [
                {"tenant_id": {"$eq": tenant_id}},
                {"project_id": {"$eq": project_id}},
                {"scope": {"$eq": scope or "default"}},
            ]}
            try:
                hits = MemoryService._store(embedder).query_where(embedding=emb, where=legacy_where, top_k=top_k * 2)
            except Exception:  # noqa: BLE001
                hits = []

        # Filter by active status from authoritative SQLite database
        hit_ids = [h.id for h in hits if h.id]
        if not hit_ids:
            return []

        active_rows = await session.execute(
            select(Memory).where(
                Memory.id.in_(hit_ids),
                Memory.tenant_id == tenant_id,
                Memory.project_id == project_id,
                Memory.status == "active",
            )
        )
        active_map = {m.id: m for m in active_rows.scalars()}

        floor = settings.memory_recall_min_score
        results: list[str] = []
        for h in hits:
            if h.id in active_map and h.text and (floor <= 0.0 or h.score >= floor):
                results.append(h.text)
                if len(results) >= top_k:
                    break
        return results

    @staticmethod
    async def get(session, tenant_id: str, project_id: str, memory_id: str) -> Memory | None:
        return (
            await session.execute(
                select(Memory).where(
                    Memory.id == memory_id,
                    Memory.tenant_id == tenant_id,
                    Memory.project_id == project_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def update(
        session,
        tenant_id: str,
        project_id: str,
        memory_id: str,
        *,
        text: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        confidence: float | None = None,
        superseded_by: str | None = None,
    ) -> Memory | None:
        m = await MemoryService.get(session, tenant_id, project_id, memory_id)
        if not m:
            return None

        if text is not None:
            m.text = text
        if kind is not None:
            m.kind = kind
        if status is not None:
            m.status = status
        if confidence is not None:
            m.confidence = confidence
        if superseded_by is not None:
            m.superseded_by = superseded_by

        await session.commit()
        await session.refresh(m)

        try:
            embedder = await KnowledgeService.embedder_for_project(session, tenant_id, project_id)
            store = MemoryService._store(embedder)
            if m.status == "active" and text:
                emb = await embedder.aembed_query(m.text)
                store.upsert(
                    ids=[m.id],
                    embeddings=[emb],
                    documents=[m.text],
                    metadatas=[{
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "scope": m.scope,
                        "kind": m.kind,
                        "status": m.status,
                    }],
                )
            elif m.status in ("deleted", "superseded"):
                store.delete(ids=[m.id])
        except Exception:  # noqa: BLE001
            pass

        return m

    @staticmethod
    async def delete(session, tenant_id: str, project_id: str, memory_id: str) -> bool:
        m = await MemoryService.get(session, tenant_id, project_id, memory_id)
        if not m:
            return False

        m.status = "deleted"
        await session.commit()

        try:
            embedder = await KnowledgeService.embedder_for_project(session, tenant_id, project_id)
            MemoryService._store(embedder).delete(ids=[m.id])
        except Exception:  # noqa: BLE001
            pass

        return True

    @staticmethod
    async def list(
        session,
        tenant_id: str,
        project_id: str,
        *,
        scope: str | None = None,
        status: str | None = "active",
        kind: str | None = None,
    ) -> list[Memory]:
        q = select(Memory).where(Memory.tenant_id == tenant_id, Memory.project_id == project_id)
        if scope:
            q = q.where(Memory.scope == scope)
        if status:
            q = q.where(Memory.status == status)
        if kind:
            q = q.where(Memory.kind == kind)
        return list((await session.execute(q.order_by(Memory.created_at.desc()))).scalars())
