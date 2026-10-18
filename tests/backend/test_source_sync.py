"""
Tests for Alberto Milestone 2.2: Configurable Source Synchronization Execution.
Verifies workflow configuration, activation, disablement, persistence,
restart recovery, scheduled execution, authorized tool scopes, and watermark persistence.
"""

from datetime import UTC, datetime, timedelta
import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy.orm.attributes import flag_modified

from alberto.db import SessionLocal
from alberto.models import McpClient, Project
from alberto.services.source_sync import SourceSyncCoordinator, SourceSyncService
from alberto.services.dispatch import run_due_source_syncs


@pytest.fixture
async def sync_fixture():
    """Fixture creating sample project and McpClient."""
    async with SessionLocal() as session:
        proj = Project(
            name="Sync Test Project",
            slug="sync-test-project",
            tenant_id="tenant_sync",
            config={"tool_execution_learning_enabled": True},
        )
        session.add(proj)
        await session.commit()
        await session.refresh(proj)

        client = McpClient(
            name="SmartThings Integration",
            tenant_id="tenant_sync",
            project_id=proj.id,
            transport="stdio",
            command="python",
            enabled=True,
            learning_enabled=True,
            disabled_tools=[],
        )
        session.add(client)
        await session.commit()
        await session.refresh(client)

        proj_id = proj.id
        client_id = client.id
        tenant_id = proj.tenant_id

    return tenant_id, proj_id, client_id


@pytest.mark.asyncio
async def test_configure_activate_disable_and_persist_sync(sync_fixture):
    """Users can create, configure, activate, disable and persist synchronization workflows."""
    tenant_id, proj_id, client_id = sync_fixture

    async with SessionLocal() as session:
        # 1. Configure sync: default disabled (no polling by default)
        job = await SourceSyncService.configure_sync(
            session=session,
            tenant_id=tenant_id,
            project_id=proj_id,
            client_id=client_id,
            template_id="device_inventory",
            cadence_cron="0 2 * * *",
            enabled=False,
        )
        assert job["enabled"] is False
        assert job["cron"] == "0 2 * * *"
        assert job["target_tool"] == "get_devices"
        assert job["watermark"] is None

        # 2. Persistence in Project.config
        persisted_jobs = await SourceSyncService.get_sync_jobs(
            session=session,
            tenant_id=tenant_id,
            project_id=proj_id,
        )
        assert len(persisted_jobs) == 1
        assert persisted_jobs[0]["job_id"] == job["job_id"]

        # 3. Activate workflow
        activated = await SourceSyncService.toggle_sync_job(
            session=session,
            tenant_id=tenant_id,
            project_id=proj_id,
            job_id=job["job_id"],
            enabled=True,
        )
        assert activated["enabled"] is True

        # 4. Disable workflow
        disabled = await SourceSyncService.toggle_sync_job(
            session=session,
            tenant_id=tenant_id,
            project_id=proj_id,
            job_id=job["job_id"],
            enabled=False,
        )
        assert disabled["enabled"] is False


@pytest.mark.asyncio
async def test_watermark_persistence_and_incremental_sync(sync_fixture):
    """Verify incremental sync filtering and watermark persistence in DB."""
    tenant_id, proj_id, client_id = sync_fixture

    async with SessionLocal() as session:
        job = await SourceSyncCoordinator.configure_sync(
            session=session,
            tenant_id=tenant_id,
            project_id=proj_id,
            client_id=client_id,
            template_id="device_inventory",
            enabled=True,
        )

        t0 = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        raw_items_batch1 = [
            {"id": "dev_1", "name": "Kitchen Light", "updated_at": t0},
            {"id": "dev_2", "name": "Hallway Sensor", "updated_at": t0},
        ]

        # Run 1
        with patch("alberto.services.mcp_learning.McpLearningService.schedule_tool_learning", new_callable=AsyncMock) as mock_learn:
            mock_learn.return_value = None
            res1 = await SourceSyncCoordinator.execute_sync(
                session=session,
                tenant_id=tenant_id,
                project_id=proj_id,
                job_id=job["job_id"],
                raw_items=raw_items_batch1,
            )

        assert res1["ok"] is True
        assert res1["processed"] == 2
        assert res1["skipped_unchanged"] == 0
        assert res1["watermark"] is not None

        # Check watermark in project config
        jobs_after = await SourceSyncCoordinator.get_sync_jobs(session, tenant_id, proj_id)
        assert jobs_after[0]["watermark"] == res1["watermark"]
        assert jobs_after[0]["last_status"] == "success"

        # Run 2 with identical/older timestamp items -> skipped
        with patch("alberto.services.mcp_learning.McpLearningService.schedule_tool_learning", new_callable=AsyncMock) as mock_learn:
            res2 = await SourceSyncCoordinator.execute_sync(
                session=session,
                tenant_id=tenant_id,
                project_id=proj_id,
                job_id=job["job_id"],
                raw_items=raw_items_batch1,
            )

        assert res2["ok"] is True
        assert res2["processed"] == 0
        assert res2["skipped_unchanged"] == 2


