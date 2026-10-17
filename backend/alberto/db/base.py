"""Async engine, session factory, and declarative base.

SQLite (aiosqlite) by default; set FORGE_DATABASE_URL to a Postgres async URL in
prod (no code change). `init_db` creates tables for dev; Alembic owns prod migrations.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from alberto.config import settings


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return str(uuid.uuid4())


class PkTimestamp:
    """Mixin: string-UUID primary key + created/updated timestamps."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


# SQLite configuration (check_same_thread disabled for async driver, 30s timeout).
_connect_args = {"check_same_thread": False, "timeout": 30.0}
# NullPool opens a fresh connection per checkout and closes it immediately, avoiding
# asyncio event loop teardown issues across tests.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args=_connect_args,
    poolclass=NullPool,
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)




async def init_db() -> None:
    # Import models so they register on Base.metadata before create_all.
    from alberto import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_new_columns)


def _ensure_new_columns(conn) -> None:
    """Dev-grade additive migration: create_all never alters existing tables, so
    columns added to the ORM after a table exists must be ALTERed in. Alembic owns
    real migrations in prod; this covers the SQLite dev database."""
    from sqlalchemy import inspect, text

    wanted = {
        "kb_sources": {"folder": "VARCHAR(200) NOT NULL DEFAULT ''"},
        "triggers": {"metadata": "JSON DEFAULT '{}'"},
        "agents": {
            "created_by": "VARCHAR(36)",
            "created_by_email": "VARCHAR(320)",
            "is_system": "BOOLEAN NOT NULL DEFAULT 0",
            "system_key": "VARCHAR(64)",
        },
        "mcp_clients": {"disabled_tools": "JSON DEFAULT '[]'"},
        "api_keys": {"user_id": "VARCHAR(36)", "project_id": "VARCHAR(36)"},
        "tool_sets": {"exposed": "BOOLEAN NOT NULL DEFAULT 1"},
        "projects": {"embed_key": "VARCHAR(64)"},
        "spans": {"input": "JSON", "output": "JSON"},
        "runs": {
            "source": "VARCHAR(40) NOT NULL DEFAULT 'playground'",
            "iterations_count": "INTEGER NOT NULL DEFAULT 0",
            "tool_calls_count": "INTEGER NOT NULL DEFAULT 0",
            "termination_reason": "VARCHAR(64)",
        },
        "traces": {
            "source": "VARCHAR(40) NOT NULL DEFAULT 'playground'",
            "actor": "VARCHAR(300) NOT NULL DEFAULT 'System'",
            "end_user_id": "VARCHAR(200)",
            "user_message": "TEXT",
            "ai_response": "TEXT",
            "iterations_count": "INTEGER NOT NULL DEFAULT 0",
            "tool_calls_count": "INTEGER NOT NULL DEFAULT 0",
            "termination_reason": "VARCHAR(64)",
        },
    }
    inspector = inspect(conn)
    for table, columns in wanted.items():
        if table not in inspector.get_table_names():
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for col, ddl in columns.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))

    if "agents" in inspector.get_table_names():
        idx_names = {idx["name"] for idx in inspector.get_indexes("agents")}
        if "uq_agents_tenant_project_system_key" not in idx_names:
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agents_tenant_project_system_key "
                        "ON agents (tenant_id, project_id, system_key) "
                        "WHERE is_system = 1 AND system_key IS NOT NULL"
                    )
                )
            except Exception:
                pass


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
