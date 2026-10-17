# Alberto — Milestone 1.6 Pre-Implementation Technical Audit
**Runtime Architecture, Execution Engine, ReAct Loops, Tool Execution, Async Workers, and Streaming**

---

## 1. Executive Summary

Milestone 1.5 successfully hardened Alberto's container delivery, port architecture, release engineering, and CI/CD quality gates. Milestone 1.6 focuses on runtime execution reliability, safety boundaries, and resilience across Alberto's execution stack.

This audit is an exhaustive, **read-only architectural and code-level investigation** of Alberto's execution engine: FastAPI lifecycle, LangGraph/ReAct runtime, tool and MCP dispatch, workflow execution, native async workers, SQLite queues, SSE streaming, cancellation semantics, observability, and configuration safety limits.

### Executive Summary Table

| Component | Status | Priority | Recommended Action |
|---|---|---|---|
| **ReAct Loop Guardrails** | Partial / Risk | **P0** | Enforce default per-agent iteration caps and tool call limits (`ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`); inject repeated identical tool-call detection. |
| **Execution Timeout** | Partial / Risk | **P0** | Change `run_wall_clock_timeout_seconds` default from `0` (unlimited) to a safe bounded default (e.g., 300s) and enforce hard deadlines. |
| **SQL & MCP Tool Timeouts** | Missing / Risk | **P0** | Enforce per-tool execution timeouts on SQL queries and remote MCP `ainvoke` calls to prevent hanging worker loops. |
| **Worker Queue Lease & Recovery** | Missing / Risk | **P0** | Implement lease/visibility timeouts and startup stale-job recovery in `job_queue` to recover tasks abandoned by crashed workers. |
| **Cancellation & Completion Race** | Risk | **P1** | Add atomic check in `_finalize()` preventing terminal status overwrite if run is already marked `canceled` in database. |
| **SSE Broker Memory Boundedness** | Risk | **P1** | Replace unbounded `self.events` list in `_RunBroker` with a bounded ring buffer to prevent OOM on long/high-frequency runs. |
| **Stale Run Startup Sweeper** | Partial | **P1** | Add immediate startup sweep for stranded `running`/`queued` runs on application boot rather than waiting up to 3600s for reaper tick. |
| **Worker Retry Backoff** | Missing | **P1** | Add exponential backoff with jitter between queue retries in `SQLiteWorker` to prevent immediate failure thrashing. |
| **Execution Observability Gaps** | Partial | **P2** | Persist structured fields on `Run`/`Trace` for ReAct iteration count, tool invocation count, and structured termination reasons. |
| **Code Tool Runaway Thread Isolation** | Risk | **P2** | Document/gate CPU exhaustion ceiling or plan subprocess sandbox boundary for Python code tools. |

---

## 2. Current Execution Architecture

Alberto operates a single-container, local-first AI butler architecture with embedded SQLite persistence, ChromaDB vector storage, and native `asyncio` execution loops.

```
                           +----------------------------------------+
                           |           Client (Next.js / UI)        |
                           +----------------------------------------+
                                        |                   ^
                         HTTP POST /run |                   | SSE Stream
                                        v                   |
                           +----------------------------------------+
                           |             FastAPI Backend            |
                           |  - Auth & Tenant Admission (quota)    |
                           |  - Thread Lock (per-thread serialize)  |
                           |  - Tenant Concurrency Gate (limit)     |
                           +----------------------------------------+
                                        |                   |
                       (Trigger / Sync) |                   | (Background offload)
                                        v                   v
                    +---------------------------+   +---------------------------+
                    |    RunService._drive()    |   |     SqliteJobQueue        |
                    | (Detached Background Task)|   |  (queue.sqlite table)     |
                    +---------------------------+   +---------------------------+
                                  |                               |
                 +----------------+----------------+              | Poll / Claim
                 |                                 |              v
                 v                                 v   +---------------------------+
   +---------------------------+     +---------------+ |    SQLiteWorker Loop      |
   |   LangGraph Compiled      |     |  _RunBroker   | | (Standalone / In-process) |
   |   Workflow StateGraph     |     | Event PubSub  | +---------------------------+
   +---------------------------+     +---------------+              |
                 |                           |                      |
      +----------+----------+                +----------->----------+
      |                     |
      v                     v
+------------+       +-------------+
| ReAct Agent|       | Flow Nodes  |
| (LangChain)|       | (Routers,   |
+------------+       |  Fanout)    |
      |              +-------------+
      v
+------------+------------+-------------+
| REST Tools | SQL Tools  | MCP Clients |
| (httpx)    | (SQLAlchemy| (anyio transport)
+------------+------------+-------------+
      |
      v
+---------------------------------------+
| Persistence:                          |
| - alberto.db (SQLite: Runs, Traces)   |
| - checkpoint.sqlite (LangGraph checkp)|
| - queue.sqlite (Job queue)            |
+---------------------------------------+
```

