"use client";

import "@xyflow/react/dist/style.css";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../icons";
import {
  api,
  GraphEntity,
  GraphRelationship,
  GraphSubgraph,
} from "@/lib/api";

const KIND_COLORS: Record<string, { bg: string; fg: string; border: string }> = {
  modelrunner: { bg: "rgba(6, 182, 212, 0.14)", fg: "#06b6d4", border: "rgba(6, 182, 212, 0.4)" },
  device: { bg: "rgba(59, 130, 246, 0.14)", fg: "#3b82f6", border: "rgba(59, 130, 246, 0.4)" },
  host: { bg: "rgba(59, 130, 246, 0.14)", fg: "#3b82f6", border: "rgba(59, 130, 246, 0.4)" },
  application: { bg: "rgba(245, 158, 11, 0.14)", fg: "#f59e0b", border: "rgba(245, 158, 11, 0.4)" },
  service: { bg: "rgba(245, 158, 11, 0.14)", fg: "#f59e0b", border: "rgba(245, 158, 11, 0.4)" },
  concept: { bg: "rgba(99, 102, 241, 0.14)", fg: "#6366f1", border: "rgba(99, 102, 241, 0.4)" },
  person: { bg: "rgba(16, 185, 129, 0.14)", fg: "#10b981", border: "rgba(16, 185, 129, 0.4)" },
  default: { bg: "rgba(148, 163, 184, 0.14)", fg: "#94a3b8", border: "rgba(148, 163, 184, 0.4)" },
};

function getKindStyle(kind?: string) {
  const k = (kind || "").trim().toLowerCase();
  return KIND_COLORS[k] || KIND_COLORS.default;
}

export function extractAliases(entity: GraphEntity | null | undefined): string[] {
  if (!entity) return [];
  const aliases: string[] = [];
  if (entity.canonical_name && entity.canonical_name !== entity.name.toLowerCase()) {
    aliases.push(entity.canonical_name);
  }
  if (entity.description) {
    const match = entity.description.match(/\[aliases:\s*([^\]]+)\]/i);
    if (match && match[1]) {
      match[1].split(",").forEach((a) => {
        const item = a.trim();
        if (item && !aliases.includes(item)) {
          aliases.push(item);
        }
      });
    }
  }
  return aliases;
}

interface KnowledgeNodeData {
  entity: GraphEntity;
  selected?: boolean;
  degree?: number;
  onExpand?: (entityId: string) => void;
}

function KnowledgeNodeComponent({ data }: NodeProps) {
  const nodeData = data as unknown as KnowledgeNodeData;
  const entity = nodeData.entity;
  const kindStyle = getKindStyle(entity?.kind);
  const isSelected = !!nodeData.selected;

  return (
    <div
      style={{
        padding: "10px 14px",
        borderRadius: 8,
        background: "var(--bg-1, #1e1e24)",
        border: isSelected ? "2px solid var(--accent, #6366f1)" : `1px solid ${kindStyle.border}`,
        boxShadow: isSelected
          ? "0 0 0 3px var(--accent-glow, rgba(99,102,241,0.25)), var(--node-shadow)"
          : "var(--node-shadow)",
        minWidth: 160,
        maxWidth: 240,
        color: "var(--fg-0, #f8fafc)",
        cursor: "pointer",
        transition: "border 0.15s ease, box-shadow 0.15s ease",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: kindStyle.fg, width: 8, height: 8 }} />
      <Handle type="source" position={Position.Right} style={{ background: kindStyle.fg, width: 8, height: 8 }} />
      <Handle type="target" position={Position.Top} id="top" style={{ opacity: 0, width: 1, height: 1 }} />
      <Handle type="source" position={Position.Bottom} id="bottom" style={{ opacity: 0, width: 1, height: 1 }} />

      <div className="row spread" style={{ alignItems: "center", marginBottom: 6 }}>
        <span
          className="badge"
          style={{
            background: kindStyle.bg,
            color: kindStyle.fg,
            borderColor: kindStyle.border,
            fontSize: 10,
            textTransform: "uppercase",
            fontWeight: 700,
            letterSpacing: "0.04em",
          }}
        >
          {entity?.kind || "Entity"}
        </span>
        {entity?.confidence !== undefined && (
          <span className="mono" style={{ fontSize: 10, color: "var(--fg-2)" }} title="Extraction confidence">
            {Math.round((entity.confidence || 1.0) * 100)}%
          </span>
        )}
      </div>

      <div className="t-h3 truncate" style={{ fontWeight: 650, color: "var(--fg-0)" }} title={entity?.name}>
        {entity?.name}
      </div>

      {entity?.canonical_name && entity.canonical_name !== entity.name && (
        <div className="mono-sm fg-2 truncate" style={{ fontSize: 11, marginTop: 2 }}>
          {entity.canonical_name}
        </div>
      )}

      {nodeData.degree !== undefined && nodeData.degree > 0 && (
        <div className="row spread" style={{ alignItems: "center", marginTop: 8, paddingTop: 6, borderTop: "1px solid var(--line, rgba(255,255,255,0.06))" }}>
          <span className="t-micro fg-2">Connections</span>
          <span className="chip chip-mono" style={{ height: 16, fontSize: 10, padding: "0 6px" }}>
            {nodeData.degree}
          </span>
        </div>
      )}
    </div>
  );
}

