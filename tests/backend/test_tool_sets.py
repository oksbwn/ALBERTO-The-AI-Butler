"""Tool Sets: service CRUD + membership, agent toolset->tools resolution, and the REST API."""

from __future__ import annotations

import uuid

import httpx

from alberto.db.base import SessionLocal
from alberto.main import create_app
from alberto.models import Project, Tool, User
from alberto.services.runtime import build_compile_context
from alberto.services.tool_sets import ToolSetService
from alberto.services.tools import ToolService


async def _seed(tenant: str, slug: str) -> tuple[str, str, str]:
    async with SessionLocal() as s:
        proj = Project(tenant_id=tenant, name="TS Proj", slug=slug, config={})
        s.add(proj)
        await s.flush()
        t1 = Tool(tenant_id=tenant, project_id=proj.id, name="alpha", kind="builtin",
                  config={"builtin": "calculator", "description": "a"})
        t2 = Tool(tenant_id=tenant, project_id=proj.id, name="beta", kind="builtin",
                  config={"builtin": "current_time", "description": "b"})
        s.add_all([t1, t2])
        await s.commit()
        for obj in (proj, t1, t2):
            await s.refresh(obj)
        return proj.id, t1.id, t2.id


async def test_tool_set_service_crud_and_membership():
    tenant = "t_ts_svc"
    pid, t1, t2 = await _seed(tenant, "ts-svc")
    async with SessionLocal() as s:
        ts = await ToolSetService.create(s, tenant, pid, name="Billing Tools", description="billing", tool_ids=[t1, t2])
        assert ts.slug == "billing-tools"
        assert set(await ToolSetService.member_ids(s, tenant, ts.id)) == {t1, t2}
        assert set((await ToolSetService.members_map(s, tenant, pid))[ts.id]) == {t1, t2}
        assert set(await ToolSetService.tool_ids_for_sets(s, tenant, pid, [ts.id])) == {t1, t2}

        # unknown / cross-project ids are filtered out of membership
        ts2 = await ToolSetService.create(s, tenant, pid, name="X", tool_ids=[t1, "does-not-exist"])
        assert await ToolSetService.member_ids(s, tenant, ts2.id) == [t1]

        # add / remove membership
        await ToolSetService.remove_member(s, ts, t1)
        assert await ToolSetService.member_ids(s, tenant, ts.id) == [t2]
        await ToolSetService.add_member(s, ts, t1)
        assert set(await ToolSetService.member_ids(s, tenant, ts.id)) == {t1, t2}
        await ToolSetService.add_member(s, ts, t1)  # idempotent (no duplicate row)
        assert len(await ToolSetService.member_ids(s, tenant, ts.id)) == 2

        # rename regenerates a unique slug (collides with ts2's "x")
        ts = await ToolSetService.update(s, ts, name="X")
        assert ts.slug == "x-2"

        # update can replace membership wholesale
        ts = await ToolSetService.update(s, ts, tool_ids=[t2])
        assert await ToolSetService.member_ids(s, tenant, ts.id) == [t2]

        # delete removes the set and its membership rows
        set_id = ts.id
        await ToolSetService.delete(s, ts)
        assert await ToolSetService.get(s, tenant, set_id) is None
        assert set_id not in await ToolSetService.members_map(s, tenant, pid)


async def test_tool_deletion_removes_membership():
    tenant = "t_ts_del"
    pid, t1, t2 = await _seed(tenant, "ts-del")
    async with SessionLocal() as s:
        ts = await ToolSetService.create(s, tenant, pid, name="S", tool_ids=[t1, t2])
        tool = await ToolService.get(s, tenant, t1)
        await ToolService.delete(s, tool)  # deleting a tool must drop its membership rows
        assert await ToolSetService.member_ids(s, tenant, ts.id) == [t2]


async def test_build_compile_context_resolves_toolset_to_member_tools():
    tenant = "t_ts_ctx"
    pid, t1, t2 = await _seed(tenant, "ts-ctx")
    async with SessionLocal() as s:
        set_id = (await ToolSetService.create(s, tenant, pid, name="Set A", tool_ids=[t1, t2])).id
    async with SessionLocal() as s:
        ctx = await build_compile_context(s, tenant_id=tenant, project_id=pid)
    # membership is loaded onto the compile context
    assert set(ctx.toolset_members.get(set_id, [])) == {t1, t2}
    # an agent granted only the set resolves to the set's member tool ids...
    assert set(ctx.resolve_tool_ids([], [set_id])) == {t1, t2}
    # ...and to the materialized tools (both builtins compiled into the registry)
    assert len(ctx.tools_for(ctx.resolve_tool_ids([], [set_id]))) == 2


async def test_tool_sets_api_end_to_end():
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        # register a real user (mutations require a real principal, not the dev fallback)
        reg = await c.post("/v1/auth/register", json={"email": f"u{uuid.uuid4().hex[:10]}@example.com", "password": "supersecret1"})
        assert reg.status_code == 201, reg.text
        c.headers["Authorization"] = f"Bearer {reg.json()['access_token']}"
        # project + two tools, all via the API (one consistent tenant = the registered workspace)
        pid = (await c.post("/v1/projects", json={"name": "API TS", "slug": "api-ts"})).json()["id"]

        def _mk(name: str, builtin: str) -> dict:
            return {"name": name, "kind": "builtin", "config": {"builtin": builtin, "description": name}}

        t1 = (await c.post(f"/v1/projects/{pid}/tools", json=_mk("aa", "calculator"))).json()["id"]
        t2 = (await c.post(f"/v1/projects/{pid}/tools", json=_mk("bb", "current_time"))).json()["id"]

        # create a set with one member
        r = await c.post(f"/v1/projects/{pid}/tool-sets", json={"name": "Group One", "description": "g1", "tool_ids": [t1]})
        assert r.status_code == 201, r.text
        st = r.json()
        assert st["slug"] == "group-one" and st["tool_ids"] == [t1] and st["description"] == "g1"
        sid = st["id"]

        # list
        r = await c.get(f"/v1/projects/{pid}/tool-sets")
        assert r.status_code == 200 and any(x["id"] == sid for x in r.json())

        # add + remove via the membership endpoints
        assert (await c.post(f"/v1/projects/{pid}/tool-sets/{sid}/tools/{t2}")).status_code == 204
        assert set((await c.get(f"/v1/projects/{pid}/tool-sets/{sid}")).json()["tool_ids"]) == {t1, t2}
        assert (await c.delete(f"/v1/projects/{pid}/tool-sets/{sid}/tools/{t1}")).status_code == 204

        # patch: rename + replace membership
        r = await c.patch(f"/v1/projects/{pid}/tool-sets/{sid}", json={"name": "Renamed", "tool_ids": [t1, t2]})
        assert r.json()["slug"] == "renamed" and set(r.json()["tool_ids"]) == {t1, t2}

        # delete
        assert (await c.delete(f"/v1/projects/{pid}/tool-sets/{sid}")).status_code == 204
        assert (await c.get(f"/v1/projects/{pid}/tool-sets/{sid}")).status_code == 404