### 2.1 Core Lifecycle and File Mapping
1. **Application Lifecycle**: `backend/alberto/main.py:148-216` (`lifespan`)
   - Initializes database tables (`init_db`), configures `AsyncSqliteSaver` checkpointer, initializes directory trees, and starts background leader loops (`_scheduler_loop`, `_reaper_loop`, `_retention_loop`).
   - Shutdown drains background tasks (`tasks.drain()`), terminates MCP connections (`mcp.close_all()`), drains queue workers (`queue.close_pool()`), and closes shared HTTP clients.
2. **Workflow Compilation**: `backend/alberto/engine/compiler.py:81-189` (`compile_workflow`)
   - Compiles executable workflow JSON into a LangGraph `CompiledStateGraph` attached to the application checkpointer.
3. **Agent & ReAct Node Factory**: `backend/alberto/nodes/agent_node.py:317-365` (`agent_factory`)
   - Uses LangChain's `create_agent` and `create_deep_agent` with dynamic middleware and tool binding.
4. **Tool Materialization & Execution**:
   - REST Tools: `backend/alberto/tools/rest.py:489-760` (`execute_rest`)
   - SQL Tools: `backend/alberto/tools/sql.py:95-146` (`execute_sql`)
   - Code Tools: `backend/alberto/tools/code.py:99-116` (`execute_code`)
   - MCP Tools: `backend/alberto/tools/mcp.py:414-466` (`_client_and_tools`), `backend/alberto/tools/mcp.py:561-605` (`load_mcp_tool`)
5. **Run Orchestration & SSE Broker**: `backend/alberto/services/runs.py:398-1356` (`RunService`, `_RunStreams`, `_RunBroker`, `_RunControl`)
   - Decouples client HTTP connection from execution driver; runs in detached background task and publishes events to subscriber queues.
6. **Task Queue & Native Worker**: `backend/alberto/queue.py:51-229` (`AsyncInMemoryQueue`, `SqliteJobQueue`), `backend/alberto/worker.py:32-214` (`SQLiteWorker`).

---

## 3. LangGraph and ReAct Execution Audit

### 3.1 Maximum ReAct Iterations
- **Status:** **Partial / Risk (P0)**
- **Code Reference:** `backend/alberto/nodes/agent_node.py:317-365`, `backend/alberto/engine/middleware_compiler.py:532-537`
- **Audit Details:** LangChain's `create_agent` accepts a list of middlewares. While `ModelCallLimitMiddleware` and `ToolCallLimitMiddleware` exist in `middleware_compiler.py`, they are **not injected by default** into the agent stack. Unless an author explicitly configures `model_call_limit` in the node's JSON middleware definition, an agent node has no inner iteration limit. It is bounded only by the top-level LangGraph recursion limit.

### 3.2 LangGraph Recursion Limits
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/services/runs.py:380-396` (`_recursion_limit`), `backend/alberto/config.py:387`
- **Audit Details:** Recursion limit is dynamically computed per workflow: `max(int(settings.graph_recursion_limit or 0), (len(nodes) + 1) * 2 + loop_iters * 3 + 10)`. The default floor in `config.py` is `100`. When hit, LangGraph terminates the run with `GraphRecursionError`, which `runs.py` captures and finalizes as an error.

### 3.3 Maximum Tool Calls per Execution
- **Status:** **Missing (P0)**
- **Code Reference:** `backend/alberto/nodes/agent_node.py:258-303`, `backend/alberto/engine/middleware_compiler.py:535-537`
- **Audit Details:** There is no total tool call quota or limit per agent invocation. An agent can call tools indefinitely up to the 100-superstep recursion ceiling.

### 3.4 Repeated Identical Tool Calls Detection
- **Status:** **Missing (P0)**
- **Code Reference:** `backend/alberto/nodes/agent_node.py:22-38`
- **Audit Details:** `_dedup_tools_by_name()` only dedupes tool *definitions* attached to the model schema (preventing OpenAI duplicate function errors). There is **no runtime detection of identical consecutive or cyclical tool calls** with identical arguments. If a tool returns an unhelpful error or empty payload, the LLM can hallucinate or loop on identical inputs until recursion exhaustion.

### 3.5 Agent Loop Progress & Deadlock
- **Status:** **Risk (P1)**
- **Code Reference:** `backend/alberto/services/runs.py:685-743`
- **Audit Details:** If an agent encounters repeated tool errors, the loop does not detect zero-progress states. It continues consuming tokens and driving LLM steps until reaching recursion limit or timeout.

### 3.6 Overall Execution Deadline
- **Status:** **Partial / Risk (P0)**
- **Code Reference:** `backend/alberto/services/runs.py:46`, `backend/alberto/services/runs.py:678-696`, `backend/alberto/config.py:368`
- **Audit Details:** In `backend/alberto/config.py:368`:
  ```python
  run_wall_clock_timeout_seconds: int = 0
  ```
  The default is **0 (unlimited)**! Therefore, out-of-the-box installations have **no execution deadline**. Furthermore, the check inside `_drive()` is cooperative between stream frames:
  ```python
  if wall_clock and (time.monotonic() - started_monotonic) > wall_clock:
      timed_out = True
      break
  ```
  If a single tool or model call blocks in an external await, the cooperative timeout cannot interrupt it until the frame yields.

### 3.7 Error Propagation
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/services/runs.py:804-821`
- **Audit Details:** Runtime errors in `graph.astream` are caught, logged, passed to `_finalize_error()`, recorded in `spans` and `traces`, and emitted to the client via `error` or fallback `done` frames.

