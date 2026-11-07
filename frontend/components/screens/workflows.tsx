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
import { NodeConfigModal } from "../canvas/NodeConfigModal";
import { NodeInspector } from "../canvas/NodeInspector";
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
  const [paletteTip, setPaletteTip] = useState<{ type: string; title?: string; desc?: string; top: number; left: number } | null>(null);
  const { fitView, screenToFlowPosition } = useReactFlow();
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

  const getCanvasCenterPosition = useCallback((offsetIndex: number = 0) => {
    if (typeof window !== "undefined") {
      const canvasEl = document.querySelector(".forge-canvas") || document.querySelector(".react-flow");
      if (canvasEl) {
        const rect = canvasEl.getBoundingClientRect();
        const center = screenToFlowPosition({
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
        });
        const stagger = (offsetIndex % 5) * 28;
        return { x: Math.round(center.x - 90 + stagger), y: Math.round(center.y - 35 + stagger) };
      }
    }
    return { x: 360 + (offsetIndex % 4) * 36, y: 140 + (offsetIndex % 4) * 36 };
  }, [screenToFlowPosition]);

  const pasteNode = useCallback(() => {
    const clip = clipboardRef.current;
    if (!clip) return;
    snapshot();
    const cur = nodesRef.current;
    const id = newNodeId(clip.nodeType, cur.map((n) => n.id));
    const base = cur.find((n) => n.id === selId);
    const pos = base ? { x: base.position.x + 44, y: base.position.y + 44 } : getCanvasCenterPosition(cur.length);
    setNodes((nds) => [...nds, { id, type: "forge", position: pos, data: { nodeType: clip.nodeType, config: JSON.parse(JSON.stringify(clip.config)) } }]);
    setSelId(id);
    setDirty(true);
  }, [selId, setNodes, snapshot, getCanvasCenterPosition]);

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

  const addNode = useCallback((type: string, position?: { x: number; y: number }) => {
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
      : type === "inject" ? { payload: "timestamp", payload_type: "timestamp", topic: "", repeat: 0 }
      : type === "debug" ? { target: "payload", active: true }
      : type === "tool_call" ? { output_key: "payload" }
      : type === "webhook_out" ? { method: "POST", url: "", output_key: "payload" }
      : type === "transform" ? { output_key: "payload" }
      : {};
    const pos = position || getCanvasCenterPosition(n);
    setNodes((nds) => [...nds, { id, type: "forge", position: pos, data: { nodeType: type, config: defConfig } }]);
    setSelId(id);
  }, [nodes, setNodes, snapshot, getCanvasCenterPosition]);

  const addToolNode = useCallback((tool: Tool, toolSetLabel?: string, position?: { x: number; y: number }) => {
    snapshot();
    setDirty(true);
    const id = newNodeId("tool_call", nodes.map((n) => n.id));
    const n = nodes.length;
    const pos = position || getCanvasCenterPosition(n);
    setNodes((nds) => [
      ...nds,
      {
        id,
        type: "forge",
        position: pos,
        data: {
          nodeType: "tool_call",
          config: {
            name: tool.name,
            tool_id: tool.id,
            output_key: "payload",
          },
        },
      },
    ]);
    setSelId(id);
  }, [nodes, setNodes, snapshot, getCanvasCenterPosition]);

  const onPaletteDragStart = useCallback((event: React.DragEvent, nodeType: string, toolData?: { tool_id: string; name: string }) => {
    event.dataTransfer.setData("application/reactflow", nodeType);
    if (toolData) {
      event.dataTransfer.setData("application/alberto-tool", JSON.stringify(toolData));
    }
    event.dataTransfer.effectAllowed = "move";
    setPaletteTip(null);
  }, []);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/reactflow");
      if (!type) return;

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const toolJson = event.dataTransfer.getData("application/alberto-tool");
      if (type === "tool_call" && toolJson) {
        try {
          const toolData = JSON.parse(toolJson);
          if (toolData?.tool_id) {
            addToolNode({ id: toolData.tool_id, name: toolData.name } as any, undefined, position);
            return;
          }
        } catch {
          // fallback to generic addNode
        }
      }

      addNode(type, position);
    },
    [screenToFlowPosition, addNode, addToolNode]
  );

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

  const integrationTools = useMemo(() => {
    const byId = new Map(tools.map((t) => [t.id, t]));
    const groups: { group: string; icon?: string | null; tools: Tool[] }[] = [];
    const grouped = new Set<string>();

    for (const ts of toolSets) {
      const members = (ts.tool_ids || []).map((id) => byId.get(id)).filter(Boolean) as Tool[];
      if (!members.length) continue;
      members.forEach((t) => grouped.add(t.id));
      groups.push({ group: ts.name, icon: ts.icon, tools: members });
    }
    const loose = tools.filter((t) => !grouped.has(t.id));
    if (loose.length) {
      groups.push({ group: "Custom & Builtin Tools", tools: loose });
    }
    return groups;
  }, [tools, toolSets]);

  const filteredIntegrationGroups = useMemo(() => {
    const q = paletteQuery.trim().toLowerCase();
    if (!q) return integrationTools;
    return integrationTools
      .map((g) => ({
        ...g,
        tools: g.tools.filter(
          (t) =>
            t.name.toLowerCase().includes(q) ||
            g.group.toLowerCase().includes(q) ||
            (t.config?.description || "").toLowerCase().includes(q)
        ),
      }))
      .filter((g) => g.tools.length > 0);
  }, [integrationTools, paletteQuery]);

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
                        draggable
                        onDragStart={(e) => onPaletteDragStart(e, it.type)}
                        style={{ padding: "7px 8px", borderRadius: 7, border: "1px solid var(--line)", background: "var(--bg-2)", cursor: "grab", textAlign: "left" }}
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

          {/* Installed Integrations & Tools */}
          {filteredIntegrationGroups.length > 0 && (
            <div style={{ marginTop: 14, paddingTop: 10, borderTop: "1px solid var(--line)" }}>
              <div className="row spread" style={{ marginBottom: 6 }}>
                <span className="t-micro" style={{ letterSpacing: "0.5px" }}>INTEGRATIONS & TOOLS</span>
                <span className="typechip" style={{ fontSize: 9 }}>
                  {filteredIntegrationGroups.reduce((acc, g) => acc + g.tools.length, 0)}
                </span>
              </div>
              {filteredIntegrationGroups.map((g) => (
                <div key={g.group} style={{ marginBottom: 10 }}>
                  <div className="t-caption fg-2" style={{ fontWeight: 600, fontSize: 10.5, marginBottom: 4 }}>
                    {g.group}
                  </div>
                  <div className="col gap1">
                    {g.tools.map((t) => (
                      <button
                        key={t.id}
                        className="row gap2"
                        draggable
                        onDragStart={(e) => onPaletteDragStart(e, "tool_call", { tool_id: t.id, name: t.name })}
                        onClick={() => addToolNode(t, g.group)}
                        style={{
                          padding: "6px 8px",
                          borderRadius: 6,
                          border: "1px solid var(--line)",
                          background: "var(--bg-2)",
                          cursor: "grab",
                          textAlign: "left",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.borderColor = "var(--signal)";
                          const r = e.currentTarget.getBoundingClientRect();
                          setPaletteTip({
                            type: "tool_call",
                            title: `${g.group}: ${t.name}`,
                            desc: t.config?.description || `Invoke ${t.name} from ${g.group}`,
                            top: r.top,
                            left: r.right + 10,
                          });
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.borderColor = "var(--line)";
                          setPaletteTip(null);
                        }}
                      >
                        <Icon name="n_tool" size={13} style={{ color: "var(--signal)", flexShrink: 0 }} />
                        <span className="t-body-sm truncate" style={{ fontSize: 11.5 }} title={t.name}>
                          {t.name}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* palette hover help card */}
        {paletteTip && (() => {
          if (paletteTip.title) {
            return (
              <div className="card" style={{
                position: "fixed", left: paletteTip.left, top: Math.max(60, Math.min(paletteTip.top, (typeof window !== "undefined" ? window.innerHeight : 800) - 210)),
                width: 290, zIndex: 90, pointerEvents: "none", padding: 12, boxShadow: "var(--sh-pop)",
              }}>
                <div className="row gap2" style={{ marginBottom: 6 }}>
                  <Icon name="n_tool" size={15} style={{ color: "var(--signal)" }} />
                  <span className="t-h3">{paletteTip.title}</span>
                  <span className="typechip">tool</span>
                </div>
                {paletteTip.desc && (
                  <div className="t-body-sm fg-1" style={{ lineHeight: "19px" }}>{paletteTip.desc}</div>
                )}
              </div>
            );
          }
          if (!NODE_HELP[paletteTip.type]) return null;
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
        <div className="grow forge-canvas" style={{ position: "relative", minWidth: 0, height: "100%" }} onDragOver={onDragOver} onDrop={onDrop}>
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
                onDragOver={onDragOver}
                onDrop={onDrop}
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
                  hideControls={false}
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

        {/* n8n-style 3-Panel Node Configuration Modal (Input Data | Parameters | Output Data) */}
        {editingNode && (
          <NodeConfigModal
            node={editingNode}
            nodes={nodes}
            edges={edges}
            project={project}
            workflowId={wf?.id || ""}
            tools={tools}
            toolSets={toolSets}
            agents={agents}
            mcpServers={mcpServers}
            components={components}
            dynamic={{ kb_folders: kbFolders, qa_kinds: qaKinds }}
            pinnedData={wf?.canvas?.pinned_data || {}}
            onPinData={(nodeId, data) => {
              if (!wf) return;
              const nextPinned = { ...(wf.canvas?.pinned_data || {}) };
              if (data) nextPinned[nodeId] = data;
              else delete nextPinned[nodeId];
              const nextCanvas = { ...(wf.canvas || {}), pinned_data: nextPinned };
              setWf({ ...wf, canvas: nextCanvas });
              setDirty(true);
            }}
            onUpdateConfig={updateConfig}
            onRenameNode={renameNodeId}
            onDeleteNode={(id) => {
              deleteNode(id);
              setEditingNodeId(null);
            }}
            onClose={() => setEditingNodeId(null)}
            renderParameters={() => (
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
            )}
          />
        )}
      </div>
    </div>
  );
}

export { NodeInspector } from "../canvas/NodeInspector";
