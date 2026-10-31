"use client";
/* Alberto Automate 2.0: n8n-inspired 3-panel node configuration modal.
   Columns:
   [ INPUT DATA ] (Previous node messages, drag-and-drop properties)
   [ PARAMETERS ] (Node configuration form, accepts dropped variables)
   [ OUTPUT DATA ] (Execution result, status, duration, Execute Step action)
*/

import { useState, useMemo, useCallback, useEffect } from "react";
import { Icon } from "../icons";
import { Tile, StatusPill } from "../primitives";
import { NODE_META } from "@/lib/data";
import { api, type Tool, type ToolSet, type Agent, type McpClientT, type ComponentT } from "@/lib/api";
import type { FlowNode, FlowEdge } from "@/lib/graph";

interface NodeConfigModalProps {
  node: FlowNode;
  nodes: FlowNode[];
  edges: FlowEdge[];
  project: any;
  workflowId: string;
  tools: Tool[];
  toolSets: ToolSet[];
  agents: Agent[];
  mcpServers: McpClientT[];
  components: ComponentT[];
  dynamic?: Record<string, string[]>;
  pinnedData?: Record<string, any>;
  onUpdateConfig: (cfg: Record<string, any>) => void;
  onRenameNode: (nodeId: string, name: string) => void;
  onDeleteNode: (nodeId: string) => void;
  onPinData?: (nodeId: string, data: any) => void;
  onClose: () => void;
  renderParameters: () => React.ReactNode;
}