### 3.8 State Persistence
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/main.py:60-79`, `backend/alberto/services/runs.py:750-775`
- **Audit Details:** LangGraph state is durably saved in `checkpoint.sqlite` via `AsyncSqliteSaver`. Thread history and node outputs are persisted.

### 3.9 Subagent Execution Limits
- **Status:** **Partial / Risk (P1)**
- **Code Reference:** `backend/alberto/nodes/agent_node.py:122-148`, `backend/alberto/nodes/agent_node.py:356-359`
- **Audit Details:** Subagents compiled into `SubAgentMiddleware` receive resolved models and tools, but do not inherit explicit timeout boundaries or step budgets separate from the parent.

### 3.10 Execution Isolation Across Concurrent Requests
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/util/locks.py:18-79`, `backend/alberto/services/runs.py:632-634`
- **Audit Details:** Thread collisions are prevented via `thread_locks.acquire_cm(thread.lg_thread_id)`. Tenant concurrency backpressure is enforced via `tenant_concurrency.slot(tenant_id, limit)`.

---

## 4. Agent Execution and Lifecycle Audit

### 4.1 Request-to-Response Execution Trace
1. **Creation**: `POST /v1/projects/{p}/workflows/{w}/runs` or `POST /v1/projects/{p}/run`.
   - Checks quota (`check_run_quota`) and project budget (`enforce_project_budget`).
   - Creates DB `Run` row with `status = "queued"`, `thread_id`, and `input`.
2. **Streaming Attach**: `GET /stream` or `POST /run` with `stream=True`.
   - Calls `RunService.stream()`, which calls `run_streams.ensure(...)`.
   - Launches `_execute()` in a detached `asyncio.create_task`.
   - `_drive()` acquires `thread_locks` and `tenant_concurrency`.
   - Updates `run.status = "running"`, `started_at = datetime.utcnow()`.
3. **Execution**: Compiles workflow graph with `build_compile_context()` and executes `graph.astream(...)`.
4. **Finalization**:
   - Success: `_finalize()` writes traces and spans, updates `run.status = "done"`, `run.output`, `total_tokens`, `total_cost_usd`, `ended_at`. Emits `done` SSE frame.
   - Failure: `_finalize_error()` writes partial spans, updates `run.status = "error"`, `run.error`. Emits `error` or error fallback frame.
   - Cancel: `_finalize(..., status="canceled")` updates `run.status = "canceled"`.
   - Cleanup: `run_control.end(run_id)`, frees locks and concurrency slots. Broker is finished (`broker.finish()`).

### 4.2 Terminal State Consistency & Race Conditions
- **Status:** **Risk (P1)**
- **Code Reference:** `backend/alberto/services/runs.py:750-775`, `backend/alberto/services/runs.py:1015-1044`
- **Audit Details:** When `cancel_run()` is invoked, it updates DB `run.status = "canceled"`, `run.ended_at = now`, and signals `run_control`. In `_drive()`, if execution completes right before the cancellation signal is observed, `_drive()` invokes `_finalize(..., status="done")` and commits `run.status = "done"` to the database. The `_finalize()` method does not check if the database record was already flipped to `canceled`. As a result, a completed run can overwrite an operator cancellation in a close race.

### 4.3 Stale Executions After Process Restart
- **Status:** **Risk (P1)**
- **Code Reference:** `backend/alberto/services/runs.py:1183-1227`, `backend/alberto/main.py:81-97`
- **Audit Details:** If Alberto's container or process terminates abruptly while runs are in `running` or `queued` status:
  - On restart, Alberto does **not** perform an immediate startup sweep of in-flight runs.
  - The background reaper (`_reaper_loop`) only ticks once every 300 seconds (5 minutes).
  - Furthermore, `running_max_age_s` defaults to **3600 seconds (1 hour)**!
  - Therefore, runs stranded by a process restart remain in `status = "running"` for up to 60 minutes before being reaped.

---

## 5. Tool and MCP Execution Audit

### 5.1 Tool Execution Timeouts
- **Status:** **Partial / Risk (P0)**
- **Code Reference:**
  - REST: `backend/alberto/tools/rest.py:645` — Bounded by `timeout = cfg.get("timeout_seconds", settings.tool_request_timeout_seconds)` (default: 30s).
  - Code: `backend/alberto/tools/code.py:105` — Bounded by `timeout = float(cfg.get("timeout_seconds", 5))`.
  - SQL: `backend/alberto/tools/sql.py:95-146` — **NO TIMEOUT!** Uses `session.stream(text(query))` without statement or connection timeout.
  - MCP: `backend/alberto/tools/mcp.py:546-558` — **NO TIMEOUT!** Uses `await underlying.ainvoke(kwargs)` directly on the remote MCP transport.
