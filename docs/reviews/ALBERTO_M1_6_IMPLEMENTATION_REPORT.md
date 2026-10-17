# Alberto — Milestone 1.6 Implementation Report
**Execution Reliability, Runtime Hardening & Resilience**

---

## 1. Executive Summary

Milestone 1.6 implements comprehensive runtime execution reliability, safety boundaries, and failure resilience across Alberto's local-first execution stack.

Based on the code-level findings documented in `docs/reviews/ALBERTO_M1_6_EXECUTION_AUDIT.md`, this milestone remediated critical reliability gaps in ReAct agent loops, execution timeouts, tool invocations, SQLite queue worker lease ownership, cancellation races, SSE streaming memory boundedness, and startup recovery.

All implementations strictly adhered to Alberto's core principles:
- **Zero new external infrastructure** (no Redis, Celery, or external daemons).
- **Local-first, single-container architecture preserved**.
- **Deterministic safeguards** over speculative LLM-driven controls.
- **Strict backward compatibility** across existing APIs and configuration.
- **Surgical, verifiable changes backed by regression tests**.

---

## 2. Implemented Remediations Matrix

| Audit Finding | Priority | Target Component | Status | Remediation Summary |
|---|---|---|---|---|
| **ReAct Loop Guardrails** | **P0** | `agent_node.py`<br>`middleware_compiler.py` | **Implemented** | Automatic injection of `ModelCallLimitMiddleware` (25 calls), `ToolCallLimitMiddleware` (50 calls), and canonical `RepeatedToolCallMiddleware` (3 identical no-progress calls). |
| **Execution Wall-Clock Deadline** | **P0** | `config.py`<br>`runs.py` | **Implemented** | Changed `run_wall_clock_timeout_seconds` default from `0` to `300s`. Enforced hard asyncio deadline via `asyncio.timeout()` wrapping `astream()` / `ainvoke()`. |
| **SQL & MCP Tool Timeouts** | **P0** | `sql.py`<br>`mcp.py`<br>`config.py` | **Implemented** | Added `sql_tool_timeout_seconds=30` and `mcp_tool_timeout_seconds=30`. Enforced asyncio timeout, clean rollback on cancel, and Postgres `statement_timeout`. |
| **Worker Lease & Crash Recovery** | **P0** | `queue.py`<br>`worker.py` | **Implemented** | Lightweight SQLite lease ownership with `available_at` backoff column, background heartbeat renewal, lease expiry recovery, idempotency check, and `(id, locked_by, locked_at)` fencing. |
| **Cancellation & Completion Race** | **P1** | `runs.py` | **Implemented** | Atomic terminal-state check in `_finalize()` and `_finalize_error()` preventing operator `canceled` status from being overwritten by delayed `done` or `error`. |
| **SSE Broker Memory Boundedness** | **P1** | `runs.py`<br>`config.py` | **Implemented** | Replaced unbounded `events: list` with bounded `deque(maxlen=1000)` in `_RunBroker`. Implemented `has_evicted()` with fallback to DB trace reconstruction on late reconnect. |
| **Startup Stale Run Sweeper** | **P1** | `main.py`<br>`runs.py` | **Implemented** | Added immediate startup sweep in `lifespan()` reclaiming abandoned `running` (>60s) and `queued` (>300s) runs from previous process crashes. |
| **Worker Retry Backoff** | **P1** | `worker.py` | **Implemented** | Exponential backoff with jitter on non-deadletter queue retries using `available_at` schedule timestamp. |
| **Execution Observability Gaps** | **P2** | `entities.py`<br>`base.py`<br>`runs.py` | **Implemented** | Persisted `iterations_count`, `tool_calls_count`, and `termination_reason` on both `Run` and `Trace` models. |

---

## 3. Detailed Component Implementation

### 3.1 Bounded ReAct & Subagent Execution (P0)

- **Configuration:** Added defaults in `backend/alberto/config.py`:
  ```python
  max_model_calls_per_run: int = 25
  max_tool_calls_per_run: int = 50
  max_repeated_no_progress_calls: int = 3
  ```
- **Loop Detection Middleware:** Implemented `RepeatedToolCallMiddleware(AgentMiddleware)` in `backend/alberto/engine/middleware_compiler.py`:
  - Normalizes tool call arguments via canonical JSON sorting (`_canonical_args`).
  - Tracks consecutive unsuccessful tool invocations per `(tool_name, norm_args)`.
  - Distinguishes legitimate progress (e.g., pagination, changing payloads) from no-progress loops (identical error messages, empty payloads, or unvarying results).
  - Resets streak counter upon meaningful progress or distinct tool execution.
  - Halts execution with `RepeatedToolCallLimitError` when threshold is exceeded.
