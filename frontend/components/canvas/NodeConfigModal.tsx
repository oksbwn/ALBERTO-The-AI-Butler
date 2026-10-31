"use client";
/* Alberto Automate 2.0: n8n-inspired 3-panel node configuration modal.
   Columns:
   [ INPUT DATA ] (Previous node messages, collapsible tree, drag-and-drop properties)
   [ PARAMETERS ] (Node configuration form, accepts dropped variables)
   [ OUTPUT DATA ] (Execution result, collapsible tree, status, duration, Test Step action)
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
  const [inputTab, setInputTab] = useState<"tree" | "json" | "table">("tree");
  const [outputTab, setOutputTab] = useState<"tree" | "json" | "table">("tree");
  const [inputSearch, setInputSearch] = useState("");
  const [outputSearch, setOutputSearch] = useState("");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Panel collapse states
  const [isInputCollapsed, setIsInputCollapsed] = useState(false);
  const [isOutputCollapsed, setIsOutputCollapsed] = useState(false);

  // Expand / collapse all signals
  const [inputExpandSignal, setInputExpandSignal] = useState(0);
  const [inputCollapseSignal, setInputCollapseSignal] = useState(0);
  const [outputExpandSignal, setOutputExpandSignal] = useState(0);
  const [outputCollapseSignal, setOutputCollapseSignal] = useState(0);

  // Single step execution via backend /step endpoint
  const executeStep = useCallback(async () => {
    if (!project?.id || !workflowId || stepExecuting) return;
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
      // Auto expand output panel if collapsed when running test
      if (isOutputCollapsed) setIsOutputCollapsed(false);
    } catch (err: any) {
      setStepResult({ ok: false, error: err?.message || "Execution failed" } as any);
      if (isOutputCollapsed) setIsOutputCollapsed(false);
    } finally {
      setStepExecuting(false);
    }
  }, [project?.id, workflowId, node, inputMessage, testMode, stepExecuting, isOutputCollapsed]);

  // Keyboard navigation: Escape to close, Ctrl+Enter to test step
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        executeStep();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose, executeStep]);

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
        background: "rgba(5, 7, 13, 0.78)",
        backdropFilter: "blur(6px)",
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
          borderRadius: 8,
          boxShadow: "0 28px 72px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.06)",
          overflow: "hidden",
          position: "relative",
        }}
      >
        {/* Subtle accent line on modal top */}
        <div style={{ height: 2, background: meta.color, width: "100%" }} />

        {/* Modal Top Bar */}
        <div
          className="row spread"
          style={{
            padding: "10px 18px",
            borderBottom: "1px solid var(--line)",
            background: "var(--bg-2)",
            flex: "none",
            alignItems: "center",
            gap: 12,
          }}
        >
          <div className="row gap3" style={{ alignItems: "center", minWidth: 0 }}>
            <Tile icon={meta.icon} color={meta.color} size={32} />
            <div className="col" style={{ minWidth: 0 }}>
              <div className="row gap2" style={{ alignItems: "center" }}>
                <span className="t-h3 truncate" style={{ maxWidth: 360, fontWeight: 700 }}>
                  {config.name || meta.label || node.id}
                </span>
                <span className="typechip" style={{ borderColor: meta.color, color: "var(--fg-0)" }}>
                  {type}
                </span>
                <span className="mono-sm fg-2">#{node.id}</span>
                {upstreamNodes.length > 0 && (
                  <span
                    className="chip mono"
                    style={{
                      height: 19,
                      fontSize: 10,
                      background: "var(--bg-3)",
                      color: "var(--fg-2)",
                      borderColor: "var(--line)",
                    }}
                    title={`Connected to ${upstreamNodes.map((u) => u.data.config?.name || u.id).join(", ")}`}
                  >
                    ← {upstreamNodes[0]?.data.config?.name || upstreamNodes[0]?.id}
                    {upstreamNodes.length > 1 ? ` +${upstreamNodes.length - 1}` : ""}
                  </span>
                )}
              </div>
              <span className="t-caption fg-2">
                Configure node parameters, map upstream variables, and test node output
              </span>
            </div>
          </div>

          <div className="row gap2" style={{ alignItems: "center", flexShrink: 0 }}>
            {/* Safe / Live Mode Switcher */}
            <div
              className="row gap1"
              style={{
                alignItems: "center",
                background: "var(--bg-3)",
                borderRadius: 4,
                padding: "2px 4px",
                border: "1px solid var(--line)",
              }}
            >
              <button
                type="button"
                className={`chip ${testMode === "dry_run" ? "chip-active" : ""}`}
                style={{
                  height: 22,
                  fontSize: 10.5,
                  cursor: "pointer",
                  fontWeight: testMode === "dry_run" ? 600 : 400,
                }}
                onClick={() => setTestMode("dry_run")}
                title="Safe test: simulated execution without mutating external resources"
              >
                Safe (Dry Run)
              </button>
              <button
                type="button"
                className={`chip ${testMode === "live" ? "chip-active" : ""}`}
                style={{
                  height: 22,
                  fontSize: 10.5,
                  cursor: "pointer",
                  color: testMode === "live" ? "var(--warn)" : undefined,
                  fontWeight: testMode === "live" ? 600 : 400,
                }}
                onClick={() => setTestMode("live")}
                title="Live test: real execution subject to authorization and approval policies"
              >
                Live
              </button>
            </div>

            {/* Test Step Action */}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={executeStep}
              disabled={stepExecuting}
              title={`Test run this node in ${testMode} mode (Ctrl+Enter)`}
              style={{
                gap: 6,
                fontWeight: 600,
                borderColor: "var(--accent)",
                color: "var(--accent)",
              }}
            >
              <Icon
                name={stepExecuting ? "refresh" : "play"}
                size={14}
                style={stepExecuting ? { animation: "spin 1s linear infinite" } : { color: "var(--accent)" }}
              />
              {stepExecuting ? "Testing…" : "Test Step"}
              <span style={{ fontSize: 9.5, opacity: 0.65, fontFamily: "var(--font-mono)" }}>Ctrl+↵</span>
            </button>

            {onPinData && (
              <button
                type="button"
                className={`btn btn-sm ${pinnedData[node.id] ? "btn-primary" : "btn-ghost"}`}
                onClick={() => onPinData(node.id, pinnedData[node.id] ? null : inputMessage)}
                title={pinnedData[node.id] ? "Unpin test data" : "Pin current input as persistent test state"}
                style={{ gap: 5 }}
              >
                <Icon name="check" size={13} />
                {pinnedData[node.id] ? "Pinned Data" : "Pin Data"}
              </button>
            )}

            <button
              type="button"
              className="iconbtn"
              onClick={() => onDeleteNode(node.id)}
              title="Delete node"
              style={{ color: "var(--err)", marginLeft: 4 }}
            >
              <Icon name="trash" size={15} />
            </button>

            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={onClose}
              style={{ minWidth: 70, gap: 4 }}
              title="Close modal (Esc)"
            >
              Done
              <span style={{ fontSize: 9.5, opacity: 0.75, fontFamily: "var(--font-mono)" }}>Esc</span>
            </button>
          </div>
        </div>

        {/* 3-Panel Main Layout */}
        <div className="row" style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
          {/* PANEL 1: INPUT DATA */}
          {isInputCollapsed ? (
            <div
              className="col"
              style={{
                width: 38,
                borderRight: "1px solid var(--line)",
                background: "var(--bg-2)",
                alignItems: "center",
                padding: "10px 4px",
                cursor: "pointer",
                userSelect: "none",
                transition: "width 0.15s ease",
              }}
              onClick={() => setIsInputCollapsed(false)}
              title="Expand Input Data panel"
            >
              <button
                type="button"
                className="iconbtn"
                style={{ width: 24, height: 24, marginBottom: 12 }}
                onClick={(e) => {
                  e.stopPropagation();
                  setIsInputCollapsed(false);
                }}
                title="Expand Input Data panel"
              >
                <Icon name="chevron" size={13} style={{ transform: "rotate(-90deg)" }} />
              </button>
              <div
                style={{
                  writingMode: "vertical-rl",
                  transform: "rotate(180deg)",
                  fontSize: 10,
                  letterSpacing: "1px",
                  fontWeight: 600,
                  color: "var(--fg-2)",
                  textTransform: "uppercase",
                  marginTop: 6,
                }}
              >
                INPUT DATA
              </div>
            </div>
          ) : (
            <div
              className="col"
              style={{
                width: "29%",
                minWidth: 280,
                maxWidth: 420,
                borderRight: "1px solid var(--line)",
                background: "var(--bg-1)",
                overflow: "hidden",
                transition: "width 0.15s ease",
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
                  gap: 8,
                }}
              >
                <div className="row gap2" style={{ alignItems: "center", minWidth: 0 }}>
                  <button
                    type="button"
                    className="iconbtn"
                    style={{ width: 20, height: 20 }}
                    onClick={() => setIsInputCollapsed(true)}
                    title="Collapse Input Data panel"
                  >
                    <Icon name="chevron" size={12} style={{ transform: "rotate(90deg)" }} />
                  </button>
                  <span className="t-micro" style={{ letterSpacing: "0.5px", fontWeight: 700 }}>INPUT DATA</span>
                  {upstreamNodes.length > 1 && (
                    <select
                      className="select mono"
                      style={{ height: 22, fontSize: 10.5, padding: "0 6px", maxWidth: 120 }}
                      value={selectedUpstreamId}
                      onChange={(e) => setSelectedUpstreamId(e.target.value)}
                    >
                      <option value="__combined__">Combined ({upstreamNodes.length})</option>
                      {upstreamNodes.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.data.config?.name || u.id}
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                <div className="row gap1" style={{ alignItems: "center" }}>
                  {inputTab === "tree" && (
                    <div className="row gap1" style={{ marginRight: 4 }}>
                      <button
                        type="button"
                        className="iconbtn"
                        style={{ width: 20, height: 20, fontSize: 10 }}
                        onClick={() => setInputExpandSignal((s) => s + 1)}
                        title="Expand all tree nodes"
                      >
                        +
                      </button>
                      <button
                        type="button"
                        className="iconbtn"
                        style={{ width: 20, height: 20, fontSize: 10 }}
                        onClick={() => setInputCollapseSignal((s) => s + 1)}
                        title="Collapse all tree nodes"
                      >
                        −
                      </button>
                    </div>
                  )}
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
                <div className="row gap1" style={{ alignItems: "center", background: "var(--bg-2)", borderRadius: 4, padding: "3px 8px", border: "1px solid var(--line)" }}>
                  <Icon name="search" size={12} style={{ color: "var(--fg-2)" }} />
                  <input
                    className="input mono"
                    style={{ border: "none", background: "transparent", height: 20, fontSize: 11, padding: 0, flex: 1 }}
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
                    expandAllSignal={inputExpandSignal}
                    collapseAllSignal={inputCollapseSignal}
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
                    <pre className="mono-sm" style={{ padding: 10, margin: 0, background: "var(--bg-2)", borderRadius: 4, overflow: "auto", fontSize: 11 }}>
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
          )}

          {/* PANEL 2: PARAMETERS (Node Configuration) */}
          <div
            className="col"
            style={{
              flex: 1,
              minWidth: 360,
              background: "var(--bg-card)",
              overflow: "hidden",
              borderRight: isOutputCollapsed ? "none" : "1px solid var(--line)",
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
              <div className="row gap2" style={{ alignItems: "center" }}>
                <span className="t-micro" style={{ letterSpacing: "0.5px", fontWeight: 700 }}>PARAMETERS</span>
                <span className="mono-sm fg-2">• {type} node configuration</span>
              </div>
              <div className="row gap2" style={{ alignItems: "center" }}>
                {isInputCollapsed && (
                  <button
                    type="button"
                    className="chip mono"
                    style={{ height: 20, fontSize: 10, cursor: "pointer" }}
                    onClick={() => setIsInputCollapsed(false)}
                  >
                    ◀ Show Input Data
                  </button>
                )}
                {isOutputCollapsed && (
                  <button
                    type="button"
                    className="chip mono"
                    style={{ height: 20, fontSize: 10, cursor: "pointer" }}
                    onClick={() => setIsOutputCollapsed(false)}
                  >
                    Show Output Data ▶
                  </button>
                )}
              </div>
            </div>

            <div className="scroll-y" style={{ flex: 1, padding: 18 }}>
              {renderParameters()}
            </div>
          </div>

          {/* PANEL 3: OUTPUT DATA */}
          {isOutputCollapsed ? (
            <div
              className="col"
              style={{
                width: 38,
                borderLeft: "1px solid var(--line)",
                background: "var(--bg-2)",
                alignItems: "center",
                padding: "10px 4px",
                cursor: "pointer",
                userSelect: "none",
                transition: "width 0.15s ease",
              }}
              onClick={() => setIsOutputCollapsed(false)}
              title="Expand Output Data panel"
            >
              <button
                type="button"
                className="iconbtn"
                style={{ width: 24, height: 24, marginBottom: 12 }}
                onClick={(e) => {
                  e.stopPropagation();
                  setIsOutputCollapsed(false);
                }}
                title="Expand Output Data panel"
              >
                <Icon name="chevron" size={13} style={{ transform: "rotate(90deg)" }} />
              </button>
              <div
                style={{
                  writingMode: "vertical-rl",
                  transform: "rotate(180deg)",
                  fontSize: 10,
                  letterSpacing: "1px",
                  fontWeight: 600,
                  color: "var(--fg-2)",
                  textTransform: "uppercase",
                  marginTop: 6,
                }}
              >
                OUTPUT DATA
              </div>
              {outputMessage && (
                <div
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: stepResult?.error ? "var(--err)" : "var(--ok)",
                    marginTop: 12,
                  }}
                  title={stepResult?.error ? "Error occurred" : "Output Available"}
                />
              )}
            </div>
          ) : (
            <div
              className="col"
              style={{
                width: "31%",
                minWidth: 290,
                maxWidth: 460,
                background: "var(--bg-1)",
                overflow: "hidden",
                transition: "width 0.15s ease",
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
                  gap: 8,
                }}
              >
                <div className="row gap2" style={{ alignItems: "center", minWidth: 0 }}>
                  <button
                    type="button"
                    className="iconbtn"
                    style={{ width: 20, height: 20 }}
                    onClick={() => setIsOutputCollapsed(true)}
                    title="Collapse Output Data panel"
                  >
                    <Icon name="chevron" size={12} style={{ transform: "rotate(-90deg)" }} />
                  </button>
                  <span className="t-micro" style={{ letterSpacing: "0.5px", fontWeight: 700 }}>OUTPUT DATA</span>
                  {stepResult?.duration_ms !== undefined && (
                    <span className="mono-sm fg-2" style={{ fontSize: 10 }}>
                      ⚡ {stepResult.duration_ms}ms
                    </span>
                  )}
                  <StatusPill status={stepResult ? (stepResult.error ? "error" : "done") : outputMessage ? "done" : "idle"} />
                </div>

                <div className="row gap1" style={{ alignItems: "center" }}>
                  {outputTab === "tree" && (
                    <div className="row gap1" style={{ marginRight: 4 }}>
                      <button
                        type="button"
                        className="iconbtn"
                        style={{ width: 20, height: 20, fontSize: 10 }}
                        onClick={() => setOutputExpandSignal((s) => s + 1)}
                        title="Expand all tree nodes"
                      >
                        +
                      </button>
                      <button
                        type="button"
                        className="iconbtn"
                        style={{ width: 20, height: 20, fontSize: 10 }}
                        onClick={() => setOutputCollapseSignal((s) => s + 1)}
                        title="Collapse all tree nodes"
                      >
                        −
                      </button>
                    </div>
                  )}
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

              {/* Status & badges if special mode */}
              {(stepResult?.mocked || stepResult?.requires_approval || stepResult?.unsupported_dry_run) && (
                <div style={{ padding: "4px 10px", background: "var(--bg-3)", borderBottom: "1px solid var(--line)", display: "flex", gap: 6, flexWrap: "wrap" }}>
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
                      Fail-Closed (Unknown Risk)
                    </span>
                  )}
                </div>
              )}

              {/* Property search filter for output */}
              <div style={{ padding: "6px 10px", borderBottom: "1px solid var(--line)", background: "var(--bg-1)" }}>
                <div className="row gap1" style={{ alignItems: "center", background: "var(--bg-2)", borderRadius: 4, padding: "3px 8px", border: "1px solid var(--line)" }}>
                  <Icon name="search" size={12} style={{ color: "var(--fg-2)" }} />
                  <input
                    className="input mono"
                    style={{ border: "none", background: "transparent", height: 20, fontSize: 11, padding: 0, flex: 1 }}
                    placeholder="Filter output properties…"
                    value={outputSearch}
                    onChange={(e) => setOutputSearch(e.target.value)}
                  />
                  {outputSearch && (
                    <button type="button" className="iconbtn" style={{ width: 14, height: 14 }} onClick={() => setOutputSearch("")}>
                      <Icon name="x" size={10} />
                    </button>
                  )}
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
                        search={outputSearch}
                        onCopyExpr={copyExpr}
                        copiedKey={copiedKey}
                        expandAllSignal={outputExpandSignal}
                        collapseAllSignal={outputCollapseSignal}
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
                        <pre className="mono-sm" style={{ padding: 10, margin: 0, background: "var(--bg-2)", borderRadius: 4, overflow: "auto", fontSize: 11 }}>
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
                    <span className="t-body-sm" style={{ fontWeight: 600 }}>No execution data yet.</span>
                    <span className="t-caption">
                      Click <strong>Test Step</strong> above to execute this individual node with current inputs.
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Tree view component with expandable/collapsible nodes & drag-and-drop property handles
function MessageTreeViewer({
  data,
  search = "",
  prefix = "msg",
  onCopyExpr,
  copiedKey,
  expandAllSignal,
  collapseAllSignal,
}: {
  data: any;
  search: string;
  prefix?: string;
  onCopyExpr: (expr: string) => void;
  copiedKey: string | null;
  expandAllSignal?: number;
  collapseAllSignal?: number;
}) {
  // Global set of expanded path keys for this tree
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    // Pre-expand depth 0 and 1
    if (data && typeof data === "object") {
      Object.keys(data).forEach((k) => {
        initial.add(`${prefix}.${k}`);
        if (data[k] && typeof data[k] === "object") {
          Object.keys(data[k]).forEach((subK) => {
            initial.add(`${prefix}.${k}.${subK}`);
          });
        }
      });
    }
    return initial;
  });

  // Expand all signal
  useEffect(() => {
    if (!expandAllSignal) return;
    const all = new Set<string>();
    function collect(obj: any, curr: string) {
      if (obj && typeof obj === "object") {
        all.add(curr);
        Object.entries(obj).forEach(([k, v]) => {
          collect(v, `${curr}.${k}`);
        });
      }
    }
    collect(data, prefix);
    setExpandedPaths(all);
  }, [expandAllSignal, data, prefix]);

  // Collapse all signal
  useEffect(() => {
    if (!collapseAllSignal) return;
    setExpandedPaths(new Set());
  }, [collapseAllSignal]);

  const togglePath = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  return (
    <TreeBranch
      data={data}
      search={search}
      prefix={prefix}
      onCopyExpr={onCopyExpr}
      copiedKey={copiedKey}
      expandedPaths={expandedPaths}
      onTogglePath={togglePath}
      depth={0}
    />
  );
}

