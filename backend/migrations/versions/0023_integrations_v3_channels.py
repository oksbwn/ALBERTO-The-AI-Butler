"""Integrations v3: workflow-independent Channel routing, identity pairing, event ledger

Revision ID: 0023_integrations_v3_channels
Revises: 0022_integrations_v2_and_tool_manager
Create Date: 2026-10-19

Non-destructive and idempotent:
- channels gains target_type / target_id / routing_state / routes / state.
- Legacy rows: explicit workflow_id -> target_type=workflow (behaviour preserved);
  no workflow_id -> routing_state='needs_review' (never auto-routed).
- New tables: channel_identities, channel_pairings, channel_events.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_integrations_v3_channels"
down_revision = "0022_integrations_v2_and_tool_manager"
branch_labels = None
depends_on = None


def _cols(insp, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "channels" in tables:
        have = _cols(insp, "channels")
        with op.batch_alter_table("channels") as b:
            if "target_type" not in have:
                b.add_column(sa.Column("target_type", sa.String(20), nullable=True))
            if "target_id" not in have:
                b.add_column(sa.Column("target_id", sa.String(36), nullable=True))
            if "routing_state" not in have:
                b.add_column(sa.Column("routing_state", sa.String(20), nullable=False, server_default="ok"))
            if "routes" not in have:
                b.add_column(sa.Column("routes", sa.JSON(), nullable=True, server_default="[]"))
            if "state" not in have:
                b.add_column(sa.Column("state", sa.JSON(), nullable=True, server_default="{}"))
        # Legacy backfill (only rows never routed by v3).
        op.execute(
            "UPDATE channels SET target_type = 'workflow', target_id = workflow_id, routing_state = 'ok' "
            "WHERE target_type IS NULL AND workflow_id IS NOT NULL"
        )
        op.execute(
            "UPDATE channels SET routing_state = 'needs_review' "
            "WHERE target_type IS NULL AND workflow_id IS NULL"
        )

    now = sa.func.now()
    if "channel_identities" not in tables:
        op.create_table(
            "channel_identities",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), nullable=False, index=True),
            sa.Column("channel_id", sa.String(36), nullable=False, index=True),
            sa.Column("provider_user_id", sa.String(200), nullable=False),
            sa.Column("provider_chat_id", sa.String(200), nullable=True),
            sa.Column("display_label", sa.String(200), nullable=True),
            sa.Column("user_id", sa.String(36), nullable=True, index=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=now, nullable=False),
            sa.UniqueConstraint("channel_id", "provider_user_id", name="uq_channel_identity_provider_user"),
        )
    if "channel_pairings" not in tables:
        op.create_table(
            "channel_pairings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), nullable=False, index=True),
            sa.Column("channel_id", sa.String(36), nullable=False, index=True),
            sa.Column("identity_id", sa.String(36), nullable=False, index=True),
            sa.Column("code_hash", sa.String(64), nullable=False, index=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=now, nullable=False),
        )
    if "channel_events" not in tables:
        op.create_table(
            "channel_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), nullable=False, index=True),
            sa.Column("channel_id", sa.String(36), nullable=False, index=True),
            sa.Column("provider_event_id", sa.String(200), nullable=False),
            sa.Column("direction", sa.String(10), nullable=False, server_default="inbound"),
            sa.Column("status", sa.String(24), nullable=False, server_default="received", index=True),
            sa.Column("correlation_id", sa.String(64), nullable=True),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("route", sa.String(120), nullable=True),
            sa.Column("detail", sa.String(300), nullable=True),
            sa.Column("run_id", sa.String(36), nullable=True),
            sa.Column("thread_key", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=now, nullable=False),
            sa.UniqueConstraint("channel_id", "provider_event_id", name="uq_channel_event_provider_id"),
        )


def downgrade() -> None:
    # Additive migration: tables/columns are left in place on downgrade to avoid data loss
    # (channel identities and pairings are security-relevant records).
    pass
