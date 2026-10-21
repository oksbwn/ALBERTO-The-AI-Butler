"""Automate: Durable workflow repair attempt persistence to prevent repair loops across restarts

Revision ID: 0024_workflow_repair_attempts
Revises: 0023_integrations_v3_channels
Create Date: 2026-10-21

Non-destructive and idempotent:
- Creates workflow_repair_attempts table if not present.
- Creates index ix_repair_attempts_wf_fingerprint.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_workflow_repair_attempts"
down_revision = "0023_integrations_v3_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    now = sa.func.now()

    if "workflow_repair_attempts" not in tables:
        op.create_table(
            "workflow_repair_attempts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), nullable=False, index=True),
            sa.Column("workflow_id", sa.String(36), nullable=False, index=True),
            sa.Column("workflow_revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("failure_fingerprint", sa.String(128), nullable=False, index=True),
            sa.Column("source_run_id", sa.String(36), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("repair_status", sa.String(50), nullable=False, server_default="attempted"),
            sa.Column("last_attempt_at", sa.DateTime(), nullable=False, server_default=now),
            sa.Column("repair_outcome", sa.JSON(), nullable=True, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), server_default=now, nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=now, nullable=False),
        )
        op.create_index(
            "ix_repair_attempts_wf_fingerprint",
            "workflow_repair_attempts",
            ["workflow_id", "failure_fingerprint", "workflow_revision"],
            unique=False,
        )


def downgrade() -> None:
    # Non-destructive
    pass
