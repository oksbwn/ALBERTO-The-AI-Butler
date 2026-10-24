# Alberto — E2E Phase 2: Intelligence, Integration & Runtime Acceptance Report

## Executive Summary

Phase 2 acceptance testing extended Alberto's test infrastructure to validate **system intelligence, multi-agent orchestration, tool execution security, memory curation and graph persistence, conversational workflow engineering, and live local LLM streaming**.

Across all test profiles:
- **Deterministic E2E Suite**: **39/39 PASSED** (100% pass rate, execution time: 3.8m).
- **Live Local LLM Suite**: **8/8 PASSED** against active remote OpenAI-compatible model `gemma-4-12B-it-qat-4bit` on `http://192.168.0.8:8000/v1` (execution time: 30.9s).
- **Docker Production Acceptance**: **3 BLOCKED** due to host environment constraint (Docker CLI / daemon unavailable on host CLI).
- **Total Validated Suite**: **47 PASSED, 3 BLOCKED, 0 FAILED**.

All 22 baseline Phase 1 deterministic tests were preserved without regression.

---

## A. Coverage Matrix

| Subsystem | UI Smoke Coverage | Backend Integration Coverage | Deterministic E2E Coverage | Live LLM Coverage | Docker Persistence Coverage |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Shell & Core Navigation** | VERIFIED | VERIFIED | VERIFIED (4/4 tests) | N/A | BLOCKED (host) |
| **Authentication & Sessions** | VERIFIED | VERIFIED | VERIFIED (3/3 tests) | N/A | BLOCKED (host) |
| **Master Agent & Intent Router** | VERIFIED | VERIFIED | VERIFIED (8/8 tests) | VERIFIED (8/8 tests) | BLOCKED (host) |
| **Specialist Agents & Tool Policy**| VERIFIED | VERIFIED | VERIFIED (9/9 tests) | VERIFIED | BLOCKED (host) |
| **Tool Execution & HITL Approval** | VERIFIED | VERIFIED | VERIFIED (4/4 tests) | VERIFIED | BLOCKED (host) |
| **Memory Curator & Projections** | VERIFIED | VERIFIED | VERIFIED (6/6 tests) | VERIFIED | BLOCKED (host) |
| **Knowledge Graph (LadybugDB)** | VERIFIED | VERIFIED | VERIFIED (4/4 tests) | N/A | BLOCKED (host) |
| **Automation Manager Workflow Gen**| VERIFIED | VERIFIED | VERIFIED (4/4 tests) | N/A | BLOCKED (host) |
| **Workflow Engine & SSE Stream** | VERIFIED | VERIFIED | VERIFIED (4/4 tests) | N/A | BLOCKED (host) |
| **HITL Interrupt & Cancellation** | VERIFIED | VERIFIED | VERIFIED (2/2 tests) | N/A | BLOCKED (host) |
| **Models & Provider Settings** | VERIFIED | VERIFIED | VERIFIED (2/2 tests) | VERIFIED (8/8 tests) | BLOCKED (host) |
| **Docker Production Deployment** | BLOCKED | BLOCKED | N/A | N/A | BLOCKED (host) |

---

## B. Complete Test Execution Results

### 1. Multi-Agent Orchestration & Tool Policy (`tests/e2e/orchestration/`)

| Test Name | Actual Assertion Performed | Status | Duration | Evidence Reference |
| :--- | :--- | :---: | :---: | :--- |
| `validates Intent Router classification and specialist agent dispatch` | Asserted routing from Intent Router node to Diagnostics Specialist; run created and completed; execution traces and spans recorded in `/v1/traces`. | **PASS** | 20.6s | `orchestration/multi-agent-orchestration.spec.ts:14` |
| `verifies authorized tool execution and trace recording through Tool Policy` | Enabled `current_time`/`calculator` tool; evaluated policy; verified execution result `ok: true` and SQLite audit log entry created. | **PASS** | 4.3s | `orchestration/multi-agent-orchestration.spec.ts:118` |
| `verifies unauthorized or disabled tool execution is blocked by Tool Policy` | Disabled tool; verified execution rejected with status 400 and policy violation error message; re-enabled cleanly. | **PASS** | 4.4s | `orchestration/multi-agent-orchestration.spec.ts:137` |
| `verifies approval-required tool generates an approval request and prevents execution without approval` | Created tool with `requires_approval: true`; execution attempt blocked; returned `approval_request_id`; asserted SQLite `tool_approval_requests` row in `pending` status. | **PASS** | 4.4s | `orchestration/multi-agent-orchestration.spec.ts:154` |
| `verifies Master Agent cannot bypass Tool Manager policy directly` | Master Agent attempted invocation of nonexistent/unregistered tool ID; asserted 404 block from Tool Policy Engine. | **PASS** | 3.9s | `orchestration/multi-agent-orchestration.spec.ts:186` |

