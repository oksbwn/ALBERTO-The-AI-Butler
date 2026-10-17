"""baseline - full current schema

Squash baseline: stamps the entire current schema via metadata.create_all (skips
existing tables, so it's safe on an already-bootstrapped dev DB). Incremental
migrations are added on top with `alembic revision --autogenerate`.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-14
"""

from alembic import op
from alberto.db.base import Base

import alberto.models  # noqa: F401 - register tables

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