@pytest.mark.asyncio
async def test_authorized_tool_scopes(sync_fixture):
    """Sync execution enforces authorized integration and tool scopes."""
    tenant_id, proj_id, client_id = sync_fixture

    async with SessionLocal() as session:
        job = await SourceSyncCoordinator.configure_sync(
            session=session,
            tenant_id=tenant_id,
            project_id=proj_id,
            client_id=client_id,
            template_id="device_inventory",
            enabled=True,
        )

        client = await session.get(McpClient, client_id)
        # 1. McpClient disabled -> sync rejected
        client.enabled = False
        await session.commit()

        res_disabled = await SourceSyncCoordinator.execute_sync(
            session=session,
            tenant_id=tenant_id,
            project_id=proj_id,
            job_id=job["job_id"],
            raw_items=[{"name": "Dev"}],
        )
        assert res_disabled["ok"] is False
        assert "disabled" in res_disabled["error"].lower()

        # Re-enable McpClient
        client.enabled = True
        # 2. Tool in disabled_tools list -> sync rejected
        client.disabled_tools = ["get_devices"]
        await session.commit()

        res_tool_disabled = await SourceSyncCoordinator.execute_sync(
            session=session,
            tenant_id=tenant_id,
            project_id=proj_id,
            job_id=job["job_id"],
            raw_items=[{"name": "Dev"}],
        )
        assert res_tool_disabled["ok"] is False
        assert "disabled" in res_tool_disabled["error"].lower()


@pytest.mark.asyncio
async def test_scheduled_execution_and_restart_recovery(sync_fixture):
    """Verify schedule due evaluation, restart recovery, and scheduler dispatcher wiring."""
    tenant_id, proj_id, client_id = sync_fixture

    async with SessionLocal() as session:
        # Configure job with cron every minute
        job = await SourceSyncCoordinator.configure_sync(
            session=session,
            tenant_id=tenant_id,
            project_id=proj_id,
            client_id=client_id,
            template_id="device_inventory",
            cadence_cron="* * * * *",
            enabled=False,
        )

        now = datetime.now(UTC)

        # 1. Disabled job is never due (no polling by default)
        assert SourceSyncCoordinator.is_job_due(job, now=now) is False

        # 2. Enable job
        job["enabled"] = True
        job["created_at"] = (now - timedelta(minutes=5)).isoformat()
        job["last_synced_at"] = (now - timedelta(minutes=5)).isoformat()
        assert SourceSyncCoordinator.is_job_due(job, now=now) is True

        # Update project config to persist enabled state
        proj = await session.get(Project, proj_id)
        assert proj is not None
        cfg = dict(proj.config or {})
        sync_jobs = cfg.get("mcp_sync_jobs", {})
        sync_jobs[job["job_id"]]["enabled"] = True
        sync_jobs[job["job_id"]]["last_synced_at"] = (now - timedelta(minutes=5)).isoformat()
        cfg["mcp_sync_jobs"] = sync_jobs
        proj.config = cfg
        flag_modified(proj, "config")
        await session.commit()

    # 3. Test scheduler integration: run_due_source_syncs
    with patch("alberto.services.source_sync.SourceSyncCoordinator.execute_sync", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"ok": True, "job_id": job["job_id"]}
        fired_count = await run_due_source_syncs()
        assert fired_count >= 1
        assert mock_exec.called
