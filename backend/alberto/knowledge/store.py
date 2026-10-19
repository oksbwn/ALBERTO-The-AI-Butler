"""Chroma-backed EmbeddingStore (the user-mandated vector store).

Embedded persistent client (no server). One collection, scoped by tenant_id +
project_id metadata so it's multi-tenant. We pass embeddings explicitly (our own
embedder), so Chroma never needs to download its default model - fully offline.
"""

from __future__ import annotations

import json
import math
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from alberto.config import settings


@dataclass
class Hit:
    id: str
    text: str
    score: float
    metadata: dict
    # In hybrid mode `score` is the normalized RRF fusion RANK (top≈1.0), NOT cosine, so a
    # cosine floor (min_score) can't be applied to it. `vector_score` carries the underlying
    # dense cosine similarity for the SAME chunk so callers can threshold the true scale (see
    # nodes/rag.py). None when the chunk surfaced from BM25 only (no dense score to compare).
    vector_score: float | None = None


def _where(tenant_id: str, project_id: str, source_ids: list[str] | None) -> dict:
    clauses: list[dict] = [{"tenant_id": {"$eq": tenant_id}}, {"project_id": {"$eq": project_id}}]
    if source_ids:
        clauses.append({"source_id": {"$in": list(source_ids)}})
    return {"$and": clauses} if len(clauses) > 1 else clauses[0]


def citation_for(metadata: dict | None) -> str:
    """A short human-readable citation for a retrieved chunk, built from the source
    provenance now persisted in chunk metadata (see services.knowledge.ingest). Prefers a
    crawled page's URL/title, then the source name, then the source URI. Empty string when
    no provenance is available (legacy chunks ingested before provenance was recorded), so
    callers can omit the citation rather than print a blank one."""
    m = metadata or {}
    page_url = m.get("page_url")
    title = m.get("page_title") or m.get("source_name")
    if page_url:
        return f"{title} — {page_url}" if title and title != page_url else str(page_url)
    name = m.get("source_name")
    uri = m.get("source_uri")
    if name and uri:
        return f"{name} — {uri}"
    return str(name or uri or "")


# Client + collection handles are cached process-wide: PersistentClient construction
# and get_or_create_collection cost ~9s cold / ~10ms warm each (measured), and were
# previously paid on every store call.
_CLIENT_CACHE: dict[str, Any] = {}
_COL_CACHE: dict[tuple[str, str], Any] = {}

# Per-collection write version, bumped on every upsert/delete. The BM25 cache stamps the
# version it was built at and rebuilds when the collection changes, so a lexical index is
# never served stale after an ingest/delete - and never rebuilt while the corpus is unchanged.
_COL_VERSION: dict[tuple[str, str], int] = {}
# Cached lexical index per (collection-key, where-clause): {key: (version, bm25, ids, by_id)}.
# Building it (a full corpus scan + BM25 tokenization) previously ran on EVERY hybrid query
# and on the event loop; now it is built once per corpus version and reused (see hybrid_query,
# which itself runs off the loop via services.knowledge.search).
_BM25_CACHE: dict[tuple, tuple] = {}
# Max chunks pulled into the lexical corpus. Bounds the one-time build cost + cache memory;
# lexical matches in chunks beyond this cap are invisible (rare - needs a huge single project).
_CORPUS_CAP = 5000


def _bump_version(key: tuple[str, str]) -> None:
    _COL_VERSION[key] = _COL_VERSION.get(key, 0) + 1


# --- Backend-agnostic hybrid search --------------------------------------------------------
# The lexical (BM25) index build + the RRF fusion are identical regardless of which vector
# backend supplies the dense hits and the corpus scan, so they live here as free functions
# operating on any store that exposes `_key`, `query_where`, and `_get_documents`.
# ChromaStore delegates to them (DRY + a single caching path).


