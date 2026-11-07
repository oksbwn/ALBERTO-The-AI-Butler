"""Postgres RLS tenant-GUC wiring and ORM Scoping Guard tests.

Verifies the request-scoped tenant contextvar round-trips, SQLite resilience,
and automatic ORM query/mutation scoping isolation.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select, text, update

from alberto import models
from alberto.db.base import SessionLocal
from alberto.db.scoping import (
    bypass_tenant_guard,
    current_tenant,
    set_current_tenant,
    tenant_guard,
)


def test_tenant_contextvar_roundtrip():
    set_current_tenant(None)
    assert current_tenant() is None
    set_current_tenant("t-1")
    assert current_tenant() == "t-1"
    with tenant_guard("t-2"):
        assert current_tenant() == "t-2"
    assert current_tenant() == "t-1"
    set_current_tenant(None)


async def test_sqlite_session_unaffected_by_guc():
    with tenant_guard("any-tenant"):
        async with SessionLocal() as s:
            assert (await s.execute(text("SELECT 1"))).scalar() == 1


async def test_tenant_isolation_select():
    # Setup two projects in different tenants
    async with SessionLocal() as s:
        p1 = models.Project(name="Tenant 1 Project", slug="t1-proj", tenant_id="tenant-alpha")
        p2 = models.Project(name="Tenant 2 Project", slug="t2-proj", tenant_id="tenant-beta")
        s.add_all([p1, p2])
        await s.commit()

    # Query with tenant-alpha active
    with tenant_guard("tenant-alpha"):
        async with SessionLocal() as s:
            projects = (await s.execute(select(models.Project))).scalars().all()
            project_names = [p.name for p in projects]
            assert "Tenant 1 Project" in project_names
            assert "Tenant 2 Project" not in project_names

    # Query with tenant-beta active
    with tenant_guard("tenant-beta"):
        async with SessionLocal() as s:
            projects = (await s.execute(select(models.Project))).scalars().all()
            project_names = [p.name for p in projects]
            assert "Tenant 2 Project" in project_names
            assert "Tenant 1 Project" not in project_names


async def test_tenant_cross_insert_blocked():
    with tenant_guard("tenant-alpha"):
        async with SessionLocal() as s:
            p = models.Project(name="Sneaky Project", slug="sneaky", tenant_id="tenant-beta")
            s.add(p)
            with pytest.raises(PermissionError) as exc_info:
                await s.commit()
            assert "Cross-tenant insert violation" in str(exc_info.value)


async def test_tenant_auto_assign_on_insert():
    with tenant_guard("tenant-alpha"):
        async with SessionLocal() as s:
            p = models.Project(name="Auto Assigned", slug="auto-assigned")
            s.add(p)
            await s.commit()
            assert p.tenant_id == "tenant-alpha"


async def test_tenant_bypass():
    with tenant_guard("tenant-alpha"):
        with bypass_tenant_guard():
            async with SessionLocal() as s:
                projects = (await s.execute(select(models.Project))).scalars().all()
                project_names = [p.name for p in projects]
                assert "Tenant 1 Project" in project_names
                assert "Tenant 2 Project" in project_names
