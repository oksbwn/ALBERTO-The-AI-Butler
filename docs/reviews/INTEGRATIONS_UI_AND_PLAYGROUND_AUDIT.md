# Alberto — Integrations UI & Playground Architecture Audit

**Document Status:** Complete & Verified (Read-Only Audit)  
**Date:** 2026-10-19  
**Scope:** Frontend Integrations, Tools, Auth Providers, MCP Clients, Knowledge Playground, and Proposed Integrations Playground.

---

## 1. Actual Frontend File Map

| File Path | Size / Lines | Primary Purpose | Status |
|---|---|---|---|
| [`frontend/components/screens/integrations.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/integrations.tsx) | 47.8 KB / 1265 lines | Unified Integrations screen (My Integrations, Explore Catalog, Custom/MCP registration, Detail View with Tools, Config, and Diagnostics). | Active (`/integrations`, `/connectors`, `/mcp`) |
| [`frontend/components/screens/tools.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/tools.tsx) | 76.5 KB / 1023 lines | Standalone Tools list, ToolSet sidebar, Tool Builder, and `LiveResponse` tester for REST/Code/SQL tools. | Active (`/tools`, `/tool-builder`) |
| [`frontend/components/screens/auth.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/auth.tsx) | 27.8 KB / 430 lines | Dedicated Auth Providers management (Bearer, API Key, Basic, OAuth2 client-creds/auth-code, CSRF session). | Active (`/auth`) |
| [`frontend/components/screens/mcp.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/mcp.tsx) | 12.0 KB / 195 lines | External MCP server registration and tool capability discovery. | Legacy / Overlapping (routed to `integrations.tsx` in `page.tsx`) |
| [`frontend/components/screens/connectors.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/connectors.tsx) | 35.4 KB / 639 lines | Legacy Connectors screen with catalog grid and install table. | Legacy / Overlapping (routed to `integrations.tsx` in `page.tsx`) |
| [`frontend/components/screens/knowledge-playground.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/knowledge-playground.tsx) | 20.5 KB / 586 lines | Split-panel interactive probe playground for SQLite facts, ChromaDB, Ladybug Graph, and Q&A pairs with live inquiry chat. | Active (`/knowledge-playground`) |
| [`frontend/components/screens/playground.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/playground.tsx) | 25.6 KB / 439 lines | Workflow runtime test harness with SSE execution streaming, node step badges, HITL pause/resume dialog, and token meter. | Active (`/playground`) |
| [`frontend/components/screens/traces.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/traces.tsx) | 32.2 KB / 700 lines | Execution traces, waterfall spans, model turns, tool execution logs, and approval lifecycle tracking. | Active (`/traces`) |
| [`frontend/components/canvas/AgentConfig.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/AgentConfig.tsx) | 29.3 KB / 469 lines | Subagent tool association editor: accordion ToolSets, individual tool selection, and raw MCP server grants. | Active (Subagent / Canvas) |
| [`frontend/components/canvas/WorkflowTestPanel.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/WorkflowTestPanel.tsx) | 16.5 KB / 320 lines | Embedded canvas run drawer with token metering and HITL pause notice. | Active (Workflow Canvas) |
| [`frontend/components/primitives.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx) | 17.6 KB / 318 lines | Core UI components: `TokenMeter`, `StatusPill`, `Toggle`, `Segmented`, `Modal`, `Drawer`, `EmptyState`, `Field`, `Tabs`, `CodeBlock`, `Tile`, `Menu`. | Shared across all screens |
| [`frontend/components/shell.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx) | 51.6 KB / 999 lines | Navigation chrome: Topbar, ProjectSidebar (with resource counts and flyout menus), CommandPalette (`Ctrl+K`), Breadcrumbs. | Application Shell |
| [`frontend/app/globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css) | 19.2 KB / 303 lines | Design system tokens: HSL/OKLCH color palettes, Geist typography, light/dark console theme variables, button styles. | Global Stylesheet |
| [`frontend/lib/data.ts`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/lib/data.ts) | 31.5 KB / 425 lines | `PROJECT_NAV` structure, `NODE_CATALOG`, `MIDDLEWARE_CATALOG`, icon and kind mappings. | Navigation & Catalog Config |
| [`frontend/lib/api.ts`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/lib/api.ts) | 48.0 KB / 1020 lines | Frontend API client for connectors, tools, MCP, tool manager analysis/diagnostics, runs, and SSE streaming. | API Layer |

---

## 2. Existing Navigation Structure

Alberto organizes navigation into structured groups inside `PROJECT_NAV` ([`frontend/lib/data.ts:363-417`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/lib/data.ts#L363-L417)):

```
Home (icon: home)
├── Automate (section)
│   ├── Workflows (/workflows)
│   ├── Agents (/agents)
│   ├── Components (/components)
│   └── Playground (/playground) [Workflow SSE Playground]
├── Knowledge (section)
│   ├── Playground (/knowledge-playground) [Recall Probe + Chat]
│   ├── Documents (/knowledge-docs)
│   ├── Vector Store (/knowledge-vector)
│   ├── Q&A Pairs (/knowledge-qa)
│   ├── Knowledge Graph (/knowledge-graph)
│   └── Long-Term Memory (/knowledge-memory)
├── Integrations (section)
│   ├── Integrations (/integrations) [NEW: Unified IntegrationsScreen]
│   ├── Tools (/tools) [ToolsScreen: REST, Code, SQL, Builtin]
│   ├── Auth Providers (/auth) [AuthProvidersScreen]
│   ├── Triggers (/triggers)
│   └── Channels (/channels)
├── Observability (section)
│   ├── Analytics (/overview)
│   ├── Traces (/traces)
│   ├── Evaluations (/datasets)
│   └── Agent Inbox (/handoff)
└── Settings (/settings)
```

### Route Resolution in [`frontend/app/page.tsx:150-183`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/page.tsx#L150-L183)
- `integrations`, `connectors`, `mcp` all route to `<IntegrationsScreen />`.
- `tools` routes to `<ToolsScreen />`.
- `tool-builder` routes to `<ToolBuilderScreen />`.
- `auth` routes to `<AuthProvidersScreen />`.
- `knowledge-playground` routes to `<KnowledgePlaygroundScreen />`.
- `playground` routes to `<PlaygroundScreen />` (Workflow engine).

---

## 3. Current Integrations UI Feature Inventory

Verified in [`frontend/components/screens/integrations.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/integrations.tsx):

