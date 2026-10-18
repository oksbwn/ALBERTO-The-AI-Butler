"""Milestone 2.2: MCP capability discovery and learning metadata columns

Revision ID: 0020_m2_2_mcp_learning_and_retrieval
Revises: 0019_m2_1_persistent_memory
Create Date: 2026-10-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_m2_2_mcp_learning_and_retrieval"
down_revision = "0019_m2_1_persistent_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "mcp_clients" in tables:
        cols = {c["name"] for c in insp.get_columns("mcp_clients")}
        if "capabilities" not in cols:
            op.add_column("mcp_clients", sa.Column("capabilities", sa.JSON(), nullable=False, server_default="{}"))
        if "last_discovered_at" not in cols:
            op.add_column("mcp_clients", sa.Column("last_discovered_at", sa.DateTime(), nullable=True))
        if "schema_fingerprint" not in cols:
            op.add_column("mcp_clients", sa.Column("schema_fingerprint", sa.String(64), nullable=True))
        if "learning_enabled" not in cols:
            op.add_column("mcp_clients", sa.Column("learning_enabled", sa.Boolean(), nullable=False, server_default="0"))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "mcp_clients" in tables:
        # SQLite does not support dropping columns cleanly in older versions
        pass