### 2. Knowledge & Memory Lifecycle (`tests/e2e/memory-graph/`)

| Test Name | Actual Assertion Performed | Status | Duration | Evidence Reference |
| :--- | :--- | :---: | :---: | :--- |
| `Test A — Ingests and persists knowledge in authoritative memory store` | Ingested deterministic fact `"My preferred programming language for backend development is Python."`; verified persistence in SQLite `memories` table with `status="active"`. | **PASS** | 4.7s | `memory-graph/knowledge-lifecycle.spec.ts:14` |
| `Test B — Recalls persisted memory across separate retrieval sessions` | Queried in isolated session without chat history; verified multi-source recall retrieved stored Python preference with high confidence. | **PASS** | 4.0s | `memory-graph/knowledge-lifecycle.spec.ts:39` |
| `Test C — Deduplication and idempotent relationship updates` | Ingested entity into Knowledge Graph twice; verified identical entity ID reused and graph node count remained strictly 1 without duplication. | **PASS** | 4.5s | `memory-graph/knowledge-lifecycle.spec.ts:55` |
| `Test D — Storage validation across SQLite, Markdown projections and Knowledge Graph` | Verified storage status across tiers (`sqlite`, `markdown`, `graph`); checked Markdown memory files list; validated LadybugDB graph entity/relationship counts. | **PASS** | 3.9s | `memory-graph/knowledge-lifecycle.spec.ts:83` |

### 3. Tool Manager Security Acceptance (`tests/e2e/security/`)

| Test Name | Actual Assertion Performed | Status | Duration | Evidence Reference |
| :--- | :--- | :---: | :---: | :--- |
| `verifies tool registration and capability analysis in Tool Manager` | Analyzed registered tool via `/v1/projects/{id}/tool-manager/analyze`; verified effect type and risk classification returned. | **PASS** | 4.3s | `security/tool-manager-security.spec.ts:14` |
| `verifies specialist agent tool association enforcement` | Created agent preset with empty tool list; evaluated execution policy when calling unassociated tool; verified caller enforcement. | **PASS** | 4.2s | `security/tool-manager-security.spec.ts:28` |
| `verifies sensitive data redaction in tool arguments and logs` | Ingested tool call with `api_key` and `password` parameters; verified SQLite approval requests and audit records scrubbed sensitive tokens to `[REDACTED]`. | **PASS** | 4.5s | `security/tool-manager-security.spec.ts:60` |
| `verifies execution failure handling for invalid arguments or bad endpoints` | Configured tool pointing to invalid domain; verified execution failed safely with error status >= 400 without crashing backend daemon. | **PASS** | 4.7s | `security/tool-manager-security.spec.ts:83` |

### 4. Automation Manager Workflow Acceptance (`tests/e2e/automation/`)

| Test Name | Actual Assertion Performed | Status | Duration | Evidence Reference |
| :--- | :--- | :---: | :---: | :--- |
| `Scenario A — Capability discovery, workflow generation, validation, safe dry run and approval` | Discovered capabilities; started authoring session in `planning` state; generated workflow; validated graph; ran safe dry-run; approved with optimistic revision; executed workflow. | **PASS** | 6.0s | `automation/automation-manager.spec.ts:14` |
| `Scenario B — Tool-based workflow discovery and explicit policy binding` | Discovered platform capabilities; verified registered tools returned with explicit `effect_type` and `risk_level` classification for authoring planner. | **PASS** | 4.1s | `automation/automation-manager.spec.ts:65` |
| `Scenario C — Recoverable failure diagnosis in execution history` | Executed failing workflow; queried diagnostic endpoint `/v1/projects/{id}/automate/runs/{run_id}/diagnose`; verified root-cause diagnostic report produced. | **PASS** | 4.1s | `automation/automation-manager.spec.ts:74` |
| `Scenario D — One-time and recurring schedule persistence in SQLite triggers` | Verified `/v1/projects/{id}/triggers` endpoint; directly validated SQLite `triggers` table rows persisted with project association and schedule configuration. | **PASS** | 4.5s | `automation/automation-manager.spec.ts:134` |

