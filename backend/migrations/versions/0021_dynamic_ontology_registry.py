"""Dynamic Knowledge Graph Ontology Registry and Persistent Entity Mappings

Revision ID: 0021_dynamic_ontology_registry
Revises: 0020_m2_2_mcp_learning_and_retrieval
Create Date: 2026-10-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_dynamic_ontology_registry"
down_revision = "0020_m2_2_mcp_learning_and_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "ontology_entity_types" not in tables:
        op.create_table(
            "ontology_entity_types",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), nullable=False, index=True),
            sa.Column("canonical_key", sa.String(64), nullable=False, index=True),
            sa.Column("display_name", sa.String(120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(30), nullable=False, server_default="approved", index=True),
            sa.Column("provenance", sa.String(64), nullable=False, server_default="system_seed"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "project_id", "canonical_key", name="uq_ontology_entity_type"),
        )

    if "ontology_relationship_types" not in tables:
        op.create_table(
            "ontology_relationship_types",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), nullable=False, index=True),
            sa.Column("canonical_key", sa.String(64), nullable=False, index=True),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("allowed_source_types", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("allowed_target_types", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("direction_semantics", sa.String(40), nullable=False, server_default="source_to_target"),
            sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(30), nullable=False, server_default="approved", index=True),
            sa.Column("provenance", sa.String(64), nullable=False, server_default="system_seed"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "project_id", "canonical_key", name="uq_ontology_rel_type"),
        )

    if "ontology_entity_mappings" not in tables:
        op.create_table(
            "ontology_entity_mappings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), nullable=False, index=True),
            sa.Column("entity_canonical_name", sa.String(120), nullable=False, index=True),
            sa.Column("target_entity_type", sa.String(64), nullable=False, index=True),
            sa.Column("provenance", sa.String(64), nullable=False, server_default="human_correction"),
            sa.Column("status", sa.String(30), nullable=False, server_default="active", index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "project_id", "entity_canonical_name", name="uq_ontology_entity_mapping"),
        )


def downgrade() -> None:
    pass