- **Problem:** If an external MCP server hangs or a database locks on a query, the tool call hangs indefinitely, freezing the run and tying up the tenant concurrency slot.

### 5.2 Tool Cancellation
- **Status:** **Partial / Risk (P1)**
- **Code Reference:** `backend/alberto/tools/code.py:107-114`, `backend/alberto/services/runs.py:124-129`
- **Audit Details:** When an execution is cancelled via `request_cancel(hard=True)`, the asyncio task driving the run is cancelled (`t.cancel()`). For async I/O tools (REST and SQL async queries), this cleanly raises `CancelledError`. However:
  - For Code tools (`execute_code`), execution is delegated to a worker thread via `asyncio.to_thread(run_code, source, kwargs)`. While `asyncio.wait_for` raises `TimeoutError` or `CancelledError`, the underlying Python thread **cannot be killed** in CPython. A runaway CPU loop (e.g., `while True: pass`) continues executing in the thread pool, consuming host CPU.

### 5.3 Tool Retries and Side Effects
- **Status:** **Implemented (REST) / Missing (Workflow level)**
- **Code Reference:** `backend/alberto/tools/rest.py:94-98`, `backend/alberto/tools/rest.py:646`
- **Audit Details:** REST tools enforce retry safety by distinguishing idempotent HTTP methods (`GET`, `PUT`, `DELETE`) from non-idempotent ones (`POST`, `PATCH`), refusing to retry non-idempotent requests unless explicitly configured with `retry_non_idempotent: true`. However, when a background worker retries an entire failed run (see Section 6), all tools in the graph are executed again, potentially duplicating non-idempotent side effects.

### 5.4 MCP Client Lifecycle and Connection Pooling
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/tools/mcp.py:44-92`, `backend/alberto/tools/mcp.py:424-465`
- **Audit Details:** MCP clients are pooled in `_CLIENT_CACHE` with a 300s TTL and a hard cap of 64 entries. Cache eviction moves retired clients to `_RETIRED` with a 30s grace window before closing. `close_all()` is cleanly called on FastAPI shutdown.

---

## 6. Workflow Execution Audit

### 6.1 Creation and Compilation
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/engine/compiler.py:81-189`
- **Audit Details:** Workflow definitions are compiled to LangGraph `StateGraph`. Topologically verified by JSON schema validation prior to compilation.

### 6.2 Workflow Execution Limits
- **Status:** **Partial / Risk (P0)**
- **Code Reference:** `backend/alberto/services/runs.py:380-396`, `backend/alberto/config.py:368`
- **Audit Details:** Overall workflow execution timeout is governed solely by `run_wall_clock_timeout_seconds`, which is disabled (0) by default. Individual workflow nodes (such as LLM nodes, data nodes, or custom code nodes) have no individual execution timeouts.

### 6.3 Partial Failure Isolation in Fan-Out
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/nodes/flow.py:227-280` (`resilient_fanout_child`)
- **Audit Details:** In `parallel_fanout`, child nodes are wrapped in `resilient_fanout_child` if `error_policy == "continue"` or `on_item_error == "skip"`. Individual item timeouts are supported via `item_timeout_seconds`. Graph control flow signals (interrupts, `GraphBubbleUp`) are correctly re-raised.

### 6.4 Subworkflows and Cycle Detection
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/nodes/flow.py:99-167` (`subworkflow_factory`)
- **Audit Details:** Subworkflows are recursively compiled without checkpointers (parent checkpointer owns durability). Recursion cycles are prevented via `compiling` set tracking on `CompileContext`.

---

## 7. Native Async Worker and SQLite Queue Audit

### 7.1 Queue Architecture & Backends
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/queue.py:51-229`, `backend/alberto/worker.py:32-214`
- **Audit Details:** Alberto implements three queue modes:
  1. `AsyncInMemoryQueue`: In-process `asyncio.Queue` (default) with 4 workers.
  2. `SqliteJobQueue`: Backed by `job_queue` table in `queue.sqlite`.
  3. `InlineQueue`: Synchronous execution fallback.

### 7.2 Worker Job Claiming & Atomicity
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/worker.py:109-145` (`_claim_next_job`)
- **Audit Details:** Uses atomic single-statement update with conditional check:
  ```sql
  UPDATE job_queue
  SET status = 'running',
      locked_at = CURRENT_TIMESTAMP,
      locked_by = ?,
      attempts = attempts + 1,
      updated_at = CURRENT_TIMESTAMP
  WHERE id = ? AND status = 'queued';
  ```
  If `cursor.rowcount == 1`, the job is claimed exclusively. WAL mode and `PRAGMA busy_timeout=5000` protect SQLite against concurrency locks.