const NODE_TYPES = {
  knowledgeNode: KnowledgeNodeComponent,
};

export interface KnowledgeGraphExplorerProps {
  project: { id: string; name?: string };
}

export function KnowledgeGraphExplorer({ project }: KnowledgeGraphExplorerProps) {
  return (
    <ReactFlowProvider>
      <KnowledgeGraphExplorerInner project={project} />
    </ReactFlowProvider>
  );
}

function calculateInitialLayout(
  entities: GraphEntity[],
  relationships: GraphRelationship[]
): { x: number; y: number }[] {
  const count = entities.length;
  if (count === 0) return [];

  // Degree count per entity
  const degrees: Record<string, number> = {};
  relationships.forEach((r) => {
    degrees[r.source_id] = (degrees[r.source_id] || 0) + 1;
    degrees[r.target_id] = (degrees[r.target_id] || 0) + 1;
  });

  // Sort entities by degree descending so central entities are placed near center
  const indexed = entities.map((e, i) => ({ index: i, id: e.id, deg: degrees[e.id] || 0 }));
  indexed.sort((a, b) => b.deg - a.deg);

  const positions: { x: number; y: number }[] = new Array(count);

  if (count === 1) {
    positions[0] = { x: 300, y: 200 };
    return positions;
  }

  // Multi-ring concentric circle layout
  const centerRingCount = Math.min(count, count <= 8 ? count : Math.max(3, Math.floor(count * 0.3)));
  const outerRingCount = count - centerRingCount;

  const centerX = 360;
  const centerY = 240;
  const innerRadius = Math.min(220, Math.max(120, centerRingCount * 30));
  const outerRadius = innerRadius + 220;

  indexed.forEach((item, rank) => {
    if (rank < centerRingCount) {
      const angle = (2 * Math.PI * rank) / centerRingCount;
      positions[item.index] = {
        x: Math.round(centerX + innerRadius * Math.cos(angle)),
        y: Math.round(centerY + innerRadius * Math.sin(angle)),
      };
    } else {
      const outerIndex = rank - centerRingCount;
      const angle = (2 * Math.PI * outerIndex) / Math.max(1, outerRingCount);
      positions[item.index] = {
        x: Math.round(centerX + outerRadius * Math.cos(angle)),
        y: Math.round(centerY + outerRadius * Math.sin(angle)),
      };
    }
  });

  return positions;
}