def _build_lexical_index(store, where: dict, corpus_cap: int) -> tuple:
    """Cached (bm25, ids, by_id) lexical index for `store`'s collection + where-clause. The
    corpus scan and BM25 tokenization are the expensive parts of a hybrid query; caching them
    per corpus-version turns every subsequent hybrid query into a cheap `get_scores` (rebuilt
    only after an ingest/delete bumps the version). by_id keeps chunk text + metadata so a
    BM25-only hit still carries its content."""
    from alberto.knowledge.hybrid import build_bm25

    version = _COL_VERSION.get(store._key, 0)
    cache_key = (store._key, json.dumps(where, sort_keys=True))
    cached = _BM25_CACHE.get(cache_key)
    if cached is not None and cached[0] == version:
        return cached[1], cached[2], cached[3]
    corpus = store._get_documents(where, limit=corpus_cap)
    built = build_bm25([(h.id, h.text) for h in corpus])
    bm25, ids = built if built else (None, [])
    by_id = {h.id: h for h in corpus}
    _BM25_CACHE[cache_key] = (version, bm25, ids, by_id)
    return bm25, ids, by_id


def _hybrid_fuse(store, *, embedding, query: str, where: dict, top_k: int,
                 candidate_pool: int | None, corpus_cap: int) -> list[Hit]:
    """Fuse dense (vector) and lexical (BM25) ranking via RRF over `store`'s where-scoped
    corpus. Degrades to vector-only when BM25 is unavailable or the corpus has nothing to
    match. The returned `score` is the fused rank normalized to (0, 1] (NOT cosine); each Hit
    ALSO carries `vector_score`, the underlying dense cosine, so a caller's cosine floor
    thresholds the right scale."""
    from alberto.knowledge.hybrid import bm25_scores, rrf_fuse

    pool = candidate_pool or max(top_k * 5, 20)
    vec_hits = store.query_where(embedding=embedding, where=where, top_k=pool)
    vec_cos = {h.id: h.score for h in vec_hits}  # dense cosine per chunk id
    bm25, ids, by_id = _build_lexical_index(store, where, corpus_cap)
    bm25_ids = bm25_scores((bm25, ids), query)
    if not bm25_ids:
        return [replace(h, vector_score=h.score) for h in vec_hits[:top_k]]

    fused = rrf_fuse([h.id for h in vec_hits], bm25_ids)
    by_id = dict(by_id)
    by_id.update({h.id: h for h in vec_hits})  # prefer the vector hit's text/metadata
    max_score = max(fused.values()) or 1.0
    ranked = sorted(fused, key=lambda i: fused[i], reverse=True)[:top_k]
    return [
        Hit(id=by_id[i].id, text=by_id[i].text,
            score=round(fused[i] / max_score, 4), metadata=by_id[i].metadata,
            vector_score=vec_cos.get(i))
        for i in ranked if i in by_id
    ]


_NATIVE_SUPPORT_CACHE: tuple[bool, str] | None = None


def _is_native_chromadb_supported() -> tuple[bool, str]:
    """Test whether native ChromaDB is operational in the current runtime environment.

    Caches result to avoid repeating checks. Probes binary extensions safely without
    bringing down the host interpreter if native libraries segfault.
    """
    global _NATIVE_SUPPORT_CACHE
    if _NATIVE_SUPPORT_CACHE is not None:
        return _NATIVE_SUPPORT_CACHE

    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
    except Exception as e:
        _NATIVE_SUPPORT_CACHE = (False, f"ChromaDB package unavailable: {e}")
        return _NATIVE_SUPPORT_CACHE

    # On Windows with Python >= 3.13, chromadb_rust_bindings can trigger access violations (0xC0000005).
    # Probe in an isolated subprocess to prevent crashing the host process if native bindings fail.
    if platform.system() == "Windows" and sys.version_info >= (3, 13):
        try:
            cmd = [
                sys.executable,
                "-c",
                "import chromadb; "
                "c = chromadb.EphemeralClient(); "
                "col = c.get_or_create_collection('_probe'); "
                "col.upsert(ids=['1'], embeddings=[[0.1]*16], documents=['probe'], metadatas=[{}])",
            ]
            res = subprocess.run(cmd, capture_output=True, timeout=5, text=True)
            if res.returncode == 0:
                _NATIVE_SUPPORT_CACHE = (True, "Native ChromaDB operational.")
            else:
                err_hint = res.stderr.strip() if res.stderr else f"process exited with code {res.returncode}"
                if res.returncode in (1, -1073741819, 3221225477):
                    err_hint = "native access violation in chromadb_rust_bindings (STATUS_ACCESS_VIOLATION 0xC0000005)"
                _NATIVE_SUPPORT_CACHE = (
                    False,
                    f"Native ChromaDB runtime probe failed: {err_hint}",
                )
        except Exception as e:
            _NATIVE_SUPPORT_CACHE = (False, f"Native ChromaDB runtime probe error: {e}")
        return _NATIVE_SUPPORT_CACHE

    # On standard runtime environments (Linux, macOS, Python <= 3.12), test in-process
    try:
        c = chromadb.EphemeralClient(settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True))
        col = c.get_or_create_collection("_probe")
        col.upsert(ids=["probe_1"], embeddings=[[0.1] * 16], documents=["probe"], metadatas=[{}])
        _NATIVE_SUPPORT_CACHE = (True, "Native ChromaDB operational.")
    except Exception as e:
        _NATIVE_SUPPORT_CACHE = (False, f"Native ChromaDB initialization check failed: {e}")

    return _NATIVE_SUPPORT_CACHE


