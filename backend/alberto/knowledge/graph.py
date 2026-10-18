"""LadybugDB Knowledge Graph: Embedded Property Graph for Alberto.

Enforces:
- Single-process write ownership via filelock + LadybugDB database locking.
- Full tenant and project isolation on every node, relationship, traversal step, and shortest path.
- Non-blocking async execution through anyio / threadpool.
- Parameterized Cypher queries; no unrestricted arbitrary LLM Cypher execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import filelock

# Ensure Windows discovers OpenSSL / runtime dependencies for LadybugDB
if sys.platform == "win32":
    try:
        import ladybug

        lib_dir = os.path.join(os.path.dirname(ladybug.__file__), "ladybug.libs")
        if os.path.isdir(lib_dir) and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(lib_dir)
        git_mingw = r"C:\Program Files\Git\mingw64\bin"
        if os.path.isdir(git_mingw) and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(git_mingw)
    except Exception:
        pass

import ladybug  # noqa: E402

logger = logging.getLogger("alberto.knowledge.graph")


class GraphDatabaseError(Exception):
    """Base exception for Knowledge Graph database errors."""


class GraphDatabaseOwnershipError(GraphDatabaseError):
    """Raised when LadybugDB is locked by another process or ownership conflict occurs."""


class GraphScopeViolationError(GraphDatabaseError):
    """Raised when an operation attempts to access or link across tenant/project boundaries."""


@dataclass
class GraphEntity:
    id: str
    tenant_id: str
    project_id: str
    kind: str
    name: str
    canonical_name: str = ""
    description: str = ""
    source: str = "manual"
    confidence: float = 1.0
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> GraphEntity:
        return cls(
            id=str(row.get("id", "")),
            tenant_id=str(row.get("tenant_id", "")),
            project_id=str(row.get("project_id", "")),
            kind=str(row.get("kind", "")),
            name=str(row.get("name", "")),
            canonical_name=str(row.get("canonical_name", "")),
            description=str(row.get("description", "")),
            source=str(row.get("source", "manual")),
            confidence=float(row.get("confidence", 1.0)),
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )


@dataclass
class GraphRelationship:
    id: str
    source_id: str
    target_id: str
    kind: str
    tenant_id: str
    project_id: str
    source: str = "manual"
    confidence: float = 1.0
    provenance: str = ""
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict[str, Any], source_id: str = "", target_id: str = "") -> GraphRelationship:
        return cls(
            id=str(row.get("id", "")),
            source_id=source_id or str(row.get("source_id", "")),
            target_id=target_id or str(row.get("target_id", "")),
            kind=str(row.get("kind", "")),
            tenant_id=str(row.get("tenant_id", "")),
            project_id=str(row.get("project_id", "")),
            source=str(row.get("source", "manual")),
            confidence=float(row.get("confidence", 1.0)),
            provenance=str(row.get("provenance", "")),
            created_at=int(row.get("created_at", 0)),
            updated_at=int(row.get("updated_at", 0)),
        )


@dataclass
class GraphPath:
    nodes: list[GraphEntity]
    relationships: list[GraphRelationship]
    length: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "relationships": [r.to_dict() for r in self.relationships],
            "length": self.length,
        }


@dataclass
class GraphStats:
    entity_count: int
    relationship_count: int
    storage_path: str
    is_available: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LadybugGraphAdapter:
    """Manages embedded LadybugDB storage, ownership, schema, and scoped graph operations."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        buffer_pool_size: int = 256 * 1024 * 1024,
        read_only: bool = False,
    ) -> None:
        if db_path is None:
            from alberto.config import settings

            db_path = settings.ladybug_path

        self.base_path = Path(db_path)
        self.read_only = read_only
        self.buffer_pool_size = buffer_pool_size
        self._db: ladybug.Database | None = None
        self._conn: ladybug.Connection | None = None
        self._lock: filelock.FileLock | None = None
        self._lock_acquired: bool = False
        self._is_memory: bool = str(db_path) == ":memory:"

        self._init_database()

    async def initialize(self) -> None:
        """Idempotent async initialization hook."""
        return None

    def _init_database(self) -> None:
        if self._is_memory:
            self._db = ladybug.Database(":memory:", buffer_pool_size=self.buffer_pool_size)
            self._conn = ladybug.Connection(self._db)
            self._init_schema()
            return

        self.base_path.mkdir(parents=True, exist_ok=True)
        lock_file = self.base_path / ".owner.lock"
        self._lock = filelock.FileLock(str(lock_file), timeout=0.1)

        if not self.read_only:
            try:
                self._lock.acquire(timeout=0.2)
                self._lock_acquired = True
            except filelock.Timeout as e:
                raise GraphDatabaseOwnershipError(
                    f"LadybugDB directory '{self.base_path}' is locked by another process. "
                    "Only one active writable backend process may own the graph database."
                ) from e

        # Database file location inside directory
        db_file = self.base_path / "graph.db"
        try:
            self._db = ladybug.Database(
                str(db_file),
                buffer_pool_size=self.buffer_pool_size,
                read_only=self.read_only,
            )
            self._conn = ladybug.Connection(self._db)
        except Exception as e:
            if self._lock_acquired and self._lock:
                self._lock.release()
                self._lock_acquired = False
            msg = str(e)
            if "lock" in msg.lower() or "conflict" in msg.lower() or "io exception" in msg.lower():
                raise GraphDatabaseOwnershipError(
                    f"LadybugDB file lock conflict at '{db_file}': {msg}. "
                    "Ensure only a single Uvicorn backend process owns the database."
                ) from e
            raise GraphDatabaseError(f"Failed to open LadybugDB at '{db_file}': {msg}") from e

        if not self.read_only:
            self._init_schema()

    def _init_schema(self) -> None:
        if not self._conn:
            return
        # Node table: Entity
        self._conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Entity (
                id STRING,
                tenant_id STRING,
                project_id STRING,
                kind STRING,
                name STRING,
                canonical_name STRING,
                description STRING,
                source STRING,
                confidence DOUBLE,
                created_at INT64,
                updated_at INT64,
                PRIMARY KEY (id)
            )
        """)

        # Relationship table: RelatesTo
        self._conn.execute("""
            CREATE REL TABLE IF NOT EXISTS RelatesTo (
                FROM Entity TO Entity,
                id STRING,
                kind STRING,
                tenant_id STRING,
                project_id STRING,
                source STRING,
                confidence DOUBLE,
                provenance STRING,
                created_at INT64,
                updated_at INT64
            )
        """)

    def close(self) -> None:
        if self._conn:
            with contextlib_suppress():
                self._conn.close()
            self._conn = None
        self._db = None
        if self._lock_acquired and self._lock:
            with contextlib_suppress():
                self._lock.release()
            self._lock_acquired = False

    def _execute(self, query: str, parameters: dict[str, Any] | None = None) -> Any:
        assert self._conn is not None
        res: Any = self._conn.execute(query, parameters)
        if isinstance(res, list):
            return res[0]
        return res

    # --- Synchronous internal implementations ---

    def _create_or_update_entity_sync(self, entity: GraphEntity) -> GraphEntity:
        assert self._conn is not None
        now = int(time.time() * 1000)
        created_at = entity.created_at or now
        updated_at = now

        # Check existing
        res = self._execute(
            "MATCH (e:Entity) WHERE e.id = $id RETURN e.tenant_id, e.project_id",
            {"id": entity.id},
        )
        if res.has_next():
            row: Any = res.get_next()
            if row[0] != entity.tenant_id or row[1] != entity.project_id:
                raise GraphScopeViolationError(
                    f"Entity '{entity.id}' belongs to another tenant/project scope."
                )
            self._execute(
                """
                MATCH (e:Entity)
                WHERE e.id = $id AND e.tenant_id = $tenant_id AND e.project_id = $project_id
                SET e.kind = $kind,
                    e.name = $name,
                    e.canonical_name = $cname,
                    e.description = $description,
                    e.source = $source,
                    e.confidence = $conf,
                    e.updated_at = $uat
                """,
                {
                    "id": entity.id,
                    "tenant_id": entity.tenant_id,
                    "project_id": entity.project_id,
                    "kind": entity.kind,
                    "name": entity.name,
                    "cname": entity.canonical_name or entity.name.lower(),
                    "description": entity.description,
                    "source": entity.source,
                    "conf": float(entity.confidence),
                    "uat": updated_at,
                },
            )
        else:
            self._execute(
                """
                CREATE (:Entity {
                    id: $id,
                    tenant_id: $tenant_id,
                    project_id: $project_id,
                    kind: $kind,
                    name: $name,
                    canonical_name: $cname,
                    description: $description,
                    source: $source,
                    confidence: $conf,
                    created_at: $cat,
                    updated_at: $uat
                })
                """,
                {
                    "id": entity.id,
                    "tenant_id": entity.tenant_id,
                    "project_id": entity.project_id,
                    "kind": entity.kind,
                    "name": entity.name,
                    "cname": entity.canonical_name or entity.name.lower(),
                    "description": entity.description,
                    "source": entity.source,
                    "conf": float(entity.confidence),
                    "cat": created_at,
                    "uat": updated_at,
                },
            )

        entity.created_at = created_at
        entity.updated_at = updated_at
        return entity

    def _get_entity_sync(self, tenant_id: str, project_id: str, entity_id: str) -> GraphEntity | None:
        assert self._conn is not None
        res: Any = self._execute(
            """
            MATCH (e:Entity)
            WHERE e.id = $id AND e.tenant_id = $tenant_id AND e.project_id = $project_id
            RETURN e.id, e.tenant_id, e.project_id, e.kind, e.name, e.canonical_name,
                   e.description, e.source, e.confidence, e.created_at, e.updated_at
            """,
            {"id": entity_id, "tenant_id": tenant_id, "project_id": project_id},
        )
        if not res.has_next():
            return None
        row: Any = res.get_next()
        return GraphEntity(
            id=row[0],
            tenant_id=row[1],
            project_id=row[2],
            kind=row[3],
            name=row[4],
            canonical_name=row[5],
            description=row[6],
            source=row[7],
            confidence=float(row[8]),
            created_at=int(row[9]),
            updated_at=int(row[10]),
        )

    def _find_entities_sync(
        self,
        tenant_id: str,
        project_id: str,
        kind: str | None = None,
        name: str | None = None,
        search: str | None = None,
        limit: int = 50,
    ) -> list[GraphEntity]:
        assert self._conn is not None
        safe_limit = min(max(1, limit), 200)
        params: dict[str, Any] = {"tenant_id": tenant_id, "project_id": project_id, "limit": safe_limit}
        where = ["e.tenant_id = $tenant_id", "e.project_id = $project_id"]
        if kind:
            where.append("e.kind = $kind")
            params["kind"] = kind
        if name:
            where.append("e.name = $name")
            params["name"] = name
        if search:
            where.append(
                "(lower(e.name) CONTAINS $search OR lower(e.canonical_name) CONTAINS $search OR lower(e.description) CONTAINS $search)"
            )
            params["search"] = search.strip().lower()

        order = ""
        if search:
            # Exact name matches first, then name/canonical substring, then explicit alias in description, then general description.
            order = (
                "ORDER BY CASE "
                "WHEN lower(e.name) = $search OR e.canonical_name = $search THEN 0 "
                "WHEN lower(e.name) CONTAINS $search OR lower(e.canonical_name) CONTAINS $search THEN 1 "
                "WHEN lower(e.description) CONTAINS '[aliases:' AND lower(e.description) CONTAINS $search THEN 2 "
                "ELSE 3 END, e.name"
            )
        query = f"""
            MATCH (e:Entity)
            WHERE {" AND ".join(where)}
            RETURN e.id, e.tenant_id, e.project_id, e.kind, e.name, e.canonical_name,
                   e.description, e.source, e.confidence, e.created_at, e.updated_at
            {order}
            LIMIT $limit
        """
        res: Any = self._execute(query, params)
        entities = []
        while res.has_next():
            row: Any = res.get_next()
            entities.append(
                GraphEntity(
                    id=row[0],
                    tenant_id=row[1],
                    project_id=row[2],
                    kind=row[3],
                    name=row[4],
                    canonical_name=row[5],
                    description=row[6],
                    source=row[7],
                    confidence=float(row[8]),
                    created_at=int(row[9]),
                    updated_at=int(row[10]),
                )
            )
        return entities

    def _delete_entity_sync(self, tenant_id: str, project_id: str, entity_id: str) -> bool:
        assert self._conn is not None
        existing = self._get_entity_sync(tenant_id, project_id, entity_id)
        if not existing:
            return False

        # Scoped DETACH DELETE
        self._execute(
            """
            MATCH (e:Entity)
            WHERE e.id = $id AND e.tenant_id = $tenant_id AND e.project_id = $project_id
            DETACH DELETE e
            """,
            {"id": entity_id, "tenant_id": tenant_id, "project_id": project_id},
        )
        return True

    def _create_or_update_relationship_sync(self, rel: GraphRelationship) -> GraphRelationship:
        assert self._conn is not None
        # Strict scope enforcement: Both endpoints MUST exist in THIS scope
        src = self._get_entity_sync(rel.tenant_id, rel.project_id, rel.source_id)
        if not src:
            raise GraphScopeViolationError(
                f"Source entity '{rel.source_id}' does not exist in tenant '{rel.tenant_id}' / project '{rel.project_id}'."
            )
        dst = self._get_entity_sync(rel.tenant_id, rel.project_id, rel.target_id)
        if not dst:
            raise GraphScopeViolationError(
                f"Target entity '{rel.target_id}' does not exist in tenant '{rel.tenant_id}' / project '{rel.project_id}'."
            )

        now = int(time.time() * 1000)
        created_at = rel.created_at or now
        updated_at = now

        # Delete existing edge with same id if any (scoped)
        self._execute(
            """
            MATCH ()-[r:RelatesTo]->()
            WHERE r.id = $id AND r.tenant_id = $tenant_id AND r.project_id = $project_id
            DELETE r
            """,
            {"id": rel.id, "tenant_id": rel.tenant_id, "project_id": rel.project_id},
        )

        self._execute(
            """
            MATCH (a:Entity {id: $src_id}), (b:Entity {id: $dst_id})
            WHERE a.tenant_id = $tenant_id AND a.project_id = $project_id
              AND b.tenant_id = $tenant_id AND b.project_id = $project_id
            CREATE (a)-[:RelatesTo {
                id: $id,
                kind: $kind,
                tenant_id: $tenant_id,
                project_id: $project_id,
                source: $source,
                confidence: $conf,
                provenance: $provenance,
                created_at: $cat,
                updated_at: $uat
            }]->(b)
            """,
            {
                "src_id": rel.source_id,
                "dst_id": rel.target_id,
                "id": rel.id,
                "kind": rel.kind,
                "tenant_id": rel.tenant_id,
                "project_id": rel.project_id,
                "source": rel.source,
                "conf": float(rel.confidence),
                "provenance": rel.provenance,
                "cat": created_at,
                "uat": updated_at,
            },
        )
        rel.created_at = created_at
        rel.updated_at = updated_at
        return rel

    def _get_relationships_sync(
        self,
        tenant_id: str,
        project_id: str,
        entity_id: str,
        direction: str = "both",
        limit: int = 50,
    ) -> list[GraphRelationship]:
        assert self._conn is not None
        if direction == "out":
            pattern = "(a:Entity {id: $id})-[r:RelatesTo]->(b:Entity)"
        elif direction == "in":
            pattern = "(a:Entity)<-[r:RelatesTo]-(b:Entity {id: $id})"
        else:
            pattern = "(a:Entity)-[r:RelatesTo]-(b:Entity) WHERE (a.id = $id OR b.id = $id)"

        where_clause = "WHERE" if "WHERE" not in pattern else "AND"
        query = f"""
            MATCH {pattern}
            {where_clause} a.tenant_id = $tenant_id AND a.project_id = $project_id
              AND b.tenant_id = $tenant_id AND b.project_id = $project_id
              AND r.tenant_id = $tenant_id AND r.project_id = $project_id
            RETURN r.id, r.kind, r.tenant_id, r.project_id, r.source, r.confidence,
                   r.provenance, r.created_at, r.updated_at, a.id, b.id
            LIMIT $limit
        """
        safe_limit = min(max(1, limit), 200)
        res: Any = self._execute(
            query,
            {"id": entity_id, "tenant_id": tenant_id, "project_id": project_id, "limit": safe_limit},
        )
        rels = []
        while res.has_next():
            row: Any = res.get_next()
            rels.append(
                GraphRelationship(
                    id=row[0],
                    kind=row[1],
                    tenant_id=row[2],
                    project_id=row[3],
                    source=row[4],
                    confidence=float(row[5]),
                    provenance=row[6],
                    created_at=int(row[7]),
                    updated_at=int(row[8]),
                    source_id=row[9],
                    target_id=row[10],
                )
            )
        return rels

    def _validate_scope_identifier(self, identifier: str, param_name: str = "identifier") -> str:
        if not identifier or not re.match(r"^[a-zA-Z0-9_\-]+$", identifier):
            raise GraphScopeViolationError(
                f"Invalid characters in {param_name}: '{identifier}'. Must be alphanumeric or -/_"
            )
        return identifier

    def _get_neighbors_sync(
        self,
        tenant_id: str,
        project_id: str,
        entity_id: str,
        direction: str = "both",
        max_depth: int = 1,
        limit: int = 50,
    ) -> list[GraphPath]:
        assert self._conn is not None
        depth = min(max(1, max_depth), 5)
        safe_limit = min(max(1, limit), 200)
        self._validate_scope_identifier(tenant_id, "tenant_id")
        self._validate_scope_identifier(project_id, "project_id")

        if direction == "in":
            pattern = f"(a:Entity)<-[r:RelatesTo* 1..{depth} (r, n | WHERE r.tenant_id = $tenant_id AND r.project_id = $project_id AND n.tenant_id = $tenant_id AND n.project_id = $project_id)]-(b:Entity)"
        elif direction == "out":
            pattern = f"(a:Entity)-[r:RelatesTo* 1..{depth} (r, n | WHERE r.tenant_id = $tenant_id AND r.project_id = $project_id AND n.tenant_id = $tenant_id AND n.project_id = $project_id)]->(b:Entity)"
        else:
            pattern = f"(a:Entity)-[r:RelatesTo* 1..{depth} (r, n | WHERE r.tenant_id = $tenant_id AND r.project_id = $project_id AND n.tenant_id = $tenant_id AND n.project_id = $project_id)]-(b:Entity)"

        query = f"""
            MATCH p = {pattern}
            WHERE a.id = $id AND a.tenant_id = $tenant_id AND a.project_id = $project_id
            RETURN nodes(p), rels(p), length(p)
            LIMIT $limit
        """
        res: Any = self._execute(
            query,
            {"id": entity_id, "tenant_id": tenant_id, "project_id": project_id, "limit": safe_limit},
        )
        paths: list[GraphPath] = []
        while res.has_next():
            row: Any = res.get_next()
            raw_nodes = row[0]
            raw_rels = row[1]
            length = row[2]

            # Security verification: EVERY intermediate node and relationship MUST match scope
            if not all(
                n.get("tenant_id") == tenant_id and n.get("project_id") == project_id for n in raw_nodes
            ):
                continue
            if not all(
                r.get("tenant_id") == tenant_id and r.get("project_id") == project_id for r in raw_rels
            ):
                continue

            nodes = [GraphEntity.from_row(n) for n in raw_nodes]
            # Undirected patterns list rels in path order; use stored _SRC/_DST for true direction.
            internal = {
                (n["_ID"]["table"], n["_ID"]["offset"]): ent.id
                for n, ent in zip(raw_nodes, nodes, strict=False)
                if isinstance(n.get("_ID"), dict)
            }
            rels = []
            for i, r in enumerate(raw_rels):
                src_id = nodes[i].id if i < len(nodes) else ""
                dst_id = nodes[i + 1].id if i + 1 < len(nodes) else ""
                s, d = r.get("_SRC"), r.get("_DST")
                if isinstance(s, dict) and isinstance(d, dict):
                    src_id = internal.get((s["table"], s["offset"]), src_id)
                    dst_id = internal.get((d["table"], d["offset"]), dst_id)
                rels.append(GraphRelationship.from_row(r, source_id=src_id, target_id=dst_id))

            paths.append(GraphPath(nodes=nodes, relationships=rels, length=length))

        return paths

    def _shortest_path_sync(
        self,
        tenant_id: str,
        project_id: str,
        start_id: str,
        end_id: str,
        max_depth: int = 5,
    ) -> GraphPath | None:
        self._validate_scope_identifier(tenant_id, "tenant_id")
        self._validate_scope_identifier(project_id, "project_id")

        # Strict scope enforcement on both endpoints
        if not self._get_entity_sync(tenant_id, project_id, start_id):
            raise GraphScopeViolationError(f"Start entity '{start_id}' does not exist in scope.")
        if not self._get_entity_sync(tenant_id, project_id, end_id):
            raise GraphScopeViolationError(f"End entity '{end_id}' does not exist in scope.")

        depth = min(max(1, max_depth), 10)

        # Native shortest path candidate selection constrained to scoped nodes and relationships
        query = f"""
            MATCH p = (a:Entity)-[r:RelatesTo* SHORTEST 1..{depth} (r, n | WHERE r.tenant_id = $tenant_id AND r.project_id = $project_id AND n.tenant_id = $tenant_id AND n.project_id = $project_id)]->(b:Entity)
            WHERE a.id = $start_id AND b.id = $end_id
              AND a.tenant_id = $tenant_id AND a.project_id = $project_id
              AND b.tenant_id = $tenant_id AND b.project_id = $project_id
            RETURN nodes(p), rels(p), length(p)
        """
        res: Any = self._execute(
            query,
            {
                "start_id": start_id,
                "end_id": end_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
            },
        )
        while res.has_next():
            row: Any = res.get_next()
            raw_nodes = row[0]
            raw_rels = row[1]
            length = row[2]

            # Scrutinize all intermediate nodes and relationships for cross-tenant leakage
            if not all(
                n.get("tenant_id") == tenant_id and n.get("project_id") == project_id for n in raw_nodes
            ):
                continue
            if not all(
                r.get("tenant_id") == tenant_id and r.get("project_id") == project_id for r in raw_rels
            ):
                continue

            nodes = [GraphEntity.from_row(n) for n in raw_nodes]
            rels = []
            for i, r in enumerate(raw_rels):
                src_id = nodes[i].id if i < len(nodes) else ""
                dst_id = nodes[i + 1].id if i + 1 < len(nodes) else ""
                rels.append(GraphRelationship.from_row(r, source_id=src_id, target_id=dst_id))

            return GraphPath(nodes=nodes, relationships=rels, length=length)

        return None

    def _delete_relationship_sync(self, tenant_id: str, project_id: str, rel_id: str) -> bool:
        assert self._conn is not None
        res: Any = self._execute(
            """
            MATCH ()-[r:RelatesTo]->()
            WHERE r.id = $id AND r.tenant_id = $tenant_id AND r.project_id = $project_id
            RETURN count(r)
            """,
            {"id": rel_id, "tenant_id": tenant_id, "project_id": project_id},
        )
        if not res.has_next() or res.get_next()[0] == 0:
            return False

        self._execute(
            """
            MATCH ()-[r:RelatesTo]->()
            WHERE r.id = $id AND r.tenant_id = $tenant_id AND r.project_id = $project_id
            DELETE r
            """,
            {"id": rel_id, "tenant_id": tenant_id, "project_id": project_id},
        )
        return True

    def _get_stats_sync(self, tenant_id: str, project_id: str) -> GraphStats:
        assert self._conn is not None
        node_res: Any = self._execute(
            "MATCH (e:Entity) WHERE e.tenant_id = $t AND e.project_id = $p RETURN count(e)",
            {"t": tenant_id, "p": project_id},
        )
        e_count = int(node_res.get_next()[0]) if node_res.has_next() else 0

        rel_res: Any = self._execute(
            "MATCH ()-[r:RelatesTo]->() WHERE r.tenant_id = $t AND r.project_id = $p RETURN count(r)",
            {"t": tenant_id, "p": project_id},
        )
        r_count = int(rel_res.get_next()[0]) if rel_res.has_next() else 0

        return GraphStats(
            entity_count=e_count,
            relationship_count=r_count,
            storage_path=str(self.base_path),
            is_available=True,
        )

    def _get_subgraph_sync(
        self,
        tenant_id: str,
        project_id: str,
        focus_id: str | None = None,
        search: str | None = None,
        kind: str | None = None,
        rel_kind: str | None = None,
        limit: int = 60,
        hop_depth: int = 1,
    ) -> dict[str, Any]:
        assert self._conn is not None
        safe_limit = min(max(1, limit), 100)
        safe_depth = min(max(1, hop_depth), 2)
        self._validate_scope_identifier(tenant_id, "tenant_id")
        self._validate_scope_identifier(project_id, "project_id")

        nodes_map: dict[str, GraphEntity] = {}
        rels_map: dict[str, GraphRelationship] = {}
        truncated = False
        resolved_focus_id = None

        if focus_id:
            focus_node = self._get_entity_sync(tenant_id, project_id, focus_id)
            if focus_node:
                nodes_map[focus_node.id] = focus_node
                resolved_focus_id = focus_node.id
                paths = self._get_neighbors_sync(
                    tenant_id, project_id, focus_id, direction="both", max_depth=safe_depth, limit=safe_limit
                )
                if len(paths) >= safe_limit:
                    truncated = True
                for path in paths:
                    for n in path.nodes:
                        if len(nodes_map) < safe_limit:
                            nodes_map[n.id] = n
                        else:
                            truncated = True
                    for r in path.relationships:
                        if not rel_kind or r.kind == rel_kind:
                            rels_map[r.id] = r
        elif search:
            matched = self._find_entities_sync(
                tenant_id, project_id, kind=kind, search=search, limit=min(safe_limit, 20)
            )
            if len(matched) >= 20:
                truncated = True
            for m in matched:
                nodes_map[m.id] = m
            if matched:
                resolved_focus_id = matched[0].id
                for m in matched[:10]:
                    paths = self._get_neighbors_sync(
                        tenant_id, project_id, m.id, direction="both", max_depth=1, limit=20
                    )
                    for path in paths:
                        for n in path.nodes:
                            if len(nodes_map) < safe_limit:
                                nodes_map[n.id] = n
                            else:
                                truncated = True
                        for r in path.relationships:
                            if not rel_kind or r.kind == rel_kind:
                                rels_map[r.id] = r
        else:
            entities = self._find_entities_sync(
                tenant_id, project_id, kind=kind, limit=safe_limit
            )
            for e in entities:
                nodes_map[e.id] = e

            params: dict[str, Any] = {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "limit": 500,
                "ids": list(nodes_map.keys()),
            }
            where_rel = [
                "r.tenant_id = $tenant_id", "r.project_id = $project_id",
                "a.tenant_id = $tenant_id", "a.project_id = $project_id",
                "b.tenant_id = $tenant_id", "b.project_id = $project_id",
                "a.id IN $ids", "b.id IN $ids",
            ]
            if rel_kind:
                where_rel.append("r.kind = $rel_kind")
                params["rel_kind"] = rel_kind

            query = f"""
                MATCH (a:Entity)-[r:RelatesTo]->(b:Entity)
                WHERE {" AND ".join(where_rel)}
                RETURN r.id, r.kind, r.tenant_id, r.project_id, r.source, r.confidence,
                       r.provenance, r.created_at, r.updated_at, a.id, b.id
                LIMIT $limit
            """
            res: Any = self._execute(query, params)
            while res.has_next():
                row: Any = res.get_next()
                r_id = row[0]
                s_id = row[9]
                t_id = row[10]
                if s_id in nodes_map and t_id in nodes_map:
                    rels_map[r_id] = GraphRelationship(
                        id=r_id,
                        kind=row[1],
                        tenant_id=row[2],
                        project_id=row[3],
                        source=row[4],
                        confidence=float(row[5]),
                        provenance=row[6],
                        created_at=int(row[7]),
                        updated_at=int(row[8]),
                        source_id=s_id,
                        target_id=t_id,
                    )

            stats = self._get_stats_sync(tenant_id, project_id)
            if stats.entity_count > len(nodes_map) or stats.relationship_count > len(rels_map):
                truncated = True

        stats = self._get_stats_sync(tenant_id, project_id)
        valid_rels = [
            r for r in rels_map.values()
            if r.source_id in nodes_map and r.target_id in nodes_map
        ]

        return {
            "nodes": [n.to_dict() for n in nodes_map.values()],
            "relationships": [r.to_dict() for r in valid_rels],
            "truncated": truncated,
            "focus_id": resolved_focus_id,
            "total_nodes": stats.entity_count,
            "total_relationships": stats.relationship_count,
        }

    # --- Async facade methods (dispatched to thread) ---

    async def create_or_update_entity(self, entity: GraphEntity) -> GraphEntity:
        return await asyncio.to_thread(self._create_or_update_entity_sync, entity)

    async def get_entity(self, tenant_id: str, project_id: str, entity_id: str) -> GraphEntity | None:
        return await asyncio.to_thread(self._get_entity_sync, tenant_id, project_id, entity_id)

    async def find_entities(
        self,
        tenant_id: str,
        project_id: str,
        kind: str | None = None,
        name: str | None = None,
        search: str | None = None,
        limit: int = 50,
    ) -> list[GraphEntity]:
        return await asyncio.to_thread(
            self._find_entities_sync, tenant_id, project_id, kind, name, search, limit
        )

    async def get_subgraph(
        self,
        tenant_id: str,
        project_id: str,
        focus_id: str | None = None,
        search: str | None = None,
        kind: str | None = None,
        rel_kind: str | None = None,
        limit: int = 60,
        hop_depth: int = 1,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._get_subgraph_sync,
            tenant_id,
            project_id,
            focus_id,
            search,
            kind,
            rel_kind,
            limit,
            hop_depth,
        )

    async def delete_entity(self, tenant_id: str, project_id: str, entity_id: str) -> bool:
        return await asyncio.to_thread(self._delete_entity_sync, tenant_id, project_id, entity_id)

    async def create_or_update_relationship(self, rel: GraphRelationship) -> GraphRelationship:
        return await asyncio.to_thread(self._create_or_update_relationship_sync, rel)

    async def get_relationships(
        self,
        tenant_id: str,
        project_id: str,
        entity_id: str,
        direction: str = "both",
        limit: int = 50,
    ) -> list[GraphRelationship]:
        return await asyncio.to_thread(
            self._get_relationships_sync, tenant_id, project_id, entity_id, direction, limit
        )

    async def get_neighbors(
        self,
        tenant_id: str,
        project_id: str,
        entity_id: str,
        direction: str = "both",
        max_depth: int = 1,
        limit: int = 50,
    ) -> list[GraphPath]:
        return await asyncio.to_thread(
            self._get_neighbors_sync, tenant_id, project_id, entity_id, direction, max_depth, limit
        )

    async def shortest_path(
        self,
        tenant_id: str,
        project_id: str,
        start_id: str,
        end_id: str,
        max_depth: int = 5,
    ) -> GraphPath | None:
        return await asyncio.to_thread(
            self._shortest_path_sync, tenant_id, project_id, start_id, end_id, max_depth
        )

    async def delete_relationship(self, tenant_id: str, project_id: str, rel_id: str) -> bool:
        return await asyncio.to_thread(self._delete_relationship_sync, tenant_id, project_id, rel_id)

    async def get_stats(self, tenant_id: str, project_id: str) -> GraphStats:
        return await asyncio.to_thread(self._get_stats_sync, tenant_id, project_id)


class contextlib_suppress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return True


_GRAPH_INSTANCE: LadybugGraphAdapter | None = None


def get_graph_adapter() -> LadybugGraphAdapter:
    """Return the singleton LadybugGraphAdapter for the current backend process."""
    global _GRAPH_INSTANCE
    if _GRAPH_INSTANCE is None:
        from alberto.config import settings

        _GRAPH_INSTANCE = LadybugGraphAdapter(
            db_path=settings.ladybug_path,
            buffer_pool_size=settings.ladybug_buffer_pool_size_mb * 1024 * 1024,
        )
    return _GRAPH_INSTANCE


def reset_graph_adapter() -> None:
    """Close and reset graph adapter (used in tests or shutdown)."""
    global _GRAPH_INSTANCE
    if _GRAPH_INSTANCE is not None:
        _GRAPH_INSTANCE.close()
        _GRAPH_INSTANCE = None


def set_graph_adapter(adapter: LadybugGraphAdapter | None) -> None:
    """Explicitly set or clear the singleton LadybugGraphAdapter (used for testing)."""
    global _GRAPH_INSTANCE
    _GRAPH_INSTANCE = adapter


def make_entity_id(*parts: str) -> str:
    """Deterministic cryptographic ID helper for entities."""
    canonical = ":".join(p.strip().lower() for p in parts if p)
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, canonical))


def make_relationship_id(*parts: str) -> str:
    """Deterministic cryptographic ID helper for relationships."""
    canonical = ":".join(p.strip() for p in parts if p)
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, canonical))