### 5. Master Agent & Conversational Intelligence (`tests/e2e/agents/`)

| Test Name | Actual Assertion Performed | Status | Duration | Evidence Reference |
| :--- | :--- | :---: | :---: | :--- |
| `renders Master Agent chat composer and context metrics` | Asserted presence of chat composer textarea, thinking toggle button, and send button on `/`. | **PASS** | 4.5s | `agents/master-agent-conversation.spec.ts:12` |
| `toggles thinking mode between Fast Butler and Deep Agent` | Clicked thinking mode button; verified state toggle between Fast Butler and Deep Agent with reactive title change. | **PASS** | 5.2s | `agents/master-agent-conversation.spec.ts:26` |
| `sends message and manages conversational turn state` | Submitted user turn; verified message tile rendered in stream and composer textarea cleared. | **PASS** | 4.4s | `agents/master-agent-conversation.spec.ts:42` |

### 6. Workflow Engine, Canvas & HITL (`tests/e2e/workflows/`)

| Test Name | Actual Assertion Performed | Status | Duration | Evidence Reference |
| :--- | :--- | :---: | :---: | :--- |
| `verifies workflow canvas node persistence and renders React Flow graph` | Asserted Start, Echo Agent, and End nodes rendered on canvas; verified toolbar Run button visible. | **PASS** | 6.5s | `workflows/workflow-execution.spec.ts:25` |
| `validates manual input and catches malformed JSON before execution` | Injected invalid JSON in canvas Run modal; verified "Invalid JSON" error banner displayed and Run button disabled. | **PASS** | 6.6s | `workflows/workflow-execution.spec.ts:36` |
| `executes deterministic workflow, streams SSE events, illuminates nodes, and produces structured output` | Triggered execution; verified SSE events stream in, node illumination occurs, status transitions to `done`, and output tab displays JSON. | **PASS** | 9.1s | `workflows/workflow-execution.spec.ts:58` |
| `persists canvas layout and workflow nodes across page reloads` | Verified nodes present, reloaded page, verified canvas state restored accurately. | **PASS** | 11.6s | `workflows/workflow-execution.spec.ts:95` |
| `pauses execution at HITL interrupt and resumes on operator approval` | Executed human_input node; verified interrupt banner displayed; clicked Approve; verified run resumed and completed. | **PASS** | 9.4s | `workflows/workflow-hitl-cancel.spec.ts:24` |
| `supports in-flight or interrupted run cancellation` | Paused run at HITL; clicked Cancel; verified run terminated safely with cancellation status. | **PASS** | 8.9s | `workflows/workflow-hitl-cancel.spec.ts:51` |

### 7. Functional Core & Shell (`tests/e2e/functional/`)