### 3.1 Main Layout & Tabs
- Header with search, category filtering, and primary actions.
- Three top-level tabs:
  1. **My Integrations (`tab === "my"`):** Unified card grid combining installed connectors (`installs`) and standalone MCP clients (`mcpClients`). Displays badge counts (`total_tools`, `enabled_tools`), authentication status (`connected`, `needs_auth`, `error`), and synchronization timestamp.
  2. **Explore Catalog (`tab === "explore"`):** Searchable catalog grid from `api.connectorCatalog()`. Cards show connector category, authentication kind, and installation state.
  3. **Custom & MCP (`tab === "custom"`):** Two configuration cards:
     - Card 1: Remote MCP Server registration modal trigger.
     - Card 2: Custom Connector Manifest JSON editor with live JSON validation (`api.validateConnectorManifest`), credential isolation selection (`shared` vs `per_user`), and submission.

### 3.2 Detail View (`IntegrationDetailView`)
Selecting an item opens a dedicated sub-view with 4 sub-tabs:
1. **Overview:** Protocol type, authentication mechanism, credential scope (`Workspace Shared` vs `Personal connection`), and last synchronization timestamp.
2. **Tools & Capabilities:** List of all tools materialized by the integration.
   - Per-tool activation toggle (`handleToggleActivation`) backed by `api.updateToolActivation` or MCP client disabled tools array.
   - Schema Inspection modal showing raw JSON input schema.
   - Tool Manager Analysis trigger (`runToolAnalysis`) calling `api.toolManagerAnalyze`. Displays classified effect (`read`, `write`, `delete`), risk (`low`, `medium`, `high`, `critical`), and activation recommendation.
   - "Open in Tools" button delegating to standalone `ToolBuilderScreen`.