### 7.3 CRITICAL: Missing Lease Timeout & Stale Task Recovery
- **Status:** **Missing / Risk (P0)**
- **Code Reference:** `backend/alberto/worker.py:114-122`
- **Audit Details:** The query to find queued jobs is strictly:
  ```sql
  SELECT id, run_id, tenant_id, project_id, attempts, max_attempts
  FROM job_queue
  WHERE status = 'queued'
  ORDER BY id ASC
  LIMIT 1;
  ```
  **There is no visibility timeout or lease handling.** If a worker claims a job (`status = 'running'`) and the worker process crashes, is killed, or restarts:
  1. The job remains in `status = 'running'` indefinitely in `queue.sqlite`.
  2. Neither this worker nor any future worker will ever claim it again because the query filters strictly on `status = 'queued'`.
  3. The task is permanently orphaned.

### 7.4 Dead-Letter Queue (DLQ) Behavior
- **Status:** **Partial / Risk (P1)**
- **Code Reference:** `backend/alberto/worker.py:177-191`
- **Audit Details:** When execution raises an exception:
  - If `attempts >= max_attempts` (3), the worker sets `job_queue.status = 'failed'` and updates `Run._mark_unfinished(..., status='error')`.
  - If `attempts < max_attempts`, it sets `job_queue.status = 'queued'`.
  - **Problem:** There is **no backoff delay** before retry. The job is immediately re-queued and claimed on the very next poll tick (~1s), which thrashes failing external resources without backoff.

---

## 8. SSE and Streaming Audit

### 8.1 Stream Broker & Reconnect Decoupling
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/services/runs.py:135-245`, `backend/alberto/services/runs.py:521-536`
- **Audit Details:** Alberto cleanly decouples run execution from client HTTP connections:
  - The driving execution task (`_drive`) runs as a detached background task.
  - Client connections subscribe to `_RunBroker` via `async for seq, frame in broker.subscribe(last_event_id)`.
  - If the client disconnects, only the subscription queue is dropped. Execution continues to completion.
  - Reconnection via `Last-Event-ID` replays missed frames from `broker.events`.

### 8.2 Unbounded Broker Event Buffer
- **Status:** **Risk (P1)**
- **Code Reference:** `backend/alberto/services/runs.py:145-163`
- **Audit Details:** In `_RunBroker`:
  ```python
  self.events: list[tuple[int, dict]] = []
  ```
  Every frame published is appended to `self.events` without an upper bound (`maxlen`). For long-running workflows, deep reasoning agents, or runs emitting hundreds of tokens and activity frames, all frames remain in memory.
  Furthermore, `_RunStreams` retains the entire `_RunBroker` in memory for `RUN_BROKER_TTL_SECONDS = 300` seconds after completion. Under high load, this causes memory accumulation.

### 8.3 Terminal Reattach from Database
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/services/runs.py:537-572` (`_reattach_from_db`)
- **Audit Details:** If a client attempts to reattach after the broker has been evicted from memory, `_reattach_from_db()` reconstructs a terminal frame from `Run` and `Trace` database rows.

---

## 9. Execution Cancellation Audit

### 9.1 Cancellation Mechanisms Across Surfaces
- **Status:** **Implemented (Multi-layer)**
- **Code Reference:** `backend/alberto/services/runs.py:49-132` (`_RunControl`), `backend/alberto/services/runs.py:1015-1045` (`cancel_run`)
- **Audit Details:** Cancellation operates across three coordinated layers:
  1. **Database Status**: `cancel_run()` sets `Run.status = "canceled"` and closes open HITL handoffs.
  2. **In-Process Cooperative Event**: `run_control.request_cancel()` signals `cancel_ev = asyncio.Event()`, polled between frames in `_drive()`.
  3. **Hard Task Interruption**: `run_control.request_cancel(hard=True)` cancels the driving `asyncio.Task`, unblocking runs stuck in long provider awaits.
  4. **Cross-Worker DB Watcher**: Each active run spawns `_watch_database()` polling the database every 0.25s. If another API process commits `status = "canceled"`, the local driving task is cancelled.

### 9.2 Cancellation Gaps
- **Status:** **Partial / Risk (P1)**
- **Audit Details:**
  1. As noted in Section 4.2, `_finalize()` does not check if the run was already marked `canceled` before committing `done`.
  2. For Code tools, Python worker threads cannot be interrupted.
  3. `alberto.util.tasks.drain()` does not cancel background tasks on shutdown; it gathers them for up to 10 seconds.

---

## 10. Resource Cleanup and Application Lifecycle

### 10.1 Resource Cleanup Assessment

| Resource | Lifecycle Management | Audit Finding |
|---|---|---|
| **Async Tasks** | `alberto.util.tasks.spawn()` / `drain()` | Tasks tracked in `_tasks` set (capped at 256). Drained on shutdown with 10s timeout. |
| **HTTP Clients** | `alberto.util.http.aclose_shared_client()` | Global shared client closed on application shutdown in `main.py:214`. |
| **MCP Sessions** | `alberto.tools.mcp.close_all()` | Pooled clients evicted after 300s TTL + 30s grace; force-closed on shutdown in `main.py:205`. |
| **Database Connections** | `SessionLocal()` / `AsyncSqliteSaver` | Database sessions scoped cleanly via `async with SessionLocal()`. Checkpointer stack closed in `main.py:215`. |
| **SQL Engine Cache** | `_ENGINE_CACHE` in `tools/sql.py` | Cached up to 64 engines with pool disposal on eviction. No global disposal on shutdown. |
| **Queue Workers** | `queue.close_pool()` | In-memory workers cancelled and drained on shutdown in `main.py:209`. |
| **Background Loops** | `main.py:194-198` | Reaper, scheduler, and retention loops explicitly cancelled and awaited on shutdown. |

