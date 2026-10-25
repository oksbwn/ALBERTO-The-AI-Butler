"use client";
/* Self-rendered canvas connections.

   React Flow v12's own edge renderer doesn't draw loaded edges reliably in this dev
   setup (handle-bounds race), so we draw the wires ourselves inside the ViewportPortal -
   which lives in flow coordinate space, so it pans/zooms with the canvas. Native edges
   are hidden via CSS to avoid double-draw. New connections (onConnect) land in the same
   `edges` array, so hand-drawn wires show here too. */
import { ViewportPortal, useReactFlow } from "@xyflow/react";
import { useMemo } from "react";
import { Icon } from "../icons";
import { type FlowEdge, type FlowNode } from "@/lib/graph";

const NODE_HEIGHT: Record<string, number> = {
  start: 36, end: 36,
  inject: 72, debug: 72, delay: 72,
  agent: 90, deep_agent: 90, llm: 80, human_input: 80, classifier: 80,
  transform: 64, tool_call: 64, webhook_out: 64, emit_event: 64, retrieval: 64,
};
const NODE_WIDTH = 230;
// Router case-row geometry - must mirror ForgeNode's router body (header + expr line + rows).
const ROUTER_GEOM = { header: 37, exprLine: 22, rowH: 24, pad: 6 };

function routerHeight(cfg: any): number {
  const rows = Object.keys(cfg?.cases || {}).length + 1; // + Else
  return ROUTER_GEOM.header + ROUTER_GEOM.exprLine + rows * ROUTER_GEOM.rowH + ROUTER_GEOM.pad;
}

/** Y offset (within the router node) of the case row an edge leaves from. */
function routerCaseY(cfg: any, edgeOrHandleId?: FlowEdge | string | null): number {
  const keys = [...Object.keys(cfg?.cases || {}), "__default__"];
  let key: string | undefined;
  if (typeof edgeOrHandleId === "string") {
    key = edgeOrHandleId.startsWith("case:") ? edgeOrHandleId.slice(5) : edgeOrHandleId;
  } else if (edgeOrHandleId && typeof edgeOrHandleId === "object") {
    const edge = edgeOrHandleId as FlowEdge;
    key = edge.sourceHandle?.startsWith("case:") ? edge.sourceHandle.slice(5) : undefined;
    if (!key || !keys.includes(key)) {
      key = Object.entries(cfg?.cases || {}).find(([, tgt]) => tgt === edge.target)?.[0]
        ?? (cfg?.default === edge.target ? "__default__" : undefined);
    }
  }
  const idx = key ? keys.indexOf(key) : 0;
  return ROUTER_GEOM.header + ROUTER_GEOM.exprLine + (idx < 0 ? 0 : idx) * ROUTER_GEOM.rowH + ROUTER_GEOM.rowH / 2;
}

