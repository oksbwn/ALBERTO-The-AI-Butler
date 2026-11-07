"""Dashboard stats & rollups service over traces and spans."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.db.base import engine
from alberto.models import Project, Span, Tool, Trace, Workflow

_DIALECT = engine.dialect.name


def _day_bucket(col):
    if _DIALECT == "sqlite":
        return func.strftime("%Y-%m-%d", col)
    return func.to_char(func.date_trunc("day", col), "YYYY-MM-DD")


_ACTIVITY = func.coalesce(Trace.started_at, Trace.created_at)

_LATENCY_BUCKETS: list[tuple[str, int | None]] = [
    ("<250ms", 250),
    ("250-500ms", 500),
    ("500ms-1s", 1000),
    ("1-2s", 2000),
    ("2-5s", 5000),
    ("5-10s", 10000),
    (">10s", None),
]


def _agg_columns():
    return (
        func.count().label("runs"),
        func.coalesce(func.sum(Trace.total_tokens), 0).label("tokens"),
        func.coalesce(func.sum(Trace.total_cost_usd), 0.0).label("cost"),
        func.coalesce(func.sum(Trace.latency_ms), 0).label("latency_sum"),
        func.coalesce(func.sum(case((Trace.status == "error", 1), else_=0)), 0).label("errors"),
    )


def _rollup(row) -> dict[str, Any]:
    runs = int(row.runs or 0)
    errors = int(row.errors or 0)
    return {
        "runs": runs,
        "tokens": int(row.tokens or 0),
        "cost_usd": round(float(row.cost or 0.0), 6),
        "avg_latency_ms": int((row.latency_sum or 0) / runs) if runs else 0,
        "errors": errors,
        "error_rate": round(errors / runs * 100, 1) if runs else 0.0,
    }


def _ts_row(row) -> dict[str, Any]:
    runs = int(row.runs or 0)
    return {
        "date": row.day,
        "runs": runs,
        "tokens": int(row.tokens or 0),
        "cost_usd": round(float(row.cost or 0.0), 6),
        "avg_latency_ms": int((row.latency_sum or 0) / runs) if runs else 0,
        "errors": int(row.errors or 0),
        "success": int(row.success or 0),
    }


class StatsService:
    @staticmethod
    async def get_dashboard(session: AsyncSession, tenant_id: str) -> dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=7)
        tenant = Trace.tenant_id == tenant_id

        totals = _rollup((await session.execute(select(*_agg_columns()).where(tenant))).one())

        win = (await session.execute(
            select(
                func.count().label("runs"),
                func.coalesce(func.sum(case((Trace.status.in_(("done", "interrupted")), 1), else_=0)), 0).label("done"),
                func.coalesce(func.sum(Trace.total_cost_usd), 0.0).label("cost"),
                func.coalesce(func.sum(Trace.latency_ms), 0).label("latency_sum"),
            ).where(tenant, _ACTIVITY >= since)
        )).one()
        total = int(win.runs or 0)
        done = int(win.done or 0)
        avg_latency = int((win.latency_sum or 0) / total) if total else 0

        per_project: dict[str, dict[str, int]] = {}

        def bucket(pid: str) -> dict[str, int]:
            return per_project.setdefault(pid, {"workflows": 0, "tools": 0, "runs_7d": 0})

        for pid, n in (await session.execute(
            select(Workflow.project_id, func.count()).where(Workflow.tenant_id == tenant_id).group_by(Workflow.project_id)
        )).all():
            bucket(pid)["workflows"] = int(n)
        for pid, n in (await session.execute(
            select(Tool.project_id, func.count()).where(Tool.tenant_id == tenant_id).group_by(Tool.project_id)
        )).all():
            bucket(pid)["tools"] = int(n)
        for pid, n in (await session.execute(
            select(Trace.project_id, func.count()).where(tenant, _ACTIVITY >= since).group_by(Trace.project_id)
        )).all():
            bucket(pid)["runs_7d"] = int(n)

        wf_names: dict[str, str] = {wid: name for wid, name in (await session.execute(
            select(Workflow.id, Workflow.name).where(Workflow.tenant_id == tenant_id)
        )).all()}
        proj_names: dict[str, str] = {pid: name for pid, name in (await session.execute(
            select(Project.id, Project.name).where(Project.tenant_id == tenant_id)
        )).all()}

        recent_rows = (await session.execute(
            select(
                Trace.id, Trace.workflow_id, Trace.project_id, Trace.status,
                Trace.total_tokens, Trace.latency_ms, Trace.total_cost_usd, Trace.started_at,
            ).where(tenant).order_by(Trace.started_at.desc()).limit(8)
        )).all()
        recent = [
            {
                "id": r.id,
                "workflow": wf_names.get(r.workflow_id or "", "run"),
                "project": proj_names.get(r.project_id, "-"),
                "status": r.status,
                "tokens": r.total_tokens,
                "latency_ms": r.latency_ms,
                "cost_usd": round(r.total_cost_usd or 0.0, 6),
                "started_at": r.started_at.isoformat() if r.started_at else None,
            }
            for r in recent_rows
        ]

        report_rows = (await session.execute(
            select(
                Trace.project_id,
                *_agg_columns(),
                func.coalesce(func.sum(case((Trace.name == "assistant", Trace.total_cost_usd), else_=0.0)), 0.0).label("asst_cost"),
                func.coalesce(func.sum(case((Trace.name == "assistant", 1), else_=0)), 0).label("asst_turns"),
            ).where(tenant).group_by(Trace.project_id)
        )).all()
        reports = [
            {
                "project_id": r.project_id,
                "project": proj_names.get(r.project_id, "(deleted project)"),
                **_rollup(r),
                "assistant_cost_usd": round(float(r.asst_cost or 0.0), 6),
                "assistant_turns": int(r.asst_turns or 0),
            }
            for r in report_rows
        ]
        reports.sort(key=lambda r: r["cost_usd"], reverse=True)

        return {
            "runs_7d": total,
            "total_runs": totals["runs"],
            "success_rate": round(done / total * 100, 1) if total else 0.0,
            "avg_latency_ms": avg_latency,
            "spend_7d": round(float(win.cost or 0.0), 6),
            "recent": recent,
            "projects": per_project,
            "reports": reports,
            "totals": totals,
        }

    @staticmethod
    async def get_project_stats(session: AsyncSession, tenant_id: str, project_id: str) -> dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=7)
        scope = (Trace.tenant_id == tenant_id, Trace.project_id == project_id)

        totals = _rollup((await session.execute(select(*_agg_columns()).where(*scope))).one())
        last_7d = _rollup((await session.execute(select(*_agg_columns()).where(*scope, _ACTIVITY >= since))).one())
        asst = (await session.execute(select(*_agg_columns()).where(*scope, Trace.name == "assistant"))).one()
        assistant = {**_rollup(asst), "turns": int(asst.runs or 0)}

        wf_names: dict[str, str] = {wid: name for wid, name in (await session.execute(
            select(Workflow.id, Workflow.name).where(Workflow.tenant_id == tenant_id, Workflow.project_id == project_id)
        )).all()}

        kind = case(
            (Trace.name == "assistant", "assistant"),
            (Trace.workflow_id.isnot(None), "workflow"),
            else_="other",
        ).label("kind")
        ident = case(
            (Trace.name == "assistant", "assistant"),
            (Trace.workflow_id.isnot(None), Trace.workflow_id),
            else_=Trace.name,
        ).label("ident")
        grouped = (await session.execute(
            select(kind, ident, *_agg_columns()).where(*scope).group_by(kind, ident)
        )).all()
        reports = []
        for r in grouped:
            if r.kind == "assistant":
                label = "Forge Assistant"
            elif r.kind == "workflow":
                label = wf_names.get(r.ident, "(deleted workflow)")
            else:
                label = r.ident
            reports.append({"label": label, "kind": r.kind, **_rollup(r)})
        reports.sort(key=lambda r: r["cost_usd"], reverse=True)

        return {
            "totals": totals,
            "last_7d": last_7d,
            "assistant": assistant,
            "reports": reports,
        }

    @staticmethod
    async def get_project_analytics(session: AsyncSession, tenant_id: str, project_id: str, days: int = 30) -> dict[str, Any]:
        days = max(1, min(days, 365))
        now = datetime.utcnow()
        since = now - timedelta(days=days)
        prev_since = since - timedelta(days=days)
        scope = (Trace.tenant_id == tenant_id, Trace.project_id == project_id)
        span_scope = (Trace.tenant_id == tenant_id, Trace.project_id == project_id, _ACTIVITY >= since)

        totals = _rollup((await session.execute(select(*_agg_columns()).where(*scope, _ACTIVITY >= since))).one())
        prev_totals = _rollup(
            (await session.execute(select(*_agg_columns()).where(*scope, _ACTIVITY >= prev_since, _ACTIVITY < since))).one()
        )

        day = _day_bucket(_ACTIVITY).label("day")
        ts_rows = (await session.execute(
            select(
                day, *_agg_columns(),
                func.coalesce(func.sum(case((Trace.status.in_(("done", "interrupted")), 1), else_=0)), 0).label("success"),
            ).where(*scope, _ACTIVITY >= since).group_by(day).order_by(day)
        )).all()
        by_day = {r.day: _ts_row(r) for r in ts_rows}
        timeseries: list[dict[str, Any]] = []
        cursor = since.date()
        end = now.date()
        while cursor <= end:
            key = cursor.isoformat()
            timeseries.append(by_day.get(key) or {
                "date": key, "runs": 0, "tokens": 0, "cost_usd": 0.0, "avg_latency_ms": 0, "errors": 0, "success": 0,
            })
            cursor += timedelta(days=1)

        src_rows = (await session.execute(
            select(Trace.source, *_agg_columns()).where(*scope, _ACTIVITY >= since).group_by(Trace.source)
        )).all()
        by_source = [{"source": r.source or "-", **_rollup(r)} for r in src_rows]
        by_source.sort(key=lambda r: r["runs"], reverse=True)

        kind = case(
            (Trace.name == "assistant", "assistant"),
            (Trace.workflow_id.isnot(None), "workflow"),
            else_="other",
        ).label("kind")
        ident = case(
            (Trace.name == "assistant", "assistant"),
            (Trace.workflow_id.isnot(None), Trace.workflow_id),
            else_=Trace.name,
        ).label("ident")
        grouped = (await session.execute(
            select(kind, ident, *_agg_columns()).where(*scope, _ACTIVITY >= since).group_by(kind, ident)
        )).all()
        wf_names: dict[str, str] = {wid: name for wid, name in (await session.execute(
            select(Workflow.id, Workflow.name).where(Workflow.tenant_id == tenant_id, Workflow.project_id == project_id)
        )).all()}
        by_workflow = []
        for r in grouped:
            if r.kind == "assistant":
                label = "Forge Assistant"
            elif r.kind == "workflow":
                label = wf_names.get(r.ident, "(deleted workflow)")
            else:
                label = r.ident
            by_workflow.append({"label": label, "kind": r.kind, **_rollup(r)})
        by_workflow.sort(key=lambda r: r["cost_usd"], reverse=True)

        span_lat = func.coalesce(func.sum(Span.latency_ms), 0).label("latency_sum")
        span_calls = func.count().label("calls")
        span_tokens = func.coalesce(func.sum(Span.input_tokens + Span.output_tokens), 0).label("tokens")
        span_cost = func.coalesce(func.sum(Span.cost_usd), 0.0).label("cost")

        tool_rows = (await session.execute(
            select(
                Span.name, span_calls, span_lat, span_tokens, span_cost,
                func.coalesce(func.sum(case((Span.error.isnot(None), 1), else_=0)), 0).label("errors"),
            ).join(Trace, Trace.id == Span.trace_id)
            .where(*span_scope, Span.kind == "tool")
            .group_by(Span.name).order_by(span_calls.desc()).limit(12)
        )).all()
        tools = [
            {
                "name": r.name,
                "calls": int(r.calls or 0),
                "avg_latency_ms": int((r.latency_sum or 0) / r.calls) if r.calls else 0,
                "errors": int(r.errors or 0),
                "cost_usd": round(float(r.cost or 0.0), 6),
                "tokens": int(r.tokens or 0),
            }
            for r in tool_rows
        ]

        model_rows = (await session.execute(
            select(Span.model, span_calls, span_lat, span_tokens, span_cost)
            .join(Trace, Trace.id == Span.trace_id)
            .where(*span_scope, Span.kind == "llm", Span.model.isnot(None))
            .group_by(Span.model).order_by(span_cost.desc()).limit(12)
        )).all()
        models = [
            {
                "model": r.model,
                "calls": int(r.calls or 0),
                "tokens": int(r.tokens or 0),
                "cost_usd": round(float(r.cost or 0.0), 6),
                "avg_latency_ms": int((r.latency_sum or 0) / r.calls) if r.calls else 0,
            }
            for r in model_rows
        ]

        hist_cols = []
        lo = 0
        for i, (_, hi) in enumerate(_LATENCY_BUCKETS):
            if hi is None:
                cond = Trace.latency_ms >= lo
            elif lo == 0:
                cond = Trace.latency_ms < hi
            else:
                cond = (Trace.latency_ms >= lo) & (Trace.latency_ms < hi)
            hist_cols.append(func.coalesce(func.sum(case((cond, 1), else_=0)), 0).label(f"b{i}"))
            lo = hi or lo
        hist_row = (await session.execute(select(*hist_cols).where(*scope, _ACTIVITY >= since))).one()
        latency_histogram = [
            {"label": label, "count": int(getattr(hist_row, f"b{i}") or 0)}
            for i, (label, _) in enumerate(_LATENCY_BUCKETS)
        ]

        recent_rows = (await session.execute(
            select(
                Trace.id, Trace.workflow_id, Trace.name, Trace.status,
                Trace.total_tokens, Trace.latency_ms, Trace.total_cost_usd, Trace.started_at,
            ).where(*scope, _ACTIVITY >= since).order_by(Trace.started_at.desc()).limit(8)
        )).all()
        recent = [
            {
                "id": r.id,
                "workflow": wf_names.get(r.workflow_id or "", r.name or "run"),
                "project": "",
                "status": r.status,
                "tokens": r.total_tokens,
                "latency_ms": r.latency_ms,
                "cost_usd": round(r.total_cost_usd or 0.0, 6),
                "started_at": r.started_at.isoformat() if r.started_at else None,
            }
            for r in recent_rows
        ]

        return {
            "range": {"days": days, "since": since.isoformat(), "until": now.isoformat(), "bucket": "day"},
            "totals": totals,
            "prev_totals": prev_totals,
            "timeseries": timeseries,
            "by_source": by_source,
            "by_workflow": by_workflow,
            "tools": tools,
            "models": models,
            "latency_histogram": latency_histogram,
            "recent": recent,
        }
