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

class Channel(PkTimestamp, Base):
    """An email deployment surface that feeds a workflow.
    `config` holds SMTP/IMAP settings and secret refs. `key` is the public,
    unguessable id used in inbound endpoint URLs."""

    __tablename__ = "channels"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    type: Mapped[str] = mapped_column(String(20))  # email
    name: Mapped[str] = mapped_column(String(120))
    key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # --- Integrations v3: workflow-independent routing -------------------------------------
    # A Channel is a communication connection. Where its messages go is explicit:
    #   target_type: master_agent (default for new channels) | subagent | workflow
    #   target_id:   agent id / workflow id (null for master_agent)
    # `workflow_id` is retained for compatibility with pre-v3 channels (mirrors target_id when
    # target_type == "workflow"). routing_state "needs_review" marks a legacy channel that relied
    # on the removed first-active-workflow fallback; it is NEVER auto-routed.
    # `routes`: optional exact command rules [{"command": "/status", "target_type", "target_id"}].
    # `state`: adapter runtime state (poll offset, diagnostics). Never holds secrets.
    target_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    routing_state: Mapped[str] = mapped_column(String(20), default="ok")
    routes: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[dict] = mapped_column(JSON, default=dict)


class ChannelIdentity(PkTimestamp, Base):
    """Binds a verified external provider identity (Telegram user, email address) on ONE
    channel to ONE Alberto user. Never inferred from display names/email lookalikes."""

    __tablename__ = "channel_identities"
    __table_args__ = (
        UniqueConstraint("channel_id", "provider_user_id", name="uq_channel_identity_provider_user"),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(String(36), index=True)
    provider_user_id: Mapped[str] = mapped_column(String(200))
    provider_chat_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    display_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|verified|revoked
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ChannelPairing(PkTimestamp, Base):
    """One-time pairing challenge. Only the SHA-256 of the code is stored."""

    __tablename__ = "channel_pairings"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(String(36), index=True)
    identity_id: Mapped[str] = mapped_column(String(36), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column()
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ChannelEvent(PkTimestamp, Base):
    """Inbound event ledger: provider-event dedup + safe delivery/diagnostic metadata.
    Message bodies are NOT stored."""

    __tablename__ = "channel_events"
    __table_args__ = (
        UniqueConstraint("channel_id", "provider_event_id", name="uq_channel_event_provider_id"),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    channel_id: Mapped[str] = mapped_column(String(36), index=True)
    provider_event_id: Mapped[str] = mapped_column(String(200))
    direction: Mapped[str] = mapped_column(String(10), default="inbound")
    # received|processing|delivered|delivery_failed|pairing_required|quarantined|rejected|failed|interrupted
    status: Mapped[str] = mapped_column(String(24), default="received", index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    route: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    thread_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
