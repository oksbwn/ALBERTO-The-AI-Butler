"""Knowledge Graph endpoints (LadybugDB property graph CRUD & path traversal)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.deps import CurrentUser, current_tenant_id, get_session, require_role
from alberto.knowledge.graph import (
    GraphEntity,
    GraphRelationship,
    GraphScopeViolationError,
    get_graph_adapter,
    make_entity_id,
    make_relationship_id,
)
from alberto.schemas.dto import (
    GraphEntityCreate,
    GraphEntityOut,
    GraphPathOut,
    GraphRelationshipCreate,
    GraphRelationshipOut,
    GraphStatsOut,
    GraphSubgraphOut,
)
from alberto.schemas.memory_curator import (
    OntologyEntityTypeIn,
    OntologyEntityTypeOut,
    OntologyRelationshipTypeIn,
    OntologyRelationshipTypeOut,
)
from alberto.services.audit import AuditService
from alberto.services.ontology_registry import OntologyRegistryService

router = APIRouter(prefix="/v1/projects/{project_id}/graph", tags=["graph"])


@router.get("/stats", response_model=GraphStatsOut)
async def get_graph_stats(
    project_id: str,
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Retrieve Knowledge Graph storage status and scoped node/edge counts."""
    adapter = get_graph_adapter()
    stats = await adapter.get_stats(tenant_id, project_id)
    return stats.to_dict()


