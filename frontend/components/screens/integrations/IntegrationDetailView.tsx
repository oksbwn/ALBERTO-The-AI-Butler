"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/icons";
import { Field, Modal, Tile, Toggle } from "@/components/primitives";
import {
  api,
  ConnectorCatalogEntry,
  ConnectorExample,
  ConnectorInstallT,
  McpClientT,
  Tool,
  ToolAnalysisResult,
  ToolDiagnosticReport,
} from "@/lib/api";
import { DetailTab, UnifiedIntegrationItem } from "./types";
import { EffectBadge, RiskBadge, StatusBadge } from "./badges";

export function IntegrationDetailView({
  project,
  item,
  allTools,
  workflows = [],
  agents = [],
  busy = false,
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
  workflows?: any[];
  agents?: any[];
  busy?: boolean;
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
  const [confirmRemoveOpen, setConfirmRemoveOpen] = useState(false);

  // Editable configuration state for MCP
  const [editMcpName, setEditMcpName] = useState(item.raw_mcp?.name || item.name);
  const [editMcpUrl, setEditMcpUrl] = useState(item.raw_mcp?.url || "");
  const [editMcpTransport, setEditMcpTransport] = useState(item.raw_mcp?.transport || "http");
  const [savingConfig, setSavingConfig] = useState(false);
  const [runningDiagnostics, setRunningDiagnostics] = useState(false);
  const [mcpDiagnostics, setMcpDiagnostics] = useState<{
    ok: boolean;
    tools_count?: number;
    error?: string;
    fingerprint?: string;
  } | null>(null);

  useEffect(() => {
    if (item.raw_mcp) {
      setEditMcpName(item.raw_mcp.name);
      setEditMcpUrl(item.raw_mcp.url || "");
      setEditMcpTransport(item.raw_mcp.transport || "http");
    }
  }, [item]);

  // Filter tools associated with this integration
  const integrationTools = useMemo(() => {
    if (item.raw_connector) {
      const anyConn = item.raw_connector as any;
      const ids = new Set((anyConn.created_tool_ids as string[]) || []);
      return allTools.filter(
        (t) =>
          ids.has(t.id) ||
          (item.raw_connector?.tool_set_id && (t as any).tool_set_id === item.raw_connector.tool_set_id)
      );
    }
    if (item.raw_mcp) {
      const matched = allTools.filter(
        (t) => (t.config as any)?.mcp_client_id === item.raw_mcp!.id
      );
      if (matched.length > 0) {
        return matched;
      }
      const caps = item.raw_mcp.capabilities || {};
      const disc = (caps.tools as any[]) || [];
      const disabledSet = new Set(item.raw_mcp.disabled_tools || []);
      // Fallback if tools list not reloaded yet
      return disc.map((dt: any) => ({
        id: `mcp_tool:${item.raw_mcp!.id}:${dt.name}`,
        project_id: project.id,
        name: dt.name,
        kind: "mcp",
        config: {
          description: dt.description || "",
          input_schema: dt.input_schema,
          parameters: dt.input_schema,
          mcp_client_id: item.raw_mcp!.id,
          remote_tool_name: dt.name,
        },
        enabled: !disabledSet.has(dt.name),
        auth_provider_id: item.raw_mcp!.auth_provider_id,
      })) as unknown as Tool[];
    }
    return [];
  }, [item, allTools, project.id]);

  // Check if any tools belonging to this integration are currently in use by workflows or agents
  const toolUsages = useMemo(() => {
    const idSet = new Set(integrationTools.map((t) => t.id));
    const nameSet = new Set(integrationTools.map((t) => t.name));
    if (idSet.size === 0 && nameSet.size === 0) return [];

    const usages: Array<{
      targetType: "Workflow" | "Agent";
      targetId: string;
      targetName: string;
      matchedTools: string[];
    }> = [];

    // 1. Check Workflows
    for (const wf of workflows || []) {
      const matched = new Set<string>();
      const execNodes = (wf.executable?.nodes as any[]) || [];
      for (const n of execNodes) {
        const cfg = n.config || {};
        const tId = cfg.tool_id || n.tool_id;
        if (tId && (idSet.has(tId) || nameSet.has(tId))) matched.add(String(tId));
        for (const tRef of cfg.tools || []) {
          if (idSet.has(tRef) || nameSet.has(tRef)) matched.add(String(tRef));
        }
      }
      const canvasNodes = (wf.canvas?.nodes as any[]) || [];
      for (const n of canvasNodes) {
        const data = n.data || {};
        const cfg = data.config || {};
        const tId = data.tool_id || cfg.tool_id;
        if (tId && (idSet.has(tId) || nameSet.has(tId))) matched.add(String(tId));
        for (const tRef of cfg.tools || data.tools || []) {
          if (idSet.has(tRef) || nameSet.has(tRef)) matched.add(String(tRef));
        }
      }
      if (matched.size > 0) {
        usages.push({
          targetType: "Workflow",
          targetId: wf.id,
          targetName: wf.name || "Untitled Workflow",
          matchedTools: Array.from(matched),
        });
      }
    }

    // 2. Check Agents
    for (const ag of agents || []) {
      const matched = new Set<string>();
      const cfg = ag.config || {};
      for (const tRef of cfg.tools || []) {
        if (idSet.has(tRef) || nameSet.has(tRef)) matched.add(String(tRef));
      }
      for (const sa of cfg.subagents || []) {
        for (const tRef of sa.tools || []) {
          if (idSet.has(tRef) || nameSet.has(tRef)) matched.add(String(tRef));
        }
      }
      if (matched.size > 0) {
        usages.push({
          targetType: "Agent",
          targetId: ag.id,
          targetName: ag.name || "Untitled Agent",
          matchedTools: Array.from(matched),
        });
      }
    }

    return usages;
  }, [integrationTools, workflows, agents]);

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
        if (!tool.id.startsWith("mcp_tool:")) {
          await api.updateTool(project.id, tool.id, { enabled: !tool.enabled });
        }
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

  const handleSaveMcpConfig = async () => {
    if (!item.raw_mcp) return;
    setSavingConfig(true);
    try {
      await api.updateMcpClient(project.id, item.raw_mcp.id, {
        name: editMcpName.trim(),
        url: editMcpUrl.trim(),
      });
      onSync();
      onReload();
    } catch (e: any) {
      alert(`Save failed: ${e?.message || e}`);
    } finally {
      setSavingConfig(false);
    }
  };

  const runDiagnosticsProbe = async () => {
    setRunningDiagnostics(true);
    try {
      if (item.raw_mcp) {
        const res = await api.refreshMcpCapabilities(project.id, item.raw_mcp.id);
        setMcpDiagnostics({
          ok: res.ok,
          tools_count: res.discovery?.tools_count ?? (res.client?.capabilities as any)?.tools_count,
          error: res.error,
          fingerprint: res.discovery?.fingerprint ?? res.client?.schema_fingerprint,
        });
        onReload();
      } else if (integrationTools.length > 0) {
        const rep = await api.toolManagerDiagnose(project.id, {
          tool_id: integrationTools[0].id,
        });
        setDiagnosticReport(rep);
      }
    } catch (e: any) {
      setMcpDiagnostics({ ok: false, error: e?.message || String(e) });
    } finally {
      setRunningDiagnostics(false);
    }
  };

  const isHome =
    item.name.toLowerCase().includes("home") || item.name.toLowerCase().includes("assistant");

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
        <div className="row gap3" style={{ alignItems: "center" }}>
          <button className="btn btn-ghost btn-sm" onClick={onBack}>
            <Icon name="arrow-left" size={14} /> Integrations
          </button>
          <div className="divider-v" />
          <div className="row gap2" style={{ alignItems: "center" }}>
            <Tile
              icon={isHome ? "home" : item.icon || "connect"}
              color="var(--signal)"
              size={36}
            />
            <div className="col">
              <span className="t-h3" style={{ margin: 0 }}>{item.name}</span>
              <span className="fg-2 t-caption mono-sm">
                {item.raw_mcp
                  ? `MCP Server (${item.raw_mcp.transport || "streamable_http"}) · ${item.raw_mcp.url || item.raw_mcp.command || "Remote endpoint"}`
                  : item.slug}
              </span>
            </div>
            <StatusBadge status={item.status} />
          </div>
        </div>

        <div className="row gap2" style={{ alignItems: "center" }}>
          {item.status === "needs_auth" && (
            <button className="btn btn-primary btn-sm" onClick={onConnect}>
              <Icon name="lock" size={14} /> Connect Account
            </button>
          )}
          <button
            className="btn btn-secondary btn-sm"
            onClick={onSync}
            disabled={busy}
            title="Re-query capabilities and tools from server"
          >
            <Icon name="refresh" size={14} /> {busy ? "Syncing…" : "Sync Capabilities"}
          </button>
          {onNav && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => onNav("integrations-playground")}
              title="Test tools in Integrations Playground"
            >
              <Icon name="playground" size={14} /> Test in Playground
            </button>
          )}
          <button
            className="btn btn-ghost btn-sm"
            style={{ color: "var(--err)" }}
            onClick={() => setConfirmRemoveOpen(true)}
            title="Remove integration and all associated tools"
          >
            <Icon name="trash" size={14} /> Remove
          </button>
        </div>
      </div>

      {/* Sub-tabs */}
      <div className="tabs-bar">
        <button
          className={`tabbtn ${detailTab === "overview" ? "active" : ""}`}
          onClick={() => setDetailTab("overview")}
        >
          <Icon name="overview" size={14} />
          <span>Overview</span>
        </button>
        <button
          className={`tabbtn ${detailTab === "tools" ? "active" : ""}`}
          onClick={() => setDetailTab("tools")}
        >
          <Icon name="tools" size={14} />
          <span>Tools & Capabilities</span>
          <span className="badge">{integrationTools.length}</span>
        </button>
        <button
          className={`tabbtn ${detailTab === "config" ? "active" : ""}`}
          onClick={() => setDetailTab("config")}
        >
          <Icon name="sliders" size={14} />
          <span>Configuration</span>
        </button>
        <button
          className={`tabbtn ${detailTab === "diagnostics" ? "active" : ""}`}
          onClick={() => setDetailTab("diagnostics")}
        >
          <Icon name="activity" size={14} />
          <span>Diagnostics</span>
          {mcpDiagnostics && !mcpDiagnostics.ok && (
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "var(--err)",
                display: "inline-block",
              }}
            />
          )}
        </button>
      </div>

      {/* Content Area */}
      <div className="grow scroll-y" style={{ padding: 24 }}>
        {/* SUBTAB: OVERVIEW */}
        {detailTab === "overview" && (
          <div className="col gap4" style={{ maxWidth: 840 }}>
            {integrationTools.length === 0 && item.raw_mcp && (
              <div
                className="row spread"
                style={{
                  padding: "14px 18px",
                  background: "var(--warn-glow, rgba(245, 158, 11, 0.1))",
                  border: "1px solid var(--warn, #f59e0b)",
                  borderRadius: "var(--radius)",
                  alignItems: "center",
                }}
              >
                <div className="col gap1">
                  <div className="row gap2" style={{ alignItems: "center", fontWeight: 600, color: "var(--warn, #f59e0b)" }}>
                    <Icon name="alert-triangle" size={16} /> 0 Tools Discovered
                  </div>
                  <div className="t-body-sm fg-2">
                    Alberto has not discovered tools from this MCP server yet. Make sure the server is reachable and click Sync Capabilities.
                  </div>
                </div>
                <button className="btn btn-primary btn-sm" onClick={onSync} disabled={busy}>
                  <Icon name="refresh" size={13} /> Sync Now
                </button>
              </div>
            )}

            <div className="card col gap3" style={{ padding: 20 }}>
              <div className="row spread" style={{ alignItems: "center" }}>
                <div className="t-h3" style={{ margin: 0 }}>Integration Overview</div>
                <span
                  style={{
                    fontSize: 11.5,
                    fontWeight: 600,
                    padding: "2px 8px",
                    borderRadius: 999,
                    background: "var(--accent-glow)",
                    color: "var(--signal)",
                    border: "1px solid var(--signal-glow)",
                  }}
                >
                  {item.raw_mcp ? "Model Context Protocol (MCP)" : "REST Connector"}
                </span>
              </div>
              <p className="t-body fg-2">{item.summary}</p>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gap: "18px 24px",
                  marginTop: 8,
                }}
              >
                <div className="col gap1">
                  <span className="t-caption fg-2" style={{ textTransform: "uppercase", fontSize: 10.5, letterSpacing: "0.05em", fontWeight: 600 }}>
                    Integration Protocol
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg-0)" }}>
                    {item.kind === "raw_mcp" ? "Model Context Protocol (MCP)" : item.kind}
                  </span>
                </div>
                <div className="col gap1">
                  <span className="t-caption fg-2" style={{ textTransform: "uppercase", fontSize: 10.5, letterSpacing: "0.05em", fontWeight: 600 }}>
                    Authentication Method
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 500, color: "var(--fg-0)" }}>
                    {item.raw_mcp?.auth_provider_id
                      ? "OAuth2 / Auth Provider"
                      : item.raw_mcp?.headers_ref
                      ? "Custom Headers / Token Secret"
                      : "Direct / Local Network"}
                  </span>
                </div>
                <div className="col gap1">
                  <span className="t-caption fg-2" style={{ textTransform: "uppercase", fontSize: 10.5, letterSpacing: "0.05em", fontWeight: 600 }}>
                    Endpoint URL
                  </span>
                  <span className="mono-sm truncate" style={{ fontSize: 12.5 }} title={item.raw_mcp?.url || ""}>
                    {item.raw_mcp?.url || item.raw_mcp?.command || "—"}
                  </span>
                </div>
                <div className="col gap1">
                  <span className="t-caption fg-2" style={{ textTransform: "uppercase", fontSize: 10.5, letterSpacing: "0.05em", fontWeight: 600 }}>
                    Last Synchronized
                  </span>
                  <span className="mono-sm" style={{ fontSize: 12.5 }}>
                    {item.last_verified ? new Date(item.last_verified).toLocaleString() : "Never"}
                  </span>
                </div>
                <div className="col gap1">
                  <span className="t-caption fg-2" style={{ textTransform: "uppercase", fontSize: 10.5, letterSpacing: "0.05em", fontWeight: 600 }}>
                    Registered Capabilities
                  </span>
                  <span style={{ fontWeight: 600, fontSize: 13, color: "var(--fg-0)" }}>
                    {integrationTools.length} tools available
                  </span>
                </div>
                <div className="col gap1">
                  <span className="t-caption fg-2" style={{ textTransform: "uppercase", fontSize: 10.5, letterSpacing: "0.05em", fontWeight: 600 }}>
                    Status
                  </span>
                  <div>
                    <StatusBadge status={item.status} />
                  </div>
                </div>
              </div>
            </div>

            {integrationTools.length > 0 && (
              <div className="card col gap3" style={{ padding: 20 }}>
                <div className="row spread" style={{ alignItems: "center" }}>
                  <div className="t-h3" style={{ margin: 0 }}>Discovered Capabilities Preview</div>
                  <button className="btn btn-ghost btn-xs" onClick={() => setDetailTab("tools")}>
                    View All {integrationTools.length} Tools →
                  </button>
                </div>
                <div className="row gap2" style={{ flexWrap: "wrap" }}>
                  {integrationTools.slice(0, 16).map((t) => (
                    <span
                      key={t.id}
                      className="mono-sm"
                      style={{
                        padding: "3px 8px",
                        background: "var(--bg-2)",
                        border: "1px solid var(--line)",
                        borderRadius: 5,
                        fontSize: 11.5,
                        color: "var(--fg-1)",
                      }}
                    >
                      {t.name}
                    </span>
                  ))}
                  {integrationTools.length > 16 && (
                    <span className="t-caption fg-2" style={{ alignSelf: "center", paddingLeft: 4 }}>
                      +{integrationTools.length - 16} more
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* SUBTAB: TOOLS & CAPABILITIES */}
        {detailTab === "tools" && (
          <div className="col gap3">
            {integrationTools.length === 0 ? (
              <EmptyState
                icon="tools"
                title="No tools discovered yet"
                sub="Alberto has not discovered capabilities from this MCP endpoint yet. Click 'Sync Capabilities' to query the server's tools, or verify that the endpoint is running and accessible."
                action={
                  <button className="btn btn-primary" onClick={onSync} disabled={busy}>
                    <Icon name="refresh" size={14} /> Sync Capabilities
                  </button>
                }
              />
            ) : (
              <>
                <div className="row spread" style={{ alignItems: "center" }}>
                  <input
                    type="search"
                    className="input"
                    style={{ maxWidth: 360 }}
                    placeholder="Search discovered tools…"
                    value={toolSearch}
                    onChange={(e) => setToolSearch(e.target.value)}
                  />
                  <span className="t-caption fg-2">
                    {filteredTools.length} of {integrationTools.length} tools available
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
                        <div className="row spread" style={{ alignItems: "center" }}>
                          <div className="row gap2" style={{ alignItems: "center" }}>
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
              </>
            )}
          </div>
        )}

        {/* SUBTAB: CONFIGURATION */}
        {detailTab === "config" && (
          <div className="col gap4" style={{ maxWidth: 680 }}>
            <div className="card col gap4" style={{ padding: 22 }}>
              <div className="col gap1">
                <div className="t-h3" style={{ margin: 0 }}>Connection Settings</div>
                <div className="t-caption fg-2">
                  Update remote server endpoint parameters or transport mode.
                </div>
              </div>
              {item.raw_mcp ? (
                <div className="col gap3">
                  <Field label="MCP Server Name">
                    <input
                      type="text"
                      className="input"
                      value={editMcpName}
                      onChange={(e) => setEditMcpName(e.target.value)}
                    />
                  </Field>
                  <Field label="Endpoint URL">
                    <input
                      type="url"
                      className="input mono"
                      value={editMcpUrl}
                      onChange={(e) => setEditMcpUrl(e.target.value)}
                    />
                  </Field>
                  <Field label="Transport Type">
                    <select
                      className="select"
                      value={editMcpTransport}
                      onChange={(e) => setEditMcpTransport(e.target.value)}
                    >
                      <option value="http">Streamable HTTP / SSE</option>
                      <option value="sse">Direct Server-Sent Events (SSE)</option>
                    </select>
                  </Field>
                  <div className="row end gap2" style={{ marginTop: 8 }}>
                    <button
                      className="btn btn-primary btn-sm"
                      disabled={savingConfig}
                      onClick={handleSaveMcpConfig}
                    >
                      {savingConfig ? "Saving…" : "Save & Re-sync"}
                    </button>
                  </div>
                </div>
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
              <div className="row spread" style={{ alignItems: "center" }}>
                <div className="col gap1">
                  <div className="t-h3" style={{ margin: 0 }}>Health & Diagnostics</div>
                  <div className="t-caption fg-2">
                    Probe integration health, endpoint availability, and tool execution status.
                  </div>
                </div>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={runningDiagnostics}
                  onClick={runDiagnosticsProbe}
                >
                  <Icon name="activity" size={14} /> {runningDiagnostics ? "Probing…" : "Run Diagnostics"}
                </button>
              </div>

              {mcpDiagnostics && (
                <div
                  className="col gap3"
                  style={{
                    background: "var(--bg-2)",
                    padding: 16,
                    borderRadius: 8,
                    border: "1px solid var(--line)",
                  }}
                >
                  <div className="row spread" style={{ alignItems: "center" }}>
                    <div className="row gap2" style={{ alignItems: "center" }}>
                      <span
                        className="dot"
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: mcpDiagnostics.ok ? "var(--ok)" : "var(--err)",
                        }}
                      />
                      <span
                        style={{
                          fontWeight: 600,
                          fontSize: 13,
                          color: mcpDiagnostics.ok ? "var(--ok)" : "var(--err)",
                        }}
                      >
                        {mcpDiagnostics.ok ? "Connected & Healthy" : "Degraded / Error"}
                      </span>
                    </div>
                    <span className="mono-sm fg-2">
                      {mcpDiagnostics.tools_count ?? integrationTools.length} tools verified
                    </span>
                  </div>
                  {mcpDiagnostics.error && (
                    <div
                      className="t-body-sm"
                      style={{
                        color: "var(--err)",
                        background: "var(--err-bg)",
                        padding: "8px 12px",
                        borderRadius: 6,
                        fontFamily: "var(--font-mono)",
                        fontSize: 12,
                      }}
                    >
                      {mcpDiagnostics.error}
                    </div>
                  )}
                  {mcpDiagnostics.fingerprint && (
                    <div className="t-caption mono fg-2 truncate">
                      Schema Fingerprint: {mcpDiagnostics.fingerprint}
                    </div>
                  )}
                </div>
              )}

              {diagnosticReport && (
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
              )}
              {!mcpDiagnostics && !diagnosticReport && (
                <p className="t-body-sm fg-2">
                  Click above to run live diagnostic probe against the endpoint.
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
            {JSON.stringify(
              schemaModalTool.config?.input_schema || schemaModalTool.config?.parameters || {},
              null,
              2
            )}
          </pre>
        </Modal>
      )}

      {/* Remove Confirmation Modal */}
      {confirmRemoveOpen && (
        <Modal
          open={confirmRemoveOpen}
          onClose={() => setConfirmRemoveOpen(false)}
          title={`Remove ${item.name}`}
        >
          <div className="col gap4">
            <div className="col gap2">
              <p className="t-body" style={{ margin: 0 }}>
                Are you sure you want to remove <b>{item.name}</b>?
              </p>

              {toolUsages.length > 0 ? (
                /* Warning callout: Tools are currently in use -> BLOCK removal */
                <div
                  className="col gap3"
                  style={{
                    background: "var(--err-bg, rgba(239, 68, 68, 0.08))",
                    border: "1px solid var(--err, #ef4444)",
                    padding: 16,
                    borderRadius: "var(--r-md, 8px)",
                  }}
                >
                  <div className="row gap2" style={{ color: "var(--err)", fontWeight: 700, fontSize: 13, alignItems: "center" }}>
                    <Icon name="alert-triangle" size={18} />
                    <span>Cannot Remove Integration: Tools In Use</span>
                  </div>
                  <div className="t-body-sm fg-1">
                    Tools provided by this integration are currently referenced and active in <b>{toolUsages.length}</b> workflow{toolUsages.length === 1 ? "" : "s"} or agent{toolUsages.length === 1 ? "" : "s"}. You must remove or replace these tools before you can remove this integration.
                  </div>
                  <div className="col gap2 scroll-y" style={{ maxHeight: 180 }}>
                    {toolUsages.map((usage, idx) => (
                      <div
                        key={idx}
                        className="col gap1"
                        style={{
                          padding: "8px 12px",
                          background: "var(--bg-1)",
                          borderRadius: 6,
                          border: "1px solid var(--line)",
                        }}
                      >
                        <div className="row spread" style={{ alignItems: "center" }}>
                          <span style={{ fontWeight: 600, fontSize: 12.5 }}>
                            {usage.targetType === "Workflow" ? "⚡ Workflow: " : "🤖 Agent: "}
                            {usage.targetName}
                          </span>
                        </div>
                        <div className="row gap1 wrap" style={{ marginTop: 2 }}>
                          <span className="t-caption fg-2">Using tools:</span>
                          {usage.matchedTools.map((tName) => (
                            <span
                              key={tName}
                              className="mono-sm"
                              style={{
                                padding: "1px 6px",
                                background: "var(--bg-2)",
                                border: "1px solid var(--line-strong)",
                                borderRadius: 4,
                                fontSize: 11,
                              }}
                            >
                              {tName}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : integrationTools.length > 0 ? (
                /* Normal confirmation: list tools to be removed */
                <div
                  className="col gap2"
                  style={{
                    background: "var(--warn-glow, rgba(245, 158, 11, 0.08))",
                    border: "1px solid var(--warn, #f59e0b)",
                    padding: 14,
                    borderRadius: "var(--r-md, 8px)",
                  }}
                >
                  <div className="row gap2" style={{ color: "var(--warn, #f59e0b)", fontWeight: 600, fontSize: 13 }}>
                    <Icon name="alert-triangle" size={16} />
                    <span>
                      {integrationTools.length} tool{integrationTools.length === 1 ? "" : "s"} will also be removed
                    </span>
                  </div>
                  <div className="t-body-sm fg-1">
                    The following tools registered by this integration will also be permanently removed from the tools registry and will no longer be available to workflows or agents:
                  </div>
                  <div
                    className="row gap1 wrap scroll-y"
                    style={{
                      maxHeight: 140,
                      padding: 8,
                      background: "var(--bg-1)",
                      borderRadius: 6,
                      border: "1px solid var(--line)",
                    }}
                  >
                    {integrationTools.map((t) => (
                      <span
                        key={t.id}
                        className="mono-sm"
                        style={{
                          padding: "2px 8px",
                          background: "var(--bg-2)",
                          border: "1px solid var(--line)",
                          borderRadius: 4,
                          fontSize: 11.5,
                        }}
                      >
                        {t.name}
                      </span>
                    ))}
                  </div>
                  <div className="t-caption fg-2" style={{ fontWeight: 500, marginTop: 4 }}>
                    Are you ok to continue?
                  </div>
                </div>
              ) : (
                <p className="t-body-sm fg-2" style={{ margin: 0 }}>
                  This integration will be removed from your project. Are you ok to continue?
                </p>
              )}
            </div>

            <div className="row end gap2" style={{ marginTop: 8 }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setConfirmRemoveOpen(false)}
              >
                {toolUsages.length > 0 ? "Close" : "Cancel"}
              </button>
              <button
                className="btn btn-danger btn-sm"
                disabled={toolUsages.length > 0}
                title={toolUsages.length > 0 ? "Cannot remove while tools are in use by workflows or agents" : undefined}
                onClick={() => {
                  setConfirmRemoveOpen(false);
                  onRemove();
                }}
              >
                <Icon name="trash" size={14} /> Remove Integration
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

