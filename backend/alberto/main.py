"""FastAPI application factory + lifespan.

Builds our own server on the MIT LangChain/LangGraph framework - never depends on
`langgraph-api` or LangSmith. Lifespan initializes the DB, the durable-execution
checkpointer, and dev seed data.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import alberto
from alberto.config import settings
from alberto.db import SessionLocal, init_db
from alberto.db.seed import bootstrap, seed_demo_data
from alberto.routers import (
    agents,
    assistant,
    audit,
    auth,
    auth_providers,
    channels,
    components,
    connections,
    connectors,
    conversations,
    evals,
    graph,
    handoff,
    health,
    hooks,
    knowledge,
    mcp_clients,
    memory,
    models,
    nodes,
    oauth,
    project_run,
    projects,
    runs,
    secrets,
    stats,
    tool_sets,
    tools,
    traces,
    versions,
    workflows,
)
from alberto.routers import (
    triggers as triggers_router,
)
from alberto.util.http import aclose_shared_client


async def _make_checkpointer(stack: AsyncExitStack):
    """Durable-execution checkpointer:
    - "memory": ephemeral (tests / throwaway).
    - "sqlite" (default): local SQLite database file.
    """
    backend = (settings.checkpoint_backend or "sqlite").lower()
    if backend == "memory" or settings.checkpoint_db == "memory":
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    cp = await stack.enter_async_context(AsyncSqliteSaver.from_conn_string(settings.checkpoint_db))
    try:
        await cp.setup()
    except Exception:  # noqa: BLE001 - setup is idempotent; ignore "already exists"
        pass
    return cp


async def _reaper_loop(app: FastAPI) -> None:
    """Periodically reap runs stuck in queued/running (never streamed, or driver died) so
    they can't linger forever (audit F3)."""
    from alberto.services.runs import RunService

    log = logging.getLogger("forge.reaper")
    run_service = RunService(checkpointer=app.state.checkpointer, store=app.state.store)
    while True:
        try:
            await asyncio.sleep(300)
            await run_service.reap_stale_runs()
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001 - keep the reaper alive across failures
            log.exception("reaper tick failed")


async def _retention_loop() -> None:
    """Purge traces/spans/runs past each project's retention horizon and audit logs past the
    workspace horizon, on a timer (finding e). Leader-only (like the reaper) so a multi-replica
    deployment purges once. No-op unless a retention window is configured."""
    from alberto.services.retention import RetentionService

    log = logging.getLogger("forge.retention")
    interval = max(60, settings.retention_interval_seconds or 3600)
    while True:
        try:
            await asyncio.sleep(interval)
            await RetentionService.purge_expired()
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001 - keep the retention loop alive across failures
            log.exception("retention tick failed")


async def _scheduler_loop(app: FastAPI) -> None:
    """Fire due `schedule` triggers once a minute. Single-worker in-process scheduler."""
    from alberto.services.dispatch import run_due_app_events, run_due_schedules
    from alberto.services.runs import RunService

    log = logging.getLogger("forge.scheduler")
    run_service = RunService(checkpointer=app.state.checkpointer, store=app.state.store)
    while True:
        try:
            await asyncio.sleep(60)
            await run_due_schedules(run_service)
            await run_due_app_events(run_service)
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001 - keep the scheduler alive across failures
            log.exception("scheduler tick failed")


