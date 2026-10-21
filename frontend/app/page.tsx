"use client";
/* Forge - root app: routing + chrome assembly (a single navigable SPA, like the handoff). */
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Topbar, ProjectSidebar, CommandPalette, Crumb } from "@/components/shell";
import { HomeScreen } from "@/components/screens/home";
import { AnalyticsScreen } from "@/components/screens/analytics";
import { PlaygroundScreen } from "@/components/screens/playground";
import { ToolsScreen, ToolBuilderScreen } from "@/components/screens/tools";
import { WorkflowsScreen, WorkflowCanvas } from "@/components/screens/workflows";
import { AgentsScreen, AgentConfigScreen } from "@/components/screens/agents";
import { ComponentsScreen, ComponentBuilderScreen } from "@/components/screens/components";
import {
  KnowledgePlaygroundScreen,
  KnowledgeDocsScreen,
  KnowledgeVectorScreen,
  KnowledgeQaScreen,
  KnowledgeGraphScreen,
  KnowledgeMemoryScreen,
} from "@/components/screens/knowledge";
import { TracesScreen } from "@/components/screens/traces";
import { AuthCredentialsScreen } from "@/components/screens/auth-credentials";
import { SettingsScreen } from "@/components/screens/settings";
import { ConnectorsScreen } from "@/components/screens/connectors";
import { IntegrationsScreen } from "@/components/screens/integrations";
import { IntegrationsPlaygroundScreen } from "@/components/screens/integrations-playground";
import { ChannelsScreen, TriggersScreen, DatasetsScreen, HandoffScreen } from "@/components/screens/platform";
import { Icon } from "@/components/icons";
import { api, Agent, ComponentT, Project, Tool, Workflow } from "@/lib/api";
import { AuthGate } from "@/components/login";

type View = { screen: string };

const SCREEN_LABEL: Record<string, string> = {
  home: "Home", chat: "Home", overview: "Analytics", automate: "Automate Playground", workflows: "Workflows", "workflow-canvas": "Workflow Canvas",
  agents: "Agents", "agent-config": "Agent Config", tools: "Tools", "tool-builder": "Tool Builder", components: "Components", "component-builder": "Component Builder",
  auth: "Auth & Credentials", knowledge: "Knowledge", playground: "Automate Playground", traces: "Executions & Traces",
  integrations: "Integrations", "integrations-playground": "Integrations Playground", connectors: "Integrations", mcp: "Integrations", settings: "Settings",
  channels: "Channels", triggers: "Triggers", datasets: "Evaluations", handoff: "Agent Inbox",
  "knowledge-playground": "Playground", "knowledge-docs": "Documents", "knowledge-vector": "Vector Store",
  "knowledge-qa": "Q&A Pairs", "knowledge-graph": "Knowledge Graph", "knowledge-memory": "Long-Term Memory",
  "knowledge-explorer": "Playground",
};
const PARENT: Record<string, [string, string]> = {
  "workflow-canvas": ["workflows", "Workflows"],
  "agent-config": ["agents", "Agents"],
  "tool-builder": ["tools", "Tools"],
  "component-builder": ["components", "Components"],
  "workflows": ["playground", "Automate"],
  auth: ["integrations", "Integrations"],
  "integrations-playground": ["integrations", "Integrations"],
  "knowledge-playground": ["knowledge-playground", "Knowledge"], "knowledge-docs": ["knowledge-playground", "Knowledge"],
  "knowledge-vector": ["knowledge-playground", "Knowledge"], "knowledge-qa": ["knowledge-playground", "Knowledge"],
  "knowledge-graph": ["knowledge-playground", "Knowledge"], "knowledge-memory": ["knowledge-playground", "Knowledge"],
  "knowledge-explorer": ["knowledge-playground", "Knowledge"],
};

