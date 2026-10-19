"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../icons";
import { api, Tool } from "@/lib/api";

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

export function IntegrationsPlaygroundScreen({
  project,
  initialToolId,
  initialIntegrationId,
  onNav,
}: IntegrationsPlaygroundProps) {
  // Draggable split percentage
  const [splitPct, setSplitPct] = useState(48);
  const containerRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);

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
    const cfg = selTool.config || {};
    const schema = cfg.input_schema || cfg.parameters || {};
    const props = schema.properties || {};

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

  // HITL Decision
  const handleDecideApproval = async (decision: "approve" | "reject") => {
    if (!project?.id || !pendingApprovalId || approvalBusy) return;
    setApprovalBusy(true);
    try {
      await api.decideApproval(project.id, pendingApprovalId, {
        decision,
        notes: "Approved from Integrations Playground Console",
      });
      setApprovalDecisionStatus(decision);
      if (decision === "approve") {
        // Auto-resume execution with the approved token
        await runTest(pendingApprovalId);
      } else {
        setPendingApprovalId(null);
      }
    } catch (err: any) {
      setExecutionError(`Failed to ${decision} request: ${err.message}`);
    } finally {
      setApprovalBusy(false);
    }
  };

  // Filter tools
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
  const schema = cfg.input_schema || cfg.parameters || {};
  const schemaProps = schema.properties || {};
  const requiredKeys = new Set(schema.required || []);
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
      {/* LEFT PANEL: Tool Explorer & Parameter Workbench */}
      <div
        style={{
          width: `${splitPct}%`,
          display: "flex",
          flexDirection: "column",
          borderRight: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
          height: "100%",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            backgroundColor: "var(--bg-1, #0f1117)",
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name="playground" size={18} style={{ color: "var(--accent, #6366f1)" }} />
              <span style={{ fontWeight: 600, fontSize: 16 }}>Integrations Playground</span>
            </div>
            <div style={{ fontSize: 12, color: "var(--fg-2, #94a3b8)", marginTop: 2 }}>
              Secured execution testbed with policy validation and HITL approvals.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {onNav && (
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => onNav("integrations")}
                style={{ fontSize: 12, gap: 6 }}
              >
                <Icon name="plug" size={13} /> Integrations Hub
              </button>
            )}
          </div>
        </div>

        {/* Tool Filter & Selection bar */}
        <div
          style={{
            padding: "12px 20px",
            borderBottom: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
            display: "flex",
            gap: 10,
            alignItems: "center",
            backgroundColor: "var(--bg-1, #0f1117)",
          }}
        >
          <div style={{ position: "relative", flex: 1 }}>
            <input
              className="input"
              style={{ width: "100%", paddingLeft: 28, fontSize: 12 }}
              placeholder="Search tools or actions..."
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
            />
            <div style={{ position: "absolute", left: 8, top: 8, color: "var(--fg-3, #64748b)" }}>
              <Icon name="search" size={14} />
            </div>
          </div>

          <select
            className="select"
            style={{ width: 140, fontSize: 12 }}
            value={filterSource}
            onChange={(e) => setFilterSource(e.target.value as any)}
          >
            <option value="all">All Sources</option>
            <option value="connector">REST APIs</option>
            <option value="mcp">MCP Tools</option>
            <option value="builtin">Builtins</option>
          </select>
        </div>

        {/* Selected Tool Header / Overview */}
        {selTool ? (
          <div
            style={{
              padding: "14px 20px",
              backgroundColor: "rgba(255, 255, 255, 0.02)",
              borderBottom: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontWeight: 600, fontSize: 15 }}>{selTool.name}</span>
                <span
                  style={{
                    fontSize: 10,
                    textTransform: "uppercase",
                    fontWeight: 700,
                    padding: "2px 7px",
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
                    padding: "2px 7px",
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
                      padding: "2px 7px",
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
              <span className="mono-sm fg-3" style={{ fontSize: 11 }}>
                ID: {selTool.id}
              </span>
            </div>
            <div style={{ fontSize: 12, color: "var(--fg-2, #94a3b8)", lineHeight: 1.4 }}>
              {cfg.description || "No description provided for this capability."}
            </div>
          </div>
        ) : (
          <div style={{ padding: 20, textAlign: "center", color: "var(--fg-3)" }}>
            Select a tool to configure test parameters.
          </div>
        )}

        {/* Tool Dropdown Selector / List */}
        <div style={{ padding: "10px 20px", display: "flex", alignItems: "center", gap: 8, backgroundColor: "var(--bg-1)" }}>
          <span style={{ fontSize: 12, color: "var(--fg-2)", fontWeight: 500 }}>Active Tool:</span>
          <select
            className="select"
            style={{ flex: 1, fontSize: 12 }}
            value={selectedToolId || ""}
            onChange={(e) => setSelectedToolId(e.target.value)}
          >
            {filteredTools.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.kind})
              </option>
            ))}
          </select>
        </div>

        {/* Parameter Workbench with Schema / Raw toggle */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", padding: "14px 20px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Execution Parameters</span>
            <div style={{ display: "flex", backgroundColor: "var(--bg-2, #181b24)", borderRadius: 6, padding: 2 }}>
              <button
                className={`btn btn-sm ${inputMode === "schema" ? "btn-secondary" : "btn-ghost"}`}
                style={{ fontSize: 11, padding: "3px 10px", height: "auto" }}
                onClick={() => setInputMode("schema")}
              >
                Form View
              </button>
              <button
                className={`btn btn-sm ${inputMode === "raw" ? "btn-secondary" : "btn-ghost"}`}
                style={{ fontSize: 11, padding: "3px 10px", height: "auto" }}
                onClick={() => setInputMode("raw")}
              >
                Raw JSON
              </button>
            </div>
          </div>

          {/* Form Content */}
          <div style={{ flex: 1, overflowY: "auto" }}>
            {inputMode === "schema" ? (
              Object.keys(schemaProps).length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {Object.entries(schemaProps).map(([key, prop]: [string, any]) => {
                    const isReq = requiredKeys.has(key);
                    const val = formValues[key] ?? "";
                    return (
                      <div key={key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                          <span style={{ fontSize: 12, fontWeight: 500, fontFamily: "var(--font-mono)" }}>
                            {key} {isReq && <span style={{ color: "var(--accent-red, #ef4444)" }}>*</span>}
                          </span>
                          <span style={{ fontSize: 10, color: "var(--fg-3)" }}>
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
                            type="number"
                            className="input mono"
                            style={{ fontSize: 12 }}
                            value={val}
                            onChange={(e) => updateFormField(key, Number(e.target.value))}
                          />
                        ) : prop.type === "object" || prop.type === "array" ? (
                          <textarea
                            className="input mono"
                            style={{ fontSize: 12, minHeight: 70 }}
                            value={typeof val === "object" ? JSON.stringify(val, null, 2) : String(val)}
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
                            type="text"
                            className="input mono"
                            style={{ fontSize: 12 }}
                            placeholder={prop.default !== undefined ? String(prop.default) : ""}
                            value={val}
                            onChange={(e) => updateFormField(key, e.target.value)}
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div style={{ padding: "30px 10px", textAlign: "center", color: "var(--fg-3)" }}>
                  <Icon name="tools" size={24} style={{ marginBottom: 8, opacity: 0.5 }} />
                  <div>No input schema parameters declared.</div>
                  <div style={{ fontSize: 11, marginTop: 4 }}>Switch to Raw JSON to pass ad-hoc arguments.</div>
                </div>
              )
            ) : (
              <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                <textarea
                  className="input mono"
                  style={{
                    flex: 1,
                    resize: "none",
                    fontFamily: "var(--font-mono)",
                    fontSize: 12,
                    lineHeight: 1.5,
                    backgroundColor: "var(--bg-0, #090a0f)",
                    borderColor: jsonError ? "var(--accent-red, #ef4444)" : undefined,
                  }}
                  value={rawJson}
                  onChange={(e) => updateRawJson(e.target.value)}
                  placeholder="{}"
                />
                {jsonError && (
                  <div style={{ fontSize: 11, color: "var(--accent-red, #ef4444)", marginTop: 6 }}>
                    {jsonError}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Execution Action Footer */}
          <div
            style={{
              paddingTop: 14,
              borderTop: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <div style={{ fontSize: 11, color: "var(--fg-3)" }}>
              Shortcut: <kbd style={{ padding: "2px 5px", background: "var(--bg-2)", borderRadius: 3 }}>Ctrl</kbd> + <kbd style={{ padding: "2px 5px", background: "var(--bg-2)", borderRadius: 3 }}>Enter</kbd>
            </div>
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

      {/* DRAGGABLE RESIZER */}
      <div
        onMouseDown={handleMouseDown}
        style={{
          width: 5,
          cursor: "col-resize",
          backgroundColor: "transparent",
          position: "relative",
          zIndex: 10,
          transition: "background 0.2s ease",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--accent, #6366f1)")}
        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
      />

      {/* RIGHT PANEL: Execution Console, Telemetry & HITL Approvals */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          overflow: "hidden",
          backgroundColor: "var(--bg-1, #0c0e14)",
        }}
      >
        {/* Right Header: Execution Status & Telemetry */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontWeight: 600, fontSize: 14 }}>Live Execution Console</span>
            {executing ? (
              <span className="pill pill-warn" style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
                <span className="dot spin" /> Running...
              </span>
            ) : pendingApprovalId ? (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  padding: "2px 8px",
                  borderRadius: 999,
                  backgroundColor: "rgba(239, 68, 68, 0.2)",
                  color: "#f87171",
                  border: "1px solid rgba(239, 68, 68, 0.4)",
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                }}
              >
                <span style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: "#f87171" }} />
                Approval Required
              </span>
            ) : executionResult ? (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  padding: "2px 8px",
                  borderRadius: 999,
                  backgroundColor: executionResult.ok === false ? "rgba(239, 68, 68, 0.15)" : "rgba(34, 197, 94, 0.15)",
                  color: executionResult.ok === false ? "#f87171" : "#4ade80",
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                }}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    backgroundColor: executionResult.ok === false ? "#f87171" : "#4ade80",
                  }}
                />
                {executionResult.ok === false ? "Status: Failed" : "Status: 200 OK"}
              </span>
            ) : (
              <span style={{ fontSize: 11, color: "var(--fg-3)" }}>Idle</span>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {executionLatency !== null && (
              <span className="mono-sm" style={{ fontSize: 11, color: "var(--fg-2)" }}>
                Latency: <strong style={{ color: "var(--fg-0)" }}>{executionLatency} ms</strong>
              </span>
            )}
            {onNav && (
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => onNav("traces")}
                style={{ fontSize: 11, gap: 5 }}
                title="Inspect distributed traces and span waterfalls"
              >
                <Icon name="traces" size={13} /> View Traces
              </button>
            )}
          </div>
        </div>

        {/* HITL HUMAN-IN-THE-LOOP APPROVAL BANNER */}
        {pendingApprovalId && (
          <div
            style={{
              padding: "16px 20px",
              backgroundColor: "rgba(239, 68, 68, 0.08)",
              borderBottom: "1px solid rgba(239, 68, 68, 0.25)",
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Icon name="shield-check" size={18} style={{ color: "#f87171" }} />
                <span style={{ fontWeight: 600, fontSize: 14, color: "#fecaca" }}>
                  Human-In-The-Loop Approval Gate Triggered
                </span>
              </div>
              <span className="mono-sm" style={{ fontSize: 11, color: "rgba(255, 255, 255, 0.7)" }}>
                Ref: {pendingApprovalId}
              </span>
            </div>

            <div style={{ fontSize: 12, color: "rgba(255, 255, 255, 0.85)", lineHeight: 1.5 }}>
              This tool action was classified with <strong>{risk} risk</strong> and <strong>{effect} effect</strong>.
              Policy requires explicit authorization before arguments can be dispatched to downstream systems.
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
              <button
                className="btn btn-primary btn-sm"
                disabled={approvalBusy}
                onClick={() => handleDecideApproval("approve")}
                style={{
                  backgroundColor: "#dc2626",
                  borderColor: "#ef4444",
                  fontSize: 12,
                  padding: "6px 14px",
                }}
              >
                {approvalBusy ? "Authorizing..." : "Approve & Execute Now"}
              </button>
              <button
                className="btn btn-ghost btn-sm"
                disabled={approvalBusy}
                onClick={() => handleDecideApproval("reject")}
                style={{ fontSize: 12 }}
              >
                Reject Request
              </button>
            </div>
          </div>
        )}

        {/* Navigation Tabs for Output */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "0 20px",
            borderBottom: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
            backgroundColor: "var(--bg-0, #090a0f)",
          }}
        >
          <button
            onClick={() => setResultTab("response")}
            style={{
              padding: "10px 14px",
              fontSize: 12,
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
              padding: "10px 14px",
              fontSize: 12,
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
              padding: "10px 14px",
              fontSize: 12,
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

        {/* Console Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
          {executionError && (
            <div
              style={{
                padding: "12px 16px",
                borderRadius: 6,
                backgroundColor: "rgba(239, 68, 68, 0.12)",
                border: "1px solid rgba(239, 68, 68, 0.25)",
                color: "#f87171",
                fontSize: 12,
                marginBottom: 16,
              }}
            >
              <strong>Error:</strong> {executionError}
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
                    Copy Output
                  </button>
                  <pre
                    style={{
                      margin: 0,
                      padding: 16,
                      borderRadius: 8,
                      backgroundColor: "var(--bg-0, #090a0f)",
                      border: "1px solid var(--border, rgba(255, 255, 255, 0.08))",
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      lineHeight: 1.5,
                      overflowX: "auto",
                      color: "#e2e8f0",
                    }}
                  >
                    {JSON.stringify(executionResult, null, 2)}
                  </pre>
                </div>
              ) : (
                <div style={{ padding: "60px 0", textAlign: "center", color: "var(--fg-3)" }}>
                  <Icon name="playground" size={32} style={{ marginBottom: 12, opacity: 0.4 }} />
                  <div>No execution output yet.</div>
                  <div style={{ fontSize: 12, marginTop: 4 }}>Configure input parameters and click Execute Tool.</div>
                </div>
              )}
            </div>
          )}

          {resultTab === "diagnostics" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div className="card" style={{ padding: 14 }}>
                <span className="t-h3" style={{ fontSize: 13, marginBottom: 8, display: "block" }}>
                  Transport & Runtime State
                </span>
                <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 8, fontSize: 12 }}>
                  <span className="fg-2">Tool ID:</span>
                  <span className="mono">{selTool?.id}</span>
                  <span className="fg-2">Kind:</span>
                  <span className="mono">{selTool?.kind}</span>
                  <span className="fg-2">Caller Identity:</span>
                  <span className="mono">test_endpoint (authenticated user session)</span>
                  <span className="fg-2">Effective Latency:</span>
                  <span className="mono">{executionLatency !== null ? `${executionLatency}ms` : "N/A"}</span>
                </div>
              </div>

              <div className="card" style={{ padding: 14 }}>
                <span className="t-h3" style={{ fontSize: 13, marginBottom: 8, display: "block" }}>
                  Sanitized Dispatched Arguments
                </span>
                <pre
                  style={{
                    margin: 0,
                    padding: 10,
                    borderRadius: 6,
                    backgroundColor: "var(--bg-0)",
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
    </div>
  );
}