function TreeBranch({
  data,
  search,
  prefix,
  onCopyExpr,
  copiedKey,
  expandedPaths,
  onTogglePath,
  depth = 0,
}: {
  data: any;
  search: string;
  prefix: string;
  onCopyExpr: (expr: string) => void;
  copiedKey: string | null;
  expandedPaths: Set<string>;
  onTogglePath: (path: string) => void;
  depth: number;
}) {
  if (data === null || data === undefined) {
    return <div className="mono-sm fg-2" style={{ paddingLeft: depth * 14 }}>null</div>;
  }

  const isObject = typeof data === "object" && !Array.isArray(data);
  const isArray = Array.isArray(data);

  if (!isObject && !isArray) {
    return <div className="mono-sm" style={{ paddingLeft: depth * 14 }}>{String(data)}</div>;
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
        const isNested = val !== null && typeof val === "object";
        const valType = Array.isArray(val) ? "array" : typeof val;
        const itemCount = isNested ? (Array.isArray(val) ? val.length : Object.keys(val).length) : 0;

        // Auto-expand if search matches inside
        const matchesSelf = !needle || key.toLowerCase().includes(needle) || (!isNested && String(val).toLowerCase().includes(needle));
        const hasMatchingChild = needle && isNested && JSON.stringify(val).toLowerCase().includes(needle);
        if (!matchesSelf && !hasMatchingChild) return null;

        const isExpanded = (needle && hasMatchingChild) || expandedPaths.has(fullPath);

        return (
          <div
            key={key}
            className="col"
            style={{
              borderRadius: 4,
              border: "1px solid var(--line-subtle, rgba(255,255,255,0.06))",
              background: "var(--bg-2)",
              marginBottom: 3,
              overflow: "hidden",
            }}
          >
            <div
              className="row spread"
              draggable={!isNested}
              onDragStart={(e) => {
                e.dataTransfer.setData("text/plain", expr);
              }}
              onClick={() => {
                if (isNested) onTogglePath(fullPath);
              }}
              style={{
                alignItems: "center",
                cursor: isNested ? "pointer" : "grab",
                padding: "4px 8px",
                background: isExpanded ? "var(--bg-3)" : "transparent",
                transition: "background 0.15s ease",
              }}
              title={
                isNested
                  ? `${isExpanded ? "Collapse" : "Expand"} ${key}`
                  : `Drag into parameter field or click to copy ${expr}`
              }
            >
              <div className="row gap1" style={{ alignItems: "center", minWidth: 0 }}>
                {isNested ? (
                  <button
                    type="button"
                    className="iconbtn"
                    onClick={(e) => {
                      e.stopPropagation();
                      onTogglePath(fullPath);
                    }}
                    style={{
                      width: 16,
                      height: 16,
                      padding: 0,
                      transform: isExpanded ? "rotate(0deg)" : "rotate(-90deg)",
                      transition: "transform 0.15s ease",
                    }}
                  >
                    <Icon name="chevron" size={11} />
                  </button>
                ) : (
                  <span style={{ width: 16, textAlign: "center", opacity: 0.35, fontSize: 10 }}>•</span>
                )}

                <span className="mono-sm" style={{ fontWeight: 600, color: "var(--fg-1)" }}>
                  {key}
                </span>

                <span
                  style={{
                    fontSize: 9.5,
                    padding: "1px 5px",
                    borderRadius: 3,
                    background: "var(--bg-1)",
                    color: "var(--fg-2)",
                    fontFamily: "var(--font-mono)",
                    border: "1px solid var(--line)",
                  }}
                >
                  {valType}
                </span>

                {isNested && (
                  <span
                    className="mono-sm fg-2"
                    style={{ fontSize: 10, opacity: 0.7 }}
                  >
                    {Array.isArray(val) ? `[${itemCount}]` : `{${itemCount}}`}
                  </span>
                )}
              </div>

              <div className="row gap1" style={{ alignItems: "center" }}>
                {!isNested && (
                  <span
                    className="mono-sm fg-2 truncate"
                    style={{
                      maxWidth: 140,
                      fontSize: 10.5,
                      color:
                        typeof val === "string"
                          ? "#34d399"
                          : typeof val === "number"
                          ? "#60a5fa"
                          : typeof val === "boolean"
                          ? "#a78bfa"
                          : undefined,
                    }}
                  >
                    {typeof val === "string" ? `"${val}"` : String(val)}
                  </span>
                )}

                <button
                  type="button"
                  className="iconbtn"
                  style={{ width: 20, height: 20 }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onCopyExpr(expr);
                  }}
                  title={`Copy ${expr}`}
                >
                  <Icon name={copiedKey === expr ? "check" : "copy"} size={11} style={copiedKey === expr ? { color: "var(--ok)" } : undefined} />
                </button>
              </div>
            </div>

            {isNested && isExpanded && (
              <div style={{ paddingLeft: 14, borderLeft: "2px solid var(--line)", marginLeft: 8, marginTop: 4, marginBottom: 4 }}>
                <TreeBranch
                  data={val}
                  search={search}
                  prefix={fullPath}
                  onCopyExpr={onCopyExpr}
                  copiedKey={copiedKey}
                  expandedPaths={expandedPaths}
                  onTogglePath={onTogglePath}
                  depth={depth + 1}
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
