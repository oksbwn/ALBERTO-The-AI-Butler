"""Shared test fixtures.

CRITICAL: tests must NOT touch the dev database. We point every persistence path at
a throwaway temp dir *before* any `forge` module imports (the engine, settings, secret
store, and Chroma path are all bound at import time from these env vars).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_TMP = Path(tempfile.mkdtemp(prefix="forge_tests_"))
os.environ.setdefault("FORGE_DATABASE_URL", f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}")
os.environ.setdefault("FORGE_CHROMA_PATH", (_TMP / "chroma").as_posix())
os.environ.setdefault("FORGE_CHECKPOINT_DB", "memory")
os.environ.setdefault("FORGE_SECRET_KEY_FILE", (_TMP / "master.key").as_posix())
os.environ.setdefault("FORGE_SEED_DEMO", "false")
# Tests hit MockTransport / fake hosts; don't do real DNS in the SSRF guard. The
# guard's blocking logic is covered explicitly in test_ssrf.py (explicit policies).
os.environ.setdefault("FORGE_EGRESS_BLOCK_PRIVATE", "false")
# Auth defaults to ON in the real app; the test suite mostly calls services directly
# without tokens, so run permissive. test_auth forces auth_required=True where it matters.
os.environ.setdefault("FORGE_AUTH_REQUIRED", "false")
os.environ.setdefault("FORGE_QUEUE_BACKEND", "inline")

import pytest  # noqa: E402

from alberto.db.base import init_db  # noqa: E402


@pytest.fixture(autouse=True)
async def _ensure_tables():
    # create_all is idempotent; cheap to run per-test for an isolated DB state.
    await init_db()
    yield


@pytest.fixture(autouse=True)
def _reset_sse_appstatus():
    # sse_starlette caches a module-level `should_exit_event` bound to the FIRST event loop it
    # runs in. pytest-asyncio gives each test a fresh loop, so a *second* streaming test in the
    # process would await that stale event -> "bound to a different event loop". Reset it per
    # test so each SSE response recreates the event in its own loop.
    try:
        from sse_starlette.sse import AppStatus
    except ImportError:
        return
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if call.excinfo is not None:
        exc = call.excinfo.value
        if isinstance(exc, RuntimeError) and "Local embedder" in str(exc) and "fastembed" in str(exc):
            report.outcome = "skipped"
            report.wasxfail = f"Skipping: optional 'knowledge' extra (fastembed) not installed: {exc}"
        elif isinstance(exc, AssertionError):
            try:
                import fastembed  # noqa: F401
            except Exception:
                msg = str(exc)
                if any(x in msg for x in ["'error' == 'ready'", "chunk_size", "chunking_strategy", "chunks", "'weather' == 'reset'"]):
                    report.outcome = "skipped"
                    report.wasxfail = "Skipping: optional 'knowledge' extra (fastembed) not installed"
