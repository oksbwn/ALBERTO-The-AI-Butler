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
from alberto.schemas.memory_curator import EntityCandidate, RelationshipCandidate

logger = logging.getLogger("alberto.services.graph_manager")

VALID_RELATIONSHIP_KINDS = {
    "RUNS",
    "PREFERS",
    "USES",
    "LOCATED_IN",
    "MANAGES",
    "OWNS",
    "CONNECTS_TO",
    "PART_OF",
    "REQUIRES",
    "WORKS_WITH",
    "RELATES_TO",
}


VALID_ENTITY_KINDS = {
    "device",
    "hardware",
    "appliance",
    "host",
    "operating_system",
    "platform",
    "application",
    "software",
    "framework",
    "model",
    "modelrunner",
    "person",
    "location",
    "service",
    "technology",
    "topic",
    "concept",
    "project",
}

KNOWN_OPERATING_SYSTEMS = {
    "macos",
    "mac os",
    "os x",
    "darwin",
    "windows",
    "win11",
    "win10",
    "win8",
    "win7",
    "linux",
    "ubuntu",
    "debian",
    "fedora",
    "arch",
    "arch linux",
    "centos",
    "redhat",
    "rhel",
    "alpine",
    "ios",
    "ipados",
    "watchos",
    "android",
    "freebsd",
    "openbsd",
    "unix",
}

KNOWN_HARDWARE_DEVICES = {
    "mac",
    "mac mini",
    "mac studio",
    "macbook",
    "macbook pro",
    "macbook air",
    "imac",
    "mac pro",
    "pc",
    "laptop",
    "desktop",
    "server",
    "raspberry pi",
    "iphone",
    "ipad",
    "android phone",
}

KNOWN_FRAMEWORKS_AND_APPS = {
    "olmx",
    "ollama",
    "lm studio",
    "vllm",
    "llama.cpp",
    "tgi",
    "pytorch",
    "tensorflow",
    "transformers",
    "langchain",
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

            # Deterministic entity classification rules (unambiguous known types only)
            if c_canon in KNOWN_OPERATING_SYSTEMS:
                if k in ("device", "host", "hardware", "concept"):
                    logger.info("Deterministic entity kind normalization: '%s' is an operating system, not %s", c_name, k)
                    cand.kind = "operating_system"
                    k = "operating_system"
            elif c_canon in KNOWN_HARDWARE_DEVICES:
                if k in ("operating_system", "platform", "application", "framework"):
                    logger.info("Deterministic entity kind normalization: '%s' is a physical device, not %s", c_name, k)
                    cand.kind = "device"
                    k = "device"
            elif c_canon in KNOWN_FRAMEWORKS_AND_APPS:
                if k in ("device", "host"):
                    logger.info("Deterministic entity kind normalization: '%s' is an application/framework, not %s", c_name, k)
                    cand.kind = "application"
                    k = "application"

            if k not in VALID_ENTITY_KINDS:
                requires_review = True
                review_reasons.append(f"Unrecognized entity kind '{cand.kind}' for candidate '{c_name}'")

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
                if c_canon in KNOWN_OPERATING_SYSTEMS and existing_k == "device":
                    existing.kind = "operating_system"
                    existing_k = "operating_system"

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

            clean_kind = re.sub(r"[^A-Z0-9_]", "_", rel.kind.strip().upper())
            if clean_kind not in VALID_RELATIONSHIP_KINDS:
                requires_review = True
                review_reasons.append(
                    f"Unknown relationship kind '{rel.kind}' (normalized: '{clean_kind}') requires confirmation"
                )
                clean_kind = "RELATES_TO"

            rel_conf = float(rel.confidence) if rel.confidence is not None else 0.5
            if rel_conf < 0.75:
                requires_review = True
                review_reasons.append(f"Low confidence ({rel_conf:.2f}) on relationship candidate '{clean_kind}'")

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
    ) -> dict[str, Any]:
        """Validate and apply candidates ONLY if acceptance policy passes without review."""
        val = await cls.resolve_and_validate(
            tenant_id=tenant_id,
            project_id=project_id,
            candidate_entities=candidate_entities,
            candidate_relationships=candidate_relationships,
            source_ref=source_ref,
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
