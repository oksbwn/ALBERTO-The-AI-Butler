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

class Project(PkTimestamp, Base):
    __tablename__ = "projects"
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|draft
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # Public, safe-to-embed key for the chat widget (Phase 3b/4), indexed for O(1) lookup by
    # the public /v1/embed/{key} routes. None until embedding is enabled; the rest of the embed
    # settings (enabled, allowed_origins, workflow_id) live in config["embed"].
    embed_key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)


class Workflow(PkTimestamp, Base):
    __tablename__ = "workflows"
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    canvas: Mapped[dict] = mapped_column(JSON, default=dict)        # React Flow round-trip (UI-owned)
    executable: Mapped[dict] = mapped_column(JSON, default=dict)    # compiler input (backend-owned)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    active_version: Mapped[int] = mapped_column(Integer, default=1)


class Component(PkTimestamp, Base):
    """A user-authored UI component (Feature 2 - generative UI): saved HTML + CSS,
    declarative button `actions`, and a JSON-Schema for the `props` the agent supplies.
    Attached to agents like tools (agent config["components"]); at runtime each becomes a
    widget-tool that, when called, emits a `component` stream frame for the client to
    render - so the markup never enters the model's token stream, only the props do."""

    __tablename__ = "components"
    # The name is used verbatim as the LLM tool name → unique per project so two components
    # can't shadow each other's widget (audit M2). Enforced on fresh DBs; the router also
    # pre-checks for the existing-table case (create_all won't add a constraint after the fact).
    __table_args__ = (UniqueConstraint("tenant_id", "project_id", "name", name="uq_component_tenant_project_name"),)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    props_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    html: Mapped[str] = mapped_column(Text, default="")
    css: Mapped[str] = mapped_column(Text, default="")
    actions: Mapped[list] = mapped_column(JSON, default=list)
    sample_props: Mapped[dict] = mapped_column(JSON, default=dict)
    kind: Mapped[str] = mapped_column(String(20), default="html")  # html (sandboxed) | declarative (future)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Agent(PkTimestamp, Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index(
            "uq_agents_tenant_project_system_key",
            "tenant_id",
            "project_id",
            "system_key",
            unique=True,
            sqlite_where=text("is_system = 1 AND system_key IS NOT NULL"),
            postgresql_where=text("is_system = true AND system_key IS NOT NULL"),
        ),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # validated vs forge/nodes/agent
    # Creator attribution (denormalized email snapshot for display without a join).
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    system_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class Trigger(PkTimestamp, Base):
    """An event-driven entry point synced from a workflow's trigger nodes. The
    dispatcher (webhook route / scheduler / inbound email / chat) fires runs from these."""

    __tablename__ = "triggers"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str] = mapped_column(String(36), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))  # webhook_in|schedule|email_in|app_event
    key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)  # webhook URL key
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Two INDEPENDENT axes, deliberately - conflating them is what makes automation ownership
    # confusing in most tools:
    #
    #   run_as_user_id - WHOSE connected accounts the run uses.
    #   scope          - WHO the trigger belongs to, and therefore who sees it.
    #
    # A salesperson's own lead-chaser is `user` scope running as them. A platform team's
    # prod-monitor is `project` scope, still running as whoever's accounts it needs. The two vary
    # separately: a shared team automation can legitimately act through one person's Slack.
    #
    # WHOSE connected accounts an unattended run uses. A webhook or a schedule has no signed-in
    # person, so without this a per-user connector (every catalog connector is one) has no
    # identity to resolve a token for and the run fails at the first tool call. Stamped with the
    # editor who saved the workflow the trigger came from, and preserved when a colleague later
    # edits that workflow - the automation belongs to whoever connected the account behind it,
    # not to whoever last fixed a typo. Reassignable from the Triggers screen.
    run_as_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # "project" (a team automation everyone sees) | "user" (someone's own, listed only for them).
    # Defaults to "project" so a pre-existing trigger keeps behaving exactly as it did; new ones
    # take their default from the role of whoever saved the workflow (see TriggerService).
    # NOTE: this is ownership and visibility, NOT access control on the event itself. A webhook
    # URL is a credential - anyone holding it fires the trigger regardless of scope.
    scope: Mapped[str] = mapped_column(String(10), default="project")
    # Runtime state (e.g. app_event dedupe cursor / seen ids); NOT synced from the node.
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class HandoffRequest(PkTimestamp, Base):
    """A conversation escalated to a human (live-agent handoff). The run is paused at a
    `handoff` interrupt; an agent replies via the inbox, which resumes the run and pushes
    the answer back over the originating channel."""

    __tablename__ = "handoff_requests"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    customer: Mapped[str | None] = mapped_column(String(300), nullable=True)  # email / display name
    customer_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|answered|closed
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reply_context: Mapped[dict] = mapped_column(JSON, default=dict)


class Dataset(PkTimestamp, Base):
    """An evaluation dataset: inputs + expected outputs run against a workflow to score
    quality and catch regressions before publish."""

    __tablename__ = "datasets"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    score_mode: Mapped[str] = mapped_column(String(20), default="contains")  # contains|exact|regex|judge
    items: Mapped[list] = mapped_column(JSON, default=list)  # [{input, expected}]
    last_pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)


class EntityVersion(PkTimestamp, Base):
    """Immutable point-in-time snapshot of a versionable entity's config, captured on each
    save so a user can view history and restore a prior version. Generic across entity types
    (workflow|agent|tool|component|auth_provider|kb_source|project) - the `snapshot` JSON holds
    the entity's restorable fields. Retention is pruned to the configured version_history_limit
    per (entity_type, entity_id). See forge.services.versions."""

    __tablename__ = "entity_versions"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "version_no", name="uq_entity_version"),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str | None] = mapped_column(String(300), nullable=True)  # entity name at snapshot time / note
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    author_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    author_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