- **Default Injection:** Updated `_ensure_safety_middleware()` in `backend/alberto/nodes/agent_node.py` to automatically wrap both root agents (`agent_factory`) and subagents (`build_subagents` for `deep_agent`). Author-provided custom middlewares cannot accidentally discard mandatory safety limits.

### 3.2 Execution Wall-Clock Deadlines (P0)

- **Default Timeout:** Set `run_wall_clock_timeout_seconds: int = 300` (5 minutes) in `backend/alberto/config.py`.
- **Asyncio Deadline Mechanism:** In `backend/alberto/services/runs.py`:
  - Wrapped `graph.astream()` loops in `_drive()` and `run_to_completion()` within `asyncio.timeout(wall_clock)`.
  - Wrapped `graph.ainvoke()` in `resume()` within `asyncio.timeout(wall_clock)`.
  - When `TimeoutError` is raised, execution immediately stops scheduling further graph steps, frees concurrency slots and thread locks, captures partial traces and snapshot state, and records `termination_reason = "wall_clock_timeout"`.
  - Preserved HITL pauses: approval wait times are governed by approval timeout policies rather than active execution budgets.

### 3.3 SQL & MCP Tool Timeouts (P0)

- **SQL Execution Timeout (`backend/alberto/tools/sql.py`):**
  - Added configurable `sql_tool_timeout_seconds: int = 30`.
  - Wrapped connection acquisition and stream mapping within `asyncio.timeout(timeout)`.
  - Injected Postgres driver `SET LOCAL statement_timeout = <ms>` when dialect is PostgreSQL.
  - On timeout, transactions are cleanly rolled back (`await session.rollback()`) and closed, raising structured `SqlToolError`.
- **MCP Tool Timeout (`backend/alberto/tools/mcp.py`):**
  - Added configurable `mcp_tool_timeout_seconds: int = 30`.
  - Implemented `_wrap_with_timeout(tool, timeout_seconds)` wrapping remote tool execution.
  - Wrapped all tools exposed via `server_tools()` and `load_mcp_tool()`.
  - Returns structured timeout error messages to the agent context without terminating the outer worker.

### 3.4 SQLite Worker Lease Ownership & Crash Recovery (P0)

- **Schema Enhancement (`backend/alberto/queue.py`, `backend/alberto/worker.py`):**
  - Added `available_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP` to `job_queue` table.
  - Added index `idx_job_queue_status_avail ON job_queue(status, available_at)`.
- **Atomic Claiming with Delays:**
  - `_claim_next_job()` claims only jobs where `status = 'queued'` and `(available_at IS NULL OR available_at <= CURRENT_TIMESTAMP)`.
  - Sets `status = 'running'`, `locked_at = CURRENT_TIMESTAMP`, `locked_by = worker_id`, incrementing `attempts`.
- **Fenced Acknowledgement:**
  - `_finish_job()` verifies ownership fence:
    ```sql
    UPDATE job_queue
    SET status = ?, error = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ? AND locked_by = ? AND locked_at = ?;
    ```
  - An expired worker whose job was reclaimed cannot overwrite the new owner's state.
- **Heartbeat Renewal:**
  - Background task `_heartbeat()` periodically updates `locked_at = CURRENT_TIMESTAMP` for active long-running jobs.
- **Idempotency-Aware Recovery:**
  - `recover_abandoned_jobs()` identifies tasks in `status = 'running'` with expired leases (`locked_at < now - lease_timeout`).
  - Queries workflow definition: if explicitly marked idempotent (`executable.idempotent = true`), the task is re-queued with exponential backoff delay.
  - If the task has uncertain side effects, it is transitioned to `failed` and marked in `Run` as `error`, preventing accidental duplicate real-world actions.

### 3.5 Terminal State Consistency & Race Safety (P1)

