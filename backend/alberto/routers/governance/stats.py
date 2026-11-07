"""Dashboard stats router - tenant-wide and project-scoped rollups over real traces."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.deps import current_tenant_id, get_session
from alberto.services.governance.stats import StatsService

router = APIRouter(prefix="/v1/stats", tags=["stats"])


# --- response models (typed contract for OpenAPI) ---

class RollupOut(BaseModel):
    runs: int
    tokens: int
    cost_usd: float
    avg_latency_ms: int
    errors: int
    error_rate: float


class RecentRunOut(BaseModel):
    id: str
    workflow: str
    project: str
    status: str
    tokens: int
    latency_ms: int
    cost_usd: float
    started_at: str | None = None


class ProjectCardStatsOut(BaseModel):
    workflows: int
    tools: int
    runs_7d: int


class DashboardReportOut(RollupOut):
    project_id: str
    project: str
    assistant_cost_usd: float
    assistant_turns: int


class DashboardStatsOut(BaseModel):
    runs_7d: int
    total_runs: int
    success_rate: float
    avg_latency_ms: int
    spend_7d: float
    recent: list[RecentRunOut]
    projects: dict[str, ProjectCardStatsOut]
    reports: list[DashboardReportOut]
    totals: RollupOut


class ReportRowOut(RollupOut):
    label: str
    kind: str


class AssistantRollupOut(RollupOut):
    turns: int


class ProjectStatsOut(BaseModel):
    totals: RollupOut
    last_7d: RollupOut
    assistant: AssistantRollupOut
    reports: list[ReportRowOut]


class TimeBucketOut(BaseModel):
    date: str
    runs: int
    tokens: int
    cost_usd: float
    avg_latency_ms: int
    errors: int
    success: int


class SourceRollupOut(RollupOut):
    source: str


class ToolStatOut(BaseModel):
    name: str
    calls: int
    avg_latency_ms: int
    errors: int
    cost_usd: float
    tokens: int


class ModelStatOut(BaseModel):
    model: str
    calls: int
    tokens: int
    cost_usd: float
    avg_latency_ms: int


class LatencyBucketOut(BaseModel):
    label: str
    count: int


class AnalyticsRangeOut(BaseModel):
    days: int
    since: str
    until: str
    bucket: str


class AnalyticsOut(BaseModel):
    range: AnalyticsRangeOut
    totals: RollupOut
    prev_totals: RollupOut
    timeseries: list[TimeBucketOut]
    by_source: list[SourceRollupOut]
    by_workflow: list[ReportRowOut]
    tools: list[ToolStatOut]
    models: list[ModelStatOut]
    latency_histogram: list[LatencyBucketOut]
    recent: list[RecentRunOut]


@router.get("/dashboard", response_model=DashboardStatsOut)
async def dashboard(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
):
    """Tenant-wide KPI rollups and recent runs."""
    return await StatsService.get_dashboard(session, tenant_id)


@router.get("/projects/{project_id}", response_model=ProjectStatsOut)
async def project_stats(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
):
    """Project-scoped rollups + report rows."""
    return await StatsService.get_project_stats(session, tenant_id, project_id)


@router.get("/projects/{project_id}/analytics", response_model=AnalyticsOut)
async def project_analytics(
    project_id: str,
    days: int = 30,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
):
    """Time-series + breakdowns for project Analytics dashboard."""
    return await StatsService.get_project_analytics(session, tenant_id, project_id, days=days)
