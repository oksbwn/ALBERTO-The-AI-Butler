import pytest
import httpx
from unittest.mock import AsyncMock, patch

from alberto.db.base import SessionLocal
from alberto.main import create_app
from alberto.models import Tenant, User
from alberto.security import create_access_token
from alberto.services.projects import ProjectService
from alberto.services.tools import ToolService


@pytest.mark.asyncio
async def test_playground_secured_execution_read_tool():
    """Playground executing a safe read tool executes immediately without approval."""
    tenant_id = "tenant-pg-test-1"
    async with SessionLocal() as db_session:
        t = Tenant(id=tenant_id, name="Test Tenant")
        db_session.add(t)
        user = User(
            tenant_id=tenant_id,
            email="tester1@example.com",
            password_hash="pw_hash",
            role="admin",
            status="active",
        )
        db_session.add(user)
        project = await ProjectService.create(db_session, tenant_id=tenant_id, name="PG Proj 1", slug="pg-proj-1")
        tool = await ToolService.create(
            db_session,
            tenant_id=tenant_id,
            project_id=project.id,
            name="read_weather",
            kind="rest_api",
            config={
                "description": "Fetch current weather data",
                "effect": "read",
                "requires_approval": False,
                "request": {"method": "GET", "url_template": "https://api.example.com/weather"},
            },
        )
        await db_session.commit()
        await db_session.refresh(user)
        await db_session.refresh(project)
        await db_session.refresh(tool)

    token = create_access_token(user_id=user.id, tenant_id=tenant_id, role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    app = create_app()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        with patch.object(ToolService, "test", new_callable=AsyncMock) as mock_test:
            mock_test.return_value = {"ok": True, "data": {"temp": 72}}
            resp = await client.post(
                f"/v1/projects/{project.id}/tools/{tool.id}/test",
                headers=headers,
                json={"args": {"city": "Seattle"}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("ok") is True
            assert data.get("data") == {"temp": 72}


@pytest.mark.asyncio
async def test_playground_hitl_approval_lifecycle():
    """Playground executing dangerous tool triggers HITL gate:

    1. Initial run -> requires_approval=True with approval_request_id.
    2. Inspection via GET /approvals/{id}.
    3. Decision via POST /approvals/{id}/decide.
    4. Second run with approval_id -> consumes approval and executes.
    5. Third run with same approval_id -> rejected (single use).
    """
    tenant_id = "tenant-pg-test-2"
    async with SessionLocal() as db_session:
        t = Tenant(id=tenant_id, name="Test Tenant")
        db_session.add(t)
        user = User(
            tenant_id=tenant_id,
            email="tester2@example.com",
            password_hash="pw_hash",
            role="admin",
            status="active",
        )
        db_session.add(user)
        project = await ProjectService.create(db_session, tenant_id=tenant_id, name="PG Proj 2", slug="pg-proj-2")
        tool = await ToolService.create(
            db_session,
            tenant_id=tenant_id,
            project_id=project.id,
            name="delete_account",
            kind="rest_api",
            config={
                "description": "Permanently purge user account",
                "effect": "delete",
                "requires_approval": True,
                "request": {"method": "DELETE", "url_template": "https://api.example.com/users/{id}"},
            },
        )
        await db_session.commit()
        await db_session.refresh(user)
        await db_session.refresh(project)
        await db_session.refresh(tool)

    token = create_access_token(user_id=user.id, tenant_id=tenant_id, role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    app = create_app()

    run_args = {"id": "user-999"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Run without approval -> policy creates pending approval
        resp1 = await client.post(
            f"/v1/projects/{project.id}/tools/{tool.id}/test",
            headers=headers,
            json={"args": run_args},
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1.get("ok") is False
        assert data1.get("requires_approval") is True
        approval_id = data1.get("approval_request_id")
        assert approval_id is not None

        # 2. Inspect approval via Integration Manager endpoint
        resp_appr = await client.get(
            f"/v1/projects/{project.id}/integration-manager/approvals/{approval_id}",
            headers=headers,
        )
        assert resp_appr.status_code == 200
        appr_info = resp_appr.json()
        assert appr_info["id"] == approval_id
        assert appr_info["status"] == "pending"

        # 3. Decide approval -> approve
        resp_decide = await client.post(
            f"/v1/projects/{project.id}/integration-manager/approvals/{approval_id}/decide",
            headers=headers,
            json={"decision": "approve"},
        )
        assert resp_decide.status_code == 200
        decide_info = resp_decide.json()
        assert decide_info["ok"] is True
        assert decide_info["status"] == "approved"

        # 4. Run with approved approval_id -> succeeds
        with patch.object(ToolService, "test", new_callable=AsyncMock) as mock_test:
            mock_test.return_value = {"ok": True, "deleted": True}
            resp2 = await client.post(
                f"/v1/projects/{project.id}/tools/{tool.id}/test",
                headers=headers,
                json={"args": run_args, "approval_id": approval_id},
            )
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert data2.get("ok") is True
            assert data2.get("deleted") is True

        # 5. Subsequent attempt reusing consumed approval -> rejected
        resp3 = await client.post(
            f"/v1/projects/{project.id}/tools/{tool.id}/test",
            headers=headers,
            json={"args": run_args, "approval_id": approval_id},
        )
        data3 = resp3.json()
        assert data3.get("ok") is False
        assert data3.get("requires_approval") is True
        assert data3.get("approval_request_id") != approval_id


@pytest.mark.asyncio
async def test_playground_tampered_arguments_rejected():
    """If an approval was granted for args A, testing with args B and same approval_id must fail."""
    tenant_id = "tenant-pg-test-3"
    async with SessionLocal() as db_session:
        t = Tenant(id=tenant_id, name="Test Tenant")
        db_session.add(t)
        user = User(
            tenant_id=tenant_id,
            email="tester3@example.com",
            password_hash="pw_hash",
            role="admin",
            status="active",
        )
        db_session.add(user)
        project = await ProjectService.create(db_session, tenant_id=tenant_id, name="PG Proj 3", slug="pg-proj-3")
        tool = await ToolService.create(
            db_session,
            tenant_id=tenant_id,
            project_id=project.id,
            name="critical_modify",
            kind="rest_api",
            config={
                "description": "Modify critical setting",
                "effect": "write",
                "requires_approval": True,
            },
        )
        await db_session.commit()
        await db_session.refresh(user)
        await db_session.refresh(project)
        await db_session.refresh(tool)

    token = create_access_token(user_id=user.id, tenant_id=tenant_id, role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    app = create_app()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Step 1: Request approval for setting A
        resp1 = await client.post(
            f"/v1/projects/{project.id}/tools/{tool.id}/test",
            headers=headers,
            json={"args": {"setting": "safe_val"}},
        )
        appr_id = resp1.json().get("approval_request_id")
        assert appr_id is not None

        # Step 2: Approve it
        await client.post(
            f"/v1/projects/{project.id}/integration-manager/approvals/{appr_id}/decide",
            headers=headers,
            json={"decision": "approve"},
        )

        # Step 3: Attempt execution with tampered args (setting: malicious_val)
        resp_tamper = await client.post(
            f"/v1/projects/{project.id}/tools/{tool.id}/test",
            headers=headers,
            json={"args": {"setting": "malicious_val"}, "approval_id": appr_id},
        )
        data = resp_tamper.json()
        assert data.get("ok") is False
        assert data.get("requires_approval") is True
        assert data.get("approval_request_id") != appr_id