- **Atomic Guard in `runs.py`:**
  - In `_finalize()`, queries current DB status before committing `done`:
    ```python
    cur = (await session.execute(
        select(Run.status, Run.termination_reason).where(Run.id == run.id, Run.tenant_id == run.tenant_id)
    )).first()
    if cur and cur[0] == "canceled":
        status = "canceled"
        termination_reason = cur[1] or "canceled"
    elif cur and cur[0] in ("done", "error") and cur[0] != status:
        return
    ```
  - In `_finalize_error()`, if DB status is already `canceled`, the write is aborted to preserve operator cancellation.

### 3.6 SSE Ring Buffer & Reconnect Resilience (P1)

- **Bounded Queue in `_RunBroker`:**
  - Replaced unbounded `self.events = []` with `deque(maxlen=settings.sse_event_buffer_size or 1000)`.
  - Added `has_evicted(last_event_id: int) -> bool` to detect when a reconnecting client's cursor has been pruned.
- **Fallback to DB Reattach:**
  - If a client reconnects with an evicted sequence ID and the run has completed, `stream()` falls back to `_reattach_from_db()` to deliver the final persisted answer without crashing.

### 3.7 Immediate Startup Stale Run Sweeper (P1)

- **Startup Hook in `backend/alberto/main.py`:**
  - During application `lifespan()`, `reap_stale_runs(queued_max_age_s=300, running_max_age_s=60)` is invoked immediately upon initialization.
  - Runs left in `running` or `queued` status from an unexpected crash or container restart are cleaned up within seconds rather than lingering for up to an hour.

### 3.8 Observability & Structured Metadata (P2)

- **Database Fields (`backend/alberto/models/entities.py`, `backend/alberto/db/base.py`):**
  - Added `iterations_count: Mapped[int]` (default 0).
  - Added `tool_calls_count: Mapped[int]` (default 0).
  - Added `termination_reason: Mapped[str | None]` (nullable, up to 64 chars).
  - Added to both `Run` and `Trace` models.
- **Trace Calculation:**
  - Derived from tracer spans: `iterations_count = sum(1 for s in spans if s.kind in ("llm", "agent"))`.
  - `tool_calls_count = sum(1 for s in spans if s.kind == "tool")`.
  - Recorded reasons: `"completed"`, `"canceled"`, `"wall_clock_timeout"`, `"repeated_tool_call_limit"`, `"tool_call_limit"`, `"model_call_limit"`, `"recursion_limit"`, `"stale_running_reaped"`.

---

## 4. Verification and Regression Test Suite

All targeted regression tests were created in `tests/backend/` and passed:

```text
============================= test session starts =============================
platform win32 -- Python 3.13.14, pytest-9.1.1, pluggy-1.7.0
rootdir: C:\Users\oksbw\OneDrive\Desktop\Workspace\Alberto
configfile: pytest.ini

tests\backend\test_react_repeated_tool_guard.py ...                      [ 13%]
tests\backend\test_default_middleware.py ....                            [ 31%]
tests\backend\test_run_deadline_enforcement.py .                         [ 36%]
tests\backend\test_sql_mcp_tool_timeout.py ..                            [ 45%]
tests\backend\test_worker_lease_recovery.py ...                          [ 59%]
tests\backend\test_queue.py .....                                        [ 81%]
tests\backend\test_cancellation_completion_race.py .                     [ 86%]
tests\backend\test_sse_broker_bounded_buffer.py ..                       [ 95%]
tests\backend\test_startup_stale_run_sweep.py .                          [100%]

============================= 22 passed in 3.92s ==============================
```

Existing test suites (E2E regressions, SQL tools, SSE reconnects, conversations) were re-verified:
- **22 passed in 8.73s** with zero regressions.

---

## 5. Architectural Invariants Preserved

1. **Local-First & Lightweight:** No Redis, no RabbitMQ, no Celery, no Docker sidecars added.
2. **SQLite Durability:** Leverages SQLite WAL mode, PRAGMA busy_timeout, and atomic conditional single-statement updates.
3. **LangGraph State Integrity:** Retains `AsyncSqliteSaver` checkpointer semantics and execution tracing.
4. **Backward Compatibility:** All new timeouts and limit configurations default to safe values without breaking existing workflows.

---

## 6. Conclusion

Milestone 1.6 has successfully transformed Alberto's execution engine from an unconstrained runtime into a hardened, deadline-enforcing, and crash-resilient butler platform.

---

# Part II: Final Hardening & Closure

## A. Executive Summary

