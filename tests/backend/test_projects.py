"""Project tests."""

from __future__ import annotations

from alberto.db.base import SessionLocal
from alberto.models import (
    Agent,
    AuthProvider,
    Component,
    HandoffRequest,
    KbSource,
    Tool,
    Workflow,
)
from alberto.services.projects import ProjectService


async def test_project_counts_are_scoped_to_project():
    tenant_id = "tenant_counts"
    async with SessionLocal() as session:
        proj = await ProjectService.create(session, tenant_id, name="Counts", slug="counts")
        other = await ProjectService.create(session, tenant_id, name="Other", slug="other")
        session.add_all([
            Workflow(tenant_id=tenant_id, project_id=proj.id, name="wf1"),
            Workflow(tenant_id=tenant_id, project_id=proj.id, name="wf2"),
            Agent(tenant_id=tenant_id, project_id=proj.id, name="a", config={}),
            Tool(tenant_id=tenant_id, project_id=proj.id, name="t1", kind="builtin", config={}),
            Tool(tenant_id=tenant_id, project_id=proj.id, name="t2", kind="builtin", config={}),
            Tool(tenant_id=tenant_id, project_id=proj.id, name="t3", kind="builtin", config={}),
            Component(tenant_id=tenant_id, project_id=proj.id, name="card"),
            KbSource(tenant_id=tenant_id, project_id=proj.id, kind="text", name="src"),
            AuthProvider(tenant_id=tenant_id, project_id=proj.id, name="auth", kind="bearer", config={}),
            HandoffRequest(tenant_id=tenant_id, project_id=proj.id, run_id="run-open", status="open"),
            HandoffRequest(tenant_id=tenant_id, project_id=proj.id, run_id="run-done", status="answered"),
            # Belongs to a different project in the same tenant - must NOT be counted for `proj`.
            Tool(tenant_id=tenant_id, project_id=other.id, name="other_tool", kind="builtin", config={}),
            Workflow(tenant_id=tenant_id, project_id=other.id, name="other_wf"),
        ])
        await session.commit()

        # ProjectService.create auto-provisions the platform built-ins, so each project starts with
        # len(BUILTIN_DEFAULTS) tools before the 3 added here. Scoping still holds: `other`'s tool
        # (and its own provisioned built-ins) are not counted for `proj`.
        from alberto.tools.builtin import BUILTIN_DEFAULTS
        counts = await ProjectService.counts(session, tenant_id, proj.id)
        assert counts == {
            "workflows": 2, "agents": 1, "tools": 3 + len(BUILTIN_DEFAULTS),
            "components": 1, "knowledge": 1, "auth": 1, "handoffs": 1, "connectors": 0,
        }
        # A fresh project is all zeros except the auto-provisioned platform built-ins (never None).
        empty = await ProjectService.create(session, tenant_id, name="Empty", slug="empty")
        assert await ProjectService.counts(session, tenant_id, empty.id) == {
            "workflows": 0, "agents": 0, "tools": len(BUILTIN_DEFAULTS), "components": 0, "knowledge": 0, "auth": 0,
            "handoffs": 0, "connectors": 0,
        }
