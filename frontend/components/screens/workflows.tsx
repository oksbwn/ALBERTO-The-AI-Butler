"use client";
/* Workflows list + the React Flow canvas editor (palette · typed nodes · inspector). */
import "@xyflow/react/dist/style.css";
import {
  addEdge, applyEdgeChanges, applyNodeChanges, Background, BackgroundVariant, Controls, MiniMap, ReactFlow, ReactFlowProvider,
  useEdgesState, useNodesState, useReactFlow, ViewportPortal, type Connection, type Edge, type EdgeChange, type NodeChange,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Icon } from "../icons";
import { StatusPill, Tile } from "../primitives";
import { ForgeNode, NodeTypesContext } from "../canvas/ForgeNode";
import { AgentConfig, CollapsibleSection } from "../canvas/AgentConfig";
import { EdgeOverlay } from "../canvas/EdgeOverlay";
import { WorkflowTestPanel } from "../canvas/WorkflowTestPanel";
import { FieldsForm, ModelSelect, MultiSelectChips, VariablePicker, type FieldSpec, type UpstreamSource } from "../canvas/ConfigForm";
import { Field, Toggle } from "../primitives";
import { VersionHistory } from "../version-history";
import { ImportExport } from "../import-export";
import type { ComponentT } from "@/lib/api";
import { api, openSSE, Agent, McpClientT, NodeType, Tool, ToolSet, Workflow } from "@/lib/api";
import { NODE_META, NODE_HELP, IO_COLOR, fmtUSD } from "@/lib/data";
import { canvasToExecutable, canvasToFlow, ioCompatible, newNodeId, starterWorkflow, type FlowEdge, type FlowNode } from "@/lib/graph";

function stripRunData(nds: FlowNode[]): FlowNode[] {
  return nds.map((n) => {
    const { status, debug, ...data } = n.data;
    return { ...n, data };
  });
}

function extractSchemaKeys(schema: any, prefix = ""): string[] {
  if (!schema) return [];
  let obj = schema;
  if (typeof obj === "string") {
    try {
      obj = JSON.parse(obj);
    } catch {
      return [];
    }
  }
  if (!obj || typeof obj !== "object") return [];
  const props = obj.properties;
  if (!props || typeof props !== "object") return [];
  const keys: string[] = [];
  for (const [key, val] of Object.entries(props)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    keys.push(fullKey);
    if (val && typeof val === "object" && (val as any).type === "object" && (val as any).properties) {
      keys.push(...extractSchemaKeys(val, fullKey));
    }
  }
  return keys;
}

function getUpstreamOutputs(selectedId: string | null, nodes: FlowNode[], edges: FlowEdge[]): UpstreamSource[] {
  if (!selectedId) return [];
  const inMap: Record<string, string[]> = {};
  for (const e of edges) {
    if (!inMap[e.target]) inMap[e.target] = [];
    inMap[e.target].push(e.source);
  }
  const visited = new Set<string>();
  const queue = [...(inMap[selectedId] || [])];
  const upstreamNodeIds: string[] = [];
  while (queue.length > 0) {
    const cur = queue.shift()!;
    if (visited.has(cur)) continue;
    visited.add(cur);
    upstreamNodeIds.push(cur);
    if (inMap[cur]) queue.push(...inMap[cur]);
  }

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const sources: UpstreamSource[] = [
    {
      nodeId: "flow",
      nodeName: "Flow State",
      keys: ["msg", "payload", "topic", "metadata", "messages"],
    },
  ];

  for (const id of upstreamNodeIds) {
    const n = byId.get(id);
    if (!n) continue;
    const t = n.data.nodeType;
    const cfg = n.data.config || {};
    const keys: string[] = [];
    if (t === "inject") {
      keys.push("payload", "topic", "msg", "metadata");
    } else if (t === "transform") {
      keys.push(cfg.output_key || "payload", "msg");
    } else if (t === "classifier") {
      keys.push(cfg.output_key || "intent");
    } else if (t === "tool_call") {
      keys.push(cfg.output_key || "result", "payload");
    } else if (t === "llm") {
      keys.push(cfg.output_key || "result", "messages");
    } else if (t === "agent" || t === "deep_agent") {
      keys.push("payload", "output", "msg", "response", "content", "messages", "tool_calls");
      if (cfg.output_key) {
        keys.push(cfg.output_key);
      }
      const schema =
        cfg.response_format?.schema ||
        cfg.response_format?.json_schema?.schema ||
        cfg.output_schema ||
        cfg.structured_output;
      if (schema) {
        const schemaKeys = extractSchemaKeys(schema);
        for (const sk of schemaKeys) {
          keys.push(sk);
          keys.push(`payload.${sk}`);
        }
      }
    } else if (t === "human_input") {
      keys.push(cfg.output_key || "decision");
    } else if (t === "webhook_in") {
      keys.push("payload", "body", "headers");
    } else if (t === "parallel_fanout") {
      keys.push(cfg.item_key || "item");
    } else if (t === "join") {
      keys.push(cfg.output_key || "results", "items");
    } else {
      keys.push("payload", "output");
    }
    sources.push({
      nodeId: n.id,
      nodeName: cfg.name || n.id,
      nodeType: t,
      keys: Array.from(new Set(keys)),
    });
  }

  return sources;
}

function EditableName({
  value,
  fallback,
  className,
  inputClassName = "input",
  style,
  inputStyle,
  onCommit,
}: {
  value?: string | null;
  fallback: string;
  className?: string;
  inputClassName?: string;
  style?: CSSProperties;
  inputStyle?: CSSProperties;
  onCommit: (name: string) => void | Promise<void>;
}) {
  const display = (value || "").trim() || fallback;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(display);

  useEffect(() => {
    if (!editing) setDraft(display);
  }, [display, editing]);

  const finish = () => {
    const next = draft.trim();
    setEditing(false);
    if (!next || next === display) {
      setDraft(display);
      return;
    }
    void onCommit(next);
  };

  if (editing) {
    return (
      <input
        className={inputClassName}
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={finish}
        onFocus={(e) => e.currentTarget.select()}
        onClick={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") {
            setDraft(display);
            setEditing(false);
          }
        }}
        style={{ minWidth: 0, ...inputStyle }}
      />
    );
  }

  return (
    <button
      type="button"
      className={className}
      title={display}
      onClick={(e) => {
        e.stopPropagation();
        setDraft(display);
        setEditing(true);
      }}
      onPointerDown={(e) => e.stopPropagation()}
      style={{
        display: "block",
        maxWidth: "100%",
        minWidth: 0,
        border: 0,
        background: "transparent",
        color: "inherit",
        padding: 0,
        textAlign: "left",
        cursor: "text",
        ...style,
      }}
    >
      {display}
    </button>
  );
}