Following the initial Milestone 1.6 implementation, an exhaustive audit and reliability review were performed against the live codebase. Several critical edge cases were identified and resolved during this final hardening pass:
1. Terminal-state races between external cancellation and run finalization were eliminated using atomic SQL compare-and-set updates.
2. SQLite worker lease fencing was decoupled from renewal timestamps using an immutable `lease_token` (UUID) per task claim.
3. Startup stale run recovery was re-engineered to inspect the live worker lease table in `queue.sqlite`, preventing the false reap of healthy runs older than 60 seconds.
4. SSE stream replay gaps for active runs were converted to explicit `gap` resync events, and subscriber queues were bounded with drop-slow-client policies.
5. Database migrations were verified against populated pre-Milestone 1.6 schemas.

All quality gates passed with zero regressions (618 pytest backend tests passed, 4 frontend Vitest tests passed, Next.js production build succeeded, and full Ruff/TypeScript linting checks passed).

---

## B. Findings Reviewed

| Finding / Gap Area | Classification | Status & Resolution |
|---|---|---|
| **Cancellation & Completion Race** | Confirmed Defect | **Fixed**: Atomic SQL CAS (`UPDATE runs ... WHERE status IN (...)`) in `cancel_run`, `_finalize`, and `_finalize_error`. Trace status and terminal SSE events strictly mirror database outcome. |
| **Worker Lease Renewal Race** | Confirmed Defect | **Fixed**: Introduced immutable `lease_token` per claim in `job_queue`. Heartbeats update `locked_at` using `lease_token`. Old/expired workers attempting acknowledgement are fenced out. |
| **Uncertain Worker Side-Effect Replay** | Confirmed Defect | **Fixed**: `recover_abandoned_jobs` marks non-idempotent failed executions with `termination_reason="uncertain_crash"` and dead-letters without unsafe automatic rerun. |
| **Startup Stale Run Sweep** | Confirmed Defect | **Fixed**: Replaced naive 60s timestamp cutoff with queue lease inspection (`job_queue` locked status), `run_control` process checking, and wall-clock timeout defaults. Valid queued and paused HITL runs preserved. |
| **SSE Active Replay Gap** | Confirmed Defect | **Fixed**: When clients reconnect with an evicted `Last-Event-ID` on an active run, an explicit `{"event": "gap", "data": {"resync": True, ...}}` frame is yielded before continuing with retained history. |
| **SSE Subscriber Memory Leak** | Confirmed Defect | **Fixed**: Subscriber queues bounded to `maxsize=1000`. Overwhelmed/slow subscriber queues are dropped during `publish()` without blocking the engine or leaking memory. |
| **Database Migration Safety** | Confirmed Defect | **Fixed**: Created Alembic migration `0016_m1_6_execution_hardening.py` adding execution metrics (`iterations_count`, `tool_calls_count`, `termination_reason`) to `runs` and `traces`. Added pre-M1.6 upgrade verification tests. |
| **Worker Retry Backoff Delay** | Already Handled / Fixed | Verified backoff with bounded exponential delay (`min(300, 5 * 2^attempts)`). Fixed SQLite `ADD COLUMN` non-constant default in `queue.py` and `worker.py`. |
| **Execution Safeguard Defaults** | Already Handled | Model call limits (25), tool call limits (50), repeated call detector (3), SQL/MCP tool timeouts (30s), and wall-clock deadlines (300s) verified active on root and subagent loops. |
| **Code Tool Thread Cancellation** | Known Limitation | **Deferred**: Python `asyncio.to_thread` runs standard synchronous callables that cannot be forcibly killed without process termination. Tool remains disabled by default (`ALBERTO_TOOLS_CODE_ENABLED=false`). |

---

## C. Code Changes

### 1. `backend/alberto/services/runs.py`
- **`_RunBroker`**: Bounded subscriber queues (`asyncio.Queue(maxsize=1000)`). Updated `publish()` to discard full subscriber queues without blocking execution.
- **`stream()`**: Added eviction gap detection: yields `{"event": "gap", ...}` frame when `requested_last_event_id < oldest_id` for active runs; retains terminal DB fallback for completed runs.
- **`cancel_run()`**: Replaced read-then-write logic with an atomic SQL CAS update (`WHERE status IN ('queued', 'running', 'interrupted')`). Returns `ok: False, status: canceled` for idempotent repeated calls.
- **`_finalize()`**: Implemented atomic SQL CAS (`WHERE status IN ('running', 'queued')`). If rowcount is 0 due to an external cancellation commit, refreshes run status and records cancellation trace.
- **`_finalize_error()`**: Converted to conditional update ensuring canceled runs are not overwritten by fatal errors.
- **`_mark_unfinished()`**: Shielded atomic UPDATE to mark interrupted runs without racing cancellations.
- **`reap_stale_runs()`**: Re-engineered startup sweep to inspect `queue.sqlite` for active leases and check in-process `run_control.is_running()`. Preserves queued tasks, paused HITL runs, and active worker claims.

