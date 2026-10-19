"""Tests for Alberto Vector Store Backend, Fallback & Health Reporting Review.

Covers:
1. Native ChromaDB initialized successfully.
2. Native initialization failure and fallback activation.
3. Persistent fallback health.
4. In-memory fallback health.
5. Unavailable backend.
6. Non-writable persistence path.
7. Actual backend reflected in health status.
8. Repeated health polling without unnecessary initialization.
9. JSON fallback restart durability.
10. Migration to native ChromaDB.
11. Metadata filtering and project isolation.
12. Existing semantic retrieval functionality.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alberto.knowledge.store import (
    _CLIENT_CACHE,
    _COL_CACHE,
    ChromaStore,
    FallbackVectorCollection,
    _check_path_durability,
    get_vector_store_status,
    migrate_fallback_to_native,
)


# 1. Native ChromaDB initialized successfully
def test_scenario_1_native_chromadb_initialized_successfully(tmp_path: Path):
    persist_dir = str(tmp_path / "native_store")
    mock_client = MagicMock()
    _CLIENT_CACHE.pop(persist_dir, None)

    with patch("alberto.knowledge.store._should_use_fallback", return_value=False), \
         patch("alberto.knowledge.store._is_native_chromadb_supported", return_value=(True, "Native ChromaDB operational.")), \
         patch("alberto.knowledge.store._client_for", return_value=mock_client):
        status = get_vector_store_status(persist_dir)

    assert status["status"] == "healthy"
    assert status["available"] is True
    assert status["mode"] == "native"
    assert status["durable"] is True
    assert status["backend"] == "chromadb.PersistentClient"
    assert status["capabilities"]["read"] is True
    assert status["capabilities"]["write"] is True
    assert status["capabilities"]["semantic_query"] is True


# 2. Native initialization failure and fallback activation
def test_scenario_2_native_init_failure_and_fallback_activation(tmp_path: Path):
    persist_dir = str(tmp_path / "failed_native")
    _CLIENT_CACHE.pop(persist_dir, None)

    with patch("alberto.knowledge.store._should_use_fallback", return_value=False), \
         patch("alberto.knowledge.store._is_native_chromadb_supported", return_value=(True, "Native ChromaDB operational.")), \
         patch("alberto.knowledge.store._client_for", side_effect=RuntimeError("Corrupt SQLite database")):
        status = get_vector_store_status(persist_dir)

    assert status["status"] == "degraded"
    assert status["available"] is True
    assert status["mode"] == "fallback"
    assert status["durable"] is True
    assert status["backend"] == "FallbackVectorCollection (pure-python)"
    assert "Corrupt SQLite database" in status["reason"]


# 3. Persistent fallback health
def test_scenario_3_persistent_fallback_health(tmp_path: Path):
    persist_dir = str(tmp_path / "persistent_fb")
    _CLIENT_CACHE.pop(persist_dir, None)

    with patch("alberto.knowledge.store._should_use_fallback", return_value=True), \
         patch("alberto.knowledge.store._is_native_chromadb_supported", return_value=(False, "Native probe simulated failure")):
        status = get_vector_store_status(persist_dir)

    assert status["status"] == "degraded"
    assert status["available"] is True
    assert status["mode"] == "fallback"
    assert status["durable"] is True
    assert status["backend"] == "FallbackVectorCollection (pure-python)"
    assert status["capabilities"]["read"] is True
    assert status["capabilities"]["write"] is True
    assert status["capabilities"]["semantic_query"] is True


# 4. In-memory fallback health
@pytest.mark.parametrize("mem_path", [":memory:", "memory", ""])
def test_scenario_4_in_memory_fallback_health(mem_path: str):
    status = get_vector_store_status(mem_path)
    assert status["status"] == "degraded_in_memory"
    assert status["available"] is True
    assert status["mode"] == "fallback"
    assert status["durable"] is False
    assert status["backend"] == "FallbackVectorCollection (in-memory)"
    assert "non-durable" in status["reason"].lower()


# 5. Unavailable backend (file path where directory required)
def test_scenario_5_unavailable_backend(tmp_path: Path):
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("hello", encoding="utf-8")

    status = get_vector_store_status(str(file_path))
    assert status["status"] == "unavailable"
    assert status["available"] is False
    assert status["mode"] == "unavailable"
    assert status["durable"] is False
    assert status["backend"] == "none"
    assert status["capabilities"]["read"] is False
    assert status["capabilities"]["write"] is False
    assert status["capabilities"]["semantic_query"] is False


# 6. Non-writable persistence path
def test_scenario_6_non_writable_persistence_path(tmp_path: Path):
    unwritable_dir = str(tmp_path / "read_only_dir")

    with patch("os.access", return_value=False):
        durable, err = _check_path_durability(unwritable_dir)
        assert durable is False
        assert "not writable" in (err or "")

        status = get_vector_store_status(unwritable_dir)
        assert status["status"] == "unavailable"
        assert status["available"] is False
        assert status["durable"] is False


# 7. Actual backend reflected in health status
def test_scenario_7_actual_backend_reflected_in_health_status(tmp_path: Path):
    # Native client
    p_native = str(tmp_path / "check_native")
    _CLIENT_CACHE[p_native] = MagicMock()
    with patch("alberto.knowledge.store._should_use_fallback", return_value=False):
        s_native = get_vector_store_status(p_native)
        assert s_native["backend"] == "chromadb.PersistentClient"
        assert s_native["mode"] == "native"

    # Persistent fallback
    p_fallback = str(tmp_path / "check_fallback")
    _CLIENT_CACHE.pop(p_fallback, None)
    with patch("alberto.knowledge.store._should_use_fallback", return_value=True):
        s_fallback = get_vector_store_status(p_fallback)
        assert s_fallback["backend"] == "FallbackVectorCollection (pure-python)"
        assert s_fallback["mode"] == "fallback"

    # In-memory
    s_mem = get_vector_store_status(":memory:")
    assert s_mem["backend"] == "FallbackVectorCollection (in-memory)"


# 8. Repeated health polling without unnecessary initialization
def test_scenario_8_repeated_health_polling_no_unnecessary_init(tmp_path: Path):
    persist_dir = str(tmp_path / "polling_store")
    mock_client = MagicMock()
    _CLIENT_CACHE[persist_dir] = mock_client

    with patch("alberto.knowledge.store._client_for") as mock_client_for, \
         patch("alberto.knowledge.store._should_use_fallback", return_value=False):
        for _ in range(10):
            status = get_vector_store_status(persist_dir)
            assert status["status"] == "healthy"

        # _client_for was NOT called repeatedly because cached client was reused
        mock_client_for.assert_not_called()


# 9. JSON fallback restart durability
def test_scenario_9_json_fallback_restart_durability(tmp_path: Path):
    persist_dir = str(tmp_path / "restart_durability")
    col1 = FallbackVectorCollection("restart_kb", persist_path=persist_dir)
    assert col1.is_durable is True

    col1.upsert(
        ids=["id_1", "id_2"],
        embeddings=[[0.1] * 128, [0.2] * 128],
        documents=["Document 1 text", "Document 2 text"],
        metadatas=[{"k": "v1"}, {"k": "v2"}],
    )
    assert col1.count() == 2

    # Fresh instance re-reading from disk
    col2 = FallbackVectorCollection("restart_kb", persist_path=persist_dir)
    assert col2.count() == 2

    doc1 = col2.get(ids=["id_1"], include=["embeddings"])
    assert doc1["ids"] == ["id_1"]
    assert doc1["documents"] == ["Document 1 text"]
    assert doc1["metadatas"] == [{"k": "v1"}]
    assert len(doc1["embeddings"][0]) == 128


# 10. Migration to native ChromaDB
def test_scenario_10_migration_to_native_chromadb(tmp_path: Path):
    persist_dir = str(tmp_path / "mig_test")
    col_name = "test_col_384"
    fb = FallbackVectorCollection(name=col_name, persist_path=persist_dir)
    fb.upsert(
        ids=["doc_a", "doc_b"],
        embeddings=[[0.5] * 384, [0.6] * 384],
        documents=["Text A", "Text B"],
        metadatas=[{"tenant": "t1"}, {"tenant": "t1"}],
    )
    fb_fp = fb._file_path()
    assert fb_fp is not None and fb_fp.exists()

    # Successful migration with full verification of IDs, documents, metadata, and embeddings
    mock_native = MagicMock()
    mock_native.get.return_value = {
        "ids": ["doc_a", "doc_b"],
        "documents": ["Text A", "Text B"],
        "metadatas": [{"tenant": "t1"}, {"tenant": "t1"}],
        "embeddings": [[0.5] * 384, [0.6] * 384],
    }
    success = migrate_fallback_to_native(mock_native, persist_dir, col_name)
    assert success is True
    mock_native.upsert.assert_called_once()
    assert not fb_fp.exists()
    assert fb_fp.with_suffix(".json.migrated").exists()

    # Retry on verification failure (document mismatch)
    retry_col = "retry_col_384"
    fb_retry = FallbackVectorCollection(name=retry_col, persist_path=persist_dir)
    fb_retry.upsert(ids=["doc_c"], embeddings=[[0.7] * 384], documents=["Text C"], metadatas=[{"k": "v"}])
    fb_retry_fp = fb_retry._file_path()

    mock_failing_native = MagicMock()
    mock_failing_native.get.return_value = {
        "ids": ["doc_c"],
        "documents": ["Wrong text"],  # Mismatched document
        "metadatas": [{"k": "v"}],
        "embeddings": [[0.7] * 384],
    }
    fail_res = migrate_fallback_to_native(mock_failing_native, persist_dir, retry_col)
    assert fail_res is False
    assert fb_retry_fp is not None and fb_retry_fp.exists()  # Retained for retry


# 11. Metadata filtering and project isolation
def test_scenario_11_metadata_filtering_and_project_isolation():
    fb = FallbackVectorCollection(name="isolation_kb", persist_path=":memory:")
    fb.upsert(
        ids=["t1_p1_1", "t1_p2_1", "t2_p1_1"],
        embeddings=[[0.1] * 8, [0.2] * 8, [0.3] * 8],
        documents=["T1 P1 doc", "T1 P2 doc", "T2 P1 doc"],
        metadatas=[
            {"tenant_id": "t1", "project_id": "p1", "source": "s1"},
            {"tenant_id": "t1", "project_id": "p2", "source": "s2"},
            {"tenant_id": "t2", "project_id": "p1", "source": "s3"},
        ],
    )

    # Scoped query matching t1 + p1 only
    where_scope = {
        "$and": [
            {"tenant_id": {"$eq": "t1"}},
            {"project_id": {"$eq": "p1"}},
        ]
    }
    res = fb.query(query_embeddings=[[0.1] * 8], n_results=10, where=where_scope)
    ids = res["ids"][0]
    assert ids == ["t1_p1_1"]
    assert "t1_p2_1" not in ids
    assert "t2_p1_1" not in ids

    # $in operator
    where_in = {"source": {"$in": ["s2", "s3"]}}
    res_in = fb.get(where=where_in)
    assert set(res_in["ids"]) == {"t1_p2_1", "t2_p1_1"}

    # Combined ids and where delete
    fb.delete(ids=["t1_p2_1"], where={"project_id": "p2"})
    assert fb.count() == 2
    assert "t1_p2_1" not in fb._items


# 12. Existing semantic retrieval functionality
def test_scenario_12_existing_semantic_retrieval_functionality(tmp_path: Path):
    persist_dir = str(tmp_path / "semantic_store")
    _COL_CACHE.clear()

    with patch("alberto.knowledge.store._should_use_fallback", return_value=True):
        store = ChromaStore(path=persist_dir, collection="semantic_kb")

        # Upsert
        store.upsert(
            ids=["vec_1", "vec_2"],
            embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            documents=["Machine learning models", "Culinary recipes"],
            metadatas=[
                {"tenant_id": "ten_a", "project_id": "proj_a", "topic": "ai"},
                {"tenant_id": "ten_a", "project_id": "proj_a", "topic": "food"},
            ],
        )

        # Vector search query
        hits = store.query_where(
            embedding=[0.9, 0.1, 0.0],
            where={"tenant_id": {"$eq": "ten_a"}, "project_id": {"$eq": "proj_a"}},
            top_k=1,
        )
        assert len(hits) == 1
        assert hits[0].id == "vec_1"
        assert hits[0].text == "Machine learning models"
        assert hits[0].score > 0.8

        # Delete where
        store.delete_where({"topic": {"$eq": "food"}})
        count_after = store.count("ten_a", "proj_a")
        assert count_after == 1
