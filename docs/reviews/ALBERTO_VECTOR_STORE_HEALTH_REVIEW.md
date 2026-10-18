# Alberto — Vector Store Backend, Fallback & Health Reporting Review

**Date:** 2026-10-18  
**Component:** Knowledge & Vector Store Subsystem (`alberto.knowledge.store`, `alberto.routers.health`)  
**Status:** Complete & Verified  

---

## 1. Executive Summary

A comprehensive architectural and runtime review was conducted on Alberto's ChromaDB initialization, fallback selection, vector persistence, and health reporting mechanisms.

Previously, `get_vector_store_status()` relied on hardcoded OS/version checks (`platform.system() == "Windows" and sys.version_info >= (3, 13)`) and returned static messages like `"Native ChromaDB unavailable on Windows Python 3.13"`. Furthermore, readiness polling in `/readyz` repeatedly constructed `chromadb.PersistentClient(...).heartbeat()`, which was prone to binary extension access violations on certain runtimes and ignored fallback states.

The implementation was upgraded to:
1. Safely probe native ChromaDB capability at runtime via isolated subprocess validation on sensitive runtimes (e.g. Windows Python 3.13 with native Rust bindings) and in-process ephemeral validation on Linux/macOS runtimes.
2. Replace static environment messages with dynamic, truthful backend detection, exposing runtime mode (`native`, `fallback`, `unavailable`), durability (`durable: bool`), verified capabilities (`read`, `write`, `semantic_query`), and sanitized error diagnostics.
3. Check storage path writability without performing destructive or expensive write probes on every health poll.
4. Align `FallbackVectorCollection` query and deletion semantics with ChromaDB standards (supporting combined `ids` and `where` filtering, proper projection of document and metadata attributes, and strict multi-tenant isolation).
5. Extract native ChromaDB transition migration into a verified, idempotent helper (`migrate_fallback_to_native`) that safely archives migrated fallback files to `.json.migrated` only after verifying full ID inclusion.
6. Connect `/readyz` readiness checks directly to `get_vector_store_status()` to avoid redundant PersistentClient instantiations.

---

## 2. Actual Initialization Flow & Fallback Activation Analysis

### Initialization Call Graph
```
ChromaStore.__init__(path, collection) / make_store(collection)
   ├── Check _COL_CACHE[(path, collection)]
   │     └── If cached, return existing collection handle
   ├── _should_use_fallback()
   │     ├── Check _USE_MEMORY_VECTOR_STORE override (for tests/config)
   │     └── If unset, evaluate _is_native_chromadb_supported()
   │           ├── Probe import chromadb
   │           ├── Probe binary operational capability (upsert/query)
   │           └── Cache result in _NATIVE_SUPPORT_CACHE
   ├── If fallback required:
   │     └── col = FallbackVectorCollection(name=collection, persist_path=path)
   └── If native supported:
         ├── c = _client_for(path) -> PersistentClient(path)
         ├── col = c.get_or_create_collection(collection, metadata={"hnsw:space": "cosine"})
         ├── migrate_fallback_to_native(col, path, collection) -> idempotent migration
         └── On failure: col = FallbackVectorCollection(name=collection, persist_path=path)
```

### Why the Fallback Was Activated
1. **Windows Python 3.13 Binary Extension Access Violation (`0xC0000005`):**
   In `backend/.venv` on Windows 11 with Python 3.13, `chromadb==1.5.9` installs `chromadb_rust_bindings.pyd`. While client instantiation succeeds, batch upsert (`col.upsert(...)`) triggers an immediate unhandled `STATUS_ACCESS_VIOLATION` (`0xC0000005`, exit code `-1073741819`) within the C/Rust extension.
   Because an access violation terminates the entire Python process without raising a standard catchable Python exception, in-process execution is fatal to the server.
2. **Linux Docker & Linux CI Runners (Python 3.12):**
   In the Linux production Docker image (`python:3.12-slim`) and GitHub Actions runners (Linux Python 3.12), `chromadb` executes natively with zero errors. Native ChromaDB is operational and preferred.
