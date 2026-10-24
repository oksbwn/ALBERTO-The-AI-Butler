# Alberto — Automate Module: Comprehensive Architecture & Execution Audit

**Document Status:** Complete & Verified (Read-Only Deep Technical Audit)  
**Date:** 2026-10-21  
**Scope:** Automate Navigation Section — Workflows (`/workflows`), Agents (`/agents`), Components (`/components`), Playground (`/playground`), Graph Engine & Compiler, Scheduler & Background Workers, Tool Policies & Security Boundaries, Persistence, and Runtime Execution Pipeline.

---

## 1. Executive Summary

The **Automate** module represents Alberto's visual agentic engineering and workflow orchestration layer. It bridges high-level AI butler capabilities with declarative graph execution:
1. **Workflows Canvas (`/workflows`)**: An interactive node-based visual DAG editor powered by `@xyflow/react` (React Flow), allowing operators to build structured workflows (grounded QA, intent classification, multi-branch routers, deterministic tool calls, HITL pause-and-resume gates, and response synthesizers).
2. **Agents Screen (`/agents`)**: Management of reusable autonomous agent presets (`agent` and `deep_agent` flavors) and protected System Sub-Agents (`tool_manager`, `memory_curator`, `graph_manager`, `intent_router`).
3. **Components Screen (`/components`)**: Generative UI authoring suite (HTML, CSS, JSON Schema props, interactive action buttons) rendered dynamically by agents in Chat and Playground.
4. **Playground Screen (`/playground`)**: A real-time SSE streaming test harness with step-by-step node execution tracing, token metering, and interactive Human-In-The-Loop interrupt resumption.
5. **Graph Engine & Compiler (`engine/` & `nodes/`)**: The backend compilation engine that transforms declarative canvas graphs into executable LangGraph `StateGraph` pipelines with checkpointer state persistence.
6. **Scheduler & Native Workers (`main.py`, `dispatch.py`, `queue.py`)**: Asynchronous scheduling loop, atomic tick claiming, and SQLite-backed background worker queue with leased execution.