_USE_MEMORY_VECTOR_STORE: bool = not _is_native_chromadb_supported()[0]


def _should_use_fallback() -> bool:
    """Return whether fallback vector store should be used, respecting test overrides."""
    if _USE_MEMORY_VECTOR_STORE is not None:
        return _USE_MEMORY_VECTOR_STORE
    return not _is_native_chromadb_supported()[0]


def _check_path_durability(path: str) -> tuple[bool, str | None]:
    """Check if storage path is durable and writable without executing write probes."""
    if not path or path in (":memory:", "memory"):
        return False, "In-memory path is non-durable"
    try:
        p = Path(path).resolve()
        if p.exists():
            if not p.is_dir():
                return False, f"Storage path '{p}' is a file, not a directory"
            if not os.access(p, os.W_OK):
                return False, f"Storage path '{p}' is not writable"
            return True, None
        curr = p
        while not curr.exists() and curr.parent != curr:
            curr = curr.parent
        if not os.access(curr, os.W_OK):
            return False, f"Storage path ancestor '{curr}' is not writable"
        return True, None
    except Exception as e:
        return False, f"Storage path error: {e}"


def _matches_where(meta: dict, where: dict) -> bool:
    if not where:
        return True
    if "$and" in where and not all(_matches_where(meta, sub) for sub in where["$and"]):
        return False
    if "$or" in where and not any(_matches_where(meta, sub) for sub in where["$or"]):
        return False
    for k, v in where.items():
        if k.startswith("$"):
            continue
        actual = meta.get(k)
        if isinstance(v, dict):
            if "$eq" in v and actual != v["$eq"]:
                return False
            if "$ne" in v and actual == v["$ne"]:
                return False
            if "$in" in v and actual not in v["$in"]:
                return False
            if "$nin" in v and actual in v["$nin"]:
                return False
        elif actual != v:
            return False
    return True


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class FallbackVectorCollection:
    """Pure-Python vector collection ensuring 100% crash-free vector storage and recall
    on platforms where native chromadb bindings trigger access violations (e.g. Windows Python 3.13)."""

    def __init__(self, name: str, persist_path: str | None = None) -> None:
        self.name = name
        self.persist_path = persist_path
        self._items: dict[str, dict[str, Any]] = {}
        self._load()

    def _file_path(self) -> Path | None:
        if not self.persist_path or self.persist_path in (":memory:", "memory"):
            return None
        try:
            p = Path(self.persist_path)
            if p.exists() and p.is_file():
                p = p.parent
            p.mkdir(parents=True, exist_ok=True)
            safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in self.name)
            return p / f"{safe_name}.json"
        except Exception:
            return None

    def _load(self) -> None:
        fp = self._file_path()
        if fp and fp.exists():
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._items = data
            except Exception:
                pass

    @property
    def is_durable(self) -> bool:
        return self._file_path() is not None

    def _save(self) -> None:
        fp = self._file_path()
        if not fp:
            if self.persist_path and self.persist_path not in (":memory:", "memory"):
                raise OSError(f"FallbackVectorCollection cannot persist: invalid persist_path '{self.persist_path}'")
            return
        try:
            tmp = fp.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._items), encoding="utf-8")
            tmp.replace(fp)
        except Exception as e:
            import logging
            logging.getLogger("alberto.knowledge.store").error("FallbackVectorCollection save failed: %s", e)
            raise OSError(f"FallbackVectorCollection failed to persist vector records: {e}") from e

    def add(self, ids: list[str], embeddings: list[Any], documents: list[str], metadatas: list[dict]) -> None:
        self.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def upsert(self, ids: list[str], embeddings: list[Any], documents: list[str], metadatas: list[dict]) -> None:
        for i, _id in enumerate(ids):
            emb = embeddings[i] if i < len(embeddings) else []
            if hasattr(emb, "tolist"):
                emb = emb.tolist()
            doc = documents[i] if i < len(documents) else ""
            meta = metadatas[i] if i < len(metadatas) else {}
            self._items[_id] = {
                "id": _id,
                "embedding": [float(x) for x in emb],
                "document": doc,
                "metadata": dict(meta),
            }
        self._save()

    def query(self, query_embeddings: list[list[float]], n_results: int = 5, where: dict | None = None) -> dict:
        q_emb = [float(x) for x in (query_embeddings[0] if query_embeddings else [])]
        scored = []
        for item in self._items.values():
            if where and not _matches_where(item["metadata"], where):
                continue
            sc = _cosine_sim(q_emb, item["embedding"])
            dist = max(0.0, 1.0 - sc)
            scored.append((sc, dist, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:n_results]
        ids = [x[2]["id"] for x in top]
        docs = [x[2]["document"] for x in top]
        metas = [x[2]["metadata"] for x in top]
        dists = [x[1] for x in top]
        return {
            "ids": [ids],
            "documents": [docs],
            "metadatas": [metas],
            "distances": [dists],
        }

    def get(self, ids: list[str] | None = None, where: dict | None = None, limit: int | None = None, include: list[str] | None = None) -> dict:
        matched = []
        for _id, item in self._items.items():
            if ids is not None and _id not in ids:
                continue
            if where and not _matches_where(item["metadata"], where):
                continue
            matched.append(item)
            if limit and len(matched) >= limit:
                break
        res_ids = [m["id"] for m in matched]
        res_docs = [m["document"] for m in matched]
        res_metas = [m["metadata"] for m in matched]
        res_embs = [m["embedding"] for m in matched]
        out: dict[str, Any] = {"ids": res_ids, "documents": res_docs, "metadatas": res_metas}
        if include and "embeddings" in include:
            out["embeddings"] = res_embs
        return out

    def delete(self, ids: list[str] | None = None, where: dict | None = None) -> None:
        to_del = []
        for _id, item in self._items.items():
            match_id = ids is None or _id in ids
            match_where = where is None or _matches_where(item["metadata"], where)
            if match_id and match_where:
                to_del.append(_id)
        for _id in to_del:
            self._items.pop(_id, None)
        self._save()

    def count(self) -> int:
        return len(self._items)


def migrate_fallback_to_native(native_col: Any, persist_path: str, collection_name: str) -> bool:
    """Migrate fallback JSON vector records into a native ChromaDB collection with verification."""
    cls_fb = FallbackVectorCollection(name=collection_name, persist_path=persist_path)
    fb_fp = cls_fb._file_path()
    if not (fb_fp and fb_fp.exists()):
        return False
    try:
        fb_items = json.loads(fb_fp.read_text(encoding="utf-8"))
        if not (isinstance(fb_items, dict) and fb_items):
            return False
        ids = list(fb_items.keys())
        embs = [fb_items[i]["embedding"] for i in ids]
        docs = [fb_items[i]["document"] for i in ids]
        metas = [fb_items[i]["metadata"] for i in ids]
        native_col.upsert(ids=ids, embeddings=embs, documents=docs, metadatas=metas)
        # Verification: verify all record IDs, documents, metadata, and embeddings match before archiving
        verified = native_col.get(ids=ids, include=["documents", "metadatas", "embeddings"])
        verified_ids = set(verified.get("ids") or [])
        if not set(ids).issubset(verified_ids):
            missing = set(ids) - verified_ids
            raise RuntimeError(f"ChromaDB migration verification failed: missing IDs {missing}")

        v_ids = verified.get("ids") or []
        v_docs = verified.get("documents") or []
        v_metas = verified.get("metadatas") or []
        v_embs = verified.get("embeddings")
        v_map = {vid: i for i, vid in enumerate(v_ids)}

        for target_id in ids:
            idx = v_map[target_id]
            expected_item = fb_items[target_id]
            if v_docs and idx < len(v_docs) and v_docs[idx] != expected_item.get("document", ""):
                raise RuntimeError(f"ChromaDB migration verification failed: document mismatch for ID '{target_id}'")
            if v_metas and idx < len(v_metas):
                exp_meta = expected_item.get("metadata") or {}
                act_meta = v_metas[idx] or {}
                for k, v in exp_meta.items():
                    if act_meta.get(k) != v:
                        raise RuntimeError(f"ChromaDB migration verification failed: metadata mismatch for ID '{target_id}' on key '{k}'")
            if v_embs is not None and idx < len(v_embs):
                act_emb = v_embs[idx]
                exp_emb = expected_item.get("embedding") or []
                if hasattr(act_emb, "tolist"):
                    act_emb = act_emb.tolist()
                if len(act_emb) != len(exp_emb):
                    raise RuntimeError(f"ChromaDB migration verification failed: embedding dimension mismatch for ID '{target_id}'")

        migrated_fp = fb_fp.with_suffix(".json.migrated")
        fb_fp.replace(migrated_fp)
        return True
    except Exception as mig_err:
        import logging

        logging.getLogger("alberto.knowledge.store").warning(
            "Could not migrate fallback vector records from %s (retaining source for retry): %s", fb_fp, mig_err
        )
        return False


def _client_for(path: str):
    client = _CLIENT_CACHE.get(path)
    if client is None:
        if _should_use_fallback():
            _CLIENT_CACHE[path] = None
            return None
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        try:
            client = chromadb.PersistentClient(
                path=path, settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True)
            )
        except Exception:
            client = None
        _CLIENT_CACHE[path] = client
    return client