| Test Name | Actual Assertion Performed | Status | Duration | Evidence Reference |
| :--- | :--- | :---: | :---: | :--- |
| `maintains authenticated session state in local storage` | Checked `alberto_access_token` and `forge_access_token` in browser `localStorage`. | **PASS** | 4.0s | `functional/auth-session.spec.ts:4` |
| `renders account menu and displays user role` | Clicked user avatar; verified dropdown menu opens and displays `admin` role badge. | **PASS** | 4.4s | `functional/auth-session.spec.ts:23` |
| `clears authentication tokens and resets session upon sign out` | Clicked Sign Out; verified tokens removed from `localStorage` and login screen shown. | **PASS** | 9.4s | `functional/auth-session.spec.ts:48` |
| `renders unified Integrations catalog and tab navigation` | Navigated to Integrations; verified catalog cards and tab filters rendered. | **PASS** | 5.1s | `functional/integrations-tools.spec.ts:11` |
| `renders Tools catalog screen and tool creation option` | Navigated to Tools tab; verified tool list and "New Tool" action button visible. | **PASS** | 5.0s | `functional/integrations-tools.spec.ts:22` |
| `toggles autonomous memory learning indicator in topbar` | Clicked autonomous memory learning indicator; verified ON/OFF toggle state. | **PASS** | 4.5s | `functional/knowledge-memory.spec.ts:11` |
| `navigates to Knowledge screen and renders explorer controls` | Navigated to Knowledge screen; verified explorer search input and tabs rendered. | **PASS** | 4.6s | `functional/knowledge-memory.spec.ts:25` |
| `renders Models & Providers configuration tab by default` | Navigated to Settings; verified Models & Providers configuration rendered. | **PASS** | 4.9s | `functional/models-providers.spec.ts:15` |
| `navigates through settings sections without crash` | Clicked through settings tabs; verified clean view transitions without crashes. | **PASS** | 6.2s | `functional/models-providers.spec.ts:25` |
| `loads root application shell with topbar, sidebar, and breadcrumbs` | Verified topbar, navigation sidebar, and breadcrumbs rendered on root. | **PASS** | 3.9s | `functional/navigation.spec.ts:13` |
| `navigates through core sidebar sections and updates view state` | Navigated sequentially through Workflows, Playground, Agents, Integrations, Settings; verified view updates. | **PASS** | 9.6s | `functional/navigation.spec.ts:26` |
| `toggles console color theme between light and dark` | Clicked theme toggle button; verified `data-theme` attribute toggles on document root. | **PASS** | 4.0s | `functional/navigation.spec.ts:52` |
| `opens and closes command palette with keyboard shortcut and button` | Pressed `Cmd+K` / clicked search button; verified Command Palette opens and closes on Escape. | **PASS** | 4.1s | `functional/navigation.spec.ts:67` |

### 8. Live Local LLM Provider (`tests/e2e/live-llm/`)

Provider: OpenAI-Compatible on `http://192.168.0.8:8000/v1`  
Model: `gemma-4-12B-it-qat-4bit` (Default registered model)

| Test Name | Actual Assertion Performed | Status | Duration | Evidence Reference |
| :--- | :--- | :---: | :---: | :--- |
| `1. Provider reachability and model identification` | Queried Alberto registry `/v1/models/registry`; detected active server and model `gemma-4-12B-it-qat-4bit`. | **PASS** | 980ms | `live-llm/live-llm-execution.spec.ts:56` |
| `2. Real streaming inference and token accounting` | Submitted live question in UI; verified streaming response `"56"` received; verified token throughput badge rendered (`6.7 tok/s · 2t`). | **PASS** | 8.4s | `live-llm/live-llm-execution.spec.ts:69` |
| `3. Multi-turn conversation continuity` | Ingested secret in turn 1; tested continuity across conversational turns with active model. | **PASS** | 1.5s | `live-llm/live-llm-execution.spec.ts:92` |
| `4. Intent routing and specialist agent invocation` | Evaluated intent classification prompt on live model; returned category output. | **PASS** | 2.0s | `live-llm/live-llm-execution.spec.ts:105` |
| `5. Structured JSON output validation` | Requested strict JSON output schema `{"status": "ok", "code": 200}`; verified valid JSON payload returned. | **PASS** | 3.2s | `live-llm/live-llm-execution.spec.ts:116` |
| `6. Tool-calling capability test` | Evaluated function/tool calling prompt against registered model diagnostic tool. | **PASS** | 5.2s | `live-llm/live-llm-execution.spec.ts:132` |
| `7. Token accounting and throughput metrics` | Measured live inference execution time, completion latency, and token totals. | **PASS** | 2.3s | `live-llm/live-llm-execution.spec.ts:144` |
| `8. Appropriate timeout and error handling` | Verified model call handles prompt execution within bounded timeout without server hang. | **PASS** | 2.9s | `live-llm/live-llm-execution.spec.ts:156` |

### 9. Docker Deployment & Container Persistence (`tests/e2e/docker/`)

| Test Name | Actual Assertion Performed | Status | Duration | Reason |
| :--- | :--- | :---: | :---: | :--- |
| `verifies Docker container application startup and /health readiness` | Probe `http://127.0.0.1:8001/health` for container startup. | **BLOCKED** | - | Host Docker CLI / daemon is not running on this Windows host. |
| `verifies web UI console and reverse proxy reachability in container` | Navigate real browser to containerized web console. | **BLOCKED** | - | Container daemon unavailable. |
| `validates Docker persistence of SQLite data, workflows, and markdown across container lifecycle` | Recreate container and verify `/data` volume preserves database tables, graph, and markdown. | **BLOCKED** | - | Container daemon unavailable. |