### Architectural Maturity & Core Strengths
- **True Detached Streaming**: The detached execution broker ([`_RunBroker`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L110-L195)) decouples client SSE connections from the underlying LangGraph task. If a client disconnects, the run continues to completion; reconnecting with `Last-Event-ID` replays missed frames from a bounded circular buffer (2,000 events) or synthesizes the final state from DB traces.
- **Defensive Multi-Tier Governance**:
  - Per-tenant daily run quota ([`run_admission`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/quota.py) and `check_run_quota`).
  - Project monthly USD spend ceiling + model allow-list enforcement ([`enforce_project_budget`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/budget.py#L1-L40)).
  - LangGraph recursion limit (max 100) + mandatory `ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`, and `RepeatedToolCallMiddleware`.
- **Decoupled Channel Gateway**: Channels (Telegram, Email) are not forced into 1:1 workflow bindings. The channel gateway ([`channel_gateway.py:480-532`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/channel_gateway.py#L480-L532)) supports independent routing to `assistant` (Master Agent), `subagent`, or `workflow`.
- **Durable HITL Checkpointing**: Human-In-The-Loop interrupts pause LangGraph execution cleanly, persisting thread state in SQLite/Postgres checkpointer tables. Hand-off requests correlate paused runs with customer conversations across channels.

### Primary Architectural Risks & Gaps
- **Critical Tool Policy Bypass in Agent Nodes (GAP-SEC-01)**: While workflow `tool_call` nodes evaluate [`ToolPolicyService.evaluate_execution`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L198-L220), agent nodes instantiate tools via [`materialize.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/tools/materialize.py#L68-L120), which only checks static user entitlements and skips `ToolPolicyService.evaluate_execution`. Autonomous agents in a workflow can execute write/delete tools without HITL approval!
- **Production Executor Misuse of Test Harness (GAP-EXEC-01)**: [`ToolManagerService.execute_tool`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/tool_manager.py#L695) calls [`ToolService.test`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/tools.py#L256-L306) rather than the standard materialization engine ([`materialize_tool`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/tools/materialize.py#L130-L180)). It executes live production tools through a simulation helper that truncates payloads.
- **No Automatic Restart Recovery for Stranded Running Workflows (GAP-REL-01)**: On container restart, the startup reaper ([`main.py:220-229`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/main.py#L220-L229)) marks running runs as errors once their timeout expires; it does not resume incomplete workflow runs from their last LangGraph checkpoint.
- **Missing Integration Event Triggers (GAP-SCHED-01)**: Schedulers, webhooks, and polling exist, but integration-driven event triggers (e.g. Home Assistant entity state changes or WebSocket events) have no canvas trigger node.

---

## 2. Actual Architecture & Execution Flow

```
                                INBOUND EVENT / USER REQUEST
                                              │
           ┌──────────────────────────────────┼──────────────────────────────────┐
           │                                  │                                  │
    HTTP Webhook                       Scheduler Loop                     Console / Test
  POST /hooks/{key}                _scheduler_loop (60s)               POST .../workflows/runs
  (HMAC + Idempotency)             (claim tick in DB txn)              (Idempotency-Key + Quota)
           │                                  │                                  │
           └──────────────────────────────────┼──────────────────────────────────┘
                                              ▼
                                   RunService.create_run
                    ┌──────────────────────────────────────────────────┐
                    │ 1. Check Tenant Quota & Project USD Budget       │
                    │ 2. Find or Create Thread (Bind End-User ID)      │
                    │ 3. Insert Run row (status="queued")              │
                    └──────────────────────────────────────────────────┘
                                              │
                                              ▼
                                     alberto.queue backend
                           ┌─────────────────────────────────────┐
                           │ AsyncInMemoryQueue / SqliteJobQueue │
                           │ (Offloads or executes inline)       │
                           └─────────────────────────────────────┘
                                              │
                                              ▼
                                    RunService._execute
                    ┌──────────────────────────────────────────────────┐
                    │ 1. Acquire tenant concurrency slot & thread lock │
                    │ 2. Build CompileContext (tools, MCPs, presets)   │
                    │ 3. compile_workflow -> LangGraph StateGraph      │
                    │ 4. Attach ForgeTracer + Activity Deque           │
                    │ 5. Register in _RunControl (cancel watcher)      │
                    └──────────────────────────────────────────────────┘
                                              │
                                              ▼
                                      graph.astream(...)
                         ┌───────────────────────────────────────────┐
                         │ Streams tasks, updates, messages, custom  │
                         │ Durability: sync checkpointer write/step  │
                         └───────────────────────────────────────────┘
                           │                         │             │
        Node: tool_call    │      Node: agent        │             │ Node: human_input
        ┌──────────────────┤      ┌──────────────────┤             │ ┌────────────────┐
        │ ToolPolicyService│      │ Tool invocation  │             │ │ LangGraph      │
        │ evaluate_execution      │ (materialize.py) │             │ │ interrupt()    │
        │ (Policy Gate)    │      │ [BYPASSES        │             │ └────────────────┘
        │   │              │      │  EVALUATE_EXEC!] │             │        │
        │   ▼              │      │   │              │             │        ▼
        │ tool.ainvoke()   │      │   ▼              │             │ status="interrupted"
        └──────────────────┘      │ tool.ainvoke()   │             │ Wait for resume
                                  └──────────────────┘             │ or reaper timeout
                                              │
                                              ▼
                                     _finalize / DB Commit
                    ┌──────────────────────────────────────────────────┐
                    │ 1. Persist final status (done/interrupted/error) │
                    │ 2. Compute token metrics & USD cost via tracer   │
                    │ 3. Write Trace & Span records                    │
                    │ 4. Publish terminal frame to _RunBroker          │
                    └──────────────────────────────────────────────────┘
```

---

## 3. Complete File Map

### 3.1. Frontend Surfaces

| File Path | Size / Lines | Role / Responsibility | Status |
|---|---|---|---|
| [`frontend/components/screens/workflows.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/workflows.tsx) | 72.3 KB / 1383 lines | Primary workflows view: workflow list, React Flow canvas, node palette, typed inspector, version history, export/import, and embedded test panel. | **Active** (`/workflows`) |
| [`frontend/components/screens/agents.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/agents.tsx) | 12.4 KB / 223 lines | Preset list view, system agent badges, creation modal, and agent detail routing. | **Active** (`/agents`) |
| [`frontend/components/screens/components.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/components.tsx) | 18.2 KB / 395 lines | Generative UI editor: live code preview (HTML/CSS), JSON Schema property definition, mock test data injection. | **Active** (`/components`) |
| [`frontend/components/screens/playground.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/playground.tsx) | 25.6 KB / 439 lines | Standalone chat execution harness: SSE token streaming, activity timeline, token meters, HITL decision modal. | **Active** (`/playground`) |
| [`frontend/components/canvas/ForgeNode.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ForgeNode.tsx) | 13.9 KB / 330 lines | Custom React Flow node view: handles input/output ports, status icons, sub-agent chips, error badges. | **Active** |
| [`frontend/components/canvas/AgentConfig.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/AgentConfig.tsx) | 27.8 KB / 603 lines | Inspector panel for agent nodes: flavor toggles (`agent` vs `deep_agent`), model picker, subagent builder, tool picker. | **Active** |
| [`frontend/components/canvas/ConfigForm.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ConfigForm.tsx) | 20.3 KB / 498 lines | Dynamic inspector form for non-agent nodes (router cases, LLM prompts, tool ID bindings, human input approvals). | **Active** |
| [`frontend/components/canvas/WorkflowTestPanel.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/WorkflowTestPanel.tsx) | 13.6 KB / 278 lines | Embedded canvas testing drawer: stream runner, active node highlighting, token count display. | **Active** |
| [`frontend/components/canvas/EdgeOverlay.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/EdgeOverlay.tsx) | 4.8 KB / 128 lines | SVG edge overlay for animated run traversal and condition labels on router edges. | **Active** |
| [`frontend/components/component-renderer.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/component-renderer.tsx) | 7.9 KB / 195 lines | Safe sandboxed rendering engine for generative UI components with CSS encapsulation and action button dispatch. | **Active** |
| [`frontend/lib/graph.ts`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/lib/graph.ts) | 9.1 KB / 192 lines | Canvas (React Flow) <-> Executable JSON translation (`canvasToExecutable`, `canvasToFlow`), IO-type validation. | **Active** |
| [`frontend/lib/chat-parts.ts`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/lib/chat-parts.ts) | 3.2 KB / 92 lines | Parser for interleaved markdown text and `[[forge:component:ID]]` component markers. | **Active** |

### 3.2. Backend Pipeline

| File Path | Role / Responsibility | Status |
|---|---|---|
| [`backend/alberto/routers/workflows.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/routers/workflows.py) | CRUD, canvas sync (`PUT /canvas`), JSON schema validation, export/import, publish. | **Active** |
| [`backend/alberto/routers/agents.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/routers/agents.py) | Agent presets CRUD, system subagent protection, flavor assignment. | **Active** |
| [`backend/alberto/routers/components.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/routers/components.py) | Generative UI component definitions, props schemas, mock test execution. | **Active** |
| [`backend/alberto/routers/runs.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/routers/runs.py) | Run creation (`POST /runs`), SSE streaming endpoint (`GET /stream`), rerun, resume, cancel. | **Active** |
| [`backend/alberto/routers/hooks.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/routers/hooks.py) | Inbound webhook dispatch (`POST /{key}`), HMAC-SHA256 signature verification, idempotency. | **Active** |
| [`backend/alberto/routers/triggers.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/routers/triggers.py) | Project trigger management: ownership, `run_as_user_id`, and `scope` assignment. | **Active** |
| [`backend/alberto/services/runs.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py) | RunService: detached executor, `_RunBroker`, LangGraph driving loop, stale run reaper. | **Active** |
| [`backend/alberto/services/dispatch.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/dispatch.py) | DispatchService: inbound trigger execution, schedule ticks, app event polling. | **Active** |
| [`backend/alberto/services/triggers.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/triggers.py) | Trigger synchronization from workflow nodes, cron & interval due calculation. | **Active** |
| [`backend/alberto/services/tool_manager.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/tool_manager.py) | Unified Tool Manager & Integration Gateway: analysis, categorization, execution routing. | **Active** |
| [`backend/alberto/services/tool_policy.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/tool_policy.py) | Central execution policy engine: default-deny, risk evaluation, HITL approval requirement. | **Active** |
| [`backend/alberto/queue.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/queue.py) | Background queue engine: `AsyncInMemoryQueue` and `SqliteJobQueue` with atomic leases. | **Active** |
| [`backend/alberto/engine/compiler.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/compiler.py) | Graph compiler: transforms declarative executable JSON into LangGraph `StateGraph`. | **Active** |
| [`backend/alberto/engine/middleware_compiler.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/middleware_compiler.py) | Middleware compiler: safety guards (`RepeatedToolCallMiddleware`, limits, prompt caching). | **Active** |
| [`backend/alberto/nodes/agent_node.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/agent_node.py) | Agent node factory: model resolution, dynamic presets, tools, subagents, prompt building. | **Active** |
| [`backend/alberto/nodes/data.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py) | Node handlers: `tool_call` (policy enforced), `transform` (JMESPath), `human_input` (HITL). | **Active** |
| [`backend/alberto/nodes/flow.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py) | Routing nodes: `router` (truthy expression evaluation), `parallel`, `passthrough`, `start`, `end`. | **Active** |
| [`backend/alberto/nodes/rag.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/rag.py) | Retrieval nodes: vector document search and curated Q&A lookup. | **Active** |
| [`backend/alberto/nodes/triggers.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/triggers.py) | Trigger node specifications: `webhook_in`, `schedule`, `email_in`, `app_event`. | **Active** |
| [`backend/alberto/tools/materialize.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/tools/materialize.py) | Universal tool builder: materializes REST, GraphQL, Code, SQL, MCP, and Builtin tools. | **Active** |

---

## 4. Capability Matrix

| Capability Area | Feature / Mechanism | Implementation Status | Verification Details |
|---|---|---|---|
| **Scheduling & Triggers** | Recurring Interval (`every_minutes`) | **Implemented and verified** | Handled in [`triggers.py:153-157`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/triggers.py#L153-L157) & [`dispatch.py:121-143`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/dispatch.py#L121-L143). Tested in `test_triggers.py`. |
| | Cron Expressions | **Implemented and verified** | Handled via `croniter` in [`triggers.py:158-167`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/triggers.py#L158-L167). Verified. |
| | One-Time Schedules (`run_at`) | **Missing** | No schema field or evaluation logic for single-shot execution dates. |
| | Inbound Webhooks (`webhook_in`) | **Implemented and verified** | HMAC-SHA256 signature verification + deduplication in [`hooks.py:153-195`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/routers/hooks.py#L153-L195). |
| | App Event Polling (`app_event`) | **Implemented and verified** | SSRF-guarded HTTP poll + JMESPath dedupe in [`dispatch.py:167-220`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/dispatch.py#L167-L220). |
| | Integration / HA Event Triggers | **Missing** | No `homeassistant_event` trigger node; HA is currently outbound only. |
| | Independent Channel Triggers | **Implemented and verified** | Channels route to `assistant`, `subagent`, or `workflow` ([`channel_gateway.py:480-532`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/channel_gateway.py#L480-L532)). |
| **Execution Lifecycle** | Run Admission & Quotas | **Implemented and verified** | Atomic daily quota + monthly USD caps in [`quota.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/quota.py) & [`budget.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/budget.py). |
| | Run Idempotency | **Partially implemented** | In-memory cache in [`alberto/util/ratelimit.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/util/ratelimit.py). Lost on container restart. |
| | Detached SSE Streaming | **Implemented and verified** | [`_RunBroker`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L110-L195) decouples client disconnection from run execution. |
| | Reconnection & Catch-Up | **Implemented and verified** | Monotonic event IDs + `Last-Event-ID` replay + DB fallback synthesis. |
| | Cooperative & Hard Cancellation | **Implemented and verified** | [`_RunControl`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L53-L100) polls DB status and interrupts asyncio tasks. |
| **Tool Security & Policies** | Workflow `tool_call` Policy Check | **Implemented and verified** | Evaluates [`ToolPolicyService.evaluate_execution`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L198-L220). |
| | Agent-Initiated Tool Policy Check | **Missing** | [`alberto/tools/materialize.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/tools/materialize.py#L38-L80) only checks static entitlements; skips policy evaluation. |
| | Tool Execution Gateway | **Implemented but incomplete** | [`ToolManagerService.execute_tool`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/tool_manager.py#L695) delegates to test helper `ToolService.test`. |
| **Agent Integration** | Dynamic Preset Inheritance | **Implemented and verified** | [`agent_node.py:543-553`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/agent_node.py#L543-L553) loads live agent presets via `agent_ref` at compile time. |
| | Sub-Agent Workflow Nesting | **Partially implemented** | Staged in `build_subagents` line 372 (`# TODO(phase: subworkflow)`). |
| | System Sub-Agent Protection | **Implemented and verified** | Protected from deletion and rename in [`agents.py:101-135`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/agents.py#L101-L135). |
| **Observability & Testing** | Real Token Metering & Cost | **Implemented and verified** | Provider-reported usage tracked by `ForgeTracer` and persisted to `Trace`. |
| | Shared Test / Prod Run Isolation | **Partially implemented** | Both console test runs and production runs share the same tables and endpoints. |
| **Persistence & Recovery** | HITL Pause / Resume Durability | **Implemented and verified** | LangGraph checkpointer persists paused state; resumable via `/resume`. |
| | Active Run Restart Recovery | **Partially implemented** | Stale runs are reaped as error; no automated resume of incomplete workflows. |
| | SQLite Job Queue Leases | **Implemented and verified** | `SqliteJobQueue` in [`queue.py:134-224`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/queue.py#L134-L224) has atomic lease claiming and expiry. |

---

## 5. Confirmed Gaps

### GAP-SEC-01 (Severity: Critical) — Agent Tool Invocations Bypass `ToolPolicyService`
- **Affected Files:** [`backend/alberto/tools/materialize.py:38-120`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/tools/materialize.py#L38-L120), [`backend/alberto/nodes/agent_node.py:496-515`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/agent_node.py#L496-L515)
- **Current Behavior:** Agent nodes compile tools via `ctx.tools_for(...)` and wrap them with `_wrap_reliability`. This wrapper checks `entitlement_denial` (static user roles) but **never calls `ToolPolicyService.evaluate_execution`**.
- **Expected Behavior:** Every tool invocation (whether from a deterministic `tool_call` node or an autonomous agent) must pass through `ToolPolicyService.evaluate_execution` to enforce read/write/delete permissions, rate limits, and HITL approval gates.
- **Technical Impact:** An autonomous agent inside a workflow can execute destructive write/delete actions (e.g. smart lock unlock, device delete) without requiring HITL human approval.
- **Recommended Direction:** Inject a unified policy execution wrapper in `materialize.py` that invokes `ToolPolicyService.evaluate_execution` before executing `inner.ainvoke()`.

---

### GAP-EXEC-01 (Severity: High) — `ToolManagerService.execute_tool` Uses Test Harness
- **Affected Files:** [`backend/alberto/services/tool_manager.py:695`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/tool_manager.py#L695)
- **Current Behavior:** `ToolManagerService.execute_tool` executes tools by calling `ToolService.test(tenant_id, project_id, cfg, parameters, ctx)`.
- **Expected Behavior:** Live tool execution should use the production tool materialization pipeline ([`materialize_tool`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/tools/materialize.py#L130-L180)), not a test preview method that formats token diffs and truncates payloads for the UI builder.
- **Technical Impact:** Payload truncation (`_clip` at 20,000 chars), synthetic latency injection, and bypass of standard tool runtime wrappers.
- **Recommended Direction:** Replace `ToolService.test` in `tool_manager.py` with `materialize_tool(cfg, ctx).ainvoke(parameters)`.

---

### GAP-REL-01 (Severity: High) — No Workflow Restart Recovery for Incomplete Runs
- **Affected Files:** [`backend/alberto/main.py:220-229`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/main.py#L220-L229), [`backend/alberto/services/runs.py:1519-1535`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L1519-L1535)
- **Current Behavior:** When the Alberto backend container restarts, `startup_run_service.reap_stale_runs()` identifies running jobs whose process died and marks them as `error` (`stale_running_reaped`) once their timeout expires.
- **Expected Behavior:** Since LangGraph checkpointer persists exact node-level state after every step, non-terminal deterministic workflows interrupted by restart should be eligible for automatic resumption or re-queuing.
- **Technical Impact:** Any server reboot or container redeploy causes long-running or queued workflows to permanently fail without retry.
- **Recommended Direction:** Add a recovery policy setting (`auto_resume_on_restart`). If enabled, the startup sweep re-enqueues interrupted runs from their latest checkpoint rather than reaping them as errors.

---

### GAP-SCHED-01 (Severity: Medium) — Missing Integration / Hardware Event Triggers
- **Affected Files:** [`backend/alberto/nodes/triggers.py:18`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/triggers.py#L18), [`backend/alberto/services/triggers.py:146-175`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/triggers.py#L146-L175)
- **Current Behavior:** The only supported trigger node types are `webhook_in`, `schedule`, `email_in`, and `app_event`. There is no native trigger node for Home Assistant events (e.g. motion detected, door open) or MQTT/Webhook state transitions.
- **Expected Behavior:** An AI Butler requires event-driven reactive workflows triggered by smart home events.
- **Technical Impact:** Operators must set up external webhook bridges or poll REST endpoints with `app_event` every N minutes instead of receiving real-time device event triggers.
- **Recommended Direction:** Introduce an `integration_event` node type backed by Home Assistant WebSocket subscription or inbound webhook dispatch.

---

### GAP-OBS-01 (Severity: Medium) — Playground and Embedded Test Panel Code Duplication
- **Affected Files:** [`frontend/components/screens/playground.tsx:59-150`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/playground.tsx#L59-L150), [`frontend/components/canvas/WorkflowTestPanel.tsx:80-170`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/WorkflowTestPanel.tsx#L80-L170)
- **Current Behavior:** Both components duplicate identical ~100-line SSE streaming connection loops, frame parsing logic (`node_start`, `activity`, `messages`, `interrupt`, `done`), and Mustache action button state handling.
- **Expected Behavior:** Reusable React hook (e.g. `useWorkflowRunStream`) shared between Playground and WorkflowTestPanel.
- **Technical Impact:** Divergent bug fixes, inconsistent error handling, and maintenance overhead.
- **Recommended Direction:** Extract the common SSE subscriber, accumulator, and interrupt logic into a shared hook `useWorkflowExecutionStream`.

---

### GAP-UI-01 (Severity: Low) — System Agent Status Badge Displays "Inactive"
- **Affected Files:** [`frontend/components/screens/agents.tsx:77-81`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/agents.tsx#L77-L81)
- **Current Behavior:** Active system agents (`tool_manager`, `memory_curator`, `graph_manager`) display an "Inactive (M2.1)" badge in the UI because their DB status string is hardcoded.
- **Expected Behavior:** System agents should accurately reflect their operational state (`Active Sub-Agent` / `Operational`).
- **Technical Impact:** Visual confusion for operators inspecting the system sub-agent catalog.

---

## 6. Existing Capabilities to Reuse

| Component / Subsystem | Path | Capabilities to Reuse (Avoid Re-inventing) |
|---|---|---|
| **Queue & Worker Engine** | [`alberto/queue.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/queue.py) | Full asynchronous worker engine with both in-memory (`AsyncInMemoryQueue`) and dedicated SQLite (`SqliteJobQueue`) backends. Includes atomic leases, exponential backoff, and dead-letter queue. **Do not install Celery/Redis.** |
| **Dispatch Service** | [`alberto/services/dispatch.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/dispatch.py) | Central trigger runner for webhooks, schedules, email, and channels. Re-check and claim-stamping in single transactions. |
| **Safety Middleware** | [`alberto/engine/middleware_compiler.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/middleware_compiler.py) | `RepeatedToolCallMiddleware`, `ToolCallLimitMiddleware`, `ModelCallLimitMiddleware`. Already prevents runaway loops. |
| **Materialize Pipeline** | [`alberto/tools/materialize.py`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/tools/materialize.py) | Universal tool builder supporting REST, GraphQL, Code (sandbox), SQL, MCP, and Builtin. Central place to enforce security policies. |
| **LangGraph Checkpointer** | [`alberto/main.py:50-81`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/main.py#L50-L81) | SQLite / Postgres durable checkpointer with atomic state save per step and thread locking (`thread_locks`). |

---

## 7. Architecture Decisions Required Before Development

1. **Agent Tool Policy Enforcement Model**:
   - *Option A (Recommended)*: Wrap all tools inside `materialize.py` with `ToolPolicyService.evaluate_execution` so both agents and workflow DAG nodes share identical policy enforcement, risk thresholds, and approval requirements.
   - *Option B*: Keep agent tools unconstrained and rely solely on system prompt guidance (high risk of unintended side-effects).
2. **Container Restart Recovery Strategy**:
   - *Option A (Recommended)*: Mark interrupted runs with recovery eligibility in DB. On restart, re-enqueue runs that were interrupted mid-flight from their last durable LangGraph checkpoint.
   - *Option B (Current)*: Reap all stranded runs as errors and require operators to manually replay them.
3. **Smart Home Event Trigger Architecture**:
   - *Option A (Recommended)*: Add an `integration_event` node to the canvas that hooks into Home Assistant / MQTT events via the existing Integration Manager gateway.
   - *Option B*: Require users to configure Home Assistant webhooks pointing to Alberto's existing `webhook_in` URLs.
4. **Tool Manager Execution Convergence**:
   - Remove the call to `ToolService.test` in `ToolManagerService.execute_tool` and unify tool execution strictly around `materialize_tool`.

---

## 8. Recommended Implementation Sequence

```
Phase 1: Security & Policy Enforcement (Zero UI Risk)
  ├── 1. Wrap ToolPolicyService in materialize.py for agent-initiated calls (GAP-SEC-01)
  └── 2. Point ToolManagerService.execute_tool to materialize_tool (GAP-EXEC-01)

Phase 2: Execution Durability & Scheduling
  ├── 3. Implement container restart checkpoint re-queuing (GAP-REL-01)
  ├── 4. Add integration_event trigger node for Home Assistant (GAP-SCHED-01)
  └── 5. Support one-time schedule triggers (run_at timestamp)

Phase 3: Observability & Frontend Consolidation
  ├── 6. Extract useWorkflowExecutionStream hook for Playground & Test Panel (GAP-OBS-01)
  ├── 7. Tag debug/test runs with distinct source metadata (source="test_panel")
  └── 8. Harmonize system agent status badges in agents.tsx (GAP-UI-01)
```

---

## 9. Open Questions (Unanswerable from Repository Inspection Alone)

1. **Target Hardware Constraints for Background Workers**:
   - When running on resource-constrained devices (e.g. Raspberry Pi 4 / 8GB Intel N100), should the SQLite background worker run in-process (`AsyncInMemoryQueue`) or as a separate isolated process (`python -m forge.worker`)?
2. **Side-Effecting External Tool Idempotency**:
   - Does Home Assistant or connected smart home devices provide idempotent toggle tokens, or must Alberto implement state verification before retrying an interrupted write action?