---

## 11. Execution Observability

### 11.1 Observability Capabilities
- **Status:** **Implemented**
- **Code Reference:** `backend/alberto/tracing/tracer.py:85-115` (`SpanRecord`), `backend/alberto/services/runs.py:1046-1107` (`_write_trace`)
- **Recorded Fields:**
  - `Trace`: `run_id`, `tenant_id`, `project_id`, `workflow_id`, `thread_id`, `status`, `started_at`, `ended_at`, `latency_ms`, `total_tokens`, `total_cost_usd`, `source`, `actor`, `user_message`, `ai_response`.
  - `Span`: `trace_id`, `parent_span_id`, `name`, `kind` (`llm`, `tool`, `chain`, `embedding`), `latency_ms`, `input`, `output`, `model`, `input_tokens`, `output_tokens`, `cost_usd`, `error`, `attributes`.
  - Tool I/O: Captured in detail via `alberto.tracing.tool_io` (method, URL, headers, query, body, response, error).
  - OpenTelemetry: Full export supported when `settings.otel_enabled = True`.

### 11.2 Observability Gaps
- **Status:** **Missing (P2)**
- **Audit Details:**
  1. Total ReAct iteration count is not recorded as a first-class metric on `Run` or `Trace` (must be computed by scanning LLM spans).
  2. Total tool call count is not recorded on `Run`.
  3. Structured termination reason (e.g., `completed`, `wall_clock_timeout`, `recursion_limit`, `operator_canceled`, `hitl_timeout`) is currently formatted as unstructured text in `error`.

---

## 12. Configuration and Safety Limits

### 12.1 Configuration Inventory & Audit

| Setting Name | Default Value | File Location | Scope | Configurable | Safety & Bounds Assessment |
|---|---|---|---|---|---|
| `run_wall_clock_timeout_seconds` | `0` (unlimited) | `config.py:368` | Run | Yes (`FORGE_RUN_WALL_CLOCK_TIMEOUT_SECONDS`) | **CRITICAL RISK:** Default 0 allows runs to execute indefinitely if loops stall. Must be bounded. |
| `graph_recursion_limit` | `100` | `config.py:387` | Workflow | Yes (`FORGE_GRAPH_RECURSION_LIMIT`) | Bounded floor. Automatically scales with loop nodes. |
| `tool_request_timeout_seconds` | `30` | `config.py:335` | REST Tool | Yes (`FORGE_TOOL_REQUEST_TIMEOUT_SECONDS`) | Safe bounded default for REST tools. |
| `max_concurrent_runs_per_tenant` | `20` | `config.py:478` | Tenant | Yes (`FORGE_MAX_CONCURRENT_RUNS_PER_TENANT`) | Safe backpressure limit on in-flight runs. |
| `hitl_approval_timeout_seconds` | `0` (unlimited) | `config.py:366` | HITL | Yes (`FORGE_HITL_APPROVAL_TIMEOUT_SECONDS`) | Default 0 waits indefinitely for human approval; reaper expires if configured > 0. |
| `run_rate_limit_per_minute` | `60` | `config.py:454` | Tenant | Yes (`FORGE_RUN_RATE_LIMIT_PER_MINUTE`) | Bounded token bucket. |
| `api_rate_limit_per_minute` | `240` | `config.py:455` | System / IP | Yes (`FORGE_API_RATE_LIMIT_PER_MINUTE`) | Bounded global rate limit. |
| `queue_poll_interval` | `1.0` | `config.py:211` | Worker | Yes (`FORGE_QUEUE_POLL_INTERVAL`) | Safe poll frequency. |
| `max_tool_response_chars` | `20000` | `config.py:332` | Tool | Yes (`FORGE_MAX_TOOL_RESPONSE_CHARS`) | Token bloat guard for large payloads. |
| `enable_code_tools` | `False` | `config.py:317` | Security | Yes (`FORGE_ENABLE_CODE_TOOLS`) | Safe default-deny. Requires explicit production bypass. |
| `enable_mcp_stdio` | `False` | `config.py:325` | Security | Yes (`FORGE_ENABLE_MCP_STDIO`) | Safe default-deny on command execution. |
| `RUN_BROKER_TTL_SECONDS` | `300` | `runs.py:142` | Memory | No (hardcoded constant) | Retains broker 5 minutes after completion for reconnects. |
| `MAX_TRIES` | `3` | `worker.py:29` | Worker | No (hardcoded constant) | Bounded retry attempts for background worker. |

---

## 13. Tests and Coverage Assessment

