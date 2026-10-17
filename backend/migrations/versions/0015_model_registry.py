"""Unified Model Registry: model_servers and registered_models tables

Replaces unconfigured cloud catalogues and ad-hoc JSON provider blobs with
first-class model_servers and registered_models tables.

Revision ID: 0015_model_registry
Revises: 0014_connector_egress_hosts
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_model_registry"
down_revision = "0014_connector_egress_hosts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "model_servers" not in tables:
        op.create_table(
            "model_servers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("provider_type", sa.String(40), nullable=False),
            sa.Column("base_url", sa.String(500), nullable=False),
            sa.Column("api_key_ref", sa.String(200), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "registered_models" not in tables:
        op.create_table(
            "registered_models",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("server_id", sa.String(36), sa.ForeignKey("model_servers.id"), nullable=False, index=True),
            sa.Column("model_name", sa.String(200), nullable=False),
            sa.Column("display_name", sa.String(200), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("context_window_max", sa.Integer(), nullable=True),
            sa.Column("context_window_configured", sa.Integer(), nullable=True),
            sa.Column("supports_tools", sa.Boolean(), nullable=True),
            sa.Column("supports_vision", sa.Boolean(), nullable=True),
            sa.Column("temperature", sa.Float(), nullable=True),
            sa.Column("top_p", sa.Float(), nullable=True),
            sa.Column("max_output_tokens", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tenant_id", "server_id", "model_name", name="uq_registered_model_tenant_server_name"),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "registered_models" in tables:
        op.drop_table("registered_models")
    if "model_servers" in tables:
        op.drop_table("model_servers")