3. **Configuration:** Read-only endpoint and slug verification.
4. **Diagnostics:** Automated diagnostic report backed by `api.toolManagerDiagnose`. Displays health status, root cause (`auth`, `rate_limit`, `timeout`, `schema_mismatch`, `network`), summary, and recommendations.

### 3.3 State Handling & Edge Cases
- **Loading:** Spinner and animated skeleton state via `loading` flag.
- **Empty States:** Renders `EmptyState` component with guidance when no integrations are installed or catalog search returns zero matches.
- **Error States:** Alert banner for failed API calls, popup timeout errors, or manifest validation failures.
- **OAuth Handling:** Uses popup window with origin-verified `message` event listener (`alberto:oauth_complete`) and bounded 120s fallback poll timer.

---

## 4. Knowledge Playground Comparison & Reusable Components

The **Knowledge Playground** ([`frontend/components/screens/knowledge-playground.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/knowledge-playground.tsx)) provides a model for interactive testing:

### 4.1 Knowledge Playground Architecture
- **Draggable Two-Panel Split Layout:**
  - Left Panel (Explorer/Probe): Source filter toggles (`sqlite_memory`, `ladybug_graph`, `chroma_memory`, `qa_pairs`, `markdown`), search input, and expandable result cards showing similarity scores, provenance, and metadata.
  - Right Panel (Interactive Assistant): Full conversational `<ChatScreen />` instance with pre-populated contextual inquiries ("Can you explain or audit this stored memory record?").
  - Adjustable splitter (`splitPct`) clamping between 20% and 80% with mouse drag listeners.

### 4.2 Workflow Playground Architecture ([`playground.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/playground.tsx))
- **Live SSE Stream Execution:**
  - Token-by-token streaming via `openSSE`.
  - Node step progress indicator pills (`Step[]`).
  - Active tool activity execution cards (`Activity[]`).
  - **HITL Pause & Resume UI:** When an interrupt occurs, renders warning card with explicit decision buttons (`approve` vs `reject`), sending decisions via `api.resumeRun`.
  - Live token meter and cost rollup.

