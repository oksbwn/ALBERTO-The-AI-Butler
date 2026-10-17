"""Milestone 2.0 System Agents: Add is_system and system_key to agents table

Revision ID: 0017_m2_0_system_agents
Revises: 0016_m1_6_execution_hardening
Create Date: 2026-10-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_m2_0_system_agents"
down_revision = "0016_m1_6_execution_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "agents" in tables:
        agent_cols = {c["name"] for c in insp.get_columns("agents")}
        if "is_system" not in agent_cols:
            op.add_column("agents", sa.Column("is_system", sa.Boolean(), nullable=False, server_default="0"))
        if "system_key" not in agent_cols:
            op.add_column("agents", sa.Column("system_key", sa.String(64), nullable=True))
            op.create_index("ix_agents_system_key", "agents", ["system_key"])



def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "agents" in tables:
        indexes = {i["name"] for i in insp.get_indexes("agents")}
        if "uq_agents_tenant_project_system_key" in indexes:
            op.drop_index("uq_agents_tenant_project_system_key", table_name="agents")
        agent_cols = {c["name"] for c in insp.get_columns("agents")}
        if "system_key" in agent_cols:
            op.drop_index("ix_agents_system_key", table_name="agents")
            op.drop_column("agents", "system_key")
        if "is_system" in agent_cols:
            op.drop_column("agents", "is_system")
