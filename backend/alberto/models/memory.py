"""Domain ORM models."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from alberto.db.base import Base, PkTimestamp


class KbSource(PkTimestamp, Base):
    __tablename__ = "kb_sources"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # text|url|file|s3|api
    name: Mapped[str] = mapped_column(String(300))
    folder: Mapped[str] = mapped_column(String(200), default="", server_default="")  # "" = unfiled
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|processing|ready|error
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)

    @property
    def chunking_strategy(self) -> str | None:
        """Chunking strategy used at ingest (recursive|section|sentence); lives in meta."""
        return (self.meta or {}).get("chunk_strategy")

    @property
    def chunk_size(self) -> int | None:
        """Target chunk size (chars) used at ingest; lives in meta, None until first ingest."""
        v = (self.meta or {}).get("chunk_size")
        return int(v) if v is not None else None

    @property
    def chunk_overlap(self) -> int | None:
        """Chunk overlap (chars) used at ingest; lives in meta, None until first ingest."""
        v = (self.meta or {}).get("chunk_overlap")
        return int(v) if v is not None else None


class QaPair(PkTimestamp, Base):
    __tablename__ = "qa_pairs"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="faq")  # faq|error_workaround
    tags: Mapped[list] = mapped_column(JSON, default=list)
    q_embedding: Mapped[list] = mapped_column(JSON, default=list)
    upvotes: Mapped[int] = mapped_column(Integer, default=0)


class Memory(PkTimestamp, Base):
    """A long-term memory an agent stored - facts that should persist across threads
    (vs. the per-thread checkpointer). Recalled by semantic search; scoped per project
    (+ optional `scope` for per-user/per-conversation memory)."""

    __tablename__ = "memories"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    scope: Mapped[str] = mapped_column(String(120), default="default", index=True)
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="note")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    provenance: Mapped[str] = mapped_column(String(120), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    source_ref: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    superseded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class MemoryLearningEvent(PkTimestamp, Base):
    """Tracks durable memory learning events from conversation turns."""

    __tablename__ = "memory_learning_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "source_event_id", name="uq_learning_events_tenant_project_source"),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    source_event_id: Mapped[str] = mapped_column(String(120), index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="conversation_turn")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)  # pending|extracted|validated|applying|completed|review_required|failed
    extraction_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_memory_ids: Mapped[list] = mapped_column(JSON, default=list)
    applied_graph_entity_ids: Mapped[list] = mapped_column(JSON, default=list)
    applied_graph_rel_ids: Mapped[list] = mapped_column(JSON, default=list)


class OntologyEntityType(PkTimestamp, Base):
    """Dynamically extensible Knowledge Graph entity type definition."""

    __tablename__ = "ontology_entity_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "canonical_key", name="uq_ontology_entity_type"),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    canonical_key: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="approved", index=True)  # approved|pending_approval|deprecated|rejected
    provenance: Mapped[str] = mapped_column(String(64), default="system_seed")  # system_seed|human_approved|llm_proposed|human_correction


class OntologyRelationshipType(PkTimestamp, Base):
    """Dynamically extensible Knowledge Graph relationship type definition."""

    __tablename__ = "ontology_relationship_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "canonical_key", name="uq_ontology_rel_type"),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    canonical_key: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    allowed_source_types: Mapped[list] = mapped_column(JSON, default=list)
    allowed_target_types: Mapped[list] = mapped_column(JSON, default=list)
    direction_semantics: Mapped[str] = mapped_column(String(40), default="source_to_target")
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="approved", index=True)  # approved|pending_approval|deprecated|rejected
    provenance: Mapped[str] = mapped_column(String(64), default="system_seed")  # system_seed|human_approved|llm_proposed|human_correction


class OntologyEntityMapping(PkTimestamp, Base):
    """Persistent learned mapping from specific entity canonical name to target entity type."""

    __tablename__ = "ontology_entity_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "entity_canonical_name", name="uq_ontology_entity_mapping"),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    entity_canonical_name: Mapped[str] = mapped_column(String(120), index=True)
    target_entity_type: Mapped[str] = mapped_column(String(64), index=True)
    provenance: Mapped[str] = mapped_column(String(64), default="human_correction")  # human_correction|seed|human_approved
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)  # active|rejected