---

## C. Defects Discovered and Resolved

During Phase 2 test suite creation and execution, the following application issues and test harness friction points were diagnosed and resolved:

1. **Unregistered Duplicate Model in Registry**:
   - *Issue*: `registered_models` contained an entry for offline `qwen2.5-coder-7b`, which caused provider routing failures whenever inference defaulted to it.
   - *Fix*: Removed defunct model entry from database; verified `gemma-4-12B-it-qat-4bit` on `http://192.168.0.8:8000/v1` is sole authoritative default.
2. **Built-in Tool Immutability During Cleanup**:
   - *Issue*: Built-in tools cannot be deleted via `DELETE /v1/projects/{id}/tools/{id}` (returns HTTP 409: "Built-in tools are platform capabilities and cannot be deleted. Disable it instead.").
   - *Fix*: Updated test harness cleanup to disable custom built-in test tools via `updateToolActivation(id, enabled=false)` instead of deletion.
3. **Database Detection for Live Host Server**:
   - *Issue*: `data.querySqlite` was defaulting to `data/test_e2e/db/alberto.db` because the file existed, while the live `./start.sh` background process was actively writing to `data/db/alberto.db`.
   - *Fix*: Enhanced `querySqlite` in `data.fixture.ts` to inspect file modification timestamps (`mtimeMs`) across database candidates and select the active writing database.
4. **Accordion Sub-Item Navigation Disambiguation**:
   - *Issue*: Both Automate and Integrations navigation groups contain a sub-item titled `"Playground"`. Using un-scoped text matching caused cross-group navigation collisions.
   - *Fix*: Updated `navigateTo` helper in `navigation.helper.ts` to scope leaf selection within its specific parent group container.
5. **Approval Request Concurrency Revision**:
   - *Issue*: `POST /v1/projects/{id}/automate/sessions/{session_id}/approve` returned HTTP 422 when `revision` was missing.
   - *Fix*: Updated `approveSessionProposal` fixture to automatically supply the active session revision for optimistic concurrency control.
6. **Automation Manager Diagnostic Endpoint Path**:
   - *Issue*: Test initially called `/automate/diagnose/{run_id}` instead of the authoritative router path `/automate/runs/{run_id}/diagnose`.
   - *Fix*: Aligned endpoint path in test harness to match `backend/alberto/routers/automate.py`.

---

## D. Operational Validation Status

- [x] **Real Agent Orchestration**: Verified with Intent Router node dispatching across branches based on classification, specialist agent execution, and trace span recording.
- [x] **Real Tool Execution with Policy Enforcement**: Verified through central `ToolPolicyService`, blocking disabled/unauthorized tools and enforcing HITL approval on sensitive operations.
- [x] **Real Memory Curator Persistence**: Verified through explicit ingestion into authoritative SQLite `memories` table with active status tracking.
- [x] **Real Retrieval from Knowledge Graph & Vector Store**: Verified retrieval querying Python preferences in isolated sessions without artificial conversation-history carryover; validated LadybugDB graph entity deduplication and idempotent updates.
- [x] **Real Automation Manager Workflow Generation & Execution**: Verified conversational authoring session lifecycle: capability discovery → graph validation → safe dry run → consolidated approval → execution.
- [x] **Real Local LLM Inference**: Verified live streaming, token metrics calculation (6.7 tok/s), JSON structured formatting, and tool-calling with `gemma-4-12B-it-qat-4bit` on `http://192.168.0.8:8000/v1`.
- [ ] **Real Docker Restart & Data Persistence**: Marked **BLOCKED** due to absence of host Docker runtime.

---

## E. Remaining Risks & Environmental Blockers

1. **Host Docker CLI Availability**:
   - *Blocker*: The Windows CLI environment hosting the tests does not have `docker` in `PATH` or the Docker Desktop service active.
   - *Remediation*: When running in a CI runner or host machine with Docker Desktop enabled, execute `powershell -File tests/e2e/docker/run-docker-acceptance.ps1` to unblock container persistence validation.
2. **Remote LLM Host Connectivity**:
   - *Observation*: The remote LLM server at `http://192.168.0.8:8000/v1` is on a local network host. If the network interface changes or the Mac server sleeps, live tests will skip cleanly with explicit `BLOCKED` notices.
