"""Milestone 1.6 Execution Hardening: Add observability and termination fields to runs and traces

Revision ID: 0016_m1_6_execution_hardening
Revises: 0015_model_registry
Create Date: 2026-10-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0016_m1_6_execution_hardening"
down_revision = "0015_model_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "runs" in tables:
        run_cols = {c["name"] for c in insp.get_columns("runs")}
        if "iterations_count" not in run_cols:
            op.add_column("runs", sa.Column("iterations_count", sa.Integer(), nullable=False, server_default="0"))
        if "tool_calls_count" not in run_cols:
            op.add_column("runs", sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default="0"))
        if "termination_reason" not in run_cols:
            op.add_column("runs", sa.Column("termination_reason", sa.String(64), nullable=True))

    if "traces" in tables:
        trace_cols = {c["name"] for c in insp.get_columns("traces")}
        if "iterations_count" not in trace_cols:
            op.add_column("traces", sa.Column("iterations_count", sa.Integer(), nullable=False, server_default="0"))
        if "tool_calls_count" not in trace_cols:
            op.add_column("traces", sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default="0"))
        if "termination_reason" not in trace_cols:
            op.add_column("traces", sa.Column("termination_reason", sa.String(64), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "runs" in tables:
        run_cols = {c["name"] for c in insp.get_columns("runs")}
        if "termination_reason" in run_cols:
            op.drop_column("runs", "termination_reason")
        if "tool_calls_count" in run_cols:
            op.drop_column("runs", "tool_calls_count")
        if "iterations_count" in run_cols:
            op.drop_column("runs", "iterations_count")

    if "traces" in tables:
        trace_cols = {c["name"] for c in insp.get_columns("traces")}
        if "termination_reason" in trace_cols:
            op.drop_column("traces", "termination_reason")
        if "tool_calls_count" in trace_cols:
            op.drop_column("traces", "tool_calls_count")
        if "iterations_count" in trace_cols:
            op.drop_column("traces", "iterations_count")
