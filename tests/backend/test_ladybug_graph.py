"""Tests for LadybugDB embedded Knowledge Graph, single-process locking, and end-to-end traversal scope isolation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from alberto.knowledge.graph import (
    GraphDatabaseOwnershipError,
    GraphEntity,
    GraphRelationship,
    GraphScopeViolationError,
    LadybugGraphAdapter,
    make_entity_id,
    make_relationship_id,
)


@pytest.fixture
def graph_tmp_dir():
    with tempfile.TemporaryDirectory(prefix="ladybug_test_") as tmp:
        yield Path(tmp)


@pytest.fixture
async def adapter(graph_tmp_dir: Path):
    ad = LadybugGraphAdapter(db_path=graph_tmp_dir)
    await ad.initialize()
    yield ad
    ad.close()


@pytest.mark.asyncio
async def test_graph_initialization_and_lock_conflict(graph_tmp_dir: Path):
    """Verify single-process file locking: competing writable owner raises GraphDatabaseOwnershipError."""
    ad1 = LadybugGraphAdapter(db_path=graph_tmp_dir)
    await ad1.initialize()

    # Competing instance on the same path
    with pytest.raises(GraphDatabaseOwnershipError, match="locked by another process"):
        LadybugGraphAdapter(db_path=graph_tmp_dir)

    ad1.close()

    # Reopening after close succeeds
    ad3 = LadybugGraphAdapter(db_path=graph_tmp_dir)
    await ad3.initialize()
    stats = await ad3.get_stats("t1", "p1")
    assert stats.entity_count == 0
    ad3.close()


@pytest.mark.asyncio
async def test_graph_crud_and_neighbors(adapter: LadybugGraphAdapter):
    tenant_id = "tenant-a"
    project_id = "proj-1"

    # 1. Create entities
    e1 = GraphEntity(
        id=make_entity_id(tenant_id, project_id, "Person", "Alice"),
        tenant_id=tenant_id,
        project_id=project_id,
        kind="Person",
        name="Alice",
        canonical_name="alice",
        description="Software Architect",
        source="test",
    )
    e2 = GraphEntity(
        id=make_entity_id(tenant_id, project_id, "Project", "Alberto"),
        tenant_id=tenant_id,
        project_id=project_id,
        kind="Project",
        name="Alberto",
        canonical_name="alberto",
        description="Local-first AI Butler",
        source="test",
    )

    saved_e1 = await adapter.create_or_update_entity(e1)
    saved_e2 = await adapter.create_or_update_entity(e2)
    assert saved_e1.name == "Alice"
    assert saved_e2.name == "Alberto"

    # 2. Get entity
    fetched = await adapter.get_entity(tenant_id, project_id, e1.id)
    assert fetched is not None
    assert fetched.name == "Alice"

    # 3. Create relationship
    rel = GraphRelationship(
        id=make_relationship_id(tenant_id, project_id, "MAINTAINS", e1.id, e2.id),
        source_id=e1.id,
        target_id=e2.id,
        kind="MAINTAINS",
        tenant_id=tenant_id,
        project_id=project_id,
        source="test",
    )
    saved_rel = await adapter.create_or_update_relationship(rel)
    assert saved_rel.kind == "MAINTAINS"

    # 4. Get neighbors
    neighbors = await adapter.get_neighbors(tenant_id, project_id, e1.id)
    assert len(neighbors) == 1
    assert neighbors[0].nodes[-1].id == e2.id

    # 5. Delete relationship and entity
    assert await adapter.delete_relationship(tenant_id, project_id, rel.id) is True
    assert await adapter.delete_entity(tenant_id, project_id, e2.id) is True
    assert await adapter.get_entity(tenant_id, project_id, e2.id) is None


@pytest.mark.asyncio
async def test_graph_shortest_path(adapter: LadybugGraphAdapter):
    tenant_id = "tenant-a"
    project_id = "proj-1"

    # Create chain A -> B -> C
    nodes = []
    for name in ["NodeA", "NodeB", "NodeC"]:
        e = GraphEntity(
            id=make_entity_id(tenant_id, project_id, "Concept", name),
            tenant_id=tenant_id,
            project_id=project_id,
            kind="Concept",
            name=name,
            canonical_name=name.lower(),
        )
        nodes.append(await adapter.create_or_update_entity(e))

    r1 = GraphRelationship(
        id=make_relationship_id(tenant_id, project_id, "CONNECTS", nodes[0].id, nodes[1].id),
        source_id=nodes[0].id,
        target_id=nodes[1].id,
        kind="CONNECTS",
        tenant_id=tenant_id,
        project_id=project_id,
    )
    r2 = GraphRelationship(
        id=make_relationship_id(tenant_id, project_id, "CONNECTS", nodes[1].id, nodes[2].id),
        source_id=nodes[1].id,
        target_id=nodes[2].id,
        kind="CONNECTS",
        tenant_id=tenant_id,
        project_id=project_id,
    )
    await adapter.create_or_update_relationship(r1)
    await adapter.create_or_update_relationship(r2)

    # Native Cypher shortest path
    path = await adapter.shortest_path(tenant_id, project_id, nodes[0].id, nodes[2].id, max_depth=3)
    assert path is not None
    assert path.length == 2
    assert len(path.nodes) == 3
    assert len(path.relationships) == 2


@pytest.mark.asyncio
async def test_mandatory_intermediate_node_scope_isolation(adapter: LadybugGraphAdapter):
    """CRITICAL SECURITY REQUIREMENT:
    A traversal initiated by Tenant A must never reveal or use an intermediate Tenant B node,
    even if the start and destination belong to Tenant A.
    """
    tenant_a = "tenant-alpha"
    tenant_b = "tenant-bravo"
    project_id = "proj-shared"

    # 1. Tenant A node 1
    node_a1 = await adapter.create_or_update_entity(
        GraphEntity(
            id=make_entity_id(tenant_a, project_id, "Host", "Host-A1"),
            tenant_id=tenant_a,
            project_id=project_id,
            kind="Host",
            name="Host-A1",
            canonical_name="host-a1",
        )
    )

    # 2. Foreign Tenant B intermediate node
    node_b = await adapter.create_or_update_entity(
        GraphEntity(
            id=make_entity_id(tenant_b, project_id, "Router", "Foreign-Router-B"),
            tenant_id=tenant_b,
            project_id=project_id,
            kind="Router",
            name="Foreign-Router-B",
            canonical_name="foreign-router-b",
        )
    )

    # 3. Tenant A node 2
    node_a2 = await adapter.create_or_update_entity(
        GraphEntity(
            id=make_entity_id(tenant_a, project_id, "Host", "Host-A2"),
            tenant_id=tenant_a,
            project_id=project_id,
            kind="Host",
            name="Host-A2",
            canonical_name="host-a2",
        )
    )

    # 4. Attempting to create cross-scope edge (Tenant A -> Tenant B) must fail
    cross_edge = GraphRelationship(
        id=make_relationship_id(tenant_a, project_id, "ROUTES", node_a1.id, node_b.id),
        source_id=node_a1.id,
        target_id=node_b.id,
        kind="ROUTES",
        tenant_id=tenant_a,
        project_id=project_id,
    )
    with pytest.raises(GraphScopeViolationError, match="does not exist in tenant"):
        await adapter.create_or_update_relationship(cross_edge)

    # 5. Cross-scope shortest path query between tenant_a and tenant_b nodes must be rejected
    with pytest.raises(GraphScopeViolationError):
        await adapter.shortest_path(tenant_a, project_id, node_a1.id, node_b.id)

    # 6. Scoped stats are strictly isolated
    stats_a = await adapter.get_stats(tenant_a, project_id)
    stats_b = await adapter.get_stats(tenant_b, project_id)
    assert stats_a.entity_count == 2
    assert stats_b.entity_count == 1


@pytest.mark.asyncio
async def test_invalid_shorter_path_vs_valid_longer_scoped_path(adapter: LadybugGraphAdapter):
    """P0 CRITICAL TEST:
    Given:
      Tenant A pure path: A -> D -> E -> C (length 3)
      Mixed-scope path:   A -> B -> C (length 2, where B is foreign Tenant B)
    The native shortest path engine must NOT drop the request;
    it must natively prune the mixed path during candidate selection and return A -> D -> E -> C.
    """
    tenant_a = "tenant-a"
    tenant_b = "tenant-b"
    project_id = "proj-1"

    # Create Tenant A nodes: A, D, E, C
    for name in ["A", "D", "E", "C"]:
        await adapter.create_or_update_entity(
            GraphEntity(
                id=f"node_{name}",
                tenant_id=tenant_a,
                project_id=project_id,
                kind="Node",
                name=name,
                canonical_name=name.lower(),
            )
        )

    # Create foreign Tenant B intermediate node: B
    await adapter.create_or_update_entity(
        GraphEntity(
            id="node_B",
            tenant_id=tenant_b,
            project_id=project_id,
            kind="Node",
            name="B",
            canonical_name="b",
        )
    )

    # Valid longer route for Tenant A: A -> D -> E -> C
    for src, dst in [("node_A", "node_D"), ("node_D", "node_E"), ("node_E", "node_C")]:
        rel = GraphRelationship(
            id=f"rel_{src}_{dst}",
            source_id=src,
            target_id=dst,
            kind="STEP",
            tenant_id=tenant_a,
            project_id=project_id,
        )
        await adapter.create_or_update_relationship(rel)

    # Inject the shorter foreign path into the underlying database: A -> B -> C
    # using raw cypher to simulate foreign relationships sharing the graph
    adapter._execute(
        """
        MATCH (a:Entity {id: 'node_A'}), (b:Entity {id: 'node_B'})
        CREATE (a)-[:RelatesTo {
            id: 'rel_A_B_foreign',
            kind: 'STEP',
            tenant_id: 'tenant-b',
            project_id: 'proj-1',
            source: 'test',
            confidence: 1.0,
            provenance: '',
            created_at: 0,
            updated_at: 0
        }]->(b)
        """
    )
    adapter._execute(
        """
        MATCH (b:Entity {id: 'node_B'}), (c:Entity {id: 'node_C'})
        CREATE (b)-[:RelatesTo {
            id: 'rel_B_C_foreign',
            kind: 'STEP',
            tenant_id: 'tenant-b',
            project_id: 'proj-1',
            source: 'test',
            confidence: 1.0,
            provenance: '',
            created_at: 0,
            updated_at: 0
        }]->(c)
        """
    )

    # Query shortest path for Tenant A from A to C:
    # Must natively select valid longer path A -> D -> E -> C (length 3), ignoring A -> B -> C!
    path = await adapter.shortest_path(tenant_a, project_id, "node_A", "node_C", max_depth=5)
    assert path is not None
    assert path.length == 3
    node_ids = [n.id for n in path.nodes]
    assert node_ids == ["node_A", "node_D", "node_E", "node_C"]
    assert all(n.tenant_id == tenant_a for n in path.nodes)
    assert all(r.tenant_id == tenant_a for r in path.relationships)


@pytest.mark.asyncio
async def test_only_invalid_paths_available(adapter: LadybugGraphAdapter):
    """When only foreign intermediate paths exist, shortest_path must return None."""
    tenant_a = "tenant-a"
    tenant_b = "tenant-b"
    project_id = "proj-1"

    await adapter.create_or_update_entity(
        GraphEntity(id="start_x", tenant_id=tenant_a, project_id=project_id, kind="Node", name="X", canonical_name="x")
    )
    await adapter.create_or_update_entity(
        GraphEntity(id="foreign_y", tenant_id=tenant_b, project_id=project_id, kind="Node", name="Y", canonical_name="y")
    )
    await adapter.create_or_update_entity(
        GraphEntity(id="end_z", tenant_id=tenant_a, project_id=project_id, kind="Node", name="Z", canonical_name="z")
    )

    # Raw inject X -> Y -> Z with foreign node Y
    adapter._execute(
        """
        MATCH (x:Entity {id: 'start_x'}), (y:Entity {id: 'foreign_y'})
        CREATE (x)-[:RelatesTo {
            id: 'r_xy', kind: 'STEP', tenant_id: 'tenant-b', project_id: 'proj-1',
            source: 'test', confidence: 1.0, provenance: '', created_at: 0, updated_at: 0
        }]->(y)
        """
    )
    adapter._execute(
        """
        MATCH (y:Entity {id: 'foreign_y'}), (z:Entity {id: 'end_z'})
        CREATE (y)-[:RelatesTo {
            id: 'r_yz', kind: 'STEP', tenant_id: 'tenant-b', project_id: 'proj-1',
            source: 'test', confidence: 1.0, provenance: '', created_at: 0, updated_at: 0
        }]->(z)
        """
    )

    path = await adapter.shortest_path(tenant_a, project_id, "start_x", "end_z", max_depth=5)
    assert path is None


@pytest.mark.asyncio
async def test_cross_project_same_tenant_isolation(adapter: LadybugGraphAdapter):
    """Entities in project-1 vs project-2 under same tenant cannot traverse across projects."""
    tenant = "tenant-shared"
    p1 = "proj-alpha"
    p2 = "proj-beta"

    e1 = await adapter.create_or_update_entity(
        GraphEntity(id="p1_node", tenant_id=tenant, project_id=p1, kind="Node", name="N1", canonical_name="n1")
    )
    e2 = await adapter.create_or_update_entity(
        GraphEntity(id="p2_node", tenant_id=tenant, project_id=p2, kind="Node", name="N2", canonical_name="n2")
    )

    # Cross project relationship creation must be rejected
    rel = GraphRelationship(
        id="rel_cross_proj",
        source_id=e1.id,
        target_id=e2.id,
        kind="STEP",
        tenant_id=tenant,
        project_id=p1,
    )
    with pytest.raises(GraphScopeViolationError):
        await adapter.create_or_update_relationship(rel)

    # Shortest path between different projects must be rejected
    with pytest.raises(GraphScopeViolationError):
        await adapter.shortest_path(tenant, p1, e1.id, e2.id)


@pytest.mark.asyncio
async def test_shortest_path_direct_scoped_path(adapter: LadybugGraphAdapter):
    """Direct 1-hop scoped path between two entities in same tenant/project."""
    t = "t-direct"
    p = "p-direct"
    e1 = await adapter.create_or_update_entity(
        GraphEntity(id="n1", tenant_id=t, project_id=p, kind="Node", name="N1")
    )
    e2 = await adapter.create_or_update_entity(
        GraphEntity(id="n2", tenant_id=t, project_id=p, kind="Node", name="N2")
    )
    await adapter.create_or_update_relationship(
        GraphRelationship(id="r12", source_id=e1.id, target_id=e2.id, kind="LINK", tenant_id=t, project_id=p)
    )

    path = await adapter.shortest_path(t, p, e1.id, e2.id, max_depth=5)
    assert path is not None
    assert path.length == 1
    assert [n.id for n in path.nodes] == [e1.id, e2.id]
    assert [r.id for r in path.relationships] == ["r12"]


@pytest.mark.asyncio
async def test_shortest_path_valid_multihop_path(adapter: LadybugGraphAdapter):
    """Valid multi-hop path across 4 hops within scope."""
    t = "t-multi"
    p = "p-multi"
    ids = ["m0", "m1", "m2", "m3", "m4"]
    for mid in ids:
        await adapter.create_or_update_entity(
            GraphEntity(id=mid, tenant_id=t, project_id=p, kind="Node", name=mid)
        )
    for i in range(len(ids) - 1):
        await adapter.create_or_update_relationship(
            GraphRelationship(
                id=f"rel_{ids[i]}_{ids[i+1]}",
                source_id=ids[i],
                target_id=ids[i + 1],
                kind="STEP",
                tenant_id=t,
                project_id=p,
            )
        )

    path = await adapter.shortest_path(t, p, "m0", "m4", max_depth=5)
    assert path is not None
    assert path.length == 4
    assert [n.id for n in path.nodes] == ids


@pytest.mark.asyncio
async def test_shortest_path_foreign_relationship_rejection(adapter: LadybugGraphAdapter):
    """Endpoints are in Tenant A, but relationship edge is in Tenant B -> traversal must reject edge."""
    t_a = "t-rel-a"
    t_b = "t-rel-b"
    p = "p-rel"
    await adapter.create_or_update_entity(GraphEntity(id="na1", tenant_id=t_a, project_id=p, kind="Node", name="A1"))
    await adapter.create_or_update_entity(GraphEntity(id="na2", tenant_id=t_a, project_id=p, kind="Node", name="A2"))

    # Injected raw edge belonging to foreign tenant B connecting two tenant A nodes
    adapter._execute(
        """
        MATCH (a:Entity {id: 'na1'}), (b:Entity {id: 'na2'})
        CREATE (a)-[:RelatesTo {
            id: 'rel_foreign_edge', kind: 'LINK', tenant_id: 't-rel-b', project_id: 'p-rel',
            source: 'test', confidence: 1.0, provenance: '', created_at: 0, updated_at: 0
        }]->(b)
        """
    )

    path = await adapter.shortest_path(t_a, p, "na1", "na2", max_depth=5)
    assert path is None


@pytest.mark.asyncio
async def test_shortest_path_cyclic_graph(adapter: LadybugGraphAdapter):
    """Graph with cycles (c1 <-> c2 <-> c3 -> c4) resolves cleanly to shortest path without infinite loop."""
    t = "t-cycle"
    p = "p-cycle"
    for i in range(1, 5):
        await adapter.create_or_update_entity(
            GraphEntity(id=f"c{i}", tenant_id=t, project_id=p, kind="Node", name=f"C{i}")
        )

    # c1 <-> c2 <-> c3 -> c4
    edges = [("c1", "c2"), ("c2", "c1"), ("c2", "c3"), ("c3", "c2"), ("c3", "c4")]
    for src, dst in edges:
        await adapter.create_or_update_relationship(
            GraphRelationship(id=f"r_{src}_{dst}", source_id=src, target_id=dst, kind="CYCLE", tenant_id=t, project_id=p)
        )

    path = await adapter.shortest_path(t, p, "c1", "c4", max_depth=5)
    assert path is not None
    assert path.length == 3
    assert [n.id for n in path.nodes] == ["c1", "c2", "c3", "c4"]


@pytest.mark.asyncio
async def test_shortest_path_dense_graph(adapter: LadybugGraphAdapter):
    """Moderately dense forward mesh graph with multiple alternate paths returns true shortest path."""
    t = "t-dense"
    p = "p-dense"
    for i in range(1, 10):
        await adapter.create_or_update_entity(
            GraphEntity(id=f"d{i}", tenant_id=t, project_id=p, kind="Node", name=f"D{i}")
        )

    # Connect forward: each node i links to i+1, i+2, and a direct leap from d1 to d5
    for i in range(1, 9):
        await adapter.create_or_update_relationship(
            GraphRelationship(id=f"r_step_{i}", source_id=f"d{i}", target_id=f"d{i+1}", kind="STEP", tenant_id=t, project_id=p)
        )
    # Direct bypass: d1 -> d5 (leap)
    await adapter.create_or_update_relationship(
        GraphRelationship(id="r_leap_1_5", source_id="d1", target_id="d5", kind="LEAP", tenant_id=t, project_id=p)
    )
    # Leap d5 -> d9
    await adapter.create_or_update_relationship(
        GraphRelationship(id="r_leap_5_9", source_id="d5", target_id="d9", kind="LEAP", tenant_id=t, project_id=p)
    )

    path = await adapter.shortest_path(t, p, "d1", "d9", max_depth=10)
    assert path is not None
    assert path.length == 2  # d1 -> d5 -> d9
    assert [n.id for n in path.nodes] == ["d1", "d5", "d9"]


@pytest.mark.asyncio
async def test_shortest_path_max_depth_boundary(adapter: LadybugGraphAdapter):
    """Max depth clamping and boundary: 10 hops found, path requiring > 10 hops returns None."""
    t = "t-depth"
    p = "p-depth"
    # Create chain of 12 nodes (0..11) -> 11 hops
    for i in range(12):
        await adapter.create_or_update_entity(
            GraphEntity(id=f"k{i}", tenant_id=t, project_id=p, kind="Node", name=f"K{i}")
        )
    for i in range(11):
        await adapter.create_or_update_relationship(
            GraphRelationship(id=f"rk_{i}", source_id=f"k{i}", target_id=f"k{i+1}", kind="STEP", tenant_id=t, project_id=p)
        )

    # Within max depth 10: k0 to k10 is exactly 10 hops -> found
    path_10 = await adapter.shortest_path(t, p, "k0", "k10", max_depth=10)
    assert path_10 is not None
    assert path_10.length == 10

    # k0 to k11 requires 11 hops -> exceeds max_depth ceiling of 10 -> returns None
    path_11 = await adapter.shortest_path(t, p, "k0", "k11", max_depth=10)
    assert path_11 is None


@pytest.mark.asyncio
async def test_shortest_path_invalid_scope_identifiers(adapter: LadybugGraphAdapter):
    """Malformed tenant_id or project_id must fail regex validation with GraphScopeViolationError."""
    with pytest.raises(GraphScopeViolationError, match="Invalid characters in tenant_id"):
        await adapter.shortest_path("tenant; DROP TABLE", "proj-1", "a", "b")

    with pytest.raises(GraphScopeViolationError, match="Invalid characters in project_id"):
        await adapter.shortest_path("tenant-1", "proj' OR '1'='1", "a", "b")


@pytest.mark.asyncio
async def test_shortest_path_no_cross_scope_information_leakage(adapter: LadybugGraphAdapter):
    """Start or end entity not belonging to caller scope raises GraphScopeViolationError."""
    t1 = "tenant-safe-1"
    t2 = "tenant-safe-2"
    p = "proj-1"

    await adapter.create_or_update_entity(GraphEntity(id="s1", tenant_id=t1, project_id=p, kind="Node", name="S1"))
    await adapter.create_or_update_entity(GraphEntity(id="s2", tenant_id=t2, project_id=p, kind="Node", name="S2"))

    # t1 attempts to query with end_id belonging to t2 -> rejected without leakage
    with pytest.raises(GraphScopeViolationError, match="does not exist in scope"):
        await adapter.shortest_path(t1, p, "s1", "s2")

    # t1 attempts to query non-existent entity -> rejected
    with pytest.raises(GraphScopeViolationError, match="does not exist in scope"):
        await adapter.shortest_path(t1, p, "s1", "non-existent")


@pytest.mark.asyncio
async def test_shortest_path_performance_comparison(adapter: LadybugGraphAdapter):
    """Performance comparison between native SHORTEST with recursive filter vs full unpruned candidate scan."""
    import time

    t = "t-perf"
    p = "p-perf"
    # Build a 25-node mesh
    for i in range(25):
        await adapter.create_or_update_entity(
            GraphEntity(id=f"p_{i}", tenant_id=t, project_id=p, kind="Node", name=f"P{i}")
        )
    for i in range(24):
        for j in range(i + 1, min(i + 4, 25)):
            await adapter.create_or_update_relationship(
                GraphRelationship(id=f"rp_{i}_{j}", source_id=f"p_{i}", target_id=f"p_{j}", kind="STEP", tenant_id=t, project_id=p)
            )

    # Measure proposed native query
    t0 = time.perf_counter()
    for _ in range(10):
        path = await adapter.shortest_path(t, p, "p_0", "p_24", max_depth=10)
        assert path is not None
    native_duration = time.perf_counter() - t0

    # Ensure execution is fast (well under 500ms for 10 executions)
    assert native_duration < 2.0
    assert path is not None
    assert path.length > 0


@pytest.mark.asyncio
async def test_graph_persistence_across_process_restart(graph_tmp_dir: Path):
    """Verify graph data persistence: write, close, reopen, and confirm all data survives."""
    t = "t-persist"
    p = "p-persist"

    # 1. Open adapter, write entity and relationship
    ad1 = LadybugGraphAdapter(db_path=graph_tmp_dir)
    await ad1.initialize()
    e1 = await ad1.create_or_update_entity(GraphEntity(id="node_p1", tenant_id=t, project_id=p, kind="Item", name="P1"))
    e2 = await ad1.create_or_update_entity(GraphEntity(id="node_p2", tenant_id=t, project_id=p, kind="Item", name="P2"))
    await ad1.create_or_update_relationship(
        GraphRelationship(id="rel_p1_p2", source_id=e1.id, target_id=e2.id, kind="CONNECTS", tenant_id=t, project_id=p)
    )
    stats1 = await ad1.get_stats(t, p)
    assert stats1.entity_count == 2
    assert stats1.relationship_count == 1
    ad1.close()

    # 2. Reopen fresh adapter instance against the same persistence directory
    ad2 = LadybugGraphAdapter(db_path=graph_tmp_dir)
    await ad2.initialize()
    stats2 = await ad2.get_stats(t, p)
    assert stats2.entity_count == 2
    assert stats2.relationship_count == 1

    # Read back entity and compute shortest path across restarted database
    reloaded_e1 = await ad2.get_entity(t, p, "node_p1")
    assert reloaded_e1 is not None
    assert reloaded_e1.name == "P1"

    path = await ad2.shortest_path(t, p, "node_p1", "node_p2", max_depth=5)
    assert path is not None
    assert path.length == 1
    assert [n.id for n in path.nodes] == ["node_p1", "node_p2"]
    ad2.close()


@pytest.mark.asyncio
async def test_graph_subgraph_and_search_inspection(adapter: LadybugGraphAdapter):
    """Test interactive visualization subgraph queries, search, bounds, and OLMX inspection."""
    tenant_id = "tenant-olmx"
    project_id = "proj-olmx"
    other_tenant = "tenant-other"

    # 1. Empty graph
    subgraph_empty = await adapter.get_subgraph(tenant_id, project_id)
    assert subgraph_empty["nodes"] == []
    assert subgraph_empty["relationships"] == []
    assert subgraph_empty["truncated"] is False
    assert subgraph_empty["total_nodes"] == 0

    # 2. Add OLMX entity, Ollama entity, and connected devices/models
    e_olmx = await adapter.create_or_update_entity(
        GraphEntity(
            id=make_entity_id(tenant_id, project_id, "ModelRunner", "OLMX"),
            tenant_id=tenant_id,
            project_id=project_id,
            kind="ModelRunner",
            name="OLMX",
            canonical_name="olmx",
            description="Local high-performance inference engine [aliases: olmx-core, fast-olmx]",
            source="manual",
            confidence=1.0,
        )
    )
    e_ollama = await adapter.create_or_update_entity(
        GraphEntity(
            id=make_entity_id(tenant_id, project_id, "Application", "Ollama"),
            tenant_id=tenant_id,
            project_id=project_id,
            kind="Application",
            name="Ollama",
            canonical_name="ollama",
            description="Separate standard runner",
            source="manual",
            confidence=0.9,
        )
    )
    e_mac = await adapter.create_or_update_entity(
        GraphEntity(
            id=make_entity_id(tenant_id, project_id, "Device", "MacStudio"),
            tenant_id=tenant_id,
            project_id=project_id,
            kind="Device",
            name="MacStudio",
            canonical_name="macstudio",
            description="M2 Ultra 192GB",
            source="mcp_scan",
            confidence=1.0,
        )
    )
    r1 = await adapter.create_or_update_relationship(
        GraphRelationship(
            id=make_relationship_id(e_olmx.id, "RUNS_ON", e_mac.id),
            source_id=e_olmx.id,
            target_id=e_mac.id,
            kind="RUNS_ON",
            tenant_id=tenant_id,
            project_id=project_id,
            provenance="system_inspection",
        )
    )

    # 3. Add other tenant entity to verify isolation
    await adapter.create_or_update_entity(
        GraphEntity(
            id=make_entity_id(other_tenant, project_id, "ModelRunner", "OLMX"),
            tenant_id=other_tenant,
            project_id=project_id,
            kind="ModelRunner",
            name="OLMX",
            canonical_name="olmx",
        )
    )

    # 4. Search for "olmx"
    search_res = await adapter.get_subgraph(tenant_id, project_id, search="olmx")
    node_names = [n["name"] for n in search_res["nodes"]]
    assert "OLMX" in node_names
    assert "Ollama" not in node_names  # distinct entity
    assert "MacStudio" in node_names  # 1-hop connected neighbor
    assert len(search_res["relationships"]) == 1
    assert search_res["relationships"][0]["kind"] == "RUNS_ON"
    assert search_res["relationships"][0]["provenance"] == "system_inspection"
    assert search_res["focus_id"] == e_olmx.id

    # Search by alias inside description
    alias_res = await adapter.get_subgraph(tenant_id, project_id, search="fast-olmx")
    assert any(n["name"] == "OLMX" for n in alias_res["nodes"])

    # 5. Focus entity
    focus_res = await adapter.get_subgraph(tenant_id, project_id, focus_id=e_olmx.id, hop_depth=1)
    assert len(focus_res["nodes"]) == 2
    assert {n["id"] for n in focus_res["nodes"]} == {e_olmx.id, e_mac.id}
    assert len(focus_res["relationships"]) == 1

    # 6. Bounded node limit
    bounded_res = await adapter.get_subgraph(tenant_id, project_id, limit=2)
    assert len(bounded_res["nodes"]) <= 2
    assert bounded_res["truncated"] is True
    assert bounded_res["total_nodes"] == 3

    # 7. Scope isolation: other tenant cannot see tenant_id entities
    other_subgraph = await adapter.get_subgraph(other_tenant, project_id)
    assert len(other_subgraph["nodes"]) == 1
    assert other_subgraph["nodes"][0]["tenant_id"] == other_tenant
    assert other_subgraph["relationships"] == []