3. **Previous Hardcoded Check:**
   Previously, line 141 had:
   `_USE_MEMORY_VECTOR_STORE = platform.system() == "Windows" and sys.version_info >= (3, 13)`
   and `get_vector_store_status` returned `"Native ChromaDB unavailable on Windows Python 3.13"`.
   This hardcoded assumption was replaced with runtime operational probing that dynamically determines whether native ChromaDB can successfully execute vector operations.

---

## 3. Native ChromaDB vs. FallbackVectorCollection Capability Matrix

| Feature | Native ChromaDB (`PersistentClient`) | `FallbackVectorCollection` (Persistent) | `FallbackVectorCollection` (In-Memory) |
|---|---|---|---|
| **Storage Engine** | SQLite + HNSW C++/Rust binary index | Pure-Python atomic JSON serialization (`.tmp` + rename) | In-memory Python `dict` |
| **Durability** | Durable on disk | Durable on disk (`.json` files per collection) | Non-durable (session lifetime only) |
| **Restart Survival** | Full disk recovery | Full disk recovery (`_load()` from JSON) | No (lost on restart) |
| **Vector Similarity** | HNSW approximate nearest neighbors (cosine) | Exact cosine similarity (`_cosine_sim`) | Exact cosine similarity (`_cosine_sim`) |
| **Hybrid Search Support** | Full dense retrieval for RRF fusion | Full dense retrieval for RRF fusion | Full dense retrieval for RRF fusion |
| **Lexical Indexing (BM25)** | External BM25 index over corpus scan | External BM25 index over corpus scan | External BM25 index over corpus scan |
| **Metadata Filtering** | `$and`, `$or`, `$eq`, `$ne`, `$in`, `$nin` | `$and`, `$or`, `$eq`, `$ne`, `$in`, `$nin` | `$and`, `$or`, `$eq`, `$ne`, `$in`, `$nin` |
| **Combined ID + Where Delete** | Deletes matching both ID and where | Deletes matching both ID and where | Deletes matching both ID and where |
| **Native Transition Migration** | Target of migration | Source of migration (`.json.migrated` upon verification) | N/A |
| **Crash Safety** | Process risk if binary extension is broken on runtime | 100% crash-free pure-Python | 100% crash-free pure-Python |

---

## 4. Health-Status Contract & Observability

### Status Contract
The function `get_vector_store_status(path: str | None = None) -> dict[str, Any]` reports:

- **`status`**:
  - `healthy`: Required native persistent backend is operational.
  - `degraded`: Persistent fallback backend is operational.
  - `degraded_in_memory`: In-memory fallback backend is operational (non-durable).
  - `unavailable`: Backend cannot perform vector operations (e.g., path unwritable or init failed).
- **`available`**: `True` if store can read/write/query vectors; `False` if unavailable.
- **`mode`**: `"native"`, `"fallback"`, or `"unavailable"`.
- **`durable`**: `True` if persistent on disk; `False` if in-memory or unwritable.
- **`backend`**: Identifies specific runtime backend (`"chromadb.PersistentClient"`, `"FallbackVectorCollection (pure-python)"`, `"FallbackVectorCollection (in-memory)"`, or `"none"`).
- **`path`**: Configured storage path.
- **`reason`** / **`message`**: Truthful runtime description of backend status or failure reason.
- **`capabilities`**:
  ```json
  {
    "read": true,
    "write": true,
    "semantic_query": true
  }
  ```

### Example Health Outputs

#### 1. Native Persistent Backend (Linux Docker / Python 3.12 CI)
```json
{
  "status": "healthy",
  "available": true,
  "mode": "native",
  "durable": true,
  "backend": "chromadb.PersistentClient",
  "path": "/data/chroma",
  "message": "Native ChromaDB operational.",
  "capabilities": {
    "read": true,
    "write": true,
    "semantic_query": true
  }
}
```