### 13.1 Empirical Test Execution Results
An empirical test run of the existing test suite was conducted in the local environment:
- `backend/.venv/Scripts/python -m pytest tests/backend/test_queue.py`: **5 passed in 2.44s**
- `backend/.venv/Scripts/python -m pytest tests/backend/test_sse_reconnect.py tests/backend/test_tool_reliability.py`: **8 passed in 2.44s**

### 13.2 Coverage Gap Analysis

| Capability | Existing Test Coverage | Gap / Defect Status |
|---|---|---|
| **Successful Agent Run** | `test_engine.py`, `test_e2e_regressions.py` | Covered. |
| **SSE Reconnect & Last-Event-ID** | `test_sse_reconnect.py` | Covered. |
| **REST Tool Cache, Rate Limit, Retry** | `test_tool_reliability.py` | Covered. |
| **Basic Queue Enqueue & Claim** | `test_queue.py` | Covered for happy path. |
| **Subworkflow Execution & Isolation** | `test_subworkflow.py` | Covered. |
| **Tracer Interrupt & HITL** | `test_tracer_interrupt.py` | Covered. |
| **Execution Wall-Clock Timeout** | None | **Missing Coverage:** No test asserts that `run_wall_clock_timeout_seconds` aborts a long run. |
| **Repeated Identical Tool Calls** | None | **Missing Coverage:** Feature missing; no test. |
| **Worker Crash & Abandoned Task Recovery** | None | **Missing Coverage:** Feature missing; no test. |
| **Worker Deadlock on Slow SQL/MCP Tool** | None | **Missing Coverage:** Feature missing; no test. |
| **Cancellation vs Completion Race** | None | **Missing Coverage:** No test exercises race between `cancel_run` and `_finalize`. |
| **Startup Recovery of Stranded Runs** | None | **Missing Coverage:** No test exercises container restart recovery. |
| **SSE Broker Buffer Boundedness** | None | **Missing Coverage:** No test verifies buffer eviction on large streams. |

---

## 14. Consolidated Risk Register

| Risk ID | Severity | Category | Risk Description | Concrete Failure Scenario |
|---|---|---|---|---|
| **RSK-01** | **P0** | Execution Safety | Infinite agent loops via repeated tool calls | Agent calls a failing or zero-progress tool with identical parameters continuously until hitting the 100 recursion superstep ceiling or blowing token budget. |
| **RSK-02** | **P0** | Execution Safety | Unbounded execution duration by default | `run_wall_clock_timeout_seconds` is `0` by default. A stalled model call or long workflow runs indefinitely. |
| **RSK-03** | **P0** | Tool Safety | Unbounded SQL query and MCP tool execution | SQL queries have no query timeout; MCP calls have no call timeout. A database lock or frozen remote MCP server blocks the worker thread forever. |
| **RSK-04** | **P0** | Queue Reliability | Permanent task orphaning on worker crash | `SQLiteWorker` sets `status = 'running'` but lacks lease expiration. If worker restarts or crashes during a task, the task remains `running` forever in `queue.sqlite`. |
| **RSK-05** | **P1** | State Consistency | Overwrite of operator cancellation | If an operator cancels a run while it is finishing, `_finalize()` does not check if `Run.status == 'canceled'` before committing `Run.status = 'done'`. |
| **RSK-06** | **P1** | Memory Leak | Unbounded SSE broker event buffer | `_RunBroker.events` appends every chunk without limit and retains it for 300s, leading to high memory consumption on high-throughput runs. |
| **RSK-07** | **P1** | Startup Recovery | Delayed recovery of crashed runs | Application restart leaves active runs in `running` for up to 3600 seconds before the reaper identifies them as stale. |
| **RSK-08** | **P1** | Queue Reliability | Immediate retry thrashing without backoff | `SQLiteWorker` requeues failed jobs immediately without exponential backoff or delay, hammering downstream failing services. |
| **RSK-09** | **P2** | Observability | Missing structured execution metrics | Run and Trace records lack structured fields for ReAct iteration count, tool count, and explicit termination taxonomy. |
| **RSK-10** | **P2** | Thread Safety | Code tool worker thread exhaustion | Runaway CPU code in `RestrictedPython` cannot be forcibly terminated on cancellation, tying up worker threads. |

---

## 15. Prioritised Milestone 1.6 Implementation Plan

All proposed remediation strictly respects Alberto's architectural constraints: single-container Docker deployment, SQLite persistence, native `asyncio` workers, and LangGraph runtime without Redis or Celery.

### Implementation Items

