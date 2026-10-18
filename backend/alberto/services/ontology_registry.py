"""Persistent Dynamic Ontology Registry for Knowledge Graph.

Manages:
- Tenant/project-scoped canonical entity types and relationship types.
- Alias resolution and synonym mappings.
- Persistent entity classification mappings learned from human review.
- Lifecycle tracking: approved | pending_approval | deprecated | rejected.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.models.entities import (
    OntologyEntityMapping,
    OntologyEntityType,
    OntologyRelationshipType,
)

logger = logging.getLogger("alberto.services.ontology_registry")

# Canonical seed definitions for bootstrap
DEFAULT_ENTITY_TYPES: list[dict[str, Any]] = [
    {
        "canonical_key": "operating_system",
        "display_name": "Operating System",
        "description": "Operating system or software platform running on hardware.",
        "aliases": ["os", "operating system", "distro"],
    },
    {
        "canonical_key": "device",
        "display_name": "Device",
        "description": "Physical hardware device, appliance, computer, or machine.",
        "aliases": ["machine"],
    },
    {
        "canonical_key": "hardware",
        "display_name": "Hardware",
        "description": "Hardware system or physical component.",
        "aliases": [],
    },
    {
        "canonical_key": "host",
        "display_name": "Host",
        "description": "Host machine or network node.",
        "aliases": [],
    },
    {
        "canonical_key": "appliance",
        "display_name": "Appliance",
        "description": "Physical appliance or dedicated equipment.",
        "aliases": [],
    },
    {
        "canonical_key": "application",
        "display_name": "Application",
        "description": "End-user software application, client, or utility.",
        "aliases": ["app", "client"],
    },
    {
        "canonical_key": "software",
        "display_name": "Software",
        "description": "Software program, system, or utility.",
        "aliases": [],
    },
    {
        "canonical_key": "container_runtime",
        "display_name": "Container Runtime",
        "description": "Container runtime, virtualization engine, or container system (e.g. Docker, Podman).",
        "aliases": ["container", "docker", "podman"],
    },
    {
        "canonical_key": "inference_framework",
        "display_name": "Inference Framework",
        "description": "Software used for AI model inference and execution.",
        "aliases": ["inference_engine", "model_framework"],
    },
    {
        "canonical_key": "framework",
        "display_name": "Framework",
        "description": "Development or inference software framework, engine, or library.",
        "aliases": ["library", "engine", "sdk", "runtime"],
    },
    {
        "canonical_key": "model",
        "display_name": "Model",
        "description": "AI or machine learning model.",
        "aliases": ["llm", "weights", "checkpoint"],
    },
    {
        "canonical_key": "modelrunner",
        "display_name": "Model Runner",
        "description": "Local or remote model execution engine or server.",
        "aliases": ["runner", "inference_server"],
    },
    {
        "canonical_key": "service",
        "display_name": "Service",
        "description": "Background network service, daemon, or API.",
        "aliases": ["daemon", "microservice", "backend"],
    },
    {
        "canonical_key": "platform",
        "display_name": "Platform",
        "description": "Computing, cloud, or runtime execution platform.",
        "aliases": ["env", "environment"],
    },
    {
        "canonical_key": "person",
        "display_name": "Person",
        "description": "Human individual or person.",
        "aliases": ["user", "human"],
    },
    {
        "canonical_key": "location",
        "display_name": "Location",
        "description": "Physical location, room, or space.",
        "aliases": ["place", "room"],
    },
    {
        "canonical_key": "technology",
        "display_name": "Technology",
        "description": "General technical standard, protocol, or technology.",
        "aliases": ["tech", "protocol", "standard"],
    },
    {
        "canonical_key": "concept",
        "display_name": "Concept",
        "description": "Abstract concept, idea, or domain topic.",
        "aliases": ["idea"],
    },
    {
        "canonical_key": "topic",
        "display_name": "Topic",
        "description": "Domain topic or subject area.",
        "aliases": [],
    },
    {
        "canonical_key": "project",
        "display_name": "Project",
        "description": "Work initiative, codebase, or project.",
        "aliases": ["initiative"],
    },
]

DEFAULT_RELATIONSHIP_TYPES: list[dict[str, Any]] = [
    {
        "canonical_key": "RUNS",
        "description": "Host, device, or platform executes a software system, service, or model.",
        "allowed_source_types": ["device", "platform", "modelrunner"],
        "allowed_target_types": ["operating_system", "application", "model", "service"],
        "direction_semantics": "source_to_target",
        "aliases": ["EXECUTES"],
    },
    {
        "canonical_key": "RUNS_ON",
        "description": "Software, container, or service executes on a host, platform, or hardware device.",
        "allowed_source_types": ["application", "service", "modelrunner", "operating_system"],
        "allowed_target_types": ["device", "platform", "operating_system"],
        "direction_semantics": "source_to_target",
        "aliases": ["EXECUTED_ON", "HOSTED_BY"],
    },
    {
        "canonical_key": "DEPLOYED_VIA",
        "description": "Application or service is deployed using a specified container or runtime technology.",
        "allowed_source_types": ["application", "service", "modelrunner"],
        "allowed_target_types": ["application", "platform", "technology"],
        "direction_semantics": "source_to_target",
        "aliases": ["CONTAINERIZED_WITH", "HOSTED_ON"],
    },
    {
        "canonical_key": "PREFERS",
        "description": "Subject prefers a tool, technology, or configuration option.",
        "allowed_source_types": ["person"],
        "allowed_target_types": [],
        "direction_semantics": "source_to_target",
        "aliases": ["FAVORS"],
    },
    {
        "canonical_key": "USES",
        "description": "Entity uses a tool, technology, or platform.",
        "allowed_source_types": [],
        "allowed_target_types": [],
        "direction_semantics": "source_to_target",
        "aliases": ["UTILIZES"],
    },
    {
        "canonical_key": "LOCATED_IN",
        "description": "Entity is located in a physical location.",
        "allowed_source_types": ["device", "person"],
        "allowed_target_types": ["location"],
        "direction_semantics": "source_to_target",
        "aliases": ["IN", "RESIDES_AT"],
    },
    {
        "canonical_key": "MANAGES",
        "description": "Entity manages or controls another entity.",
        "allowed_source_types": ["person", "application", "service"],
        "allowed_target_types": [],
        "direction_semantics": "source_to_target",
        "aliases": ["CONTROLS", "ADMINISTERS"],
    },
    {
        "canonical_key": "OWNS",
        "description": "Subject owns a device, asset, or project.",
        "allowed_source_types": ["person"],
        "allowed_target_types": ["device", "project"],
        "direction_semantics": "source_to_target",
        "aliases": ["POSSESSES"],
    },
    {
        "canonical_key": "CONNECTS_TO",
        "description": "Network or physical connection between entities.",
        "allowed_source_types": [],
        "allowed_target_types": [],
        "direction_semantics": "source_to_target",
        "aliases": ["LINKS_TO", "COMMUNICATES_WITH"],
    },
    {
        "canonical_key": "PART_OF",
        "description": "Entity is part of a larger system or collection.",
        "allowed_source_types": [],
        "allowed_target_types": [],
        "direction_semantics": "source_to_target",
        "aliases": ["COMPONENT_OF", "SUBSET_OF"],
    },
    {
        "canonical_key": "REQUIRES",
        "description": "Entity requires another entity as a prerequisite.",
        "allowed_source_types": [],
        "allowed_target_types": [],
        "direction_semantics": "source_to_target",
        "aliases": ["DEPENDS_ON"],
    },
    {
        "canonical_key": "WORKS_WITH",
        "description": "Entity is interoperable with another entity.",
        "allowed_source_types": [],
        "allowed_target_types": [],
        "direction_semantics": "source_to_target",
        "aliases": ["COMPATIBLE_WITH"],
    },
    {
        "canonical_key": "RELATES_TO",
        "description": "General semantic relationship between entities.",
        "allowed_source_types": [],
        "allowed_target_types": [],
        "direction_semantics": "source_to_target",
        "aliases": ["ASSOCIATED_WITH"],
    },
]

# Baseline entity classification seed mappings
DEFAULT_ENTITY_MAPPINGS: dict[str, str] = {
    # Operating systems
    "macos": "operating_system",
    "mac os": "operating_system",
    "os x": "operating_system",
    "darwin": "operating_system",
    "windows": "operating_system",
    "win11": "operating_system",
    "win10": "operating_system",
    "linux": "operating_system",
    "ubuntu": "operating_system",
    "debian": "operating_system",
    "fedora": "operating_system",
    "arch": "operating_system",
    "arch linux": "operating_system",
    "centos": "operating_system",
    "redhat": "operating_system",
    "rhel": "operating_system",
    "alpine": "operating_system",
    "ios": "operating_system",
    "ipados": "operating_system",
    "android": "operating_system",
    "freebsd": "operating_system",
    "openbsd": "operating_system",
    "unix": "operating_system",
    # Hardware devices
    "mac": "device",
    "mac mini": "device",
    "mac studio": "device",
    "macbook": "device",
    "macbook pro": "device",
    "macbook air": "device",
    "imac": "device",
    "mac pro": "device",
    "pc": "device",
    "laptop": "device",
    "desktop": "device",
    "raspberry pi": "device",
    "iphone": "device",
    "ipad": "device",
    # Frameworks & applications
    "olmx": "application",
    "ollama": "application",
    "lm studio": "application",
    "vllm": "framework",
    "llama.cpp": "framework",
    "tgi": "framework",
    "pytorch": "framework",
    "tensorflow": "framework",
    "transformers": "framework",
    "langchain": "framework",
    "docker": "application",
}


class OntologyRegistryService:
    """Dynamic Ontology Registry for Knowledge Graph entities and relationships."""

    @staticmethod
    def canonicalize_key(key: str) -> str:
        """Clean lowercase key for entity types."""
        return re.sub(r"[^a-z0-9_]", "_", (key or "").strip().lower()).strip("_")

    @staticmethod
    def canonicalize_rel_key(key: str) -> str:
        """Clean uppercase key for relationship types."""
        return re.sub(r"[^A-Z0-9_]", "_", (key or "").strip().upper()).strip("_")

    @classmethod
    async def ensure_seed_definitions(
        cls, session: AsyncSession, tenant_id: str, project_id: str
    ) -> None:
        """Seed default canonical ontology definitions if not already present."""
        # 1. Entity types
        existing_ents = (
            await session.execute(
                select(OntologyEntityType.canonical_key).where(
                    OntologyEntityType.tenant_id == tenant_id,
                    OntologyEntityType.project_id == project_id,
                )
            )
        ).scalars().all()
        existing_ent_keys = set(existing_ents)

        for d in DEFAULT_ENTITY_TYPES:
            if d["canonical_key"] not in existing_ent_keys:
                session.add(
                    OntologyEntityType(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        canonical_key=d["canonical_key"],
                        display_name=d["display_name"],
                        description=d["description"],
                        aliases=d["aliases"],
                        status="approved",
                        provenance="system_seed",
                    )
                )

        # 2. Relationship types
        existing_rels = (
            await session.execute(
                select(OntologyRelationshipType.canonical_key).where(
                    OntologyRelationshipType.tenant_id == tenant_id,
                    OntologyRelationshipType.project_id == project_id,
                )
            )
        ).scalars().all()
        existing_rel_keys = set(existing_rels)

        for r in DEFAULT_RELATIONSHIP_TYPES:
            if r["canonical_key"] not in existing_rel_keys:
                session.add(
                    OntologyRelationshipType(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        canonical_key=r["canonical_key"],
                        description=r["description"],
                        allowed_source_types=r["allowed_source_types"],
                        allowed_target_types=r["allowed_target_types"],
                        direction_semantics=r["direction_semantics"],
                        aliases=r["aliases"],
                        status="approved",
                        provenance="system_seed",
                    )
                )

        # 3. Seed entity mappings
        existing_maps = (
            await session.execute(
                select(OntologyEntityMapping.entity_canonical_name).where(
                    OntologyEntityMapping.tenant_id == tenant_id,
                    OntologyEntityMapping.project_id == project_id,
                )
            )
        ).scalars().all()
        existing_map_names = set(existing_maps)

        for name, target_type in DEFAULT_ENTITY_MAPPINGS.items():
            if name not in existing_map_names:
                session.add(
                    OntologyEntityMapping(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        entity_canonical_name=name,
                        target_entity_type=target_type,
                        provenance="seed",
                        status="active",
                    )
                )

        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.debug("Seed ontology definitions already committed or race: %s", e)

    @classmethod
    async def get_entity_mapping(
        cls, session: AsyncSession | None, tenant_id: str, project_id: str, entity_name: str
    ) -> str | None:
        """Resolve learned entity mapping from canonical entity name."""
        c_name = (entity_name or "").strip().lower()
        if not c_name:
            return None

        if session is not None:
            m = (
                await session.execute(
                    select(OntologyEntityMapping).where(
                        OntologyEntityMapping.tenant_id == tenant_id,
                        OntologyEntityMapping.project_id == project_id,
                        OntologyEntityMapping.entity_canonical_name == c_name,
                        OntologyEntityMapping.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if m:
                return m.target_entity_type

        # Fallback to in-memory default seed dictionary
        if c_name in DEFAULT_ENTITY_MAPPINGS:
            return DEFAULT_ENTITY_MAPPINGS[c_name]
        for k, v in DEFAULT_ENTITY_MAPPINGS.items():
            if c_name.startswith(f"{k} "):
                return v
        return None

    @classmethod
    async def resolve_entity_type(
        cls, session: AsyncSession | None, tenant_id: str, project_id: str, raw_kind: str
    ) -> tuple[str | None, str | None]:
        """Resolve a raw kind to canonical entity key and approval status.
        Returns: (canonical_key, status) or (None, None) if not found.
        """
        k = cls.canonicalize_key(raw_kind)
        if not k:
            return None, None

        if session is not None:
            # 1. Exact match in DB
            exact = (
                await session.execute(
                    select(OntologyEntityType).where(
                        OntologyEntityType.tenant_id == tenant_id,
                        OntologyEntityType.project_id == project_id,
                        OntologyEntityType.canonical_key == k,
                    )
                )
            ).scalar_one_or_none()
            if exact:
                return exact.canonical_key, exact.status

            # 2. Check aliases in DB
            all_types = (
                await session.execute(
                    select(OntologyEntityType).where(
                        OntologyEntityType.tenant_id == tenant_id,
                        OntologyEntityType.project_id == project_id,
                    )
                )
            ).scalars().all()
            for t in all_types:
                aliases = [a.lower() for a in (t.aliases or [])]
                if k in aliases or raw_kind.lower() in aliases:
                    return t.canonical_key, t.status

        # Fallback to default in-memory definitions
        for d in DEFAULT_ENTITY_TYPES:
            if d["canonical_key"] == k:
                return d["canonical_key"], "approved"
        for d in DEFAULT_ENTITY_TYPES:
            if k in [a.lower() for a in d["aliases"]]:
                return d["canonical_key"], "approved"

        return None, None

    @classmethod
    async def resolve_relationship_type(
        cls, session: AsyncSession | None, tenant_id: str, project_id: str, raw_kind: str
    ) -> tuple[str | None, str | None]:
        """Resolve a raw relationship kind to canonical uppercase key and approval status.
        Returns: (canonical_key, status) or (None, None) if not found.
        """
        k = cls.canonicalize_rel_key(raw_kind)
        if not k:
            return None, None

        if session is not None:
            # 1. Exact match in DB
            exact = (
                await session.execute(
                    select(OntologyRelationshipType).where(
                        OntologyRelationshipType.tenant_id == tenant_id,
                        OntologyRelationshipType.project_id == project_id,
                        OntologyRelationshipType.canonical_key == k,
                    )
                )
            ).scalar_one_or_none()
            if exact:
                return exact.canonical_key, exact.status

            # 2. Check aliases in DB
            all_types = (
                await session.execute(
                    select(OntologyRelationshipType).where(
                        OntologyRelationshipType.tenant_id == tenant_id,
                        OntologyRelationshipType.project_id == project_id,
                    )
                )
            ).scalars().all()
            for t in all_types:
                aliases = [a.upper() for a in (t.aliases or [])]
                if k in aliases or raw_kind.upper() in aliases:
                    return t.canonical_key, t.status

        # Fallback to default in-memory definitions
        for d in DEFAULT_RELATIONSHIP_TYPES:
            if d["canonical_key"] == k:
                return d["canonical_key"], "approved"
            if k in [a.upper() for a in d["aliases"]]:
                return d["canonical_key"], "approved"

        return None, None

    @classmethod
    async def list_entity_types(
        cls, session: AsyncSession, tenant_id: str, project_id: str, status: str | None = None
    ) -> list[OntologyEntityType]:
        """List entity types registered in scope."""
        await cls.ensure_seed_definitions(session, tenant_id, project_id)
        stmt = select(OntologyEntityType).where(
            OntologyEntityType.tenant_id == tenant_id,
            OntologyEntityType.project_id == project_id,
        )
        if status:
            stmt = stmt.where(OntologyEntityType.status == status)
        res = await session.execute(stmt.order_by(OntologyEntityType.canonical_key.asc()))
        return list(res.scalars().all())

    @classmethod
    async def list_relationship_types(
        cls, session: AsyncSession, tenant_id: str, project_id: str, status: str | None = None
    ) -> list[OntologyRelationshipType]:
        """List relationship types registered in scope."""
        await cls.ensure_seed_definitions(session, tenant_id, project_id)
        stmt = select(OntologyRelationshipType).where(
            OntologyRelationshipType.tenant_id == tenant_id,
            OntologyRelationshipType.project_id == project_id,
        )
        if status:
            stmt = stmt.where(OntologyRelationshipType.status == status)
        res = await session.execute(stmt.order_by(OntologyRelationshipType.canonical_key.asc()))
        return list(res.scalars().all())

    @classmethod
    async def register_entity_type(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        canonical_key: str,
        display_name: str | None = None,
        description: str = "",
        aliases: list[str] | None = None,
        status: str = "approved",
        provenance: str = "human_approved",
    ) -> OntologyEntityType:
        """Register or update an entity type definition in project scope."""
        k = cls.canonicalize_key(canonical_key)
        existing = (
            await session.execute(
                select(OntologyEntityType).where(
                    OntologyEntityType.tenant_id == tenant_id,
                    OntologyEntityType.project_id == project_id,
                    OntologyEntityType.canonical_key == k,
                )
            )
        ).scalar_one_or_none()

        d_name = display_name or k.replace("_", " ").title()
        if existing:
            existing.display_name = d_name
            if description:
                existing.description = description
            if aliases:
                existing.aliases = list(set(existing.aliases + aliases))
            existing.status = status
            existing.provenance = provenance
            await session.commit()
            return existing

        created = OntologyEntityType(
            tenant_id=tenant_id,
            project_id=project_id,
            canonical_key=k,
            display_name=d_name,
            description=description,
            aliases=aliases or [],
            status=status,
            provenance=provenance,
        )
        session.add(created)
        await session.commit()
        return created

    @classmethod
    async def register_relationship_type(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        canonical_key: str,
        description: str = "",
        allowed_source_types: list[str] | None = None,
        allowed_target_types: list[str] | None = None,
        direction_semantics: str = "source_to_target",
        aliases: list[str] | None = None,
        status: str = "approved",
        provenance: str = "human_approved",
    ) -> OntologyRelationshipType:
        """Register or update a relationship type definition in project scope."""
        k = cls.canonicalize_rel_key(canonical_key)
        existing = (
            await session.execute(
                select(OntologyRelationshipType).where(
                    OntologyRelationshipType.tenant_id == tenant_id,
                    OntologyRelationshipType.project_id == project_id,
                    OntologyRelationshipType.canonical_key == k,
                )
            )
        ).scalar_one_or_none()

        if existing:
            if description:
                existing.description = description
            if allowed_source_types is not None:
                existing.allowed_source_types = allowed_source_types
            if allowed_target_types is not None:
                existing.allowed_target_types = allowed_target_types
            existing.direction_semantics = direction_semantics
            if aliases:
                existing.aliases = list(set(existing.aliases + aliases))
            existing.status = status
            existing.provenance = provenance
            await session.commit()
            return existing

        created = OntologyRelationshipType(
            tenant_id=tenant_id,
            project_id=project_id,
            canonical_key=k,
            description=description,
            allowed_source_types=allowed_source_types or [],
            allowed_target_types=allowed_target_types or [],
            direction_semantics=direction_semantics,
            aliases=aliases or [],
            status=status,
            provenance=provenance,
        )
        session.add(created)
        await session.commit()
        return created

    @classmethod
    async def record_entity_mapping(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        entity_name: str,
        target_type: str,
        provenance: str = "human_correction",
        status: str = "active",
    ) -> OntologyEntityMapping:
        """Persist a learned entity-to-type mapping (e.g. macOS -> operating_system)."""
        c_name = (entity_name or "").strip().lower()
        t_key = cls.canonicalize_key(target_type)

        existing = (
            await session.execute(
                select(OntologyEntityMapping).where(
                    OntologyEntityMapping.tenant_id == tenant_id,
                    OntologyEntityMapping.project_id == project_id,
                    OntologyEntityMapping.entity_canonical_name == c_name,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.target_entity_type = t_key
            existing.provenance = provenance
            existing.status = status
            await session.commit()
            return existing

        created = OntologyEntityMapping(
            tenant_id=tenant_id,
            project_id=project_id,
            entity_canonical_name=c_name,
            target_entity_type=t_key,
            provenance=provenance,
            status=status,
        )
        session.add(created)
        await session.commit()
        return created


OntologyRegistry = OntologyRegistryService
