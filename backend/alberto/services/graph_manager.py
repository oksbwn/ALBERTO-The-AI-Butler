"""Graph Manager: Deterministic validation, entity resolution, and scoped graph operations.

Enforces:
- Deterministic-first entity canonicalization and alias resolution.
- Scoped graph operations strictly within (tenant_id, project_id).
- Typed relationship validation against existing entities.
- Single-process ownership via LadybugGraphAdapter.
- Ambiguity detection (flags requires_review rather than fabricating certainty).
- No arbitrary model-generated Cypher.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from alberto.knowledge.graph import (
    GraphEntity,
    GraphRelationship,
    GraphScopeViolationError,
    get_graph_adapter,
    make_entity_id,
    make_relationship_id,
)
from alberto.schemas.memory_curator import (
    CANONICAL_ENTITY_KINDS,
    CANONICAL_RELATIONSHIP_KINDS,
    EntityCandidate,
    RelationshipCandidate,
)
from alberto.services.ontology_registry import (
    DEFAULT_ENTITY_MAPPINGS,
    OntologyRegistryService,
)

logger = logging.getLogger("alberto.services.graph_manager")

VALID_RELATIONSHIP_KINDS = set(CANONICAL_RELATIONSHIP_KINDS)
VALID_ENTITY_KINDS = set(CANONICAL_ENTITY_KINDS)

# Legacy alias reference mappings preserved for test and module backwards compatibility
KNOWN_OPERATING_SYSTEMS = {
    k for k, v in DEFAULT_ENTITY_MAPPINGS.items() if v == "operating_system"
}
KNOWN_HARDWARE_DEVICES = {
    k for k, v in DEFAULT_ENTITY_MAPPINGS.items() if v == "device"
}
KNOWN_FRAMEWORKS_AND_APPS = {
    k for k, v in DEFAULT_ENTITY_MAPPINGS.items() if v in ("application", "framework")
}

COMPATIBLE_KIND_SETS = [
    {"operating_system", "platform"},
    {"application", "framework", "modelrunner", "software"},
    {"device", "host", "hardware", "appliance"},
]

GENERIC_ENTITY_NAMES = {
    "server",
    "router",
    "laptop",
    "pc",
    "computer",
    "device",
    "application",
    "app",
    "service",
    "wife",
    "husband",
    "friend",
    "manager",
    "room",
    "home",
    "bot",
    "assistant",
    "system",
    "client",
    "model",
}


class GraphManagerService:
    """Coordinates deterministic Knowledge Graph updates for Alberto."""

    @staticmethod
    def canonicalize_name(name: str) -> str:
        """Produce a clean lowercase canonical name for lookup and deduplication."""
        return re.sub(r"\s+", " ", (name or "").strip().lower())

    @classmethod
    def _extract_aliases(cls, entity: GraphEntity) -> list[str]:
        """Extract explicit aliases from entity description if encoded."""
        if not entity.description:
            return []
        match = re.search(r"\[aliases:\s*([^\]]+)\]", entity.description, re.IGNORECASE)
        if match:
            return [cls.canonicalize_name(a.strip()) for a in match.group(1).split(",") if a.strip()]
        return []

    @classmethod
    async def resolve_and_validate(
        cls,
        tenant_id: str,
        project_id: str,
        candidate_entities: list[EntityCandidate],
        candidate_relationships: list[RelationshipCandidate],
        source_ref: str = "memory_curator",
        session: Any | None = None,
    ) -> dict[str, Any]:
        """Resolve canonical identities and validate candidates deterministically WITHOUT mutating graph.

        Returns:
            {
                "resolved_entities": list[GraphEntity],
                "resolved_relationships": list[GraphRelationship],
                "resolved_entity_map": dict[str, str],
                "requires_review": bool,
                "review_reasons": list[str],
            }
        """
        adapter = get_graph_adapter()
        review_reasons: list[str] = []
        requires_review = False

        # 1. Fetch existing entities in this scope for deterministic resolution
        existing_entities = await adapter.find_entities(tenant_id, project_id, limit=200)
        by_canonical: dict[str, list[GraphEntity]] = {}
        by_id: dict[str, GraphEntity] = {}

        for ent in existing_entities:
            by_id[ent.id] = ent
            canon = cls.canonicalize_name(ent.canonical_name or ent.name)
            by_canonical.setdefault(canon, []).append(ent)

        resolved_entities: list[GraphEntity] = []
        resolved_entity_map: dict[str, str] = {ent.id: ent.id for ent in existing_entities}

        # 2. Resolve Entities
        for cand in candidate_entities:
            c_name = cand.name.strip()
            if not c_name:
                continue

            # Confidence check on candidate entity
            cand_conf = float(cand.confidence) if cand.confidence is not None else 0.5
            if cand_conf < 0.75:
                requires_review = True
                review_reasons.append(f"Low confidence ({cand_conf:.2f}) on entity candidate '{c_name}'")

            c_canon = cls.canonicalize_name(c_name)
            k = (cand.kind or "").strip().lower()

            # 1. Learned entity mapping lookup (e.g. macOS -> operating_system, Mac mini -> device)
            mapped_type = await OntologyRegistryService.get_entity_mapping(
                session, tenant_id, project_id, c_canon
            )
            if mapped_type:
                if mapped_type == "operating_system" and k in ("device", "host", "hardware", "concept"):
                    logger.info("Learned ontology kind normalization: '%s' is an operating system, not %s", c_name, k)
                    cand.kind = "operating_system"
                    k = "operating_system"
                elif mapped_type == "device" and k in ("operating_system", "platform", "application", "framework"):
                    logger.info("Learned ontology kind normalization: '%s' is a physical device, not %s", c_name, k)
                    cand.kind = "device"
                    k = "device"
                elif mapped_type == "application" and k in ("device", "host", "unknown_software", "software", "tool"):
                    logger.info("Learned ontology kind normalization: '%s' is an application, not %s", c_name, k)
                    cand.kind = "application"
                    k = "application"
                elif k != mapped_type and (k in ("device", "concept", "hardware", "unknown_software") or k not in CANONICAL_ENTITY_KINDS):
                    cand.kind = mapped_type
                    k = mapped_type

            # 2. Dynamic ontology entity-type resolution
            resolved_k, k_status = await OntologyRegistryService.resolve_entity_type(
                session, tenant_id, project_id, k
            )
            if resolved_k:
                cand.kind = resolved_k
                k = resolved_k
                if k_status != "approved":
                    requires_review = True
                    review_reasons.append(
                        f"Entity type '{cand.kind}' proposed for '{c_name}' has status '{k_status}' and requires approval"
                    )
            else:
                # Novel entity kind proposal
                requires_review = True
                review_reasons.append(
                    f"Novel entity type '{cand.kind}' proposed for '{c_name}' requires human review and ontology approval"
                )

            matches = list(by_canonical.get(c_canon, []))

            # Check matching by explicit aliases
            if not matches:
                for ent in existing_entities:
                    aliases = cls._extract_aliases(ent)
                    if c_canon in aliases:
                        matches.append(ent)
                        break

            # Generic label guard: generic names like "server", "router", "wife"
            # should NOT silently merge with existing entities if identity is ungrounded
            if c_canon in GENERIC_ENTITY_NAMES and matches:
                requires_review = True
                review_reasons.append(
                    f"Ambiguous generic entity label '{c_name}': multiple real-world instances plausible"
                )

            chosen_entity: GraphEntity | None = None

            if len(matches) == 1:
                existing = matches[0]
                existing_k = (existing.kind or "").strip().lower()

                # Remediate/normalize existing entity kind if it was misclassified under older taxonomy
                if mapped_type and existing_k != mapped_type and existing_k in ("device", "concept"):
                    existing.kind = mapped_type
                    existing_k = mapped_type

                # Check kind compatibility
                is_compatible = (
                    existing_k == k
                    or k in ("concept", "topic")
                    or any(existing_k in s and k in s for s in COMPATIBLE_KIND_SETS)
                )

                if is_compatible:
                    chosen_entity = existing
                    if k in ("operating_system", "platform") and existing_k != k:
                        existing.kind = k
                    if cand.description and cand.description not in (existing.description or ""):
                        new_desc = f"{existing.description}; {cand.description}".strip("; ")
                        existing.description = new_desc
                        existing.confidence = max(existing.confidence, cand_conf)
                else:
                    requires_review = True
                    review_reasons.append(
                        f"Ambiguous entity '{c_name}': existing kind '{existing.kind}' vs candidate kind '{cand.kind}'"
                    )
            elif len(matches) > 1:
                requires_review = True
                review_reasons.append(
                    f"Ambiguous entity '{c_name}': multiple existing entities found ({len(matches)})"
                )

            if not chosen_entity:
                new_id = make_entity_id(cand.kind, c_name)
                desc = cand.description
                if cand.aliases:
                    alias_tag = f" [aliases: {', '.join(cand.aliases)}]"
                    if alias_tag not in desc:
                        desc = f"{desc}{alias_tag}".strip()
                chosen_entity = GraphEntity(
                    id=new_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    kind=cand.kind,
                    name=c_name,
                    canonical_name=c_canon,
                    description=desc,
                    source=source_ref,
                    confidence=cand_conf,
                )

            resolved_entities.append(chosen_entity)
            resolved_entity_map[cand.temporary_id] = chosen_entity.id
            resolved_entity_map[c_name.lower()] = chosen_entity.id
            resolved_entity_map[c_canon] = chosen_entity.id

        # 3. Resolve Relationships
        resolved_relationships: list[GraphRelationship] = []
        for rel in candidate_relationships:
            src_key = rel.source_ref.strip().lower()
            tgt_key = rel.target_ref.strip().lower()

            src_id = resolved_entity_map.get(rel.source_ref) or resolved_entity_map.get(src_key)
            tgt_id = resolved_entity_map.get(rel.target_ref) or resolved_entity_map.get(tgt_key)

            if not src_id or not tgt_id:
                requires_review = True
                review_reasons.append(
                    f"Unresolved relationship endpoints: source '{rel.source_ref}' or target '{rel.target_ref}'"
                )
                continue

            if src_id == tgt_id:
                continue

            # Dynamic ontology relationship-type resolution
            clean_kind = re.sub(r"[^A-Z0-9_]", "_", rel.kind.strip().upper())
            resolved_rel_k, rel_status = await OntologyRegistryService.resolve_relationship_type(
                session, tenant_id, project_id, rel.kind
            )
            if resolved_rel_k:
                clean_kind = resolved_rel_k
                if rel_status != "approved":
                    requires_review = True
                    review_reasons.append(
                        f"Relationship type '{clean_kind}' has status '{rel_status}' and requires approval"
                    )
            else:
                requires_review = True
                review_reasons.append(
                    f"Unknown relationship kind '{rel.kind}' (normalized: '{clean_kind}') requires confirmation and ontology approval"
                )
                clean_kind = "RELATES_TO"

            rel_conf = float(rel.confidence) if rel.confidence is not None else 0.5
            if rel_conf < 0.75:
                requires_review = True
                review_reasons.append(f"Low confidence ({rel_conf:.2f}) on relationship candidate '{clean_kind}'")

            # Directional semantic validation
            src_ent = by_id.get(src_id) or next((e for e in resolved_entities if e.id == src_id), None)
            tgt_ent = by_id.get(tgt_id) or next((e for e in resolved_entities if e.id == tgt_id), None)
            if src_ent and tgt_ent:
                src_k = (src_ent.kind or "").lower()
                tgt_k = (tgt_ent.kind or "").lower()
                if clean_kind == "RUNS" and src_k in ("application", "framework", "service") and tgt_k in ("device", "host", "platform"):
                    requires_review = True
                    review_reasons.append(
                        f"Possible inverted relationship direction: '{src_ent.name}' ({src_k}) RUNS '{tgt_ent.name}' ({tgt_k})"
                    )
                elif clean_kind == "DEPLOYED_VIA" and tgt_k in ("application", "framework") and src_k in ("platform", "device"):
                    requires_review = True
                    review_reasons.append(
                        f"Possible inverted deployment direction: '{src_ent.name}' DEPLOYED_VIA '{tgt_ent.name}'"
                    )

            rel_id = make_relationship_id(src_id, clean_kind, tgt_id)
            relationship = GraphRelationship(
                id=rel_id,
                source_id=src_id,
                target_id=tgt_id,
                kind=clean_kind,
                tenant_id=tenant_id,
                project_id=project_id,
                source=source_ref,
                confidence=rel_conf,
                provenance="memory_curator_extraction",
            )
            resolved_relationships.append(relationship)

        return {
            "resolved_entities": resolved_entities,
            "resolved_relationships": resolved_relationships,
            "resolved_entity_map": resolved_entity_map,
            "requires_review": requires_review,
            "review_reasons": review_reasons,
        }

    @classmethod
    async def apply_resolved(
        cls,
        tenant_id: str,
        project_id: str,
        resolved_entities: list[GraphEntity],
        resolved_relationships: list[GraphRelationship],
    ) -> dict[str, list[str]]:
        """Apply pre-validated, approved entities and relationships to LadybugDB."""
        adapter = get_graph_adapter()
        applied_entities: list[str] = []
        applied_relationships: list[str] = []

        for entity in resolved_entities:
            try:
                saved = await adapter.create_or_update_entity(entity)
                if saved.id not in applied_entities:
                    applied_entities.append(saved.id)
            except GraphScopeViolationError as e:
                logger.error("Scope violation creating entity %s: %s", entity.id, e)
                continue

        for relationship in resolved_relationships:
            try:
                saved_rel = await adapter.create_or_update_relationship(relationship)
                if saved_rel.id not in applied_relationships:
                    applied_relationships.append(saved_rel.id)
            except GraphScopeViolationError as e:
                logger.error("Scope violation creating relationship %s: %s", relationship.id, e)
                continue

        return {
            "applied_entities": applied_entities,
            "applied_relationships": applied_relationships,
        }

    @classmethod
    async def resolve_and_apply(
        cls,
        tenant_id: str,
        project_id: str,
        candidate_entities: list[EntityCandidate],
        candidate_relationships: list[RelationshipCandidate],
        source_ref: str = "memory_curator",
        session: Any | None = None,
    ) -> dict[str, Any]:
        """Validate and apply candidates ONLY if acceptance policy passes without review."""
        val = await cls.resolve_and_validate(
            tenant_id=tenant_id,
            project_id=project_id,
            candidate_entities=candidate_entities,
            candidate_relationships=candidate_relationships,
            source_ref=source_ref,
            session=session,
        )

        # STRICT INVARIANT: If review is required, DO NOT MUTATE THE GRAPH!
        if val["requires_review"]:
            return {
                "applied_entities": [],
                "applied_relationships": [],
                "resolved_entities": val["resolved_entities"],
                "resolved_relationships": val["resolved_relationships"],
                "requires_review": True,
                "review_reasons": val["review_reasons"],
            }

        app = await cls.apply_resolved(
            tenant_id=tenant_id,
            project_id=project_id,
            resolved_entities=val["resolved_entities"],
            resolved_relationships=val["resolved_relationships"],
        )

        return {
            "applied_entities": app["applied_entities"],
            "applied_relationships": app["applied_relationships"],
            "requires_review": False,
            "review_reasons": [],
        }

    @classmethod
    async def sweep_orphaned_entities(cls) -> int:
        """Scan Knowledge Graph and prune:
        1. Entities from deleted MCP integrations (source starts with mcp:<client_id> where client_id is not in DB).
        2. Entities from deleted Tools (source starts with tool:<tool_id> where tool_id is not in DB).
        3. Capability entities whose name is an exact match for a tool's name (self-referencing duplicate capability nodes).
        4. Redundant prefix capability nodes (e.g. 'HA: ha_config_get_scene').
        """
        from alberto.db.base import SessionLocal
        from alberto.models import McpClient, Tool
        from alberto.knowledge.graph import get_graph_adapter
        from sqlalchemy import select

        adapter = get_graph_adapter()
        purged = 0

        async with SessionLocal() as s:
            active_mcp_ids = set((await s.execute(select(McpClient.id))).scalars().all())
            active_tool_ids = set((await s.execute(select(Tool.id))).scalars().all())
            active_tool_names = set((await s.execute(select(Tool.name))).scalars().all())

            # Query all entities
            res = adapter._execute("MATCH (e:Entity) RETURN e.id, e.tenant_id, e.project_id, e.kind, e.name, e.source")
            to_delete: list[tuple[str, str, str]] = []
            while res.has_next():
                row = res.get_next()
                eid, tid, pid, kind, name, source = row[0], row[1], row[2], row[3], row[4], str(row[5] or "")

                # Check 1: Old MCP client
                if source.startswith("mcp:"):
                    parts = source.split(":")
                    if len(parts) >= 2 and parts[1] not in active_mcp_ids:
                        to_delete.append((tid, pid, eid))
                        continue

                # Check 2: Old tool
                if source.startswith("tool:"):
                    parts = source.split(":")
                    if len(parts) >= 2 and parts[1] not in active_tool_ids:
                        to_delete.append((tid, pid, eid))
                        continue

                # Check 3: Redundant capability node that shares the exact same name as a tool
                if kind == "capability" and name in active_tool_names:
                    to_delete.append((tid, pid, eid))
                    continue

                # Check 4: Redundant prefix capability (e.g. "HA: ha_config_get_scene" or "Home Assistant: ...")
                if kind == "capability" and any(name.endswith(f": {tname}") for tname in active_tool_names):
                    to_delete.append((tid, pid, eid))
                    continue

            for tid, pid, eid in to_delete:
                if await adapter.delete_entity(tid, pid, eid):
                    purged += 1

        return purged
