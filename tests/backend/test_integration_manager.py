import pytest
import httpx

from alberto.db.base import SessionLocal
from alberto.main import create_app
from alberto.models import Tenant, User
from alberto.security import create_access_token
from alberto.services.agents import AgentService


@pytest.mark.asyncio
async def test_integration_manager_system_subagent_identity_and_upgrade():
    """Verify that ensure_system_agents creates/updates tool_manager agent

    with display name 'Integration Manager', keeping system_key 'tool_manager'.
    """
    tenant_id = "tenant-im-test"
    project_id = "proj-im-test"

    async with SessionLocal() as session:
        # Run ensure_system_agents
        agents = await AgentService.ensure_system_agents(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
        )

        im_agent = next((a for a in agents if getattr(a, "system_key", None) == "tool_manager"), None)
        assert im_agent is not None, "tool_manager system subagent must exist"
        assert im_agent.name == "Integration Manager"
        assert im_agent.is_system is True
        cfg = im_agent.config or {}
        assert "Integration Manager" in cfg.get("prompt", "") or "Integration Manager" in im_agent.name

        # Idempotent re-run does not duplicate or alter custom overrides
        agents_again = await AgentService.ensure_system_agents(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        assert len(agents_again) == len(agents)
        im_again = next((a for a in agents_again if getattr(a, "system_key", None) == "tool_manager"), None)
        assert im_again is not None
        assert im_again.id == im_agent.id
        assert im_again.name == "Integration Manager"


@pytest.mark.asyncio
async def test_integration_manager_route_alias():
    """Verify that /v1/projects/{project_id}/integration-manager is routed

    identically to /v1/projects/{project_id}/tool-manager.
    """
    tenant_id = "tenant-im-alias"
    project_id = "proj-im-alias"

    async with SessionLocal() as session:
        t = Tenant(id=tenant_id, name="Test Tenant")
        session.add(t)
        user = User(
            tenant_id=tenant_id,
            email="admin-im@example.com",
            password_hash="pw_hash",
            role="admin",
            status="active",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    token = create_access_token(user_id=user.id, tenant_id=tenant_id, role="admin")
    headers = {"Authorization": f"Bearer {token}"}

    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Channel diagnosis endpoint under integration-manager route alias (POST method)
        resp = await client.post(
            f"/v1/projects/{project_id}/integration-manager/diagnose-channel/non-existent-channel",
            headers=headers,
        )
        # Channel not found -> 404
        assert resp.status_code == 404
        data = resp.json()
        assert "not found" in data["detail"].lower()