@router.get("/subgraph", response_model=GraphSubgraphOut)
async def get_subgraph(
    project_id: str,
    focus_id: str | None = None,
    search: str | None = None,
    kind: str | None = None,
    rel_kind: str | None = None,
    limit: int = Query(default=60, ge=1, le=100),
    hop_depth: int = Query(default=1, ge=1, le=2),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Retrieve a bounded, scoped subgraph for interactive visualization."""
    import contextlib

    from alberto.services.graph_manager import GraphManagerService

    with contextlib.suppress(Exception):
        await GraphManagerService.sweep_orphaned_entities()

    adapter = get_graph_adapter()
    subgraph = await adapter.get_subgraph(
        tenant_id=tenant_id,
        project_id=project_id,
        focus_id=focus_id,
        search=search,
        kind=kind,
        rel_kind=rel_kind,
        limit=limit,
        hop_depth=hop_depth,
    )
    return subgraph


@router.get("/entities", response_model=list[GraphEntityOut])
async def list_entities(
    project_id: str,
    kind: str | None = None,
    name: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Find entities matching filters within the authorized tenant/project scope."""
    adapter = get_graph_adapter()
    entities = await adapter.find_entities(
        tenant_id, project_id, kind=kind, name=name, search=search, limit=limit
    )
    return [e.to_dict() for e in entities]


@router.post("/entities", response_model=GraphEntityOut, status_code=201)
async def create_or_update_entity(
    project_id: str,
    body: GraphEntityCreate,
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Create or upsert an entity in the Knowledge Graph with scoped ownership."""
    adapter = get_graph_adapter()
    entity_id = body.id or make_entity_id(body.kind, body.name)
    entity = GraphEntity(
        id=entity_id,
        tenant_id=tenant_id,
        project_id=project_id,
        kind=body.kind,
        name=body.name,
        canonical_name=body.canonical_name or body.name.lower(),
        description=body.description,
        source=body.source,
        confidence=body.confidence,
    )
    try:
        saved = await adapter.create_or_update_entity(entity)
        await AuditService.log(
            tenant_id=tenant_id,
            project_id=project_id,
            action="graph.entity.create_or_update",
            actor_id=user.id if user else None,
            actor_email=user.email if user else None,
            resource_type="graph_entity",
            resource_id=saved.id,
            meta={"kind": saved.kind, "name": saved.name},
        )
        return saved.to_dict()
    except GraphScopeViolationError as e:
        raise HTTPException(403, str(e)) from e


@router.get("/entities/{entity_id}", response_model=GraphEntityOut)
async def get_entity(
    project_id: str,
    entity_id: str,
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Get an entity by ID within the authorized tenant/project scope."""
    adapter = get_graph_adapter()
    entity = await adapter.get_entity(tenant_id, project_id, entity_id)
    if entity is None:
        raise HTTPException(404, "Entity not found")
    return entity.to_dict()


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    project_id: str,
    entity_id: str,
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Delete an entity and its associated relationships within scope."""
    adapter = get_graph_adapter()
    deleted = await adapter.delete_entity(tenant_id, project_id, entity_id)
    if not deleted:
        raise HTTPException(404, "Entity not found")
    await AuditService.log(
        tenant_id=tenant_id,
        project_id=project_id,
        action="graph.entity.delete",
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        resource_type="graph_entity",
        resource_id=entity_id,
    )


@router.post("/relationships", response_model=GraphRelationshipOut, status_code=201)
async def create_relationship(
    project_id: str,
    body: GraphRelationshipCreate,
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Create a scoped relationship between two entities. Both must belong to the same scope."""
    adapter = get_graph_adapter()
    rel_id = body.id or make_relationship_id(body.source_id, body.target_id, body.kind)
    rel = GraphRelationship(
        id=rel_id,
        source_id=body.source_id,
        target_id=body.target_id,
        kind=body.kind,
        tenant_id=tenant_id,
        project_id=project_id,
        source=body.source,
        confidence=body.confidence,
        provenance=body.provenance,
    )
    try:
        saved = await adapter.create_or_update_relationship(rel)
        await AuditService.log(
            tenant_id=tenant_id,
            project_id=project_id,
            action="graph.relationship.create_or_update",
            actor_id=user.id if user else None,
            actor_email=user.email if user else None,
            resource_type="graph_relationship",
            resource_id=saved.id,
            meta={"kind": saved.kind, "source_id": saved.source_id, "target_id": saved.target_id},
        )
        return saved.to_dict()
    except GraphScopeViolationError as e:
        raise HTTPException(403, str(e)) from e


@router.get("/entities/{entity_id}/neighbors", response_model=list[GraphPathOut])
async def get_neighbors(
    project_id: str,
    entity_id: str,
    direction: str = Query(default="both", pattern="^(in|out|both)$"),
    max_depth: int = Query(default=1, ge=1, le=5),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Traverse relationships around an entity with end-to-end scope verification."""
    adapter = get_graph_adapter()
    paths = await adapter.get_neighbors(
        tenant_id, project_id, entity_id, direction=direction, max_depth=max_depth, limit=limit
    )
    return [p.to_dict() for p in paths]


@router.get("/shortest-path", response_model=GraphPathOut)
async def shortest_path(
    project_id: str,
    start_id: str = Query(...),
    end_id: str = Query(...),
    max_depth: int = Query(default=5, ge=1, le=10),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """Find native shortest path between two entities within scope."""
    adapter = get_graph_adapter()
    try:
        path = await adapter.shortest_path(
            tenant_id, project_id, start_id, end_id, max_depth=max_depth
        )
    except GraphScopeViolationError as e:
        raise HTTPException(404, str(e)) from e
    if path is None:
        raise HTTPException(404, "No path found within authorized scope")
    return path.to_dict()


@router.delete("/relationships/{rel_id}", status_code=204)
async def delete_relationship(
    project_id: str,
    rel_id: str,
    tenant_id: str = Depends(current_tenant_id),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Delete a relationship by ID within scope."""
    adapter = get_graph_adapter()
    deleted = await adapter.delete_relationship(tenant_id, project_id, rel_id)
    if not deleted:
        raise HTTPException(404, "Relationship not found")
    await AuditService.log(
        tenant_id=tenant_id,
        project_id=project_id,
        action="graph.relationship.delete",
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        resource_type="graph_relationship",
        resource_id=rel_id,
    )


# --- Dynamic Ontology Registry Endpoints ---

@router.get("/ontology/entity-types", response_model=list[OntologyEntityTypeOut])
async def list_ontology_entity_types(
    project_id: str,
    status: str | None = None,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """List approved and scoped Knowledge Graph entity types."""
    types = await OntologyRegistryService.list_entity_types(
        session, tenant_id, project_id, status=status
    )
    return [
        OntologyEntityTypeOut(
            id=t.id,
            tenant_id=t.tenant_id,
            project_id=t.project_id,
            canonical_key=t.canonical_key,
            display_name=t.display_name,
            description=t.description,
            aliases=t.aliases or [],
            status=t.status,
            provenance=t.provenance,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in types
    ]


@router.post("/ontology/entity-types", response_model=OntologyEntityTypeOut, status_code=201)
async def register_ontology_entity_type(
    project_id: str,
    body: OntologyEntityTypeIn,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Register or approve an entity type definition in project scope."""
    ent_type = await OntologyRegistryService.register_entity_type(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        canonical_key=body.canonical_key,
        display_name=body.display_name,
        description=body.description,
        aliases=body.aliases,
        status=body.status,
        provenance="human_approved",
    )
    await AuditService.log(
        tenant_id=tenant_id,
        project_id=project_id,
        action="graph.ontology.entity_type.create",
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        resource_type="ontology_entity_type",
        resource_id=ent_type.id,
        meta={"canonical_key": ent_type.canonical_key},
    )
    return OntologyEntityTypeOut(
        id=ent_type.id,
        tenant_id=ent_type.tenant_id,
        project_id=ent_type.project_id,
        canonical_key=ent_type.canonical_key,
        display_name=ent_type.display_name,
        description=ent_type.description,
        aliases=ent_type.aliases or [],
        status=ent_type.status,
        provenance=ent_type.provenance,
        created_at=ent_type.created_at,
        updated_at=ent_type.updated_at,
    )


@router.get("/ontology/relationship-types", response_model=list[OntologyRelationshipTypeOut])
async def list_ontology_relationship_types(
    project_id: str,
    status: str | None = None,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(require_role("viewer")),
):
    """List approved and scoped Knowledge Graph relationship types."""
    types = await OntologyRegistryService.list_relationship_types(
        session, tenant_id, project_id, status=status
    )
    return [
        OntologyRelationshipTypeOut(
            id=t.id,
            tenant_id=t.tenant_id,
            project_id=t.project_id,
            canonical_key=t.canonical_key,
            description=t.description,
            allowed_source_types=t.allowed_source_types or [],
            allowed_target_types=t.allowed_target_types or [],
            direction_semantics=t.direction_semantics,
            aliases=t.aliases or [],
            status=t.status,
            provenance=t.provenance,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in types
    ]


@router.post("/ontology/relationship-types", response_model=OntologyRelationshipTypeOut, status_code=201)
async def register_ontology_relationship_type(
    project_id: str,
    body: OntologyRelationshipTypeIn,
    tenant_id: str = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role("editor")),
):
    """Register or approve a relationship type definition in project scope."""
    rel_type = await OntologyRegistryService.register_relationship_type(
        session=session,
        tenant_id=tenant_id,
        project_id=project_id,
        canonical_key=body.canonical_key,
        description=body.description,
        allowed_source_types=body.allowed_source_types,
        allowed_target_types=body.allowed_target_types,
        direction_semantics=body.direction_semantics,
        aliases=body.aliases,
        status=body.status,
        provenance="human_approved",
    )
    await AuditService.log(
        tenant_id=tenant_id,
        project_id=project_id,
        action="graph.ontology.relationship_type.create",
        actor_id=user.id if user else None,
        actor_email=user.email if user else None,
        resource_type="ontology_relationship_type",
        resource_id=rel_type.id,
        meta={"canonical_key": rel_type.canonical_key},
    )
    return OntologyRelationshipTypeOut(
        id=rel_type.id,
        tenant_id=rel_type.tenant_id,
        project_id=rel_type.project_id,
        canonical_key=rel_type.canonical_key,
        description=rel_type.description,
        allowed_source_types=rel_type.allowed_source_types or [],
        allowed_target_types=rel_type.allowed_target_types or [],
        direction_semantics=rel_type.direction_semantics,
        aliases=rel_type.aliases or [],
        status=rel_type.status,
        provenance=rel_type.provenance,
        created_at=rel_type.created_at,
        updated_at=rel_type.updated_at,
    )