def _preload_heavy_modules() -> None:
    """Import the slow modules off the critical path. First import of langchain_openai
    / chromadb costs ~22s / ~9s on this machine (AV scanning); doing it in a daemon
    thread at startup means the first real run doesn't pay it."""
    import importlib

    for mod in ("langchain_openai", "chromadb", "langchain.chat_models"):
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001 - optional providers may be missing
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Install the IPv4-first DNS resolver before anything opens a connection, so outbound calls
    # (LLM providers, REST tools, DB) never pay the multi-second AAAA-lookup stall.
    if settings.prefer_ipv4_egress:
        from alberto.util.netfix import install_prefer_ipv4_dns

        install_prefer_ipv4_dns()
    settings.ensure_dirs()
    problems = settings.validate_production()
    if problems:
        # Refuse to serve a misconfigured production install (default secrets, auth off,
        # SSRF guard off, SQLite, non-durable checkpointer, unsandboxed code). Set the
        # flagged env vars before deploying. Enforced for every non-dev environment (S6).
        raise RuntimeError("Unsafe production configuration:\n  - " + "\n  - ".join(problems))
    for warn in settings.startup_warnings():
        logging.getLogger("forge.config").warning("INSECURE CONFIG: %s", warn)
    await init_db()
    threading.Thread(target=_preload_heavy_modules, name="forge-preload", daemon=True).start()
    app.state.exit_stack = AsyncExitStack()
    app.state.checkpointer = await _make_checkpointer(app.state.exit_stack)
    from alberto.queue import set_checkpointer

    set_checkpointer(app.state.checkpointer)
    async with SessionLocal() as session:
        tenant_id = await bootstrap(session)
        if settings.seed_demo:
            await seed_demo_data(session, tenant_id)
        app.state.tenant_id = tenant_id
    from alberto.knowledge.graph import get_graph_adapter
    app.state.graph_db = get_graph_adapter()
    # Immediate startup sweep for stranded runs and abandoned tasks from previous process (Milestone 1.6)
    with contextlib.suppress(Exception):
        from alberto.services.runs import RunService

        startup_run_service = RunService(checkpointer=app.state.checkpointer, store=app.state.store)
        reaped = await startup_run_service.reap_stale_runs(
            queued_max_age_s=settings.run_wall_clock_timeout_seconds * 3,
            running_max_age_s=settings.run_wall_clock_timeout_seconds,
        )
        if reaped:
            logging.getLogger("forge.startup").info("Startup sweep reaped %d stale/abandoned runs", reaped)
    # Immediate startup sweep for pending/interrupted memory learning events (Milestone 2.1)
    with contextlib.suppress(Exception):
        from alberto.services.learning_coordinator import LearningCoordinator

        recovered = await LearningCoordinator.recover_pending_events()
        if recovered:
            logging.getLogger("forge.startup").info("Startup sweep recovered %d pending learning events", recovered)
    if settings.otel_enabled:
        from alberto.tracing import otel

        otel.configure()
    bg_tasks: list[asyncio.Task] = []
    # The scheduler must run on EXACTLY ONE instance (else every replica double-fires).
    # `enable_scheduler` turns it on; `scheduler_leader` elects the single instance by env
    # so you can ship one image everywhere (audit P3).
    if settings.enable_scheduler and settings.scheduler_leader:
        bg_tasks.append(asyncio.create_task(_scheduler_loop(app), name="forge-scheduler"))
    # The reaper is safe to run everywhere (idempotent), but one instance is enough.
    if settings.scheduler_leader:
        bg_tasks.append(asyncio.create_task(_reaper_loop(app), name="forge-reaper"))
    # Data-retention purge (leader-only): ages out traces/spans/runs + audit logs (finding e).
    if settings.enable_retention and settings.scheduler_leader:
        bg_tasks.append(asyncio.create_task(_retention_loop(), name="forge-retention"))
    yield
    for t in bg_tasks:
        t.cancel()
    for t in bg_tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await t
    from alberto.util.tasks import drain

    await drain()
    with contextlib.suppress(Exception):
        from alberto.tools.mcp import close_all

        await close_all()
    with contextlib.suppress(Exception):
        from alberto.queue import close_pool

        await close_pool()
    with contextlib.suppress(Exception):
        from alberto.queue import set_checkpointer

        set_checkpointer(None)
    with contextlib.suppress(Exception):
        from alberto.knowledge.graph import reset_graph_adapter

        reset_graph_adapter()
    await aclose_shared_client()
    await app.state.exit_stack.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Alberto API",
        version=alberto.__version__,
        description="Alberto - local-first AI Home Butler.",
        lifespan=lifespan,
    )
    # Host-header allow-list (defense-in-depth against Host-header attacks). Empty => any (dev).
    if settings.trusted_hosts:
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Coarse per-IP request ceiling (api_rate_limit_per_minute) as a blunt DoS guard;
    # complements the per-surface limits. Health/SSE exempt (finding a).
    if settings.enable_global_rate_limit:
        from alberto.util.ratelimit import GlobalRateLimitMiddleware

        app.add_middleware(GlobalRateLimitMiddleware)
    # Audit all successful mutations (pure ASGI; safe with SSE streams).
    from alberto.audit_middleware import AuditMiddleware

    app.add_middleware(AuditMiddleware)
    for r in (
        health.router, auth.router, auth.team_router, auth.workspace_router,
        audit.router, oauth.router, hooks.router,
        models.router, nodes.router, projects.router, workflows.router, runs.router, project_run.router,
        tool_sets.router, tools.router, components.router, auth_providers.router, connections.router, secrets.router, agents.router,
        knowledge.router, knowledge.qa_router, traces.router, conversations.router, assistant.router, stats.router,
        triggers_router.router, channels.router, channels.public, handoff.router, evals.router,
        mcp_clients.router, versions.router,
        graph.router, memory.router,
        connectors.router,
    ):
        app.include_router(r)
    return app


app = create_app()