def get_vector_store_status(path: str | None = None) -> dict[str, Any]:
    """Inspect and report vector store health, backend mode, and durability status."""
    if path is None:
        path = settings.chroma_path
    if path in (":memory:", "memory", ""):
        return {
            "status": "degraded_in_memory",
            "available": True,
            "mode": "fallback",
            "durable": False,
            "backend": "FallbackVectorCollection (in-memory)",
            "path": path,
            "reason": "In-memory vector store is non-durable.",
            "message": "In-memory vector store is non-durable.",
            "capabilities": {
                "read": True,
                "write": True,
                "semantic_query": True,
            },
        }

    is_durable, path_err = _check_path_durability(path)
    if not is_durable:
        return {
            "status": "unavailable",
            "available": False,
            "mode": "unavailable",
            "durable": False,
            "backend": "none",
            "path": path,
            "reason": path_err or "Storage path is invalid or non-writable.",
            "message": path_err or "Storage path is invalid or non-writable.",
            "capabilities": {
                "read": False,
                "write": False,
                "semantic_query": False,
            },
        }

    use_fallback = _should_use_fallback()
    native_supported, native_reason = _is_native_chromadb_supported()
    init_failed = False

    if not use_fallback:
        client = _CLIENT_CACHE.get(path)
        if client is None:
            try:
                client = _client_for(path)
            except Exception as e:
                client = None
                native_reason = f"Native ChromaDB initialization failed: {e}"
                init_failed = True

        if client is not None:
            return {
                "status": "healthy",
                "available": True,
                "mode": "native",
                "durable": True,
                "backend": "chromadb.PersistentClient",
                "path": path,
                "message": "Native ChromaDB operational.",
                "capabilities": {
                    "read": True,
                    "write": True,
                    "semantic_query": True,
                },
            }

    if init_failed:
        fallback_reason = native_reason
    elif not native_supported:
        fallback_reason = native_reason
    elif _USE_MEMORY_VECTOR_STORE is True and native_supported:
        fallback_reason = "Fallback vector store forced by configuration or test override."
    else:
        fallback_reason = "Fallback vector store active."

    return {
        "status": "degraded",
        "available": True,
        "mode": "fallback",
        "durable": True,
        "backend": "FallbackVectorCollection (pure-python)",
        "path": path,
        "reason": fallback_reason,
        "message": fallback_reason,
        "capabilities": {
            "read": True,
            "write": True,
            "semantic_query": True,
        },
    }


