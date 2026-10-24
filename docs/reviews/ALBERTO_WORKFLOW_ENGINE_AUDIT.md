# Alberto — Low-Code Workflow Engine: Comprehensive Architecture, Functionality & UX Audit

**Audit Date:** October 24, 2026  
**Auditor:** Antigravity Engineering (Autonomous Diagnostic Agent)  
**Target Repository:** Alberto (Local AI Home Butler & Workflow Engine)  
**Scope:** Visual Designer, Node Registry, LangGraph Runtime, Tool Security, Triggers & Scheduler, Observability, Automation Manager, Persistence, and Test Suites.  
**Mode:** Diagnostic & Evidence-Based Audit Only (Zero code modifications).

---

## A. Executive Summary

Alberto possesses a surprisingly sophisticated, local-first workflow orchestration engine based on **LangGraph** (`CompiledStateGraph`), **FastAPI**, **SQLite**, and **React Flow** (`@xyflow/react`). Unlike typical toy visual builders that either naively wrap linear chains or rely on fragile LLM-generated code strings, Alberto employs a true graph-compilation pipeline with typed node schemas, explicit control/conditional edges, sandboxed state transitions, and detached background execution.

### What Alberto Does Exceptionally Well
1. **LangGraph StateGraph Compilation & Detached Streaming:** The workflow compiler ([compiler.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/compiler.py#L81-L189)) compiles executable JSON definitions into native `CompiledStateGraph` instances. Execution in [runs.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L620-L750) is run in detached background tasks managed by a thread-safe `_RunBroker` and `_RunStreams` registry, multiplexing SSE events (`tasks`, `updates`, `messages`, `custom`) and supporting browser reconnections via `Last-Event-ID`.
2. **Strict Tool Security Enforcement:** Centralized security policy ([tool_policy.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/tool_policy.py#L187-L340)) is enforced across both deterministic `tool_call` nodes ([data.py:198-220](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L198-L220)) and agentic tool calls ([agent_node.py:361-425](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/agent_node.py#L361-L425)). Neither execution path can bypass default-deny activation, project scoping, caller verification, or runtime approval requirements.
3. **Deterministic & Parallel Control Flow:** Built-in support for conditional routing with multi-branch evaluation ([flow.py:44-93](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L44-L93)), bounded loops with strict `max_iter` ceilings ([flow.py:171-193](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L171-L193)), and parallel fan-out via LangGraph `Send` with stable index ordering ([flow.py:196-225](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L196-L225)).
4. **Resilient Background Triggers:** Triggers are embedded in workflow definitions ([workflows.py:141-155](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/workflows.py#L141-L155)) and synchronized to SQLite `Trigger` rows. Schedulers claim due runs atomically in transactions with `last_fired_at` stamps ([dispatch.py:123-179](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/dispatch.py#L123-L179)), preventing duplicate execution across ticks or replicas.
5. **Observability Workbench:** The Unified Workflow Execution Panel ([WorkflowTestPanel.tsx](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/WorkflowTestPanel.tsx)) provides real-time node illumination, token and latency metrics, live subagent/tool activity traces, secret-redacted JSON inspection, and inline HITL approval/rejection buttons.

### Critical Gaps & Architectural Fragilities
1. **Handle ID Dropping on Canvas (Typed Port Mismatch):** While [registry.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/registry.py#L1-L75) defines typed I/O ports (`json`, `text`, `messages`, `any`, `control`) with an `io_compatible` validation matrix, [ForgeNode.tsx:66-70](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ForgeNode.tsx#L66-L70) omits `id` on single-port handles. React Flow emits edges without `sourceHandle` and `targetHandle` (except router `case:*` handles), causing port-level compatibility checks to fall back to generic passthroughs.
2. **Schema Directory Redundancy:** The codebase maintains two completely identical node schema directories: [backend/schemas/alberto/nodes/](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/schemas/alberto/nodes) and [backend/schemas/forge/nodes/](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/schemas/forge/nodes) (21 JSON schema files each).
3. **Knowledge Graph Sync Mismatch:** In [workflows.py:186](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/workflows.py#L186), `_sync_knowledge_graph` checks `if n.get("type") == "tool"`, but the registered node type is `"tool_call"`. Consequently, standalone tool call nodes are never linked in LadybugDB Knowledge Graph entity relationships.
4. **Data Mapping Inaccessibility for Non-Technical Users:** Data flow between downstream nodes requires writing raw JMESPath expressions or configuring state key variables (`input_key`, `output_key`). There is no visual drag-and-drop or token-picker property editor for intermediate node outputs.
5. **Absence of Version History / Rollback:** Workflows increment `active_version` on every canvas save, but previous graph definitions are overwritten in place in the `workflows` table.

---

## B. Execution Architecture & Lifecycle Map

```
  +----------------------------------------------------------------------------------------------------+
  |                                        REACT FLOW DESIGNER                                         |
  |  - Canvas State (nodes, edges, viewport)                                                            |
  |  - Property Inspector Forms (ConfigForm.tsx, AgentConfig.tsx)                                      |
  |  - Auto-Discovery & State Injection (graph.ts: canvasToExecutable)                                 |
  +---------------------------------------------------+------------------------------------------------+
                                                      | PUT /workflows/{id}/canvas
                                                      v
  +----------------------------------------------------------------------------------------------------+
  |                                     FASTAPI WORKFLOW SERVICE                                       |
  |  - Schema Validation (validation.py: Layer 1 Shape, Layer 2 Node Schemas, Layer 3 Structural Rules) |
  |  - Persistence (SQLite 'workflows' table: stores canvas JSON + executable JSON)                   |
  |  - Embedded Trigger Sync (TriggerService.sync_from_workflow: updates SQLite 'triggers' table)       |
  |  - Knowledge Graph Sync (_sync_knowledge_graph -> LadybugDB USES relationships)                    |
  +---------------------------------------------------+------------------------------------------------+
                                                      | POST /runs (stream=true)
                                                      v
  +----------------------------------------------------------------------------------------------------+
  |                                          LANGGRAPH RUNTIME                                         |
  |  - CompileContext Resolution (models, tool registry, auth resolver, checkpointer, store)          |
  |  - Graph Compilation (compiler.py: StateGraph, subagent folding, router conditional edges)         |
  |  - Detached Execution Task (_RunBroker & _RunStreams in runs.py)                                   |
  |  - Concurrency Lock (thread_locks + tenant_concurrency slots)                                      |
  |  - LangGraph astream (stream_mode=["tasks", "updates", "messages", "custom"], subgraphs=True)      |
  +-------------------------+------------------------------------+-------------------------------------+
                            |                                    |
                            v                                    v
  +-----------------------------------+        +-----------------------------------+
  |      DETERMINISTIC PIPELINE       |        |          AGENTIC SUBGRAPH         |
  |  - Pure Python / JMESPath / JQ    |        |  - LangChain ChatModel Invocation |
  |  - tool_call -> ToolPolicyService |        |  - Subagent Orchestration / Tools |
  |  - router -> conditional branch   |        |  - MemoryRecallMiddleware         |
  |  - parallel_fanout -> Send batch  |        |  - ToolPolicyService Enforcement  |
  +-----------------+-----------------+        +-----------------+-----------------+
                    |                                            |
                    +--------------------+-----------------------+
                                         |
                                         v
  +----------------------------------------------------------------------------------------------------+
  |                                 OBSERVABILITY & HITL MANAGEMENT                                    |
  |  - LangGraph interrupt() -> Run status 'interrupted' -> POST /runs/{id}/resume                     |
  |  - ForgeTracer collects Trace & Span records -> persisted to SQLite                               |
  |  - Cross-Worker Cancellation via _RunControl watching Run.status == "canceled"                    |
  |  - Unified Workflow Execution Panel (WorkflowTestPanel.tsx) renders SSE updates & JSON output     |
  +----------------------------------------------------------------------------------------------------+
```

### Complete Lifecycle Trace

| Lifecycle Phase | Source of Truth | Key Components & Files | Operational Behavior |
|---|---|---|---|
| **1. Definition** | Frontend React Flow State | [workflows.tsx](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/workflows.tsx), [graph.ts](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/lib/graph.ts) | React Flow maintains `nodes` and `edges`. On commit, `canvasToExecutable` identifies entry node and infers written state keys. |
| **2. Validation** | Backend Contracts & Registry | [validation.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/validation.py), [registry.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/registry.py) | 3-layer check: JSON schema shape (`forge/workflow`), individual node config schemas, and structural DFS (reachability, cycle detection, path to END). |
| **3. Persistence** | SQLite Database (`workflows`, `triggers`) | [workflows.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/workflows.py), [triggers.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/triggers.py) | `canvas` and `executable` persisted in atomic transaction; embedded triggers upserted into `triggers` table; KG entities linked. |
| **4. Compilation** | Memory (`CompiledStateGraph`) | [compiler.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/compiler.py), [middleware_compiler.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/middleware_compiler.py) | Compiles AST/JSON into LangGraph builder; folds sub-agents into parent `deep_agent`; wires conditional edges and parallel fanout. |
| **5. Execution** | Detached Asyncio Task & Broker | [runs.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py), [runtime.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runtime.py) | `create_run` creates DB rows (`runs`, `threads`). Detached executor `_drive` runs graph; thread-level lock prevents state interleaving. |
| **6. Node Processing** | Registered Node Handlers | [nodes/agent_node.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/agent_node.py), [nodes/data.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py), [nodes/flow.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py) | Nodes execute synchronously or asynchronously. Tools and agents evaluate permissions via `ToolPolicyService`. |
| **7. State Updates** | LangGraph State Schema | [state.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/state.py), [context.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/context.py) | Updates applied to channels with declared reducers (`last`, `add`, `add_messages`). Undeclared keys are dropped. |
| **8. Output & Observability** | SSE Stream & Tracing DB | [WorkflowTestPanel.tsx](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/WorkflowTestPanel.tsx), [tracer.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/tracing/tracer.py) | Live SSE frames dispatched to UI (`node_start`, `activity`, `messages`, `done`). Spans persisted to SQLite `spans`/`traces`. |
| **9. History & Replay** | SQLite Checkpointer & Run DB | [runs.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L197-L224), [models.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/models.py) | Reconnections replay buffered frames by `last_event_id`; completed runs reconstructed from persisted traces. |

---

## C. Complete Node Architecture & Inventory

The engine registers **23 distinct node types** in [backend/alberto/engine/registry.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/registry.py#L80-L105).

| Node Type | Category | Purpose | Configuration | Inputs | Outputs | Runtime Handler | Validation | Error Handling | UI Support | Status | Source File |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `start` | `flow` | Graph entry marker | `{}` | `any` | `any` | `start_factory` ([flow.py:36](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L36)) | Schema validated | Passthrough | Canvas node | Complete | [flow.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py) |
| `end` | `flow` | Graph terminal marker | `{}` | `any` | `any` | `end_factory` ([flow.py:40](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L40)) | Reached by DFS | Passthrough | Canvas node | Complete | [flow.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py) |
| `router` | `flow` | State-based conditional branch | `expression`, `cases`, `default`, `multi` | `control` | `control` | `router_factory` ([flow.py:95](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L95)) | Target node existence, writer check | Logs failure, falls back to `default`/`END` | `RouterForm` editor | Complete | [flow.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py) |
| `loop` | `flow` | Bounded iteration counter | `max_iter`, `condition` | `control` | `control` | `loop_factory` ([flow.py:171](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L171)) | `allows_cycle=True` | Stops at `max_iter` or falsy condition | Config form | Complete | [flow.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py) |
| `subworkflow` | `flow` | Reusable child workflow | `workflow_id`, `version`, `input_mapping`, `output_mapping` | `any` | `any` | `subworkflow_factory` ([flow.py:100](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L100)) | Cycle detection via `ctx.compiling` | Missing definition returns `{}` | Config form | Complete | [flow.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py) |
| `parallel_fanout`| `flow` | Map over array via `Send` | `over`, `child_node`, `item_key`, `index_key`, `on_item_error`, `item_timeout_seconds` | `any` | `any` | `make_fanout_path` ([flow.py:196](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L196)) | `child_node` reachability in `_adjacency` | `resilient_fanout_child` isolates/skips item | Config form | Complete | [flow.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py) |
| `join` | `flow` | Fan-in state aggregator | `key`, `reducer`, `output_key`, `sort_by_index` | `any` | `any` | `join_factory` ([flow.py:302](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L302)) | Reducer in `(concat, first, last, merge)` | Non-list values passed unchanged | Config form | Complete | [flow.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py) |
| `agent` | `agents` | Specialist agent runner | `name`, `model`, `system_prompt`, `tools`, `toolsets`, `memory` | `messages` | `messages` | `agent_factory` ([agent_node.py:650](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/agent_node.py#L650)) | Schema validated, checks model | Tool policy error propagation | `AgentConfig` inspector | Complete | [agent_node.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/agent_node.py) |
| `deep_agent` | `agents` | Supervisor with subagents | `name`, `model`, `subagents`, `tools`, `toolsets` | `messages` | `messages` | `deep_agent_factory` ([agent_node.py:750](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/agent_node.py#L750)) | Subagent edge handle check | Subagent failure captured in trace | Canvas supervisor handle | Complete | [agent_node.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/agent_node.py) |
| `human_input` | `human` | HITL approval interrupt | `prompt`, `allowed_decisions`, `output_key`, `timeout_seconds` | `any` | `any` | `human_input_factory` ([data.py:80](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L80)) | Decision list non-empty | LangGraph `interrupt()`, reaper expiry | Interactive approval drawer | Complete | [data.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py) |
| `handoff` | `human` | Live agent chat handoff | `reason`, `ack_message` | `any` | `any` | `handoff_factory` ([data.py:124](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L124)) | Schema validated | Pauses run until human replies | Inspector form | Complete | [data.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py) |
| `webhook_out` | `integrations`| Outbound HTTP request | `method`, `url`, `body`, `headers`, `auth_provider_id`, `output_key` | `json` | `json` | `webhook_out_factory` ([data.py:140](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L140)) | SSRF validation via `validate_url` | HTTP error raised or captured | Config form | Complete | [data.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py) |
| `emit_event` | `integrations`| Custom SSE event push | `channel`, `payload` | `any` | `any` | `emit_event_factory` ([data.py:231](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L231)) | Schema validated | Swallowed if no stream writer | Config form | Complete | [data.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py) |
| `retrieval` | `knowledge` | RAG & FAQ search | `include_docs`, `include_qa`, `folders`, `top_k`, `min_score`, `hybrid`, `rerank` | `messages` | `messages` | `retrieval_factory` ([rag.py:58](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/rag.py#L58)) | Warns if both docs and QA disabled | Cosine/RRF floor, `announce_empty` | Knowledge section in inspector | Complete | [rag.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/rag.py) |
| `llm` | `model_tools` | Single LLM prompt call | `model`, `prompt`, `response_format`, `model_params` | `text` | `text` | `llm_factory` ([llm_node.py:20](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/llm_node.py#L20)) | Structured schema validated | Model exceptions propagated | Config form with model picker | Complete | [llm_node.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/llm_node.py) |
| `classifier` | `model_tools` | Intent classification | `labels`, `output_key`, `multi_label`, `model` | `messages` | `control` | `classifier_factory` ([llm_node.py:63](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/llm_node.py#L63)) | Non-empty labels list | Fallback to naive keyword match | Labels editor in inspector | Complete | [llm_node.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/llm_node.py) |
| `tool_call` | `model_tools` | Explicit tool execution | `tool_id`, `input_mapping`, `output_key` | `json` | `json` | `tool_call_factory` ([data.py:177](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L177)) | Tool existence in registry | `ToolPolicyService` denial / error dict | Tool selector dropdown | Complete | [data.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py) |
| `transform` | `model_tools` | JMESPath / JQ data map | `expression`, `engine`, `input_key`, `output_key` | `json` | `json` | `transform_factory` ([data.py:57](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L57)) | Schema validated | Logs error, writes `None` to `output_key` | Expression input | Complete | [data.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py) |
| `webhook_in` | `triggers` | Inbound webhook trigger | `secret`, `signed`, `auth_header`, `output_key` | None | `json` | Passthrough entry node; mirrored to `Trigger` | Signed webhook secret warning | 401 Unauthorized on invalid signature | Trigger inspector | Complete | [triggers.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/triggers.py) |
| `schedule` | `triggers` | Cron / one-time trigger | `cron`, `timezone`, `run_at` | None | `any` | Passthrough entry node; claimed by scheduler | Cron / ISO datetime format | Missed ticks claimed atomically | Cron input in inspector | Complete | [triggers.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/triggers.py) |
| `email_in` | `triggers` | Inbound email trigger | `mailbox`, `allowed_senders`, `output_key` | None | `json` | Passthrough entry node; polled by email worker | Email address format | Unknown senders ignored | Config form | Complete | [triggers.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/triggers.py) |
| `app_event` | `triggers` | HTTP poll event trigger | `poll_url`, `method`, `items_path`, `seen_key` | None | `json` | Passthrough entry node; polled by worker | SSRF guarded URL | Deduped via `meta.seen` | URL/poll config form | Complete | [triggers.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/triggers.py) |
| `integration_event`| `triggers`| Channel event trigger | `connector_id`, `event_type`, `output_key` | None | `json` | Aliased to `app_event` spec | Connector existence | Connector event filtering | Connector picker | Complete | [triggers.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/triggers.py) |

---

## D. Workflow Capability Matrix

### A. Triggers

| Capability | Status | Implementation Details & Evidence |
|---|---|---|
| Manual Execution | **Fully Implemented** | Triggered via `POST /runs` or visual `WorkflowTestPanel.tsx:71-74`. Supports plain message text or raw JSON payload. |
| Schedule & Cron | **Fully Implemented** | [dispatch.py:123-179](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/dispatch.py#L123-L179) executes `run_due_schedules` with atomic transaction claims and `last_fired_at` stamps. |
| One-Time Execution (`run_at`) | **Fully Implemented** | Evaluated in `is_due`. Once executed, trigger is disabled (`enabled=False`) and stamped with `one_time_run_id` ([dispatch.py:158-164](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/dispatch.py#L158-L164)). |
| Webhook / API Triggers | **Fully Implemented** | Inbound endpoint `/triggers/webhooks/{key}` verifies HMAC signatures if `signed=True`, runs rate-limiting, and passes payload to `dispatch_trigger`. |
| Integration Events | **Fully Implemented** | Registered in `registry.py` under `integration_event` (sharing factory with `app_event`); listens on channel gateways. |
| Channel-Originated Events | **Fully Implemented** | `dispatch_message` in [dispatch.py:83-120](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/dispatch.py#L83-L120) attaches inbound Telegram/Email messages to persisted `Thread` rows using `ch:<conversation_key>`. |

### B. Control Flow

| Capability | Status | Implementation Details & Evidence |
|---|---|---|
| Conditions & Branching | **Fully Implemented** | `router` nodes evaluate Python expressions against state dictionary ([flow.py:65-92](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L65-L92)). Outgoing edges support `branches` maps. |
| Multiple Branches (Parallel) | **Fully Implemented** | With `multi: true`, `make_router_path` returns a list of target node IDs; LangGraph executes branches concurrently in a single superstep. |
| Loops & Bounded Iteration | **Fully Implemented** | `loop` node increments `_loop_count` and compares against `max_iter` ([flow.py:171-193](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L171-L193)). `allows_cycle=True` allows DFS validator bypass. |
| Parallel Fanout (Map) | **Fully Implemented** | `parallel_fanout` dispatches LangGraph `Send(child, item)` per element in array ([flow.py:196-225](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L196-L225)). |
| Join / Merge | **Fully Implemented** | `join` node aggregates state via `concat`, `first`, `last`, `merge`, or `sort_by_index` ([flow.py:283-330](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/flow.py#L283-L330)). |
| Delay / Wait | **Not Supported** | No dedicated timer/sleep node. Wait behavior is achieved only via scheduling cron triggers or HITL pauses. |
| Human Approval (HITL) | **Fully Implemented** | `human_input` pauses execution using LangGraph `interrupt()` ([data.py:103-106](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L103-L106)); resumes via `POST /runs/{id}/resume`. |
| Retry & Failure Paths | **Partially Implemented** | Per-item fanout isolation via `resilient_fanout_child` (`isolate=True`). General graph node retries rely on per-tool/per-model client retries. |
| Termination / End | **Fully Implemented** | `end` nodes wired directly to `langgraph.graph.END`. Terminal DFS validation enforces that every branch reaches `END`. |

### C. Data Processing

| Capability | Status | Implementation Details & Evidence |
|---|---|---|
| Input / Output Mapping | **Partially Implemented** | Nodes accept `input_key` and write to `output_key`. However, data mapping requires typing raw keys rather than a visual link interface. |
| Workflow Variables & State | **Fully Implemented** | Defined in `definition.state` ([state.py:21-70](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/state.py#L21-L70)). Canvas builder auto-injects detected node output keys. |
| JSON Transformation | **Fully Implemented** | `transform` node supports both `jmespath` and compiled `jq` engines ([data.py:25-78](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L25-L78)). |
| Expression Evaluation | **Fully Implemented** | Sandboxed parser in [expressions.py:1-68](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/expressions.py#L1-L68) evaluates state paths, boolean comparisons, and null checks without using `eval()`. |
| Schema Validation | **Fully Implemented** | Full JSON Schema draft-07 validation via `jsonschema` in [contracts.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/schemas/contracts.py). |
| Secret Redaction | **Fully Implemented** | Frontend `redactSensitive` ([WorkflowTestPanel.tsx:48-68](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/WorkflowTestPanel.tsx#L48-L68)) and backend `_client_error` prevent credential leaks. |

### D. Execution & Integration

| Capability | Status | Implementation Details & Evidence |
|---|---|---|
| Agent Invocation | **Fully Implemented** | Embedded `agent` compiles to an inner agent subgraph with middleware, prompt formatting, and attached tools. |
| Multi-Agent Delegation | **Fully Implemented** | `deep_agent` supervises specialist agents connected via `"subagents"` handles ([compiler.py:89-109](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/compiler.py#L89-L109)). |
| Tool Execution | **Fully Implemented** | `tool_call` executes registered Python, REST, Code, or SQL tools through `ToolPolicyService`. |
| MCP Tools | **Fully Implemented** | Tools materialized from active `McpClient` connections are registered in `tool_registry` and exposed to agents/tool nodes. |
| REST / Webhook Integration | **Fully Implemented** | `webhook_out` supports dynamic URL templating `{{state.*}}`, header injection, and SSRF validation. |
| Subworkflow Execution | **Fully Implemented** | `subworkflow` node compiles nested workflow definitions with cycle guards and optional I/O key isolation. |

---

## E. Visual Workflow Designer & UX Audit

### 1. Canvas Interactions
- **Node Addition & Palette:** The left palette groups nodes by category (Flow, Agents, Tools, Integrations, Knowledge). Nodes can be dragged onto the canvas or clicked to spawn.
- **Node Duplication & Clipboard:** Full keyboard shortcut support in [workflows.tsx:357-402](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/workflows.tsx#L357-L402) for `Ctrl+C`, `Ctrl+V`, `Ctrl+D`, `Ctrl+Z` (undo), and `Ctrl+Y` / `Ctrl+Shift+Z` (redo).
- **Auto-Snapshots:** History snapshots are pushed on node deletion, pasting, and edge disconnection.
- **Handle ID Dropping (Bug):** In [ForgeNode.tsx:66-70](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ForgeNode.tsx#L66-L70):
  ```tsx
  <Handle
    type="target"
    position={Position.Left}
    id={inputs.length === 1 ? undefined : inputs[0]?.id}
    ...
  ```
  When a node has exactly one input or output port (the case for 18 of the 23 node types), React Flow renders the handle without an `id`. Consequently, edges created between nodes carry `sourceHandle: null` and `targetHandle: null`. This renders the backend port type validation ([validation.py:194-196](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/validation.py#L194-L196)) ineffective, as port names cannot be matched.

### 2. Configuration & Inspector Forms
- **Dynamic Field Rendering:** [ConfigForm.tsx](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ConfigForm.tsx) renders fields dynamically based on `FieldSpec` arrays (text, select, model picker, multi-select chips, toggle, textarea).
- **Router Edge Normalization:** Visual router edges connected to downstream nodes are synchronized with `config.cases` in [workflows.tsx:444-460](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/workflows.tsx#L444-L460) via handles named `case:<label>`.
- **State Key Suggestions:** The Router configuration form inspects upstream nodes in real-time ([workflows.tsx:1331-1355](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/workflows.tsx#L1331-L1355)) using `stateWriters(nodes)` and displays a datalist of routable state keys, flagging an inline warning if no upstream node writes a routing variable.

### 3. Usability Friction Points for Non-Technical Users
1. **Lack of Visual Output Mapping:** Connecting Node A to Node B does not automatically pipe Node A's output into Node B's parameters. The user must manually inspect Node A's `output_key` (e.g. `data` or `tool_result`) and configure Node B with `{{state.data}}` or a JMESPath query.
2. **Schema Terminology Exposure:** Prompts, system schemas, and technical terms like `jmespath`, `RRF`, `BM25`, and `MMR Lambda` are displayed directly to the user without high-level low-code abstractions or simple toggle modes.
3. **No Canvas Edge Data Labels:** Edges between deterministic nodes are unlabelled lines. Unless an edge is connected to a Router case, the user cannot see which state keys are flowing along the path.

---

## F. Execution Engine & LangGraph Runtime Findings

### 1. Compilation
- **Schema-Agnostic Compilation:** [compiler.py:81-188](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/compiler.py#L81-L188) builds the `StateGraph` without re-validating structural rules, trusting [validation.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/validation.py).
- **Automatic State Declaration:** LangGraph raises a runtime exception if a node writes to a channel not declared in `StateGraph(state_schema)`. [graph.ts:102-132](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/lib/graph.ts#L102-L132) prevents this by inspecting all nodes for `output_key`, `route_key`, and `item_key`, synthesizing required state keys with appropriate reducers (`add` for lists, `last` for scalars).
- **Subagent Folding:** Specialists connected to a `deep_agent` via the `subagents` handle are folded directly into the supervisor agent's configuration dictionary ([compiler.py:93-109](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/engine/compiler.py#L93-L109)) and omitted as standalone graph nodes.

### 2. Execution & Detached Streaming
- **Detached Task Execution:** In [runs.py:237-253](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L237-L253), `run_streams.ensure` starts `_drive` as a decoupled `asyncio.create_task`. Client disconnects only terminate the SSE subscriber loop; the execution runs to completion, ensuring side-effects and traces are never half-committed.
- **Replay Buffer:** `_RunBroker` retains the latest 100 SSE frames in a memory buffer ([runs.py:170-224](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L170-L224)). Reconnecting clients passing `Last-Event-ID` resume frame streaming without missing node transitions.
- **Recursion Ceiling Scaling:** In [runs.py:408-424](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L408-L424), `_recursion_limit` computes the LangGraph superstep budget dynamically:
  $$\text{budget} = \max(\text{settings.graph\_recursion\_limit}, (N + 1) \times 2 + \sum \text{loop\_iters} \times 3 + 10)$$
  This prevents `GraphRecursionError` crashes on legitimate bounded loop executions.

### 3. Cancellation & Concurrency
- **Cross-Worker Cancellation Watcher:** [runs.py:91-117](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L91-L117) spawns `_watch_database` per active run. If another API process sets `Run.status = 'canceled'`, the watcher interrupts in-flight asyncio tasks even if blocked on external network requests.
- **Thread Concurrency Lock:** [runs.py:679-681](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/runs.py#L679-L681) serializes execution using `thread_locks.acquire_cm(thread.lg_thread_id)`, preventing concurrent messages from corrupting checkpointer turn history.

---

## G. Security & Reliability Findings

### 1. Tool Execution Gateway
- **Centralized Enforcement:** Both deterministic and agentic tool invocations route through `ToolPolicyService.evaluate_execution(...)` ([tool_policy.py:187-340](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/tool_policy.py#L187-L340)).
- **Verification Gates:**
  1. Tool must exist and be `active = True`.
  2. Caller must be an authorized subagent or workflow.
  3. Action must not violate static role entitlements.
  4. If the tool is designated `critical_risk` or mutating, `requires_approval = True` halts execution until approved.

### 2. SSRF Protection
- **Outbound HTTP Nodes:** Both `webhook_out` ([data.py:165](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/nodes/data.py#L165)) and `app_event` triggers ([dispatch.py:232](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/dispatch.py#L232)) pass requests through [ssrf.py:guarded_request](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/util/ssrf.py). This strictly blocks loopback addresses (`127.0.0.1`), link-local metadata endpoints (`169.254.169.254`), and private RFC 1918 subnets unless explicitly allowlisted in `EgressPolicy`.

### 3. Concurrency & SQLite Integrity
- **Database Locks:** SQLite WAL mode with 30s busy timeouts prevents disk corruption.
- **Atomic Schedule Claims:** In [dispatch.py:138-165](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/dispatch.py#L138-L165), schedule triggers are fetched and stamped with `last_fired_at` inside an atomic transaction before dispatching workers, eliminating race-condition double firing.

---

## H. Automation Manager Integration & Synchronization

### 1. Conversational Planning & Synthesis
[AutomationManagerService](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/automation_manager.py) provides end-to-end natural language workflow authoring:
1. **Capability Discovery:** `discover_capabilities` ([lines 103-160](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/automation_manager.py#L103-L160)) sanitizes project tools, models, and agents, excluding credentials and secrets.
2. **Schema-Compliant Graph Generation:** Workflows are generated conforming strictly to Alberto's node registry.
3. **Bounded Self-Correction:** If the generated graph fails validation, `self_correct_workflow` ([lines 447-562](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/automation_manager.py#L447-L562)) performs up to 3 surgical repair passes (auto-inserting missing start/end nodes, reconnecting orphan edges, injecting undeclared state keys, adding fallback branch conditions).
4. **Automated Canvas Layout:** `compute_canvas` ([lines 372-445](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/automation_manager.py#L372-L445)) computes coordinates for React Flow, arranging triggers, logic, agents, tools, and terminal nodes into clear visual columns.

### 2. Synchronization Integrity
- **Optimistic Concurrency:** [automation_manager.py:585-595](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/automation_manager.py#L585-L595) verifies `expected_revision == auth_session.revision`, blocking concurrent conversational modifications from overwriting manual visual edits.
- **Safe Dry-Run Testing:** Conversational dry-runs execute graphs with mocked tool calls, validating compilation and topology without triggering destructive side effects.

---

## I. Test Coverage Audit

Alberto features extensive test infrastructure: **119 backend test files** and **12 E2E test suites**.

| Capability Area | Backend Test File | UI Test File | Playwright E2E Test | Failure / Edge Case Test | Coverage Assessment |
|---|---|---|---|---|---|
| Workflow Graph Compilation | `test_engine.py` | `ForgeNode.test.tsx` | `workflow-execution.spec.ts` | `test_validation.py` | **Comprehensive** |
| Canvas <-> Executable Sync | `test_workflow_graph_sync.py` | None | `workflow-execution.spec.ts` | `test_revision_safe_canvas_sync.py` | **Adequate** |
| HITL Interrupt & Resume | `test_channels_hitl.py` | None | `workflow-hitl-cancel.spec.ts` | `test_tracer_interrupt.py` | **Comprehensive** |
| In-Flight Cancellation | `test_cancellation_completion_race.py` | None | `workflow-hitl-cancel.spec.ts` | `test_run_deadline_enforcement.py` | **Comprehensive** |
| Schedule & Cron Triggering | `test_triggers.py` | None | `scheduler-execution.spec.ts` | `test_crash_safe_scheduling.py` | **Comprehensive** |
| SSE Streaming & Reconnect | `test_sse_reconnect.py` | None | `workflow-execution.spec.ts` | `test_sse_broker_bounded_buffer.py` | **Comprehensive** |
| Tool Policy Enforcement | `test_tool_policy_agent_enforcement.py` | None | `multi-agent-tool-lifecycle.spec.ts` | `test_runtime_tool_authorization.py` | **Comprehensive** |
| Parallel Fanout & Join | `test_advanced_nodes.py` | None | None | `test_body_template_loop.py` | **Adequate (Missing E2E)** |
| Subworkflow Recursion | `test_subworkflow.py` | None | None | `test_subworkflow.py:test_cycle` | **Backend Only** |
| Conversational Automation | `test_automation_manager.py` | None | `conversational-automation.spec.ts` | `test_durable_repair_protection.py` | **Comprehensive** |

### Test Gaps
1. **No E2E Test for Parallel Fanout / Join:** While `parallel_fanout` has unit tests in `test_advanced_nodes.py`, there is no Playwright test exercising visual fanout configuration and live execution in the browser.
2. **Subworkflow E2E Gap:** Visual configuration of subworkflows and child execution streaming is tested only at the Python unit level.

---

## J. Low-Code Platform Maturity Assessment

Alberto's Low-Code Workflow Engine is assessed across 8 foundational dimensions:

| Dimension | Classification | Concrete Evidence & Findings |
|---|---|---|
| **1. Usability** | **Adequate** | Visual React Flow canvas, full keyboard shortcuts, and node inspector forms work reliably. However, non-technical users struggle with manual JMESPath expressions and state key typing for inter-node data mapping. |
| **2. Expressiveness** | **Strong** | Supports deterministic routing, bounded loops, parallel fanout, subagent supervision, RAG retrieval, structured LLM extraction, and outbound webhooks without writing custom Python code. |
| **3. Composability** | **Strong** | Standardized `NodeSpec` registry, reusable `subworkflow` nodes, and explicit specialist agent folding allow components to be combined cleanly. |
| **4. Predictability** | **Strong** | Sandboxed AST expression evaluation, strict structural DFS validation before execution, and immutable run traces prevent unpredictable side effects. |
| **5. Reliability** | **Strong** | Detached background executors (`_drive`), thread-level concurrency locks, SQLite crash-safe scheduling claims, and cooperative cross-worker cancellation watchers ensure solid operational stability. |
| **6. Extensibility** | **Adequate** | Adding a node requires registering in `registry.py`, creating a factory in `nodes/`, adding a JSON schema in `schemas/`, and registering an inspector in `workflows.tsx`. While straightforward, the dual schema directories introduce maintenance overhead. |
| **7. Performance** | **Strong** | Deterministic nodes execute instantly without LLM latency or token cost. SSE streaming tokenizes LLM chunks in real-time, and parallel fanout runs concurrent branches in a single superstep. |
| **8. Security** | **Strong** | Universal `ToolPolicyService` gateway, SSRF egress guards on all HTTP nodes, tenant RLS scoping, and automatic sensitive argument redaction in traces and execution panels. |

---

## K. Prioritized Improvement Backlog

### P0 — Critical (Immediate Stability & Integrity Fixes)

#### 1. Fix Knowledge Graph Node Type Sync
- **Problem:** `_sync_knowledge_graph` in [workflows.py:186](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/workflows.py#L186) checks `if n.get("type") == "tool"`, but the registered node type is `"tool_call"`.
- **User Impact:** Standalone tool nodes are never linked to workflows in the LadybugDB Knowledge Graph, breaking conversational Butler tool discovery.
- **Root Cause:** Node type string mismatch between `registry.py` (`tool_call`) and `workflows.py` (`tool`).
- **Relevant Source Files:** [backend/alberto/services/workflows.py:183-188](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/services/workflows.py#L183-L188)
- **Proposed Solution:** Update condition to `if n.get("type") in ("tool", "tool_call"):`.
- **Tests Required:** `tests/backend/test_engine_knowledge_regressions.py`.

#### 2. Restore Handle IDs on Single-Port Nodes for Typed Port Connections
- **Problem:** In [ForgeNode.tsx:66-70](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ForgeNode.tsx#L66-L70), handles omit `id` when port count is 1, causing React Flow edges to omit `sourceHandle` / `targetHandle`.
- **User Impact:** Typed port compatibility validation (`io_compatible`) is bypassed in production.
- **Root Cause:** Ternary `id={inputs.length === 1 ? undefined : inputs[0]?.id}` deliberately omitted the handle ID.
- **Relevant Source Files:** [frontend/components/canvas/ForgeNode.tsx:66-79](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ForgeNode.tsx#L66-L79)
- **Proposed Solution:** Always set `id={inputs[0]?.id || "in"}` and `id={outputs[0]?.id || "out"}`.
- **Tests Required:** `tests/e2e/workflows/workflow-execution.spec.ts`.

---

### P1 — High (Core Functionality & Usability Gaps)

#### 3. Eliminate Redundant Schema Directory
- **Problem:** Two identical directories exist: `backend/schemas/alberto/nodes/` and `backend/schemas/forge/nodes/` (21 duplicate files each).
- **User Impact:** Developer confusion; schema changes in one directory may fail to reflect in the active validator.
- **Root Cause:** Uncleaned legacy migration artifact.
- **Relevant Source Files:** [backend/alberto/schemas/contracts.py](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/backend/alberto/schemas/contracts.py)
- **Proposed Solution:** Consolidate onto a single authoritative schema directory and remove the duplicate.
- **Tests Required:** `tests/backend/test_validation.py`.

#### 4. Visual Data-Flow Token Picker
- **Problem:** Users must manually type `{{state.my_key}}` or JMESPath expressions to pass data between nodes.
- **User Impact:** High barrier to entry for non-technical users.
- **Root Cause:** Inspector inputs are plain text fields without an upstream variable picker.
- **Relevant Source Files:** [frontend/components/canvas/ConfigForm.tsx](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ConfigForm.tsx)
- **Proposed Solution:** Implement an inline variable pill picker dropdown on all expression and template fields listing outputs of all topologically upstream nodes.
- **Tests Required:** Playwright E2E visual authoring test.

---

### P2 — Medium (Low-Code Usability & Monitoring Enhancements)

#### 5. Add Playwright E2E Coverage for Parallel Fanout and Join
- **Problem:** Parallel fanout and join nodes have unit test coverage but lack Playwright E2E test verification.
- **User Impact:** Risk of visual regression on parallel orchestration workflows.
- **Relevant Source Files:** `tests/e2e/workflows/workflow-execution.spec.ts`
- **Proposed Solution:** Add an E2E test executing a fanout map over a 3-element list with join aggregation.
- **Tests Required:** New test in `tests/e2e/workflows/workflow-execution.spec.ts`.

#### 6. Canvas Edge Data Badges
- **Problem:** Edges between deterministic nodes do not indicate which state keys or data contracts flow across them.
- **User Impact:** Complex workflows are difficult to read and troubleshoot visually.
- **Relevant Source Files:** [frontend/components/canvas/EdgeOverlay.tsx](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/EdgeOverlay.tsx)
- **Proposed Solution:** Render an optional data badge on edges showing the active state key (e.g. `intent`, `webhook_result`).

---

### P3 — Optional (Advanced Orchestration Capabilities)

#### 7. Visual Delay / Timer Node
- **Problem:** Workflows cannot pause for a specified duration (e.g. "Wait 2 hours then send email") without external cron setups.
- **User Impact:** Limited delayed-action marketing and reminder workflows.
- **Proposed Solution:** Implement a `delay` node backed by one-time schedule triggers.

---

## L. Recommended Evolution Plan

```
  Phase 1: Integrity & Fixes (P0)
  ├── Fix Knowledge Graph tool_call sync
  ├── Restore handle IDs on ForgeNode ports
  └── Remove duplicate schema directory

  Phase 2: Data Flow & Usability (P1)
  ├── Implement Visual Upstream Variable Picker
  └── Add Edge Data Flow Badges

  Phase 3: Test Suite Expansion (P2)
  ├── Add E2E tests for Parallel Fanout & Join
  └── Add E2E tests for Subworkflow nesting

  Phase 4: Advanced Orchestration (P3)
  └── Implement Delay/Timer node using durable scheduler triggers
```

1. **Step 1: Clean Contract & Handle Integrity (Phase 1)**
   - Correct the `tool_call` type check in `_sync_knowledge_graph`.
   - Restore explicit handle IDs on `ForgeNode.tsx` to enable true port-level connection validation.
   - Clean up the duplicate `schemas/alberto/nodes/` directory.
   - *Verification:* Run `tests/backend/test_validation.py` and `tests/backend/test_engine_knowledge_regressions.py`.

2. **Step 2: Low-Code Data Flow UX (Phase 2)**
   - Add upstream variable suggestions to `ConfigForm.tsx` so non-technical users can select previous node outputs with a single click.
   - *Verification:* Playwright E2E workflow authoring test.

3. **Step 3: Orchestration E2E Hardening (Phase 3)**
   - Add dedicated Playwright test covering parallel fanout execution and join output visualization in `WorkflowTestPanel.tsx`.
   - *Verification:* `npx playwright test tests/e2e/workflows/`.