function App() {
  const [view, setView] = useState<View>({ screen: "home" });
  const [cmdOpen, setCmdOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [project, setProject] = useState<Project | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [selTool, setSelTool] = useState<Tool | null>(null);
  const [focusToolSet, setFocusToolSet] = useState<string | null>(null);
  const [selWorkflow, setSelWorkflow] = useState<Workflow | null>(null);
  const [selAgent, setSelAgent] = useState<Agent | null>(null);
  const [selComponent, setSelComponent] = useState<ComponentT | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const reloadProject = async () => {
    try {
      let p = await api.listProjects();
      let defaultProj = p?.[0];
      if (!defaultProj) {
        defaultProj = await api.createProject({ name: "Alberto" });
      }
      setProject(defaultProj);
      setLoaded(true);
      return defaultProj;
    } catch {
      setLoaded(true);
    }
  };

  useEffect(() => { reloadProject(); }, []);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmdOpen((o) => !o); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const go = (v: any) => {
    setView({ screen: v.screen || "home" });
  };

  const navScreen = (screen: string) => {
    if (screen !== "tools") setFocusToolSet(null);
    setView({ screen });
  };

  // Breadcrumbs: show active screen hierarchy, without project name on top
  const crumbs: Crumb[] = [];
  const currentScreen = view.screen || "home";
  if (currentScreen === "home" || currentScreen === "chat") {
    crumbs.push({ label: "Home" });
  } else if (currentScreen === "overview") {
    crumbs.push({ label: "Analytics" });
  } else {
    const parent = PARENT[currentScreen];
    if (parent) crumbs.push({ label: parent[1], onClick: () => navScreen(parent[0]) });
    const leaf =
      currentScreen === "tool-builder" && selTool ? selTool.name :
      currentScreen === "workflow-canvas" && selWorkflow ? selWorkflow.name :
      currentScreen === "agent-config" && selAgent ? selAgent.name :
      currentScreen === "component-builder" && selComponent ? selComponent.name :
      SCREEN_LABEL[currentScreen] || currentScreen;
    crumbs.push({ label: leaf });
  }

  const canvasFlushRef = useRef<(() => Promise<void>) | null>(null);
  const [publishState, setPublishState] = useState<"idle" | "publishing" | "published" | "error">("idle");
  async function publishWorkflow() {
    if (!project || !selWorkflow) return;
    setPublishState("publishing");
    try {
      if (canvasFlushRef.current) await canvasFlushRef.current();
      await api.publishWorkflow((project as any).id, selWorkflow.id);
      setPublishState("published");
      setRefreshNonce((n) => n + 1);
      setTimeout(() => setPublishState("idle"), 1600);
    } catch {
      setPublishState("error");
      setTimeout(() => setPublishState("idle"), 2400);
    }
  }

  const topRight: ReactNode =
    view.screen === "workflow-canvas" ? (
      <div className="row gap2">
        <button className="btn btn-primary btn-sm" onClick={publishWorkflow} disabled={!selWorkflow || publishState === "publishing"}>
          <Icon name={publishState === "published" ? "check" : "bolt"} size={14} />
          {publishState === "publishing" ? "Publishing…" : publishState === "published" ? "Published" : publishState === "error" ? "Invalid - fix problems" : "Publish"}
        </button>
      </div>
    ) : null;

  const body = (() => {
    if (!loaded || !project) {
      return (
        <div className="col center grow" style={{ padding: 60, color: "var(--fg-2)" }}>
          Loading Alberto…
        </div>
      );
    }
    switch (view.screen) {
      case "home":
      case "chat":
        return <HomeScreen project={project} onNav={navScreen} onMutate={() => setRefreshNonce((n) => n + 1)} />;
      case "overview": return <AnalyticsScreen project={project} onNav={navScreen} />;
      case "automate":
      case "playground": return <PlaygroundScreen project={project} onOpenWorkflow={(w: Workflow) => { setSelWorkflow(w); navScreen("workflow-canvas"); }} onNav={navScreen} />;
      case "workflows": return <WorkflowsScreen project={project} onOpen={(w) => { setSelWorkflow(w); navScreen("workflow-canvas"); }} onNav={navScreen} />;
      case "workflow-canvas": return <WorkflowCanvas project={project} workflowId={selWorkflow?.id} onWorkflowChange={setSelWorkflow} onBack={() => navScreen("workflows")} onRun={() => navScreen("playground")} onRegisterFlush={(fn) => { canvasFlushRef.current = fn; }} />;
      case "agents": return <AgentsScreen project={project} onOpen={(a) => { setSelAgent(a); navScreen("agent-config"); }} />;
      case "agent-config": return <AgentConfigScreen project={project} agentId={selAgent?.id} onBack={() => navScreen("agents")} />;
      case "tools": return <ToolsScreen key={focusToolSet || "all"} project={project} focusSetId={focusToolSet} onOpen={(t) => { setSelTool(t); navScreen("tool-builder"); }} />;
      case "tool-builder": return <ToolBuilderScreen project={project} toolId={selTool?.id} onBack={() => navScreen("tools")} />;
      case "components": return <ComponentsScreen project={project} onOpen={(c) => { setSelComponent(c); navScreen("component-builder"); }} />;
      case "component-builder": return <ComponentBuilderScreen project={project} componentId={selComponent?.id} onBack={() => navScreen("components")} />;
      case "auth": return <AuthCredentialsScreen project={project} onNav={navScreen} />;
      case "integrations":
      case "connectors":
      case "mcp": return <IntegrationsScreen project={project} onNav={navScreen} onOpenTool={(t) => { setSelTool(t); navScreen("tool-builder"); }} />;
      case "integrations-playground": return <IntegrationsPlaygroundScreen project={project} onNav={navScreen} />;
      case "channels": return <IntegrationsScreen project={project} initialTab="my" onNav={navScreen} onOpenTool={(t) => { setSelTool(t); navScreen("tool-builder"); }} />;
      case "knowledge":
      case "knowledge-playground":
      case "knowledge-explorer": return <KnowledgePlaygroundScreen project={project} />;
      case "knowledge-docs": return <KnowledgeDocsScreen project={project} />;
      case "knowledge-vector": return <KnowledgeVectorScreen project={project} />;
      case "knowledge-qa": return <KnowledgeQaScreen project={project} />;
      case "knowledge-graph": return <KnowledgeGraphScreen project={project} />;
      case "knowledge-memory": return <KnowledgeMemoryScreen project={project} />;
      case "triggers": return <TriggersScreen project={project} />;
      case "datasets": return <DatasetsScreen project={project} />;
      case "handoff": return <HandoffScreen project={project} />;
      case "traces": return <TracesScreen project={project} />;
      case "settings": return <SettingsScreen project={project} />;
      default: return <HomeScreen project={project} onNav={navScreen} onMutate={() => setRefreshNonce((n) => n + 1)} />;
    }
  })();

  const sidebarActive =
    view.screen === "workflow-canvas" ? "workflows" :
    view.screen === "agent-config" ? "agents" :
    view.screen === "tool-builder" ? "tools" :
    view.screen === "component-builder" ? "components" :
    view.screen === "knowledge" ? "knowledge-playground" :
    view.screen === "knowledge-explorer" ? "knowledge-playground" :
    view.screen === "auth" ? "auth" :
    view.screen === "channels" ? "integrations" :
    view.screen === "automate" ? "playground" :
    (view.screen || "home");

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      {project && (
        <ProjectSidebar
          project={project}
          active={sidebarActive}
          onNav={navScreen}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
          refreshKey={refreshNonce}
        />
      )}
      <div className="col grow" style={{ minWidth: 0 }}>
        <Topbar
          crumbs={crumbs}
          right={topRight}
          project={project}
          onCommand={() => setCmdOpen(true)}
        />
        <div key={(view.screen || "") + (project?.id || "") + refreshNonce} className="col grow" style={{ minHeight: 0 }}>
          {body}
        </div>
      </div>
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} onGo={go} projects={project ? [{ id: project.id, name: project.name }] : []} />
    </div>
  );
}

export default function Page() {
  return (
    <AuthGate>
      <App />
    </AuthGate>
  );
}