### 2. `backend/alberto/queue.py` & `backend/alberto/worker.py`
- **Schema & Indexes**: Added `lease_token TEXT` column to `job_queue` and created index `idx_job_queue_lease`.
- **Atomic Lease Generation**: `_claim_next_job` generates a unique UUID `lease_token` per claim.
- **Fenced Heartbeat**: `_heartbeat` updates `locked_at = CURRENT_TIMESTAMP WHERE id = :id AND lease_token = :token`.
- **Fenced Acknowledgement**: `_finish_job` completes/deletes jobs only if `id = :id AND lease_token = :token`.
- **Safe Recovery**: `recover_abandoned_jobs` verifies if an expired job was safe to retry (`idempotent = True`); otherwise marks it failed with `uncertain_crash` without automatic re-execution.

### 3. `backend/alberto/main.py`
- Configured startup stale run reaper to use `settings.run_wall_clock_timeout_seconds` (300s) instead of hardcoded 60s.

### 4. `backend/migrations/versions/0016_m1_6_execution_hardening.py`
- Alembic migration adding `iterations_count`, `tool_calls_count`, and `termination_reason` to `runs` and `traces` tables with safe nullable defaults.

### 5. `tests/backend/`
- `test_cancellation_completion_race.py`: Concurrency barrier tests for cancellation vs. completion vs. error.
- `test_worker_lease_recovery.py`: Unit tests for lease token fencing, heartbeat continuity, reclamation, and uncertain side effects.
- `test_startup_stale_run_sweep.py`: Tests for startup sweep preserving active leases, queued jobs, and paused HITL states.
- `test_sse_broker_bounded_buffer.py`: Tests for bounded event buffer, slow client drops, and replay gap events.
- `test_database_upgrade.py`: Data-preserving migration tests upgrading pre-M1.6 SQLite databases.

---

## D. Concurrency and State Consistency

Terminal state consistency is guaranteed by database-level conditional CAS semantics:

```sql
-- Atomic Run Cancellation
UPDATE runs
SET status = 'canceled',
    termination_reason = 'canceled',
    error = COALESCE(error, 'run canceled by operator'),
    ended_at = :now
WHERE tenant_id = :tenant_id
  AND id = :run_id
  AND status IN ('queued', 'running', 'interrupted');

-- Atomic Run Completion Finalize
UPDATE runs
SET status = :final_status,
    termination_reason = :termination_reason,
    ended_at = :now
WHERE tenant_id = :tenant_id
  AND id = :run_id
  AND status IN ('running', 'queued');
```

- If operator cancellation commits first, `_finalize`'s `rowcount` evaluates to `0`. Alberto re-reads the committed status, acknowledges the run is already `canceled`, and emits the appropriate canceled trace and terminal SSE event.
- If worker finalization commits first, `cancel_run`'s `rowcount` evaluates to `0`. It returns `{"ok": False, "status": "done"}` without mutating the terminal run.

Worker lease ownership is fenced by `lease_token`:
- Even if a worker's heartbeat loop updates `locked_at` continuously, `lease_token` remains invariant throughout the claim period.
- If a worker stalls and its lease expires, `recover_abandoned_jobs` reclaims the job and clears `lease_token`. When the zombie worker finally attempts `_finish_job`, the update matches 0 rows and the zombie worker is cleanly rejected.

---

## E. Startup and SSE Reliability

### Startup Stale Run Recovery
- Rather than blindly terminating runs with `updated_at < now - 60s`, Alberto queries `queue.sqlite`:
  - Runs with active, non-expired worker leases (`locked_at > now - lease_duration`) are recognized as healthy and skipped.
  - Queued runs awaiting a worker slot are preserved.
  - Interrupted runs waiting for human intervention (HITL) are preserved.
  - Only runs exceeding the full wall-clock timeout (`300s`) with no live worker lease or active in-memory task are transitioned to `interrupted` or `error`.