export function NodeConfigModal({
  node,
  nodes,
  edges,
  project,
  workflowId,
  pinnedData = {},
  onUpdateConfig,
  onRenameNode,
  onDeleteNode,
  onPinData,
  onClose,
  renderParameters,
}: NodeConfigModalProps) {
  const type = node.data.nodeType;
  const config = node.data.config || {};
  const meta = NODE_META[type] || { icon: "n_agent", color: "var(--accent)", label: type };

  // Upstream nodes supplying input
  const upstreamEdges = useMemo(() => edges.filter((e) => e.target === node.id), [edges, node.id]);
  const upstreamNodes = useMemo(() => {
    return upstreamEdges.map((e) => nodes.find((n) => n.id === e.source)).filter(Boolean) as FlowNode[];
  }, [upstreamEdges, nodes]);

  const [selectedUpstreamId, setSelectedUpstreamId] = useState<string>(
    upstreamNodes[0]?.id || ""
  );

  const activeUpstreamNode = useMemo(() => {
    return upstreamNodes.find((n) => n.id === selectedUpstreamId) || upstreamNodes[0] || null;
  }, [upstreamNodes, selectedUpstreamId]);

  // Derive input message from upstream debug, pinned data, or sensible default
  const inputMessage = useMemo(() => {
    if (pinnedData[node.id]) return pinnedData[node.id];
    if (selectedUpstreamId === "__combined__" && upstreamNodes.length > 1) {
      const branches: Record<string, any> = {};
      upstreamNodes.forEach((un) => {
        const out = un?.data?.debug?.output;
        branches[un.id] = out?.payload !== undefined ? out.payload : (out || {});
      });
      return {
        _msgid: "msg-combined",
        topic: "combined",
        payload: branches,
        _branches: branches,
        _alberto: { source_node: "combined_upstream" },
      };
    }
    if (activeUpstreamNode?.data?.debug?.output) {
      const out = activeUpstreamNode.data.debug.output;
      if (out.msg) return out.msg;
      return {
        _msgid: `msg-${activeUpstreamNode.id}`,
        topic: out.topic || "",
        payload: out.payload !== undefined ? out.payload : out,
        _alberto: { source_node: activeUpstreamNode.id },
      };
    }
    return {
      _msgid: "msg-sample",
      topic: "default",
      payload: { message: "Sample input message payload" },
      _alberto: { source_node: "simulated" },
    };
  }, [pinnedData, node.id, activeUpstreamNode, selectedUpstreamId, upstreamNodes]);

  // Output message from node's debug execution or last step test
  const [stepExecuting, setStepExecuting] = useState(false);
  const [testMode, setTestMode] = useState<"dry_run" | "live">("dry_run");
  const [stepResult, setStepResult] = useState<{
    ok?: boolean;
    output?: any;
    duration_ms?: number;
    error?: string;
    mocked?: boolean;
    requires_approval?: boolean;
    unsupported_dry_run?: boolean;
  } | null>(null);

  const outputMessage = useMemo(() => {
    if (stepResult?.output) return stepResult.output;
    if (node.data?.debug?.output) return node.data.debug.output;
    return null;
  }, [stepResult, node.data?.debug?.output]);

  // View modes: tree | json | table
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const [inputTab, setInputTab] = useState<"tree" | "json" | "table">("tree");
  const [outputTab, setOutputTab] = useState<"tree" | "json" | "table">("tree");
  const [inputSearch, setInputSearch] = useState("");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Single step execution via backend /step endpoint
  const executeStep = useCallback(async () => {
    if (!project?.id || !workflowId) return;
    setStepExecuting(true);
    setStepResult(null);
    try {
      const res = await api.executeStep(project.id, workflowId, {
        node_id: node.id,
        node_type: node.data.nodeType,
        config: node.data.config || {},
        mode: testMode,
        input_state: {
          msg: inputMessage,
          payload: inputMessage?.payload,
          topic: inputMessage?.topic || "",
        },
      });
      setStepResult(res);
    } catch (err: any) {
      setStepResult({ ok: false, error: err?.message || "Execution failed" } as any);
    } finally {
      setStepExecuting(false);
    }
  }, [project?.id, workflowId, node, inputMessage]);

  const copyExpr = useCallback((expr: string) => {
    navigator.clipboard?.writeText(expr);
    setCopiedKey(expr);
    setTimeout(() => setCopiedKey(null), 1500);
  }, []);

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: "rgba(0, 0, 0, 0.65)",
        backdropFilter: "blur(4px)",
        zIndex: 999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "16px",
      }}
    >
      <div
        className="card col"
        style={{
          width: "96vw",
          maxWidth: 1540,
          height: "92vh",
          background: "var(--bg-1)",
          border: "1px solid var(--line)",
          borderRadius: 4,
          boxShadow: "0 24px 64px rgba(0,0,0,0.4)",
          overflow: "hidden",
        }}
      >
        {/* Modal Top Bar */}
        <div
          className="row spread"
          style={{
            padding: "10px 18px",
            borderBottom: "1px solid var(--line)",
            background: "var(--bg-2)",
            flex: "none",
            alignItems: "center",
          }}
        >
          <div className="row gap3" style={{ alignItems: "center", minWidth: 0 }}>
            <Tile icon={meta.icon} color={meta.color} size={30} />
            <div className="col" style={{ minWidth: 0 }}>
              <div className="row gap2" style={{ alignItems: "center" }}>
                <span className="t-h3 truncate" style={{ maxWidth: 360 }}>
                  {config.name || meta.label || node.id}
                </span>
                <span className="typechip">{type}</span>
                <span className="mono-sm fg-2">#{node.id}</span>
              </div>
              <span className="t-caption fg-2">
                Configure node parameters and map upstream message variables
              </span>
            </div>
          </div>

          <div className="row gap2" style={{ alignItems: "center" }}>
            <div className="row gap1" style={{ alignItems: "center", background: "var(--bg-3)", borderRadius: 3, padding: "2px 4px" }}>
              <button
                type="button"
                className={`chip ${testMode === "dry_run" ? "chip-active" : ""}`}
                style={{ height: 20, fontSize: 10, cursor: "pointer" }}
                onClick={() => setTestMode("dry_run")}
                title="Safe test: simulated execution without mutating external resources"
              >
                Safe (Dry Run)
              </button>
              <button
                type="button"
                className={`chip ${testMode === "live" ? "chip-active" : ""}`}
                style={{ height: 20, fontSize: 10, cursor: "pointer", color: testMode === "live" ? "var(--warn)" : undefined }}
                onClick={() => setTestMode("live")}
                title="Live test: real tool execution subject to authorization and approval policies"
              >
                Live
              </button>
            </div>

            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={executeStep}
              disabled={stepExecuting}
              title={`Test run this node in ${testMode} mode`}
              style={{ gap: 6, fontWeight: 600 }}
            >
              <Icon
                name={stepExecuting ? "refresh" : "play"}
                size={14}
                style={stepExecuting ? { animation: "spin 1s linear infinite" } : { color: "var(--accent)" }}
              />
              {stepExecuting ? "Executing…" : "Test Step"}
            </button>

            {onPinData && (
              <button
                type="button"
                className={`btn btn-sm ${pinnedData[node.id] ? "btn-primary" : "btn-ghost"}`}
                onClick={() => onPinData(node.id, pinnedData[node.id] ? null : inputMessage)}
                title={pinnedData[node.id] ? "Unpin test data" : "Pin input as test data"}
                style={{ gap: 5 }}
              >
                <Icon name="check" size={13} />
                {pinnedData[node.id] ? "Pinned Data" : "Pin Test Data"}
              </button>
            )}

            <button
              type="button"
              className="iconbtn"
              onClick={() => onDeleteNode(node.id)}
              title="Delete node"
              style={{ color: "var(--err)" }}
            >
              <Icon name="trash" size={15} />
            </button>

            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={onClose}
              style={{ minWidth: 70 }}
            >
              Done
            </button>
          </div>
        </div>

        {/* 3-Panel Main Layout */}
        <div className="row" style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
          {/* PANEL 1: INPUT DATA */}
          <div
            className="col"
            style={{
              width: "29%",
              minWidth: 280,
              borderRight: "1px solid var(--line)",
              background: "var(--bg-1)",
              overflow: "hidden",
            }}
          >
            {/* Input Header */}
            <div
              className="row spread"
              style={{
                padding: "8px 12px",
                borderBottom: "1px solid var(--line)",
                background: "var(--bg-2)",
                alignItems: "center",
              }}
            >
              <div className="row gap2" style={{ alignItems: "center" }}>
                <span className="t-micro" style={{ letterSpacing: "0.5px" }}>INPUT DATA</span>
                {upstreamNodes.length > 1 && (
                  <select
                    className="select mono"
                    style={{ height: 22, fontSize: 10.5, padding: "0 6px" }}
                    value={selectedUpstreamId}
                    onChange={(e) => setSelectedUpstreamId(e.target.value)}
                  >
                    <option value="__combined__">Combined Branches ({upstreamNodes.length})</option>
                    {upstreamNodes.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.data.config?.name || u.id}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="row gap1">
                <button
                  type="button"
                  className={`chip ${inputTab === "tree" ? "chip-active" : ""}`}
                  style={{ height: 20, fontSize: 10, cursor: "pointer" }}
                  onClick={() => setInputTab("tree")}
                >
                  Tree
                </button>
                <button
                  type="button"
                  className={`chip ${inputTab === "json" ? "chip-active" : ""}`}
                  style={{ height: 20, fontSize: 10, cursor: "pointer" }}
                  onClick={() => setInputTab("json")}
                >
                  JSON
                </button>
                <button
                  type="button"
                  className={`chip ${inputTab === "table" ? "chip-active" : ""}`}
                  style={{ height: 20, fontSize: 10, cursor: "pointer" }}
                  onClick={() => setInputTab("table")}
                >
                  Table
                </button>
              </div>
            </div>

            {/* Property search filter */}
            <div style={{ padding: "6px 10px", borderBottom: "1px solid var(--line)", background: "var(--bg-1)" }}>
              <div className="row gap1" style={{ alignItems: "center", background: "var(--bg-2)", borderRadius: 3, padding: "2px 6px" }}>
                <Icon name="search" size={12} style={{ color: "var(--fg-2)" }} />
                <input
                  className="input mono"
                  style={{ border: "none", background: "transparent", height: 22, fontSize: 11, padding: 0 }}
                  placeholder="Filter input properties…"
                  value={inputSearch}
                  onChange={(e) => setInputSearch(e.target.value)}
                />
                {inputSearch && (
                  <button type="button" className="iconbtn" style={{ width: 14, height: 14 }} onClick={() => setInputSearch("")}>
                    <Icon name="x" size={10} />
                  </button>
                )}
              </div>
            </div>

            {/* Input Data View */}
            <div className="scroll-y" style={{ flex: 1, padding: "8px 10px" }}>
              {inputTab === "tree" && (
                <MessageTreeViewer
                  data={inputMessage}
                  search={inputSearch}
                  onCopyExpr={copyExpr}
                  copiedKey={copiedKey}
                />
              )}
              {inputTab === "json" && (
                <div style={{ position: "relative" }}>
                  <button
                    type="button"
                    className="iconbtn"
                    style={{ position: "absolute", right: 6, top: 6, zIndex: 10 }}
                    onClick={() => copyExpr(JSON.stringify(inputMessage, null, 2))}
                    title="Copy full JSON"
                  >
                    <Icon name="copy" size={13} />
                  </button>
                  <pre className="mono-sm" style={{ padding: 8, margin: 0, background: "var(--bg-2)", borderRadius: 4, overflow: "auto", fontSize: 11 }}>
                    {JSON.stringify(inputMessage, null, 2)}
                  </pre>
                </div>
              )}
              {inputTab === "table" && (
                <MessageTableViewer data={inputMessage?.payload ?? inputMessage} />
              )}
            </div>

            <div style={{ padding: "6px 10px", borderTop: "1px solid var(--line)", background: "var(--bg-2)", fontSize: 10.5 }} className="fg-2">
              💡 Drag properties into parameters or click copy to map expressions.
            </div>
          </div>

          {/* PANEL 2: PARAMETERS (Node Configuration) */}
          <div
            className="col"
            style={{
              flex: 1,
              minWidth: 360,
              background: "var(--bg-card)",
              overflow: "hidden",
              borderRight: "1px solid var(--line)",
            }}
          >
            <div
              className="row spread"
              style={{
                padding: "8px 14px",
                borderBottom: "1px solid var(--line)",
                background: "var(--bg-2)",
                alignItems: "center",
              }}
            >
              <span className="t-micro" style={{ letterSpacing: "0.5px" }}>PARAMETERS</span>
              <span className="mono-sm fg-2">Node Settings</span>
            </div>

            <div className="scroll-y" style={{ flex: 1, padding: 18 }}>
              {renderParameters()}
            </div>
          </div>

          {/* PANEL 3: OUTPUT DATA */}
          <div
            className="col"
            style={{
              width: "31%",
              minWidth: 290,
              background: "var(--bg-1)",
              overflow: "hidden",
            }}
          >
            {/* Output Header */}
            <div
              className="row spread"
              style={{
                padding: "8px 12px",
                borderBottom: "1px solid var(--line)",
                background: "var(--bg-2)",
                alignItems: "center",
              }}
            >
              <div className="row gap2" style={{ alignItems: "center" }}>
                <span className="t-micro" style={{ letterSpacing: "0.5px" }}>OUTPUT DATA</span>
                {stepResult?.duration_ms !== undefined && (
                  <span className="mono-sm fg-2" style={{ fontSize: 10 }}>
                    ⚡ {stepResult.duration_ms}ms
                  </span>
                )}
                <StatusPill status={stepResult ? (stepResult.error ? "error" : "done") : outputMessage ? "done" : "idle"} />
                {stepResult?.mocked && (
                  <span className="chip" style={{ height: 18, fontSize: 9.5, background: "rgba(59, 130, 246, 0.15)", color: "var(--accent)" }}>
                    Simulated Dry Run
                  </span>
                )}
                {stepResult?.requires_approval && (
                  <span className="chip" style={{ height: 18, fontSize: 9.5, background: "rgba(245, 158, 11, 0.15)", color: "var(--warn)" }}>
                    Approval Required
                  </span>
                )}
                {stepResult?.unsupported_dry_run && (
                  <span className="chip" style={{ height: 18, fontSize: 9.5, background: "rgba(239, 68, 68, 0.15)", color: "var(--err)" }}>
                    Fail-Closed (Unknown Classification)
                  </span>
                )}
              </div>
              <div className="row gap1">
                <button
                  type="button"
                  className={`chip ${outputTab === "tree" ? "chip-active" : ""}`}
                  style={{ height: 20, fontSize: 10, cursor: "pointer" }}
                  onClick={() => setOutputTab("tree")}
                >
                  Tree
                </button>
                <button
                  type="button"
                  className={`chip ${outputTab === "json" ? "chip-active" : ""}`}
                  style={{ height: 20, fontSize: 10, cursor: "pointer" }}
                  onClick={() => setOutputTab("json")}
                >
                  JSON
                </button>
                <button
                  type="button"
                  className={`chip ${outputTab === "table" ? "chip-active" : ""}`}
                  style={{ height: 20, fontSize: 10, cursor: "pointer" }}
                  onClick={() => setOutputTab("table")}
                >
                  Table
                </button>
              </div>
            </div>

            {/* Error display if failed */}
            {stepResult?.error && (
              <div
                style={{
                  padding: "8px 12px",
                  background: "rgba(239, 68, 68, 0.12)",
                  borderBottom: "1px solid var(--err)",
                  color: "var(--err)",
                  fontSize: 11,
                  display: "flex",
                  gap: 6,
                  alignItems: "flex-start",
                }}
              >
                <Icon name="x" size={14} style={{ flexShrink: 0, marginTop: 2 }} />
                <span>{stepResult.error}</span>
              </div>
            )}

            {/* Output Data Content */}
            <div className="scroll-y" style={{ flex: 1, padding: "8px 10px" }}>
              {outputMessage ? (
                <>
                  {outputTab === "tree" && (
                    <MessageTreeViewer
                      data={outputMessage}
                      search=""
                      onCopyExpr={copyExpr}
                      copiedKey={copiedKey}
                    />
                  )}
                  {outputTab === "json" && (
                    <div style={{ position: "relative" }}>
                      <button
                        type="button"
                        className="iconbtn"
                        style={{ position: "absolute", right: 6, top: 6, zIndex: 10 }}
                        onClick={() => copyExpr(JSON.stringify(outputMessage, null, 2))}
                        title="Copy full JSON"
                      >
                        <Icon name="copy" size={13} />
                      </button>
                      <pre className="mono-sm" style={{ padding: 8, margin: 0, background: "var(--bg-2)", borderRadius: 4, overflow: "auto", fontSize: 11 }}>
                        {JSON.stringify(outputMessage, null, 2)}
                      </pre>
                    </div>
                  )}
                  {outputTab === "table" && (
                    <MessageTableViewer data={outputMessage?.payload ?? outputMessage} />
                  )}
                </>
              ) : (
                <div className="col gap2 center" style={{ height: "100%", padding: 30, textAlign: "center", color: "var(--fg-2)" }}>
                  <Icon name="play" size={24} style={{ opacity: 0.5 }} />
                  <span className="t-body-sm">No execution data yet.</span>
                  <span className="t-caption">
                    Click <strong>Test Step</strong> above to execute this individual node with current inputs.
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Tree view component with drag-and-drop property handles
function MessageTreeViewer({
  data,
  search,
  prefix = "msg",
  onCopyExpr,
  copiedKey,
}: {
  data: any;
  search: string;
  prefix?: string;
  onCopyExpr: (expr: string) => void;
  copiedKey: string | null;
}) {
  if (data === null || data === undefined) {
    return <div className="mono-sm fg-2">null</div>;
  }

  const isObject = typeof data === "object" && !Array.isArray(data);
  const isArray = Array.isArray(data);

  if (!isObject && !isArray) {
    return <div className="mono-sm">{String(data)}</div>;
  }

  const entries = isArray
    ? data.map((v, i) => [`[${i}]`, v] as [string, any])
    : Object.entries(data);

  const needle = search.trim().toLowerCase();

  return (
    <div className="col gap1">
      {entries.map(([key, val]) => {
        const fullPath = prefix === "msg" && key === "payload" ? "msg.payload" : `${prefix}.${key}`;
        const expr = `{{${fullPath}}}`;
        const valType = Array.isArray(val) ? "array" : typeof val;
        const matches = !needle || key.toLowerCase().includes(needle) || String(val).toLowerCase().includes(needle);

        if (!matches) return null;

        const isNested = val !== null && typeof val === "object";

        return (
          <div
            key={key}
            className="col"
            style={{
              padding: "3px 6px",
              borderRadius: 3,
              border: "1px solid transparent",
              background: "var(--bg-2)",
              marginBottom: 2,
            }}
          >
            <div
              className="row spread"
              draggable={!isNested}
              onDragStart={(e) => {
                e.dataTransfer.setData("text/plain", expr);
              }}
              style={{
                alignItems: "center",
                cursor: !isNested ? "grab" : "default",
              }}
              title={!isNested ? `Drag into parameter field or click to copy ${expr}` : undefined}
            >
              <div className="row gap1" style={{ alignItems: "center", minWidth: 0 }}>
                <span className="mono-sm" style={{ fontWeight: 600, color: "var(--fg-1)" }}>
                  {key}
                </span>
                <span
                  style={{
                    fontSize: 9,
                    padding: "1px 4px",
                    borderRadius: 2,
                    background: "var(--bg-3)",
                    color: "var(--fg-2)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {valType}
                </span>
              </div>

              <div className="row gap1" style={{ alignItems: "center" }}>
                {!isNested && (
                  <span className="mono-sm fg-2 truncate" style={{ maxWidth: 110, fontSize: 10.5 }}>
                    {typeof val === "string" ? `"${val}"` : String(val)}
                  </span>
                )}
                <button
                  type="button"
                  className="iconbtn"
                  style={{ width: 18, height: 18 }}
                  onClick={() => onCopyExpr(expr)}
                  title={`Copy ${expr}`}
                >
                  <Icon name={copiedKey === expr ? "check" : "copy"} size={11} />
                </button>
              </div>
            </div>

            {isNested && (
              <div style={{ paddingLeft: 12, borderLeft: "1px solid var(--line)", marginTop: 3 }}>
                <MessageTreeViewer
                  data={val}
                  search={search}
                  prefix={fullPath}
                  onCopyExpr={onCopyExpr}
                  copiedKey={copiedKey}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// Table view component
function MessageTableViewer({ data }: { data: any }) {
  if (!data) return <div className="mono-sm fg-2">No table data</div>;

  if (Array.isArray(data) && data.length > 0 && typeof data[0] === "object") {
    const headers = Array.from(new Set(data.flatMap((d) => Object.keys(d || {}))));
    return (
      <div style={{ overflowX: "auto" }}>
        <table className="table mono-sm" style={{ width: "100%", fontSize: 11 }}>
          <thead>
            <tr>
              {headers.map((h) => (
                <th key={h} style={{ padding: "4px 8px" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.slice(0, 50).map((row, i) => (
              <tr key={i}>
                {headers.map((h) => (
                  <td key={h} style={{ padding: "4px 8px" }}>
                    {typeof row[h] === "object" ? JSON.stringify(row[h]) : String(row[h] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (typeof data === "object") {
    return (
      <table className="table mono-sm" style={{ width: "100%", fontSize: 11 }}>
        <thead>
          <tr>
            <th style={{ padding: "4px 8px" }}>Key</th>
            <th style={{ padding: "4px 8px" }}>Value</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).map(([k, v]) => (
            <tr key={k}>
              <td style={{ padding: "4px 8px", fontWeight: 600 }}>{k}</td>
              <td style={{ padding: "4px 8px" }}>
                {typeof v === "object" ? JSON.stringify(v) : String(v ?? "")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  return <div className="mono-sm">{String(data)}</div>;
}
