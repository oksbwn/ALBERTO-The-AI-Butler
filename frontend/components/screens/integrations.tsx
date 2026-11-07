"use client";
/* Unified Integrations Screen: Single management console for REST connectors,
   Remote MCP servers, custom APIs, OAuth 2.0 and API token authentication. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../icons";
import { EmptyState, Field, Modal, Tile, Toggle } from "../primitives";
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

import { MainTab, DetailTab, UnifiedIntegrationItem } from "./integrations/types";
import { StatusBadge, EffectBadge, RiskBadge } from "./integrations/badges";
import { IntegrationDetailView } from "./integrations/IntegrationDetailView";
import { ChannelDetailView } from "./integrations/ChannelDetailView";

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

  useEffect(() => {
    if (initialTab) {
      setTab(initialTab);
    }
  }, [initialTab]);

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
  const [newChannelToken, setNewChannelToken] = useState("");
  const [newChannelTransport, setNewChannelTransport] = useState<"auto" | "polling" | "webhook">("auto");
  const [newChannelTargetType, setNewChannelTargetType] = useState<"master_agent" | "subagent" | "workflow">("master_agent");
  const [newChannelTargetId, setNewChannelTargetId] = useState("");

  // UI states
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState("all");
  const [busySlug, setBusySlug] = useState<string | null>(null);

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

      const isHome = client.name.toLowerCase().includes("home") || client.name.toLowerCase().includes("assistant");
      list.push({
        id: `mcp:${client.id}`,
        slug: client.id,
        name: client.name,
        summary: `MCP Server (${client.transport}) · ${client.url || client.command || "Remote endpoint"}`,
        icon: isHome ? "home" : "connect",
        kind: "raw_mcp",
        status: client.enabled ? "connected" : "degraded",
        status_detail: client.enabled ? undefined : "Disabled",
        account: client.auth_provider_id ? "OAuth / Provider bound" : "Local / Network",
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

  // Remove or uninstall an item
  const handleRemoveItem = async (item: UnifiedIntegrationItem) => {
    setBusySlug(item.slug);
    try {
      if (item.raw_connector) {
        await api.uninstallConnector(project.id, item.raw_connector.slug);
      } else if (item.raw_mcp) {
        await api.deleteMcpClient(project.id, item.raw_mcp.id);
      }
      setSelectedItem(null);
      await reload();
      setNote(`Successfully removed ${item.name} and its associated tools.`);
      setTimeout(() => setNote(null), 4000);
    } catch (e: any) {
      const msg = e?.message || "Failed to remove integration";
      setErr(msg);
      alert(msg);
    } finally {
      setBusySlug(null);
    }
  };

  // Add custom MCP client
  const handleAddMcpClient = async () => {
    if (!newMcpName.trim() || !newMcpUrl.trim()) return;
    setErr(null);
    try {
      const created = await api.createMcpClient(project.id, {
        name: newMcpName.trim(),
        transport: newMcpTransport,
        url: newMcpUrl.trim(),
      });
      try {
        const disc = await api.refreshMcpCapabilities(project.id, created.id);
        if (disc.ok && disc.discovery?.tools_count) {
          setNote(`Successfully registered ${newMcpName.trim()} with ${disc.discovery.tools_count} tools.`);
        } else if (disc.error) {
          setNote(`Registered ${newMcpName.trim()}. Connection notice: ${disc.error}`);
        } else {
          setNote(`Successfully registered ${newMcpName.trim()}.`);
        }
      } catch {
        setNote(`Successfully registered ${newMcpName.trim()}.`);
      }
      setAddMcpOpen(false);
      setNewMcpName("");
      setNewMcpUrl("");
      await reload();
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
        workflows={workflows}
        agents={agents}
        busy={busySlug === selectedItem.slug}
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
          {newChannelType === "telegram" && (
            <>
              <Field
                label="Telegram Bot Token"
                required
                help="Obtained from @BotFather on Telegram (e.g. 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ)"
              >
                <input
                  type="password"
                  className="input mono"
                  placeholder="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
                  value={newChannelToken}
                  onChange={(e) => setNewChannelToken(e.target.value)}
                />
              </Field>
              <Field
                label="Transport Mode"
                help="Auto detects webhook or polling. Polling works seamlessly on localhost / behind NAT."
              >
                <select
                  className="select"
                  value={newChannelTransport}
                  onChange={(e) => setNewChannelTransport(e.target.value as any)}
                >
                  <option value="auto">Auto (Detect Webhook or Polling)</option>
                  <option value="polling">Long Polling (Recommended for Local Dev)</option>
                  <option value="webhook">Webhook Mode (Public HTTPS)</option>
                </select>
              </Field>
              <div
                style={{
                  padding: "10px 14px",
                  borderRadius: 8,
                  background: "rgba(99, 102, 241, 0.08)",
                  border: "1px solid rgba(99, 102, 241, 0.25)",
                  fontSize: 12,
                  lineHeight: 1.5,
                  color: "var(--fg-1)",
                }}
              >
                <strong>Pairing Notice:</strong> After creating this channel, open your bot in Telegram and send <code>/start</code>. It will reply with a 6-character linking code. Enter that code under the channel&apos;s <strong>Access &amp; Pairing</strong> tab to authorize your Telegram account.
              </div>
            </>
          )}
          <Field label="Default Destination" help="Select who answers inbound queries from this channel">
            <select
              className="select"
              value={newChannelTargetType}
              onChange={(e) => {
                setNewChannelTargetType(e.target.value as any);
                setNewChannelTargetId("");
              }}
            >
              <option value="master_agent">Master Agent (Conversational AI Butler)</option>
              <option value="subagent">Specialized Subagent</option>
              <option value="workflow">Workflow</option>
            </select>
          </Field>
          {newChannelTargetType === "subagent" && (
            <Field label="Select Subagent" required>
              <select
                className="select"
                value={newChannelTargetId}
                onChange={(e) => setNewChannelTargetId(e.target.value)}
              >
                <option value="">Choose a subagent...</option>
                {agents.map((a: any) => (
                  <option key={a.id} value={a.id}>
                    {a.name} ({a.role || "Agent"})
                  </option>
                ))}
              </select>
            </Field>
          )}
          {newChannelTargetType === "workflow" && (
            <Field label="Select Workflow" required>
              <select
                className="select"
                value={newChannelTargetId}
                onChange={(e) => setNewChannelTargetId(e.target.value)}
              >
                <option value="">Choose a workflow...</option>
                {workflows.map((w: any) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <div className="row end gap2" style={{ marginTop: 12 }}>
            <button
              className="btn btn-ghost"
              onClick={() => {
                setNewChannelOpen(false);
                setNewChannelName("");
                setNewChannelToken("");
                setNewChannelTransport("auto");
                setNewChannelTargetType("master_agent");
                setNewChannelTargetId("");
              }}
            >
              Cancel
            </button>
            <button
              className="btn btn-primary"
              disabled={
                !newChannelName.trim() ||
                (newChannelType === "telegram" && !newChannelToken.trim()) ||
                ((newChannelTargetType === "subagent" || newChannelTargetType === "workflow") && !newChannelTargetId)
              }
              onClick={async () => {
                try {
                  const config: Record<string, any> = {};
                  if (newChannelType === "telegram") {
                    config.bot_token = newChannelToken.trim();
                    config.transport = newChannelTransport;
                  }
                  const ch = await api.createChannel(project.id, {
                    type: newChannelType,
                    name: newChannelName.trim(),
                    target_type: newChannelTargetType,
                    target_id: newChannelTargetType === "master_agent" ? undefined : newChannelTargetId || undefined,
                    config,
                  });
                  setNewChannelOpen(false);
                  setNewChannelName("");
                  setNewChannelToken("");
                  setNewChannelTransport("auto");
                  setNewChannelTargetType("master_agent");
                  setNewChannelTargetId("");
                  await reload();
                  setSelectedItem({
                    id: `channel:${ch.id}`,
                    slug: ch.type,
                    name: ch.name,
                    summary: `Channel Gateway · ${ch.target_type === "subagent" ? "Subagent" : ch.target_type === "workflow" ? "Workflow" : "Master Agent (Default)"}`,
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

export { StatusBadge, EffectBadge, RiskBadge } from "./integrations/badges";
export type { UnifiedIntegrationItem, MainTab, DetailTab } from "./integrations/types";
