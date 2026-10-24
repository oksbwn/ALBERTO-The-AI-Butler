"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../icons";
import { api, Tool } from "@/lib/api";
import { ChatScreen } from "./chat";

interface IntegrationsPlaygroundProps {
  project: any;
  initialToolId?: string | null;
  initialIntegrationId?: string | null;
  onNav?: (screen: string) => void;
}

const EFFECT_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  read: { bg: "rgba(59, 130, 246, 0.12)", text: "#60a5fa", border: "rgba(59, 130, 246, 0.25)" },
  write: { bg: "rgba(245, 158, 11, 0.12)", text: "#fbbf24", border: "rgba(245, 158, 11, 0.25)" },
  delete: { bg: "rgba(239, 68, 68, 0.12)", text: "#f87171", border: "rgba(239, 68, 68, 0.25)" },
  execute: { bg: "rgba(168, 85, 247, 0.12)", text: "#c084fc", border: "rgba(168, 85, 247, 0.25)" },
  unknown: { bg: "rgba(148, 163, 184, 0.12)", text: "#94a3b8", border: "rgba(148, 163, 184, 0.25)" },
};

const RISK_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  low: { bg: "rgba(34, 197, 94, 0.12)", text: "#4ade80", border: "rgba(34, 197, 94, 0.25)" },
  medium: { bg: "rgba(234, 179, 8, 0.12)", text: "#facc15", border: "rgba(234, 179, 8, 0.25)" },
  high: { bg: "rgba(249, 115, 22, 0.12)", text: "#fb923c", border: "rgba(249, 115, 22, 0.25)" },
  critical: { bg: "rgba(239, 68, 68, 0.15)", text: "#f87171", border: "rgba(239, 68, 68, 0.35)" },
};

const BUILTIN_SCHEMAS: Record<string, { properties: Record<string, any>; required?: string[] }> = {
  calculator: {
    properties: { expression: { type: "string", description: "Arithmetic expression, e.g. '2 * (3 + 4)'" } },
    required: ["expression"],
  },
  web_fetch: {
    properties: { url: { type: "string", description: "URL to fetch (e.g. 'https://example.com')" } },
    required: ["url"],
  },
  web_search: {
    properties: { query: { type: "string", description: "Search query" } },
    required: ["query"],
  },
  knowledge_search: {
    properties: { query: { type: "string", description: "Search query to find in project documents & FAQs" } },
    required: ["query"],
  },
  remember: {
    properties: {
      key: { type: "string", description: "Memory key or label" },
      value: { type: "string", description: "Memory content to store" },
    },
    required: ["key", "value"],
  },
  recall: {
    properties: { query: { type: "string", description: "Query to search stored memories" } },
    required: ["query"],
  },
  current_time: {
    properties: { tz: { type: "string", description: "Timezone name (default: UTC)", default: "UTC" } },
  },
};

function extractToolSchema(tool: any): { properties: Record<string, any>; required: Set<string> } {
  if (!tool) return { properties: {}, required: new Set() };
  const cfg = tool.config || {};

  // 1. Built-in tools fallback
  if (tool.kind === "builtin" || cfg.builtin) {
    const bKey = cfg.builtin || tool.name;
    const bSchema = BUILTIN_SCHEMAS[bKey];
    if (bSchema) {
      return { properties: bSchema.properties, required: new Set(bSchema.required || []) };
    }
  }

  // 2. Direct schema: input_schema, inputSchema, parameters, args_schema
  const rawSchema = cfg.input_schema || cfg.inputSchema || cfg.parameters || cfg.args_schema || {};
  const properties: Record<string, any> = {};
  const required = new Set<string>();

  if (rawSchema.properties && typeof rawSchema.properties === "object") {
    Object.assign(properties, rawSchema.properties);
    if (Array.isArray(rawSchema.required)) {
      rawSchema.required.forEach((r: string) => required.add(r));
    }
  } else if (Array.isArray(rawSchema)) {
    for (const p of rawSchema) {
      const name = p.name || p.path;
      if (name) {
        properties[name] = { type: p.type || "string", description: p.description || "", default: p.default };
        if (p.required) required.add(name);
      }
    }
  } else if (typeof rawSchema === "object" && Object.keys(rawSchema).length > 0 && !rawSchema.type) {
    Object.assign(properties, rawSchema);
  }

  // 3. REST fields fallback: cfg.fields or cfg.request?.fields
  if (Object.keys(properties).length === 0) {
    const fields = cfg.fields || cfg.request?.fields;
    if (Array.isArray(fields)) {
      for (const f of fields) {
        const name = f.path || f.name;
        if (name && f.llm_visible !== false) {
          properties[name] = { type: f.type || "string", description: f.description || "", default: f.default };
          if (f.required) required.add(name);
        }
      }
    }
  }

  return { properties, required };
}


