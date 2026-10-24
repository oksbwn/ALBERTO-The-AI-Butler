"use client";
/* Unified Workflow Execution & Structured Result Viewer.
   Replaces redundant workflow chat with a professional orchestration workbench:
   - Manual Trigger with input parameter validation (Message or JSON payload)
   - Real-time execution status (queued, running, waiting for approval, completed, failed, cancelled)
   - Synchronized node-by-node canvas highlights
   - Subagent invocation & tool activity tracking
   - Formatted, expandable output viewer with sensitive secret redaction
   - Interactive Human-In-The-Loop (HITL) approval actions
*/
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../icons";
import { StatusPill, Tile } from "../primitives";
import { api, openSSE, type Workflow, type ComponentT } from "@/lib/api";
import { fmtUSD } from "@/lib/data";
import { ComponentRenderer } from "../component-renderer";
import { Markdown } from "../markdown";
import { ReplyAccumulator, type Part, type ComponentInstance } from "@/lib/chat-parts";

export interface NodeStepRecord {
  id: string;
  name: string;
  type?: string;
  status: "running" | "done" | "error";
  output?: any;
  error?: string;
  timestamp: number;
}

export interface ActivityRecord {
  id: string;
  kind: "tool" | "subagent" | string;
  name: string;
  phase: "start" | "end";
  input?: any;
  output?: any;
  error?: boolean;
  timestamp: number;
}

export interface LogEntry {
  id: string;
  time: string;
  event: string;
  summary: string;
}

