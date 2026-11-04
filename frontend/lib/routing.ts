/* Alberto URL Routing: deterministic 2-level canonical paths (/module/page) */

export const PATH_TO_SCREEN: Record<string, string> = {
  // Home module
  "/": "home",
  "/home": "home",
  "/home/overview": "home",
  "/chat": "home",

  // Automate module
  "/automate": "playground",
  "/automate/playground": "playground",
  "/playground": "playground",
  "/automate/workflows": "workflows",
  "/workflows": "workflows",
  "/automate/canvas": "workflow-canvas",
  "/automate/workflows/canvas": "workflow-canvas",
  "/workflows/canvas": "workflow-canvas",
  "/workflow-canvas": "workflow-canvas",
  "/automate/agents": "agents",
  "/agents": "agents",
  "/automate/agents/config": "agent-config",
  "/agent-config": "agent-config",
  "/automate/components": "components",
  "/components": "components",
  "/automate/components/builder": "component-builder",
  "/component-builder": "component-builder",
  "/automate/traces": "traces",

  // Knowledge module
  "/knowledge": "knowledge-playground",
  "/knowledge/playground": "knowledge-playground",
  "/knowledge-playground": "knowledge-playground",
  "/knowledge/docs": "knowledge-docs",
  "/knowledge-docs": "knowledge-docs",
  "/knowledge/vector": "knowledge-vector",
  "/knowledge-vector": "knowledge-vector",
  "/knowledge/qa": "knowledge-qa",
  "/knowledge-qa": "knowledge-qa",
  "/knowledge/graph": "knowledge-graph",
  "/knowledge-graph": "knowledge-graph",
  "/knowledge/memory": "knowledge-memory",
  "/knowledge-memory": "knowledge-memory",
  "/knowledge/reviews": "ontology-review-queue",
  "/knowledge-reviews": "ontology-review-queue",

  // Integrations module
  "/integrations": "integrations",
  "/integrations/connectors": "integrations",
  "/connectors": "integrations",
  "/mcp": "integrations",
  "/integrations/playground": "integrations-playground",
  "/integrations-playground": "integrations-playground",
  "/integrations/channels": "channels",
  "/channels": "channels",
  "/integrations/tools": "tools",
  "/tools": "tools",
  "/integrations/tools/builder": "tool-builder",
  "/tool-builder": "tool-builder",
  "/integrations/triggers": "triggers",
  "/triggers": "triggers",
  "/integrations/auth": "auth",
  "/auth": "auth",

  // Observability module
  "/observability": "overview",
  "/observability/analytics": "overview",
  "/analytics": "overview",
  "/overview": "overview",
  "/observability/traces": "traces",
  "/traces": "traces",
  "/observability/evaluations": "datasets",
  "/observability/datasets": "datasets",
  "/evaluations": "datasets",
  "/datasets": "datasets",
  "/observability/inbox": "handoff",
  "/observability/handoff": "handoff",
  "/handoff": "handoff",
  "/inbox": "handoff",

  // Settings module
  "/settings": "settings",
  "/settings/general": "settings",
};

export const SCREEN_TO_PATH: Record<string, string> = {
  // Home module
  home: "/home/overview",
  chat: "/home/overview",

  // Automate module
  playground: "/automate/playground",
  automate: "/automate/playground",
  workflows: "/automate/workflows",
  "workflow-canvas": "/automate/canvas",
  agents: "/automate/agents",
  "agent-config": "/automate/agents/config",
  components: "/automate/components",
  "component-builder": "/automate/components/builder",

  // Knowledge module
  knowledge: "/knowledge/playground",
  "knowledge-playground": "/knowledge/playground",
  "knowledge-explorer": "/knowledge/playground",
  "knowledge-docs": "/knowledge/docs",
  "knowledge-vector": "/knowledge/vector",
  "knowledge-qa": "/knowledge/qa",
  "knowledge-graph": "/knowledge/graph",
  "knowledge-memory": "/knowledge/memory",
  "ontology-review-queue": "/knowledge/reviews",

  // Integrations module
  "integrations-playground": "/integrations/playground",
  integrations: "/integrations/connectors",
  connectors: "/integrations/connectors",
  mcp: "/integrations/connectors",
  channels: "/integrations/channels",
  tools: "/integrations/tools",
  "tool-builder": "/integrations/tools/builder",
  triggers: "/integrations/triggers",
  auth: "/integrations/auth",

  // Observability module
  overview: "/observability/analytics",
  traces: "/observability/traces",
  datasets: "/observability/evaluations",
  handoff: "/observability/inbox",

  // Settings module
  settings: "/settings/general",
};

export function pathToScreen(pathname: string): string {
  const clean = pathname.replace(/\/+$/, "") || "/";
  return PATH_TO_SCREEN[clean] || "home";
}

export function screenToPath(screen: string): string {
  return SCREEN_TO_PATH[screen] || (screen === "home" ? "/home/overview" : `/${screen}/general`);
}

