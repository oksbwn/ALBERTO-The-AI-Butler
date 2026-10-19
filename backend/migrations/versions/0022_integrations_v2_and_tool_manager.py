"""Integrations v2 and Tool Manager: ToolApprovalRequest and ToolAnalysisJob tables

Revision ID: 0022_integrations_v2_and_tool_manager
Revises: 0021_dynamic_ontology_registry
Create Date: 2026-10-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_integrations_v2_and_tool_manager"
down_revision = "0021_dynamic_ontology_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "tool_approval_requests" not in tables:
        op.create_table(
            "tool_approval_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), nullable=False, index=True),
            sa.Column("user_id", sa.String(36), nullable=True, index=True),
            sa.Column("user_role", sa.String(40), nullable=False, server_default="viewer"),
            sa.Column("originating_agent_id", sa.String(36), nullable=True),
            sa.Column("originating_workflow_id", sa.String(36), nullable=True),
            sa.Column("caller_type", sa.String(40), nullable=False, server_default="assistant"),
            sa.Column("tool_id", sa.String(120), nullable=False, index=True),
            sa.Column("tool_name", sa.String(120), nullable=False),
            sa.Column("operation", sa.String(120), nullable=True),
            sa.Column("tool_version", sa.String(40), nullable=True),
            sa.Column("arguments_hash", sa.String(64), nullable=False, index=True),
            sa.Column("arguments_scrubbed", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending", index=True),
            sa.Column("reason", sa.String(200), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("decided_by", sa.String(320), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        )

    if "tool_analysis_jobs" not in tables:
        op.create_table(
            "tool_analysis_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), nullable=False, index=True),
            sa.Column("tool_id", sa.String(120), nullable=False, index=True),
            sa.Column("schema_fingerprint", sa.String(64), nullable=False, index=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending", index=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("result_summary", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        )

    # Ensure composite lookup index on tool_analysis_jobs
    if "tool_analysis_jobs" in set(sa.inspect(bind).get_table_names()):
        indexes = {i["name"] for i in sa.inspect(bind).get_indexes("tool_analysis_jobs")}
        if "ix_tool_analysis_jobs_lookup" not in indexes:
            op.create_index(
                "ix_tool_analysis_jobs_lookup",
                "tool_analysis_jobs",
                ["tenant_id", "project_id", "tool_id", "schema_fingerprint"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "tool_analysis_jobs" in tables:
        op.drop_table("tool_analysis_jobs")
    if "tool_approval_requests" in tables:
        op.drop_table("tool_approval_requests")
