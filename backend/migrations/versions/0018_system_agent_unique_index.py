"""Milestone 2.0: Safe partial unique index on system agents

Revision ID: 0018_system_agent_unique_index
Revises: 0017_m2_0_system_agents
Create Date: 2026-10-18
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0018_system_agent_unique_index"
down_revision = "0017_m2_0_system_agents"
branch_labels = None
depends_on = None


def _deduplicate_system_agents(bind: sa.engine.Connection) -> None:
    """Safely deduplicate existing system agents sharing (tenant_id, project_id, system_key).

    Rules:
    - Only examine rows where is_system = 1 AND system_key IS NOT NULL.
    - If duplicates exist:
      - Preserve the record with custom model overrides (config['model']).
      - If tie, preserve the most recently updated/created record.
      - Delete only the redundant system agent rows.
    - User agents (is_system = 0 or system_key IS NULL) are NEVER touched.
    """
    rows = bind.execute(
        sa.text(
            "SELECT id, tenant_id, project_id, system_key, config, created_at, updated_at "
            "FROM agents "
            "WHERE is_system = 1 AND system_key IS NOT NULL"
        )
    ).fetchall()

    if not rows:
        return

    groups: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for r in rows:
        key = (str(r[1]), str(r[2]), str(r[3]))
        groups[key].append(r)

    to_delete: list[str] = []
    for _key, group in groups.items():
        if len(group) <= 1:
            continue

        def score(row: Any) -> tuple[int, str]:
            cfg_raw = row[4]
            has_model_override = 0
            if cfg_raw:
                try:
                    cfg = json.loads(cfg_raw) if isinstance(cfg_raw, str) else dict(cfg_raw)
                    if cfg.get("model"):
                        has_model_override = 1
                except Exception:
                    pass
            ts = str(row[6] or row[5] or "")
            return (has_model_override, ts)

        sorted_group = sorted(group, key=score)
        # Keep the best row (highest score), delete earlier duplicates
        for dupe in sorted_group[:-1]:
            to_delete.append(str(dupe[0]))

    if to_delete:
        for aid in to_delete:
            bind.execute(sa.text("DELETE FROM agents WHERE id = :id"), {"id": aid})


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "agents" not in tables:
        return

    # Deduplicate any pre-existing system agent duplicates
    _deduplicate_system_agents(bind)

    indexes = {i["name"] for i in insp.get_indexes("agents")}
    if "uq_agents_tenant_project_system_key" not in indexes:
        op.create_index(
            "uq_agents_tenant_project_system_key",
            "agents",
            ["tenant_id", "project_id", "system_key"],
            unique=True,
            sqlite_where=sa.text("is_system = 1 AND system_key IS NOT NULL"),
            postgresql_where=sa.text("is_system = true AND system_key IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "agents" in tables:
        indexes = {i["name"] for i in insp.get_indexes("agents")}
        if "uq_agents_tenant_project_system_key" in indexes:
            op.drop_index("uq_agents_tenant_project_system_key", table_name="agents")
