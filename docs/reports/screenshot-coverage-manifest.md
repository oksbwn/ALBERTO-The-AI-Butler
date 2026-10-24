# Alberto Documentation Screenshot Coverage Manifest

| Screenshot Filename | Application Route | Feature Represented | Playwright Test | Used In Documentation Pages | Capture Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `auth/login.png` | `/` (unauthenticated) | First-time setup, workspace select, credentials | `01: Login Screen` | `getting-started/first-admin-and-login.md`, `security/auth-and-jwt.md` | Verified |
| `home/dashboard.png` | `/` (`screen: "home"`) | Butler Dashboard, status indicators, memory learning | `02: Core Navigation` | `getting-started/index.md`, `getting-started/first-conversation.md` | Verified |
| `chat/chat-interface.png` | `/` (`screen: "chat"`) | Butler Chat, prompt assembly, streaming, model pick | `02: Core Navigation` | `getting-started/first-conversation.md`, `agents/master-coordinator.md` | Verified |
| `automate/workflows-list.png` | `/` (`screen: "workflows"`) | Automate workflow manager, status pills, import/export | `02: Core Navigation` | `automate/index.md`, `getting-started/first-workflow.md` | Verified |
| `automate/workflow-canvas.png` | `/` (`screen: "workflow-canvas"`) | React Flow visual canvas, palette, nodes, edge links | `02: Core Navigation` | `automate/canvas.md`, `automate/node-types.md` | Verified |
| `automate/playground.png` | `/` (`screen: "playground"`) | Automate AI Studio execution playground | `02: Core Navigation` | `automate/execution.md`, `automate/examples.md` | Verified |
| `agents/agent-list.png` | `/` (`screen: "agents"`) | Specialist agent presets, flavor, model associations | `02: Core Navigation` | `agents/index.md`, `agents/specialist-agents.md` | Verified |
| `integrations/integrations-list.png` | `/` (`screen: "integrations"`) | Integration gateway, REST & MCP connectors | `02: Core Navigation` | `tools-and-integrations/index.md`, `getting-started/first-integration.md` | Verified |
| `integrations/tools-list.png` | `/` (`screen: "tools"`) | Tool Manager catalog, permissions, schema inspect | `02: Core Navigation` | `tools-and-integrations/tool-manager.md` | Verified |
| `integrations/auth-credentials.png` | `/` (`screen: "auth"`) | Secret manager, credential storage, tokens | `02: Core Navigation` | `tools-and-integrations/rest-integrations.md`, `security/tool-authorization.md` | Verified |
| `knowledge/documents.png` | `/` (`screen: "knowledge-docs"`) | Document parsing, PDF/Markdown ingestion | `02: Core Navigation` | `memory/vector-store.md`, `memory/index.md` | Verified |
| `knowledge/vector-store.png` | `/` (`screen: "knowledge-vector"`) | ChromaDB vector search & semantic chunk retrieval | `02: Core Navigation` | `memory/vector-store.md` | Verified |
| `knowledge/knowledge-graph.png` | `/` (`screen: "knowledge-graph"`) | Interactive Ladybug entity-relationship graph explorer | `02: Core Navigation` | `memory/knowledge-graph.md` | Verified |
| `knowledge/memory.png` | `/` (`screen: "knowledge-memory"`) | Long-term episodic memory, facts & preferences | `02: Core Navigation` | `memory/unified-memory.md`, `memory/markdown-memory.md` | Verified |
| `knowledge/qa-pairs.png` | `/` (`screen: "knowledge-qa"`) | Synthesized Q&A pairs for precision retrieval | `02: Core Navigation` | `memory/vector-store.md` | Verified |
| `observability/analytics.png` | `/` (`screen: "overview"`) | Token consumption, latency, and cost analytics | `02: Core Navigation` | `providers/catalog-and-metrics.md`, `deployment/operations.md` | Verified |
| `observability/traces.png` | `/` (`screen: "traces"`) | LangGraph step execution traces & waterfall viewer | `02: Core Navigation` | `architecture/orchestration.md`, `architecture/event-flow.md` | Verified |
| `settings/models-providers.png` | `/` (`screen: "settings"`, models) | Model provider credentials, Ollama/vLLM endpoints | `02: Core Navigation` | `providers/index.md`, `getting-started/first-llm.md` | Verified |
| `settings/secrets-credentials.png` | `/` (`screen: "settings"`, apikeys) | Masked master keys, API credentials | `02: Core Navigation` | `security/auth-and-jwt.md`, `security/index.md` | Verified |
| `settings/members.png` | `/` (`screen: "settings"`, members) | RBAC team roles (owner, admin, editor, viewer) | `02: Core Navigation` | `security/auth-and-jwt.md` | Verified |
| `settings/guardrails.png` | `/` (`screen: "settings"`, guardrails) | Egress control, default middleware, approval gates | `02: Core Navigation` | `security/tool-authorization.md`, `tools-and-integrations/tool-manager.md` | Verified |
| `settings/advanced.png` | `/` (`screen: "settings"`, advanced) | Project metadata, budgets, scheduler settings | `02: Core Navigation` | `deployment/environment-variables.md` | Verified |
| `mobile/home-mobile.png` | `/` (viewport 390x844) | Mobile responsive home & drawer navigation | `03: Mobile Viewport` | `index.md`, `getting-started/index.md` | Verified |
| `mobile/chat-mobile.png` | `/` (viewport 390x844) | Mobile conversational assistant interface | `03: Mobile Viewport` | `getting-started/first-conversation.md` | Verified |