#### 2. Persistent Pure-Python Fallback (Windows 11 Python 3.13)
```json
{
  "status": "degraded",
  "available": true,
  "mode": "fallback",
  "durable": true,
  "backend": "FallbackVectorCollection (pure-python)",
  "path": "C:\\Users\\...\\chroma",
  "reason": "Native ChromaDB runtime probe failed: native access violation in chromadb_rust_bindings (STATUS_ACCESS_VIOLATION 0xC0000005)",
  "message": "Native ChromaDB runtime probe failed: native access violation in chromadb_rust_bindings (STATUS_ACCESS_VIOLATION 0xC0000005)",
  "capabilities": {
    "read": true,
    "write": true,
    "semantic_query": true
  }
}
```

#### 3. In-Memory Mode (`:memory:`)
```json
{
  "status": "degraded_in_memory",
  "available": true,
  "mode": "fallback",
  "durable": false,
  "backend": "FallbackVectorCollection (in-memory)",
  "path": ":memory:",
  "reason": "In-memory vector store is non-durable.",
  "message": "In-memory vector store is non-durable.",
  "capabilities": {
    "read": true,
    "write": true,
    "semantic_query": true
  }
}
```

#### 4. Unwritable Storage Path
```json
{
  "status": "unavailable",
  "available": false,
  "mode": "unavailable",
  "durable": false,
  "backend": "none",
  "path": "/read_only_volume/chroma",
  "reason": "Storage path '/read_only_volume/chroma' is not writable",
  "message": "Storage path '/read_only_volume/chroma' is not writable",
  "capabilities": {
    "read": false,
    "write": false,
    "semantic_query": false
  }
}
```

---

## 5. Verification & Quality Gate Results

### Targeted Tests (`tests/backend/test_vector_store_health.py`)
14 tests executed covering all 12 review requirements:
1. `test_scenario_1_native_chromadb_initialized_successfully` — PASSED
2. `test_scenario_2_native_init_failure_and_fallback_activation` — PASSED
3. `test_scenario_3_persistent_fallback_health` — PASSED
4. `test_scenario_4_in_memory_fallback_health[:memory:]` — PASSED
5. `test_scenario_4_in_memory_fallback_health[memory]` — PASSED
6. `test_scenario_4_in_memory_fallback_health[]` — PASSED
7. `test_scenario_5_unavailable_backend` — PASSED
8. `test_scenario_6_non_writable_persistence_path` — PASSED
9. `test_scenario_7_actual_backend_reflected_in_health_status` — PASSED
10. `test_scenario_8_repeated_health_polling_no_unnecessary_init` — PASSED
11. `test_scenario_9_json_fallback_restart_durability` — PASSED
12. `test_scenario_10_migration_to_native_chromadb` — PASSED
13. `test_scenario_11_metadata_filtering_and_project_isolation` — PASSED
14. `test_scenario_12_existing_semantic_retrieval_functionality` — PASSED

### Existing Regression Suites
- `tests/backend/test_memory_recall_accuracy.py`: 12 passed.
- `tests/backend/test_ladybug_graph.py` (migration test): passed.
- `tests/backend/test_platform_hardening.py` (`/readyz` check): passed.

---

## 6. Files Changed

1. `backend/alberto/knowledge/store.py`:
   - Added runtime operational capability probing (`_is_native_chromadb_supported()`).
   - Implemented non-destructive path durability verification (`_check_path_durability()`).
   - Upgraded `get_vector_store_status()` with dynamic diagnostics, truthful backend classification, and verified capabilities.
   - Refined `FallbackVectorCollection.get()` and `delete()` to adhere to ChromaDB query/deletion semantics.
   - Extracted verified migration helper `migrate_fallback_to_native()`.
2. `backend/alberto/routers/health.py`:
   - Updated `_vector_status()` to reuse `get_vector_store_status()`, avoiding repeated `chromadb.PersistentClient` instantiations during readiness polling.
3. `tests/backend/test_vector_store_health.py`:
   - Created comprehensive test suite verifying all 12 operational scenarios.