export function EdgeOverlay({
  nodes,
  edges,
  selectedNodeId,
  onRemove,
}: {
  nodes: FlowNode[];
  edges: FlowEdge[];
  selectedNodeId?: string | null;
  onRemove: (edge: FlowEdge) => void;
}) {
  const rf = useReactFlow();
  const byId = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);
  const h = (n: any) => {
    if (n?.measured?.height) return n.measured.height;
    if (n?.height) return n.height;
    if (n?.data?.nodeType === "router") return routerHeight(n?.data?.config);
    return NODE_HEIGHT[n?.data?.nodeType] ?? 68;
  };

  const getHandlePosition = (
    nodeId: string,
    handleType: "source" | "target",
    handleId?: string | null,
    isSubagent?: boolean,
    edge?: FlowEdge
  ): { x: number; y: number } | null => {
    const node = byId[nodeId];
    if (!node) return null;

    const intNode = rf.getInternalNode?.(nodeId);
    const pos = intNode?.internals?.positionAbsolute || node.position;
    const width = intNode?.measured?.width || (node as any).measured?.width || (node as any).width || NODE_WIDTH;
    const height = intNode?.measured?.height || (node as any).measured?.height || (node as any).height || h(node);

    // 1. Precise dot position from React Flow's live measured handleBounds
    const bounds = intNode?.internals?.handleBounds?.[handleType];
    if (bounds && bounds.length > 0) {
      let handle = handleId ? bounds.find((hb) => hb.id === handleId) : bounds[0];
      if (!handle && bounds.length > 0) handle = bounds[0];
      if (handle) {
        return {
          x: pos.x + handle.x + handle.width / 2,
          y: pos.y + handle.y + handle.height / 2,
        };
      }
    }

    // 2. Accurate fallback geometry (mirrors HandleStack and router geometry)
    if (isSubagent && handleType === "source") {
      return { x: pos.x + width / 2, y: pos.y + height };
    }
    if (isSubagent && handleType === "target") {
      return { x: pos.x + width / 2, y: pos.y };
    }

    if (handleType === "source") {
      if (node.data?.nodeType === "router") {
        return {
          x: pos.x + width,
          y: pos.y + routerCaseY(node.data?.config, edge || handleId),
        };
      }
      return {
        x: pos.x + width,
        y: pos.y + height / 2,
      };
    } else {
      return {
        x: pos.x,
        y: pos.y + height / 2,
      };
    }
  };

  const edgeGeometry = (e: FlowEdge) => {
    const s = byId[e.source];
    const t = byId[e.target];
    if (!s || !t) return null;

    const isSub = e.sourceHandle === "subagents";
    const srcPt = getHandlePosition(e.source, "source", e.sourceHandle, isSub, e);
    const tgtPt = getHandlePosition(e.target, "target", e.targetHandle, isSub, e);
    if (!srcPt || !tgtPt) return null;

    const sx = srcPt.x;
    const sy = srcPt.y;
    const tx = tgtPt.x;
    const ty = tgtPt.y;

    if (isSub) {
      const dy = Math.max(28, Math.abs(ty - sy) / 2);
      const d = `M ${sx},${sy} C ${sx},${sy + dy} ${tx},${ty - dy} ${tx},${ty}`;
      return { d, mx: (sx + tx) / 2, my: (sy + ty) / 2, sub: true };
    }

    const dx = Math.max(40, Math.abs(tx - sx) / 2);
    const d = `M ${sx},${sy} C ${sx + dx},${sy} ${tx - dx},${ty} ${tx},${ty}`;
    return { d, mx: (sx + tx) / 2, my: (sy + ty) / 2, sub: false };
  };
  return (
    <ViewportPortal>
      <svg style={{ position: "absolute", left: 0, top: 0, width: 1, height: 1, overflow: "visible", pointerEvents: "none", zIndex: -1 }}>
        <defs>
          <marker id="forge-arrow" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">
            <path d="M0,0 L7,3 L0,6 Z" fill="var(--line-strong)" />
          </marker>
          <marker id="forge-arrow-sub" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">
            <path d="M0,0 L7,3 L0,6 Z" fill="var(--accent)" />
          </marker>
        </defs>
        {edges.map((e) => {
          const geo = edgeGeometry(e);
          if (!geo) return null;
          return <path key={e.id} d={geo.d} fill="none" stroke={geo.sub ? "var(--accent)" : "var(--line-strong)"} strokeWidth={2} strokeDasharray={geo.sub ? "6 5" : undefined} markerEnd={geo.sub ? "url(#forge-arrow-sub)" : "url(#forge-arrow)"} />;
        })}
      </svg>
      {edges.map((e) => {
        const geo = edgeGeometry(e);
        if (!geo) return null;
        return (
          <button
            key={`${e.id}-detach`}
            title="Detach edge"
            aria-label={`Detach edge from ${e.source} to ${e.target}`}
            onPointerDown={(ev) => ev.stopPropagation()}
            onClick={(ev) => { ev.stopPropagation(); onRemove(e); }}
            style={{
              position: "absolute", left: geo.mx - 9, top: geo.my - 9,
              width: 18, height: 18, borderRadius: 999,
              border: "1px solid var(--line-strong)", background: "var(--bg-1)",
              color: "var(--fg-2)", boxShadow: "var(--sh-1)",
              display: "flex", alignItems: "center", justifyContent: "center",
              padding: 0, cursor: "pointer", pointerEvents: "auto", zIndex: 8,
            }}
          >
            <Icon name="x" size={10} />
          </button>
        );
      })}
      {edges.map((e) => {
        const geo = edgeGeometry(e);
        if (!geo) return null;
        const s = byId[e.source];
        const isSelected = selectedNodeId && (e.source === selectedNodeId || e.target === selectedNodeId);
        if (!isSelected) return null;
        const badgeText =
          e.sourceHandle?.startsWith("case:")
            ? e.sourceHandle.slice(5)
            : (e as any).label ||
              (s?.data?.nodeType === "inject"
                ? (s.data?.config?.topic ? `topic: ${s.data.config.topic}` : "payload")
                : s?.data?.config?.output_key || "payload");
        return (
          <span
            key={`${e.id}-badge`}
            className="chip chip-mono fade-in"
            style={{
              position: "absolute",
              left: geo.mx,
              top: geo.my - 22,
              transform: "translateX(-50%)",
              fontSize: 10,
              height: 18,
              padding: "0 6px",
              borderColor: "var(--accent)",
              background: "var(--bg-1)",
              color: "var(--fg-0)",
              boxShadow: "var(--sh-1)",
              pointerEvents: "none",
              zIndex: 9,
            }}
          >
            {badgeText}
          </span>
        );
      })}
    </ViewportPortal>
  );
}
