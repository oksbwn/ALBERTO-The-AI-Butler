"""Domain ORM models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from alberto.db.base import Base, PkTimestamp

class Thread(PkTimestamp, Base):
    __tablename__ = "threads"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str] = mapped_column(String(36), index=True)
    user_external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lg_thread_id: Mapped[str] = mapped_column(String(100))  # passed to LangGraph configurable.thread_id
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class Run(PkTimestamp, Base):
    __tablename__ = "runs"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str] = mapped_column(String(36), index=True)
    thread_id: Mapped[str] = mapped_column(String(36), index=True)
    # Where this run originated, for the Traces conversation view. Set at create_run by each
    # caller: playground|api|embed|channel_email|webhook|schedule (assistant runs
    # have no Run row). Copied onto the Trace at finalize.
    source: Mapped[str] = mapped_column(String(40), default="playground")
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|interrupted|done|error
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    iterations_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls_count: Mapped[int] = mapped_column(Integer, default=0)
    termination_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Trace(PkTimestamp, Base):
    __tablename__ = "traces"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    iterations_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls_count: Mapped[int] = mapped_column(Integer, default=0)
    termination_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # --- Conversation view (Traces): one Trace = one turn; group by thread_id for a session. ---
    # Origin of the turn (copied from Run.source; assistant turns = "assistant").
    # Indexed: the Traces filter facets run a DISTINCT over this column.
    source: Mapped[str] = mapped_column(String(40), default="playground", index=True)
    # Display + filter label: "System" for playground/test/assistant, else the end user's name,
    # else "Unknown user". Denormalized so the conversation list is a single Trace query.
    actor: Mapped[str] = mapped_column(String(300), default="System", index=True)
    # Stable end-user id (disambiguates same-named users); None for anonymous / system.
    end_user_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    # This turn's user message and the AI's response, captured from live state at finalize.
    user_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(PkTimestamp, Base):
    """Append-only audit trail: who did what, when (Doc 2 §12). Written for auth
    events, secret reads, and create/update/delete of every resource. Never updated
    or deleted in normal operation."""

    __tablename__ = "audit_logs"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)  # e.g. auth.login, secret.read, workflow.delete
    resource_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok|denied|error
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class Span(PkTimestamp, Base):
    __tablename__ = "spans"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    trace_id: Mapped[str] = mapped_column(String(36), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20))  # llm|tool|chain|retriever|agent|node|subagent
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)


# --- Platform-hardening tables (finding h/j). All new: dev create_all builds them; prod needs
# an Alembic migration + the tenant-isolation policies in infra/postgres_rls.sql. -------------