/* ============ WORKFLOWS LIST ============ */
export function WorkflowsScreen({ project, onOpen, onNav }: { project: any; onOpen: (w: Workflow) => void; onNav?: (screen: string) => void }) {
  const [wfs, setWfs] = useState<Workflow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    if (!project?.id) return;
    api.listWorkflows(project.id).then((w) => { setWfs(w); setLoaded(true); }).catch(() => setLoaded(true));
  }, [project?.id]);
  useEffect(() => { reload(); }, [reload]);

  async function create() {
    setBusy(true);
    try {
      const s = starterWorkflow();
      const executable = canvasToExecutable(s.nodes, s.edges, { id: "wf" });
      const wf = await api.createWorkflow(project.id, { name: "Untitled workflow", canvas: s.canvas, executable });
      onOpen(wf);
    } finally { setBusy(false); }
  }

  const [deleting, setDeleting] = useState<string | null>(null);
  async function del(e: React.MouseEvent, w: Workflow) {
    e.stopPropagation();
    if (!window.confirm(`Delete workflow "${w.name}"?\n\nThis also removes its run history and traces. This cannot be undone.`)) return;
    setDeleting(w.id);
    try {
      setWfs((prev) => prev.filter((x) => x.id !== w.id)); // optimistic
      await api.deleteWorkflow(project.id, w.id);
    } catch {
      reload(); // restore on failure
    } finally {
      setDeleting(null);
    }
  }

  async function renameWorkflow(w: Workflow, name: string) {
    if (!project?.id || name === w.name) return;
    const previous = wfs;
    setWfs((prev) => prev.map((x) => (x.id === w.id ? { ...x, name } : x)));
    try {
      const updated = await api.updateWorkflow(project.id, w.id, { name });
      setWfs((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
    } catch {
      setWfs(previous);
    }
  }

  return (
    <div className="scroll-y" style={{ flex: 1, padding: "24px 28px" }}>
      <div className="fade-up" style={{ maxWidth: 1600, margin: "0 auto" }}>
        <div className="row spread" style={{ marginBottom: 18 }}>
          <div>
            <div className="t-display">Workflows</div>
            <div className="fg-1" style={{ marginTop: 3 }}>Visual graphs compiled to LangGraph. Build agents, routers, tools, and HITL on the canvas.</div>
          </div>
          <div className="row gap2">
            {onNav && (
              <button className="btn btn-secondary" onClick={() => onNav("playground")}>
                <Icon name="sparkles" size={15} /> AI Studio
              </button>
            )}
            <ImportExport project={project} type="workflow" typeLabel="workflow" size="md" onImported={reload}
              items={wfs.map((w) => ({ id: w.id, name: w.name || "Untitled workflow", sub: `${(w.executable?.nodes || []).length} nodes` }))} />
            <button className="btn btn-primary" onClick={create} disabled={busy}><Icon name="plus" size={15} />{busy ? "Creating…" : "New workflow"}</button>
          </div>
        </div>
        {loaded && wfs.length === 0 ? (
          <div className="card col center" style={{ padding: 48, gap: 12, textAlign: "center" }}>
            <Tile icon="workflows" color="var(--accent)" size={52} glow />
            <div className="t-h1">No workflows yet</div>
            <div className="fg-1" style={{ maxWidth: 360 }}>Create your first workflow and wire nodes on the canvas.</div>
            <button className="btn btn-primary btn-lg" onClick={create} disabled={busy}><Icon name="plus" size={16} />New workflow</button>
          </div>
        ) : (
          <div className="col gap3">
            {wfs.map((w) => (
              <div key={w.id} className="card card-hover" style={{ padding: 14 }} onClick={() => onOpen(w)}>
                <div className="row gap3">
                  <Tile icon="workflows" color="var(--accent)" size={38} />
                  <div className="grow" style={{ minWidth: 0 }}>
                    <EditableName value={w.name} fallback="Untitled workflow" className="t-h2 truncate" inputStyle={{ height: 28, maxWidth: 360 }} onCommit={(name) => renameWorkflow(w, name)} />
                    <div className="fg-2 t-caption">{(w.executable?.nodes || []).length} nodes · v{w.active_version}</div>
                  </div>
                  <StatusPill status={w.status === "active" ? "active" : "draft"} />
                  <button className="iconbtn" title="Delete workflow" disabled={deleting === w.id} onClick={(e) => del(e, w)}><Icon name="trash" size={15} /></button>
                  <Icon name="chevright" size={16} style={{ color: "var(--fg-2)" }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ============ CANVAS ============ */
export function guardCanvasBeforeUnload(dirty: boolean, event: BeforeUnloadEvent): boolean {
  if (!dirty) return false;
  event.preventDefault();
  event.returnValue = "";
  return true;
}

export function WorkflowCanvas(props: { project: any; workflowId?: string; onWorkflowChange?: (workflow: Workflow) => void; onBack: () => void; onRun: () => void; onRegisterFlush?: (fn: (() => Promise<void>) | null) => void }) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}

function CanvasInner({ project, workflowId, onWorkflowChange, onBack, onRun, onRegisterFlush }: { project: any; workflowId?: string; onWorkflowChange?: (workflow: Workflow) => void; onBack: () => void; onRun: () => void; onRegisterFlush?: (fn: (() => Promise<void>) | null) => void }) {
  const [wf, setWf] = useState<Workflow | null>(null);
  const [registry, setRegistry] = useState<Record<string, NodeType>>({});
  const [tools, setTools] = useState<Tool[]>([]);
  const [toolSets, setToolSets] = useState<ToolSet[]>([]);
  // Saved agent presets (from the Agents tab) - loadable into an agent node.
  const [agents, setAgents] = useState<Agent[]>([]);
  const [mcpServers, setMcpServers] = useState<McpClientT[]>([]);
  const [components, setComponents] = useState<ComponentT[]>([]);
  // Live KB folders + Q&A kinds drive the dropdowns in the retrieval node config.
  const [kbFolders, setKbFolders] = useState<string[]>([]);
  const [qaKinds, setQaKinds] = useState<string[]>([]);
  const [nodes, setNodes] = useNodesState<FlowNode>([]);
  const [edges, setEdges] = useEdgesState<FlowEdge>([]);
  const [selId, setSelId] = useState<string | null>(null);
  const [problems, setProblems] = useState<{ pointer: string; message: string }[]>([]);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "invalid">("idle");
  const [running, setRunning] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<"info" | "debug">("info");
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(340);
  const [trayWidth, setTrayWidth] = useState(480);
  const [showProblems, setShowProblems] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  // Unsaved-changes tracking (drives the beforeunload guard + auto-save on navigate-away).
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  // Undo/redo stacks of {nodes, edges} snapshots. Structural actions push; undo/redo pop.
  const [past, setPast] = useState<{ nodes: FlowNode[]; edges: FlowEdge[] }[]>([]);
  const [future, setFuture] = useState<{ nodes: FlowNode[]; edges: FlowEdge[] }[]>([]);
  // Clipboard for copy/paste/duplicate of a single node.
  const clipboardRef = useRef<{ nodeType: string; config: Record<string, any> } | null>(null);
  // Transient, non-blocking connection-type mismatch hint (edges stay permissive).
  const [connWarning, setConnWarning] = useState<string | null>(null);
  const [paletteQuery, setPaletteQuery] = useState("");
  // Hover help for palette items - rendered as a fixed-position card so the palette's
  // own scroll container can't clip it. Positioned from the hovered item's rect (the
  // palette's viewport offset varies with the rail/sidebar, so no hardcoded left).
  const [paletteTip, setPaletteTip] = useState<{ type: string; top: number; left: number } | null>(null);
  const { fitView } = useReactFlow();
  const registryReady = Object.keys(registry).length > 0;

  useEffect(() => {
    api.listNodeTypes().then((nt) => setRegistry(Object.fromEntries(nt.map((n) => [n.type, n])))).catch(() => {});
    if (project?.id) {
      api.listTools(project.id).then(setTools).catch(() => {});
      api.listToolSets(project.id).then(setToolSets).catch(() => {});
      api.listAgents(project.id).then(setAgents).catch(() => {});
      api.listMcpClients(project.id).then(setMcpServers).catch(() => {});
      api.listComponents(project.id).then(setComponents).catch(() => {});
      api.listFolders(project.id).then(setKbFolders).catch(() => {});
      api.listQaKinds(project.id).then(setQaKinds).catch(() => {});
    }
  }, [project?.id]);

  useEffect(() => {
    if (!project?.id || !workflowId) return;
    api.getWorkflow(project.id, workflowId).then((w) => {
      setWf(w);
      const flow = w.canvas?.nodes?.length ? canvasToFlow(w.canvas) : starterWorkflow();
      setNodes(flow.nodes);
      setEdges(flow.edges as any);
      setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 90);
    }).catch(() => {});
  }, [project?.id, workflowId, reloadKey, setNodes, setEdges, fitView]);

  const nodeTypes = useMemo(() => ({ alberto: ForgeNode, forge: ForgeNode }), []);
  const selected = nodes.find((n) => n.id === selId) || null;
  const editingNode = useMemo(() => nodes.find((n) => n.id === editingNodeId) || null, [nodes, editingNodeId]);

  // ---- Canvas UX: dirty tracking, undo/redo, copy/paste/duplicate ----
  // Refs mirror the latest graph so the history/clipboard callbacks stay stable (no dep churn)
  // yet always operate on current state; calling snapshot() inside an action captures the
  // pre-action graph (refs update after render).
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);
  useEffect(() => { edgesRef.current = edges; }, [edges]);
  useEffect(() => { dirtyRef.current = dirty; }, [dirty]);

  // A node wired as a deep_agent sub-agent (target of a "subagents" edge) is a folded specialist,
  // not a flow node - flag it so ForgeNode hides its now-meaningless in/out flow handles.
  const subagentIds = useMemo(
    () => new Set(edges.filter((e) => e.sourceHandle === "subagents").map((e) => e.target)),
    [edges],
  );
  const flowNodes = useMemo(
    () => (subagentIds.size === 0 ? nodes : nodes.map((n) => (subagentIds.has(n.id) ? { ...n, data: { ...n.data, isSubagent: true } } : n))),
    [nodes, subagentIds],
  );

  // Warn before closing/reloading the tab with unsaved edits.
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { guardCanvasBeforeUnload(dirtyRef.current, e); };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, []);

  const snapshot = useCallback(() => {
    setPast((p) => [...p.slice(-49), { nodes: nodesRef.current, edges: edgesRef.current }]);
    setFuture([]);
  }, []);

  const undo = useCallback(() => {
    setPast((p) => {
      if (!p.length) return p;
      const prev = p[p.length - 1];
      setFuture((f) => [{ nodes: nodesRef.current, edges: edgesRef.current }, ...f].slice(0, 50));
      setNodes(prev.nodes);
      setEdges(prev.edges as any);
      setSelId(null);
      setDirty(true);
      return p.slice(0, -1);
    });
  }, [setNodes, setEdges]);

  const redo = useCallback(() => {
    setFuture((f) => {
      if (!f.length) return f;
      const next = f[0];
      setPast((p) => [...p.slice(-49), { nodes: nodesRef.current, edges: edgesRef.current }]);
      setNodes(next.nodes);
      setEdges(next.edges as any);
      setSelId(null);
      setDirty(true);
      return f.slice(1);
    });
  }, [setNodes, setEdges]);

  const copyNode = useCallback(() => {
    const n = nodesRef.current.find((x) => x.id === selId);
    if (n) clipboardRef.current = { nodeType: n.data.nodeType, config: JSON.parse(JSON.stringify(n.data.config || {})) };
  }, [selId]);

  const pasteNode = useCallback(() => {
    const clip = clipboardRef.current;
    if (!clip) return;
    snapshot();
    const cur = nodesRef.current;
    const id = newNodeId(clip.nodeType, cur.map((n) => n.id));
    const base = cur.find((n) => n.id === selId);
    const pos = base ? { x: base.position.x + 44, y: base.position.y + 44 } : { x: 360 + (cur.length % 4) * 36, y: 160 + (cur.length % 4) * 36 };
    setNodes((nds) => [...nds, { id, type: "forge", position: pos, data: { nodeType: clip.nodeType, config: JSON.parse(JSON.stringify(clip.config)) } }]);
    setSelId(id);
    setDirty(true);
  }, [selId, setNodes, snapshot]);

  const duplicateNode = useCallback(() => {
    const n = nodesRef.current.find((x) => x.id === selId);
    if (!n) return;
    clipboardRef.current = { nodeType: n.data.nodeType, config: JSON.parse(JSON.stringify(n.data.config || {})) };
    pasteNode();
  }, [selId, pasteNode]);

  // Keyboard: Ctrl/Cmd+Z undo · Ctrl/Cmd+Shift+Z (or Ctrl+Y) redo · Ctrl+C/V copy/paste ·
  // Ctrl+D duplicate. Ignored while typing in a form field so text editing keeps its own undo.
  useEffect(() => {
    const isEditable = (el: EventTarget | null) => {
      const t = el as HTMLElement | null;
      if (!t) return false;
      const tag = t.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || !!t.isContentEditable;
    };
    const h = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || isEditable(e.target)) return;
      const k = e.key.toLowerCase();
      if (k === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); }
      else if (k === "y") { e.preventDefault(); redo(); }
      else if (k === "c") { copyNode(); }
      else if (k === "v") { pasteNode(); }
      else if (k === "d") { e.preventDefault(); duplicateNode(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [undo, redo, copyNode, pasteNode, duplicateNode]);

  // LangGraph edges are control flow (data moves via shared state), so connections
  // are permissive: any output -> any input, just not a node to itself. Handle colors
  // remain as a visual hint of the dominant data type.
  const isValidConnection = useCallback(
    (c: Connection | Edge) => {
      if (!c.source || !c.target || c.source === c.target) return false;
      // A sub-agent edge (deep_agent's bottom handle) may only connect to an agent it can call.
      if (c.sourceHandle === "subagents") {
        const tgt = nodes.find((n) => n.id === c.target)?.data.nodeType;
        return tgt === "agent" || tgt === "deep_agent";
      }
      return true;
    },
    [nodes],
  );

  const stripRouterTargets = useCallback((nds: FlowNode[], removedIds: Set<string>): FlowNode[] => {
    if (!removedIds.size) return nds;
    return nds.map((n) => {
      if (n.data.nodeType !== "router") return n;
      const cfg = { ...(n.data.config || {}) };
      const cases = Object.fromEntries(
        Object.entries(cfg.cases || {}).map(([key, target]) => [key, removedIds.has(String(target)) ? "" : target]),
      );
      if (removedIds.has(String(cfg.default))) cfg.default = "";
      return { ...n, data: { ...n.data, config: { ...cfg, cases } } };
    });
  }, []);

  const onNodesChangeSynced = useCallback((changes: NodeChange[]) => {
    const removedIds = new Set(
      changes.filter((c) => c.type === "remove").map((c) => c.id),
    );
    // Snapshot before a keyboard (Backspace/Delete) removal so it can be undone.
    if (removedIds.size) snapshot();
    // Ignore pure selection/measurement churn so the canvas doesn't read as dirty on load.
    if (changes.some((c) => c.type !== "select" && c.type !== "dimensions")) setDirty(true);
    setNodes((nds) => stripRouterTargets(applyNodeChanges(changes, nds) as FlowNode[], removedIds));
  }, [setNodes, stripRouterTargets, snapshot]);

  const syncRouterCaseEdge = useCallback((nodeId: string, key: string, target: string) => {
    const handle = `case:${key}`;
    setEdges((eds) => {
      const rest = eds.filter((e) => !(e.source === nodeId && e.sourceHandle === handle));
      if (!target) return rest;
      return [
        ...rest,
        {
          id: `e-${nodeId}-${key}-${target}`,
          source: nodeId,
          target,
          sourceHandle: handle,
          style: { stroke: IO_COLOR.control || "var(--io-control)", strokeWidth: 2 },
        } as FlowEdge,
      ];
    });
  }, [setEdges]);

  const renameRouterCaseEdges = useCallback((nodeId: string, oldKey: string, newKey: string) => {
    setEdges((eds) => eds.map((e) => (
      e.source === nodeId && e.sourceHandle === `case:${oldKey}`
        ? { ...e, sourceHandle: `case:${newKey}`, id: `e-${nodeId}-${newKey}-${e.target}` }
        : e
    )));
  }, [setEdges]);

  const removeRouterCaseEdges = useCallback((nodeId: string, key: string) => {
    setEdges((eds) => eds.filter((e) => !(e.source === nodeId && e.sourceHandle === `case:${key}`)));
  }, [setEdges]);

  const routerKeyForEdge = useCallback((cfg: Record<string, any>, edge: FlowEdge): string | undefined => {
    if (edge.sourceHandle?.startsWith("case:")) return edge.sourceHandle.slice(5);
    const match = Object.entries(cfg.cases || {}).find(([, target]) => target === edge.target);
    if (match) return match[0];
    if (cfg.default === edge.target) return "__default__";
    return undefined;
  }, []);

  const clearRouterTargetsForRemovedEdges = useCallback((removed: FlowEdge[]) => {
    if (!removed.length) return;
    setNodes((nds) => nds.map((n) => {
      if (n.data.nodeType !== "router") return n;
      const relevant = removed.filter((e) => e.source === n.id);
      if (!relevant.length) return n;
      const cfg = { ...(n.data.config || {}) };
      let cases = { ...(cfg.cases || {}) };
      let changed = false;
      for (const edge of relevant) {
        const key = routerKeyForEdge(cfg, edge);
        if (!key) continue;
        if (key === "__default__") {
          if (cfg.default) { cfg.default = ""; changed = true; }
        } else if (Object.prototype.hasOwnProperty.call(cases, key) && cases[key]) {
          cases = { ...cases, [key]: "" };
          changed = true;
        }
      }
      return changed ? { ...n, data: { ...n.data, config: { ...cfg, cases } } } : n;
    }));
  }, [routerKeyForEdge, setNodes]);

  const onEdgesChangeSynced = useCallback((changes: EdgeChange[]) => {
    const removedIds = new Set(changes.filter((c) => c.type === "remove").map((c) => c.id));
    if (removedIds.size) {
      snapshot();
      clearRouterTargetsForRemovedEdges(edges.filter((e) => removedIds.has(e.id)));
    }
    if (changes.some((c) => c.type !== "select")) setDirty(true);
    setEdges((eds) => applyEdgeChanges(changes, eds) as FlowEdge[]);
  }, [clearRouterTargetsForRemovedEdges, edges, setEdges, snapshot]);

  const removeEdge = useCallback((edge: FlowEdge) => {
    snapshot();
    setDirty(true);
    clearRouterTargetsForRemovedEdges([edge]);
    setEdges((eds) => eds.filter((e) => e.id !== edge.id));
  }, [clearRouterTargetsForRemovedEdges, setEdges, snapshot]);

  const onConnect = useCallback((params: Connection) => {
    if (!isValidConnection(params)) return;
    snapshot();
    setDirty(true);
    const sn = nodes.find((n) => n.id === params.source);
    const tn = nodes.find((n) => n.id === params.target);
    const sp = registry[sn?.data.nodeType || ""]?.output_ports || [];
    const tp = registry[tn?.data.nodeType || ""]?.input_ports || [];
    const fromRouterCase = !!params.sourceHandle?.startsWith("case:") && sn?.data.nodeType === "router";
    const sHandle = params.sourceHandle || (fromRouterCase ? params.sourceHandle : (sp[0]?.id || "out"));
    const tHandle = params.targetHandle || (tp[0]?.id || "in");
    // Dragging from a router's case row wires that case to the target node - the canvas
    // edge is the picture, config.cases/default is what the compiler routes on.
    if (sHandle?.startsWith("case:") && sn?.data.nodeType === "router") {
      const key = sHandle.slice(5);
      setNodes((nds) => nds.map((n) => {
        if (n.id !== params.source) return n;
        const cfg = { ...(n.data.config || {}) };
        if (key === "__default__") cfg.default = params.target;
        else cfg.cases = { ...(cfg.cases || {}), [key]: params.target };
        return { ...n, data: { ...n.data, config: cfg } };
      }));
    }
    const io = (sp.find((p) => p.id === sHandle) || sp[0])?.io_type || "any";
    // Non-blocking type hint: LangGraph edges are control flow (data moves via shared state),
    // so a mismatch is allowed - but surface it so the user knows the port types differ.
    const tio = (tp.find((p) => p.id === tHandle) || tp[0])?.io_type || "any";
    if (!ioCompatible(io, tio)) {
      setConnWarning(`Connected ${io} → ${tio}: the port types differ. It still works (data flows through shared state), just double-check this is intended.`);
      window.setTimeout(() => setConnWarning(null), 6000);
    }
    setEdges((eds) => addEdge(
      { ...params, sourceHandle: sHandle, targetHandle: tHandle, style: { stroke: IO_COLOR[io] || "var(--io-any)", strokeWidth: 2 } },
      fromRouterCase ? eds.filter((e) => !(e.source === params.source && e.sourceHandle === sHandle)) : eds,
    ));
  }, [isValidConnection, nodes, registry, setEdges, setNodes, snapshot]);

  const addNode = useCallback((type: string) => {
    snapshot();
    setDirty(true);
    const id = newNodeId(type, nodes.map((n) => n.id));
    const n = nodes.length;
    const defConfig: Record<string, any> =
      type === "agent" || type === "deep_agent" ? { flavor: type === "deep_agent" ? "deep_agent" : "agent", model: "openai:gpt-4o-mini", middleware: [], tools: [] }
      : type === "router" ? { expression: "intent", cases: {}, default: "" }
      : type === "llm" ? { model: "openai:gpt-4o-mini", prompt: "" }
      : type === "retrieval" ? { top_k: 4, include_docs: true, hybrid: false, rerank: false, include_qa: true, qa_threshold: 0.3, qa_top_k: 3, min_score: 0.18, announce_empty: true }
      : type === "classifier" ? { labels: ["question", "request", "complaint"], output_key: "intent" }
      : {};
    setNodes((nds) => [...nds, { id, type: "forge", position: { x: 360 + (n % 4) * 36, y: 140 + (n % 4) * 36 }, data: { nodeType: type, config: defConfig } }]);
    setSelId(id);
  }, [nodes, setNodes, snapshot]);

  const updateConfig = useCallback((cfg: Record<string, any>) => {
    if (!selId) return;
    setDirty(true);
    setNodes((nds) => nds.map((n) => (n.id === selId ? { ...n, data: { ...n.data, config: cfg } } : n)));
  }, [selId, setNodes]);

  const deleteNode = useCallback((id: string) => {
    snapshot();
    setDirty(true);
    setNodes((nds) => stripRouterTargets(nds.filter((n) => n.id !== id), new Set([id])));
    setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
    setSelId((cur) => (cur === id ? null : cur));
  }, [setNodes, setEdges, stripRouterTargets, snapshot]);

  const saveCanvasState = useCallback(async (nextNodes: FlowNode[], nextEdges: FlowEdge[]) => {
    if (!wf) return;
    setSaveState("saving");
    const persistNodes = stripRunData(nextNodes);
    const executable = canvasToExecutable(persistNodes, nextEdges, { id: wf.id, version: wf.active_version });
    const canvas = { nodes: persistNodes, edges: nextEdges, viewport: { x: 0, y: 0, zoom: 1 } };
    try {
      const res = await api.saveCanvas(project.id, wf.id, canvas, executable);
      // Errors block publish; warnings are wiring smells (e.g. a router whose expression
      // nothing writes) - show both in the tray, tagged by level.
      const warns = ((res as any).warnings || []).map((w: any) => ({ ...w, level: "warning" }));
      setProblems([...res.errors, ...warns]);
      setSaveState(res.valid ? "saved" : "invalid");
      setDirty(false); // canvas is persisted (invalid only blocks publish, not the save)
      if (!res.valid || warns.length) setShowProblems(true);
      setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1500);
    } catch {
      setSaveState("invalid");
    }
  }, [wf, project?.id]);

  const [deployMode, setDeployMode] = useState<"publish" | "save">("publish");
  const [deployMenuOpen, setDeployMenuOpen] = useState(false);
  const [publishState, setPublishState] = useState<"idle" | "publishing" | "published" | "error">("idle");
  const deployMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!deployMenuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (deployMenuRef.current && !deployMenuRef.current.contains(e.target as Node)) {
        setDeployMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [deployMenuOpen]);

  useEffect(() => {
    const onInjectTrigger = () => {
      setSidebarTab("debug");
      setEditingNodeId(null);
    };
    window.addEventListener("alberto-inject-trigger", onInjectTrigger);
    return () => window.removeEventListener("alberto-inject-trigger", onInjectTrigger);
  }, []);

  const save = useCallback(async () => {
    await saveCanvasState(nodes, edges);
  }, [saveCanvasState, nodes, edges]);

  const deployOrSave = useCallback(async (forcedMode?: "publish" | "save") => {
    const mode = forcedMode || deployMode;
    if (!wf || !project?.id) return;
    setSaveState("saving");
    if (mode === "publish") setPublishState("publishing");
    const persistNodes = stripRunData(nodes);
    const executable = canvasToExecutable(persistNodes, edges, { id: wf.id, version: wf.active_version });
    const canvas = { nodes: persistNodes, edges, viewport: { x: 0, y: 0, zoom: 1 } };
    try {
      const res = await api.saveCanvas(project.id, wf.id, canvas, executable);
      const warns = ((res as any).warnings || []).map((w: any) => ({ ...w, level: "warning" }));
      setProblems([...res.errors, ...warns]);
      setDirty(false);
      if (!res.valid) {
        setSaveState("invalid");
        if (mode === "publish") {
          setPublishState("error");
          setTimeout(() => setPublishState("idle"), 2400);
        }
        setShowProblems(true);
        return;
      }
      setSaveState("saved");
      setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1500);

      if (mode === "publish") {
        try {
          await api.publishWorkflow(project.id, wf.id);
          setPublishState("published");
          setTimeout(() => setPublishState("idle"), 1600);
        } catch {
          setPublishState("error");
          setTimeout(() => setPublishState("idle"), 2400);
        }
      }
    } catch {
      setSaveState("invalid");
      if (mode === "publish") {
        setPublishState("error");
        setTimeout(() => setPublishState("idle"), 2400);
      }
    }
  }, [wf, project?.id, nodes, edges, deployMode]);

  // Register the canvas flush with the parent so external calls save first.
  useEffect(() => {
    onRegisterFlush?.(save);
    return () => onRegisterFlush?.(null);
  }, [onRegisterFlush, save]);

  const backGuarded = useCallback(async () => {
    if (dirtyRef.current) { try { await save(); } catch { /* leave anyway */ } }
    onBack();
  }, [save, onBack]);

  const renameWorkflowTitle = useCallback(async (name: string) => {
    if (!wf || !project?.id || name === wf.name) return;
    const previous = wf;
    const optimistic = { ...wf, name };
    setWf(optimistic);
    onWorkflowChange?.(optimistic);
    try {
      const updated = await api.updateWorkflow(project.id, wf.id, { name });
      setWf(updated);
      onWorkflowChange?.(updated);
    } catch {
      setWf(previous);
      onWorkflowChange?.(previous);
    }
  }, [wf, project?.id, onWorkflowChange]);

  const renameNodeId = useCallback((nodeId: string, rawId: string) => {
    const nextId = rawId.trim().replace(/\s+/g, "_").replace(/[^a-zA-Z0-9_-]/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "");
    if (!nextId || nextId === nodeId || nodes.some((n) => n.id === nextId)) return;
    const nextNodes = nodes.map((n) => {
      const data = n.data.nodeType === "router"
        ? {
            ...n.data,
            config: {
              ...(n.data.config || {}),
              cases: Object.fromEntries(
                Object.entries(n.data.config?.cases || {}).map(([key, target]) => [
                  key,
                  String(target) === nodeId ? nextId : target,
                ]),
              ),
              default: String(n.data.config?.default || "") === nodeId ? nextId : n.data.config?.default,
            },
          }
        : n.data;
      return n.id === nodeId ? { ...n, id: nextId, data } : { ...n, data };
    });
    const nextEdges = edges.map((e) => ({
      ...e,
      source: e.source === nodeId ? nextId : e.source,
      target: e.target === nodeId ? nextId : e.target,
    }));
    setNodes(nextNodes);
    setEdges(nextEdges);
    setSelId((cur) => (cur === nodeId ? nextId : cur));
    void saveCanvasState(nextNodes, nextEdges);
  }, [nodes, edges, saveCanvasState, setNodes, setEdges]);

  const clearRunDebug = useCallback(() => {
    setNodes((nds) => stripRunData(nds));
    setRunning(false);
  }, [setNodes]);

  const markRunNode = useCallback((nodeId: string, status?: "idle" | "running" | "done" | "error", output?: any) => {
    setNodes((nds) => nds.map((n) => (
      n.id === nodeId
        ? { ...n, data: { ...n.data, status, debug: { ...(n.data.debug || {}), ...(output !== undefined ? { output } : {}) } } }
        : n
    )));
  }, [setNodes]);

  const applyFinalDebug = useCallback((debugNodes: Record<string, any> = {}) => {
    setNodes((nds) => nds.map((n) => {
      const debug = debugNodes[n.id];
      return debug ? { ...n, data: { ...n.data, debug: { ...(n.data.debug || {}), ...debug } } } : n;
    }));
  }, [setNodes]);

  const closeTestPanel = useCallback(() => {
    setSidebarTab("info");
    clearRunDebug();
  }, [clearRunDebug]);

  const startSidebarResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = sidebarWidth;
    const onMouseMove = (ev: MouseEvent) => {
      const delta = startX - ev.clientX;
      const next = Math.max(260, Math.min(window.innerWidth * 0.65, startW + delta));
      setSidebarWidth(Math.round(next));
    };
    const onMouseUp = () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }, [sidebarWidth]);

  const startTrayResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = trayWidth;
    const onMouseMove = (ev: MouseEvent) => {
      const delta = startX - ev.clientX;
      const next = Math.max(340, Math.min(window.innerWidth * 0.85, startW + delta));
      setTrayWidth(Math.round(next));
    };
    const onMouseUp = () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }, [trayWidth]);

  const palette = useMemo(() => {
    const groups: Record<string, NodeType[]> = {};
    Object.values(registry).forEach((nt) => {
      if (nt.type === "start" || nt.type === "end") return;
      (groups[nt.category] = groups[nt.category] || []).push(nt);
    });
    return groups;
  }, [registry]);

  return (
    <div className="col" style={{ flex: 1, minHeight: 0 }}>
      {/* toolbar */}
      <div className="row spread" style={{ padding: "10px 16px", borderBottom: "1px solid var(--line)", background: "var(--bg-1)" }}>
        <div className="row gap2">
          <button className="iconbtn" onClick={backGuarded}><Icon name="chevleft" size={18} /></button>
          <Tile icon="workflows" color="var(--accent)" size={28} />
          <div style={{ minWidth: 0 }}>
            <EditableName value={wf?.name} fallback="Workflow" className="t-h2 truncate" inputStyle={{ height: 28, minWidth: 220 }} onCommit={renameWorkflowTitle} />
            <div className="fg-2 t-caption mono">{nodes.length} nodes · {edges.length} edges</div>
          </div>
        </div>
        <div className="row gap2">
          <div className="row" style={{ gap: 1 }}>
            <button className="iconbtn" title="Undo (Ctrl+Z)" onClick={undo} disabled={!past.length}><Icon name="undo" size={16} /></button>
            <button className="iconbtn" title="Redo (Ctrl+Shift+Z)" onClick={redo} disabled={!future.length}><Icon name="redo" size={16} /></button>
          </div>
          {problems.length > 0 && (
            <button className="btn btn-danger btn-sm" onClick={() => setShowProblems((s) => !s)}><Icon name="validate" size={14} />{problems.length} problem{problems.length === 1 ? "" : "s"}</button>
          )}
          <VersionHistory entityType="workflow" entityId={wf?.id} entityLabel={wf?.name} onRestored={() => setReloadKey((k) => k + 1)} />

          {/* Node-RED style Deploy / Save split button */}
          <div ref={deployMenuRef} className="row" style={{ position: "relative", gap: 0 }}>
            <button
              className="btn btn-primary btn-sm"
              style={{
                borderTopRightRadius: 0,
                borderBottomRightRadius: 0,
                borderRight: "1px solid rgba(255,255,255,0.25)",
              }}
              onClick={() => void deployOrSave()}
              disabled={saveState === "saving" || publishState === "publishing"}
            >
              <Icon
                name={
                  publishState === "published" || saveState === "saved"
                    ? "check"
                    : deployMode === "publish"
                    ? "bolt"
                    : "save"
                }
                size={14}
              />
              {publishState === "publishing"
                ? "Deploying…"
                : publishState === "published"
                ? "Deployed"
                : publishState === "error"
                ? "Fix errors"
                : saveState === "saving"
                ? "Saving…"
                : saveState === "saved"
                ? "Saved"
                : saveState === "invalid"
                ? "Invalid"
                : deployMode === "publish"
                ? "Deploy"
                : "Save"}
              {dirty && saveState === "idle" && publishState === "idle" && (
                <span
                  title="Unsaved changes"
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: "rgba(255,255,255,0.9)",
                    marginLeft: 4,
                  }}
                />
              )}
            </button>
            <button
              className="btn btn-primary btn-sm"
              style={{
                borderTopLeftRadius: 0,
                borderBottomLeftRadius: 0,
                padding: "0 6px",
              }}
              onClick={() => setDeployMenuOpen((o) => !o)}
              title="Deploy options"
            >
              <Icon name="chevdown" size={12} />
            </button>
            {deployMenuOpen && (
              <div
                className="card col gap1"
                style={{
                  position: "absolute",
                  top: "100%",
                  right: 0,
                  marginTop: 4,
                  minWidth: 175,
                  padding: 4,
                  zIndex: 100,
                  boxShadow: "var(--sh-pop)",
                  background: "var(--bg-2)",
                  border: "1px solid var(--line)",
                }}
              >
                <button
                  type="button"
                  className="row gap2"
                  style={{
                    padding: "6px 8px",
                    borderRadius: 4,
                    background: deployMode === "publish" ? "var(--bg-3)" : "transparent",
                    border: "none",
                    cursor: "pointer",
                    textAlign: "left",
                    width: "100%",
                    color: "var(--fg-1)",
                  }}
                  onClick={() => {
                    setDeployMode("publish");
                    setDeployMenuOpen(false);
                    void deployOrSave("publish");
                  }}
                >
                  <Icon name="bolt" size={14} style={{ color: "var(--accent)" }} />
                  <div>
                    <div className="t-body-sm" style={{ fontWeight: 600 }}>Deploy (Full)</div>
                    <div className="t-caption fg-2">Save &amp; publish live triggers</div>
                  </div>
                </button>
                <button
                  type="button"
                  className="row gap2"
                  style={{
                    padding: "6px 8px",
                    borderRadius: 4,
                    background: deployMode === "save" ? "var(--bg-3)" : "transparent",
                    border: "none",
                    cursor: "pointer",
                    textAlign: "left",
                    width: "100%",
                    color: "var(--fg-1)",
                  }}
                  onClick={() => {
                    setDeployMode("save");
                    setDeployMenuOpen(false);
                    void deployOrSave("save");
                  }}
                >
                  <Icon name="save" size={14} style={{ color: "var(--fg-2)" }} />
                  <div>
                    <div className="t-body-sm" style={{ fontWeight: 600 }}>Save Draft</div>
                    <div className="t-caption fg-2">Save without publishing</div>
                  </div>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "stretch", flex: 1, minHeight: 0, position: "relative", overflow: "hidden" }}>
        {/* palette */}
        <div className="scroll-y" style={{ width: 200, flex: "none", borderRight: "1px solid var(--line)", background: "var(--bg-1)", padding: 10 }}>
          <input className="input" placeholder="Search nodes…" value={paletteQuery} onChange={(e) => setPaletteQuery(e.target.value)} style={{ marginBottom: 10 }} />
          {Object.entries(palette).map(([cat, items]) => {
            const filtered = items.filter((it) => it.label.toLowerCase().includes(paletteQuery.toLowerCase()) || it.type.includes(paletteQuery.toLowerCase()));
            if (!filtered.length) return null;
            return (
              <div key={cat} style={{ marginBottom: 12 }}>
                <div className="t-micro" style={{ marginBottom: 6 }}>{cat.replace("_", " & ")}</div>
                <div className="col gap1">
                  {filtered.map((it) => {
                    const meta = NODE_META[it.type] || { icon: "n_agent", color: "var(--fg-2)" };
                    return (
                      <button key={it.type} className="row gap2" onClick={() => addNode(it.type)}
                        style={{ padding: "7px 8px", borderRadius: 7, border: "1px solid var(--line)", background: "var(--bg-2)", cursor: "pointer", textAlign: "left" }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.borderColor = meta.color;
                          const r = e.currentTarget.getBoundingClientRect();
                          setPaletteTip({ type: it.type, top: r.top, left: r.right + 10 });
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.borderColor = "var(--line)";
                          setPaletteTip(null);
                        }}>
                        <Icon name={meta.icon} size={15} style={{ color: meta.color, flexShrink: 0 }} />
                        <span className="t-body-sm truncate">{it.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {/* Connector actions are deliberately NOT listed here. They are ordinary tools, and
              the palette's job is NODE TYPES - one Tool Call node reaches any of them through
              its picker. Enumerating every installed action turned a fixed list into one that
              grew with each connector, pushing the actual node types off the screen. */}
        </div>

        {/* palette hover help card */}
        {paletteTip && NODE_HELP[paletteTip.type] && (() => {
          const help = NODE_HELP[paletteTip.type];
          const meta = NODE_META[paletteTip.type] || { icon: "n_agent", color: "var(--fg-2)", label: paletteTip.type };
          return (
            <div className="card" style={{
              position: "fixed", left: paletteTip.left, top: Math.max(60, Math.min(paletteTip.top, (typeof window !== "undefined" ? window.innerHeight : 800) - 210)),
              width: 290, zIndex: 90, pointerEvents: "none", padding: 12, boxShadow: "var(--sh-pop)",
            }}>
              <div className="row gap2" style={{ marginBottom: 6 }}>
                <Icon name={meta.icon} size={15} style={{ color: meta.color }} />
                <span className="t-h3">{meta.label}</span>
                <span className="typechip">{paletteTip.type}</span>
              </div>
              <div className="t-body-sm fg-1" style={{ lineHeight: "19px", marginBottom: 8 }}>{help.what}</div>
              <div style={{ background: "var(--bg-3)", border: "1px solid var(--line)", borderRadius: 7, padding: "7px 9px" }}>
                <div className="t-micro" style={{ marginBottom: 3 }}>Example</div>
                <div className="mono-sm fg-1" style={{ fontSize: 11.5, lineHeight: "17px", whiteSpace: "pre-wrap" }}>{help.example}</div>
              </div>
            </div>
          );
        })()}

        {/* canvas */}
        <div className="grow forge-canvas" style={{ position: "relative", minWidth: 0, height: "100%" }}>
          {/* Hide React Flow's native edge layer - we draw connections via EdgeOverlay. */}
          <style>{`.forge-canvas .react-flow__edge { display: none; }`}</style>
          <NodeTypesContext.Provider value={registry}>
            {/* Wait for the node-type registry before mounting React Flow so nodes render
                WITH their handles on first paint - otherwise React Flow measures handle-less
                nodes and loaded edges never get drawn (their handle bounds stay empty). */}
            {registryReady ? (
              <ReactFlow
                style={{ width: "100%", height: "100%" }}
                nodes={flowNodes} edges={edges} nodeTypes={nodeTypes}
                onNodesChange={onNodesChangeSynced} onEdgesChange={onEdgesChangeSynced} onConnect={onConnect}
                onNodeDragStart={() => snapshot()}
                isValidConnection={isValidConnection as any}
                onNodeClick={(_, n) => {
                  setSelId(n.id);
                  setEditingNodeId(n.id);
                }}
                onNodeDoubleClick={(_, n) => {
                  setSelId(n.id);
                  setEditingNodeId(n.id);
                }}
                onPaneClick={() => {
                  setSelId(null);
                  setEditingNodeId(null);
                }}
                deleteKeyCode={["Backspace", "Delete"]}
                fitView proOptions={{ hideAttribution: true }} defaultEdgeOptions={{ style: { strokeWidth: 2 } }}
              >
                <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="var(--canvas-grid)" />
                <Controls />
                <MiniMap pannable zoomable style={{ background: "var(--bg-1)" }} nodeColor={(n) => NODE_META[(n.data as any)?.nodeType]?.color || "var(--fg-2)"} />
                <EdgeOverlay nodes={flowNodes} edges={edges} selectedNodeId={selId} onRemove={removeEdge} />
              </ReactFlow>
            ) : (
              <div className="col center" style={{ width: "100%", height: "100%", color: "var(--fg-2)" }}>Loading canvas…</div>
            )}
          </NodeTypesContext.Provider>

          {connWarning && (
            <div className="card fade-in" style={{ position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)", maxWidth: 460, padding: "8px 12px", boxShadow: "var(--sh-2)", borderColor: "var(--warn)", zIndex: 5 }}>
              <div className="row gap2" style={{ alignItems: "flex-start" }}>
                <Icon name="validate" size={14} style={{ color: "var(--warn)", flexShrink: 0, marginTop: 2 }} />
                <span className="t-caption fg-1" style={{ flex: 1 }}>{connWarning}</span>
                <button className="iconbtn" style={{ width: 20, height: 20 }} onClick={() => setConnWarning(null)}><Icon name="x" size={12} /></button>
              </div>
            </div>
          )}

          {showProblems && problems.length > 0 && (
            <div className="card" style={{ position: "absolute", left: 12, right: 12, bottom: 12, maxHeight: 160, overflow: "auto", boxShadow: "var(--sh-pop)" }}>
              <div className="row spread" style={{ padding: "8px 12px", borderBottom: "1px solid var(--line)" }}>
                <div className="t-h3" style={{ color: "var(--err)" }}>Problems</div>
                <button className="iconbtn" onClick={() => setShowProblems(false)}><Icon name="x" size={15} /></button>
              </div>
              <div className="col" style={{ padding: 6 }}>
                {problems.map((p: any, i) => (
                  <div key={i} className="row gap2" style={{ padding: "5px 8px", alignItems: "flex-start" }}>
                    <span className="mono-sm" style={{ color: p.level === "warning" ? "var(--warn)" : "var(--err)", flexShrink: 0 }}>
                      {p.level === "warning" ? "⚠ " : ""}{p.pointer}
                    </span>
                    <span className="t-caption fg-1">{p.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Permanent Right Sidebar (Info / Debug) */}
        <div
          className="col"
          style={{
            width: sidebarWidth,
            flex: "none",
            borderLeft: "1px solid var(--line)",
            background: "var(--bg-1)",
            minHeight: 0,
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
            position: "relative",
          }}
        >
          {/* Draggable resize handle */}
          <div
            onMouseDown={startSidebarResize}
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 0,
              width: 5,
              cursor: "col-resize",
              zIndex: 25,
            }}
            title="Drag to resize sidebar"
          />
          {/* Permanent Sidebar Tabs Header */}
          <div
            className="row spread"
            style={{
              padding: "6px 10px",
              borderBottom: "1px solid var(--line)",
              background: "var(--bg-2)",
              flex: "none",
              alignItems: "center",
            }}
          >
            <div className="row gap1" style={{ alignItems: "center" }}>
              <button
                type="button"
                className={`btn btn-xs ${sidebarTab === "info" ? "btn-secondary" : "btn-ghost"}`}
                onClick={() => setSidebarTab("info")}
                style={{ height: 26, fontSize: 11.5, gap: 5 }}
              >
                <Icon name="info" size={13} style={{ color: sidebarTab === "info" ? "var(--accent)" : "var(--fg-2)" }} />
                Info
              </button>
              <button
                type="button"
                className={`btn btn-xs ${sidebarTab === "debug" ? "btn-secondary" : "btn-ghost"}`}
                onClick={() => setSidebarTab("debug")}
                style={{ height: 26, fontSize: 11.5, gap: 5 }}
                title="Run Workflow"
                aria-label="Debug Panel"
              >
                <Icon name="bug" size={13} style={{ color: sidebarTab === "debug" ? "var(--accent)" : "var(--fg-2)" }} />
                Debug
                {running && (
                  <span
                    className="pill"
                    style={{
                      fontSize: 8.5,
                      background: "var(--accent)",
                      color: "var(--fg-on-accent)",
                      padding: "0 4px",
                      marginLeft: 2,
                    }}
                  >
                    ●
                  </span>
                )}
              </button>
            </div>
          </div>

          {/* Sidebar Tab Content */}
          {/* Sidebar Tab Content */}
          <div className="col" style={{ flex: 1, minHeight: 0, position: "relative", overflow: "hidden" }}>
            {/* Debug panel kept permanently mounted so event listeners and execution logs stay alive */}
            <div
              style={{
                display: sidebarTab === "debug" ? "flex" : "none",
                flex: 1,
                minHeight: 0,
                height: "100%",
                flexDirection: "column",
              }}
            >
              {wf && (
                <WorkflowTestPanel
                  project={project}
                  workflow={wf}
                  hideControls={true}
                  running={running}
                  onRunningChange={setRunning}
                  onBeforeRun={save}
                  onClose={() => setSidebarTab("info")}
                  onResetRun={clearRunDebug}
                  onNodeStep={markRunNode}
                  onFinalDebug={applyFinalDebug}
                />
              )}
            </div>

            {/* Info panel */}
            <div
              className="scroll-y"
              style={{
                display: sidebarTab === "info" ? "flex" : "none",
                flex: 1,
                minHeight: 0,
                height: "100%",
                flexDirection: "column",
              }}
            >
              {selected ? (
                <div className="col gap3" style={{ padding: 14 }}>
                  <div className="row spread" style={{ alignItems: "center" }}>
                    <div className="row gap2" style={{ alignItems: "center", minWidth: 0 }}>
                      <Tile
                        icon={NODE_META[selected.data.nodeType]?.icon || "n_agent"}
                        color={NODE_META[selected.data.nodeType]?.color || "var(--accent)"}
                        size={26}
                      />
                      <div style={{ minWidth: 0 }}>
                        <div className="t-h3 truncate">{selected.data.config?.name || NODE_META[selected.data.nodeType]?.label || selected.id}</div>
                        <div className="mono-sm fg-2 truncate">{selected.id}</div>
                      </div>
                    </div>
                    <span className="typechip">{selected.data.nodeType}</span>
                  </div>

                  {NODE_HELP[selected.data.nodeType]?.what && (
                    <div className="t-caption fg-1" style={{ lineHeight: "18px" }}>
                      {NODE_HELP[selected.data.nodeType].what}
                    </div>
                  )}

                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setEditingNodeId(selected.id)}
                    style={{ width: "100%", justifyContent: "center", gap: 6, marginTop: 4 }}
                  >
                    <Icon name="edit" size={13} /> Edit Node Configuration
                  </button>

                  <div className="card col gap2" style={{ padding: 10 }}>
                    <div className="t-micro">Node Information</div>
                    <div className="row spread mono-sm">
                      <span className="fg-2">Type</span>
                      <span>{selected.data.nodeType}</span>
                    </div>
                    <div className="row spread mono-sm">
                      <span className="fg-2">ID</span>
                      <span className="truncate" style={{ maxWidth: 160 }}>{selected.id}</span>
                    </div>
                    {selected.data.config?.topic && (
                      <div className="row spread mono-sm">
                        <span className="fg-2">Topic</span>
                        <span className="truncate" style={{ maxWidth: 160 }}>{selected.data.config.topic}</span>
                      </div>
                    )}
                    {selected.data.config?.model && (
                      <div className="row spread mono-sm">
                        <span className="fg-2">Model</span>
                        <span className="truncate" style={{ maxWidth: 160 }}>{selected.data.config.model}</span>
                      </div>
                    )}
                  </div>

                  {/* Connections info */}
                  <div className="card col gap2" style={{ padding: 10 }}>
                    <div className="t-micro">Connections</div>
                    <div className="mono-sm">
                      <span className="fg-2">Upstream: </span>
                      <span>
                        {edges.filter((e) => e.target === selected.id).length
                          ? edges
                              .filter((e) => e.target === selected.id)
                              .map((e) => e.source)
                              .join(", ")
                          : "None (entry point)"}
                      </span>
                    </div>
                    <div className="mono-sm" style={{ marginTop: 4 }}>
                      <span className="fg-2">Downstream: </span>
                      <span>
                        {edges.filter((e) => e.source === selected.id).length
                          ? edges
                              .filter((e) => e.source === selected.id)
                              .map((e) => e.target)
                              .join(", ")
                          : "None (terminal node)"}
                      </span>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="col gap3" style={{ padding: 14 }}>
                  <div className="t-micro">Workflow Info</div>
                  <div className="t-h2 truncate">{wf?.name || "Workflow"}</div>
                  <div className="fg-2 t-caption mono">
                    {nodes.length} nodes · {edges.length} edges
                  </div>
                  <div className="card" style={{ padding: 12 }}>
                    <div className="t-caption fg-2">Shared State Schema</div>
                    <div className="mono-sm" style={{ marginTop: 4 }}>
                      payload · messages · intent
                    </div>
                  </div>
                  <div className="field-help" style={{ marginTop: 8 }}>
                    Click or double-click any node to open its configuration tray. Click <b>Inject</b> on an Inject node to run the workflow.
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Node-RED style slide-in Editor Tray (opens on top of permanent sidebar) */}
        {editingNode && (
          <div
            className="col"
            style={{
              position: "absolute",
              top: 0,
              right: 0,
              bottom: 0,
              width: trayWidth,
              maxWidth: "100%",
              background: "var(--bg-1)",
              borderLeft: "1px solid var(--line)",
              boxShadow: "var(--sh-pop)",
              zIndex: 70,
              display: "flex",
              flexDirection: "column",
            }}
          >
            {/* Draggable resize handle for Editor Tray */}
            <div
              onMouseDown={startTrayResize}
              style={{
                position: "absolute",
                left: 0,
                top: 0,
                bottom: 0,
                width: 6,
                cursor: "col-resize",
                zIndex: 80,
              }}
              title="Drag to resize editor tray"
            />
            {/* Tray Header */}
            <div
              className="row spread"
              style={{
                padding: "10px 14px",
                borderBottom: "1px solid var(--line)",
                background: "var(--bg-2)",
                flex: "none",
                alignItems: "center",
              }}
            >
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setEditingNodeId(null)}
              >
                Cancel
              </button>
              <div className="row gap2" style={{ alignItems: "center", minWidth: 0 }}>
                <Icon
                  name={NODE_META[editingNode.data.nodeType]?.icon || "n_agent"}
                  size={16}
                  style={{ color: NODE_META[editingNode.data.nodeType]?.color || "var(--accent)" }}
                />
                <span className="t-h3 truncate" style={{ maxWidth: 200 }}>
                  {editingNode.data.config?.name || NODE_META[editingNode.data.nodeType]?.label || editingNode.id}
                </span>
              </div>
              <div className="row gap1" style={{ alignItems: "center" }}>
                <button
                  type="button"
                  className="iconbtn"
                  onClick={() => {
                    deleteNode(editingNode.id);
                    setEditingNodeId(null);
                  }}
                  title="Delete node"
                >
                  <Icon name="trash" size={14} />
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => setEditingNodeId(null)}
                >
                  Done
                </button>
              </div>
            </div>

            {/* Tray Body */}
            <div className="scroll-y" style={{ flex: 1, padding: 16 }}>
              <NodeInspector
                node={editingNode}
                nodes={nodes}
                edges={edges}
                tools={tools}
                toolSets={toolSets}
                agents={agents}
                mcpServers={mcpServers}
                components={components}
                dynamic={{ kb_folders: kbFolders, qa_kinds: qaKinds }}
                onChange={updateConfig}
                onRename={renameNodeId}
                onDelete={(id) => {
                  deleteNode(id);
                  setEditingNodeId(null);
                }}
                onRouterCaseTarget={syncRouterCaseEdge}
                onRouterCaseRename={renameRouterCaseEdges}
                onRouterCaseRemove={removeRouterCaseEdges}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function TransformForm({
  c,
  set,
  upstreamSources,
}: {
  c: Record<string, any>;
  set: (p: Record<string, any>) => void;
  upstreamSources?: UpstreamSource[];
}) {
  const [mode, setMode] = useState<"simple" | "advanced">(c.operations ? "simple" : "advanced");
  const ops: Array<{ type: string; target: string; value?: any; from?: string; to?: string }> = Array.isArray(c.operations) ? c.operations : [];

  const addOp = () => {
    const next = [...ops, { type: "set", target: "payload.status", value: "active" }];
    set({ operations: next });
  };

  const updateOp = (idx: number, patch: Partial<(typeof ops)[0]>) => {
    const next = ops.map((op, i) => (i === idx ? { ...op, ...patch } : op));
    set({ operations: next });
  };

  const removeOp = (idx: number) => {
    const next = ops.filter((_, i) => i !== idx);
    set({ operations: next });
  };

  return (
    <div className="col gap3">
      <div className="row spread" style={{ borderBottom: "1px solid var(--line)", paddingBottom: 6 }}>
        <span className="t-micro">Transform Mode</span>
        <div className="row gap1">
          <button
            type="button"
            className="chip"
            style={{
              cursor: "pointer",
              background: mode === "simple" ? "var(--accent)" : "var(--bg-3)",
              color: mode === "simple" ? "var(--fg-on-accent)" : "var(--fg-1)",
              borderColor: mode === "simple" ? "var(--accent)" : "var(--line)",
            }}
            onClick={() => {
              setMode("simple");
              if (!c.operations) {
                set({ operations: [{ type: "set", target: "payload.status", value: "active" }] });
              }
            }}
          >
            Simple (Rules)
          </button>
          <button
            type="button"
            className="chip"
            style={{
              cursor: "pointer",
              background: mode === "advanced" ? "var(--accent)" : "var(--bg-3)",
              color: mode === "advanced" ? "var(--fg-on-accent)" : "var(--fg-1)",
              borderColor: mode === "advanced" ? "var(--accent)" : "var(--line)",
            }}
            onClick={() => setMode("advanced")}
          >
            Advanced (JMESPath)
          </button>
        </div>
      </div>

      {mode === "simple" ? (
        <div className="col gap2">
          <div className="row spread">
            <span className="t-body-sm fg-2">Operations</span>
            <button type="button" className="btn btn-xs btn-secondary" onClick={addOp}>
              <Icon name="plus" size={12} /> Add Operation
            </button>
          </div>
          {ops.length === 0 ? (
            <div className="field-help">No operations defined. Click "Add Operation" to configure field rules.</div>
          ) : (
            <div className="col gap2">
              {ops.map((op, i) => (
                <div key={i} className="card col gap1" style={{ padding: 8, background: "var(--bg-3)", border: "1px solid var(--line)" }}>
                  <div className="row spread">
                    <select
                      className="select"
                      style={{ height: 26, fontSize: 11, width: 100 }}
                      value={op.type}
                      onChange={(e) => updateOp(i, { type: e.target.value })}
                    >
                      <option value="set">Set</option>
                      <option value="change">Change</option>
                      <option value="move">Move</option>
                      <option value="rename">Rename</option>
                      <option value="delete">Delete</option>
                    </select>
                    <button type="button" className="iconbtn" style={{ width: 20, height: 20 }} onClick={() => removeOp(i)}>
                      <Icon name="trash" size={12} />
                    </button>
                  </div>
                  <div className="row gap1" style={{ alignItems: "center" }}>
                    <input
                      className="input mono"
                      style={{ height: 26, fontSize: 11, flex: 1 }}
                      placeholder="property (e.g. payload.item)"
                      value={op.target || ""}
                      onChange={(e) => updateOp(i, { target: e.target.value })}
                    />
                    <VariablePicker
                      sources={upstreamSources}
                      onSelect={(path) => updateOp(i, { target: path })}
                    />
                  </div>
                  {op.type !== "delete" && (
                    <div className="row gap1" style={{ alignItems: "center" }}>
                      <span className="fg-2 mono-sm" style={{ fontSize: 10, width: 36 }}>to:</span>
                      <input
                        className="input mono"
                        style={{ height: 26, fontSize: 11, flex: 1 }}
                        placeholder={op.type === "rename" || op.type === "move" ? "new property name" : "value or expression"}
                        value={op.value !== undefined ? String(op.value) : (op.to || "")}
                        onChange={(e) => {
                          if (op.type === "rename" || op.type === "move") {
                            updateOp(i, { to: e.target.value });
                          } else {
                            updateOp(i, { value: e.target.value });
                          }
                        }}
                      />
                      <VariablePicker
                        sources={upstreamSources}
                        onSelect={(path) => {
                          if (op.type === "rename" || op.type === "move") {
                            updateOp(i, { to: path });
                          } else {
                            updateOp(i, { value: `{{${path}}}` });
                          }
                        }}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <FieldsForm specs={NODE_FIELDS.transform} config={c} onPatch={set} upstreamSources={upstreamSources} />
      )}
    </div>
  );
}

function NodeInspector({
  node,
  nodes,
  edges,
  tools,
  toolSets,
  agents,
  mcpServers,
  components,
  dynamic,
  onChange,
  onRename,
  onDelete,
  onRouterCaseTarget,
  onRouterCaseRename,
  onRouterCaseRemove,
}: {
  node: FlowNode;
  nodes: FlowNode[];
  edges: FlowEdge[];
  tools: Tool[];
  toolSets: ToolSet[];
  agents: Agent[];
  mcpServers: McpClientT[];
  components: ComponentT[];
  dynamic?: Record<string, string[]>;
  onChange: (c: Record<string, any>) => void;
  onRename: (nodeId: string, name: string) => void;
  onDelete: (id: string) => void;
  onRouterCaseTarget: (nodeId: string, key: string, target: string) => void;
  onRouterCaseRename: (nodeId: string, oldKey: string, newKey: string) => void;
  onRouterCaseRemove: (nodeId: string, key: string) => void;
}) {
  const type = node.data.nodeType;
  const c = node.data.config || {};
  const set = (patch: Record<string, any>) => onChange({ ...c, ...patch });
  const meta = NODE_META[type] || { label: type, color: "var(--fg-2)", icon: "n_agent" };
  const nodeIds = nodes.map((n) => n.id).filter((id) => id !== node.id);
  const upstreamSources = useMemo(() => getUpstreamOutputs(node.id, nodes, edges), [node.id, nodes, edges]);

  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="row spread">
        <div className="row gap2" style={{ minWidth: 0 }}>
          <Tile icon={meta.icon} color={meta.color} size={28} />
          <div style={{ minWidth: 0 }}>
            <div className="t-h2 truncate">{meta.label}</div>
            <EditableName value={node.id} fallback={node.id} className="mono-sm fg-2 truncate" inputClassName="input mono" inputStyle={{ height: 26, maxWidth: 190 }} onCommit={(name) => onRename(node.id, name)} />
          </div>
        </div>
        <button className="btn btn-danger btn-sm" onClick={() => onDelete(node.id)}><Icon name="trash" size={14} />Delete</button>
      </div>

      {(type === "agent" || type === "deep_agent") && <AgentConfig config={c} onChange={onChange} tools={tools} toolSets={toolSets} agents={agents} mcpServers={mcpServers} components={components} folders={dynamic?.kb_folders || []} kinds={dynamic?.qa_kinds || []} upstreamSources={upstreamSources} />}

      {type === "retrieval" && <RetrievalForm c={c} set={set} folders={dynamic?.kb_folders || []} kinds={dynamic?.qa_kinds || []} />}

      {(type === "router" || type === "switch") && (
        <RouterForm
          nodeId={node.id}
          c={c}
          set={set}
          nodeIds={nodeIds}
          nodes={nodes}
          upstreamSources={upstreamSources}
          onCaseTarget={onRouterCaseTarget}
          onCaseRename={onRouterCaseRename}
          onCaseRemove={onRouterCaseRemove}
        />
      )}

      {type === "llm" && (
        <div className="col gap3">
          <Field label="Model"><ModelSelect value={c.model || ""} onChange={(v) => set({ model: v })} /></Field>
          <Field label="Prompt" help="The instruction the model runs on the incoming message."><textarea className="textarea" rows={4} value={c.prompt || ""} onChange={(e) => set({ prompt: e.target.value })} /></Field>
        </div>
      )}

      {type === "tool_call" && (
        <div className="col gap3">
          <Field label="Tool" help={tools.length ? "Which project tool to invoke." : "No tools in this project yet - add them on the Tools or Connectors screen."}>
            <ToolPicker tools={tools} toolSets={toolSets} value={c.tool_id || ""} onChange={(v) => set({ tool_id: v || undefined })} />
          </Field>
          <Field label="Output state key" help="Where the tool's result is written in state."><input className="input mono" value={c.output_key ?? ""} placeholder="result" onChange={(e) => set({ output_key: e.target.value || undefined })} /></Field>
        </div>
      )}

      {type === "transform" || type === "change" ? (
        <TransformForm c={c} set={set} upstreamSources={upstreamSources} />
      ) : NODE_FIELDS[type] ? (
        <FieldsForm specs={NODE_FIELDS[type]} config={c} onPatch={set} dynamic={dynamic} upstreamSources={upstreamSources} />
      ) : null}

      {(type === "start" || type === "end") && <div className="fg-2 t-body-sm">No configuration for this node.</div>}

      {!FORM_NODES.has(type) && (
        <>
          <div className="field-label">Config (JSON)</div>
          <textarea className="textarea mono" rows={8} style={{ fontSize: 12 }} defaultValue={JSON.stringify(c, null, 2)}
            onChange={(e) => { try { onChange(JSON.parse(e.target.value || "{}")); } catch { /* keep */ } }} />
        </>
      )}
    </div>
  );
}

/* Tool picker for the Tool Call node, grouped by tool set.

   Every installed connector owns a tool set, so its actions arrive here as their own group
   ("Slack", "Gmail", …) rather than being scattered through one flat alphabetical list of every
   tool in the project. With a couple of connectors installed that flat list runs to dozens of
   entries and picking the right one becomes guesswork; the group label is the only context that
   tells you which system an action actually talks to. A search box filters across both the tool
   name and its group, so typing "slack" finds the actions even when their names don't say so. */
function ToolPicker({ tools, toolSets, value, onChange }: {
  tools: Tool[]; toolSets: ToolSet[]; value: string; onChange: (v: string) => void;
}) {
  const [q, setQ] = useState("");
  const byId = useMemo(() => new Map(tools.map((t) => [t.id, t])), [tools]);

  // Group by tool set, preserving set order; anything in no set falls into "Other tools".
  // A tool in several sets is listed under each (membership is labels, not folders).
  const groups = useMemo(() => {
    const out: { label: string; icon?: string | null; tools: Tool[] }[] = [];
    const grouped = new Set<string>();
    for (const ts of toolSets) {
      const members = (ts.tool_ids || []).map((id) => byId.get(id)).filter(Boolean) as Tool[];
      if (!members.length) continue;
      members.forEach((t) => grouped.add(t.id));
      out.push({ label: ts.name, icon: ts.icon, tools: members });
    }
    const loose = tools.filter((t) => !grouped.has(t.id));
    if (loose.length) out.push({ label: "Other tools", tools: loose });
    return out;
  }, [tools, toolSets, byId]);

  const needle = q.trim().toLowerCase();
  const filtered = needle
    ? groups
        .map((g) => ({ ...g, tools: g.tools.filter((t) => (t.name + " " + g.label).toLowerCase().includes(needle)) }))
        .filter((g) => g.tools.length)
    : groups;

  const selected = value ? byId.get(value) : undefined;
  const selectedGroup = value ? groups.find((g) => g.tools.some((t) => t.id === value)) : undefined;

  return (
    <div className="col" style={{ gap: 6 }}>
      {tools.length > 8 && (
        <input className="input" style={{ height: 28, fontSize: 12 }} value={q} placeholder="Filter tools…"
          onChange={(e) => setQ(e.target.value)} />
      )}
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select a tool…</option>
        {/* Keep the current selection selectable even when the filter hides it, or typing in
            the filter box would silently blank the node's configured tool. */}
        {selected && needle && !filtered.some((g) => g.tools.some((t) => t.id === selected.id)) && (
          <option value={selected.id}>{selected.name} · current</option>
        )}
        {filtered.map((g) => (
          <optgroup key={g.label} label={g.label}>
            {g.tools.map((t) => <option key={g.label + t.id} value={t.id}>{t.name} · {t.kind}</option>)}
          </optgroup>
        ))}
      </select>
      {selectedGroup && (
        <div className="row gap2" style={{ fontSize: 11.5, color: "var(--fg-2)" }}>
          <Icon name={selectedGroup.icon || "tools"} size={12} />
          <span>from <strong style={{ color: "var(--fg-1)" }}>{selectedGroup.label}</strong></span>
        </div>
      )}
      {selected && !selected.enabled && (
        <div className="row gap1" style={{ fontSize: 11.5, color: "#ef4444", marginTop: 2 }}>
          <Icon name="alert" size={12} />
          <span>This tool is disabled or inactive. Enable it in Integrations to execute.</span>
        </div>
      )}
      {selected && selected.enabled && Boolean((selected as any).config?.requires_approval) && (
        <div className="row gap1" style={{ fontSize: 11.5, color: "#f59e0b", marginTop: 2 }}>
          <Icon name="shield" size={12} />
          <span>Execution requires human-in-the-loop approval.</span>
        </div>
      )}
    </div>
  );
}

/* Declarative field specs → friendly form widgets (no raw JSON for common nodes). The form
   merges only its own keys, so any extra config is preserved. Mirrors the node config schemas.
   (Widgets + FieldSpec live in canvas/ConfigForm.tsx, shared with the middleware stack.) */
const NODE_FIELDS: Record<string, FieldSpec[]> = {
  transform: [
    { key: "input_key", label: "Input state key", widget: "text", placeholder: "messages", help: "Which state field to read." },
    { key: "output_key", label: "Output state key", widget: "text", placeholder: "result", help: "Which state field to write." },
    { key: "expression", label: "Expression", widget: "textarea", help: "Sandboxed expression over state (e.g. len(messages))." },
  ],
  classifier: [
    { key: "labels", label: "Intent labels", widget: "csv", placeholder: "return_item, cancel_subscription, get_information", help: "Wire a Router after this with one case per label." },
    { key: "output_key", label: "Write label to state key", widget: "text", placeholder: "intent", help: "The Router's expression should read this key." },
    { key: "multi_label", label: "Multi-label (all that apply)", widget: "toggle", help: "Write EVERY applicable label (a list) instead of exactly one. Pair with a Router set to 'Route to every match' so a question with several intents reaches several specialists in parallel." },
    { key: "model", label: "Model", widget: "model", emptyLabel: "Auto (cheapest model)", help: "Left on Auto, the classifier uses your provider's cheapest model (e.g. gpt-4.1-nano) — not the project default — since classification is high-volume and low-stakes. Pick a model to override." },
    { key: "instructions", label: "Extra guidance (optional)", widget: "textarea", placeholder: "Domain hints, tie-breaking rules…" },
  ],
  human_input: [
    { key: "prompt", label: "Prompt to reviewer", widget: "textarea", help: "Shown when the run pauses for approval." },
    { key: "allowed_decisions", label: "Allowed decisions", widget: "csv", placeholder: "approve, reject", help: "The buttons the reviewer sees in the Playground." },
    { key: "output_key", label: "Write decision to state key", widget: "text", placeholder: "decision", help: "Optional: use a key name like decision. The selected value is written there so a Router can branch approve vs reject." },
  ],
  emit_event: [
    { key: "event", label: "Event name", widget: "text", placeholder: "order.created" },
  ],
  webhook_out: [
    { key: "url", label: "Webhook URL", widget: "text", placeholder: "https://…" },
    { key: "method", label: "Method", widget: "select", options: ["POST", "PUT", "PATCH", "GET"].map((m) => ({ value: m, label: m })) },
  ],
  handoff: [
    { key: "reason", label: "Reason", widget: "text", placeholder: "Escalated to a human agent.", help: "Why the conversation is handed off (shown in the agent inbox)." },
    { key: "ack_message", label: "Hold message (optional)", widget: "textarea", placeholder: "A team member will follow up shortly.", help: "Sent to the customer while they wait for a human." },
  ],
  // --- flow ---
  loop: [
    { key: "max_iter", label: "Max iterations", widget: "number", min: 1, step: 1, help: "Safety cap on how many times the body runs." },
    { key: "condition", label: "Continue while (expression)", widget: "textarea", placeholder: "keep_going == True", help: "Sandboxed expression over state; loops while truthy. Writes _loop = continue/done - wire a Router on _loop and point its body back to this node." },
  ],
  parallel_fanout: [
    { key: "over", label: "List state key", widget: "text", placeholder: "items", help: "State field holding the list to map over." },
    { key: "child_node", label: "Child node id", widget: "text", placeholder: "worker", help: "The node run once per item, in parallel (Send)." },
    { key: "item_key", label: "Item state key", widget: "text", placeholder: "item", help: "Each item is written here for the child to read." },
  ],
  join: [
    { key: "reducer", label: "Combine results", widget: "select", options: ["concat", "merge", "first", "last"].map((m) => ({ value: m, label: m })), help: "How parallel branches converge. Children should write to an add-reducer state key to aggregate." },
  ],
  subworkflow: [
    { key: "workflow_id", label: "Workflow (id or name)", widget: "text", placeholder: "Verify identity", help: "Another workflow in THIS project, run as a reusable component (shares messages state)." },
  ],
  // --- triggers ---
  webhook_in: [
    { key: "message_path", label: "Message JMESPath (optional)", widget: "text", placeholder: "text", help: "Path into the POSTed JSON body used as the message (empty = the whole body). The webhook URL appears on the Triggers screen after you publish." },
    { key: "require_signature", label: "Require HMAC signature", widget: "toggle", help: "Verify the X-Alberto-Signature or X-Forge-Signature (sha256) header using the secret below." },
    { key: "secret_ref", label: "Signing secret ref", widget: "text", placeholder: "secret://proj/webhook_secret", help: "Secret used to verify the signature." },
  ],
  schedule: [
    { key: "every_minutes", label: "Every N minutes", widget: "number", min: 1, step: 1, help: "Run on a fixed interval. Use this OR cron." },
    { key: "cron", label: "Cron expression (optional)", widget: "text", placeholder: "0 9 * * 1-5", help: "Standard cron (needs the workers extra). Overrides the interval if set." },
    { key: "message", label: "Message", widget: "textarea", placeholder: "Summarize today's tickets.", help: "The input sent into the workflow on each run." },
  ],
  email_in: [
    { key: "mailbox", label: "Mailbox", widget: "text", placeholder: "support@yourco.com", help: "The address this trigger handles. Connect an Email channel (Connect screen) to receive mail." },
    { key: "include_subject", label: "Include subject", widget: "toggle", help: "Prepend the email subject to the message." },
    { key: "reply", label: "Reply to sender", widget: "toggle", help: "Send the workflow's answer back as a threaded email." },
  ],
  app_event: [
    { key: "poll_url", label: "Poll URL", widget: "text", placeholder: "https://api.example.com/events", help: "Polled on each interval; new items fire the workflow." },
    { key: "method", label: "Method", widget: "select", options: ["GET", "POST"].map((m) => ({ value: m, label: m })) },
    { key: "interval_minutes", label: "Poll every N minutes", widget: "number", min: 1, step: 1 },
    { key: "items_path", label: "Items JMESPath", widget: "text", placeholder: "data.items", help: "Path to the list of items in the response (empty = the whole body)." },
    { key: "dedupe_key", label: "Dedupe key JMESPath", widget: "text", placeholder: "id", help: "Unique id within each item so it fires only once." },
    { key: "message_path", label: "Message JMESPath (optional)", widget: "text", placeholder: "title", help: "Path within an item for the message text (empty = the whole item)." },
  ],
  inject: [
    { key: "topic", label: "Topic (msg.topic)", widget: "text", placeholder: "home.status", help: "Topic identifier for message routing." },
    { key: "payload_type", label: "Payload type", widget: "select", options: [
      { value: "json", label: "JSON Object" },
      { value: "string", label: "String" },
      { value: "number", label: "Number" },
      { value: "boolean", label: "Boolean" },
      { value: "timestamp", label: "Current Timestamp" },
    ]},
    { key: "payload", label: "Payload (msg.payload)", widget: "textarea", placeholder: "{\n  \"status\": \"active\"\n}", help: "Message payload content injected into workflow." },
    { key: "repeat", label: "Repeat interval (seconds, 0=manual)", widget: "number", min: 0, step: 1 },
  ],
  debug: [
    { key: "target", label: "Inspect property", widget: "select", options: [
      { value: "payload", label: "msg.payload" },
      { value: "msg", label: "Complete msg object" },
      { value: "topic", label: "msg.topic" },
      { value: "messages", label: "messages (chat history)" },
    ], help: "Which state property to inspect and print in the debug sidebar." },
    { key: "active", label: "Debug active", widget: "toggle", help: "Mute debug output without disconnecting the node." },
  ],
  delay: [
    { key: "seconds", label: "Delay duration", widget: "number", min: 0.1, step: 0.5 },
    { key: "unit", label: "Unit", widget: "select", options: [
      { value: "seconds", label: "Seconds" },
      { value: "minutes", label: "Minutes" },
      { value: "hours", label: "Hours" },
    ]},
  ],
};
// Node types that render a real form (agent/router/llm/tool_call have bespoke forms; the rest come from NODE_FIELDS).
const FORM_NODES = new Set<string>(["agent", "deep_agent", "router", "switch", "llm", "tool_call", "retrieval", "start", "end", "transform", "change", "inject", "debug", "delay", ...Object.keys(NODE_FIELDS)]);

/** State keys written by upstream-capable nodes, with the values they can take -
 *  shown in the router form so users branch on real values, not made-up labels. */
function stateWriters(nodes: FlowNode[]): { key: string; values: string[]; from: string }[] {
  const out: { key: string; values: string[]; from: string }[] = [];
  const valuesOf = (value: any, fallback: string[] = []) => (
    Array.isArray(value)
      ? value
      : typeof value === "string"
        ? value.split(",")
        : fallback
  ).map((v) => String(v).trim()).filter(Boolean);
  for (const n of nodes) {
    const cfg = n.data.config || {};
    const t = n.data.nodeType;
    if (t === "classifier") out.push({ key: cfg.output_key || "intent", values: valuesOf(cfg.labels), from: n.id });
    if (t === "retrieval" && cfg.route_key) out.push({ key: cfg.route_key, values: ["yes", "no"], from: n.id });
    if (t === "human_input" && cfg.output_key) out.push({ key: cfg.output_key, values: valuesOf(cfg.allowed_decisions, ["approve", "reject"]), from: n.id });
  }
  return out;
}

/* Retrieval node config - toggleable Knowledge (RAG over documents) + FAQs / Q&A sections,
   mirroring the agent panel's Knowledge sections (AgentConfig). Document search (include_docs)
   and Q&A lookup (include_qa) are independent: use either or both. The flat retrieval config is
   read/written directly. */
function RetrievalForm({ c, set, folders, kinds }: { c: Record<string, any>; set: (p: Record<string, any>) => void; folders: string[]; kinds: string[] }) {
  const ragOn = c.include_docs !== false; // RAG on unless explicitly turned off
  const qaOn = !!c.include_qa;
  const memoryOn = c.include_memory !== false;
  const graphOn = c.include_graph !== false;
  return (
    <div className="col" style={{ gap: 18 }}>
      <CollapsibleSection label="Unified Memory" badge={memoryOn || graphOn ? "active" : undefined}
        hint="Automatically ground workflow steps with curated facts from Memory Curator and entity relations from Knowledge Graph.">
        <div className="col gap2">
          <label className="row gap2" style={{ cursor: "pointer" }}>
            <Toggle on={memoryOn} onChange={(on) => set({ include_memory: on })} />
            <span className="t-body-sm">Include Curated Memories (Facts &amp; Preferences)</span>
          </label>
          <label className="row gap2" style={{ cursor: "pointer" }}>
            <Toggle on={graphOn} onChange={(on) => set({ include_graph: on })} />
            <span className="t-body-sm">Include Knowledge Graph (Entities &amp; Relations)</span>
          </label>
        </div>
      </CollapsibleSection>

      <CollapsibleSection label="Knowledge" badge={ragOn ? "enabled" : undefined}
        hint="Pull the most relevant document chunks from your knowledge base into context for a grounded agent.">
        <div className="col gap2">
          <label className="row gap2" style={{ cursor: "pointer" }}>
            <Toggle on={ragOn} onChange={(on) => set({ include_docs: on })} />
            <span className="t-body-sm">Search knowledge base (RAG over documents)</span>
          </label>
          {ragOn && (
            <div className="col gap2" style={{ paddingLeft: 6 }}>
              <Field label="Folders" help="Limit document search to these folders (none selected = all).">
                <MultiSelectChips value={c.folders || []} options={folders} onChange={(items) => set({ folders: items })} />
              </Field>
              <div className="row gap3 wrap">
                <Field label="Documents (top K)" help="Chunks returned per search.">
                  <input className="input" type="number" min={1} max={20} step={1} style={{ width: 92 }}
                    value={c.top_k ?? 5} onChange={(e) => set({ top_k: Number(e.target.value) || 1 })} />
                </Field>
                <Field label="Min score" help="Drop chunks below this similarity (0–1).">
                  <input className="input" type="number" min={0} max={1} step={0.02} style={{ width: 92 }}
                    value={c.min_score ?? 0.18} onChange={(e) => set({ min_score: Number(e.target.value) })} />
                </Field>
              </div>
              <label className="row gap2" style={{ cursor: "pointer" }}>
                <Toggle on={!!c.hybrid} onChange={(on) => set({ hybrid: on })} />
                <span className="t-body-sm">Hybrid search (BM25 + vector)</span>
              </label>
              <div className="field-help">Blend lexical keyword (BM25) ranking with semantic vectors so exact terms - codes, names, SKUs - aren’t missed.</div>
              <label className="row gap2" style={{ cursor: "pointer" }}>
                <Toggle on={!!c.rerank} onChange={(on) => set({ rerank: on })} />
                <span className="t-body-sm">Rerank (cross-encoder)</span>
              </label>
              <div className="field-help">Two-stage retrieval: a local cross-encoder re-scores the shortlist and keeps only the best matches. Big accuracy boost; adds some latency. Runs offline on CPU (no extra cost). Min score is ignored while this is on (the reranker score is on a different scale).</div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection label="FAQs / Q&amp;A" badge={qaOn ? "enabled" : undefined}
        hint="Also pull curated FAQ / Q&amp;A pairs into context alongside the documents.">
        <div className="col gap2">
          <label className="row gap2" style={{ cursor: "pointer" }}>
            <Toggle on={qaOn} onChange={(on) => set({ include_qa: on })} />
            <span className="t-body-sm">Include FAQ / Q&amp;A answers</span>
          </label>
          {qaOn && (
            <div className="col gap2" style={{ paddingLeft: 6 }}>
              <Field label="Kinds" help="Limit Q&A to these kinds/categories (none selected = all).">
                <MultiSelectChips value={c.qa_kinds || []} options={kinds} onChange={(items) => set({ qa_kinds: items })} />
              </Field>
              <div className="row gap3 wrap">
                <Field label="Pairs (top K)" help="Q&A pairs returned per lookup.">
                  <input className="input" type="number" min={1} max={20} step={1} style={{ width: 92 }}
                    value={c.qa_top_k ?? 3} onChange={(e) => set({ qa_top_k: Number(e.target.value) || 1 })} />
                </Field>
                <Field label="Match threshold" help="Min similarity for a Q&A pair (0–1).">
                  <input className="input" type="number" min={0} max={1} step={0.05} style={{ width: 92 }}
                    value={c.qa_threshold ?? 0.3} onChange={(e) => set({ qa_threshold: Number(e.target.value) })} />
                </Field>
              </div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      <div className="col gap2">
        <div className="t-micro">When nothing is found</div>
        <label className="row gap2" style={{ cursor: "pointer" }}>
          <Toggle on={!!c.announce_empty} onChange={(on) => set({ announce_empty: on })} />
          <span className="t-body-sm">Announce when empty</span>
        </label>
        <div className="field-help">Tells a grounded agent nothing relevant was found, so it says “I don’t know” instead of guessing.</div>
        <Field label="Route flag (state key)" help="Optional: writes 'yes'/'no' (anything found?) to this state field so a Router can branch found vs not-found.">
          <input className="input mono" value={c.route_key ?? ""} placeholder="data_found" onChange={(e) => set({ route_key: e.target.value || undefined })} />
        </Field>
      </div>

      {!ragOn && !qaOn && (
        <div className="field-help" style={{ color: "var(--warn)" }}>
          ⚠ Both sources are off - this node will retrieve nothing. Turn on Knowledge and/or Q&amp;A above.
        </div>
      )}
    </div>
  );
}

function RouterForm({
  nodeId,
  c,
  set,
  nodeIds,
  nodes,
  upstreamSources = [],
  onCaseTarget,
  onCaseRename,
  onCaseRemove,
}: {
  nodeId: string;
  c: Record<string, any>;
  set: (p: Record<string, any>) => void;
  nodeIds: string[];
  nodes: FlowNode[];
  upstreamSources?: UpstreamSource[];
  onCaseTarget: (nodeId: string, key: string, target: string) => void;
  onCaseRename: (nodeId: string, oldKey: string, newKey: string) => void;
  onCaseRemove: (nodeId: string, key: string) => void;
}) {
  const [mode, setMode] = useState<"rules" | "expression">(c.rules ? "rules" : "expression");
  const rules: Array<{ property: string; op: string; value: any; target: string }> = Array.isArray(c.rules) ? c.rules : [];
  const cases: Record<string, string> = c.cases || {};
  const rows = Object.entries(cases);

  const addRule = () => {
    const next = [...rules, { property: "payload.status", op: "eq", value: "active", target: nodeIds[0] || "" }];
    set({ rules: next });
  };
  const updateRule = (idx: number, patch: Partial<(typeof rules)[0]>) => {
    const next = rules.map((r, i) => (i === idx ? { ...r, ...patch } : r));
    set({ rules: next });
  };
  const removeRule = (idx: number) => {
    const next = rules.filter((_, i) => i !== idx);
    set({ rules: next });
  };

  const setCase = (k: string, v: string) => {
    set({ cases: { ...cases, [k]: v } });
    onCaseTarget(nodeId, k, v);
  };
  const renameCase = (oldK: string, newK: string) => {
    if (!newK || newK === oldK) return;
    const n = { ...cases };
    const val = n[oldK];
    delete n[oldK];
    n[newK] = val;
    set({ cases: n });
    onCaseRename(nodeId, oldK, newK);
  };
  const removeCase = (k: string) => {
    const n = { ...cases };
    delete n[k];
    set({ cases: n });
    onCaseRemove(nodeId, k);
  };
  const writers = stateWriters(nodes);
  const activeWriter = writers.find((w) => w.key === (c.expression || "").trim());
  const nextCaseKey = () => {
    const nextKnown = activeWriter?.values?.find((value) => value && !Object.prototype.hasOwnProperty.call(cases, value));
    if (nextKnown) return nextKnown;
    let i = rows.length + 1;
    while (Object.prototype.hasOwnProperty.call(cases, `case_${i}`)) i++;
    return `case_${i}`;
  };
  const addCase = () => setCase(nextCaseKey(), "");

  return (
    <div className="col gap3">
      <div className="row spread" style={{ borderBottom: "1px solid var(--line)", paddingBottom: 6 }}>
        <span className="t-micro">Routing Mode</span>
        <div className="row gap1">
          <button
            type="button"
            className="chip"
            style={{
              cursor: "pointer",
              background: mode === "rules" ? "var(--accent)" : "var(--bg-3)",
              color: mode === "rules" ? "var(--fg-on-accent)" : "var(--fg-1)",
              borderColor: mode === "rules" ? "var(--accent)" : "var(--line)",
            }}
            onClick={() => {
              setMode("rules");
              if (!c.rules) {
                set({ rules: [{ property: "payload.status", op: "eq", value: "active", target: nodeIds[0] || "" }] });
              }
            }}
          >
            Simple Rules
          </button>
          <button
            type="button"
            className="chip"
            style={{
              cursor: "pointer",
              background: mode === "expression" ? "var(--accent)" : "var(--bg-3)",
              color: mode === "expression" ? "var(--fg-on-accent)" : "var(--fg-1)",
              borderColor: mode === "expression" ? "var(--accent)" : "var(--line)",
            }}
            onClick={() => setMode("expression")}
          >
            Expression
          </button>
        </div>
      </div>

      {mode === "rules" ? (
        <div className="col gap3">
          <div className="row spread">
            <span className="t-body-sm fg-2">Switch Conditions</span>
            <button type="button" className="btn btn-xs btn-secondary" onClick={addRule}>
              <Icon name="plus" size={12} /> Add Rule
            </button>
          </div>
          {rules.length === 0 ? (
            <div className="field-help">No rules configured. Messages will follow the default target.</div>
          ) : (
            <div className="col gap2">
              {rules.map((r, i) => (
                <div key={i} className="card col gap1" style={{ padding: 8, background: "var(--bg-3)", border: "1px solid var(--line)" }}>
                  <div className="row spread">
                    <span className="mono-sm fg-2" style={{ fontSize: 11 }}>Rule #{i + 1}</span>
                    <button type="button" className="iconbtn" style={{ width: 20, height: 20 }} onClick={() => removeRule(i)}>
                      <Icon name="trash" size={12} />
                    </button>
                  </div>
                  <div className="row gap1" style={{ alignItems: "center" }}>
                    <input
                      className="input mono"
                      style={{ height: 26, fontSize: 11, flex: 1 }}
                      placeholder="property (e.g. payload.status)"
                      value={r.property || ""}
                      onChange={(e) => updateRule(i, { property: e.target.value })}
                    />
                    <VariablePicker
                      sources={upstreamSources}
                      onSelect={(path) => updateRule(i, { property: path })}
                    />
                  </div>
                  <div className="row gap1">
                    <select
                      className="select"
                      style={{ height: 26, fontSize: 11, flex: 1 }}
                      value={r.op}
                      onChange={(e) => updateRule(i, { op: e.target.value })}
                    >
                      <option value="eq">== (equals)</option>
                      <option value="neq">!= (not equals)</option>
                      <option value="contains">contains</option>
                      <option value="gt">&gt; (greater than)</option>
                      <option value="gte">&gt;= (greater than or equal)</option>
                      <option value="lt">&lt; (less than)</option>
                      <option value="lte">&lt;= (less than or equal)</option>
                      <option value="exists">exists</option>
                      <option value="empty">is empty</option>
                      <option value="true">is true</option>
                      <option value="false">is false</option>
                    </select>
                    {!["exists", "empty", "true", "false"].includes(r.op) && (
                      <input
                        className="input mono"
                        style={{ height: 26, fontSize: 11, flex: 1 }}
                        placeholder="value"
                        value={r.value !== undefined ? String(r.value) : ""}
                        onChange={(e) => updateRule(i, { value: e.target.value })}
                      />
                    )}
                  </div>
                  <div className="row gap1" style={{ alignItems: "center" }}>
                    <span className="fg-2 mono-sm" style={{ fontSize: 10, width: 44 }}>route →</span>
                    <select
                      className="select"
                      style={{ height: 26, fontSize: 11, flex: 1 }}
                      value={r.target || ""}
                      onChange={(e) => updateRule(i, { target: e.target.value })}
                    >
                      <option value="">Select target node…</option>
                      {nodeIds.map((id) => <option key={id} value={id}>{id}</option>)}
                    </select>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <>
          <div>
            <div className="field-label">Expression (over state)</div>
            <input className="input mono" value={c.expression || ""} placeholder="intent" list="router-state-keys" onChange={(e) => set({ expression: e.target.value })} />
            <datalist id="router-state-keys">{writers.map((w) => <option key={w.key} value={w.key} />)}</datalist>
            {writers.length > 0 ? (
              <div className="field-help">
                Keys written upstream: {writers.map((w) => `${w.key} (${w.values.slice(0, 4).join("/") || "…"}, from ${w.from})`).join(" · ")}
              </div>
            ) : (
              <div className="field-help" style={{ color: "var(--warn)" }}>
                ⚠ No node in this workflow writes a routable state key yet. Add a Classifier (writes a label), or set a route/decision flag on Retrieval or Human Input - otherwise every run takes the Default path.
              </div>
            )}
          </div>
          <div>
            <div className="field-label">Cases - when the expression VALUE equals… → go to</div>
            {activeWriter && (
              <div className="field-help" style={{ marginBottom: 6 }}>
                '{activeWriter.key}' takes the values: <b>{activeWriter.values.join(", ") || "(set by " + activeWriter.from + ")"}</b> - use those exact values as case keys.
              </div>
            )}
            <div className="col gap2">
              {rows.map(([k, v], i) => (
                <div key={i} className="row gap2">
                  <input className="input mono" style={{ flex: 1 }} value={k} onChange={(e) => renameCase(k, e.target.value)} />
                  <Icon name="chevright" size={14} style={{ color: "var(--fg-2)" }} />
                  <select className="select" style={{ flex: 1 }} value={v} onChange={(e) => setCase(k, e.target.value)}>
                    <option value="">target…</option>
                    {nodeIds.map((id) => <option key={id} value={id}>{id}</option>)}
                  </select>
                  <button className="iconbtn" onClick={() => removeCase(k)}><Icon name="trash" size={14} /></button>
                </div>
              ))}
              <button className="btn btn-secondary btn-sm" style={{ alignSelf: "flex-start" }} onClick={addCase}><Icon name="plus" size={13} />Add case</button>
            </div>
          </div>
        </>
      )}

      <div>
        <div className="field-label">Default target</div>
        <select className="select" value={c.default || ""} onChange={(e) => { set({ default: e.target.value }); onCaseTarget(nodeId, "__default__", e.target.value); }}>
          <option value="">none</option>
          {nodeIds.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
        {!c.default && (
          <div className="field-help" style={{ color: "var(--warn)" }}>
            ⚠ No default: if no rules match, the run ends silently.
          </div>
        )}
      </div>
      <div>
        <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={!!c.multi} onChange={(e) => set({ multi: e.target.checked })} />
          <span className="field-label" style={{ margin: 0 }}>Route to every match (multi)</span>
        </label>
        <div className="field-help">
          For list-valued expressions or multiple matching rules: run EVERY matching case in parallel.
        </div>
      </div>
    </div>
  );
}
