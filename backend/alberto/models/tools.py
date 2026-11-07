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

class Tool(PkTimestamp, Base):
    __tablename__ = "tools"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # rest_api|graphql|code|mcp|builtin
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    auth_provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_tested: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pass|fail|untested


class ToolSet(PkTimestamp, Base):
    """A named, describable group of tools ("tool set"). Tool sets are the unit of
    organization in the Tools screen (they render as folders) AND the unit of exposure: an
    agent can be granted a whole set (agent config.toolsets) and the MCP server can publish
    a set as a GitHub-style toolset. Membership is many-to-many via ToolSetMember, so a tool
    may live in several sets (label-style, not a single home folder). `description` is what
    an MCP client / the model reads to decide when to enable the set; `is_default` marks a
    set that's published by default when a project exposes its tools over MCP."""

    __tablename__ = "tool_sets"
    __table_args__ = (UniqueConstraint("tenant_id", "project_id", "slug", name="uq_tool_set_slug"),)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), index=True)  # url-safe id, unique per project
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Publish this set (and its enabled tools) over MCP. The MCP surface is EXACTLY the enabled
    # tools of exposed sets - there are no loose "directly exposed" tools (GitHub-toolset model).
    exposed: Mapped[bool] = mapped_column(Boolean, default=True)


class ToolSetMember(PkTimestamp, Base):
    """Many-to-many membership linking a Tool to a ToolSet (a tool can belong to several
    sets). No DB-level cascade (matching the rest of the schema); ToolSetService and
    ToolService delete the membership rows explicitly when a set or tool is removed."""

    __tablename__ = "tool_set_members"
    __table_args__ = (UniqueConstraint("tool_set_id", "tool_id", name="uq_tool_set_member"),)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    tool_set_id: Mapped[str] = mapped_column(String(36), index=True)
    tool_id: Mapped[str] = mapped_column(String(36), index=True)


class AuthProvider(PkTimestamp, Base):
    __tablename__ = "auth_providers"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    credentials_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Secret(PkTimestamp, Base):
    __tablename__ = "secrets"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="generic")
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary)
    version: Mapped[int] = mapped_column(Integer, default=1)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)


class McpClient(PkTimestamp, Base):
    __tablename__ = "mcp_clients"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    transport: Mapped[str] = mapped_column(String(20), default="http")
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    headers_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    disabled_tools: Mapped[list] = mapped_column(JSON, default=list)  # remote tool names toggled off in the External MCP tab
    # An Auth Provider whose resolved headers are attached to every request to this server.
    # This is what lets Forge talk to an OAuth-protected remote MCP server (mcp.slack.com,
    # the Google Workspace / Microsoft servers, Notion, Linear, …) instead of only servers
    # that accept a static header secret. Nullable: existing rows and open servers are
    # unaffected, and `headers_ref` still works (both are merged, provider wins on conflict).
    auth_provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Milestone 2.2: MCP capability discovery and execution learning metadata
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    last_discovered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    learning_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class OAuthClient(PkTimestamp, Base):
    """Legacy model for dynamically-registered OAuth 2.1 clients (RFC 7591).
    Retained to preserve database table structure for existing migrations without data loss."""

    __tablename__ = "oauth_clients"
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    redirect_uris: Mapped[list] = mapped_column(JSON, default=list)


class ConnectorInstall(PkTimestamp, Base):
    """One installed connector - the receipt for a manifest that was expanded into real rows.

    A connector is NOT a runtime concept: installing one creates an `AuthProvider`, a `ToolSet`,
    N `Tool` rows (and an `McpClient` for MCP-backed connectors), and from then on agents,
    workflow tool nodes, the MCP server and traces treat them like any other hand-built tool.
    Delete `forge/connectors/` and every installed connector keeps working.

    This row exists so the install is REVERSIBLE and UPGRADABLE: it records exactly which rows
    the install created (so uninstall removes those and nothing else) and freezes the manifest
    that produced them (so a catalog update can be diffed against what's actually deployed
    rather than assumed).
    """

    __tablename__ = "connector_installs"
    __table_args__ = (UniqueConstraint("tenant_id", "project_id", "slug", name="uq_connector_install_slug"),)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    source: Mapped[str] = mapped_column(String(20), default="catalog")  # catalog | custom | url
    # Frozen copy of the manifest that produced this install. Survives catalog edits/upgrades,
    # so uninstall and "what changed?" stay correct even if the bundled file moved on.
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    auth_provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tool_set_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mcp_client_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_tool_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_secret_names: Mapped[list] = mapped_column(JSON, default=list)
    # Hosts this install ADDED to the project's egress allow-list - not every host its manifest
    # names. A host somebody allow-listed by hand before the connector existed is not this
    # install's to take away on uninstall, and the two are indistinguishable after the fact.
    created_egress_hosts: Mapped[list] = mapped_column(JSON, default=list)
    # needs_setup (credentials missing) | needs_auth (connect flow not run) | connected | error
    status: Mapped[str] = mapped_column(String(20), default="needs_setup")
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "shared" (one project-wide account) | "per_user" (each end user connects their own).
    auth_mode: Mapped[str] = mapped_column(String(20), default="shared")


class ToolApprovalRequest(PkTimestamp, Base):
    """Human-in-the-loop (HITL) approval request persisted in SQLite."""

    __tablename__ = "tool_approval_requests"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_role: Mapped[str] = mapped_column(String(40), default="viewer")
    originating_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    originating_workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    caller_type: Mapped[str] = mapped_column(String(40), default="assistant")
    tool_id: Mapped[str] = mapped_column(String(120), index=True)
    tool_name: Mapped[str] = mapped_column(String(120))
    operation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tool_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    arguments_hash: Mapped[str] = mapped_column(String(64), index=True)
    arguments_scrubbed: Mapped[dict] = mapped_column(JSON, default=dict)
    # Status: pending | approved | rejected | consumed | cancelled | expired
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    decided_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolAnalysisJob(PkTimestamp, Base):
    """Durable tool discovery / classification job persisted in SQLite."""

    __tablename__ = "tool_analysis_jobs"
    __table_args__ = (
        Index("ix_tool_analysis_jobs_lookup", "tenant_id", "project_id", "tool_id", "schema_fingerprint"),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    tool_id: Mapped[str] = mapped_column(String(120), index=True)
    schema_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    # Status: pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[dict] = mapped_column(JSON, default=dict)