export function redactSensitive(val: any): any {
  if (val === null || val === undefined) return val;
  if (typeof val === "string") {
    return val.replace(/(password|token|secret|api[_\-]?key|bearer)\s*[:=]\s*['"]?[^\s'"]+/gi, "$1=••••••••");
  }
  if (Array.isArray(val)) {
    return val.map(redactSensitive);
  }
  if (typeof val === "object") {
    const res: Record<string, any> = {};
    for (const [k, v] of Object.entries(val)) {
      if (/password|token|secret|api_?key|credential|authorization|private_?key/i.test(k)) {
        res[k] = "••••••••";
      } else {
        res[k] = redactSensitive(v);
      }
    }
    return res;
  }
  return val;
}

export function JsonViewer({ data, rootLabel = "output", maxDepth = 4 }: { data: any; rootLabel?: string; maxDepth?: number }) {
  const [copied, setCopied] = useState(false);
  const redacted = useMemo(() => redactSensitive(data), [data]);

  const copy = () => {
    try {
      navigator.clipboard.writeText(JSON.stringify(redacted, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  return (
    <div className="card col" style={{ background: "var(--bg-card)", border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}>
      <div className="row spread" style={{ padding: "6px 10px", background: "var(--bg-surface)", borderBottom: "1px solid var(--line)", alignItems: "center" }}>
        <span className="mono-sm fg-2" style={{ fontSize: 11 }}>{rootLabel}</span>
        <button type="button" className="btn btn-xs btn-ghost" onClick={copy} style={{ height: 22, fontSize: 11 }}>
          <Icon name={copied ? "check" : "copy"} size={12} /> {copied ? "Copied" : "Copy JSON"}
        </button>
      </div>
      <div className="scroll-y" style={{ padding: "8px 10px", maxHeight: 320, fontSize: 12, lineHeight: "17px" }}>
        <JsonNode value={redacted} depth={0} maxDepth={maxDepth} />
      </div>
    </div>
  );
}

function JsonNode({ value, depth, maxDepth }: { value: any; depth: number; maxDepth: number }) {
  const [expanded, setExpanded] = useState(depth < 2);

  if (value === null) return <span style={{ color: "var(--fg-2)" }}>null</span>;
  if (typeof value === "boolean") return <span style={{ color: "var(--accent)" }}>{value ? "true" : "false"}</span>;
  if (typeof value === "number") return <span style={{ color: "var(--signal)" }}>{value}</span>;
  if (typeof value === "string") return <span style={{ color: "var(--ok)", wordBreak: "break-all" }}>"{value}"</span>;

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="fg-2">[]</span>;
    return (
      <div style={{ marginLeft: depth > 0 ? 12 : 0 }}>
        <span
          onClick={() => setExpanded(!expanded)}
          style={{ cursor: "pointer", userSelect: "none", color: "var(--fg-1)", fontWeight: 600 }}
        >
          {expanded ? "▼" : "▶"} Array[{value.length}]
        </span>
        {expanded && (
          <div style={{ borderLeft: "1px dashed var(--line)", paddingLeft: 8, marginTop: 2 }}>
            {value.map((item, idx) => (
              <div key={idx} style={{ marginTop: 2 }}>
                <span className="fg-2 mono-sm" style={{ marginRight: 4 }}>{idx}:</span>
                <JsonNode value={item} depth={depth + 1} maxDepth={maxDepth} />
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (typeof value === "object") {
    const keys = Object.keys(value);
    if (keys.length === 0) return <span className="fg-2">{"{}"}</span>;
    return (
      <div style={{ marginLeft: depth > 0 ? 12 : 0 }}>
        <span
          onClick={() => setExpanded(!expanded)}
          style={{ cursor: "pointer", userSelect: "none", color: "var(--fg-1)", fontWeight: 600 }}
        >
          {expanded ? "▼" : "▶"} Object{"{"}{keys.length}{"}"}
        </span>
        {expanded && (
          <div style={{ borderLeft: "1px dashed var(--line)", paddingLeft: 8, marginTop: 2 }}>
            {keys.map((k) => (
              <div key={k} style={{ marginTop: 2 }}>
                <span style={{ color: "var(--accent)", fontWeight: 600, marginRight: 4 }}>"{k}":</span>
                <JsonNode value={value[k]} depth={depth + 1} maxDepth={maxDepth} />
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return <span>{String(value)}</span>;
}

export function WorkflowExecutionPanel({
  project,
  workflow,
  running: controlledRunning,
  onRunningChange,
  onBeforeRun,
  onClose,
  onResetRun,
  onNodeStep,
  onFinalDebug,
  wfs,
  onSelectWorkflow,
}: {
  project: any;
  workflow: Workflow | null;
  running?: boolean;
  onRunningChange?: (running: boolean) => void;
  onBeforeRun?: () => Promise<void>;
  onClose?: () => void;
  onResetRun?: () => void;
  onNodeStep?: (nodeId: string, status?: "idle" | "running" | "done" | "error", output?: any) => void;
  onFinalDebug?: (debugNodes: Record<string, any>) => void;
  wfs?: Workflow[];
  onSelectWorkflow?: (w: Workflow) => void;
}) {
  const [internalRunning, setInternalRunning] = useState(false);
  const isRunning = controlledRunning !== undefined ? controlledRunning : internalRunning;
  const setRunning = useCallback((r: boolean) => {
    setInternalRunning(r);
    onRunningChange?.(r);
  }, [onRunningChange]);

  const [inputMode, setInputMode] = useState<"message" | "json">("message");
  const [inputVal, setInputVal] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);

  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<"idle" | "queued" | "running" | "interrupted" | "done" | "error" | "canceled">("idle");
  const [executionError, setExecutionError] = useState<string | null>(null);

  const [startTime, setStartTime] = useState<number | null>(null);
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [meter, setMeter] = useState<{ tokens: number; cost: number } | null>(null);

  const [finalAnswer, setFinalAnswer] = useState("");
  const [finalOutput, setFinalOutput] = useState<any>(null);
  const [nodeSteps, setNodeSteps] = useState<NodeStepRecord[]>([]);
  const [activities, setActivities] = useState<ActivityRecord[]>([]);
  const [rawLogs, setRawLogs] = useState<LogEntry[]>([]);
  const [interruptPayload, setInterruptPayload] = useState<any>(null);
  const [compDefs, setCompDefs] = useState<Record<string, ComponentT>>({});
  const [liveParts, setLiveParts] = useState<Part[]>([]);

  const [viewerTab, setViewerTab] = useState<"output" | "nodes" | "activity" | "logs">("output");

  const threadRef = useRef<string | null>(null);
  const activeRef = useRef(true);
  const abortCtrlRef = useRef<AbortController | null>(null);
  const actNameRef = useRef<Record<string, string>>({});

  useEffect(() => {
    activeRef.current = true;
    return () => {
      activeRef.current = false;
      abortCtrlRef.current?.abort();
      setRunning(false);
    };
  }, [setRunning]);

  useEffect(() => {
    if (project?.id) {
      api.listComponents(project.id).then((cs) => setCompDefs(Object.fromEntries(cs.map((c) => [c.id, c])))).catch(() => {});
    }
  }, [project?.id]);

  // Map sub-agent names to graph node IDs for live canvas illumination
  const subNameToId = useMemo(() => {
    const m: Record<string, string> = {};
    const nodes = (workflow as any)?.executable?.nodes || (workflow as any)?.canvas?.nodes || [];
    for (const n of nodes) {
      const name = n?.config?.name ?? n?.data?.config?.name;
      const type = n?.type ?? n?.data?.nodeType;
      if (type === "agent" || type === "deep_agent") {
        if (name) m[name] = n.id;
        m[n.id] = n.id;
      }
    }
    return m;
  }, [workflow]);

  // Validate JSON if in JSON mode
  const handleInputChange = (val: string) => {
    setInputVal(val);
    if (inputMode === "json" && val.trim()) {
      try {
        JSON.parse(val);
        setJsonError(null);
      } catch (e: any) {
        setJsonError(`Invalid JSON: ${e.message}`);
      }
    } else {
      setJsonError(null);
    }
  };

  const addLog = useCallback((event: string, summary: string) => {
    const time = new Date().toLocaleTimeString();
    setRawLogs((prev) => [...prev, { id: Math.random().toString(36).slice(2, 7), time, event, summary }]);
  }, []);

  const resetExecution = () => {
    threadRef.current = null;
    setRunId(null);
    setRunStatus("idle");
    setExecutionError(null);
    setStartTime(null);
    setDurationMs(null);
    setMeter(null);
    setFinalAnswer("");
    setFinalOutput(null);
    setNodeSteps([]);
    setActivities([]);
    setRawLogs([]);
    setInterruptPayload(null);
    setLiveParts([]);
    onResetRun?.();
  };

  async function handleRun() {
    if (isRunning || !project?.id || !workflow?.id) return;

    let payload: Record<string, any> = {};
    const trimmed = inputVal.trim();
    if (inputMode === "json") {
      if (trimmed) {
        try {
          payload = JSON.parse(trimmed);
        } catch (e: any) {
          setJsonError(`JSON Syntax Error: ${e.message}`);
          return;
        }
      }
    } else {
      if (trimmed) {
        payload = { messages: [{ role: "user", content: trimmed }] };
      }
    }

    setRunning(true);
    setRunStatus("queued");
    setExecutionError(null);
    setFinalAnswer("");
    setFinalOutput(null);
    setNodeSteps([]);
    setActivities([]);
    setRawLogs([]);
    setInterruptPayload(null);
    setLiveParts([]);
    actNameRef.current = {};
    onResetRun?.();

    const startTs = Date.now();
    setStartTime(startTs);
    addLog("init", `Starting execution for workflow "${workflow.name}"`);

    const acc = new ReplyAccumulator();
    let currentLastNode: string | null = null;
    abortCtrlRef.current = new AbortController();

    try {
      if (onBeforeRun) await onBeforeRun();
      if (!activeRef.current) return;

      const run = await api.createRun(
        project.id,
        workflow.id,
        payload,
        threadRef.current || undefined,
      );

      setRunId(run.id);
      threadRef.current = run.thread_id;
      setRunStatus("running");
      addLog("run_created", `Run ID: ${run.id} (Thread: ${run.thread_id})`);

      await openSSE(
        api.runStreamUrl(project.id, workflow.id, run.id),
        (f) => {
          if (!activeRef.current) return;

          if (f.event === "messages" && f.data?.content) {
            acc.addText(f.data.content);
            setLiveParts(acc.parts({ streaming: true }));
          } else if (f.event === "node_start" && f.data?.node) {
            const node = f.data.node;
            currentLastNode = node;
            onNodeStep?.(node, "running");
            addLog("node_start", `Node started: ${node}`);
            setNodeSteps((prev) => {
              const existing = prev.find((s) => s.id === node);
              if (existing) {
                return prev.map((s) => (s.id === node ? { ...s, status: "running", timestamp: Date.now() } : s));
              }
              return [...prev, { id: node, name: node, status: "running", timestamp: Date.now() }];
            });
          } else if (f.event === "node_error" && f.data?.node) {
            const node = f.data.node;
            const msg = f.data?.message || `${node} failed`;
            onNodeStep?.(node, "error");
            addLog("node_error", `Node error on ${node}: ${msg}`);
            setNodeSteps((prev) => prev.map((s) => (s.id === node ? { ...s, status: "error", error: msg } : s)));
          } else if (f.event === "updates" && f.data && typeof f.data === "object") {
            const node = Object.keys(f.data)[0];
            if (node) {
              const output = f.data[node];
              onNodeStep?.(node, "done", output);
              addLog("updates", `Node updated: ${node}`);
              setNodeSteps((prev) => prev.map((s) => (s.id === node ? { ...s, status: "done", output } : s)));
              if (currentLastNode === node) currentLastNode = null;
            }
          } else if (f.event === "activity" && f.data?.id) {
            const a = f.data;
            addLog("activity", `${a.kind} [${a.name}] phase: ${a.phase}`);
            if (a.phase === "start") {
              if (a.kind === "subagent") {
                actNameRef.current[a.id] = a.name;
                const nid = subNameToId[a.name];
                if (nid) onNodeStep?.(nid, "running");
              }
              setActivities((prev) => [...prev, {
                id: a.id,
                kind: a.kind,
                name: a.name,
                phase: "start",
                input: a.input,
                timestamp: Date.now(),
              }]);
            } else if (a.phase === "end") {
              if (a.kind === "subagent") {
                const nid = subNameToId[actNameRef.current[a.id] || a.name];
                if (nid) onNodeStep?.(nid, "done", a.output);
              }
              setActivities((prev) => prev.map((it) => (it.id === a.id ? { ...it, phase: "end", output: a.output, error: !!a.error } : it)));
            }
          } else if (f.event === "custom" && f.data?.channel === "component" && f.data?.payload) {
            acc.addComponent(f.data.payload as ComponentInstance);
            setLiveParts(acc.parts({ streaming: true }));
            addLog("custom", `Interactive component: ${(f.data.payload as any).name || "widget"}`);
          } else if (f.event === "done") {
            const answer = f.data?.answer || "";
            setFinalAnswer(answer);
            setFinalOutput(f.data);
            setRunStatus("done");
            setMeter({ tokens: f.data?.total_tokens ?? 0, cost: f.data?.total_cost_usd ?? 0 });
            onFinalDebug?.(f.data?.debug?.nodes || {});
            if (currentLastNode) onNodeStep?.(currentLastNode, "done");
            addLog("done", `Execution finished (${f.data?.total_tokens ?? 0} tokens)`);
          } else if (f.event === "interrupt") {
            setRunStatus("interrupted");
            setInterruptPayload(f.data);
            addLog("interrupt", "Execution paused for Human Approval");
            if (currentLastNode) onNodeStep?.(currentLastNode, "done");
          } else if (f.event === "error") {
            const errStr = f.data?.message || "Execution failed";
            setExecutionError(errStr);
            setRunStatus("error");
            addLog("error", errStr);
            if (currentLastNode) onNodeStep?.(currentLastNode, "error");
          }
        },
        { signal: abortCtrlRef.current.signal },
      );
    } catch (e: any) {
      if (!activeRef.current) return;
      const msg = e.name === "AbortError" ? "Execution stopped by user" : (e.message || String(e));
      setExecutionError(msg);
      setRunStatus(e.name === "AbortError" ? "canceled" : "error");
      addLog(e.name === "AbortError" ? "canceled" : "error", msg);
      if (currentLastNode) onNodeStep?.(currentLastNode, "error");
    } finally {
      if (activeRef.current) {
        setDurationMs(Date.now() - startTs);
        setRunning(false);
      }
    }
  }

  async function handleCancel() {
    abortCtrlRef.current?.abort();
    if (runId && project?.id && workflow?.id) {
      try {
        await api.cancelRun(project.id, workflow.id, runId);
      } catch {}
    }
    setRunStatus("canceled");
    setRunning(false);
    addLog("canceled", "Run cancellation requested");
  }

  async function handleResumeApproval(approved: boolean) {
    if (!runId || !project?.id || !workflow?.id) return;
    setRunning(true);
    setRunStatus("running");
    addLog("approval_response", `User ${approved ? "APPROVED" : "REJECTED"} paused operation`);
    try {
      const res = await api.resumeRun(project.id, workflow.id, runId, { approved });
      setInterruptPayload(null);
      if (res?.interrupted) {
        setRunStatus("interrupted");
      } else if (res?.error) {
        setExecutionError(res.error);
        setRunStatus("error");
      } else {
        setRunStatus("done");
      }
    } catch (e: any) {
      setExecutionError(e.message || "Failed to resume run");
      setRunStatus("error");
    } finally {
      setRunning(false);
    }
  }

  const durationStr = durationMs !== null ? (durationMs < 1000 ? `${durationMs}ms` : `${(durationMs / 1000).toFixed(2)}s`) : null;

  return (
    <div className="col" style={{ flex: 1, minHeight: 0, background: "var(--bg-1)" }}>
      {/* Top Header */}
      <div className="row spread" style={{ padding: "10px 14px", borderBottom: "1px solid var(--line)", background: "var(--bg-2)", flex: "none", alignItems: "center" }}>
        <div className="row gap2" style={{ alignItems: "center", minWidth: 0 }}>
          <Tile icon="workflows" color="var(--accent)" size={24} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 700, display: "flex", alignItems: "center", gap: 6 }}>
              <span>Orchestrator Execution</span>
              {runStatus !== "idle" && <StatusPill status={runStatus} />}
            </div>
            {workflow && <div className="fg-2 t-caption mono truncate">{workflow.name}</div>}
          </div>
        </div>
        <div className="row gap2" style={{ alignItems: "center" }}>
          {wfs && wfs.length > 0 && onSelectWorkflow && (
            <select
              className="select"
              style={{ height: 26, fontSize: 11, maxWidth: 140 }}
              value={workflow?.id || ""}
              onChange={(e) => {
                const target = wfs.find((w) => w.id === e.target.value);
                if (target) onSelectWorkflow(target);
              }}
            >
              {wfs.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          )}
          {onClose && (
            <button type="button" className="iconbtn" onClick={onClose} title="Close Execution Viewer">
              <Icon name="x" size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Manual Trigger & Config Controls */}
      <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)", background: "var(--bg-surface)", flex: "none" }}>
        <div className="col gap2">
          <div className="row spread" style={{ alignItems: "center" }}>
            <div className="row gap1" style={{ alignItems: "center" }}>
              <span className="t-micro" style={{ color: "var(--fg-1)" }}>Input Parameters</span>
              <span className="mono-sm fg-2" style={{ fontSize: 10 }}>({inputMode === "message" ? "Message" : "JSON Payload"})</span>
            </div>
            <div className="row gap1" style={{ alignItems: "center" }}>
              <button
                type="button"
                className={`btn btn-xs ${inputMode === "message" ? "btn-secondary" : "btn-ghost"}`}
                onClick={() => setInputMode("message")}
                style={{ height: 22, fontSize: 10.5 }}
              >
                Message
              </button>
              <button
                type="button"
                className={`btn btn-xs ${inputMode === "json" ? "btn-secondary" : "btn-ghost"}`}
                onClick={() => setInputMode("json")}
                style={{ height: 22, fontSize: 10.5 }}
              >
                JSON Payload
              </button>
            </div>
          </div>

          {inputMode === "message" ? (
            <input
              className="input"
              placeholder="Message the workflow…"
              value={inputVal}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleRun();
                }
              }}
              disabled={isRunning}
              style={{ fontSize: 12.5, height: 32 }}
            />
          ) : (
            <textarea
              className="input mono-sm"
              placeholder='{\n  "input": "data",\n  "param": 123\n}'
              value={inputVal}
              onChange={(e) => handleInputChange(e.target.value)}
              disabled={isRunning}
              rows={3}
              style={{ fontSize: 11.5, resize: "vertical", fontFamily: "var(--font-mono)" }}
            />
          )}

          {jsonError && (
            <div style={{ color: "var(--err)", fontSize: 11 }} className="row gap1">
              <Icon name="alert-triangle" size={12} /> {jsonError}
            </div>
          )}

          <div className="row spread" style={{ alignItems: "center", marginTop: 2 }}>
            <button
              type="button"
              className="btn btn-ghost btn-xs"
              onClick={resetExecution}
              disabled={isRunning}
              style={{ height: 26, fontSize: 11 }}
            >
              Reset
            </button>
            <div className="row gap2" style={{ alignItems: "center" }}>
              {isRunning ? (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleCancel}
                  style={{ height: 28, fontSize: 11.5 }}
                >
                  <Icon name="x" size={12} /> Stop
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={handleRun}
                  disabled={!workflow || !!jsonError}
                  style={{ height: 28, fontSize: 11.5, minWidth: 80 }}
                >
                  <Icon name="play" size={12} /> Run
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Execution Diagnostics Bar */}
      {(runId || durationStr || meter) && (
        <div className="row spread" style={{ padding: "6px 14px", borderBottom: "1px solid var(--line)", background: "var(--bg-3)", flex: "none", alignItems: "center", fontSize: 11 }}>
          <div className="row gap2" style={{ alignItems: "center" }}>
            {runId && (
              <span className="mono-sm fg-2" title={`Run ID: ${runId}`}>
                run: {runId.slice(0, 10)}…
              </span>
            )}
            {durationStr && (
              <span className="fg-2">
                ⏱ {durationStr}
              </span>
            )}
          </div>
          {meter && (
            <span className="mono-sm" style={{ color: "var(--signal)" }}>
              {meter.tokens} tok · {fmtUSD(meter.cost)}
            </span>
          )}
        </div>
      )}

      {/* Human Approval Interrupt Request Card */}
      {runStatus === "interrupted" && (
        <div style={{ margin: "10px 14px 0", padding: "10px 12px", background: "rgba(245,158,11,0.08)", border: "1px solid var(--warn)", borderRadius: 8 }}>
          <div className="col gap2">
            <div className="row gap2" style={{ alignItems: "center" }}>
              <Icon name="shield" size={16} style={{ color: "var(--warn)" }} />
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--warn)" }}>Action Requires Approval</div>
            </div>
            <div className="fg-1" style={{ fontSize: 11.5 }}>
              The workflow execution paused for operator confirmation before executing a privileged action or tool.
            </div>
            {interruptPayload && (
              <div className="mono-sm card" style={{ padding: 6, fontSize: 10.5, background: "var(--bg-card)", maxHeight: 100, overflow: "auto" }}>
                {JSON.stringify(interruptPayload, null, 2)}
              </div>
            )}
            <div className="row gap2" style={{ marginTop: 4 }}>
              <button
                type="button"
                className="btn btn-xs btn-primary"
                onClick={() => handleResumeApproval(true)}
                disabled={isRunning}
                style={{ background: "var(--ok)", borderColor: "var(--ok)", color: "#fff", fontSize: 11 }}
              >
                <Icon name="check" size={12} /> Approve Action
              </button>
              <button
                type="button"
                className="btn btn-xs btn-secondary"
                onClick={() => handleResumeApproval(false)}
                disabled={isRunning}
                style={{ fontSize: 11 }}
              >
                Reject Action
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Execution Error Banner */}
      {executionError && (
        <div style={{ margin: "10px 14px 0", padding: "8px 12px", background: "rgba(239,68,68,0.1)", border: "1px solid var(--err)", borderRadius: 8, color: "var(--err)", fontSize: 11.5 }}>
          <div className="row gap1" style={{ alignItems: "flex-start" }}>
            <Icon name="alert-triangle" size={14} style={{ flexShrink: 0, marginTop: 1 }} />
            <div>{executionError}</div>
          </div>
        </div>
      )}

      {/* Result Viewer Navigation Tabs */}
      <div className="row" style={{ padding: "0 14px", borderBottom: "1px solid var(--line)", background: "var(--bg-2)", flex: "none", gap: 8 }}>
        <button
          type="button"
          className={`btn btn-xs btn-ghost ${viewerTab === "output" ? "active-tab" : ""}`}
          onClick={() => setViewerTab("output")}
          style={{ height: 28, borderRadius: 0, borderBottom: viewerTab === "output" ? "2px solid var(--accent)" : "2px solid transparent", color: viewerTab === "output" ? "var(--fg-0)" : "var(--fg-2)" }}
        >
          Output & Results
        </button>
        <button
          type="button"
          className={`btn btn-xs btn-ghost ${viewerTab === "nodes" ? "active-tab" : ""}`}
          onClick={() => setViewerTab("nodes")}
          style={{ height: 28, borderRadius: 0, borderBottom: viewerTab === "nodes" ? "2px solid var(--accent)" : "2px solid transparent", color: viewerTab === "nodes" ? "var(--fg-0)" : "var(--fg-2)" }}
        >
          Node Steps ({nodeSteps.length})
        </button>
        <button
          type="button"
          className={`btn btn-xs btn-ghost ${viewerTab === "activity" ? "active-tab" : ""}`}
          onClick={() => setViewerTab("activity")}
          style={{ height: 28, borderRadius: 0, borderBottom: viewerTab === "activity" ? "2px solid var(--accent)" : "2px solid transparent", color: viewerTab === "activity" ? "var(--fg-0)" : "var(--fg-2)" }}
        >
          Tools & Subagents ({activities.length})
        </button>
        <button
          type="button"
          className={`btn btn-xs btn-ghost ${viewerTab === "logs" ? "active-tab" : ""}`}
          onClick={() => setViewerTab("logs")}
          style={{ height: 28, borderRadius: 0, borderBottom: viewerTab === "logs" ? "2px solid var(--accent)" : "2px solid transparent", color: viewerTab === "logs" ? "var(--fg-0)" : "var(--fg-2)" }}
        >
          Logs ({rawLogs.length})
        </button>
      </div>

      {/* Tab Contents */}
      <div className="scroll-y" style={{ flex: 1, padding: 14 }}>
        {viewerTab === "output" && (
          <div className="col gap3">
            {finalAnswer && (
              <div className="card col gap1" style={{ padding: 12, background: "var(--bg-surface)" }}>
                <div className="t-micro" style={{ color: "var(--fg-2)" }}>Final Synthesis / Answer</div>
                <div style={{ fontSize: 13, lineHeight: "19px" }}>
                  <Markdown>{finalAnswer}</Markdown>
                </div>
              </div>
            )}

            {liveParts.length > 0 && (
              <div className="col gap2">
                {liveParts.map((p, idx) => {
                  if (p.kind === "text") {
                    return <div key={idx}><Markdown>{p.text}</Markdown></div>;
                  }
                  const def = compDefs[p.inst.component_id];
                  return (
                    <ComponentRenderer
                      key={idx}
                      def={def || { id: p.inst.component_id, name: p.inst.name, html: "", css: "" }}
                      props={p.inst.props || {}}
                      onAction={() => {}}
                    />
                  );
                })}
              </div>
            )}

            {finalOutput ? (
              <JsonViewer data={finalOutput} rootLabel="Final Run Output" />
            ) : isRunning ? (
              <div className="col center" style={{ padding: 24, textAlign: "center", color: "var(--fg-2)" }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", animation: "pulse 1s infinite", marginBottom: 8 }} />
                <div style={{ fontSize: 12 }}>Pipeline executing... lighting up nodes on canvas</div>
              </div>
            ) : (
              <div className="col center" style={{ padding: 32, textAlign: "center", color: "var(--fg-2)" }}>
                <Tile icon="playground" color="var(--accent)" size={32} />
                <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--fg-1)", marginTop: 8 }}>Ready for Execution</div>
                <div style={{ fontSize: 11, maxWidth: 280, marginTop: 4 }}>
                  Configure inputs above and click Run to execute this pipeline with full node telemetry.
                </div>
              </div>
            )}
          </div>
        )}

        {viewerTab === "nodes" && (
          <div className="col gap2">
            {nodeSteps.length === 0 ? (
              <div className="fg-2" style={{ fontSize: 11.5, textAlign: "center", padding: 20 }}>
                No node executions recorded yet.
              </div>
            ) : (
              nodeSteps.map((s, idx) => (
                <div key={idx} className="card col gap1" style={{ padding: 10, background: "var(--bg-card)" }}>
                  <div className="row spread" style={{ alignItems: "center" }}>
                    <div className="row gap2" style={{ alignItems: "center" }}>
                      <Icon name="workflow" size={13} style={{ color: "var(--accent)" }} />
                      <span style={{ fontSize: 12, fontWeight: 600 }}>{s.name}</span>
                    </div>
                    <StatusPill status={s.status} />
                  </div>
                  {s.error && (
                    <div style={{ color: "var(--err)", fontSize: 11 }}>{s.error}</div>
                  )}
                  {s.output && (
                    <div style={{ marginTop: 4 }}>
                      <JsonViewer data={s.output} rootLabel={`Output: ${s.name}`} maxDepth={2} />
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {viewerTab === "activity" && (
          <div className="col gap2">
            {activities.length === 0 ? (
              <div className="fg-2" style={{ fontSize: 11.5, textAlign: "center", padding: 20 }}>
                No delegated tool or specialist subagent activity recorded.
              </div>
            ) : (
              activities.map((a, idx) => (
                <div key={idx} className="card col gap1" style={{ padding: 10, background: "var(--bg-card)" }}>
                  <div className="row spread" style={{ alignItems: "center" }}>
                    <div className="row gap2" style={{ alignItems: "center" }}>
                      <Icon name={a.kind === "subagent" ? "bot" : "tools"} size={13} style={{ color: a.kind === "subagent" ? "var(--accent)" : "var(--signal)" }} />
                      <span style={{ fontSize: 12, fontWeight: 600 }}>{a.name}</span>
                      <span className="pill" style={{ fontSize: 9.5 }}>{a.kind}</span>
                    </div>
                    <span className="mono-sm fg-2" style={{ fontSize: 10.5 }}>{a.phase}</span>
                  </div>
                  {a.input && (
                    <div style={{ marginTop: 2 }}>
                      <div className="t-micro" style={{ color: "var(--fg-2)" }}>Arguments</div>
                      <JsonViewer data={a.input} rootLabel="Args" maxDepth={2} />
                    </div>
                  )}
                  {a.output && (
                    <div style={{ marginTop: 4 }}>
                      <div className="t-micro" style={{ color: "var(--fg-2)" }}>Result</div>
                      <JsonViewer data={a.output} rootLabel="Result" maxDepth={2} />
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {viewerTab === "logs" && (
          <div className="mono-sm card" style={{ padding: 10, background: "var(--bg-card)", fontSize: 11, lineHeight: "17px" }}>
            {rawLogs.length === 0 ? (
              <div className="fg-2">Execution event stream empty.</div>
            ) : (
              rawLogs.map((l) => (
                <div key={l.id} className="row gap2" style={{ borderBottom: "1px dashed var(--line)", padding: "3px 0" }}>
                  <span className="fg-2" style={{ minWidth: 64 }}>{l.time}</span>
                  <span style={{ color: "var(--accent)", fontWeight: 600, minWidth: 90 }}>[{l.event}]</span>
                  <span className="fg-1 truncate">{l.summary}</span>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// Backward-compatible alias so existing callers require 0 modification
export const WorkflowTestPanel = WorkflowExecutionPanel;
