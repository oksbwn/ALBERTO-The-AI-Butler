# Alberto — Frontend UI & Design System Discovery Report

**Assessment Date:** 2026-10-18  
**Assessment Mode:** READ-ONLY discovery. No files modified during discovery. No dependencies installed. No test state mutated.

---

## 1. Executive Summary

- **Frontend Core:** Next.js 14.2.18 (App Router), React 18.3.1, TypeScript 5.6.3.
- **Routing Model:** Client-state single-page application (SPA) router mounted in root [`page.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/page.tsx). 20 user-facing screens and sub-builders, plus 1 orphaned screen ([`mcp.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/mcp.tsx)).
- **Styling Architecture:** Monolithic [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css) (303 lines) with CSS variables + utility classes, paired with heavy inline React `style={{ ... }}` throughout every component. No Tailwind, no CSS Modules, no Sass.
- **Theming:** Dual-mode light/dark token system via `:root[data-theme="light"]` and `:root[data-theme="dark"]` controlled by HTML attribute toggled in [`shell.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx). Verified working in browser inspection.
- **Responsive State:** **Zero responsive breakpoint media queries**. The UI relies exclusively on fixed pixel widths and flex containers, leading to layout clipping and overlapping on viewports < 1024px.
- **Readiness:** High potential for an incremental design system. Core design token variables exist in [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css), but component-level token adoption is fragmented due to pervasive hardcoded hex/rgba values and inline CSS.

---

## 2. Frontend Technical Stack

| Aspect | Technology / Detail | Verification File / Location |
|---|---|---|
| **Framework** | Next.js 14.2.18 (App Router) | [`package.json:17`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/package.json#L17) |
| **Runtime & Language** | React 18.3.1, TypeScript 5.6.3 | [`package.json:18-35`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/package.json#L18-L35) |
| **Node / Bundler** | Next.js Webpack + Standalone Docker support | [`next.config.mjs:12`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/next.config.mjs#L12) |
| **Primary Styling** | Vanilla CSS tokens & utilities + inline React styles | [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css) |
| **Canvas / Graph Library** | `@xyflow/react` 12.3.5 (React Flow) | [`package.json:14`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/package.json#L14) |
| **Data Visualization** | `recharts` 3.10.0 + custom SVG Sparkline/Donut | [`package.json:21`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/package.json#L21), [`primitives.tsx:8-62`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L8-L62) |
| **Markdown Rendering** | `react-markdown` 9.0.1, `remark-gfm` 4.0.0 | [`package.json:20-22`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/package.json#L20-L22), [`markdown.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/markdown.tsx) |
| **Templating & Queries** | `mustache` 4.2.0, `jmespath` 0.16.0 | [`package.json:15-16`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/package.json#L15-L16) |
| **Icon System** | Custom 24x24 SVG path dictionary (Lucide-style, 1.5px stroke) | [`icons.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/icons.tsx) |
| **Typography & Fonts** | Google Fonts Geist (100..900) & Geist Mono (100..900) via `<link>` | [`layout.tsx:16-19`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/layout.tsx#L16-L19) |
| **Test Runner** | Vitest 2.1.9, `@testing-library/react` 16.3.2, `jsdom` 25.0.1 | [`vitest.config.mts`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/vitest.config.mts) |
| **Security Headers** | Frame-ancestors 'none', X-Frame-Options DENY, X-Content-Type nosniff | [`middleware.ts:9-16`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/middleware.ts#L9-L16) |

---

## 3. UI Route and Screen Inventory

The application operates as an authenticated single-page application routed through client state `view.screen` in [`page.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/page.tsx).

| Screen / Route | Purpose | Main Components | Styling Method | UI & Visual Observations |
|---|---|---|---|---|
| **Home / Chat** (`home` / `chat`) | AI Home Butler landing & active operation console | [`HomeScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/home.tsx), [`HomeInfoScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/home_info.tsx), [`ChatScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/chat.tsx) | Split flex container with draggable divider; cards, inline styles, CSS utility classes | Two-pane split view (Home vitals on left, Butler chat on right). Left pane cards show metrics and IoT widget slots. Right pane contains streaming conversation, collapsible thinking trace, token counter, and voice STT/TTS controls. |
| **Analytics** (`overview`) | System telemetry, model costs & token throughput | [`AnalyticsScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/analytics.tsx) | Grid, cards, Recharts responsive containers | Latency, volume, and cost charts with time-range selector. Token throughput sparklines. |
| **Workflows** (`workflows`) | Workflow automation list & template launcher | [`WorkflowsScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/workflows.tsx), [`ImportExport`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/import-export.tsx) | Cards, tables, `.btn` classes, inline styles | Displays workflow cards with active version badges, publication status, import/export JSON modals. |
| **Workflow Canvas** (`workflow-canvas`) | Node-based visual graph editor | [`WorkflowCanvas`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/workflows.tsx), [`ForgeNode`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ForgeNode.tsx), [`EdgeOverlay`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/EdgeOverlay.tsx), [`ConfigForm`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ConfigForm.tsx), [`WorkflowTestPanel`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/WorkflowTestPanel.tsx) | `@xyflow/react` styles, CSS canvas tokens, node shadows | Fullscreen canvas with dot grid, palette sidebar, typed input/output ports, edge labels, sliding configuration drawer, and embedded execution debugger. |
| **Agents** (`agents`) | Autonomous ReAct agent catalog | [`AgentsScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/agents.tsx) | Table `.tbl`, chips, `.btn` | Lists agent presets, associated models, tool counts, and middleware counts. |
| **Agent Config** (`agent-config`) | Individual agent tuning & middleware harness | [`AgentConfigScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/agents.tsx), [`AgentConfig`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/AgentConfig.tsx) | Collapsible sections, textareas, multi-select chips | Detailed prompt editor, model selection, tool picker, middleware stack toggles (PII, guardrails, budget limits). |
| **Components** (`components`) | Generative UI chat widgets catalog | [`ComponentsScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/components.tsx) | Cards, grid, `.badge` | Lists custom interactive widgets callable by agents during conversations. |
| **Component Builder** (`component-builder`) | Sandbox authoring environment for UI widgets | [`ComponentBuilderScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/components.tsx), [`ComponentRenderer`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/component-renderer.tsx) | Split code editor + sandboxed iframe preview | Side-by-side HTML/CSS editor with live Mustache interpolation testing. |
| **Playground** (`playground`) | Interactive workflow execution harness | [`PlaygroundScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/playground.tsx), [`TokenMeter`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L65) | Split execution log + chat console | Run tester with token optimization meter, step-by-step state inspection, and human-in-the-loop approval triggers. |
| **Connectors** (`connectors`) | External SaaS & IoT service integration hub | [`ConnectorsScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/connectors.tsx) | Filter tabs, card grid, connection table | Displays connected and available integrations (Airtable, Jira, GitHub, Gmail, Linear, Slack, etc.) with credential connection modals. |
| **Tools** (`tools`) | Executable capability catalog (REST, Code, MCP) | [`ToolsScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/tools.tsx) | Search header, filter chips, `.tbl-dense` table | Shows tools grouped by toolsets, test status indicators (pass/fail/untested), token footprint comparisons. |
| **Tool Builder** (`tool-builder`) | Tool configuration & sandboxed test environment | [`ToolBuilderScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/tools.tsx) | Multi-step form, code editor, JSON viewer | Endpoint setup, HTTP method, parameter definition, auth provider linkage, live test button. |
| **Knowledge** (`knowledge`) | RAG vector storage, document ingest & Q&A | [`KnowledgeScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/knowledge.tsx), [`ChunkMap`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/chunk-map.tsx) | Tabs, upload dropzone, 2D vector canvas | Ingests PDF/URL/text, shows chunk embeddings, chunk clustering map canvas, and curated Q&A pairs. |
| **Auth Providers** (`auth`) | Credential vault for tool/connector authentication | [`AuthProvidersScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/auth.tsx) | Table, modal forms, status chips | OAuth2 client credentials, Bearer tokens, Basic auth, and CSRF session configurations. |
| **Triggers** (`triggers`) | Event listeners & scheduled automation entry points | [`TriggersScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/platform.tsx#L61) | List, modal form, status badges | Webhook URLs with HMAC secrets, cron schedules, email incoming hooks, and API pollers. |
| **Channels** (`channels`) | Communication gateways | [`ChannelsScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/platform.tsx#L12) | Config forms, card list | Email channel SMTP/IMAP configuration and incoming message routing. |
| **Evaluations** (`datasets`) | Automated regression test suites & scorecards | [`DatasetsScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/platform.tsx#L111) | Test matrix, score pills, metric summary | Workflow evaluation suites, ground-truth test cases, pass/fail regression metrics. |
| **Agent Inbox** (`handoff`) | Human-in-the-loop escalation review queue | [`HandoffScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/platform.tsx#L162) | Master-detail split inbox, message stream | Escalation queue for runs paused by human-input nodes; human response composition. |
| **Traces** (`traces`) | Execution observability & span waterfall breakdown | [`TracesScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/traces.tsx) | Master-detail split view, waterfall bar chart | Span waterfall with duration bars, token counts, node costs, and input/output payload inspectors. |
| **Settings** (`settings`) | System configuration, models, credentials, team | [`SettingsScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/settings.tsx) | Secondary vertical sidebar with 8 tabs, complex forms | Manages local LLM servers (Ollama, vLLM), API keys, guardrails, budget limits, version retention, and diff history. |
| **Auth Gate / Login** (`login`) | Operator authentication & workspace onboarding | [`LoginScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/login.tsx#L72), [`AcceptInviteScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/login.tsx#L12) | Centered card on `.auth-bg` radial gradient | Username/email, password, workspace name input, submit button. |
| **MCP Clients** *(Orphaned)* | Model Context Protocol server registration | [`McpClientsScreen`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/mcp.tsx) | Master-detail list, modal forms | Component exists in codebase but is not registered in `PROJECT_NAV` or `page.tsx` routing. |

---

## 4. Current Styling Architecture

### 4.1 Methodology
- **Styling Paradigm:** CSS utility classes combined with inline React `style={{ ... }}` objects.
- **No Preprocessors / Utility Frameworks:** Tailwind CSS, Sass, Less, and CSS Modules are not installed.
- **Global Ingestion:** Single global stylesheet [`frontend/app/globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css) imported at [`layout.tsx:3`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/layout.tsx#L3).
- **External CSS:** `@xyflow/react/dist/style.css` imported in [`layout.tsx:2`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/layout.tsx#L2) and [`workflows.tsx:3`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/workflows.tsx#L3).

### 4.2 Utility Classes in [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css)
- **Flexbox Utilities:** `.row`, `.col`, `.gap1` through `.gap6`, `.spread`, `.center`, `.wrap`, `.grow`.
- **Text & Hierarchy:** `.t-display-lg`, `.t-display`, `.t-h1`, `.t-h2`, `.t-h3`, `.t-body`, `.t-body-sm`, `.t-caption`, `.t-micro`, `.mono`, `.mono-sm`, `.truncate`.
- **Buttons & Interactive:** `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.btn-danger`, `.btn-sm`, `.btn-lg`, `.iconbtn`.
- **Form Controls:** `.input`, `.textarea`, `.select`, `.field-label`, `.field-help`, `.toggle`, `.segmented`.
- **Containers & Surfaces:** `.card`, `.card-hover`, `.auth-bg`, `.tbl`, `.tbl-dense`, `.divider`, `.vdivider`.
- **Badges & Indicators:** `.chip`, `.pill`, `.pill-ok`, `.pill-warn`, `.pill-err`, `.pill-info`, `.pill-muted`, `.typechip`, `.badge`, `.badge-accent`, `.typing-dot`.

---

## 5. Existing Theme and Design Token Inventory

All design tokens are declared as CSS custom properties in [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css#L7-L63).

### 5.1 Color Tokens

| Token Category | Variable Name | Light Mode Value | Dark Mode Value | Purpose / Usage |
|---|---|---|---|---|
| **Backgrounds** | `--bg-0` | `#F5F5F5` | `#0A0A0A` | Viewport & page root background |
| | `--bg-1` | `#FFFFFF` | `#171717` | Primary surface, cards, sidebars, topbar |
| | `--bg-2` | `#FFFFFF` | `#1F1F1F` | Elevated cards, canvas nodes |
| | `--bg-3` | `#F0F0F0` | `#262626` | Subtle containers, segmented controls, code blocks |
| | `--bg-hover` | `#E8E8E8` | `#2E2E2E` | Hover background for list items and buttons |
| **Borders** | `--line` | `#E5E5E5` | `rgba(255,255,255,0.10)` | Standard 1px divider, hairline separators |
| | `--line-strong` | `#D4D4D4` | `rgba(255,255,255,0.16)` | Inputs, active card borders, scrollbars |
| **Typography** | `--fg-0` | `#0A0A0A` | `#FAFAFA` | Primary high-contrast text |
| | `--fg-1` | `#404040` | `#D4D4D4` | Secondary text, labels |
| | `--fg-2` | `#737373` | `#A3A3A3` | Muted descriptions, timestamps, placeholders |
| | `--fg-on-accent` | `#FAFAFA` | `#FFFFFF` | Text over accent surfaces |
| **Primary Action** | `--primary` | `#0A0A0A` | `#FAFAFA` | Main call-to-action button background |
| | `--primary-fg` | `#FAFAFA` | `#171717` | Text on primary call-to-action button |
| | `--primary-hover` | `#262626` | `#E5E5E5` | Hover state for primary action |
| **Brand Accent** | `--accent` | `#4F46E5` | `#818CF8` | Indigo brand highlight, active tabs, links |
| | `--accent-bright` | `#6366F1` | `#A5B4FC` | Gradient highlight stop |
| | `--accent-dim` | `#4338CA` | `#6366F1` | Gradient dark stop |
| | `--accent-glow` | `rgba(79,70,229,0.10)` | `rgba(129,140,248,0.18)` | Selection, active navigation background |
| **Signal / Action** | `--signal` | `#4F46E5` | `#818CF8` | Live runs, focus rings, active toggles |
| | `--signal-dim` | `#4338CA` | `#6366F1` | Secondary signal |
| | `--signal-glow` | `rgba(79,70,229,0.14)` | `rgba(129,140,248,0.18)` | Focus ring glow |
| **Feedback** | `--ok` / `--ok-bg` | `#16A34A` / `rgba(22,163,74,0.10)` | `#4ADE80` / `rgba(74,222,128,0.12)` | Success pills, online status, checks |
| | `--warn` / `--warn-bg` | `#D97706` / `rgba(217,119,6,0.12)` | `#FBBF24` / `rgba(251,191,36,0.12)` | Warning indicators, human pause |
| | `--err` / `--err-bg` | `#DC2626` / `rgba(220,38,38,0.10)` | `#F87171` / `rgba(248,113,113,0.12)` | Errors, delete buttons, failures |
| | `--info` / `--info-bg` | `#2563EB` / `rgba(37,99,235,0.10)` | `#60A5FA` / `rgba(96,165,250,0.12)` | Information badges |
| **Graph I/O Types** | `--io-messages` | `#0D9488` | `#2DD4BF` | Chat messages connection handle |
| | `--io-text` | `#6B7280` | `#9CA3AF` | Raw string handle |
| | `--io-json` | `#7C3AED` | `#A78BFA` | JSON payload handle |
| | `--io-tool` | `#4F46E5` | `#818CF8` | Tool invocation handle |
| | `--io-vector` | `#C026D3` | `#E879F9` | Vector embeddings handle |
| | `--io-control` | `#737373` | `#A3A3A3` | Control flow / router handle |
| | `--io-any` | `#A3A3A3` | `#C0C7D0` | Generic wildcard handle |
| **Workflow Canvas** | `--canvas-bg` | `#FAFAFA` | `#0A0A0A` | Canvas background |
| | `--canvas-grid` | `rgba(10,10,10,0.05)` | `rgba(255,255,255,0.05)` | Canvas dot grid |
| | `--canvas-grid-strong` | `rgba(10,10,10,0.09)` | `rgba(255,255,255,0.09)` | Major canvas subdivisions |

### 5.2 Spacing, Dimensions, and Geometry Tokens
- **Spacing Scale:** `--s1: 4px`, `--s2: 8px`, `--s3: 12px`, `--s4: 16px`, `--s5: 20px`, `--s6: 24px`, `--s8: 32px`, `--s10: 40px`, `--s12: 48px`.
- **Border Radii:** `--r-xs: 4px`, `--r-sm: 8px`, `--r-md: 8px`, `--r-lg: 12px`, `--r-xl: 14px`, plus pill radius `999px`.
- **Elevations & Shadows:**
  - `--sh-1`: `0 1px 2px 0 rgba(0,0,0,.05)` (dark: `rgba(0,0,0,.4)`)
  - `--sh-2`: `0 4px 6px -1px rgba(0,0,0,.1), 0 2px 4px -2px rgba(0,0,0,.1)`
  - `--sh-pop`: `0 20px 25px -5px rgba(0,0,0,.1), 0 8px 10px -6px rgba(0,0,0,.1)` (dark: `rgba(0,0,0,.6)`)
  - `--node-shadow`: `0 1px 3px rgba(0,0,0,.1), 0 1px 2px -1px rgba(0,0,0,.1)`
- **Animation & Transitions:**
  - `--ease`: `cubic-bezier(.2,.8,.2,1)`
  - `--dur-fast`: `120ms`
  - `--dur`: `180ms`
  - `--dur-slow`: `260ms`

---

## 6. Shared Component Inventory

Located in [`frontend/components/primitives.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx) and [`frontend/components/shell.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx):

| Component | File Path | Props / Purpose | Reuse Count | Notes & Observations |
|---|---|---|---|---|
| `Modal` | [`primitives.tsx:161`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L161) | Dialog container portaled to `document.body` with backdrop blur, title, footer | 14 files | Portaled to body to avoid CSS transform bugs. Traps Escape key, lacks focus trapping. |
| `Drawer` | [`primitives.tsx:193`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L193) | Slide-over panel from right viewport edge | 5 files | Fixed position overlay, transitions `transform: translateX(100%)`. |
| `StatusPill` | [`primitives.tsx:111`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L111) | Neutral status pill with tinted problem states | 11 files | Maps `done/pass/active/ready/running` to neutral `.pill-muted`. Only `error/fail/interrupted` get color. |
| `Avatar` | [`primitives.tsx:124`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L124) | Initials circle with deterministic hash-based background hue | 6 files | Generated via OKLCH color wheel based on user/agent name character codes. |
| `Toggle` | [`primitives.tsx:135`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L135) | Pill switch with sliding circle handle | 9 files | Sets `aria-pressed`. Native `<button>` implementation. |
| `Segmented` | [`primitives.tsx:143`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L143) | Compact pill tab switcher | 7 files | Used for view modes, filter selectors, and time-span ranges. |
| `Tabs` | [`primitives.tsx:239`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L239) | Underlined tab bar with active accent indicator and counter badges | 8 files | Used in Settings, Knowledge, and Tool screens. |
| `Field` | [`primitives.tsx:228`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L228) | Form input wrapper with label, required asterisk, and help text | 12 files | Standardizes label margin and help text layout. |
| `EmptyState` | [`primitives.tsx:214`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L214) | Centered placeholder with rounded icon box, header, and action CTA | 9 files | Shown when lists or runs are empty. |
| `CodeBlock` | [`primitives.tsx:259`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L259) | Code container with copy-to-clipboard button | 5 files | Scrollable monospace block. |
| `TokenMeter` | [`primitives.tsx:65`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L65) | Signature visual token savings meter with progress bar | 3 files | Animates raw tokens vs projected tokens with percentage savings badge. |
| `Sparkline` | [`primitives.tsx:8`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L8) | Compact SVG trend line with optional gradient fill | 3 files | Used in project cards and analytics overview. |
| `Donut` | [`primitives.tsx:34`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L34) | SVG circular segment chart | 2 files | Used for token and model breakdown ratios. |
| `Menu` | [`primitives.tsx:287`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L287) | Dropdown popup triggered by an anchor element | 4 files | Uses click-outside listener. |
| `Topbar` | [`shell.tsx:187`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx#L187) | Global application topbar | 1 file (Root) | Renders breadcrumbs, autonomous memory learning toggle, ⌘K search, theme toggle, and account menu. |
| `ProjectSidebar` | [`shell.tsx:228`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx#L228) | Collapsible navigation rail with live count badges | 1 file (Root) | Renders icon rail when collapsed (56px) or expanded group sidebar (220px). Supports hover flyouts. |
| `CommandPalette` | [`shell.tsx:370`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx#L370) | ⌘K quick switcher and search dialog | 1 file (Root) | Fuzzy search over all navigation screens and project assets. |
| `Icon` | [`icons.tsx:129`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/icons.tsx#L129) | Universal inline SVG glyph renderer | All files | Custom lookup by icon name string. |

---

## 7. Visual Consistency Findings

### Finding 1: Inconsistent Color Variable Names and Hardcoded Fallbacks [High]
- **Issue:** [`login.tsx:45`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/login.tsx#L45) references `var(--danger, #d33)`.
- **Problem:** `--danger` does not exist in [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css) (the canonical token is `--err`). The style silently fails back to the hardcoded `#d33` hex string.
- **Other occurrences:** Hardcoded hex codes appear across components:
  - `#b00020` in [`component-renderer.tsx:55`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/component-renderer.tsx#L55).
  - `#22c55e` and `#ef4444` in [`shell.tsx:166`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx#L166).
  - Direct rgba calls `rgba(8,10,14,.5)` in [`primitives.tsx:176`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L176) instead of a shared `--overlay-bg` token.

### Finding 2: Inline Typography Hierarchy Fragmentation [Medium]
- **Issue:** Font sizes and weights are repeatedly defined ad-hoc inside component files instead of using typography tokens:
  - [`home_info.tsx:71`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/home_info.tsx#L71): `<h2 className="t-h2" style={{ margin: 0, fontSize: 18 }}>` overrides `.t-h2` (which is `15px` in `globals.css`) to `18px`.
  - [`home_info.tsx:74`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/home_info.tsx#L74): `<div className="fg-2 t-caption" style={{ marginTop: 2, fontSize: 12 }}>` manually re-declares `12px` (which is already `.t-caption`).
  - [`shell.tsx:161-163`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx#L161-L163): uses fractional `fontSize: 11.5`.

### Finding 3: Arbitrary Border Radius Usage [Medium]
- **Issue:** [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css#L59) defines tokens `--r-xs: 4px`, `--r-sm: 8px`, `--r-md: 8px`, `--r-lg: 12px`, `--r-xl: 14px`.
- **Reality in code:** Components frequently use hardcoded arbitrary pixel radii:
  - `borderRadius: 6` in [`shell.tsx:159`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx#L159) and [`shell.tsx:217`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx#L217).
  - `borderRadius: 9` in [`mcp.tsx:38`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/mcp.tsx#L38) and [`shell.tsx:38`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx#L38).
  - `borderRadius: 5` in [`primitives.tsx:308`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L308).

### Finding 4: Inconsistent Flyout Positioning & Overlap [Medium]
- **Verified via Browser Subagent:** When clicking or hovering sidebar group icons (e.g. Integrations) on desktop and mobile, the floating menu renders at `position: fixed` with `left: 56px`, covering the leftmost 200px of page content rather than pushing content or sliding inside an off-canvas drawer.

---

## 8. CSS Duplication and Technical Debt

### 8.1 Heavy Inline Styles in Place of CSS Classes
Across all 17 screen files and 8 component files, UI elements use React `style={{ ... }}` objects for layout, padding, font size, margins, and borders.
- **Example in [`home_info.tsx:46-57`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/home_info.tsx#L46-L57):**
  ```tsx
  style={{
    width: "100%", height: "100%", background: "var(--bg-0)",
    display: "flex", flexDirection: "column", padding: "16px 20px",
    overflowY: "auto", scrollbarWidth: "none", msOverflowStyle: "none",
  }}
  ```
- **Consequence:** These styles cannot be overridden cleanly by global theme adjustments, cannot support media queries without JS window listeners, and increase bundle size and rendering overhead.

### 8.2 Specificity and Reset Gaps
- Scrollbars: [`globals.css:78-81`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css#L78-L81) customizes `::-webkit-scrollbar`, but individual screens duplicate scrollbar suppression rules (`scrollbarWidth: "none"`, `msOverflowStyle: "none"` in [`home_info.tsx:54-55`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/home_info.tsx#L54-L55)).
- Focus outlines: `:focus-visible` is styled with `--glow-signal` in [`globals.css:242`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css#L242), but numerous clickable elements (`<div onClick=...>`, custom buttons) use `outline: none` without keyboard focus states.

### 8.3 Legacy Naming and Naming Drift
- The design tokens in [`globals.css:1-5`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css#L1-L5) and comments in [`page.tsx:2`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/page.tsx#L2) refer to the upstream design prototype name "Forge" rather than "Alberto".
- Event listeners in [`shell.tsx:254`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx#L254) listen to both `alberto:counts-changed` and `forge:counts-changed` to handle legacy events.

---

## 9. Accessibility and Responsiveness Findings

### 9.1 Responsiveness Assessment [Critical]
- **Verified in Browser (390px Mobile Width):**
  1. The 56px navigation rail remains permanently pinned to the left, consuming 15% of the mobile screen width.
  2. The topbar elements (breadcrumbs, autonomous memory toggle, search bar, theme switcher, avatar) collide and overflow horizontally.
  3. Tables (such as Connectors and Tools) do not collapse into mobile cards; text and actions are clipped off-screen with horizontal scrolling.
  4. The Home two-pane split layout maintains a `minWidth: 280px` on both panes, causing severe viewport overflow and layout disruption on narrow screens.
- **Root Cause:** [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css) contains no responsive breakpoint `@media` queries for viewport widths.

### 9.2 Accessibility (a11y) Assessment [High]
- **Interactive Element Semantics:** Several clickable items use `<div>` with `onClick` without `role="button"` or `tabIndex={0}`:
  - Custom dropdown menus in [`primitives.tsx:299`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L299): `<div onClick={() => setOpen((o) => !o)}>{trigger}</div>`.
  - Cards with `onClick` in [`home_info.tsx:99`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/home_info.tsx#L99).
- **Focus Management:** Modals portaled to `document.body` handle Escape key listeners, but do not trap focus or return focus to the triggering element upon closing.
- **Color Contrast:** Low contrast observed on muted text (`--fg-2: #737373` on `--bg-0: #F5F5F5` has a contrast ratio of ~3.6:1, falling below WCAG AA 4.5:1 for body copy). In dark mode (`#A3A3A3` on `#0A0A0A`), contrast is ~6.2:1 (compliant).

---

## 10. Design System Readiness Assessment

| Evaluation Dimension | Status | Assessment |
|---|---|---|
| **Design Token Foundation** | **Ready** | Solid token palette in [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css) with semantic naming (`--bg-*`, `--fg-*`, `--accent`, `--ok`, `--err`). |
| **Theming (Dark/Light)** | **Ready** | Fully operational via CSS attribute selectors (`data-theme`). Smooth instant switching verified. |
| **Component Primitives** | **Partial** | Core primitives exist in [`primitives.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx), but lack standard props interfaces (`variant`, `size`, polymorphic `as`) and have inline styles embedded. |
| **Layout Standards** | **Needs Refactoring** | Layouts rely on fixed pixel values (`width: 280`, `width: 56`) rather than fluid containers with media query breakpoints. |
| **Adoption Across Screens** | **Low** | Screens bypass design tokens in favor of ad-hoc inline styles and hardcoded hex colors. |

**Verdict:** The codebase does **NOT** require an architectural rewrite or an external component framework (e.g., adding full Tailwind or Radix packages). The existing vanilla CSS custom properties and Next.js setup can support an enterprise-grade design system through **surgical tokenization, utility expansion, and component consolidation**.

---

## 11. Recommended Target Design System Architecture

```
frontend/
├── app/
│   ├── layout.tsx
│   ├── page.tsx
│   └── globals.css              --> Keep minimal reset + imports
├── styles/
│   ├── tokens/
│   │   ├── colors.css           --> Semantic light & dark tokens, status, I/O
│   │   ├── typography.css       --> Scale, line-heights, weights (Geist / Mono)
│   │   ├── spacing.css          --> 4px scale, layout dimensions, z-index scale
│   │   └── elevation.css        --> Shadows, borders, radii, transitions
│   ├── utilities/
│   │   ├── layout.css           --> Grid, flexbox, containers, responsive helpers
│   │   └── responsive.css       --> Standard breakpoints: sm (640), md (768), lg (1024), xl (1280)
│   └── components/              --> Base CSS classes for buttons, cards, inputs, tables
├── components/
│   ├── ui/                      --> Consolidated Design System Primitives
│   │   ├── Button.tsx
│   │   ├── Input.tsx
│   │   ├── Card.tsx
│   │   ├── Badge.tsx / StatusPill.tsx
│   │   ├── Modal.tsx / Drawer.tsx
│   │   ├── Tabs.tsx
│   │   └── Table.tsx
│   ├── shell/                   --> App Shell & Responsive Navigation
│   │   ├── Topbar.tsx
│   │   ├── Sidebar.tsx          --> Desktop rail + Mobile slide-over drawer
│   │   └── CommandPalette.tsx
│   └── screens/                 --> Screen modules consuming unified UI primitives
```

### Architectural Principles:
1. **Extend Existing Vanilla CSS Variables:** Retain `--bg-*`, `--fg-*`, `--accent`, `--signal`, etc. Add missing elevation, overlay, and z-index scale tokens.
2. **Standardize Breakpoints in CSS:**
   - Mobile: `< 768px` (Sidebar collapses into an off-canvas drawer with hamburger toggle; Home splits into tabbed or stacked views).
   - Tablet: `768px - 1024px` (Sidebar stays in compact 56px rail mode).
   - Desktop: `> 1024px` (Full split layout with resizable splitter).
3. **Eliminate Inline Hardcoded Styles:** Replace inline `style={{ ... }}` on repeated patterns (buttons, cards, inputs, table rows) with semantic classes or unified primitive components.

---

## 12. Proposed Implementation Phases

### Phase 1: Token Unification & Hygiene (Low Risk, Zero Regressions)
- Fix dangling variable references (e.g. map `--danger` to `--err` in [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css)).
- Extract hardcoded hex/rgba values from [`login.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/login.tsx), [`shell.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx), and [`primitives.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx) into tokens.
- Add formal z-index tokens (`--z-base: 0`, `--z-dropdown: 1000`, `--z-drawer: 7000`, `--z-modal: 8000`, `--z-toast: 9000`).

### Phase 2: Primitive Component Hardening (Medium Risk)
- Consolidate button, card, modal, and drawer primitives into strongly-typed components.
- Ensure all interactive elements include `:focus-visible` styling, keyboard accessibility, and ARIA roles.
- Remove inline style overrides on typography and standardize heading classes (`.t-h1`, `.t-h2`, `.t-h3`).

### Phase 3: Responsive Navigation & Layout System (Medium Risk)
- Add responsive media queries to [`globals.css`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/app/globals.css).
- Adapt [`shell.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/shell.tsx) with a responsive mobile drawer for screens `< 768px`.
- Make the Home screen two-pane split responsive: render stacked or tabbed on mobile viewports (< 768px).

### Phase 4: Screen Refactoring & Token Adoption (Iterative, Per-Module)
- Refactor screens one by one to consume design tokens:
  1. Home & Chat ([`home.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/home.tsx), [`chat.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/chat.tsx))
  2. Workflows & Canvas ([`workflows.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/workflows.tsx), [`canvas/*`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ForgeNode.tsx))
  3. Settings ([`settings.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/settings.tsx))
  4. Connectors & Tools ([`connectors.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/connectors.tsx), [`tools.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/tools.tsx))
  5. Observability & Platform ([`analytics.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/analytics.tsx), [`traces.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/traces.tsx), [`platform.tsx`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/platform.tsx))

---

## 13. Critical Compatibility and Constraints

During any subsequent visual refactor, the following core functional areas **MUST NOT BE BROKEN**:

1. **Workflow Canvas Drag & Drop and Node Handles:**
   - React Flow (`@xyflow/react`) node internal measurements depend on specific port key tracking in [`ForgeNode.tsx:107-108`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/canvas/ForgeNode.tsx#L107-L108). Altering handle positioning or CSS classes without testing edge reconciliation will break canvas wiring.
2. **Sandboxed ComponentRenderer iframe:**
   - Must preserve `sandbox="allow-scripts"` (without `allow-same-origin`) and postMessage communication bridge in [`component-renderer.tsx:21-28`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/component-renderer.tsx#L21-L28).
3. **Chat Live Streaming & SSE Frames:**
   - The SSE parser in [`lib/api.ts`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/lib/api.ts) drives live token metering and thought collapsing. UI re-renders must not disrupt open SSE connections or unmount streaming bubbles prematurely.
4. **Voice Butler Web Speech API:**
   - STT (`webkitSpeechRecognition`) and TTS (`window.speechSynthesis`) integration in [`chat.tsx:119-140`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/screens/chat.tsx#L119-L140) must preserve button triggers and state flags.
5. **Modal & Drawer Portaling:**
   - Modals must continue to portal to `document.body` to avoid clipping caused by ancestor `.fade-up` CSS transforms (noted in [`primitives.tsx:162-165`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/frontend/components/primitives.tsx#L162-L165)).

---

## 14. Existing Validation Commands

All commands verified from project configuration and [`test.sh`](file:///c:/Users/oksbw/OneDrive/Desktop/Workspace/Alberto/test.sh):

```bash
# 1. Typecheck the frontend (no emit)
cd frontend && npx tsc --noEmit

# 2. Run Next.js linter
cd frontend && npm run lint

# 3. Run frontend unit & component tests via Vitest
cd frontend && npm test

# 4. Run full repository verification suite (linters, backend tests, frontend tests)
./test.sh

# 5. Verify Next.js production build bundle
cd frontend && npm run build
```
