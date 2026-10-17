"""Milestone 2.1: Persistent memory columns and learning events table

Revision ID: 0019_m2_1_persistent_memory
Revises: 0018_system_agent_unique_index
Create Date: 2026-10-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_m2_1_persistent_memory"
down_revision = "0018_system_agent_unique_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    # 1. Extend memories table if present
    if "memories" in tables:
        cols = {c["name"] for c in insp.get_columns("memories")}
        if "confidence" not in cols:
            op.add_column("memories", sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"))
        if "provenance" not in cols:
            op.add_column("memories", sa.Column("provenance", sa.String(120), nullable=False, server_default="manual"))
        if "status" not in cols:
            op.add_column("memories", sa.Column("status", sa.String(20), nullable=False, server_default="active"))
            op.create_index("ix_memories_status", "memories", ["status"])
        if "source_ref" not in cols:
            op.add_column("memories", sa.Column("source_ref", sa.String(120), nullable=True))
            op.create_index("ix_memories_source_ref", "memories", ["source_ref"])
        if "superseded_by" not in cols:
            op.add_column("memories", sa.Column("superseded_by", sa.String(36), nullable=True))
        if "metadata" not in cols and "meta" not in cols:
            op.add_column("memories", sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"))

    # 2. Create memory_learning_events table if absent
    if "memory_learning_events" not in tables:
        op.create_table(
            "memory_learning_events",
            sa.Column("id", sa.String(36), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("source_event_id", sa.String(120), nullable=False),
            sa.Column("source_type", sa.String(40), nullable=False, server_default="conversation_turn"),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("extraction_payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requires_review", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("applied_memory_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("applied_graph_entity_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("applied_graph_rel_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        )
        op.create_index("ix_mle_tenant_id", "memory_learning_events", ["tenant_id"])
        op.create_index("ix_mle_project_id", "memory_learning_events", ["project_id"])
        op.create_index("ix_mle_source_event_id", "memory_learning_events", ["source_event_id"])
        op.create_index("ix_mle_status", "memory_learning_events", ["status"])
        op.create_index(
            "uq_learning_events_tenant_project_source",
            "memory_learning_events",
            ["tenant_id", "project_id", "source_event_id"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "memory_learning_events" in tables:
        op.drop_table("memory_learning_events")

    if "memories" in tables:
        cols = {c["name"] for c in insp.get_columns("memories")}
        # SQLite does not support dropping columns easily in older versions, but if needed:
        indexes = {i["name"] for i in insp.get_indexes("memories")}
        if "ix_memories_status" in indexes:
            op.drop_index("ix_memories_status", table_name="memories")
        if "ix_memories_source_ref" in indexes:
            op.drop_index("ix_memories_source_ref", table_name="memories")