| Priority | Component | Current Behaviour | Problem | Proposed Fix | Files Affected | Validation Test |
|---|---|---|---|---|---|---|
| **P0** | **ReAct Runtime** | No loop repetition detection or default iteration limit in agent factory. | Agents can loop 100 times calling identical tools with identical arguments. | 1. Inject default `ModelCallLimitMiddleware(run_limit=25)` in `agent_node.py`.<br>2. Implement `_RepeatedToolCallMiddleware` that detects identical consecutive tool calls (same tool + same args > 3 times) and halts or forces final answer. | `backend/alberto/nodes/agent_node.py`<br>`backend/alberto/engine/middleware_compiler.py` | `test_react_repeated_tool_guard.py` |
| **P0** | **Execution Limits** | `run_wall_clock_timeout_seconds = 0` (unlimited). | Stalled executions run forever. | Set safe default in `config.py` (e.g., `run_wall_clock_timeout_seconds = 300`). Enforce hard timeout in `_drive()` and `run_to_completion()` via `asyncio.wait_for()`. | `backend/alberto/config.py`<br>`backend/alberto/services/runs.py` | `test_run_deadline_enforcement.py` |
| **P0** | **Tool Execution** | SQL tools and MCP tools have no timeout. | Database locks or hung MCP servers block worker indefinitely. | 1. Add `timeout_seconds` (default 30s) to `execute_sql` with `asyncio.wait_for`.<br>2. Add `timeout_seconds` to MCP tool wrapper with `asyncio.wait_for`. | `backend/alberto/tools/sql.py`<br>`backend/alberto/tools/mcp.py` | `test_sql_tool_timeout.py`<br>`test_mcp_tool_timeout.py` |
| **P0** | **SQLite Queue** | `job_queue` lacks lease expiration; crashed tasks are lost. | Crashed worker leaves jobs in `status='running'` forever. | 1. Add `lease_timeout` (e.g., 300s) to `_claim_next_job`: allow claiming jobs where `status='queued' OR (status='running' AND locked_at < datetime.now() - lease_timeout)`.<br>2. Add startup recovery in `worker.py` resetting abandoned jobs. | `backend/alberto/worker.py`<br>`backend/alberto/queue.py` | `test_worker_lease_recovery.py` |
| **P1** | **Run State Consistency** | `_finalize()` unconditionally overwrites DB status. | Race condition where completed execution overwrites operator cancellation. | In `_finalize()` and `_finalize_error()`, verify `run.status != 'canceled'` before updating status to `'done'` or `'error'`. If canceled, preserve canceled state. | `backend/alberto/services/runs.py` | `test_cancellation_completion_race.py` |
| **P1** | **SSE Broker** | `_RunBroker.events` is an unbounded list. | High memory consumption and OOM risk on large/long streams. | Convert `self.events` to a bounded ring buffer (e.g., `collections.deque(maxlen=1000)`). If client requests replay beyond buffer, fall back cleanly to `_reattach_from_db`. | `backend/alberto/services/runs.py` | `test_sse_broker_bounded_buffer.py` |
| **P1** | **Startup Lifecycle** | Reaper only wakes after 300s; stale age is 3600s. | Stranded runs after container reboot stay active for up to an hour. | Call `reap_stale_runs(running_max_age_s=60)` immediately in `lifespan` on startup before accepting incoming traffic. | `backend/alberto/main.py`<br>`backend/alberto/services/runs.py` | `test_startup_stale_run_sweep.py` |
| **P1** | **Worker Retries** | Requeues immediately with no delay. | Immediate retry storms on downstream outages. | Add backoff delay column (`available_at`) or exponential sleep before re-queueing in `job_queue`. | `backend/alberto/worker.py` | `test_worker_retry_backoff.py` |
| **P2** | **Observability** | ReAct steps and tool counts only in trace spans. | Hard to query execution efficiency and loop patterns at a glance. | Add `iterations_count`, `tool_calls_count`, and `termination_reason` columns to `Run` and `Trace` models and populate them during finalization. | `backend/alberto/models/entities.py`<br>`backend/alberto/services/runs.py`<br>`backend/alberto/tracing/tracer.py` | `test_execution_observability_fields.py` |

---

## 16. Final Recommendation

Alberto's foundation in Milestone 1.5 is robust, well-structured, and strictly adheres to its single-container, local-first architecture. The core LangGraph compilation, durable checkpointer, detached SSE broker, and native SQLite queues are thoughtfully designed.

However, the execution layer has several **critical safety defaults set to "unlimited" (0)** and lacks **defensive loop-breaking and lease recovery guards**.

### Remediation Roadmap for Milestone 1.6
1. **Phase 1 (Execution Safety - P0)**:
   - Change default wall-clock run timeout from 0 to 300s.
   - Enforce timeouts on SQL and MCP tool executions.
   - Inject ReAct loop iteration caps and repeated identical tool call detection.
   - Implement worker task lease timeout and abandoned job recovery.
2. **Phase 2 (Reliability & Lifecycle - P1)**:
   - Prevent cancellation-completion terminal status overwrite race in `_finalize`.
   - Bound the SSE event buffer in `_RunBroker`.
   - Add immediate startup stale run cleanup on container boot.
   - Introduce worker retry backoff.
3. **Phase 3 (Observability & Hardening - P2)**:
   - Persist structured ReAct step counts, tool call counts, and termination reason taxonomy.
   - Expand regression tests covering timeout enforcement, cancellation races, and worker recovery.

Execution of this plan in Milestone 1.6 will ensure Alberto delivers deterministic, resilient, and enterprise-grade execution stability without introducing external queue dependencies.
