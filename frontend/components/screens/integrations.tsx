"use client";
/* Unified Integrations Screen: Single management console for REST connectors,
   Remote MCP servers, custom APIs, OAuth 2.0 and API token authentication. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../icons";
import { EmptyState, Field, Modal, Tile, Toggle } from "../primitives";
import { AuthProvidersScreen } from "./auth";
import {
  api,
  Channel,
  ChannelDiagnostics,
  ChannelIdentityOut,
  ChannelPairingOut,
  ConnectorCatalogEntry,
  ConnectorExample,
  ConnectorInstallT,
  McpClientT,
  Tool,
  ToolAnalysisResult,
  ToolDiagnosticReport,
} from "@/lib/api";

type MainTab = "my" | "explore" | "custom" | "advanced";
type DetailTab = "overview" | "tools" | "config" | "diagnostics";

interface UnifiedIntegrationItem {
  id: string;
  slug: string;
  name: string;
  summary: string;
  icon: string;
  kind: "connector_rest" | "connector_mcp" | "raw_mcp" | "channel_email" | "channel_telegram";
  status: "connected" | "needs_auth" | "needs_setup" | "degraded" | "error" | "installed";
  status_detail?: string | null;
  account?: string | null;
  total_tools: number;
  enabled_tools: number;
  last_verified?: string | null;
  auth_kind?: string;
  source: "catalog" | "custom" | "mcp" | "channel";
  raw_connector?: ConnectorInstallT;
  raw_mcp?: McpClientT;
  raw_channel?: Channel;
}

export function IntegrationsScreen({
  project,
  initialTab = "my",
  onNav,
  onOpenTool,
}: {
  project: any;
  initialTab?: MainTab;
  onNav?: (screen: string) => void;
  onOpenTool?: (t: Tool) => void;
}) {
  const [tab, setTab] = useState<MainTab>(initialTab);
  const [selectedItem, setSelectedItem] = useState<UnifiedIntegrationItem | null>(null);

  // Data states
  const [catalog, setCatalog] = useState<ConnectorCatalogEntry[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [installs, setInstalls] = useState<ConnectorInstallT[]>([]);
  const [mcpClients, setMcpClients] = useState<McpClientT[]>([]);
  const [allTools, setAllTools] = useState<Tool[]>([]);
  const [examples, setExamples] = useState<ConnectorExample[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [agents, setAgents] = useState<any[]>([]);

  // Create Channel Modal state
  const [newChannelOpen, setNewChannelOpen] = useState(false);
  const [newChannelType, setNewChannelType] = useState<"telegram" | "email">("telegram");
  const [newChannelName, setNewChannelName] = useState("");

  // UI states
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState("all");
  const [busySlug, setBusySlug] = useState<string | null>(null);
  const [advancedSubTab, setAdvancedSubTab] = useState<"auth" | "oauth" | "mcp">("auth");

  // Custom Integration Modal / Form
  const [customManifest, setCustomManifest] = useState("");
  const [customAuthMode, setCustomAuthMode] = useState("shared");
  const [customValues, setCustomValues] = useState<Record<string, string>>({});
  const [validating, setValidating] = useState(false);
  const [validationErr, setValidationErr] = useState<string | null>(null);

  // Add MCP server modal
  const [addMcpOpen, setAddMcpOpen] = useState(false);
  const [newMcpName, setNewMcpName] = useState("");
  const [newMcpUrl, setNewMcpUrl] = useState("");
  const [newMcpTransport, setNewMcpTransport] = useState<"http" | "sse">("http");

  // OAuth popup listener ref
  const popupRef = useRef<Window | null>(null);
  const popupPollTimerRef = useRef<NodeJS.Timeout | null>(null);

  const cleanupOAuthWatcher = useCallback(() => {
    if (popupPollTimerRef.current) {
      clearInterval(popupPollTimerRef.current);
      popupPollTimerRef.current = null;
    }
    popupRef.current = null;
  }, []);

  useEffect(() => {
    return cleanupOAuthWatcher;
  }, [cleanupOAuthWatcher]);

  // Load all integration resources
  const reload = useCallback(async () => {
    if (!project?.id) return;
    try {
      setLoading(true);
      const [catRes, instRes, mcpRes, toolsRes, exRes, chanRes, wfRes, agRes] = await Promise.all([
        api.connectorCatalog(project.id).catch(() => ({ connectors: [], categories: [], roles: [] })),
        api.listConnectors(project.id).catch(() => []),
        api.listMcpClients(project.id).catch(() => []),
        api.listTools(project.id).catch(() => []),
        api.connectorExamples(project.id).catch(() => []),
        api.listChannels(project.id).catch(() => []),
        api.listWorkflows(project.id).catch(() => []),
        api.listAgents(project.id).catch(() => []),
      ]);

      setCatalog(catRes.connectors || []);
      setCategories(catRes.categories || []);
      setInstalls(instRes || []);
      setMcpClients(mcpRes || []);
      setAllTools(toolsRes || []);
      setExamples(exRes || []);
      setChannels(chanRes || []);
      setWorkflows(wfRes || []);
      setAgents(agRes || []);
    } catch (e: any) {
      setErr(e?.message || "Failed to load integrations");
    } finally {
      setLoading(false);
    }
  }, [project?.id]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Assemble unified list of installed integrations
  const installedItems: UnifiedIntegrationItem[] = useMemo(() => {
    const list: UnifiedIntegrationItem[] = [];

    // 1. Installed Connectors
    for (const inst of installs) {
      const anyInst = inst as any;
      const manifest = anyInst.manifest || {};
      const catEntry = catalog.find((c) => c.slug === inst.slug);
      const createdIds = new Set((anyInst.created_tool_ids as string[]) || []);
      const matchingTools = allTools.filter((t) => createdIds.has(t.id) || (inst.tool_set_id && (t as any).tool_set_id === inst.tool_set_id));
      const enabledTools = matchingTools.filter((t) => t.enabled);

      const isMcp = Boolean(inst.mcp_client_id) || manifest?.backend?.kind === "mcp" || inst.type === "MCP";

      let status: UnifiedIntegrationItem["status"] = "connected";
      if (inst.status === "needs_auth") status = "needs_auth";
      else if (inst.status === "needs_setup") status = "needs_setup";
      else if (inst.status === "error") status = "error";

      list.push({
        id: `connector:${inst.id}`,
        slug: inst.slug,
        name: inst.name,
        summary: catEntry?.summary || manifest?.summary || inst.summary || "Connected integration",
        icon: catEntry?.icon || manifest?.icon || inst.icon || "plug",
        kind: isMcp ? "connector_mcp" : "connector_rest",
        status,
        status_detail: inst.status_detail,
        account: inst.auth_mode === "per_user" ? "Personal connection" : "Workspace shared",
        total_tools: matchingTools.length > 0 ? matchingTools.length : (inst.tool_count || 0),
        enabled_tools: enabledTools.length,
        last_verified: anyInst.updated_at || anyInst.created_at,
        auth_kind: catEntry?.auth?.kind || (catEntry as any)?.auth_kind || manifest?.auth?.kind || inst.auth_kind,
        source: inst.source as any,
        raw_connector: inst,
      });
    }

    // 2. Direct MCP Clients (that are not managed by a connector)
    for (const client of mcpClients) {
      if (client.connector_slug) continue; // Already covered by connector item

      const caps = client.capabilities || {};
      const discTools = (caps.tools as any[]) || [];
      const disabledSet = new Set(client.disabled_tools || []);
      const enabledCount = discTools.filter((t: any) => !disabledSet.has(t.name)).length;

      list.push({
        id: `mcp:${client.id}`,
        slug: client.id,
        name: client.name,
        summary: `MCP Server (${client.transport}) · ${client.url || client.command || "Remote endpoint"}`,
        icon: "connect",
        kind: "raw_mcp",
        status: client.enabled ? "connected" : "degraded",
        status_detail: client.enabled ? undefined : "Disabled",
        account: client.auth_provider_id ? "OAuth / Provider bound" : "Header / Public",
        total_tools: discTools.length,
        enabled_tools: client.enabled ? enabledCount : 0,
        last_verified: client.last_discovered_at || (client as any).updated_at,
        auth_kind: client.auth_provider_id ? "oauth2" : "headers",
        source: "mcp",
        raw_mcp: client,
      });
    }

    // 3. Independent Communication Channels (Integrations v3)
    for (const ch of channels) {
      const isTg = ch.type === "telegram";
      let status: UnifiedIntegrationItem["status"] = "connected";
      if (!ch.enabled) status = "degraded";
      else if (ch.routing_state === "needs_review") status = "needs_setup";
      else if (ch.state?.connected === false) status = "degraded";

      const targetLabel =
        ch.target_type === "subagent"
          ? `Subagent: ${agents.find((a: any) => a.id === ch.target_id)?.name || ch.target_id || "Unset"}`
          : ch.target_type === "workflow"
          ? `Workflow: ${workflows.find((w: any) => w.id === ch.target_id)?.name || ch.target_id || "Unset"}`
          : "Master Agent (Default)";

      list.push({
        id: `channel:${ch.id}`,
        slug: ch.type,
        name: ch.name || (isTg ? "Telegram Bot Channel" : "Email Communication Channel"),
        summary: `Channel Gateway · ${targetLabel}`,
        icon: isTg ? "msg" : "mail",
        kind: isTg ? "channel_telegram" : "channel_email",
        status,
        status_detail: ch.routing_state === "needs_review" ? "Routing needs review" : (ch.state?.last_error || undefined),
        account: isTg
          ? (ch.state?.effective_transport === "polling" ? "Polling mode" : "Webhook mode")
          : (ch.inbound_url ? "Inbound webhook ready" : "Outbound SMTP"),
        total_tools: 0,
        enabled_tools: 0,
        last_verified: ch.state?.last_poll_at ? new Date(ch.state.last_poll_at * 1000).toISOString() : (ch as any).created_at,
        auth_kind: isTg ? "bot_token" : "smtp_credentials",
        source: "channel",
        raw_channel: ch,
      });
    }

    return list;
  }, [installs, mcpClients, allTools, catalog, channels, workflows, agents]);

  // Handle OAuth completion via secure message event
  const startOAuthFlow = useCallback(
    async (slug: string) => {
      setBusySlug(slug);
      setErr(null);
      setNote(null);
      cleanupOAuthWatcher();

      try {
        const { authorize_url } = await api.connectConnector(project.id, slug);

        // Open popup
        const width = 720;
        const height = 820;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;
        const popup = window.open(
          authorize_url,
          `alberto_oauth_${slug}`,
          `width=${width},height=${height},left=${left},top=${top},status=yes,toolbar=no,menubar=no`
        );
        popupRef.current = popup;
        setNote("Finish signing in with the provider. This window will sync automatically upon approval.");

        // Safe message listener with exact origin checking
        const onMessage = (event: MessageEvent) => {
          if (event.origin !== window.location.origin) {
            return;
          }
          if (event.data?.type === "alberto:oauth_complete") {
            window.removeEventListener("message", onMessage);
            cleanupOAuthWatcher();

            if (event.data.status === "success") {
              setNote("Authorization completed successfully! Updating capabilities…");
              api
                .syncConnector(project.id, slug)
                .catch(() => {})
                .finally(() => {
                  reload();
                  setBusySlug(null);
                });
            } else {
              setErr(`Authorization failed: ${event.data.error || "User cancelled or denied consent"}`);
              setBusySlug(null);
            }
          }
        };

        window.addEventListener("message", onMessage);

        // Bounded fallback timeout (120s ceiling, non-infinite) to catch manual popup closure
        let elapsed = 0;
        popupPollTimerRef.current = setInterval(() => {
          elapsed += 1;
          if (popup?.closed) {
            window.removeEventListener("message", onMessage);
            cleanupOAuthWatcher();
            // Trigger a single status check
            api.syncConnector(project.id, slug).catch(() => {});
            reload();
            setBusySlug(null);
          } else if (elapsed > 120) {
            window.removeEventListener("message", onMessage);
            cleanupOAuthWatcher();
            setBusySlug(null);
          }
        }, 1000);
      } catch (e: any) {
        setErr(e?.message || "Could not initialize authorization flow");
        setBusySlug(null);
      }
    },
    [project.id, reload, cleanupOAuthWatcher]
  );

  // Sync / refresh actions for an item
  const handleSyncItem = async (item: UnifiedIntegrationItem) => {
    setBusySlug(item.slug);
    setErr(null);
    try {
      if (item.raw_connector) {
        await api.syncConnector(project.id, item.raw_connector.slug);
      } else if (item.raw_mcp) {
        await api.refreshMcpCapabilities(project.id, item.raw_mcp.id);
      }
      await reload();
      setNote(`Successfully refreshed capabilities for ${item.name}.`);
      setTimeout(() => setNote(null), 3000);
    } catch (e: any) {
      setErr(e?.message || "Failed to sync capabilities");
    } finally {
      setBusySlug(null);
    }
  };

  // Disconnect or uninstall an item
  const handleRemoveItem = async (item: UnifiedIntegrationItem) => {
    if (!window.confirm(`Are you sure you want to disconnect “${item.name}”?`)) return;
    setBusySlug(item.slug);
    try {
      if (item.raw_connector) {
        await api.uninstallConnector(project.id, item.raw_connector.slug);
      } else if (item.raw_mcp) {
        await api.deleteMcpClient(project.id, item.raw_mcp.id);
      }
      setSelectedItem(null);
      await reload();
    } catch (e: any) {
      setErr(e?.message || "Failed to remove integration");
    } finally {
      setBusySlug(null);
    }
  };

  // Add custom MCP client
  const handleAddMcpClient = async () => {
    if (!newMcpName.trim() || !newMcpUrl.trim()) return;
    setErr(null);
    try {
      await api.createMcpClient(project.id, {
        name: newMcpName.trim(),
        transport: newMcpTransport,
        url: newMcpUrl.trim(),
      });
      setAddMcpOpen(false);
      setNewMcpName("");
      setNewMcpUrl("");
      reload();
    } catch (e: any) {
      setErr(e?.message || "Failed to register MCP server");
    }
  };

  // Keep selectedItem in sync with reloaded data
  useEffect(() => {
    if (!selectedItem) return;
    const updated = installedItems.find((i) => i.id === selectedItem.id);
    if (updated) setSelectedItem(updated);
  }, [installedItems, selectedItem]);

  // Render detail view if an item is selected
  if (selectedItem) {
    if (selectedItem.raw_channel) {
      return (
        <ChannelDetailView
          project={project}
          channel={selectedItem.raw_channel}
          workflows={workflows}
          agents={agents}
          onBack={() => setSelectedItem(null)}
          onReload={reload}
          onNav={onNav}
        />
      );
    }
    return (
      <IntegrationDetailView
        project={project}
        item={selectedItem}
        allTools={allTools}
        onBack={() => setSelectedItem(null)}
        onReload={reload}
        onConnect={() => startOAuthFlow(selectedItem.slug)}
        onSync={() => handleSyncItem(selectedItem)}
        onRemove={() => handleRemoveItem(selectedItem)}
        onOpenTool={onOpenTool}
        onNav={onNav}
      />
    );
  }

  // Filtered catalog entries for Explore tab
  const filteredCatalog = catalog.filter((c) => {
    const matchesSearch =
      !search ||
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.summary.toLowerCase().includes(search.toLowerCase()) ||
      c.slug.toLowerCase().includes(search.toLowerCase());
    const categories = c.categories || ((c as any).category ? [(c as any).category] : []);
    const matchesCategory = filterCategory === "all" || categories.includes(filterCategory);
    return matchesSearch && matchesCategory;
  });

  return (
    <div className="col grow" style={{ minHeight: 0, background: "var(--bg-0)" }}>
      {/* Top Header */}
      <div
        className="row spread"
        style={{
          padding: "16px 24px",
          borderBottom: "1px solid var(--line-strong)",
          background: "var(--bg-1)",
        }}
      >
        <div className="col" style={{ gap: 4 }}>
          <div className="row gap2">
            <Icon name="plug" size={20} style={{ color: "var(--signal)" }} />
            <h1 className="t-h2" style={{ margin: 0 }}>Integrations</h1>
          </div>
          <div className="t-body-sm fg-2">
            Connect smart devices, cloud services, and independent communication channels to Alberto.
          </div>
        </div>

        <div className="row gap3" style={{ alignItems: "center" }}>
          {/* Primary Segmented Tabs */}
          <div className="row gap1" style={{ background: "var(--bg-2)", padding: 3, borderRadius: 8 }}>
            <button
              className={`btn btn-sm ${tab === "my" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setTab("my")}
            >
              <Icon name="check" size={14} /> My Integrations ({installedItems.length})
            </button>
            <button
              className={`btn btn-sm ${tab === "explore" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setTab("explore")}
            >
              <Icon name="search" size={14} /> Explore ({catalog.length + 2})
            </button>
            <button
              className={`btn btn-sm ${tab === "custom" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setTab("custom")}
            >
              <Icon name="plus" size={14} /> Custom
            </button>
            <button
              className={`btn btn-sm ${tab === "advanced" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setTab("advanced")}
            >
              <Icon name="settings-2" size={14} /> Advanced Settings
            </button>
          </div>

          <div className="row gap2">
            {onNav && (
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => onNav("integrations-playground")}
                style={{ gap: 6 }}
                title="Launch Integrations Playground"
              >
                <Icon name="playground" size={14} /> Playground
              </button>
            )}
            <button
              className="btn btn-primary btn-sm"
              onClick={() => setNewChannelOpen(true)}
              style={{ gap: 6 }}
            >
              <Icon name="plus" size={14} /> New Channel
            </button>
          </div>
        </div>
      </div>

      {/* Notifications */}
      {err && (
        <div className="row spread" style={{ padding: "10px 24px", background: "var(--err-glow)", borderBottom: "1px solid var(--err)" }}>
          <div className="row gap2 t-body-sm" style={{ color: "var(--err)" }}>
            <Icon name="alert-triangle" size={16} />
            <span>{err}</span>
          </div>
          <button className="iconbtn" onClick={() => setErr(null)}>✕</button>
        </div>
      )}
      {note && (
        <div className="row spread" style={{ padding: "10px 24px", background: "var(--signal-glow)", borderBottom: "1px solid var(--signal)" }}>
          <div className="row gap2 t-body-sm" style={{ color: "var(--signal)" }}>
            <Icon name="info" size={16} />
            <span>{note}</span>
          </div>
          <button className="iconbtn" onClick={() => setNote(null)}>✕</button>
        </div>
      )}

      {/* Main Body */}
      <div className="grow scroll-y" style={{ padding: 24 }}>
        {/* TAB 1: MY INTEGRATIONS */}
        {tab === "my" && (
          <div className="col gap3">
            {installedItems.length === 0 ? (
              <EmptyState
                icon="plug"
                title="No integrations connected yet"
                sub="Explore the catalog or register an MCP server to equip Alberto with external capabilities."
                action={
                  <button className="btn btn-primary" onClick={() => setTab("explore")}>
                    <Icon name="search" size={15} /> Browse Catalog
                  </button>
                }
              />
            ) : (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))",
                  gap: 16,
                }}
              >
                {installedItems.map((item) => (
                  <div
                    key={item.id}
                    className="card hoverable col"
                    onClick={() => setSelectedItem(item)}
                    style={{
                      padding: 18,
                      borderRadius: "var(--radius)",
                      border: "1px solid var(--line-strong)",
                      cursor: "pointer",
                      gap: 12,
                      background: "var(--bg-1)",
                    }}
                  >
                    <div className="row spread">
                      <div className="row gap2">
                        <Tile icon={item.icon || "plug"} color="var(--signal)" size={36} />
                        <div className="col">
                          <span style={{ fontWeight: 600, fontSize: 15 }}>{item.name}</span>
                          <span className="mono-sm fg-2" style={{ fontSize: 11 }}>
                            {item.kind.startsWith("channel")
                              ? "Independent Channel Gateway"
                              : item.kind === "raw_mcp"
                              ? "Remote MCP Server"
                              : "REST Connector"}
                          </span>
                        </div>
                      </div>
                      <div className="row gap1" style={{ alignItems: "center" }}>
                        {item.status_detail === "Routing needs review" && (
                          <span className="badge" style={{ background: "rgba(245, 158, 11, 0.15)", color: "#f59e0b", fontSize: 11 }}>
                            ⚠ Review Required
                          </span>
                        )}
                        <StatusBadge status={item.status} />
                      </div>
                    </div>

                    <div className="t-body-sm fg-2 truncate-2" style={{ minHeight: 38 }}>
                      {item.summary}
                    </div>

                    <div
                      className="row spread"
                      style={{
                        paddingTop: 10,
                        borderTop: "1px solid var(--line)",
                        fontSize: 12,
                        color: "var(--fg-2)",
                      }}
                    >
                      <div className="row gap2">
                        <span className="badge" title="Active tools / Discovered capabilities">
                          <Icon name="tools" size={12} /> {item.enabled_tools} / {item.total_tools} tools
                        </span>
                        {item.account && (
                          <span className="typechip truncate" style={{ maxWidth: 120 }}>
                            {item.account}
                          </span>
                        )}
                      </div>

                      <div className="row gap1" onClick={(e) => e.stopPropagation()}>
                        {item.status === "needs_auth" ? (
                          <button
                            className="btn btn-primary btn-xs"
                            onClick={() => startOAuthFlow(item.slug)}
                            disabled={busySlug === item.slug}
                          >
                            <Icon name="lock" size={12} /> Connect
                          </button>
                        ) : (
                          <button
                            className="btn btn-ghost btn-xs"
                            title="Refresh tools"
                            onClick={() => handleSyncItem(item)}
                            disabled={busySlug === item.slug}
                          >
                            <Icon name="refresh" size={13} />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* TAB 2: EXPLORE CATALOG */}
        {tab === "explore" && (
          <div className="col gap3">
            {/* Search and Filters */}
            <div className="row spread gap2">
              <div className="row gap2 grow" style={{ maxWidth: 420 }}>
                <input
                  type="search"
                  className="input grow"
                  placeholder="Search connectors by name, service or protocol…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>

              <div className="row gap1">
                <button
                  className={`btn btn-xs ${filterCategory === "all" ? "btn-secondary" : "btn-ghost"}`}
                  onClick={() => setFilterCategory("all")}
                >
                  All ({catalog.length})
                </button>
                {categories.map((c) => (
                  <button
                    key={c}
                    className={`btn btn-xs ${filterCategory === c ? "btn-secondary" : "btn-ghost"}`}
                    onClick={() => setFilterCategory(c)}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>

            {/* Catalog Grid */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
                gap: 16,
              }}
            >
              {/* Featured Communication Channels (Integrations v3) */}
              <div
                className="card col spread"
                style={{
                  padding: 18,
                  borderRadius: "var(--radius)",
                  border: "1px solid rgba(99, 102, 241, 0.3)",
                  background: "var(--bg-1)",
                  gap: 12,
                }}
              >
                <div className="col gap2">
                  <div className="row spread">
                    <Tile icon="msg" color="var(--accent, #6366f1)" size={36} />
                    <span className="typechip" style={{ background: "rgba(99, 102, 241, 0.15)", color: "#818cf8" }}>
                      Channel Gateway
                    </span>
                  </div>
                  <div className="col">
                    <span style={{ fontWeight: 600, fontSize: 15 }}>Telegram Bot Channel</span>
                    <span className="fg-2 t-caption">Independent Communication Channel</span>
                  </div>
                  <p className="t-body-sm fg-2" style={{ margin: 0, minHeight: 40 }}>
                    Bi-directional Telegram Bot API gateway. Route inbound chat to Master Agent, subagents, or workflows with identity challenge pairing.
                  </p>
                </div>
                <div className="row spread" style={{ paddingTop: 12, borderTop: "1px solid var(--line)" }}>
                  <span className="badge">
                    <Icon name="bot" size={12} /> Bot Token
                  </span>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => {
                      setNewChannelType("telegram");
                      setNewChannelName("Telegram Bot Channel");
                      setNewChannelOpen(true);
                    }}
                  >
                    <Icon name="plus" size={14} /> Configure
                  </button>
                </div>
              </div>

              <div
                className="card col spread"
                style={{
                  padding: 18,
                  borderRadius: "var(--radius)",
                  border: "1px solid rgba(59, 130, 246, 0.3)",
                  background: "var(--bg-1)",
                  gap: 12,
                }}
              >
                <div className="col gap2">
                  <div className="row spread">
                    <Tile icon="mail" color="#3b82f6" size={36} />
                    <span className="typechip" style={{ background: "rgba(59, 130, 246, 0.15)", color: "#60a5fa" }}>
                      Channel Gateway
                    </span>
                  </div>
                  <div className="col">
                    <span style={{ fontWeight: 600, fontSize: 15 }}>Email Inbound & Outbound</span>
                    <span className="fg-2 t-caption">Independent Communication Channel</span>
                  </div>
                  <p className="t-body-sm fg-2" style={{ margin: 0, minHeight: 40 }}>
                    Webhook mail ingestion from Mailgun, SendGrid, or Postmark with authenticated outbound SMTP reply delivery.
                  </p>
                </div>
                <div className="row spread" style={{ paddingTop: 12, borderTop: "1px solid var(--line)" }}>
                  <span className="badge">
                    <Icon name="mail" size={12} /> Webhook + SMTP
                  </span>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => {
                      setNewChannelType("email");
                      setNewChannelName("Email Communication Channel");
                      setNewChannelOpen(true);
                    }}
                  >
                    <Icon name="plus" size={14} /> Configure
                  </button>
                </div>
              </div>

              {filteredCatalog.map((cat) => {
                const isInstalled = installs.some((i) => i.slug === cat.slug);
                return (
                  <div
                    key={cat.slug}
                    className="card col spread"
                    style={{
                      padding: 18,
                      borderRadius: "var(--radius)",
                      border: "1px solid var(--line-strong)",
                      background: "var(--bg-1)",
                      gap: 12,
                    }}
                  >
                    <div className="col gap2">
                      <div className="row spread">
                        <Tile icon={cat.icon || "plug"} color="var(--signal)" size={36} />
                        <span className="typechip">{cat.type || "Connector"}</span>
                      </div>
                      <div className="col">
                        <span style={{ fontWeight: 600, fontSize: 15 }}>{cat.name}</span>
                        <span className="fg-2 t-caption">{cat.categories?.[0] || (cat as any).category || "Integration"}</span>
                      </div>
                      <p className="t-body-sm fg-2" style={{ margin: 0, minHeight: 40 }}>
                        {cat.summary}
                      </p>
                    </div>

                    <div
                      className="row spread"
                      style={{
                        paddingTop: 12,
                        borderTop: "1px solid var(--line)",
                      }}
                    >
                      <span className="badge">
                        <Icon name="key" size={12} /> {cat.auth?.kind || (cat as any).auth_kind || "Token"}
                      </span>

                      {isInstalled ? (
                        <span className="badge" style={{ color: "var(--signal)" }}>
                          <Icon name="check" size={13} /> Installed
                        </span>
                      ) : (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => startOAuthFlow(cat.slug)}
                          disabled={busySlug === cat.slug}
                        >
                          <Icon name="plus" size={14} /> Connect
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* TAB 3: CUSTOM INTEGRATIONS */}
        {tab === "custom" && (
          <div className="col gap4" style={{ maxWidth: 840 }}>
            {/* Card 1: Remote MCP Server */}
            <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
              <div className="row spread">
                <div className="col gap1">
                  <div className="t-h3">Connect Remote MCP Server</div>
                  <div className="t-body-sm fg-2">
                    Attach any Model Context Protocol server via HTTP SSE or local stdio stream.
                  </div>
                </div>
                <button className="btn btn-primary btn-sm" onClick={() => setAddMcpOpen(true)}>
                  <Icon name="plus" size={14} /> Register MCP Server
                </button>
              </div>
            </div>

            {/* Card 2: Custom REST Manifest */}
            <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
              <div className="col gap1">
                <div className="t-h3">Install Custom Connector Manifest</div>
                <div className="t-body-sm fg-2">
                  Paste or author a custom REST connector JSON manifest with request templates and schemas.
                </div>
              </div>

              {examples.length > 0 && (
                <div className="row gap2 wrap">
                  <span className="t-caption fg-2">Starter Templates:</span>
                  {examples.map((ex) => (
                    <button
                      key={ex.slug}
                      className="btn btn-ghost btn-xs"
                      onClick={() => {
                        setCustomManifest(typeof ex.manifest === "string" ? ex.manifest : JSON.stringify(ex.manifest, null, 2));
                        setValidationErr(null);
                      }}
                    >
                      {ex.name}
                    </button>
                  ))}
                </div>
              )}

              <Field label="Connector Manifest (JSON)">
                <textarea
                  className="textarea mono"
                  rows={10}
                  placeholder={`{\n  "schema_version": "forge.connector/1",\n  "slug": "custom-api",\n  "name": "Custom REST API",\n  "auth": { "kind": "api_key", ... }\n}`}
                  value={customManifest}
                  onChange={(e) => setCustomManifest(e.target.value)}
                />
              </Field>

              {validationErr && (
                <div className="badge badge-err" style={{ padding: 8 }}>
                  <Icon name="alert-triangle" size={14} /> {validationErr}
                </div>
              )}

              <div className="row spread">
                <div className="row gap2">
                  <span className="t-caption fg-2">Credential Isolation:</span>
                  <select
                    className="select"
                    value={customAuthMode}
                    onChange={(e) => setCustomAuthMode(e.target.value)}
                  >
                    <option value="shared">Workspace Shared</option>
                    <option value="per_user">Per-User Personal</option>
                  </select>
                </div>

                <button
                  className="btn btn-primary"
                  disabled={!customManifest.trim() || validating}
                  onClick={async () => {
                    setValidating(true);
                    setValidationErr(null);
                    try {
                      const parsed = JSON.parse(customManifest);
                      const val = await api.validateConnectorManifest(project.id, parsed);
                      if (!val.ok) throw new Error(val.error || "Manifest validation failed");

                      await api.installCustomConnector(project.id, {
                        manifest: parsed,
                        values: customValues,
                        auth_mode: customAuthMode,
                      });
                      setCustomManifest("");
                      reload();
                      setTab("my");
                    } catch (e: any) {
                      setValidationErr(e?.message || "Invalid JSON or manifest structure");
                    } finally {
                      setValidating(false);
                    }
                  }}
                >
                  <Icon name="check" size={15} /> Install Custom Connector
                </button>
              </div>
            </div>
          </div>
        )}
        {/* TAB 4: ADVANCED SETTINGS */}
        {tab === "advanced" && (
          <div className="col gap4">
            <div className="row spread" style={{ borderBottom: "1px solid var(--line)", paddingBottom: 16 }}>
              <div className="col gap1">
                <span className="t-h2" style={{ margin: 0 }}>Advanced Integration Settings</span>
                <div className="t-caption fg-2">
                  Configure authentication providers, shared OAuth callback credentials, and low-level MCP server transports.
                </div>
              </div>
              <div className="row gap1" style={{ background: "var(--bg-2)", padding: 3, borderRadius: 8 }}>
                <button
                  className={`btn btn-sm ${advancedSubTab === "auth" ? "btn-secondary" : "btn-ghost"}`}
                  onClick={() => setAdvancedSubTab("auth")}
                >
                  <Icon name="shield-check" size={13} /> Auth Providers
                </button>
                <button
                  className={`btn btn-sm ${advancedSubTab === "oauth" ? "btn-secondary" : "btn-ghost"}`}
                  onClick={() => setAdvancedSubTab("oauth")}
                >
                  <Icon name="key" size={13} /> Shared OAuth
                </button>
                <button
                  className={`btn btn-sm ${advancedSubTab === "mcp" ? "btn-secondary" : "btn-ghost"}`}
                  onClick={() => setAdvancedSubTab("mcp")}
                >
                  <Icon name="connect" size={13} /> Advanced MCP
                </button>
              </div>
            </div>

            {advancedSubTab === "auth" && (
              <div className="col gap3">
                <AuthProvidersScreen project={project} />
              </div>
            )}

            {advancedSubTab === "oauth" && (
              <div className="col gap3" style={{ maxWidth: 840 }}>
                <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
                  <div className="t-h3">Shared OAuth 2.0 Client Configuration</div>
                  <div className="t-body-sm fg-2">
                    Alberto supports workspace-wide OAuth 2.0 app credentials for Google, Microsoft, GitHub, and custom IdPs.
                  </div>
                  <div className="col gap2" style={{ padding: 16, background: "var(--bg-2)", borderRadius: 8 }}>
                    <div className="row spread">
                      <span className="mono-sm fg-2">Default Callback URI:</span>
                      <span className="mono-sm" style={{ fontWeight: 600 }}>/v1/auth/callback/oauth2</span>
                    </div>
                    <div className="row spread">
                      <span className="mono-sm fg-2">Credential Storage:</span>
                      <span className="badge" style={{ color: "var(--signal)" }}>Fernet AES-256 encrypted</span>
                    </div>
                    <div className="row spread">
                      <span className="mono-sm fg-2">Token Refresh Policy:</span>
                      <span className="mono-sm">Autonomous pre-expiry renewal via refresh_token</span>
                    </div>
                  </div>
                  <div className="t-caption fg-3">
                    To register a new OAuth provider client, open the <strong>Auth Providers</strong> tab or install a catalog connector requiring OAuth.
                  </div>
                </div>
              </div>
            )}

            {advancedSubTab === "mcp" && (
              <div className="col gap3" style={{ maxWidth: 840 }}>
                <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
                  <div className="row spread">
                    <div className="col gap1">
                      <div className="t-h3">Registered Model Context Protocol Clients</div>
                      <div className="t-body-sm fg-2">
                        Inspect low-level SSE endpoints, stdio transports, and discovered tools.
                      </div>
                    </div>
                    <button className="btn btn-primary btn-sm" onClick={() => setAddMcpOpen(true)}>
                      <Icon name="plus" size={14} /> Register MCP Server
                    </button>
                  </div>

                  {mcpClients.length === 0 ? (
                    <div className="t-body-sm fg-2" style={{ padding: 16, textAlign: "center", background: "var(--bg-2)", borderRadius: 8 }}>
                      No direct MCP servers registered yet. Connect a remote server or install a catalog MCP connector.
                    </div>
                  ) : (
                    <div className="col gap2">
                      {mcpClients.map((client) => (
                        <div key={client.id} className="row spread" style={{ padding: "12px 16px", background: "var(--bg-2)", borderRadius: 8 }}>
                          <div className="col">
                            <span style={{ fontWeight: 600 }}>{client.name}</span>
                            <span className="mono-sm fg-2">{client.url || client.command || "Remote stream"} · Transport: {client.transport}</span>
                          </div>
                          <div className="row gap2" style={{ alignItems: "center" }}>
                            <span className="badge">{client.enabled ? "Enabled" : "Disabled"}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* MODAL: Add MCP Client */}
      <Modal open={addMcpOpen} onClose={() => setAddMcpOpen(false)} title="Register MCP Server">
        <div className="col gap3">
          <Field label="Server Name">
            <input
              type="text"
              className="input"
              placeholder="e.g. Home Assistant, Linear, GitHub MCP"
              value={newMcpName}
              onChange={(e) => setNewMcpName(e.target.value)}
            />
          </Field>
          <Field label="Transport Type">
            <select
              className="select"
              value={newMcpTransport}
              onChange={(e) => setNewMcpTransport(e.target.value as any)}
            >
              <option value="http">Streamable HTTP / SSE</option>
              <option value="sse">Direct Server-Sent Events (SSE)</option>
            </select>
          </Field>
          <Field label="Endpoint URL">
            <input
              type="url"
              className="input mono"
              placeholder="http://localhost:8000/sse or https://api.vendor.com/mcp"
              value={newMcpUrl}
              onChange={(e) => setNewMcpUrl(e.target.value)}
            />
          </Field>
          <div className="row spread" style={{ marginTop: 12 }}>
            <button className="btn btn-ghost" onClick={() => setAddMcpOpen(false)}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              disabled={!newMcpName.trim() || !newMcpUrl.trim()}
              onClick={handleAddMcpClient}
            >
              Register & Discover
            </button>
          </div>
        </div>
      </Modal>

      {/* MODAL: New Channel */}
      <Modal open={newChannelOpen} onClose={() => setNewChannelOpen(false)} title="Add Communication Channel">
        <div className="col gap3">
          <Field label="Channel Type">
            <select
              className="select"
              value={newChannelType}
              onChange={(e) => setNewChannelType(e.target.value as any)}
            >
              <option value="telegram">Telegram Bot API</option>
              <option value="email">Email (Inbound Webhook + SMTP Outbound)</option>
            </select>
          </Field>
          <Field label="Channel Name">
            <input
              className="input"
              value={newChannelName}
              placeholder={newChannelType === "telegram" ? "Alberto Telegram Bot" : "Alberto Support Email"}
              onChange={(e) => setNewChannelName(e.target.value)}
            />
          </Field>
          <div className="t-caption fg-2">
            Default destination will be set to <strong>Master Agent</strong> (Conversational AI Butler). Independent of workflows.
          </div>
          <div className="row end gap2" style={{ marginTop: 12 }}>
            <button className="btn btn-ghost" onClick={() => setNewChannelOpen(false)}>Cancel</button>
            <button
              className="btn btn-primary"
              disabled={!newChannelName.trim()}
              onClick={async () => {
                try {
                  const ch = await api.createChannel(project.id, {
                    type: newChannelType,
                    name: newChannelName.trim(),
                    target_type: "master_agent",
                  });
                  setNewChannelOpen(false);
                  setNewChannelName("");
                  await reload();
                  setSelectedItem({
                    id: `channel:${ch.id}`,
                    slug: ch.type,
                    name: ch.name,
                    summary: "Channel Gateway · Master Agent (Default)",
                    icon: ch.type === "telegram" ? "msg" : "mail",
                    kind: ch.type === "telegram" ? "channel_telegram" : "channel_email",
                    status: "connected",
                    total_tools: 0,
                    enabled_tools: 0,
                    source: "channel",
                    raw_channel: ch,
                  });
                } catch (err: any) {
                  alert(err.message || "Failed to create channel");
                }
              }}
            >
              Create Channel
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

/* ---------------- Detail View Component ---------------- */

function IntegrationDetailView({
  project,
  item,
  allTools,
  onBack,
  onReload,
  onConnect,
  onSync,
  onRemove,
  onOpenTool,
  onNav,
}: {
  project: any;
  item: UnifiedIntegrationItem;
  allTools: Tool[];
  onBack: () => void;
  onReload: () => void;
  onConnect: () => void;
  onSync: () => void;
  onRemove: () => void;
  onOpenTool?: (t: Tool) => void;
  onNav?: (screen: string) => void;
}) {
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const [schemaModalTool, setSchemaModalTool] = useState<any | null>(null);
  const [toolAnalysis, setToolAnalysis] = useState<Record<string, ToolAnalysisResult>>({});
  const [diagnosticReport, setDiagnosticReport] = useState<ToolDiagnosticReport | null>(null);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);
  const [toolSearch, setToolSearch] = useState("");

  // Filter tools associated with this integration
  const integrationTools = useMemo(() => {
    if (item.raw_connector) {
      const anyConn = item.raw_connector as any;
      const ids = new Set((anyConn.created_tool_ids as string[]) || []);
      return allTools.filter((t) => ids.has(t.id) || (item.raw_connector?.tool_set_id && (t as any).tool_set_id === item.raw_connector.tool_set_id));
    }
    if (item.raw_mcp) {
      const caps = item.raw_mcp.capabilities || {};
      const disc = (caps.tools as any[]) || [];
      const disabledSet = new Set(item.raw_mcp.disabled_tools || []);
      // Map MCP tools to standard Tool view models
      return disc.map((dt: any) => ({
        id: `mcp_tool:${item.raw_mcp!.id}:${dt.name}`,
        project_id: project.id,
        name: dt.name,
        kind: "mcp",
        config: {
          description: dt.description || "",
          input_schema: dt.input_schema,
          parameters: dt.input_schema,
        },
        enabled: !disabledSet.has(dt.name),
        auth_provider_id: item.raw_mcp!.auth_provider_id,
      })) as unknown as Tool[];
    }
    return [];
  }, [item, allTools, project.id]);

  const filteredTools = integrationTools.filter(
    (t) =>
      !toolSearch ||
      t.name.toLowerCase().includes(toolSearch.toLowerCase()) ||
      ((t.config?.description as string) || "").toLowerCase().includes(toolSearch.toLowerCase())
  );

  // Toggle tool activation
  const handleToggleActivation = async (tool: Tool) => {
    try {
      if (item.raw_connector) {
        await api.updateToolActivation(project.id, tool.id, { enabled: !tool.enabled });
      } else if (item.raw_mcp) {
        const disabled = new Set(item.raw_mcp.disabled_tools || []);
        if (tool.enabled) disabled.add(tool.name);
        else disabled.delete(tool.name);
        await api.updateMcpClient(project.id, item.raw_mcp.id, {
          disabled_tools: Array.from(disabled),
        });
      }
      onReload();
    } catch (e: any) {
      alert(`Activation update failed: ${e?.message || e}`);
    }
  };

  // Run Tool Manager analysis on a tool
  const runToolAnalysis = async (tool: Tool) => {
    setLoadingAnalysis(true);
    try {
      const res = await api.toolManagerAnalyze(project.id, {
        tool_id: tool.id,
        name: tool.name,
        description: (tool.config?.description as string) || "",
        input_schema: tool.config?.input_schema || tool.config?.parameters,
      });
      setToolAnalysis((prev) => ({ ...prev, [tool.id]: res }));
    } catch (e: any) {
      alert(`Analysis failed: ${e?.message || e}`);
    } finally {
      setLoadingAnalysis(false);
    }
  };

  return (
    <div className="col grow" style={{ minHeight: 0, background: "var(--bg-0)" }}>
      {/* Detail Top Header */}
      <div
        className="row spread"
        style={{
          padding: "16px 24px",
          borderBottom: "1px solid var(--line-strong)",
          background: "var(--bg-1)",
        }}
      >
        <div className="row gap3">
          <button className="btn btn-ghost btn-sm" onClick={onBack}>
            <Icon name="arrow-left" size={14} /> Integrations
          </button>
          <div className="divider-v" />
          <div className="row gap2">
            <Tile icon={item.icon || "plug"} color="var(--signal)" size={32} />
            <div className="col">
              <span className="t-h3" style={{ margin: 0 }}>{item.name}</span>
              <span className="fg-2 t-caption mono-sm">{item.slug}</span>
            </div>
            <StatusBadge status={item.status} />
          </div>
        </div>

        <div className="row gap2">
          {item.status === "needs_auth" && (
            <button className="btn btn-primary btn-sm" onClick={onConnect}>
              <Icon name="lock" size={14} /> Connect Account
            </button>
          )}
          <button className="btn btn-secondary btn-sm" onClick={onSync}>
            <Icon name="refresh" size={14} /> Sync Capabilities
          </button>
          <button className="btn btn-ghost btn-sm" style={{ color: "var(--err)" }} onClick={onRemove}>
            <Icon name="trash" size={14} /> Disconnect
          </button>
        </div>
      </div>

      {/* Sub-tabs */}
      <div
        className="row gap2"
        style={{
          padding: "0 24px",
          borderBottom: "1px solid var(--line)",
          background: "var(--bg-1)",
        }}
      >
        <button
          className={`tabbtn ${detailTab === "overview" ? "active" : ""}`}
          onClick={() => setDetailTab("overview")}
        >
          Overview
        </button>
        <button
          className={`tabbtn ${detailTab === "tools" ? "active" : ""}`}
          onClick={() => setDetailTab("tools")}
        >
          Tools & Capabilities ({integrationTools.length})
        </button>
        <button
          className={`tabbtn ${detailTab === "config" ? "active" : ""}`}
          onClick={() => setDetailTab("config")}
        >
          Configuration
        </button>
        <button
          className={`tabbtn ${detailTab === "diagnostics" ? "active" : ""}`}
          onClick={() => setDetailTab("diagnostics")}
        >
          Diagnostics
        </button>
      </div>

      {/* Content Area */}
      <div className="grow scroll-y" style={{ padding: 24 }}>
        {/* SUBTAB: OVERVIEW */}
        {detailTab === "overview" && (
          <div className="col gap4" style={{ maxWidth: 760 }}>
            <div className="card col gap3" style={{ padding: 20 }}>
              <div className="t-h3">Integration Overview</div>
              <p className="t-body fg-2">{item.summary}</p>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: 16,
                  marginTop: 8,
                }}
              >
                <div className="col gap1">
                  <span className="t-caption fg-2">Integration Protocol</span>
                  <span className="badge">{item.kind}</span>
                </div>
                <div className="col gap1">
                  <span className="t-caption fg-2">Authentication Method</span>
                  <span className="badge">{item.auth_kind || "None / Key"}</span>
                </div>
                <div className="col gap1">
                  <span className="t-caption fg-2">Credential Scope</span>
                  <span>{item.account || "Default"}</span>
                </div>
                <div className="col gap1">
                  <span className="t-caption fg-2">Last Synchronized</span>
                  <span className="mono-sm">{item.last_verified ? new Date(item.last_verified).toLocaleString() : "Never"}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* SUBTAB: TOOLS & CAPABILITIES */}
        {detailTab === "tools" && (
          <div className="col gap3">
            <div className="row spread">
              <input
                type="search"
                className="input"
                style={{ maxWidth: 360 }}
                placeholder="Search discovered tools…"
                value={toolSearch}
                onChange={(e) => setToolSearch(e.target.value)}
              />
              <span className="t-caption fg-2">
                {filteredTools.length} tools available
              </span>
            </div>

            <div className="col gap2">
              {filteredTools.map((t) => {
                const analysis = toolAnalysis[t.id];
                const effect = analysis?.effect || "read";
                const risk = analysis?.risk || "low";

                return (
                  <div
                    key={t.id}
                    className="card col gap2"
                    style={{
                      padding: 16,
                      background: "var(--bg-1)",
                      border: "1px solid var(--line)",
                    }}
                  >
                    <div className="row spread">
                      <div className="row gap2">
                        <Toggle
                          on={Boolean(t.enabled)}
                          onChange={() => handleToggleActivation(t)}
                        />
                        <span className="mono" style={{ fontWeight: 600 }}>
                          {t.name}
                        </span>
                        <EffectBadge effect={effect} />
                        <RiskBadge risk={risk} />
                      </div>

                      <div className="row gap2">
                        <button
                          className="btn btn-ghost btn-xs"
                          onClick={() => setSchemaModalTool(t)}
                        >
                          <Icon name="code" size={13} /> Schema
                        </button>
                        <button
                          className="btn btn-ghost btn-xs"
                          disabled={loadingAnalysis}
                          onClick={() => runToolAnalysis(t)}
                        >
                          <Icon name="bot" size={13} /> Analyze
                        </button>
                        {onOpenTool && (
                          <button
                            className="btn btn-ghost btn-xs"
                            onClick={() => onOpenTool(t)}
                          >
                            <Icon name="arrow-up-right" size={13} /> Open in Tools
                          </button>
                        )}
                        {onNav && (
                          <button
                            className="btn btn-secondary btn-xs"
                            onClick={() => onNav("integrations-playground")}
                            title="Test this tool in Integrations Playground"
                            style={{ gap: 4 }}
                          >
                            <Icon name="playground" size={12} /> Test
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="t-body-sm fg-2">
                      {(t.config?.description as string) || "No description provided."}
                    </div>

                    {analysis && (
                      <div
                        className="col gap1"
                        style={{
                          background: "var(--bg-2)",
                          padding: 10,
                          borderRadius: 6,
                          fontSize: 12,
                        }}
                      >
                        <div className="row spread">
                          <span className="fg-2">Category: <b>{analysis.category}</b></span>
                          <span className="fg-2">Recommended Activation: <b>{analysis.recommended_activation}</b></span>
                        </div>
                        {analysis.warnings?.length > 0 && (
                          <div style={{ color: "var(--warn)" }}>
                            Warnings: {analysis.warnings.join("; ")}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* SUBTAB: CONFIGURATION */}
        {detailTab === "config" && (
          <div className="col gap4" style={{ maxWidth: 680 }}>
            <div className="card col gap3" style={{ padding: 20 }}>
              <div className="t-h3">Connection Settings</div>
              {item.raw_mcp ? (
                <Field label="MCP Server URL">
                  <input
                    type="text"
                    className="input mono"
                    defaultValue={item.raw_mcp.url || ""}
                    disabled
                  />
                </Field>
              ) : (
                <Field label="Integration Slug">
                  <input
                    type="text"
                    className="input mono"
                    defaultValue={item.slug}
                    disabled
                  />
                </Field>
              )}
            </div>
          </div>
        )}

        {/* SUBTAB: DIAGNOSTICS */}
        {detailTab === "diagnostics" && (
          <div className="col gap4" style={{ maxWidth: 760 }}>
            <div className="card col gap3" style={{ padding: 20 }}>
              <div className="row spread">
                <div className="t-h3">Health & Diagnostics</div>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={async () => {
                    if (integrationTools.length > 0) {
                      const rep = await api.toolManagerDiagnose(project.id, {
                        tool_id: integrationTools[0].id,
                      });
                      setDiagnosticReport(rep);
                    }
                  }}
                >
                  <Icon name="activity" size={14} /> Run Tool Diagnostics
                </button>
              </div>

              {diagnosticReport ? (
                <div className="col gap2" style={{ background: "var(--bg-2)", padding: 14, borderRadius: 8 }}>
                  <div className="row spread">
                    <span className="badge">Status: {diagnosticReport.health_status}</span>
                    <span className="badge">Root Cause: {diagnosticReport.root_cause_category}</span>
                  </div>
                  <p className="t-body-sm">{diagnosticReport.summary}</p>
                  {diagnosticReport.recommendations?.length > 0 && (
                    <ul className="t-caption fg-2" style={{ paddingLeft: 16 }}>
                      {diagnosticReport.recommendations.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : (
                <p className="t-body-sm fg-2">
                  No active execution errors recorded. Click above to run Tool Manager diagnostic inspection.
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Schema Modal */}
      {schemaModalTool && (
        <Modal
          open={Boolean(schemaModalTool)}
          onClose={() => setSchemaModalTool(null)}
          title={`Schema: ${schemaModalTool.name}`}
        >
          <pre
            className="mono scroll-y"
            style={{
              padding: 14,
              background: "var(--bg-2)",
              borderRadius: 6,
              maxHeight: 400,
              fontSize: 12,
            }}
          >
            {JSON.stringify(schemaModalTool.config?.input_schema || schemaModalTool.config?.parameters || {}, null, 2)}
          </pre>
        </Modal>
      )}
    </div>
  );
}

/* ---------------- Channel Detail View Component ---------------- */

function ChannelDetailView({
  project,
  channel,
  workflows,
  agents,
  onBack,
  onReload,
  onNav,
}: {
  project: any;
  channel: Channel;
  workflows: any[];
  agents: any[];
  onBack: () => void;
  onReload: () => void;
  onNav?: (screen: string) => void;
}) {
  const [tab, setTab] = useState<"overview" | "connection" | "pairing" | "routing" | "diagnostics">("overview");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const isTg = channel.type === "telegram";
  const [name, setName] = useState(channel.name || "");
  const [enabled, setEnabled] = useState(channel.enabled);
  const [tgToken, setTgToken] = useState((channel.config || {}).bot_token || "");
  const [tgTransport, setTgTransport] = useState<"polling" | "webhook">((channel.config || {}).transport || "webhook");

  // Email config
  const smtp = channel.config?.smtp || {};
  const [smtpHost, setSmtpHost] = useState(smtp.host || "");
  const [smtpPort, setSmtpPort] = useState(smtp.port ?? 587);
  const [smtpUser, setSmtpUser] = useState(smtp.username || "");
  const [smtpFrom, setSmtpFrom] = useState(smtp.from || "");
  const [smtpPassRef, setSmtpPassRef] = useState(smtp.password_ref || "");
  const [emailProvider, setEmailProvider] = useState((channel.config || {}).provider || "mailgun");

  // Pairing state
  const [activePairing, setActivePairing] = useState<ChannelPairingOut | null>(null);
  const [pairingTtlRemaining, setPairingTtlRemaining] = useState<number | null>(null);
  const [manualCode, setManualCode] = useState("");
  const [manualSender, setManualSender] = useState("");
  const [manualLabel, setManualLabel] = useState("");
  const [identities, setIdentities] = useState<ChannelIdentityOut[]>([]);
  const [loadingIdentities, setLoadingIdentities] = useState(false);

  // Routing state
  const [targetType, setTargetType] = useState<string>(channel.target_type || "master_agent");
  const [targetId, setTargetId] = useState<string>(channel.target_id || "");
  const [routes, setRoutes] = useState<any[]>(channel.routes || []);
  const [newCmd, setNewCmd] = useState("");
  const [newCmdTargetType, setNewCmdTargetType] = useState("workflow");
  const [newCmdTargetId, setNewCmdTargetId] = useState("");

  // Diagnostics state
  const [diagnostics, setDiagnostics] = useState<ChannelDiagnostics | null>(null);
  const [runningDiag, setRunningDiag] = useState(false);
  const [testRecipient, setTestRecipient] = useState("");
  const [testText, setTestText] = useState("Hello from Alberto channel diagnostics!");
  const [sendingTest, setSendingTest] = useState(false);
  const [testSendResult, setTestSendResult] = useState<any | null>(null);

  // Load identities
  const loadIdentities = useCallback(async () => {
    setLoadingIdentities(true);
    try {
      const list = await api.listChannelIdentities(project.id, channel.id);
      setIdentities(list);
    } catch {
      setIdentities([]);
    } finally {
      setLoadingIdentities(false);
    }
  }, [project.id, channel.id]);

  useEffect(() => {
    if (tab === "pairing") {
      loadIdentities();
    }
  }, [tab, loadIdentities]);

  // Pairing TTL timer countdown
  useEffect(() => {
    if (!activePairing) return;
    const interval = setInterval(() => {
      const exp = new Date(activePairing.expires_at).getTime();
      const now = Date.now();
      const diff = Math.max(0, Math.round((exp - now) / 1000));
      setPairingTtlRemaining(diff);
      if (diff <= 0) {
        setActivePairing(null);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [activePairing]);

  const handleToggleEnabled = async () => {
    try {
      const next = !enabled;
      setEnabled(next);
      await api.updateChannel(project.id, channel.id, { enabled: next });
      onReload();
    } catch (e: any) {
      setEnabled(!enabled);
      setErr(e.message || "Failed to update channel status");
    }
  };

  const handleSaveConnection = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const cfg: Record<string, any> = { ...channel.config };
      if (isTg) {
        if (tgToken) cfg.bot_token = tgToken;
        cfg.transport = tgTransport;
      } else {
        cfg.provider = emailProvider;
        cfg.smtp = {
          host: smtpHost,
          port: Number(smtpPort),
          username: smtpUser,
          from: smtpFrom,
          password_ref: smtpPassRef,
        };
      }
      await api.updateChannel(project.id, channel.id, { name, config: cfg });
      setMsg("Connection configuration saved successfully.");
      onReload();
    } catch (e: any) {
      setErr(e.message || "Failed to save connection");
    } finally {
      setBusy(false);
    }
  };

  const handleGeneratePairing = async () => {
    setBusy(true);
    setErr(null);
    try {
      const p = await api.createChannelPairing(project.id, channel.id);
      setActivePairing(p);
      setPairingTtlRemaining(p.ttl_seconds);
      setManualCode(p.code);
    } catch (e: any) {
      setErr(e.message || "Failed to generate pairing challenge");
    } finally {
      setBusy(false);
    }
  };

  const handleConfirmPairing = async () => {
    if (!manualCode.trim() || !manualSender.trim()) {
      setErr("Challenge code and external sender ID are required.");
      return;
    }
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const res = await api.confirmChannelPairing(project.id, {
        channel_id: channel.id,
        code: manualCode.trim().toUpperCase(),
        external_user_id: manualSender.trim(),
        display_label: manualLabel.trim() || undefined,
      });
      if (res.ok) {
        setMsg(`Identity '${manualSender}' successfully paired.`);
        setManualSender("");
        setManualLabel("");
        setActivePairing(null);
        await loadIdentities();
      }
    } catch (e: any) {
      setErr(e.message || "Pairing confirmation failed");
    } finally {
      setBusy(false);
    }
  };

  const handleRevokeIdentity = async (iid: string) => {
    if (!confirm("Revoke this paired external identity?")) return;
    try {
      await api.revokeChannelIdentity(project.id, channel.id, iid);
      await loadIdentities();
    } catch (e: any) {
      setErr(e.message || "Failed to revoke identity");
    }
  };

  const handleSaveRouting = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await api.setChannelRouting(project.id, channel.id, {
        target_type: targetType,
        target_id: targetType === "master_agent" ? null : targetId || null,
        routes,
      });
      setMsg("Channel routing policy updated successfully.");
      onReload();
    } catch (e: any) {
      setErr(e.message || "Failed to update routing policy");
    } finally {
      setBusy(false);
    }
  };

  const handleAddRoute = () => {
    if (!newCmd.trim()) return;
    const formatted = newCmd.trim().startsWith("/") ? newCmd.trim() : `/${newCmd.trim()}`;
    setRoutes((r) => [
      ...r.filter((x) => x.command !== formatted),
      {
        command: formatted,
        target_type: newCmdTargetType,
        target_id: newCmdTargetType === "master_agent" ? null : newCmdTargetId || null,
      },
    ]);
    setNewCmd("");
  };

  const handleRemoveRoute = (cmd: string) => {
    setRoutes((r) => r.filter((x) => x.command !== cmd));
  };

  const handleRunDiagnostics = async () => {
    setRunningDiag(true);
    setErr(null);
    try {
      const rep = await api.diagnoseChannel(project.id, channel.id);
      setDiagnostics(rep);
    } catch (e: any) {
      setErr(e.message || "Diagnostic check failed");
    } finally {
      setRunningDiag(false);
    }
  };

  const handleSendTestMessage = async () => {
    if (!testRecipient.trim() || !testText.trim()) return;
    setSendingTest(true);
    setTestSendResult(null);
    try {
      const res = await api.sendChannelMessage(project.id, channel.id, {
        recipient: testRecipient.trim(),
        text: testText.trim(),
      });
      setTestSendResult(res);
    } catch (e: any) {
      setTestSendResult({ ok: false, error: e.message || "Failed to dispatch message" });
    } finally {
      setSendingTest(false);
    }
  };

  const handleDeleteChannel = async () => {
    if (!confirm("Are you sure you want to delete this channel?")) return;
    try {
      await api.deleteChannel(project.id, channel.id);
      onBack();
      onReload();
    } catch (e: any) {
      alert(e.message || "Failed to delete channel");
    }
  };

  const targetLabel =
    channel.target_type === "subagent"
      ? `Subagent: ${agents.find((a: any) => a.id === channel.target_id)?.name || channel.target_id || "Unset"}`
      : channel.target_type === "workflow"
      ? `Workflow: ${workflows.find((w: any) => w.id === channel.target_id)?.name || channel.target_id || "Unset"}`
      : "Master Agent (Conversational Butler)";

  return (
    <div className="col grow" style={{ minHeight: 0, background: "var(--bg-0)" }}>
      {/* Top Header */}
      <div
        className="row spread"
        style={{
          padding: "16px 24px",
          borderBottom: "1px solid var(--line-strong)",
          background: "var(--bg-1)",
        }}
      >
        <div className="row gap3" style={{ alignItems: "center" }}>
          <button className="btn btn-ghost btn-sm" onClick={onBack}>
            <Icon name="arrow-left" size={14} /> Integrations
          </button>
          <div className="divider-v" />
          <div className="row gap2" style={{ alignItems: "center" }}>
            <Tile icon={isTg ? "msg" : "mail"} color="var(--accent, #6366f1)" size={32} />
            <div className="col">
              <span className="t-h3" style={{ margin: 0 }}>{channel.name}</span>
              <span className="fg-2 t-caption mono-sm">
                {isTg ? "Telegram Bot Channel" : "Email Channel"} · ID: {channel.id}
              </span>
            </div>
            {enabled ? (
              <span className="badge" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.3)" }}>
                ● Active
              </span>
            ) : (
              <span className="badge" style={{ background: "rgba(148, 163, 184, 0.15)", color: "#94a3b8" }}>
                Disabled
              </span>
            )}
            {channel.routing_state === "needs_review" && (
              <span className="badge" style={{ background: "rgba(245, 158, 11, 0.15)", color: "#f59e0b", border: "1px solid rgba(245, 158, 11, 0.3)" }}>
                ⚠ Routing Needs Review
              </span>
            )}
          </div>
        </div>

        <div className="row gap2" style={{ alignItems: "center" }}>
          <Toggle on={enabled} onChange={handleToggleEnabled} />
          <button className="btn btn-ghost btn-sm" title="Delete Channel" onClick={handleDeleteChannel}>
            <Icon name="trash" size={14} />
          </button>
        </div>
      </div>

      {/* Segmented Navigation */}
      <div
        className="row spread"
        style={{
          padding: "0 24px",
          borderBottom: "1px solid var(--line)",
          background: "var(--bg-1)",
        }}
      >
        <div className="row gap1">
          {(["overview", "connection", "pairing", "routing", "diagnostics"] as const).map((t) => (
            <button
              key={t}
              className={`btn btn-sm ${tab === t ? "btn-secondary" : "btn-ghost"}`}
              style={{
                borderRadius: "8px 8px 0 0",
                textTransform: "capitalize",
                borderBottom: tab === t ? "2px solid var(--accent, #6366f1)" : "2px solid transparent",
              }}
              onClick={() => setTab(t)}
            >
              {t === "pairing" ? "Access & Pairing" : t}
            </button>
          ))}
        </div>
      </div>

      {/* Notifications */}
      {err && (
        <div className="row spread" style={{ padding: "10px 24px", background: "rgba(239, 68, 68, 0.15)", borderBottom: "1px solid #ef4444" }}>
          <span style={{ color: "#f87171", fontSize: 13 }}>{err}</span>
          <button className="iconbtn" onClick={() => setErr(null)}>✕</button>
        </div>
      )}
      {msg && (
        <div className="row spread" style={{ padding: "10px 24px", background: "rgba(34, 197, 94, 0.15)", borderBottom: "1px solid #22c55e" }}>
          <span style={{ color: "#4ade80", fontSize: 13 }}>{msg}</span>
          <button className="iconbtn" onClick={() => setMsg(null)}>✕</button>
        </div>
      )}

      {/* Tab Contents */}
      <div className="grow scroll-y" style={{ padding: 24, maxWidth: 860 }}>
        {/* 1. OVERVIEW */}
        {tab === "overview" && (
          <div className="col gap3">
            {(channel.routing_state === "needs_review" || channel.routing_state === "requires_review") && (
              <div
                className="col gap1"
                style={{
                  padding: "12px 16px",
                  borderRadius: 8,
                  background: "rgba(245, 158, 11, 0.12)",
                  border: "1px solid rgba(245, 158, 11, 0.4)",
                  color: "#f59e0b",
                }}
              >
                <div className="row gap2" style={{ alignItems: "center", fontWeight: 600 }}>
                  <Icon name="alert-triangle" size={16} />
                  <span>Legacy Channel Destination Review Required</span>
                </div>
                <div className="t-body-sm" style={{ color: "var(--fg-1)" }}>
                  This historical channel was migrated without an explicit destination workflow. Inbound message execution is paused until an administrator confirms the target destination in the Routing tab.
                </div>
                <div style={{ marginTop: 6 }}>
                  <button className="btn btn-secondary btn-xs" onClick={() => setTab("routing")}>
                    Review & Configure Routing →
                  </button>
                </div>
              </div>
            )}
            <div className="card col gap2" style={{ padding: 18, background: "var(--bg-1)" }}>
              <span className="t-h3">Channel Summary</span>
              <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 10, fontSize: 13 }}>
                <span className="fg-2">Default Destination:</span>
                <span style={{ fontWeight: 600 }}>{targetLabel}</span>
                <span className="fg-2">Effective Transport:</span>
                <span className="mono">{channel.state?.effective_transport || (isTg ? "webhook/polling" : "inbound webhook")}</span>
                <span className="fg-2">Routing State:</span>
                <span className="badge" style={{ width: "fit-content" }}>{channel.routing_state || "ok"}</span>
                {channel.inbound_url && (
                  <>
                    <span className="fg-2">Inbound Webhook URL:</span>
                    <div className="row gap1" style={{ alignItems: "center" }}>
                      <span className="mono-sm fg-1 truncate" style={{ maxWidth: 450 }}>{channel.inbound_url}</span>
                      <button className="btn btn-ghost btn-xs" onClick={() => navigator.clipboard.writeText(channel.inbound_url!)}>Copy</button>
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="row gap3 wrap">
              <div className="card col grow gap1" style={{ padding: 14, background: "var(--bg-1)" }}>
                <span className="fg-2 t-caption">Total Inbound Events</span>
                <span className="t-h2">{channel.state?.total_events || 0}</span>
              </div>
              <div className="card col grow gap1" style={{ padding: 14, background: "var(--bg-1)" }}>
                <span className="fg-2 t-caption">Paired Identities</span>
                <span className="t-h2">{channel.state?.paired_identities || identities.length}</span>
              </div>
              <div className="card col grow gap1" style={{ padding: 14, background: "var(--bg-1)" }}>
                <span className="fg-2 t-caption">Connection Status</span>
                <span className="t-h2" style={{ color: channel.state?.connected !== false ? "#4ade80" : "#f87171" }}>
                  {channel.state?.connected !== false ? "Connected" : "Disconnected"}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* 2. CONNECTION CONFIG */}
        {tab === "connection" && (
          <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
            <span className="t-h3">Connection & Secrets</span>
            <Field label="Channel Name">
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>

            {isTg ? (
              <>
                <Field label="Telegram Bot Token" help="Obtained from @BotFather. Securely resolved via project secrets.">
                  <input
                    type="password"
                    className="input mono"
                    placeholder="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
                    value={tgToken}
                    onChange={(e) => setTgToken(e.target.value)}
                  />
                </Field>
                <Field label="Transport Mode">
                  <select
                    className="select"
                    value={tgTransport}
                    onChange={(e) => setTgTransport(e.target.value as any)}
                  >
                    <option value="webhook">Webhook Mode (Recommended for production)</option>
                    <option value="polling">Long Polling Mode (Local dev behind NAT)</option>
                  </select>
                </Field>
                {channel.inbound_url && (
                  <Field label="Inbound Webhook URL (with Secret Token Header)">
                    <input className="input mono" readOnly value={channel.inbound_url} />
                  </Field>
                )}
              </>
            ) : (
              <>
                <Field label="Provider Verification Protocol">
                  <select
                    className="select"
                    value={emailProvider}
                    onChange={(e) => setEmailProvider(e.target.value)}
                  >
                    <option value="mailgun">Mailgun (HMAC-SHA256 signature)</option>
                    <option value="shared_secret">Shared Secret Token / Header</option>
                    <option value="basic_auth">HTTP Basic Authentication</option>
                  </select>
                </Field>
                <span className="t-h4" style={{ marginTop: 8 }}>Outbound SMTP Credentials (for Butler Replies)</span>
                <div className="row gap2">
                  <div style={{ flex: 2 }}>
                    <Field label="SMTP Host">
                      <input className="input mono" placeholder="smtp.mailgun.org" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} />
                    </Field>
                  </div>
                  <div style={{ flex: 1 }}>
                    <Field label="Port">
                      <input type="number" className="input mono" value={smtpPort} onChange={(e) => setSmtpPort(Number(e.target.value))} />
                    </Field>
                  </div>
                </div>
                <div className="row gap2">
                  <div style={{ flex: 1 }}>
                    <Field label="Username">
                      <input className="input mono" value={smtpUser} onChange={(e) => setSmtpUser(e.target.value)} />
                    </Field>
                  </div>
                  <div style={{ flex: 1 }}>
                    <Field label="From Address">
                      <input className="input mono" placeholder="butler@yourdomain.com" value={smtpFrom} onChange={(e) => setSmtpFrom(e.target.value)} />
                    </Field>
                  </div>
                </div>
                <Field label="Password Secret Reference" help="Pointer to encrypted secret store (e.g. secret://proj/smtp_pass).">
                  <input className="input mono" placeholder="secret://proj/smtp_password" value={smtpPassRef} onChange={(e) => setSmtpPassRef(e.target.value)} />
                </Field>
              </>
            )}

            <div className="row end" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={busy} onClick={handleSaveConnection}>
                {busy ? "Saving..." : "Save Connection Settings"}
              </button>
            </div>
          </div>
        )}

        {/* 3. ACCESS & PAIRING */}
        {tab === "pairing" && (
          <div className="col gap3">
            <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
              <div className="row spread">
                <div className="col gap1">
                  <span className="t-h3">One-Time Pairing Challenge</span>
                  <div className="t-caption fg-2">
                    External users must pair their Telegram handle or Email address with an Alberto account before interacting.
                  </div>
                </div>
                <button className="btn btn-primary btn-sm" disabled={busy} onClick={handleGeneratePairing}>
                  <Icon name="shield-check" size={14} /> Generate Code
                </button>
              </div>

              {activePairing && (
                <div
                  style={{
                    padding: 18,
                    borderRadius: 8,
                    background: "rgba(99, 102, 241, 0.1)",
                    border: "1px solid rgba(99, 102, 241, 0.3)",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <span className="t-caption fg-2">Send this 6-character challenge code from Telegram or Email:</span>
                  <span
                    className="mono"
                    style={{
                      fontSize: 32,
                      fontWeight: 700,
                      letterSpacing: 6,
                      color: "var(--accent, #6366f1)",
                    }}
                  >
                    {activePairing.code}
                  </span>
                  <span className="t-caption fg-2">
                    Expires in <strong>{pairingTtlRemaining ?? activePairing.ttl_seconds}s</strong> (SHA-256 protected, one-time use)
                  </span>
                </div>
              )}

              {/* Manual Confirmation Form for Dev Testing */}
              <div className="col gap2" style={{ paddingTop: 12, borderTop: "1px solid var(--line)" }}>
                <span className="t-h4">Manual Confirmation / Simulated Pairing</span>
                <div className="row gap2">
                  <div style={{ flex: 1 }}>
                    <Field label="Code">
                      <input className="input mono" placeholder="ABC123" value={manualCode} onChange={(e) => setManualCode(e.target.value)} />
                    </Field>
                  </div>
                  <div style={{ flex: 2 }}>
                    <Field label="External User ID">
                      <input className="input mono" placeholder="e.g. 12345678 or user@example.com" value={manualSender} onChange={(e) => setManualSender(e.target.value)} />
                    </Field>
                  </div>
                  <div style={{ flex: 2 }}>
                    <Field label="Display Label">
                      <input className="input" placeholder="e.g. @alice or Alice" value={manualLabel} onChange={(e) => setManualLabel(e.target.value)} />
                    </Field>
                  </div>
                </div>
                <div className="row end">
                  <button className="btn btn-secondary btn-sm" disabled={busy} onClick={handleConfirmPairing}>
                    Confirm Pairing
                  </button>
                </div>
              </div>
            </div>

            {/* Paired Identities Table */}
            <div className="card col gap2" style={{ padding: 18, background: "var(--bg-1)" }}>
              <span className="t-h3">Authorized Paired Identities ({identities.length})</span>
              {loadingIdentities ? (
                <div className="t-caption fg-2">Loading paired identities...</div>
              ) : identities.length === 0 ? (
                <div className="t-caption fg-2">No external senders paired yet. Generate a challenge code above.</div>
              ) : (
                <div className="col gap1">
                  {identities.map((id) => (
                    <div
                      key={id.id}
                      className="row spread"
                      style={{
                        padding: "10px 14px",
                        borderRadius: 6,
                        background: "var(--bg-2)",
                        alignItems: "center",
                      }}
                    >
                      <div className="row gap3" style={{ alignItems: "center" }}>
                        <span className="mono" style={{ fontWeight: 600 }}>{id.external_user_id}</span>
                        {id.display_label && <span className="typechip">{id.display_label}</span>}
                        <span className="t-caption fg-3">Paired {new Date(id.paired_at).toLocaleDateString()}</span>
                      </div>
                      <button className="btn btn-ghost btn-xs" onClick={() => handleRevokeIdentity(id.id)} title="Revoke pairing">
                        Revoke
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* 4. ROUTING */}
        {tab === "routing" && (
          <div className="col gap3">
            {(channel.routing_state === "needs_review" || channel.routing_state === "requires_review") && (
              <div
                className="col gap1"
                style={{
                  padding: "12px 16px",
                  borderRadius: 8,
                  background: "rgba(245, 158, 11, 0.12)",
                  border: "1px solid rgba(245, 158, 11, 0.4)",
                  color: "#f59e0b",
                }}
              >
                <div className="row gap2" style={{ alignItems: "center", fontWeight: 600 }}>
                  <Icon name="alert-triangle" size={16} />
                  <span>Routing Review Required</span>
                </div>
                <div className="t-body-sm" style={{ color: "var(--fg-1)" }}>
                  Select an explicit conversational target below (Master Agent, Subagent, or Workflow) and click <strong>"Save Routing Policy"</strong> to confirm destination and authorize inbound message execution.
                </div>
              </div>
            )}
            <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
              <span className="t-h3">Conversational Routing Destination</span>
              <div className="t-caption fg-2">
                Channels are decoupled from workflows. By default, incoming messages land in Master Agent.
              </div>

              <div className="col gap2">
                <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="targetType"
                    checked={targetType === "master_agent"}
                    onChange={() => {
                      setTargetType("master_agent");
                      setTargetId("");
                    }}
                  />
                  <div>
                    <span style={{ fontWeight: 600 }}>Master Agent (Recommended Default)</span>
                    <div className="t-caption fg-2">
                      Conversational AI Butler with persistent cross-session memory and autonomous tool delegation.
                    </div>
                  </div>
                </label>

                <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="targetType"
                    checked={targetType === "subagent"}
                    onChange={() => setTargetType("subagent")}
                  />
                  <div>
                    <span style={{ fontWeight: 600 }}>Specialized Subagent</span>
                    <div className="t-caption fg-2">Route directly to an expert subagent (e.g. Integration Manager or Curator).</div>
                  </div>
                </label>

                {targetType === "subagent" && (
                  <div style={{ marginLeft: 24 }}>
                    <Field label="Select Target Subagent">
                      <select className="select" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                        <option value="">Choose subagent...</option>
                        {agents.map((a) => (
                          <option key={a.id} value={a.id}>{a.name} ({a.role || a.id})</option>
                        ))}
                      </select>
                    </Field>
                  </div>
                )}

                <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="targetType"
                    checked={targetType === "workflow"}
                    onChange={() => setTargetType("workflow")}
                  />
                  <div>
                    <span style={{ fontWeight: 600 }}>Specific Workflow</span>
                    <div className="t-caption fg-2">Route messages into a deterministic LangGraph workflow execution.</div>
                  </div>
                </label>

                {targetType === "workflow" && (
                  <div style={{ marginLeft: 24 }}>
                    <Field label="Select Target Workflow">
                      <select className="select" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                        <option value="">Choose workflow...</option>
                        {workflows.map((w) => (
                          <option key={w.id} value={w.id}>{w.name} ({w.status})</option>
                        ))}
                      </select>
                    </Field>
                  </div>
                )}
              </div>

              {/* Custom Command Rules */}
              <div className="col gap2" style={{ paddingTop: 14, borderTop: "1px solid var(--line)" }}>
                <span className="t-h4">Custom Command Rules (e.g. /status, /help)</span>
                <div className="row gap2">
                  <input
                    className="input mono"
                    placeholder="/status"
                    style={{ flex: 1 }}
                    value={newCmd}
                    onChange={(e) => setNewCmd(e.target.value)}
                  />
                  <select
                    className="select"
                    style={{ flex: 1 }}
                    value={newCmdTargetType}
                    onChange={(e) => setNewCmdTargetType(e.target.value)}
                  >
                    <option value="workflow">Workflow</option>
                    <option value="subagent">Subagent</option>
                    <option value="master_agent">Master Agent</option>
                  </select>
                  {newCmdTargetType !== "master_agent" && (
                    <select
                      className="select"
                      style={{ flex: 2 }}
                      value={newCmdTargetId}
                      onChange={(e) => setNewCmdTargetId(e.target.value)}
                    >
                      <option value="">Select target...</option>
                      {newCmdTargetType === "workflow"
                        ? workflows.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)
                        : agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </select>
                  )}
                  <button className="btn btn-secondary btn-sm" onClick={handleAddRoute}>Add Rule</button>
                </div>

                {routes.length > 0 && (
                  <div className="col gap1" style={{ marginTop: 8 }}>
                    {routes.map((r, i) => (
                      <div key={i} className="row spread" style={{ padding: "8px 12px", background: "var(--bg-2)", borderRadius: 6 }}>
                        <div className="row gap2 mono-sm" style={{ alignItems: "center" }}>
                          <strong>{r.command}</strong> → <span>{r.target_type}: {r.target_id || "default"}</span>
                        </div>
                        <button className="btn btn-ghost btn-xs" onClick={() => handleRemoveRoute(r.command)}>✕</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="row end" style={{ marginTop: 12 }}>
                <button className="btn btn-primary" disabled={busy} onClick={handleSaveRouting}>
                  {busy ? "Saving..." : "Save Routing Policy"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 5. DIAGNOSTICS */}
        {tab === "diagnostics" && (
          <div className="col gap3">
            <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
              <div className="row spread">
                <div className="col gap1">
                  <span className="t-h3">Integration Manager Channel Diagnostics</span>
                  <div className="t-caption fg-2">
                    Evaluates transport connectivity, webhook secrets, pairing health, and delivery metrics.
                  </div>
                </div>
                <button className="btn btn-secondary btn-sm" disabled={runningDiag} onClick={handleRunDiagnostics}>
                  {runningDiag ? "Inspecting..." : "Run Channel Diagnostic"}
                </button>
              </div>

              {diagnostics && (
                <div className="col gap2" style={{ padding: 14, background: "var(--bg-2)", borderRadius: 8 }}>
                  <div className="row spread">
                    <span className="badge">Status: {diagnostics.status.toUpperCase()}</span>
                    <span className="mono-sm">Transport: {diagnostics.effective_transport}</span>
                  </div>
                  {diagnostics.issues.length > 0 ? (
                    <div>
                      <span className="fg-2 t-caption">Issues Identified:</span>
                      <ul style={{ margin: "4px 0", paddingLeft: 18, color: "#f87171", fontSize: 12 }}>
                        {diagnostics.issues.map((iss, i) => <li key={i}>{iss}</li>)}
                      </ul>
                    </div>
                  ) : (
                    <div style={{ color: "#4ade80", fontSize: 12 }}>✓ No critical connectivity issues detected.</div>
                  )}

                  {diagnostics.recommendations.length > 0 && (
                    <div>
                      <span className="fg-2 t-caption">Recommendations:</span>
                      <ul style={{ margin: "4px 0", paddingLeft: 18, fontSize: 12 }}>
                        {diagnostics.recommendations.map((rec, i) => <li key={i}>{rec}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* Test Outbound Send */}
              <div className="col gap2" style={{ paddingTop: 14, borderTop: "1px solid var(--line)" }}>
                <span className="t-h4">Outbound Send Test (Channel Delivery Service)</span>
                <Field label="Recipient (Telegram Chat ID or Email Address)">
                  <input
                    className="input mono"
                    placeholder={isTg ? "e.g. 123456789" : "recipient@example.com"}
                    value={testRecipient}
                    onChange={(e) => setTestRecipient(e.target.value)}
                  />
                </Field>
                <Field label="Test Message Body">
                  <textarea
                    className="textarea mono"
                    rows={2}
                    value={testText}
                    onChange={(e) => setTestText(e.target.value)}
                  />
                </Field>
                <div className="row end">
                  <button className="btn btn-primary btn-sm" disabled={sendingTest || !testRecipient.trim()} onClick={handleSendTestMessage}>
                    {sendingTest ? "Sending..." : "Send Test Message"}
                  </button>
                </div>

                {testSendResult && (
                  <div
                    style={{
                      padding: 10,
                      borderRadius: 6,
                      background: testSendResult.ok ? "rgba(34, 197, 94, 0.15)" : "rgba(239, 68, 68, 0.15)",
                      fontSize: 12,
                    }}
                  >
                    {testSendResult.ok ? (
                      <span style={{ color: "#4ade80" }}>
                        ✓ Message dispatched successfully. Delivery ID: {testSendResult.delivery_id}
                      </span>
                    ) : (
                      <span style={{ color: "#f87171" }}>
                        ✕ Failed to send: {testSendResult.error}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------------- Badges and Chips ---------------- */

function StatusBadge({ status }: { status: UnifiedIntegrationItem["status"] }) {
  if (status === "connected") {
    return (
      <span className="badge" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.3)" }}>
        ● Connected
      </span>
    );
  }
  if (status === "needs_auth") {
    return (
      <span className="badge" style={{ background: "rgba(245, 158, 11, 0.15)", color: "#f59e0b", border: "1px solid rgba(245, 158, 11, 0.3)" }}>
        ○ Needs Auth
      </span>
    );
  }
  return (
    <span className="badge" style={{ background: "rgba(239, 68, 68, 0.15)", color: "#ef4444", border: "1px solid rgba(239, 68, 68, 0.3)" }}>
      ✕ {status}
    </span>
  );
}

function EffectBadge({ effect }: { effect: string }) {
  const colors: Record<string, { bg: string; fg: string }> = {
    read: { bg: "rgba(16, 185, 129, 0.15)", fg: "#10b981" },
    write: { bg: "rgba(59, 130, 246, 0.15)", fg: "#3b82f6" },
    delete: { bg: "rgba(239, 68, 68, 0.15)", fg: "#ef4444" },
    unknown: { bg: "rgba(156, 163, 175, 0.15)", fg: "#9ca3af" },
  };
  const c = colors[effect] || colors.unknown;
  return (
    <span className="typechip" style={{ background: c.bg, color: c.fg }}>
      {effect.toUpperCase()}
    </span>
  );
}

function RiskBadge({ risk }: { risk: string }) {
  const colors: Record<string, string> = {
    low: "#10b981",
    medium: "#f59e0b",
    high: "#ef4444",
    critical: "#8b5cf6",
  };
  return (
    <span className="t-caption" style={{ color: colors[risk] || "#9ca3af", fontWeight: 600 }}>
      {risk.toUpperCase()}
    </span>
  );
}