export function IntegrationsPlaygroundScreen({
  project,
  initialToolId,
  initialIntegrationId,
  onNav,
}: IntegrationsPlaygroundProps) {
  // Draggable split percentage
  const [splitPct, setSplitPct] = useState(50);
  const containerRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);

  // Left panel view: "parameters" (Schema & Form/Raw JSON) | "console" (Live Telemetry & Execution Output)
  const [workbenchTab, setWorkbenchTab] = useState<"parameters" | "console">("parameters");
  const [externalChatInput, setExternalChatInput] = useState<string>("");

  // Tools state
  const [tools, setTools] = useState<Tool[]>([]);
  const [loadingTools, setLoadingTools] = useState(true);
  const [selectedToolId, setSelectedToolId] = useState<string | null>(initialToolId || null);
  const [filterQuery, setFilterQuery] = useState("");
  const [filterSource, setFilterSource] = useState<"all" | "connector" | "mcp" | "builtin">("all");

  // Input state
  const [inputMode, setInputMode] = useState<"schema" | "raw">("schema");
  const [formValues, setFormValues] = useState<Record<string, any>>({});
  const [rawJson, setRawJson] = useState("{}");
  const [jsonError, setJsonError] = useState<string | null>(null);

  // Execution state
  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<any | null>(null);
  const [executionLatency, setExecutionLatency] = useState<number | null>(null);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [resultTab, setResultTab] = useState<"response" | "diagnostics" | "audit">("response");

  // HITL state
  const [pendingApprovalId, setPendingApprovalId] = useState<string | null>(null);
  const [approvalDecisionStatus, setApprovalDecisionStatus] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);

  // Handle URL deep linking
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const urlToolId = params.get("toolId");
      if (urlToolId) {
        setSelectedToolId(urlToolId);
      }
    }
  }, []);

  // Divider drag
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    isDraggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDraggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const raw = ((moveEvent.clientX - rect.left) / rect.width) * 100;
      setSplitPct(Math.max(25, Math.min(75, Math.round(raw))));
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  };

  // Load tools
  const loadTools = useCallback(async () => {
    if (!project?.id) return;
    setLoadingTools(true);
    try {
      const list = await api.listTools(project.id);
      setTools(list);
      if (!selectedToolId && list.length > 0) {
        setSelectedToolId(list[0].id);
      }
    } catch {
      setTools([]);
    } finally {
      setLoadingTools(false);
    }
  }, [project?.id, selectedToolId]);

  useEffect(() => {
    loadTools();
  }, [loadTools]);

  const selTool = useMemo(
    () => tools.find((t) => t.id === selectedToolId) || null,
    [tools, selectedToolId]
  );

  // Sync schema properties to form values when tool changes
  useEffect(() => {
    if (!selTool) return;
    const { properties: props } = extractToolSchema(selTool);

    const defaults: Record<string, any> = {};
    Object.keys(props).forEach((k) => {
      if (props[k]?.default !== undefined) {
        defaults[k] = props[k].default;
      } else if (props[k]?.type === "string") {
        defaults[k] = "";
      } else if (props[k]?.type === "number" || props[k]?.type === "integer") {
        defaults[k] = 0;
      } else if (props[k]?.type === "boolean") {
        defaults[k] = false;
      }
    });

    setFormValues(defaults);
    setRawJson(JSON.stringify(defaults, null, 2));
    setJsonError(null);
    setExecutionResult(null);
    setPendingApprovalId(null);
    setExecutionError(null);
  }, [selTool]);

  const updateRawJson = (val: string) => {
    setRawJson(val);
    try {
      const parsed = JSON.parse(val);
      setFormValues(parsed);
      setJsonError(null);
    } catch (e: any) {
      setJsonError(e.message || "Invalid JSON syntax");
    }
  };

  const updateFormField = (key: string, val: any) => {
    const next = { ...formValues, [key]: val };
    setFormValues(next);
    setRawJson(JSON.stringify(next, null, 2));
    setJsonError(null);
  };

  // Execute Tool Test
  const runTest = async (approvalIdToResume?: string) => {
    if (!project?.id || !selTool || executing) return;
    setExecuting(true);
    setWorkbenchTab("console");
    setExecutionError(null);
    setApprovalDecisionStatus(null);
    const start = performance.now();

    let args: Record<string, any> = {};
    if (inputMode === "raw") {
      try {
        args = JSON.parse(rawJson);
      } catch (err: any) {
        setExecutionError(`Invalid JSON arguments: ${err.message}`);
        setExecuting(false);
        return;
      }
    } else {
      args = formValues;
    }

    try {
      const res = await api.testToolSecured(project.id, selTool.id, {
        args,
        approval_id: approvalIdToResume || pendingApprovalId || undefined,
      });

      const latency = Math.round(performance.now() - start);
      setExecutionLatency(latency);
      setExecutionResult(res);

      if (res?.requires_approval) {
        setPendingApprovalId(res.approval_request_id || null);
      } else {
        setPendingApprovalId(null);
      }
    } catch (e: any) {
      const latency = Math.round(performance.now() - start);
      setExecutionLatency(latency);
      setExecutionError(e.message || "Execution failed");
    } finally {
      setExecuting(false);
    }
  };

  // Approve or Reject HITL Gate
  const handleDecideApproval = async (decision: "approve" | "reject") => {
    if (!pendingApprovalId || !project?.id || approvalBusy) return;
    setApprovalBusy(true);
    setApprovalDecisionStatus(null);
    try {
      const res = await api.decideApproval(project.id, pendingApprovalId, {
        decision,
        notes: decision === "approve" ? "Authorized from Integrations Playground" : "Rejected by user in test console",
      });
      setApprovalDecisionStatus(`Request ${decision}d successfully.`);
      if (decision === "approve") {
        await runTest(pendingApprovalId);
      } else {
        setPendingApprovalId(null);
        setExecutionResult({ ok: false, error: "Execution cancelled: HITL approval rejected by operator." });
      }
    } catch (err: any) {
      setApprovalDecisionStatus(`Decision error: ${err.message}`);
    } finally {
      setApprovalBusy(false);
    }
  };

  // Keyboard shortcut Ctrl + Enter to run
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        runTest();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  const restCount = useMemo(() => tools.filter((t) => t.kind === "rest_api").length, [tools]);
  const mcpCount = useMemo(() => tools.filter((t) => t.kind === "mcp" || Boolean((t.config as any)?.mcp_client_id)).length, [tools]);
  const builtinCount = useMemo(() => tools.filter((t) => t.kind === "builtin").length, [tools]);

  const filteredTools = useMemo(() => {
    return tools.filter((t) => {
      if (filterSource === "connector" && t.kind !== "rest_api") return false;
      if (filterSource === "mcp" && t.kind !== "mcp" && !(t.config as any)?.mcp_client_id) return false;
      if (filterSource === "builtin" && t.kind !== "builtin") return false;
      if (!filterQuery) return true;
      const q = filterQuery.toLowerCase();
      return (
        t.name.toLowerCase().includes(q) ||
        (t.config?.description || "").toLowerCase().includes(q)
      );
    });
  }, [tools, filterSource, filterQuery]);

  const cfg = selTool?.config || {};
  const { properties: schemaProps, required: requiredKeys } = useMemo(
    () => extractToolSchema(selTool),
    [selTool]
  );
  const effect = (cfg.effect || "execute").toLowerCase();
  const risk = (cfg.risk || "medium").toLowerCase();
  const effectStyle = EFFECT_COLORS[effect] || EFFECT_COLORS.unknown;
  const riskStyle = RISK_COLORS[risk] || RISK_COLORS.medium;

  return (
    <div
      ref={containerRef}
      style={{
        display: "flex",
        flex: 1,
        height: "100%",
        overflow: "hidden",
        backgroundColor: "var(--bg-0, #090a0f)",
        color: "var(--fg-0, #f1f5f9)",
      }}
    >
      {/* ==================================================================== */}
      {/* LEFT HALF: Tool Workbench & Live Execution Console                   */}
      {/* ==================================================================== */}
      <div
        style={{
          width: `${splitPct}%`,
          height: "100%",
          minWidth: 340,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          backgroundColor: "var(--bg-0)",
        }}
      >
        {/* Explorer Header */}
        <div
          style={{
            padding: "16px 20px 12px",
            borderBottom: "1px solid var(--line, rgba(255, 255, 255, 0.08))",
            backgroundColor: "var(--bg-1)",
            flex: "none",
          }}
        >
          <div className="row spread" style={{ alignItems: "center" }}>
            <div>
              <div className="row gap2" style={{ alignItems: "center" }}>
                <Icon name="playground" size={17} style={{ color: "var(--accent, #6366f1)" }} />
                <span className="t-h2" style={{ fontSize: 16 }}>
                  Integrations Playground
                </span>
                <span
                  className="badge"
                  style={{
                    backgroundColor: "var(--accent-glow, rgba(99, 102, 241, 0.15))",
                    color: "var(--accent, #818cf8)",
                    fontWeight: 600,
                    fontSize: 11,
                  }}
                >
                  {tools.length} available
                </span>
              </div>
              <div className="fg-2 t-caption" style={{ marginTop: 2 }}>
                Secured testbed with ToolPolicyService validation and Human-In-The-Loop gates.
              </div>
            </div>
          </div>

          {/* Source Filter Tabs */}
          <div className="row gap2" style={{ marginTop: 12, alignItems: "center" }}>
            <button
              className={`btn btn-sm ${filterSource === "all" ? "btn-secondary" : "btn-ghost"}`}
              style={{ fontSize: 11, padding: "3px 9px", height: "auto" }}
              onClick={() => setFilterSource("all")}
            >
              All ({tools.length})
            </button>
            <button
              className={`btn btn-sm ${filterSource === "connector" ? "btn-secondary" : "btn-ghost"}`}
              style={{ fontSize: 11, padding: "3px 9px", height: "auto" }}
              onClick={() => setFilterSource("connector")}
            >
              REST APIs ({restCount})
            </button>
            <button
              className={`btn btn-sm ${filterSource === "mcp" ? "btn-secondary" : "btn-ghost"}`}
              style={{ fontSize: 11, padding: "3px 9px", height: "auto" }}
              onClick={() => setFilterSource("mcp")}
            >
              MCP Tools ({mcpCount})
            </button>
            <button
              className={`btn btn-sm ${filterSource === "builtin" ? "btn-secondary" : "btn-ghost"}`}
              style={{ fontSize: 11, padding: "3px 9px", height: "auto" }}
              onClick={() => setFilterSource("builtin")}
            >
              Built-ins ({builtinCount})
            </button>
          </div>

          {/* Unified Tool Search & Selector Row */}
          <div className="row gap2" style={{ marginTop: 10, alignItems: "center" }}>
            <div style={{ position: "relative", width: 170, flex: "none" }}>
              <input
                className="input mono-sm"
                style={{ width: "100%", paddingLeft: 26, fontSize: 12, height: 32 }}
                placeholder="Search tools…"
                value={filterQuery}
                onChange={(e) => setFilterQuery(e.target.value)}
              />
              <div style={{ position: "absolute", left: 8, top: 7, color: "var(--fg-3)" }}>
                <Icon name="search" size={13} />
              </div>
              {filterQuery && (
                <button
                  onClick={() => setFilterQuery("")}
                  style={{
                    position: "absolute",
                    right: 6,
                    top: 6,
                    background: "none",
                    border: "none",
                    color: "var(--fg-3)",
                    cursor: "pointer",
                    padding: 2,
                  }}
                  title="Clear search"
                >
                  <Icon name="x" size={12} />
                </button>
              )}
            </div>

            <div style={{ position: "relative", flex: 1 }}>
              <select
                className="select"
                style={{ width: "100%", height: 32, fontSize: 12, fontWeight: 500 }}
                value={selectedToolId || ""}
                onChange={(e) => setSelectedToolId(e.target.value)}
              >
                {filteredTools.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({(t.kind || "tool").toUpperCase()}) {t.config?.effect ? `• ${t.config.effect}` : ""} {t.config?.requires_approval ? "• HITL" : ""}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Selected Tool Details Card */}
        {selTool ? (
          <div
            style={{
              padding: "12px 20px",
              backgroundColor: "rgba(255, 255, 255, 0.02)",
              borderBottom: "1px solid var(--line, rgba(255, 255, 255, 0.08))",
              flex: "none",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 5 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontWeight: 600, fontSize: 14 }}>{selTool.name}</span>
                <span
                  style={{
                    fontSize: 10,
                    textTransform: "uppercase",
                    fontWeight: 700,
                    padding: "1px 6px",
                    borderRadius: 4,
                    backgroundColor: effectStyle.bg,
                    color: effectStyle.text,
                    border: `1px solid ${effectStyle.border}`,
                  }}
                >
                  {effect}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    textTransform: "uppercase",
                    fontWeight: 700,
                    padding: "1px 6px",
                    borderRadius: 4,
                    backgroundColor: riskStyle.bg,
                    color: riskStyle.text,
                    border: `1px solid ${riskStyle.border}`,
                  }}
                >
                  {risk} risk
                </span>
                {cfg.requires_approval && (
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      padding: "1px 6px",
                      borderRadius: 4,
                      backgroundColor: "rgba(239, 68, 68, 0.15)",
                      color: "#f87171",
                      border: "1px solid rgba(239, 68, 68, 0.3)",
                    }}
                  >
                    HITL Gated
                  </span>
                )}
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="mono-sm fg-3" style={{ fontSize: 10 }}>
                  ID: {selTool.id}
                </span>
              </div>
            </div>

            <div style={{ fontSize: 12, color: "var(--fg-2, #94a3b8)", lineHeight: 1.4 }}>
              {cfg.description || "No description provided for this capability."}
            </div>
          </div>
        ) : (
          <div style={{ padding: 18, textAlign: "center", color: "var(--fg-3)" }}>
            Select a tool above to configure test parameters.
          </div>
        )}

        {/* Workbench Section Navigation Tabs */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 20px",
            borderBottom: "1px solid var(--line, rgba(255, 255, 255, 0.08))",
            backgroundColor: "var(--bg-1)",
            flex: "none",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <button
              onClick={() => setWorkbenchTab("parameters")}
              style={{
                padding: "9px 12px",
                fontSize: 12,
                fontWeight: workbenchTab === "parameters" ? 600 : 400,
                background: "none",
                border: "none",
                cursor: "pointer",
                color: workbenchTab === "parameters" ? "var(--accent, #6366f1)" : "var(--fg-2)",
                borderBottom: workbenchTab === "parameters" ? "2px solid var(--accent, #6366f1)" : "2px solid transparent",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <Icon name="sliders" size={13} />
              Parameters ({Object.keys(schemaProps).length})
            </button>

            <button
              onClick={() => setWorkbenchTab("console")}
              style={{
                padding: "9px 12px",
                fontSize: 12,
                fontWeight: workbenchTab === "console" ? 600 : 400,
                background: "none",
                border: "none",
                cursor: "pointer",
                color: workbenchTab === "console" ? "var(--accent, #6366f1)" : "var(--fg-2)",
                borderBottom: workbenchTab === "console" ? "2px solid var(--accent, #6366f1)" : "2px solid transparent",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <Icon name="terminal" size={13} />
              Execution Console
              {executing ? (
                <span className="dot spin" style={{ width: 6, height: 6 }} />
              ) : pendingApprovalId ? (
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    backgroundColor: "#f87171",
                    boxShadow: "0 0 6px #f87171",
                  }}
                  title="Approval Required"
                />
              ) : executionResult ? (
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    backgroundColor: executionResult.ok === false ? "#f87171" : "#4ade80",
                  }}
                />
              ) : null}
            </button>
          </div>

          {workbenchTab === "parameters" && (
            <div style={{ display: "flex", backgroundColor: "var(--bg-2, rgba(255,255,255,0.06))", borderRadius: 5, padding: 2 }}>
              <button
                className={`btn btn-sm ${inputMode === "schema" ? "btn-secondary" : "btn-ghost"}`}
                style={{ fontSize: 11, padding: "2px 8px", height: "auto" }}
                onClick={() => setInputMode("schema")}
              >
                Form
              </button>
              <button
                className={`btn btn-sm ${inputMode === "raw" ? "btn-secondary" : "btn-ghost"}`}
                style={{ fontSize: 11, padding: "2px 8px", height: "auto" }}
                onClick={() => setInputMode("raw")}
              >
                Raw JSON
              </button>
            </div>
          )}

          {workbenchTab === "console" && (
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {executionLatency !== null && (
                <span className="mono-sm" style={{ fontSize: 11, color: "var(--fg-2)" }}>
                  Latency: <strong style={{ color: "var(--fg-0)" }}>{executionLatency} ms</strong>
                </span>
              )}
              {onNav && (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => onNav("traces")}
                  style={{ fontSize: 11, gap: 4, padding: "2px 6px" }}
                  title="Inspect distributed traces and span waterfalls"
                >
                  <Icon name="traces" size={12} /> Traces
                </button>
              )}
            </div>
          )}
        </div>

        {/* Tab 1: Parameters Workbench */}
        {workbenchTab === "parameters" && (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>
              {inputMode === "schema" ? (
                Object.keys(schemaProps).length > 0 ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    {Object.entries(schemaProps).map(([key, prop]: [string, any]) => {
                      const isReq = requiredKeys.has(key);
                      const val = formValues[key] ?? "";
                      return (
                        <div
                          key={key}
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 5,
                            padding: "10px 14px",
                            borderRadius: 6,
                            backgroundColor: "var(--bg-1, rgba(255, 255, 255, 0.02))",
                            border: "1px solid var(--line, rgba(255, 255, 255, 0.06))",
                          }}
                        >
                          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                            <span style={{ fontSize: 12, fontWeight: 600, fontFamily: "var(--font-mono)" }}>
                              {key} {isReq && <span style={{ color: "#ef4444" }}>*</span>}
                            </span>
                            <span
                              style={{
                                fontSize: 10,
                                color: "var(--fg-3)",
                                textTransform: "uppercase",
                                backgroundColor: "rgba(255,255,255,0.05)",
                                padding: "1px 5px",
                                borderRadius: 3,
                              }}
                            >
                              {prop.type || "string"}
                            </span>
                          </div>
                          {prop.description && (
                            <span style={{ fontSize: 11, color: "var(--fg-2)" }}>{prop.description}</span>
                          )}
                          {prop.type === "boolean" ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                              <input
                                type="checkbox"
                                checked={Boolean(val)}
                                onChange={(e) => updateFormField(key, e.target.checked)}
                              />
                              <span style={{ fontSize: 12 }}>{val ? "True" : "False"}</span>
                            </div>
                          ) : prop.type === "number" || prop.type === "integer" ? (
                            <input
                              className="input mono-sm"
                              type="number"
                              style={{ fontSize: 12, height: 32 }}
                              value={val}
                              onChange={(e) => updateFormField(key, parseFloat(e.target.value) || 0)}
                            />
                          ) : prop.type === "object" || prop.type === "array" ? (
                            <textarea
                              className="input mono-sm"
                              style={{ height: 64, fontSize: 11, resize: "vertical" }}
                              value={typeof val === "object" ? JSON.stringify(val, null, 2) : val}
                              onChange={(e) => {
                                try {
                                  updateFormField(key, JSON.parse(e.target.value));
                                } catch {
                                  updateFormField(key, e.target.value);
                                }
                              }}
                            />
                          ) : (
                            <input
                              className="input"
                              type="text"
                              style={{ fontSize: 12, height: 32 }}
                              value={val}
                              placeholder={prop.default !== undefined ? String(prop.default) : `Enter ${key}...`}
                              onChange={(e) => updateFormField(key, e.target.value)}
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div
                    style={{
                      padding: 24,
                      textAlign: "center",
                      color: "var(--fg-3)",
                      border: "1px dashed var(--line, rgba(255, 255, 255, 0.1))",
                      borderRadius: 8,
                    }}
                  >
                    This tool requires no input arguments. Click "Execute Tool" below to dispatch immediately.
                  </div>
                )
              ) : (
                <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 8 }}>
                  <textarea
                    className="input mono-sm"
                    style={{
                      flex: 1,
                      minHeight: 180,
                      fontSize: 12,
                      fontFamily: "var(--font-mono, monospace)",
                      lineHeight: 1.5,
                      padding: 12,
                      resize: "none",
                    }}
                    value={rawJson}
                    onChange={(e) => updateRawJson(e.target.value)}
                  />
                  {jsonError && (
                    <div style={{ color: "#ef4444", fontSize: 11, display: "flex", alignItems: "center", gap: 5 }}>
                      <Icon name="x" size={13} /> {jsonError}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Execution Action Footer */}
            <div
              style={{
                padding: "12px 20px",
                borderTop: "1px solid var(--line, rgba(255, 255, 255, 0.08))",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                backgroundColor: "var(--bg-1)",
                flex: "none",
              }}
            >
              <div style={{ fontSize: 11, color: "var(--fg-3)" }}>
                Shortcut: <kbd style={{ padding: "2px 5px", background: "var(--bg-2)", borderRadius: 3 }}>Ctrl</kbd> + <kbd style={{ padding: "2px 5px", background: "var(--bg-2)", borderRadius: 3 }}>Enter</kbd>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {selTool && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setExternalChatInput(
                        `Inspect configuration, schema, and security policy for tool "${selTool.name}" (${selTool.id}).`
                      );
                    }}
                    title="Consult Integration Manager subagent about this tool"
                    style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 12px", fontSize: 12 }}
                  >
                    <Icon name="bot" size={13} style={{ color: "#a855f7" }} /> Ask Manager
                  </button>
                )}
                <button
                  className="btn btn-primary"
                  disabled={executing || !selTool}
                  onClick={() => runTest()}
                  style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 18px" }}
                >
                  {executing ? (
                    <>
                      <Icon name="activity" size={14} className="spin" /> Executing Policy...
                    </>
                  ) : (
                    <>
                      <Icon name="playground" size={14} /> Execute Tool
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Execution Console */}
        {workbenchTab === "console" && (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {/* HITL HUMAN-IN-THE-LOOP APPROVAL BANNER */}
            {pendingApprovalId && (
              <div
                style={{
                  padding: "14px 20px",
                  backgroundColor: "rgba(239, 68, 68, 0.08)",
                  borderBottom: "1px solid rgba(239, 68, 68, 0.25)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Icon name="shield-check" size={17} style={{ color: "#f87171" }} />
                    <span style={{ fontWeight: 600, fontSize: 13, color: "#fecaca" }}>
                      Human-In-The-Loop Approval Gate Triggered
                    </span>
                  </div>
                  <span className="mono-sm" style={{ fontSize: 10, color: "rgba(255, 255, 255, 0.7)" }}>
                    Ref: {pendingApprovalId}
                  </span>
                </div>

                <div style={{ fontSize: 11.5, color: "rgba(255, 255, 255, 0.85)", lineHeight: 1.5 }}>
                  This tool action was classified with <strong>{risk} risk</strong> and <strong>{effect} effect</strong>.
                  ToolPolicyService requires explicit authorization before arguments can be dispatched downstream.
                </div>

                <div style={{ display: "flex", gap: 8, marginTop: 2 }}>
                  <button
                    className="btn btn-primary btn-sm"
                    disabled={approvalBusy}
                    onClick={() => handleDecideApproval("approve")}
                    style={{
                      backgroundColor: "#dc2626",
                      borderColor: "#ef4444",
                      fontSize: 11,
                      padding: "5px 12px",
                    }}
                  >
                    {approvalBusy ? "Authorizing..." : "Approve & Execute Now"}
                  </button>
                  <button
                    className="btn btn-ghost btn-sm"
                    disabled={approvalBusy}
                    onClick={() => handleDecideApproval("reject")}
                    style={{ fontSize: 11 }}
                  >
                    Reject Call
                  </button>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => {
                      setExternalChatInput(
                        `Tool "${selTool?.name}" triggered a HITL approval gate (Risk: ${risk}, Effect: ${effect}, Ref: ${pendingApprovalId}). What are the risks of authorizing this execution?`
                      );
                    }}
                    style={{ fontSize: 11, color: "var(--accent, #a855f7)", gap: 4, marginLeft: "auto" }}
                  >
                    <Icon name="bot" size={12} /> Consult Manager
                  </button>
                </div>

                {approvalDecisionStatus && (
                  <div style={{ fontSize: 11, color: "var(--fg-2)", marginTop: 2 }}>
                    {approvalDecisionStatus}
                  </div>
                )}
              </div>
            )}

            {/* Console Sub-Tabs */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                padding: "0 20px",
                borderBottom: "1px solid var(--line, rgba(255, 255, 255, 0.08))",
                backgroundColor: "var(--bg-0, #090a0f)",
                flex: "none",
              }}
            >
              <button
                onClick={() => setResultTab("response")}
                style={{
                  padding: "9px 12px",
                  fontSize: 11.5,
                  fontWeight: 500,
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: resultTab === "response" ? "var(--accent, #6366f1)" : "var(--fg-3)",
                  borderBottom: resultTab === "response" ? "2px solid var(--accent, #6366f1)" : "2px solid transparent",
                }}
              >
                Response JSON
              </button>
              <button
                onClick={() => setResultTab("diagnostics")}
                style={{
                  padding: "9px 12px",
                  fontSize: 11.5,
                  fontWeight: 500,
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: resultTab === "diagnostics" ? "var(--accent, #6366f1)" : "var(--fg-3)",
                  borderBottom: resultTab === "diagnostics" ? "2px solid var(--accent, #6366f1)" : "2px solid transparent",
                }}
              >
                Sanitized Diagnostics
              </button>
              <button
                onClick={() => setResultTab("audit")}
                style={{
                  padding: "9px 12px",
                  fontSize: 11.5,
                  fontWeight: 500,
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: resultTab === "audit" ? "var(--accent, #6366f1)" : "var(--fg-3)",
                  borderBottom: resultTab === "audit" ? "2px solid var(--accent, #6366f1)" : "2px solid transparent",
                }}
              >
                Policy & Security
              </button>
            </div>

            {/* Console Output Body */}
            <div style={{ flex: 1, overflowY: "auto", padding: 18 }}>
              {executionError && (
                <div
                  style={{
                    padding: "12px 16px",
                    borderRadius: 6,
                    backgroundColor: "rgba(239, 68, 68, 0.12)",
                    border: "1px solid rgba(239, 68, 68, 0.25)",
                    color: "#f87171",
                    fontSize: 12,
                    marginBottom: 14,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                  }}
                >
                  <div>
                    <strong>Execution Error:</strong> {executionError}
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      setExternalChatInput(
                        `The execution test for "${selTool?.name}" (${selTool?.id}) failed with error: "${executionError}". How can I diagnose and fix this?`
                      );
                    }}
                    style={{ fontSize: 11, padding: "3px 8px", whiteSpace: "nowrap", gap: 5 }}
                  >
                    <Icon name="bot" size={12} style={{ color: "#a855f7" }} /> Ask Manager
                  </button>
                </div>
              )}

              {resultTab === "response" && (
                <div>
                  {executionResult ? (
                    <div style={{ position: "relative" }}>
                      <button
                        className="btn btn-ghost btn-sm"
                        style={{ position: "absolute", right: 8, top: 8, fontSize: 11 }}
                        onClick={() => navigator.clipboard.writeText(JSON.stringify(executionResult, null, 2))}
                      >
                        Copy
                      </button>
                      <pre
                        style={{
                          margin: 0,
                          padding: 14,
                          borderRadius: 6,
                          backgroundColor: "var(--bg-1, #0c0e14)",
                          fontFamily: "var(--font-mono, monospace)",
                          fontSize: 11.5,
                          overflowX: "auto",
                          border: "1px solid var(--line, rgba(255, 255, 255, 0.08))",
                        }}
                      >
                        {JSON.stringify(executionResult, null, 2)}
                      </pre>
                    </div>
                  ) : (
                    <div
                      style={{
                        padding: 30,
                        textAlign: "center",
                        color: "var(--fg-3)",
                        border: "1px dashed var(--line, rgba(255, 255, 255, 0.1))",
                        borderRadius: 8,
                      }}
                    >
                      No execution output yet. Return to Parameters tab and click "Execute Tool" to dispatch a test payload.
                    </div>
                  )}
                </div>
              )}

              {resultTab === "diagnostics" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <div className="card" style={{ padding: 14 }}>
                    <span className="t-h3" style={{ fontSize: 13, marginBottom: 8, display: "block" }}>
                      Sanitized Telemetry & Execution Context
                    </span>
                    <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 8, fontSize: 12 }}>
                      <span className="fg-3">Execution Mode:</span>
                      <span className="mono-sm">Secured Sub-Agent Dispatch</span>

                      <span className="fg-3">Active Tool Kind:</span>
                      <span className="mono-sm">{selTool?.kind || "unknown"}</span>

                      <span className="fg-3">HITL Interception:</span>
                      <span>
                        {selTool?.config?.requires_approval
                          ? "Gated by ToolPolicyService (Active)"
                          : "None (Policy Bypass Permitted)"}
                      </span>

                      <span className="fg-3">Latency:</span>
                      <span>{executionLatency !== null ? `${executionLatency} ms` : "N/A"}</span>

                      <span className="fg-3">Audit Logs:</span>
                      <span className="mono-sm">Forwarded to Project Telemetry</span>
                    </div>
                  </div>

                  <div className="card" style={{ padding: 14 }}>
                    <span className="t-h3" style={{ fontSize: 13, marginBottom: 8, display: "block" }}>
                      Parameter Payload Snapshot
                    </span>
                    <pre
                      style={{
                        margin: 0,
                        padding: 10,
                        borderRadius: 6,
                        backgroundColor: "var(--bg-1)",
                        fontFamily: "var(--font-mono)",
                        fontSize: 11,
                        overflowX: "auto",
                      }}
                    >
                      {rawJson}
                    </pre>
                  </div>
                </div>
              )}

              {resultTab === "audit" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <div className="card" style={{ padding: 14 }}>
                    <span className="t-h3" style={{ fontSize: 13, marginBottom: 8, display: "block" }}>
                      ToolPolicyService Evaluation Invariants
                    </span>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ color: "#4ade80" }}>✓</span>
                        <span>Project Scope: Verified against tenant/project boundary</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ color: "#4ade80" }}>✓</span>
                        <span>Activation Gate: Enabled in tool registry</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ color: "#4ade80" }}>✓</span>
                        <span>Caller Boundary: Direct execution strictly confined to test_endpoint</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ color: cfg.requires_approval ? "#fbbf24" : "#4ade80" }}>
                          {cfg.requires_approval ? "⚠" : "✓"}
                        </span>
                        <span>
                          HITL Approval Requirement: {cfg.requires_approval ? "Active (Required)" : "Standard Bypass"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ==================================================================== */}
      {/* DRAGGABLE DIVIDER (1px hairline matching HomeScreen)                 */}
      {/* ==================================================================== */}
      <div
        onMouseDown={handleMouseDown}
        style={{
          width: 1,
          flex: "none",
          position: "relative",
          background: "var(--line, rgba(255, 255, 255, 0.08))",
          cursor: "col-resize",
          userSelect: "none",
          outline: "none",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: -4,
            right: -4,
            cursor: "col-resize",
            zIndex: 10,
          }}
          title="Drag to resize Workbench and Chat panels"
        />
      </div>

      {/* ==================================================================== */}
      {/* RIGHT HALF: Integration Manager Sub-Agent                            */}
      {/* ==================================================================== */}
      <div
        style={{
          width: `${100 - splitPct}%`,
          height: "100%",
          minWidth: 340,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <ChatScreen
          project={project}
          persona="tool_manager"
          externalInput={externalChatInput}
          onExternalInputConsumed={() => setExternalChatInput("")}
        />
      </div>
    </div>
  );
}