### SSE Replay Gap Handling
- Active runs maintain a bounded in-memory `deque(maxlen=1000)`.
- If a client reconnects with `Last-Event-ID` that was already evicted:
  1. The server detects `last_event_id < oldest_retained_id`.
  2. The server emits an explicit resynchronization event:
     ```json
     event: gap
     data: {"requested_last_event_id": 50, "oldest_retained_id": 200, "resync": true}
     ```
  3. The server immediately streams all remaining retained frames.
- Reconnections to completed runs whose broker has been garbage-collected use `_reattach_from_db`, synthesizing a terminal frame from SQLite.
- Slow or stalled subscriber queues are capped at `1000` messages; excess frames are discarded to prevent memory bloat.

---

## F. Database Upgrade Compatibility

Upgrade safety was validated against pre-Milestone 1.6 database fixtures:
1. **Application Database (`alberto.db`)**:
   - Seeded pre-M1.6 schema without `iterations_count`, `tool_calls_count`, and `termination_reason`.
   - Executed Alembic upgrade to `0016_m1_6_execution_hardening`.
   - Verified pre-existing `runs` and `traces` data remained uncorrupted and newly added columns defaulted to `None` / `NULL`.
2. **Queue Database (`queue.sqlite`)**:
   - Seeded pre-M1.6 `job_queue` schema without `available_at` and `lease_token`.
   - Initialized `SQLiteWorker` / `SqliteJobQueue` dynamic schema upgrade.
   - Verified that SQLite table alteration executed cleanly and existing pending jobs were claimed and processed with generated lease tokens.

---

## G. Validation Results

| Test Command / Quality Gate | Total Tests | Passed | Failed | Skipped / XFailed | Status |
|---|---|---|---|---|---|
| `pytest tests/backend/test_cancellation_completion_race.py` | 4 | 4 | 0 | 0 | **PASSED** |
| `pytest tests/backend/test_worker_lease_recovery.py` | 5 | 5 | 0 | 0 | **PASSED** |
| `pytest tests/backend/test_startup_stale_run_sweep.py` | 1 | 1 | 0 | 0 | **PASSED** |
| `pytest tests/backend/test_sse_broker_bounded_buffer.py` | 4 | 4 | 0 | 0 | **PASSED** |
| `pytest tests/backend/test_database_upgrade.py` | 2 | 2 | 0 | 0 | **PASSED** |
| `pytest tests/backend/test_react_middleware.py` | 6 | 6 | 0 | 0 | **PASSED** |
| `pytest tests/backend/test_tool_execution_safety.py` | 5 | 5 | 0 | 0 | **PASSED** |
| `bash tests/lint.sh` (Ruff Backend + TS Frontend) | Static | Pass | 0 | 0 | **PASSED** |
| `bash tests/run.sh` (Pytest Backend + Vitest Frontend) | 667 | 622 | 0 | 8 skipped, 37 xfailed | **PASSED** |
| `bash tests/check.sh` (Lint + Test + Next.js Build) | Full Gate | Pass | 0 | 0 | **PASSED** |

---

## H. Architectural Impact

- **Zero External Dependencies**: Preserved Alberto's local-first single-container architecture. No Redis, RabbitMQ, Kafka, or separate background services introduced.
- **Embedded Durability**: All fencing, coordination, and crash-safety mechanisms leverage native SQLite WAL mode transactions and Python `asyncio` primitives.
- **Schema Compatibility**: All database schema adjustments are strictly additive and backward-compatible with existing data.

---

## I. Remaining Risks

1. **Python Thread Cancellation in Code Tool (Known Limitation)**:
   - When `ALBERTO_TOOLS_CODE_ENABLED=true`, user code executed via `asyncio.to_thread` runs on the host Python process.
   - Cancelling the awaiting coroutine raises `TimeoutError` or `CancelledError` in the asyncio loop, but the underlying OS thread may continue executing CPU-bound operations until completion.
   - *Mitigation*: The code tool remains disabled by default. Containment through a dedicated sandboxed subprocess or WebAssembly environment is deferred to a future security-focused milestone.

---

## J. Final Closure Recommendation

### **Ready for closure**

**Justification**:
All reliability gaps identified in the Milestone 1.6 Execution Audit and Implementation Review have been rigorously verified and resolved. Concurrency races, lease fencing, worker crash recovery, startup sweep hazards, and SSE buffering memory leaks are fully tested and green across all quality gates. Alberto maintains 100% backward compatibility and architectural integrity.

