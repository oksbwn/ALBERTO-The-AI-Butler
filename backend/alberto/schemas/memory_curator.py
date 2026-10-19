"""Schemas for Memory Curator extraction and persistent memory management."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CANONICAL_MEMORY_KINDS: tuple[str, ...] = (
    "preference",
    "fact",
    "instruction",
    "profile",
    "technology",
    "home",
    "project",
)

CANONICAL_ENTITY_KINDS: tuple[str, ...] = (
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
)

CANONICAL_RELATIONSHIP_KINDS: tuple[str, ...] = (
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
)


class MemoryCandidate(BaseModel):
    """A durable memory candidate extracted from conversation."""

    kind: str = Field(
        default="preference",
        description=f"Category: {', '.join(CANONICAL_MEMORY_KINDS)}",
    )
    content: str = Field(description="The factual, durable statement to remember.")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    durability: Literal["long_term", "ephemeral"] = Field(
        default="long_term",
        description="Whether this is stable long-term knowledge or temporary chat context.",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Message IDs, roles, or text fragments proving this fact.",
    )
    operation: Literal["propose_upsert", "propose_replace", "propose_delete"] = Field(
        default="propose_upsert",
        description="Storage operation proposed.",
    )
    target_memory_id: str | None = Field(
        default=None,
        description="Existing memory ID if this operation modifies or supersedes an existing fact.",
    )
    supersedes_fact: str | None = Field(
        default=None,
        description="Summary of the older fact being replaced (e.g. 'Previously ran Qwen 7B').",
    )


class EntityCandidate(BaseModel):
    """A candidate Knowledge Graph entity node."""

    temporary_id: str = Field(description="Temporary ID scoped to this extraction (e.g. e1, e2).")
    name: str = Field(description="Entity name as explicitly stated (e.g. Mac mini, LM Studio).")
    kind: str = Field(
        default="concept",
        description=f"Entity type: {', '.join(CANONICAL_ENTITY_KINDS)}",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    description: str = Field(default="", description="Brief description or context.")
    aliases: list[str] = Field(default_factory=list, description="Known aliases explicitly supported by evidence.")
    evidence_refs: list[str] = Field(default_factory=list, description="Supporting evidence references.")


class RelationshipCandidate(BaseModel):
    """A candidate typed relationship between entities."""

    source_ref: str = Field(description="Source entity temporary_id or exact entity name.")
    target_ref: str = Field(description="Target entity temporary_id or exact entity name.")
    kind: str = Field(
        default="RELATES_TO",
        description=f"Controlled uppercase relationship kind: {', '.join(CANONICAL_RELATIONSHIP_KINDS)}",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list, description="Supporting evidence references.")


class ConflictItem(BaseModel):
    """A detected conflict between newly extracted facts and prior knowledge."""

    existing_content: str = Field(description="Previously stored content.")
    new_content: str = Field(description="Newly stated conflicting content.")
    reason: str = Field(description="Explanation of the conflict.")
    requires_review: bool = Field(default=False, description="Whether human review is required before applying.")


class MemoryCuratorOutput(BaseModel):
    """Single structured LLM extraction output for Memory Curator."""

    schema_version: int = Field(default=1)
    should_learn: bool = Field(
        default=False,
        description="True if durable facts, preferences, or entities worthy of persistence were found.",
    )
    memories: list[MemoryCandidate] = Field(default_factory=list)
    entities: list[EntityCandidate] = Field(default_factory=list)
    relationships: list[RelationshipCandidate] = Field(default_factory=list)
    conflicts: list[ConflictItem] = Field(default_factory=list)
    requires_review: bool = Field(
        default=False,
        description="True if any ambiguous identity, low confidence, or unresolved conflict requires user review.",
    )
    review_reason: str | None = Field(default=None, description="Explanation if review is required.")
    extraction_error: str | None = Field(default=None, description="Non-sensitive error if parsing or model call failed.")


# --- DTOs for APIs & Frontend ---

class MemoryRecordDetailOut(BaseModel):
    """Authoritative memory record output."""

    id: str
    tenant_id: str
    project_id: str
    scope: str
    text: str
    kind: str
    confidence: float
    provenance: str
    status: str
    source_ref: str | None = None
    superseded_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MemoryRecordUpdateIn(BaseModel):
    """Payload for updating or correcting an existing memory."""

    text: str | None = None
    kind: str | None = None
    status: str | None = None


class MemoryLearningSettingsIn(BaseModel):
    """Update memory learning configuration and model overrides."""

    memory_learning_enabled: bool | None = None
    tool_execution_learning_enabled: bool | None = None
    memory_curator_model: str | None = None
    graph_manager_model: str | None = None


class MemoryLearningSettingsOut(BaseModel):
    """Current memory learning configuration and status."""

    memory_learning_enabled: bool
    tool_execution_learning_enabled: bool = False
    memory_curator_model: str
    memory_curator_effective_model: str
    graph_manager_model: str
    graph_manager_effective_model: str
    operational_state: str
    last_learning_at: str | None = None


class LearningEventOut(BaseModel):
    """Learning lifecycle event record."""

    id: str
    tenant_id: str
    project_id: str
    source_event_id: str
    source_type: str
    status: str
    extraction_payload: dict[str, Any]
    error: str | None = None
    retry_count: int = 0
    requires_review: bool = False
    applied_memory_ids: list[str] = Field(default_factory=list)
    applied_graph_entity_ids: list[str] = Field(default_factory=list)
    applied_graph_rel_ids: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarkdownMemoryFileOut(BaseModel):
    """Inspected markdown memory file."""

    filename: str
    category: str
    size_bytes: int
    updated_at: str
    content: str | None = None


# --- Dynamic Ontology & HITL Approval DTOs ---

class CuratorAdvisorySuggestion(BaseModel):
    """Advisory recommendation from Memory Curator when warnings occur during review."""

    target_type: Literal["entity", "relationship"]
    target_ref: str = Field(description="Entity temporary_id / name or relationship index / label.")
    suggested_kind: str | None = None
    existing_type_mapping: str | None = None
    suggested_direction: Literal["normal", "reverse"] | None = None
    explanation: str = Field(default="", description="Grounding justification for the recommendation.")
    evidence_refs: list[str] = Field(default_factory=list)
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_new_ontology_definition: bool = False


class NodeApprovalEdit(BaseModel):
    """Reviewer modifications to candidate entity before approval."""

    temporary_id: str
    name: str | None = None
    kind: str | None = None
    description: str | None = None
    action: Literal["approve", "reject", "reclassify"] = "approve"
    is_new_ontology_type: bool = False
    ontology_type_description: str | None = None


class EdgeApprovalEdit(BaseModel):
    """Reviewer modifications to candidate relationship before approval."""

    source_ref: str | None = None
    target_ref: str | None = None
    kind: str | None = None
    direction: Literal["normal", "reverse"] = "normal"
    action: Literal["approve", "reject"] = "approve"
    is_new_ontology_type: bool = False
    ontology_type_description: str | None = None


class LearningEventApprovalIn(BaseModel):
    """Reviewer decision payload for learning event approval."""

    node_edits: list[NodeApprovalEdit] = Field(default_factory=list)
    edge_edits: list[EdgeApprovalEdit] = Field(default_factory=list)
    approved_memories: list[dict[str, Any]] | None = None


class OntologyEntityTypeOut(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    canonical_key: str
    display_name: str
    description: str
    aliases: list[str] = Field(default_factory=list)
    status: str
    provenance: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OntologyEntityTypeIn(BaseModel):
    canonical_key: str
    display_name: str | None = None
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    status: str = "approved"


class OntologyRelationshipTypeOut(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    canonical_key: str
    description: str
    allowed_source_types: list[str] = Field(default_factory=list)
    allowed_target_types: list[str] = Field(default_factory=list)
    direction_semantics: str = "source_to_target"
    aliases: list[str] = Field(default_factory=list)
    status: str
    provenance: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OntologyRelationshipTypeIn(BaseModel):
    canonical_key: str
    description: str = ""
    allowed_source_types: list[str] = Field(default_factory=list)
    allowed_target_types: list[str] = Field(default_factory=list)
    direction_semantics: str = "source_to_target"
    aliases: list[str] = Field(default_factory=list)
    status: str = "approved"