function KnowledgeGraphExplorerInner({ project }: KnowledgeGraphExplorerProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { fitView, setCenter } = useReactFlow();

  // State
  const [entitiesMap, setEntitiesMap] = useState<Map<string, GraphEntity>>(new Map());
  const [relationshipsMap, setRelationshipsMap] = useState<Map<string, GraphRelationship>>(new Map());
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedRelId, setSelectedRelId] = useState<string | null>(null);

  // Filters & Controls
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [selectedKind, setSelectedKind] = useState<string>("all");
  const [selectedRelKind, setSelectedRelKind] = useState<string>("all");
  const [hopDepth, setHopDepth] = useState<number>(1);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [totalNodes, setTotalNodes] = useState(0);
  const [totalRelationships, setTotalRelationships] = useState(0);

  // History tracking of expanded peripheral nodes to support collapse
  const initialEntityIdsRef = useRef<Set<string>>(new Set());
  const [expandedNodesCount, setExpandedNodesCount] = useState(0);

  // Compute available entity and relationship kinds dynamically
  const availableKinds = useMemo(() => {
    const s = new Set<string>();
    entitiesMap.forEach((e) => {
      if (e.kind) s.add(e.kind);
    });
    return Array.from(s).sort();
  }, [entitiesMap]);

  const availableRelKinds = useMemo(() => {
    const s = new Set<string>();
    relationshipsMap.forEach((r) => {
      if (r.kind) s.add(r.kind);
    });
    return Array.from(s).sort();
  }, [relationshipsMap]);

  // Synchronize React Flow nodes & edges whenever maps change or selection changes
  const syncGraphToCanvas = useCallback(
    (
      currentEntities: Map<string, GraphEntity>,
      currentRels: Map<string, GraphRelationship>,
      selEntId: string | null,
      selRId: string | null
    ) => {
      const entityList = Array.from(currentEntities.values());
      const relList = Array.from(currentRels.values());

      // Filter by kind if active
      const filteredEntities = entityList.filter((e) => {
        if (selectedKind !== "all" && e.kind !== selectedKind) return false;
        return true;
      });
      const filteredEntityIds = new Set(filteredEntities.map((e) => e.id));

      // Filter relationships
      const filteredRels = relList.filter((r) => {
        if (!filteredEntityIds.has(r.source_id) || !filteredEntityIds.has(r.target_id)) return false;
        if (selectedRelKind !== "all" && r.kind !== selectedRelKind) return false;
        return true;
      });

      // Compute node degrees
      const degrees: Record<string, number> = {};
      filteredRels.forEach((r) => {
        degrees[r.source_id] = (degrees[r.source_id] || 0) + 1;
        degrees[r.target_id] = (degrees[r.target_id] || 0) + 1;
      });

      setNodes((prevNodes) => {
        const prevPosMap = new Map<string, { x: number; y: number }>();
        prevNodes.forEach((n) => prevPosMap.set(n.id, n.position));

        const positions = calculateInitialLayout(filteredEntities, filteredRels);

        return filteredEntities.map((ent, idx) => {
          const pos = prevPosMap.get(ent.id) || positions[idx] || { x: 200 + (idx % 5) * 180, y: 150 + Math.floor(idx / 5) * 120 };
          return {
            id: ent.id,
            type: "knowledgeNode",
            position: pos,
            data: {
              entity: ent,
              selected: ent.id === selEntId,
              degree: degrees[ent.id] || 0,
            },
          };
        });
      });

      setEdges(
        filteredRels.map((r) => {
          const isSelected = r.id === selRId;
          return {
            id: r.id,
            source: r.source_id,
            target: r.target_id,
            label: r.kind,
            type: "smoothstep",
            animated: isSelected,
            style: {
              stroke: isSelected ? "var(--accent, #6366f1)" : "var(--line-strong, #64748b)",
              strokeWidth: isSelected ? 2.5 : 1.5,
            },
            labelStyle: {
              fontSize: 10,
              fontWeight: 600,
              fill: isSelected ? "var(--accent, #6366f1)" : "var(--fg-1, #94a3b8)",
              background: "var(--bg-1)",
              padding: "2px 4px",
            },
            labelBgStyle: {
              fill: "var(--bg-0, #0f172a)",
              fillOpacity: 0.85,
            },
            labelBgPadding: [4, 2] as [number, number],
            labelBgBorderRadius: 4,
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: isSelected ? "var(--accent, #6366f1)" : "var(--line-strong, #64748b)",
              width: 14,
              height: 14,
            },
          };
        })
      );
    },
    [selectedKind, selectedRelKind, setEdges, setNodes]
  );

  // Load subgraph from server
  const loadGraph = useCallback(
    async (opts?: { search?: string; focus_id?: string }) => {
      if (!project?.id) return;
      setLoading(true);
      setErr(null);
      try {
        const res: GraphSubgraph = await api.graphSubgraph(project.id, {
          search: opts?.search !== undefined ? opts.search : activeSearch,
          focus_id: opts?.focus_id,
          limit: 60,
          hop_depth: hopDepth,
        });

        const newEntMap = new Map<string, GraphEntity>();
        res.nodes.forEach((n) => newEntMap.set(n.id, n));

        const newRelMap = new Map<string, GraphRelationship>();
        res.relationships.forEach((r) => newRelMap.set(r.id, r));

        setEntitiesMap(newEntMap);
        setRelationshipsMap(newRelMap);
        setTruncated(res.truncated);
        setTotalNodes(res.total_nodes);
        setTotalRelationships(res.total_relationships);

        initialEntityIdsRef.current = new Set(newEntMap.keys());
        setExpandedNodesCount(0);

        const targetFocus = res.focus_id || opts?.focus_id || (res.nodes.length > 0 ? res.nodes[0].id : null);
        if (opts?.search && targetFocus) {
          setSelectedEntityId(targetFocus);
          setSelectedRelId(null);
        }

        syncGraphToCanvas(newEntMap, newRelMap, targetFocus, null);

        setTimeout(() => {
          fitView({ padding: 0.2, duration: 400 });
        }, 80);
      } catch (e: any) {
        setErr(e?.message || "Failed to load Knowledge Graph data");
      } finally {
        setLoading(false);
      }
    },
    [activeSearch, fitView, hopDepth, project?.id, syncGraphToCanvas]
  );

  // Initial load
  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // Handle Search submit
  const handleSearchSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const q = searchQuery.trim();
    setActiveSearch(q);
    loadGraph({ search: q });
  };

  const handleClearSearch = () => {
    setSearchQuery("");
    setActiveSearch("");
    loadGraph({ search: "" });
  };

  // Node Click
  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedEntityId(node.id);
      setSelectedRelId(null);
      syncGraphToCanvas(entitiesMap, relationshipsMap, node.id, null);
    },
    [entitiesMap, relationshipsMap, syncGraphToCanvas]
  );

  // Edge Click
  const handleEdgeClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      setSelectedRelId(edge.id);
      setSelectedEntityId(null);
      syncGraphToCanvas(entitiesMap, relationshipsMap, null, edge.id);
    },
    [entitiesMap, relationshipsMap, syncGraphToCanvas]
  );

  // Canvas pane click -> deselect
  const handlePaneClick = useCallback(() => {
    setSelectedEntityId(null);
    setSelectedRelId(null);
    syncGraphToCanvas(entitiesMap, relationshipsMap, null, null);
  }, [entitiesMap, relationshipsMap, syncGraphToCanvas]);

  // Expand node neighbours on demand
  const handleExpandNeighbours = useCallback(
    async (entityId: string) => {
      if (!project?.id) return;
      setLoading(true);
      try {
        const paths = await api.graphEntityNeighbors(project.id, entityId, {
          direction: "both",
          max_depth: 1,
          limit: 30,
        });

        const updatedEntMap = new Map(entitiesMap);
        const updatedRelMap = new Map(relationshipsMap);

        const parentNode = nodes.find((n) => n.id === entityId);
        const parentPos = parentNode?.position || { x: 300, y: 200 };

        let addedCount = 0;
        const newNodes: GraphEntity[] = [];

        paths.forEach((p) => {
          p.nodes.forEach((n) => {
            if (!updatedEntMap.has(n.id)) {
              updatedEntMap.set(n.id, n);
              newNodes.push(n);
              addedCount++;
            }
          });
          p.relationships.forEach((r) => {
            if (!updatedRelMap.has(r.id)) {
              updatedRelMap.set(r.id, r);
            }
          });
        });

        // Set initial positions for newly expanded nodes arranged radially around the parent
        setNodes((prev) => {
          const prevMap = new Map(prev.map((n) => [n.id, n]));
          const radius = 180;
          newNodes.forEach((n, idx) => {
            const angle = (2 * Math.PI * idx) / Math.max(1, newNodes.length);
            const x = Math.round(parentPos.x + radius * Math.cos(angle));
            const y = Math.round(parentPos.y + radius * Math.sin(angle));
            prevMap.set(n.id, {
              id: n.id,
              type: "knowledgeNode",
              position: { x, y },
              data: {
                entity: n,
                selected: false,
                degree: 1,
              },
            });
          });
          return Array.from(prevMap.values());
        });

        setEntitiesMap(updatedEntMap);
        setRelationshipsMap(updatedRelMap);
        setExpandedNodesCount((prev) => prev + addedCount);

        syncGraphToCanvas(updatedEntMap, updatedRelMap, entityId, selectedRelId);
      } catch (e: any) {
        alert(`Failed to expand neighbours: ${e?.message || e}`);
      } finally {
        setLoading(false);
      }
    },
    [entitiesMap, nodes, project?.id, relationshipsMap, selectedRelId, setNodes, syncGraphToCanvas]
  );

  // Collapse branches back to initial set
  const handleCollapseBranches = useCallback(() => {
    if (initialEntityIdsRef.current.size === 0) return;
    const initialIds = initialEntityIdsRef.current;

    const prunedEntMap = new Map<string, GraphEntity>();
    entitiesMap.forEach((e, id) => {
      if (initialIds.has(id) || id === selectedEntityId) {
        prunedEntMap.set(id, e);
      }
    });

    const prunedRelMap = new Map<string, GraphRelationship>();
    relationshipsMap.forEach((r, id) => {
      if (prunedEntMap.has(r.source_id) && prunedEntMap.has(r.target_id)) {
        prunedRelMap.set(id, r);
      }
    });

    setEntitiesMap(prunedEntMap);
    setRelationshipsMap(prunedRelMap);
    setExpandedNodesCount(0);
    syncGraphToCanvas(prunedEntMap, prunedRelMap, selectedEntityId, selectedRelId);
    setTimeout(() => fitView({ duration: 300 }), 50);
  }, [entitiesMap, fitView, relationshipsMap, selectedEntityId, selectedRelId, syncGraphToCanvas]);

  // Center selected entity in canvas
  const handleCenterNode = useCallback(
    (entityId: string) => {
      const node = nodes.find((n) => n.id === entityId);
      if (node) {
        setCenter(node.position.x + 80, node.position.y + 40, { zoom: 1.1, duration: 400 });
      }
    },
    [nodes, setCenter]
  );

  // Inspector selected entity details
  const selectedEntity = useMemo(() => {
    if (!selectedEntityId) return null;
    return entitiesMap.get(selectedEntityId) || null;
  }, [entitiesMap, selectedEntityId]);

  // Inspector selected relationship details
  const selectedRelationship = useMemo(() => {
    if (!selectedRelId) return null;
    return relationshipsMap.get(selectedRelId) || null;
  }, [relationshipsMap, selectedRelId]);

  // Connected relationships for inspector
  const entityConnections = useMemo(() => {
    if (!selectedEntityId) return { incoming: [], outgoing: [] };
    const incoming: { rel: GraphRelationship; other: GraphEntity | undefined }[] = [];
    const outgoing: { rel: GraphRelationship; other: GraphEntity | undefined }[] = [];

    relationshipsMap.forEach((r) => {
      if (r.target_id === selectedEntityId) {
        incoming.push({ rel: r, other: entitiesMap.get(r.source_id) });
      }
      if (r.source_id === selectedEntityId) {
        outgoing.push({ rel: r, other: entitiesMap.get(r.target_id) });
      }
    });

    return { incoming, outgoing };
  }, [entitiesMap, relationshipsMap, selectedEntityId]);

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
      {/* 1. Explorer Toolbar */}
      <div
        className="row spread"
        style={{
          padding: "12px 16px",
          borderBottom: "1px solid var(--line)",
          background: "var(--bg-1)",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        {/* Search */}
        <form onSubmit={handleSearchSubmit} className="row gap2" style={{ alignItems: "center", flex: "1 1 240px", maxWidth: 360 }}>
          <div style={{ position: "relative", width: "100%" }}>
            <input
              type="text"
              className="input mono-sm"
              style={{ width: "100%", paddingLeft: 30, paddingRight: activeSearch ? 28 : 10, height: 32 }}
              placeholder="Search entity (e.g. OLMX, MacStudio)…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <span style={{ position: "absolute", left: 9, top: 8, color: "var(--fg-2)" }}>
              <Icon name="search" size={14} />
            </span>
            {searchQuery && (
              <button
                type="button"
                onClick={handleClearSearch}
                style={{
                  position: "absolute",
                  right: 6,
                  top: 7,
                  background: "transparent",
                  border: "none",
                  color: "var(--fg-2)",
                  cursor: "pointer",
                }}
              >
                <Icon name="close" size={13} />
              </button>
            )}
          </div>
          <button type="submit" className="btn btn-secondary btn-sm" disabled={loading} style={{ height: 32 }}>
            Find
          </button>
        </form>

        {/* Filters & Depth */}
        <div className="row gap2" style={{ alignItems: "center", flexWrap: "wrap" }}>
          {/* Entity Kind Filter */}
          <div className="row gap1" style={{ alignItems: "center" }}>
            <span className="t-caption fg-2">Type:</span>
            <select
              className="input mono-sm"
              style={{ height: 32, padding: "2px 8px" }}
              value={selectedKind}
              onChange={(e) => {
                setSelectedKind(e.target.value);
              }}
            >
              <option value="all">All Types</option>
              {availableKinds.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </div>

          {/* Relationship Kind Filter */}
          <div className="row gap1" style={{ alignItems: "center" }}>
            <span className="t-caption fg-2">Rel:</span>
            <select
              className="input mono-sm"
              style={{ height: 32, padding: "2px 8px" }}
              value={selectedRelKind}
              onChange={(e) => {
                setSelectedRelKind(e.target.value);
              }}
            >
              <option value="all">All Rels</option>
              {availableRelKinds.map((rk) => (
                <option key={rk} value={rk}>
                  {rk}
                </option>
              ))}
            </select>
          </div>

          {/* Hop Depth */}
          <div className="row gap1" style={{ alignItems: "center" }}>
            <span className="t-caption fg-2">Hops:</span>
            <select
              className="input mono-sm"
              style={{ height: 32, padding: "2px 8px" }}
              value={hopDepth}
              onChange={(e) => {
                const d = parseInt(e.target.value, 10);
                setHopDepth(d);
              }}
            >
              <option value={1}>1-hop</option>
              <option value={2}>2-hops</option>
            </select>
          </div>

          {/* Fit View Button */}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => fitView({ padding: 0.2, duration: 300 })}
            title="Fit canvas to view"
            style={{ height: 32 }}
          >
            <Icon name="layers" size={13} /> Fit
          </button>

          {/* Refresh Button */}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => loadGraph()}
            disabled={loading}
            title="Reload graph from LadybugDB"
            style={{ height: 32 }}
          >
            <Icon name={loading ? "refresh" : "check"} size={13} style={loading ? { animation: "spin 1s linear infinite" } : {}} />
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {/* Truncation & Status Notice */}
      {truncated && (
        <div
          className="row spread"
          style={{
            padding: "6px 16px",
            background: "rgba(245, 158, 11, 0.12)",
            borderBottom: "1px solid rgba(245, 158, 11, 0.3)",
            color: "var(--warn, #d97706)",
            fontSize: 12,
            alignItems: "center",
          }}
        >
          <div className="row gap2" style={{ alignItems: "center" }}>
            <Icon name="clock" size={13} />
            <span>
              Bounded visualization: Showing {entitiesMap.size} of {totalNodes} entities in scope. Use Search or Filters to inspect specific entities.
            </span>
          </div>
          <span className="t-micro mono">Hop depth capped</span>
        </div>
      )}

      {err && (
        <div style={{ padding: "8px 16px", background: "rgba(220, 38, 38, 0.1)", color: "var(--err)", fontSize: 13 }}>
          {err}
        </div>
      )}

      {/* 2. Main Interactive Area: Canvas + Side Inspector */}
      <div className="row" style={{ minHeight: 520, height: 560, position: "relative" }}>
        {/* Graph Canvas */}
        <div style={{ flex: 1, minWidth: 0, height: "100%", background: "var(--canvas-bg, #09090b)" }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={handleNodeClick}
            onEdgeClick={handleEdgeClick}
            onPaneClick={handlePaneClick}
            nodeTypes={NODE_TYPES}
            fitView
            minZoom={0.2}
            maxZoom={2.5}
            defaultEdgeOptions={{ type: "smoothstep" }}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--canvas-grid, rgba(255,255,255,0.08))" />
            <Controls showInteractive={false} style={{ margin: 12 }} />
            <MiniMap
              nodeStrokeColor="#6366f1"
              nodeColor="#1e1e24"
              nodeBorderRadius={4}
              style={{
                width: 130,
                height: 90,
                background: "var(--bg-1, #1e1e24)",
                border: "1px solid var(--line)",
                borderRadius: 6,
                margin: 12,
              }}
            />
          </ReactFlow>

          {nodes.length === 0 && !loading && (
            <div
              className="col center"
              style={{
                position: "absolute",
                top: "50%",
                left: "40%",
                transform: "translate(-50%, -50%)",
                textAlign: "center",
                gap: 8,
                color: "var(--fg-2)",
                pointerEvents: "none",
              }}
            >
              <Icon name="n_router" size={32} />
              <div className="t-h3">No entities found in scope</div>
              <div className="t-caption fg-2">
                {activeSearch ? `No matches for "${activeSearch}". Try another search term.` : "Store memories or enable autonomous learning to populate the graph."}
              </div>
            </div>
          )}
        </div>

        {/* 3. Side Inspector Panel */}
        <div
          className="col scroll-y"
          style={{
            width: 360,
            flex: "none",
            borderLeft: "1px solid var(--line)",
            background: "var(--bg-1)",
            padding: 16,
            gap: 14,
          }}
        >
          {selectedEntity ? (
            /* Entity Inspector */
            <div className="col gap3">
              <div className="row spread" style={{ alignItems: "flex-start" }}>
                <div>
                  <div className="row gap2" style={{ alignItems: "center" }}>
                    <span
                      className="badge"
                      style={{
                        ...getKindStyle(selectedEntity.kind),
                        fontSize: 10,
                        textTransform: "uppercase",
                        fontWeight: 700,
                      }}
                    >
                      {selectedEntity.kind}
                    </span>
                    <span className="mono t-caption fg-2">Entity Details</span>
                  </div>
                  <div className="t-h2" style={{ marginTop: 4, wordBreak: "break-word" }}>
                    {selectedEntity.name}
                  </div>
                </div>
                <button
                  className="btn btn-secondary btn-sm"
                  style={{ padding: "4px 8px" }}
                  onClick={() => setSelectedEntityId(null)}
                  title="Close inspector"
                >
                  <Icon name="close" size={13} />
                </button>
              </div>

              {/* Action Buttons */}
              <div className="row gap2" style={{ flexWrap: "wrap" }}>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => handleExpandNeighbours(selectedEntity.id)}
                  disabled={loading}
                >
                  <Icon name="plus" size={13} /> Expand 1-Hop
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => handleCenterNode(selectedEntity.id)}
                >
                  <Icon name="search" size={13} /> Center
                </button>
                {expandedNodesCount > 0 && (
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={handleCollapseBranches}
                    title="Collapse expanded branches"
                  >
                    <Icon name="minus" size={13} /> Collapse
                  </button>
                )}
              </div>

              {/* Aliases */}
              {(() => {
                const aliases = extractAliases(selectedEntity);
                return (
                  <div className="card" style={{ padding: 10, background: "var(--bg-0)" }}>
                    <div className="t-micro fg-2" style={{ marginBottom: 4 }}>Known Aliases</div>
                    {aliases.length > 0 ? (
                      <div className="row gap1" style={{ flexWrap: "wrap" }}>
                        {aliases.map((a, i) => (
                          <span key={i} className="chip chip-mono" style={{ fontSize: 11 }}>
                            {a}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <div className="t-caption fg-2">No aliases recorded for this entity.</div>
                    )}
                  </div>
                );
              })()}

              {/* Description */}
              <div className="card" style={{ padding: 10, background: "var(--bg-0)" }}>
                <div className="t-micro fg-2" style={{ marginBottom: 4 }}>Description</div>
                <div className="t-body-sm" style={{ whiteSpace: "pre-wrap", color: "var(--fg-1)" }}>
                  {selectedEntity.description || "(No description stored)"}
                </div>
              </div>

              {/* Properties Table */}
              <div className="col gap1">
                <div className="t-micro fg-2">Properties &amp; Provenance</div>
                <div className="card col gap2" style={{ padding: 10, background: "var(--bg-0)", fontSize: 12 }}>
                  <div className="row spread">
                    <span className="fg-2">Canonical Name:</span>
                    <span className="mono-sm truncate" style={{ maxWidth: 180 }}>{selectedEntity.canonical_name || "—"}</span>
                  </div>
                  <div className="row spread">
                    <span className="fg-2">Source:</span>
                    <span className="mono-sm">{selectedEntity.source}</span>
                  </div>
                  <div className="row spread">
                    <span className="fg-2">Confidence:</span>
                    <span className="mono-sm">{Math.round(selectedEntity.confidence * 100)}%</span>
                  </div>
                  <div className="row spread">
                    <span className="fg-2">Entity ID:</span>
                    <span className="mono-sm truncate" style={{ maxWidth: 180 }} title={selectedEntity.id}>
                      {selectedEntity.id}
                    </span>
                  </div>
                  <div className="row spread">
                    <span className="fg-2">Updated:</span>
                    <span className="fg-2">
                      {selectedEntity.updated_at ? new Date(selectedEntity.updated_at).toLocaleDateString() : "—"}
                    </span>
                  </div>
                </div>
              </div>

              {/* Connected Relationships */}
              <div className="col gap2">
                <div className="t-micro fg-2">
                  Connected Relationships ({entityConnections.outgoing.length + entityConnections.incoming.length})
                </div>

                {entityConnections.outgoing.map(({ rel, other }) => (
                  <div
                    key={rel.id}
                    className="card row spread"
                    style={{ padding: 8, background: "var(--bg-0)", alignItems: "center", cursor: "pointer" }}
                    onClick={() => {
                      if (other) {
                        setSelectedEntityId(other.id);
                        handleCenterNode(other.id);
                      }
                    }}
                  >
                    <div className="row gap2" style={{ alignItems: "center", minWidth: 0 }}>
                      <span className="badge" style={{ fontSize: 10, background: "rgba(99,102,241,0.15)", color: "var(--accent)" }}>
                        -{rel.kind}→
                      </span>
                      <span className="t-body-sm truncate" style={{ fontWeight: 550 }}>
                        {other?.name || rel.target_id}
                      </span>
                    </div>
                    <Icon name="arrow-right" size={13} />
                  </div>
                ))}

                {entityConnections.incoming.map(({ rel, other }) => (
                  <div
                    key={rel.id}
                    className="card row spread"
                    style={{ padding: 8, background: "var(--bg-0)", alignItems: "center", cursor: "pointer" }}
                    onClick={() => {
                      if (other) {
                        setSelectedEntityId(other.id);
                        handleCenterNode(other.id);
                      }
                    }}
                  >
                    <div className="row gap2" style={{ alignItems: "center", minWidth: 0 }}>
                      <span className="badge" style={{ fontSize: 10, background: "rgba(16,185,129,0.15)", color: "var(--ok)" }}>
                        ←{rel.kind}-
                      </span>
                      <span className="t-body-sm truncate" style={{ fontWeight: 550 }}>
                        {other?.name || rel.source_id}
                      </span>
                    </div>
                    <Icon name="arrow-right" size={13} />
                  </div>
                ))}

                {entityConnections.outgoing.length === 0 && entityConnections.incoming.length === 0 && (
                  <div className="t-caption fg-2">No visible connections in currently loaded graph. Click Expand to discover neighbours.</div>
                )}
              </div>
            </div>
          ) : selectedRelationship ? (
            /* Relationship Inspector */
            <div className="col gap3">
              <div className="row spread" style={{ alignItems: "flex-start" }}>
                <div>
                  <div className="row gap2" style={{ alignItems: "center" }}>
                    <span className="badge" style={{ background: "rgba(99,102,241,0.15)", color: "var(--accent)" }}>
                      {selectedRelationship.kind}
                    </span>
                    <span className="mono t-caption fg-2">Relationship</span>
                  </div>
                  <div className="t-h2" style={{ marginTop: 4 }}>
                    {selectedRelationship.kind}
                  </div>
                </div>
                <button
                  className="btn btn-secondary btn-sm"
                  style={{ padding: "4px 8px" }}
                  onClick={() => setSelectedRelId(null)}
                  title="Close inspector"
                >
                  <Icon name="close" size={13} />
                </button>
              </div>

              {/* Endpoints */}
              <div className="col gap2">
                <div className="t-micro fg-2">Connected Endpoints</div>
                <div
                  className="card row spread"
                  style={{ padding: 10, background: "var(--bg-0)", cursor: "pointer" }}
                  onClick={() => {
                    setSelectedEntityId(selectedRelationship.source_id);
                    setSelectedRelId(null);
                    handleCenterNode(selectedRelationship.source_id);
                  }}
                >
                  <div>
                    <div className="t-micro fg-2">Source Entity</div>
                    <div className="t-body-sm" style={{ fontWeight: 600 }}>
                      {entitiesMap.get(selectedRelationship.source_id)?.name || selectedRelationship.source_id}
                    </div>
                  </div>
                  <Icon name="arrow-right" size={14} />
                </div>

                <div
                  className="card row spread"
                  style={{ padding: 10, background: "var(--bg-0)", cursor: "pointer" }}
                  onClick={() => {
                    setSelectedEntityId(selectedRelationship.target_id);
                    setSelectedRelId(null);
                    handleCenterNode(selectedRelationship.target_id);
                  }}
                >
                  <div>
                    <div className="t-micro fg-2">Target Entity</div>
                    <div className="t-body-sm" style={{ fontWeight: 600 }}>
                      {entitiesMap.get(selectedRelationship.target_id)?.name || selectedRelationship.target_id}
                    </div>
                  </div>
                  <Icon name="arrow-right" size={14} />
                </div>
              </div>

              {/* Provenance & Properties */}
              <div className="col gap1">
                <div className="t-micro fg-2">Provenance &amp; Metadata</div>
                <div className="card col gap2" style={{ padding: 10, background: "var(--bg-0)", fontSize: 12 }}>
                  <div className="row spread">
                    <span className="fg-2">Confidence:</span>
                    <span className="mono-sm">{Math.round((selectedRelationship.confidence || 1.0) * 100)}%</span>
                  </div>
                  <div className="row spread">
                    <span className="fg-2">Source:</span>
                    <span className="mono-sm">{selectedRelationship.source}</span>
                  </div>
                  <div className="col gap1">
                    <span className="fg-2">Supporting Provenance:</span>
                    <span className="mono-sm" style={{ wordBreak: "break-word", color: "var(--fg-1)" }}>
                      {selectedRelationship.provenance || "manual"}
                    </span>
                  </div>
                  <div className="row spread">
                    <span className="fg-2">Relationship ID:</span>
                    <span className="mono-sm truncate" style={{ maxWidth: 180 }} title={selectedRelationship.id}>
                      {selectedRelationship.id}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            /* Empty Inspector State */
            <div className="col center" style={{ height: "100%", textAlign: "center", gap: 10, padding: 20, color: "var(--fg-2)" }}>
              <Icon name="n_router" size={28} />
              <div className="t-h3" style={{ color: "var(--fg-1)" }}>Inspect Knowledge</div>
              <div className="t-caption" style={{ lineHeight: "18px" }}>
                Click any entity node or relationship edge on the canvas to inspect real LadybugDB properties, aliases, and supporting provenance.
              </div>
              <div className="card col gap1" style={{ marginTop: 12, padding: 10, textAlign: "left", width: "100%", background: "var(--bg-0)" }}>
                <div className="t-micro fg-2">Visible Graph Scope</div>
                <div className="row spread" style={{ fontSize: 12 }}>
                  <span className="fg-2">Visible Nodes:</span>
                  <span className="mono">{nodes.length}</span>
                </div>
                <div className="row spread" style={{ fontSize: 12 }}>
                  <span className="fg-2">Visible Edges:</span>
                  <span className="mono">{edges.length}</span>
                </div>
                <div className="row spread" style={{ fontSize: 12 }}>
                  <span className="fg-2">Total Project Scope:</span>
                  <span className="mono">{totalNodes} nodes</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