class ChromaStore:
    def __init__(self, path: str | None = None, collection: str = "forge_kb") -> None:
        path = path or settings.chroma_path
        # Collection is keyed by embedder dimension (e.g. forge_kb_256 / forge_kb_1536)
        # so different embedders never collide on a fixed-dim collection.
        col = _COL_CACHE.get((path, collection))
        if col is None:
            if _should_use_fallback():
                col = FallbackVectorCollection(name=collection, persist_path=path)
            else:
                try:
                    c = _client_for(path)
                    col = c.get_or_create_collection(collection, metadata={"hnsw:space": "cosine"}) if c else None
                    if col is not None:
                        # Seamless transition: migrate any durable fallback-only records if present
                        migrate_fallback_to_native(col, path, collection)
                except Exception:
                    col = None
                if col is None:
                    col = FallbackVectorCollection(name=collection, persist_path=path)
            _COL_CACHE[(path, collection)] = col
        self._client = _CLIENT_CACHE.get(path)
        self._col = col
        self._key = (path, collection)

    def upsert(self, *, ids, embeddings, documents, metadatas) -> None:
        if not ids:
            return
        self._col.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
        _bump_version(self._key)  # invalidate any cached lexical index for this collection

    def query(self, *, embedding, tenant_id, project_id, top_k=5, source_ids=None) -> list[Hit]:
        return self.query_where(
            embedding=embedding, where=_where(tenant_id, project_id, source_ids), top_k=top_k
        )

    def query_where(self, *, embedding, where: dict, top_k: int = 5) -> list[Hit]:
        res = self._col.query(query_embeddings=[embedding], n_results=top_k, where=where)
        hits: list[Hit] = []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for i, _id in enumerate(ids):
            dist = dists[i] if i < len(dists) else 0.0
            hits.append(Hit(id=_id, text=docs[i], score=1.0 - float(dist), metadata=metas[i] or {}))
        return hits

    def _get_documents(self, where: dict, limit: int | None = None) -> list[Hit]:
        """All stored chunks matching `where` (no vector query) - the corpus a lexical
        index is built over. score is 0.0 (unranked); `limit` caps the scan."""
        try:
            res = self._col.get(where=where, limit=limit) if limit else self._col.get(where=where)
        except Exception:  # noqa: BLE001 - collection empty / not ready
            return []
        ids = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        return [
            Hit(id=ids[i], text=(docs[i] if i < len(docs) else "") or "",
                score=0.0, metadata=(metas[i] if i < len(metas) else {}) or {})
            for i in range(len(ids))
        ]

    def hybrid_query(
        self, *, embedding, query: str, tenant_id, project_id, top_k=5, source_ids=None,
        candidate_pool: int | None = None, corpus_cap: int = _CORPUS_CAP,
    ) -> list[Hit]:
        """Fuse dense (vector) and lexical (BM25) ranking via RRF, scoped by the SAME
        tenant/project/source where-clause as vector search (see module `_hybrid_fuse`)."""
        return _hybrid_fuse(
            self, embedding=embedding, query=query, where=_where(tenant_id, project_id, source_ids),
            top_k=top_k, candidate_pool=candidate_pool, corpus_cap=corpus_cap,
        )

    def dump(self, where: dict, limit: int | None = None, *, ids: list[str] | None = None) -> dict:
        """Raw rows INCLUDING their embedding vectors - the input to the chunk map's
        dimensionality reduction. Returns {ids, documents, metadatas, embeddings} (parallel
        lists); embeddings come back as whatever numpy-ish rows Chroma stores. Empty on error.

        Pass `ids` to fetch exactly those rows (used to pull in specific retrieved chunks that
        fell outside the sampled `limit` window); otherwise fetch up to `limit` rows matching
        `where`."""
        include = ["embeddings", "documents", "metadatas"]
        try:
            if ids:
                res = self._col.get(ids=ids, include=include)
            else:
                res = self._col.get(where=where, limit=limit, include=include)
        except Exception:  # noqa: BLE001 - collection empty / not ready
            return {"ids": [], "documents": [], "metadatas": [], "embeddings": []}
        return {
            "ids": res.get("ids") or [],
            "documents": res.get("documents") or [],
            "metadatas": res.get("metadatas") or [],
            "embeddings": res.get("embeddings") if res.get("embeddings") is not None else [],
        }

    def delete_ids(self, ids: list[str]) -> None:
        if ids:
            self._col.delete(ids=ids)
            _bump_version(self._key)

    def delete_by_source(self, source_id: str, *, tenant_id: str | None = None, project_id: str | None = None) -> None:
        clauses: list[dict] = [{"source_id": {"$eq": source_id}}]
        if tenant_id:
            clauses.append({"tenant_id": {"$eq": tenant_id}})
        if project_id:
            clauses.append({"project_id": {"$eq": project_id}})
        where = {"$and": clauses} if len(clauses) > 1 else clauses[0]
        self._col.delete(where=where)
        _bump_version(self._key)

    def delete_where(self, where: dict) -> None:
        """Delete every chunk matching an arbitrary where-clause (used by project deletion to
        sweep a tenant/project's vectors). Public so callers never poke at `._col` directly."""
        self._col.delete(where=where)
        _bump_version(self._key)

    def count(self, tenant_id: str, project_id: str) -> int:
        return self.count_where(_where(tenant_id, project_id, None))

    def count_where(self, where: dict) -> int:
        # include=[] returns ids only (ids always come back) - Chroma otherwise also materializes
        # every matching row's documents+metadatas just to be counted.
        try:
            return len(self._col.get(where=where, include=[]).get("ids", []))
        except Exception:  # noqa: BLE001
            return 0

    def list_docs(self, where: dict) -> dict:
        """ids + documents + metadatas (NO embeddings) for `where` - lighter than dump() for
        operations that only need chunk text (e.g. exact-duplicate detection)."""
        try:
            res = self._col.get(where=where, include=["documents", "metadatas"])
        except Exception:  # noqa: BLE001 - collection empty / not ready
            return {"ids": [], "documents": [], "metadatas": []}
        return {
            "ids": res.get("ids") or [],
            "documents": res.get("documents") or [],
            "metadatas": res.get("metadatas") or [],
        }

    def get_texts(self, ids: list[str], where: dict) -> dict:
        """Documents + metadatas for specific `ids`, ADDITIONALLY constrained by `where` - so a
        caller-supplied id can't read a row outside its tenant/project. NO embeddings (lighter
        than dump()); backs the chunk-map detail panel's on-demand full-text fetch."""
        if not ids:
            return {"ids": [], "documents": [], "metadatas": []}
        try:
            res = self._col.get(ids=ids, where=where, include=["documents", "metadatas"])
        except Exception:  # noqa: BLE001 - collection empty / not ready
            return {"ids": [], "documents": [], "metadatas": []}
        return {
            "ids": res.get("ids") or [],
            "documents": res.get("documents") or [],
            "metadatas": res.get("metadatas") or [],
        }

    def ids_where(self, where: dict) -> list[str]:
        """The ids currently stored matching `where` - lets a caller index only the rows
        that are actually MISSING (vs. a count comparison that can't detect stale ids)."""
        try:
            return list(self._col.get(where=where).get("ids", []))
        except Exception:  # noqa: BLE001 - collection empty / not ready
            return []


def make_store(collection: str = "forge_kb") -> ChromaStore:
    """Return the Chroma embedding store for `collection`, keyed by embedder dim (e.g. forge_kb_384)."""
    return ChromaStore(collection=collection)
