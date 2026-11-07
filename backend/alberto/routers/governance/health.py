"""Health, readiness, version, and Prometheus metrics."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

import alberto
from alberto.config import _get_logical_data_root, settings
from alberto.db import SessionLocal
from alberto.util.metrics import snapshot

router = APIRouter(tags=["meta"])


def _v(pkg: str) -> str:
    try:
        return version(pkg)
    except PackageNotFoundError:
        return "not-installed"


@router.get("/health")
@router.get("/livez")
async def health() -> dict:
    """Liveness: the process is up and serving. Cheap and dependency-free."""
    return {"status": "ok"}


def _vector_status() -> str:
    try:
        from alberto.knowledge.store import get_vector_store_status

        st = get_vector_store_status(settings.chroma_path)
        if st.get("available"):
            return "ok" if st.get("status") == "healthy" else st.get("status", "ok")
        return f"error: {st.get('reason', 'unavailable')}"
    except Exception as e:  # noqa: BLE001
        return f"error: {type(e).__name__}"


def _graph_status() -> str:
    try:
        from alberto.knowledge.graph import _GRAPH_INSTANCE

        if _GRAPH_INSTANCE is not None and getattr(_GRAPH_INSTANCE, "_conn", None) is not None:
            res = _GRAPH_INSTANCE._conn.execute("RETURN 1 as ping").fetchall()
            if res:
                return "ok"
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"error: {type(e).__name__}"


def _disk_status() -> str:
    try:
        root = _get_logical_data_root()
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".probe_tmp"
        probe.write_text("ok", encoding="utf-8")
        if probe.exists():
            probe.unlink(missing_ok=True)
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"error: {type(e).__name__}"


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness: can this instance actually serve traffic? Checks the DB, durable
    checkpointer, vector store, graph DB, and storage write accessibility.
    Returns 503 when a gating dependency is down.
    """
    checks: dict[str, str] = {}
    try:
        async with SessionLocal() as s:
            await s.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["db"] = f"error: {type(e).__name__}"

    checks["checkpointer"] = (
        "ok" if getattr(request.app.state, "checkpointer", None) is not None else "missing"
    )
    checks["vector_store"] = _vector_status()
    checks["graph_db"] = _graph_status()
    checks["disk"] = _disk_status()

    # Gating checks: DB and disk write accessibility must be healthy.
    gating = ["db", "disk"]
    if getattr(request.app.state, "checkpointer", None) is not None:
        gating.append("checkpointer")

    ready = all(checks.get(k) == "ok" for k in gating)
    return JSONResponse(
        {
            "status": "ok" if ready else "degraded",
            "ready": ready,
            "checks": checks,
        },
        status_code=200 if ready else 503,
    )


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    """Prometheus text-format exposition of the in-process counters so operators can scrape
    them (per-worker; aggregate across replicas at the scraper). Complements the OTLP trace
    export. No new dependency - rendered directly from the counter snapshot.

    Gated behind `settings.expose_metrics` (default off): the counters are an internal
    operational surface, so keep it disabled on public deployments and enable only where the
    scrape endpoint is reachable from a trusted network."""
    if not settings.expose_metrics:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    lines: list[str] = []
    for name, value in sorted(snapshot().items()):
        metric = "forge_" + "".join(c if (c.isalnum() or c == "_") else "_" for c in name)
        lines.append(f"# TYPE {metric} counter")
        lines.append(f"{metric} {value}")
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/version")
async def version_info() -> dict:
    # Dependency versions aid fingerprinting; gate behind the same operator-only switch as /metrics.
    if not settings.expose_metrics:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return {
        "name": "alberto-api",
        "version": alberto.__version__,
        "langchain": _v("langchain"),
        "langgraph": _v("langgraph"),
    }