### 4.3 What Can Be Reused for an Integrations Playground
1. **Draggable Two-Panel Splitter (`containerRef`, `isDraggingRef`, `splitPct`):** Excellent UX for placing tool configuration/inputs on the left and live execution/traces/outputs on the right.
2. **`TokenMeter` Primitive ([`primitives.tsx:65-108`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L65-L108)):** Reusable component for visualizing raw vs projected tool output payloads.
3. **`LiveResponse` Pattern from `tools.tsx` ([`tools.tsx:888-970`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/tools.tsx#L888-L970)):** Existing form generator for tool parameters with schema inputs, raw JSON textarea fallback, HTTP latency chips, and output formatters.
4. **HITL Interrupt Banner Pattern from `playground.tsx`:** Standardized UI for displaying pending approval requests with argument inspection and Approve/Reject triggers.

---

## 5. Duplicate or Overlapping Pages

| Page / Component | Overlapping Functionality | Recommended Disposition |
|---|---|---|
| [`connectors.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/connectors.tsx) (`ConnectorsScreen`) | Legacy catalog grid and connector installation table. Redundant with `IntegrationsScreen` tabs 1 and 2. | **Retire / Deprecate**: Retain file temporarily for legacy references, but keep route aliased to `IntegrationsScreen`. |
| [`mcp.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/mcp.tsx) (`McpClientsScreen`) | Standalone MCP client list and tool toggle. Redundant with `IntegrationsScreen` custom tab and unified installed list. | **Retire / Deprecate**: Keep route aliased to `IntegrationsScreen`. |
| [`auth.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/auth.tsx) (`AuthProvidersScreen`) | Standalone auth provider credentials (API Keys, Bearer tokens, CSRF configs). | **Keep Standalone + Cross-link**: High-security credential management; keep in `PROJECT_NAV`, with deep-link from `IntegrationsScreen` config tab. |
| [`tools.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/tools.tsx) (`ToolsScreen` & `ToolBuilderScreen`) | Authoring custom Python/SQL/REST tools, grouping into `ToolSets`, JMESPath projection editing. | **Keep Standalone for Custom Authoring**: IntegrationsScreen manages external connectors and MCP servers; ToolsScreen manages internal custom tools and groupings. |

---

## 6. UI/UX Gap Analysis

### P0 (Critical / Functional Blocker)
- **GAP-01: No Unified MCP Tool Testing:** `ToolService.test` explicitly rejects MCP tools (`Test 'mcp' tools by attaching them to an agent...`). An operator cannot test MCP tools outside of running a full workflow.
- **GAP-02: Direct Test Endpoint Bypasses `ToolPolicyService`:** `POST /projects/{pid}/tools/{tid}/test` directly executes REST/SQL/Code tools without passing through `ToolPolicyService.evaluate_execution`. Destructive actions in tool tests bypass HITL approval gating.

### P1 (High / Operational Gaps)
- **GAP-03: No JSON Schema Form Generator for Complex Objects:** `LiveResponse` in `tools.tsx` handles flat string/number/array fields well, but falls back to a raw JSON textarea for nested object schemas.
- **GAP-04: No In-Context Execution Trace Viewer:** When testing tools, the operator sees output JSON but cannot view intermediate HTTP request/response headers, sanitized payload hashes, or policy decision audits.
- **GAP-05: Missing Direct Link from Integration Detail to Tool Playground:** The "Open in Tools" button navigates to `tool-builder` (which cannot test MCP tools), rather than an execution sandbox.

### P2 (Medium / Polish & Ergonomics)
- **GAP-06: Duplicated Route Aliases:** `page.tsx` maps `connectors` and `mcp` to `IntegrationsScreen`, but `connectors.tsx` and `mcp.tsx` remain in the codebase as dead components.
- **GAP-07: Inconsistent Status Pill Color Semantics:** Status badges in `integrations.tsx` use inline styles (`rgba(16, 185, 129, 0.15)`), while `primitives.tsx` defines `StatusPill` and `globals.css` defines `.pill-ok`, `.pill-warn`, `.pill-err`.

---

## 7. Proposed Integrations Playground: Feasibility Assessment

### 7.1 Architecture & Feasibility: **FEASIBLE**
An **Integrations Playground** can be introduced as either:
- A top-level tab in `IntegrationsScreen` (`tab === "playground"`), OR
- An interactive drawer / sub-view accessible directly from any integration or tool card.

### 7.2 Core Capabilities & Implementation Model

1. **Integration & Tool Selection:**
   - Dropdown or searchable picker populated from `installedItems` and active materialized tools.
   - URL parameter support (`?integration=slug&tool=tool_id`) to allow direct linking from `IntegrationDetailView`.

2. **JSON Schema Form Generation:**
   - Read `tool.config.input_schema` or `tool.config.parameters`.
   - Render structured inputs for top-level properties (strings, numbers, booleans, enums).
   - Render a toggleable raw JSON Monaco/textarea editor synchronized with the form.

3. **Secured Runtime Execution with Policy Enforcement:**
   - **Crucial Rule:** The playground must NOT execute tools directly or bypass `ToolPolicyService`.
   - It must call a secured execution endpoint with `caller_type="test_endpoint"` or `"tool_manager"`.
   - If `ToolPolicyService.evaluate_execution` returns `requires_approval=True`, the playground displays a HITL approval modal with sanitized arguments hash and wait state.
   - Upon approval by an authorized role, execution resumes and consumes the approval token atomically.

4. **Result & Trace Inspection:**
   - Two-panel display: Response output on top, execution diagnostics & traces below.
   - Formatted JSON viewer with copy action.
   - Duration / latency chip and token count meter.
   - Security audit metadata (requester ID, tenant, sanitized argument hash, policy decision reason).

---

## 8. Existing Backend APIs Available for Playground

| API Endpoint | Method | Purpose | Usable in Playground? |
|---|---|---|---|
| `GET /v1/projects/{pid}/connectors` | GET | List installed connectors and tool sets. | **Yes** (populates integration selector) |
| `GET /v1/projects/{pid}/mcp-clients` | GET | List MCP servers and discovered tools. | **Yes** (populates MCP tool selector) |
| `GET /v1/projects/{pid}/tools` | GET | List all registered tools with schemas. | **Yes** (provides input schemas) |
| `POST /v1/projects/{pid}/tool-manager/analyze` | POST | Analyze capability, effect, and risk. | **Yes** (displays risk warnings prior to execution) |
| `POST /v1/projects/{pid}/tool-manager/diagnose` | POST | Diagnose execution failures and root causes. | **Yes** (displays diagnostic report on failure) |
| `POST /v1/projects/{pid}/tools/{tid}/test` | POST | Test custom REST/Code/SQL tool. | **Partial** (Bypasses `ToolPolicyService` and rejects MCP tools) |

---

## 9. Missing Functionality / Backend Gaps

1. **Unified Secured Playground Execution Endpoint:**
   - **Missing:** An endpoint such as `POST /v1/projects/{pid}/tool-manager/execute-test` that:
     - Accepts any registered tool (REST, MCP, Code, SQL, Builtin).
     - Resolves user context and credential.
     - Evaluates `ToolPolicyService.evaluate_execution(..., caller_type="test_endpoint")`.
     - Returns `status="requires_approval"` with `approval_id` and `arguments_hash` if side-effecting.
     - Executes through `ToolRegistry.execute_tool` once approved.
2. **Approval Decision Endpoint for UI:**
   - `ToolPolicyService.decide_approval_request` exists in Python, but there is no dedicated REST route for an operator to approve/reject an arbitrary pending `approval_id` outside of Assistant or Workflow resume.

---

## 10. Recommended Final Information Architecture

```
Integrations Hub (/integrations)
├── Tab 1: My Integrations (Installed connectors & active MCP servers)
│   └── Detail View (/integrations/:id)
│       ├── Overview
│       ├── Tools & Capabilities [With "Test in Playground" action]
│       ├── Configuration [Deep-link to /auth for credentials]
│       └── Diagnostics
├── Tab 2: Explore Catalog (Browse & install pre-built connectors)
├── Tab 3: Custom & MCP (Add raw MCP server or custom manifest)
└── Tab 4: Playground (Interactive Secured Tool Testing Console)
    ├── Left Panel: Integration & Tool Picker, Schema Form, Raw JSON Input
    └── Right Panel: Live Execution Result, Token Meter, HITL Approval Gate, Sanitized Traces

Secondary Standalone Screens:
├── Tools & ToolSets (/tools) — Dedicated to creating custom Code/SQL/REST tools
└── Auth Providers (/auth) — Dedicated to enterprise OAuth2 / API Key credential storage
```

---

## 11. Suggested Phased UI Implementation Approach

### Phase 1: Clean Up & Navigation Alignment (Zero Backend Changes)
- Deprecate dead components `connectors.tsx` and `mcp.tsx`.
- Standardize status badges across `integrations.tsx` using `StatusPill` and design tokens from `globals.css`.
- Add deep-links from `IntegrationsScreen` Configuration tab to `/auth`.

### Phase 2: Backend Playground Gateway & HITL Decision Route
- Expose `POST /v1/projects/{pid}/tool-manager/execute-test` with full `ToolPolicyService` evaluation and MCP execution support.
- Expose `POST /v1/projects/{pid}/tool-manager/approvals/{approval_id}/decision` for human review.

### Phase 3: Build Integrations Playground Screen
- Implement `IntegrationsPlayground` component using the two-panel layout from `knowledge-playground.tsx`.
- Integrate schema form generator with raw JSON toggle.
- Add HITL pause/approval modal and token meter.
- Add "Test in Playground" button inside `IntegrationDetailView`.
