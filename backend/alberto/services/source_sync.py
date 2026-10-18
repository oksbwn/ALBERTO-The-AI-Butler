"""Configurable Source Synchronization Service.

Provides opt-in, user-configured periodic synchronization workflows for MCP integrations
with incremental watermarks, change detection, bounded batches, and safe failure handling.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from alberto.models import McpClient, Project
from alberto.services.mcp_learning import McpLearningService
from alberto.tools.mcp import McpExecutionOutcome

logger = logging.getLogger("alberto.services.source_sync")

SYNC_TEMPLATES: dict[str, dict[str, Any]] = {
    "device_inventory": {
        "id": "device_inventory",
        "name": "Device Inventory Sync",
        "description": "Periodically synchronizes connected smart home device inventory",
        "default_cron": "0 4 * * *",
        "target_tool": "get_devices",
        "supports_incremental": True,
        "enabled_by_default": False,
    },
    "calendar_metadata": {
        "id": "calendar_metadata",
        "name": "Calendar Metadata Sync",
        "description": "Periodically synchronizes calendar metadata and schedules",
        "default_cron": "0 5 * * *",
        "target_tool": "list_events",
        "supports_incremental": True,
        "enabled_by_default": False,
    },
    "capability_refresh": {
        "id": "capability_refresh",
        "name": "Integration Capability Refresh",
        "description": "Periodically refreshes tool schemas and capability fingerprints",
        "default_cron": "0 0 * * *",
        "target_tool": "discover_tools",
        "supports_incremental": False,
        "enabled_by_default": False,
    },
}


class SourceSyncCoordinator:
    """Coordinates user-configured periodic source synchronization."""

    @classmethod
    def list_templates(cls) -> list[dict[str, Any]]:
        """Return available synchronization workflow templates."""
        return list(SYNC_TEMPLATES.values())

    @classmethod
    async def configure_sync(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        client_id: str,
        template_id: str,
        *,
        cadence_cron: str | None = None,
        enabled: bool = False,
    ) -> dict[str, Any]:
        """Configure an opt-in synchronization job on a project's MCP integration.
        Disabled by default upon creation."""
        tmpl = SYNC_TEMPLATES.get(template_id)
        if not tmpl:
            raise ValueError(f"Unknown sync template: {template_id}")

        proj = (
            await session.execute(
                select(Project).where(
                    Project.tenant_id == tenant_id,
                    Project.id == project_id,
                )
            )
        ).scalar_one_or_none()
        if not proj:
            raise ValueError(f"Project not found: {project_id}")

        cfg = dict(proj.config or {})
        sync_configs = cfg.get("mcp_sync_jobs", {})

        job_key = f"{client_id}:{template_id}"
        cron = cadence_cron or tmpl["default_cron"]

        job_entry = {
            "job_id": job_key,
            "client_id": client_id,
            "template_id": template_id,
            "template_name": tmpl["name"],
            "target_tool": tmpl["target_tool"],
            "cron": cron,
            "enabled": enabled,
            "watermark": None,
            "last_synced_at": None,
            "last_status": "never_run",
            "created_at": datetime.now(UTC).isoformat(),
        }

        sync_configs[job_key] = job_entry
        cfg["mcp_sync_jobs"] = sync_configs
        proj.config = cfg
        flag_modified(proj, "config")
        await session.commit()
        await session.refresh(proj)
        return job_entry

    @classmethod
    async def get_sync_jobs(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
    ) -> list[dict[str, Any]]:
        """List configured sync jobs for a project."""
        proj = (
            await session.execute(
                select(Project).where(
                    Project.tenant_id == tenant_id,
                    Project.id == project_id,
                )
            )
        ).scalar_one_or_none()
        if not proj or not proj.config:
            return []
        return list((proj.config.get("mcp_sync_jobs") or {}).values())

    @classmethod
    async def toggle_sync_job(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        job_id: str,
        enabled: bool,
    ) -> dict[str, Any]:
        """Enable or disable a configured sync job."""
        proj = (
            await session.execute(
                select(Project).where(
                    Project.tenant_id == tenant_id,
                    Project.id == project_id,
                )
            )
        ).scalar_one_or_none()
        if not proj:
            raise ValueError("Project not found")

        cfg = dict(proj.config or {})
        sync_jobs = cfg.get("mcp_sync_jobs", {})
        if job_id not in sync_jobs:
            raise ValueError(f"Sync job {job_id} not found")

        sync_jobs[job_id]["enabled"] = enabled
        cfg["mcp_sync_jobs"] = sync_jobs
        proj.config = cfg
        flag_modified(proj, "config")
        await session.commit()
        return sync_jobs[job_id]

    @classmethod
    async def execute_sync(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        job_id: str,
        raw_items: list[dict[str, Any]] | None = None,
        execution_outcome: McpExecutionOutcome | str = McpExecutionOutcome.SUCCESS,
    ) -> dict[str, Any]:
        """Execute a synchronization job with incremental watermark filtering and bounded batches.

        If the integration tool returns an error or is unavailable, records failure
        WITHOUT deleting existing memories or graph records.
        """
        proj = (
            await session.execute(
                select(Project).where(
                    Project.tenant_id == tenant_id,
                    Project.id == project_id,
                )
            )
        ).scalar_one_or_none()
        if not proj:
            return {"ok": False, "error": "Project not found"}

        cfg = dict(proj.config or {})
        sync_jobs = cfg.get("mcp_sync_jobs", {})
        job = sync_jobs.get(job_id)
        if not job:
            return {"ok": False, "error": f"Job {job_id} not found"}

        if not job.get("enabled", False):
            return {"ok": False, "error": "Sync job is disabled"}

        # Authoritative Execution Outcome Check: do not learn on non-success outcomes
        outcome_str = str(execution_outcome).upper()
        if outcome_str != "SUCCESS" and execution_outcome != McpExecutionOutcome.SUCCESS:
            logger.warning("Sync job %s execution outcome not successful (%s); skipping learning", job_id, execution_outcome)
            job["last_status"] = "failed"
            job["last_error"] = f"Tool execution outcome failed: {execution_outcome}"
            sync_jobs[job_id] = job
            cfg["mcp_sync_jobs"] = sync_jobs
            proj.config = cfg
            flag_modified(proj, "config")
            await session.commit()
            return {"ok": False, "error": f"Tool execution outcome failed: {execution_outcome}"}

        client_id = job["client_id"]
        client = (
            await session.execute(
                select(McpClient).where(
                    McpClient.tenant_id == tenant_id,
                    McpClient.id == client_id,
                )
            )
        ).scalar_one_or_none()

        if not client:
            return {"ok": False, "error": f"McpClient {client_id} not found"}

        if not getattr(client, "enabled", True):
            return {"ok": False, "error": f"McpClient {client_id} is disabled"}

        target_tool = job.get("target_tool", "sync_tool")
        disabled_tools = set(getattr(client, "disabled_tools", None) or [])
        if target_tool in disabled_tools:
            return {"ok": False, "error": f"Target tool {target_tool!r} is disabled for McpClient {client.name!r}"}

        # Check raw items for embedded errors
        items_to_process = raw_items or []
        for it in items_to_process:
            if isinstance(it, dict) and (it.get("isError") or it.get("is_error") or "error" in it):
                logger.warning("Sync job %s raw items contain tool error: %s", job_id, it.get("error"))
                job["last_status"] = "failed"
                job["last_error"] = str(it.get("error") or "Tool returned error payload")
                sync_jobs[job_id] = job
                cfg["mcp_sync_jobs"] = sync_jobs
                proj.config = cfg
                flag_modified(proj, "config")
                await session.commit()
                return {"ok": False, "error": "Tool execution returned error in output"}

        now = datetime.now(UTC)
        last_watermark = job.get("watermark")

        new_or_updated: list[dict[str, Any]] = []

        # Filter against watermark: only process items newer than watermark or with changed hash
        for item in items_to_process:
            item_ts = item.get("updated_at") or item.get("timestamp") or item.get("created_at")
            item_hash = hashlib.sha256(json.dumps(item, sort_keys=True).encode("utf-8")).hexdigest()[:16]

            if last_watermark and isinstance(last_watermark, str):
                if item_ts and str(item_ts) <= last_watermark:
                    continue
                if last_watermark.startswith("hash:") and last_watermark == f"hash:{item_hash}":
                    continue

            new_or_updated.append(item)

        # Enforce batch ceiling (max 100 items per sync run)
        bounded_items = new_or_updated[:100]

        # Trigger learning on new/updated items if tool learning is enabled and execution verified
        learned_event = None
        if bounded_items:
            tool_name = job.get("target_tool", "sync_tool")
            exec_id = f"sync_{job_id}_{int(now.timestamp())}"
            learned_event = await McpLearningService.schedule_tool_learning(
                tenant_id=tenant_id,
                project_id=project_id,
                client_id=client.id,
                client_name=client.name,
                tool_name=tool_name,
                tool_input={"job_id": job_id, "watermark": last_watermark},
                tool_output=bounded_items,
                execution_id=exec_id,
                execution_outcome=execution_outcome,
            )

        # Update watermark
        new_watermark = now.isoformat()
        job["watermark"] = new_watermark
        job["last_synced_at"] = new_watermark
        job["last_status"] = "success"
        sync_jobs[job_id] = job
        cfg["mcp_sync_jobs"] = sync_jobs
        proj.config = cfg
        flag_modified(proj, "config")
        await session.commit()

        return {
            "ok": True,
            "job_id": job_id,
            "total_received": len(items_to_process),
            "processed": len(bounded_items),
            "skipped_unchanged": len(items_to_process) - len(bounded_items),
            "watermark": new_watermark,
            "learning_event_id": learned_event.id if learned_event else None,
        }

    @classmethod
    def is_job_due(cls, job: dict[str, Any], now: datetime | None = None) -> bool:
        """Evaluate if a configured sync job is due based on cron or interval schedule.
        Returns False by default if disabled (no polling by default)."""
        if not job.get("enabled", False):
            return False

        now_dt = now or datetime.now(UTC)
        cron_expr = job.get("cron")
        last_str = job.get("last_synced_at") or job.get("created_at")
        last_dt = None
        if last_str:
            try:
                last_dt = datetime.fromisoformat(last_str)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
            except Exception:
                last_dt = None

        if not last_dt:
            return True

        if cron_expr:
            try:
                from croniter import croniter  # type: ignore

                base_dt = last_dt or (now_dt - timedelta(minutes=1))
                nxt = croniter(cron_expr, base_dt).get_next(datetime)
                if nxt.tzinfo is None:
                    nxt = nxt.replace(tzinfo=UTC)
                return nxt <= now_dt
            except (ImportError, Exception):
                parts = cron_expr.strip().split()
                if len(parts) == 5:
                    m, h, dom, mon, dow = parts
                    if m == "*" and h == "*":
                        return (now_dt - last_dt) >= timedelta(minutes=1)
                    if m.startswith("*/"):
                        step = int(m[2:])
                        return (now_dt - last_dt) >= timedelta(minutes=step)
                    if m.isdigit() and h.isdigit():
                        return (now_dt - last_dt) >= timedelta(hours=23) and now_dt.hour == int(h)
                return (now_dt - last_dt) >= timedelta(hours=24)

        interval_mins = job.get("interval_minutes")
        if interval_mins:
            if not last_dt:
                return True
            return (now_dt - last_dt) >= timedelta(minutes=int(interval_mins))

        return False

    @classmethod
    async def execute_due_sync_jobs(
        cls,
        session: AsyncSession,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Find all enabled and due sync jobs across projects and execute them."""
        projects = list((await session.execute(select(Project))).scalars())
        results = []
        for proj in projects:
            cfg = proj.config or {}
            jobs = cfg.get("mcp_sync_jobs", {})
            for job_id, job in list(jobs.items()):
                if cls.is_job_due(job, now=now):
                    logger.info("Executing scheduled sync job %s for project %s", job_id, proj.id)
                    res = await cls.execute_sync(
                        session=session,
                        tenant_id=proj.tenant_id,
                        project_id=proj.id,
                        job_id=job_id,
                    )
                    results.append(res)
        return results


SourceSyncService = SourceSyncCoordinator
