"""Project CRUD."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.models import (
    Agent,
    AuthProvider,
    Component,
    ConnectorInstall,
    HandoffRequest,
    KbSource,
    Project,
    Tool,
    Workflow,
)

# Sidebar badge counts. Keys match `countKey` in apps/web/lib/data.ts (PROJECT_NAV); the
# sidebar reads these instead of fetching six full lists just to call `.length`.
_COUNT_MODELS: dict[str, type] = {
    "workflows": Workflow,
    "agents": Agent,
    "tools": Tool,
    "components": Component,
    "knowledge": KbSource,
    "auth": AuthProvider,
    "connectors": ConnectorInstall,
}


class ProjectService:
    @staticmethod
    async def list(session: AsyncSession, tenant_id: str) -> list[Project]:
        rows = await session.execute(
            select(Project).where(Project.tenant_id == tenant_id, Project.archived.is_(False))
        )
        return list(rows.scalars())

    @staticmethod
    async def counts(session: AsyncSession, tenant_id: str, project_id: str) -> dict[str, int]:
        """Per-resource counts for the project sidebar badges. Cheap COUNT(*) per table
        (tenant+project scoped) instead of pulling six full lists client-side."""
        out: dict[str, int] = {}
        for key, model in _COUNT_MODELS.items():
            stmt = select(func.count()).select_from(model).where(
                model.tenant_id == tenant_id, model.project_id == project_id
            )
            if model is Agent:
                stmt = stmt.where(Agent.is_system.is_(False))
            n = await session.scalar(stmt)
            out[key] = int(n or 0)
        open_handoffs = await session.scalar(
            select(func.count()).select_from(HandoffRequest).where(
                HandoffRequest.tenant_id == tenant_id,
                HandoffRequest.project_id == project_id,
                HandoffRequest.status == "open",
            )
        )
        out["handoffs"] = int(open_handoffs or 0)
        return out

    @staticmethod
    async def get(session: AsyncSession, tenant_id: str, project_id: str) -> Project | None:
        row = await session.execute(
            select(Project).where(Project.tenant_id == tenant_id, Project.id == project_id)
        )
        return row.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: str,
        *,
        name: str,
        slug: str | None = None,
        description: str | None = None,
        config: dict | None = None,
    ) -> Project:
        project = Project(
            tenant_id=tenant_id,
            name=name,
            slug=slug or name.lower().replace(" ", "-"),
            description=description,
            config=config or {},
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        # Provision the platform's built-in tools so a brand-new project has them immediately
        # (agents can reference them before the tools screen is ever opened).
        from alberto.services.tools import ToolService
        await ToolService.ensure_builtins(session, tenant_id, project.id)
        from alberto.services.agents import AgentService
        await AgentService.ensure_system_agents(session, tenant_id, project.id)
        return project

    @staticmethod
    async def update(
        session: AsyncSession, project: Project, *, name: str | None = None,
        description: str | None = None, config: dict | None = None,
    ) -> Project:
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if config is not None:
            project.config = config
        await session.commit()
        await session.refresh(project)
        return project
