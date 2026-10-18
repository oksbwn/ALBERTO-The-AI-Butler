"use client";

import { useCallback, useEffect, useState } from "react";
import { Icon } from "../icons";
import {
  api,
  GraphStats,
  OntologyEntityType,
  OntologyRelationshipType,
} from "@/lib/api";
import { KnowledgeGraphExplorer } from "../canvas/KnowledgeGraphExplorer";
import { KnowledgeHistory } from "./knowledge-history";
import { OntologyReviewQueue } from "./ontology-review-queue";

export function KnowledgeGraphScreen({ project }: { project: any }) {
  const [tab, setTab] = useState<"visualizer" | "entities" | "ontology" | "approvals" | "engine">("visualizer");
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [entities, setEntities] = useState<any[]>([]);
  const [ontologyEntityTypes, setOntologyEntityTypes] = useState<OntologyEntityType[]>([]);
  const [ontologyRelTypes, setOntologyRelTypes] = useState<OntologyRelationshipType[]>([]);
  const [loading, setLoading] = useState(true);
  const [histOpen, setHistOpen] = useState(false);

  const reload = useCallback(() => {
    if (!project?.id) return;
    setLoading(true);
    Promise.all([
      api.graphStats(project.id).catch(() => null),
      api.graphEntities(project.id, { limit: 100 }).catch(() => []),
      api.listOntologyEntityTypes(project.id).catch(() => []),
      api.listOntologyRelationshipTypes(project.id).catch(() => []),
    ])
      .then(([s, ents, ets, rts]) => {
        setStats(s);
        setEntities(ents || []);
        setOntologyEntityTypes(ets || []);
        setOntologyRelTypes(rts || []);
      })
      .finally(() => setLoading(false));
  }, [project?.id]);

  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <div className="col" style={{ flex: 1, minHeight: 0 }}>
      {/* Header */}
      <div
        style={{
          padding: "18px 32px 14px",
          borderBottom: "1px solid var(--line)",
          background: "var(--bg-1)",
        }}
      >
        <div className="row spread" style={{ alignItems: "flex-start" }}>
          <div>
            <div className="row gap2" style={{ alignItems: "center" }}>
              <span className="t-display">Knowledge Graph</span>
              <span className="typechip" style={{ fontWeight: 600 }}>LadybugDB</span>
            </div>
            <div className="fg-1 t-caption" style={{ marginTop: 3 }}>
              LadybugDB native property graph, entities, directed relationships, and domain ontology schema.
            </div>
          </div>
          <div className="row gap2" style={{ alignItems: "center" }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setHistOpen(true)}
              disabled={!project?.id}
              title="Audit trail of graph mutations"
            >
              <Icon name="clock" size={13} /> History
            </button>
          </div>
        </div>
      </div>

      <KnowledgeHistory project={project} open={histOpen} onClose={() => setHistOpen(false)} />

      {/* Body */}
      <div className="scroll-y" style={{ flex: 1, minWidth: 0, padding: "20px 32px 48px" }}>
        <div style={{ maxWidth: 1600, width: "100%", margin: "0 auto" }}>
          <div className="col gap3">
            {/* Inner Tabs */}
            <div
              className="row spread"
              style={{
                alignItems: "center",
                borderBottom: "1px solid var(--line)",
                paddingBottom: 10,
              }}
            >
              <div
                className="row gap1"
                style={{
                  background: "var(--bg-1)",
                  padding: 3,
                  borderRadius: 8,
                  border: "1px solid var(--line)",
                }}
              >
                {[
                  { id: "visualizer", label: "Graph Visualizer", icon: "workflow" },
                  { id: "entities", label: "Entities & Relations", icon: "list" },
                  { id: "ontology", label: "Domain Ontology", icon: "layers" },
                  { id: "approvals", label: "Ontology Approvals", icon: "shield-check" },
                  { id: "engine", label: "Engine Status", icon: "activity" },
                ].map((t) => {
                  const on = tab === t.id;
                  return (
                    <button
                      key={t.id}
                      onClick={() => setTab(t.id as any)}
                      className="row gap1"
                      style={{
                        alignItems: "center",
                        padding: "6px 14px",
                        borderRadius: 6,
                        border: "none",
                        cursor: "pointer",
                        fontSize: 12.5,
                        fontWeight: on ? 600 : 500,
                        background: on ? "var(--bg-3)" : "transparent",
                        color: on ? "var(--fg-0)" : "var(--fg-2)",
                        transition: "all var(--dur-fast)",
                      }}
                    >
                      <Icon name={t.icon as any} size={13} />
                      <span>{t.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {tab === "visualizer" && (
              <div className="col gap3">
                <div className="card" style={{ padding: "14px 20px" }}>
                  <div className="row spread" style={{ alignItems: "center" }}>
                    <div className="row gap2" style={{ alignItems: "center" }}>
                      <span className="t-h2">LadybugDB Interactive Graph Explorer</span>
                      <span className="badge" style={{ color: "var(--ok)", background: "rgba(34,197,94,0.15)" }}>
                        Online
                      </span>
                    </div>
                    <span className="fg-2 t-caption">Click nodes to inspect properties and traversals</span>
                  </div>
                </div>
                <KnowledgeGraphExplorer project={project} />
              </div>
            )}

            {tab === "entities" && (
              <div className="card" style={{ overflow: "hidden" }}>
                <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--line)" }}>
                  <div className="t-h2">Structured Entities in Scope</div>
                  <div className="fg-2 t-caption" style={{ marginTop: 2 }}>
                    Authoritative graph nodes with normalized canonical keys and trust confidence scores.
                  </div>
                </div>
                <table className="tbl" style={{ width: "100%" }}>
                  <thead>
                    <tr>
                      <th style={{ width: "24%" }}>Name</th>
                      <th style={{ width: "16%" }}>Kind</th>
                      <th style={{ width: "26%" }}>Canonical Key</th>
                      <th style={{ width: "20%" }}>Source / Provenance</th>
                      <th style={{ width: "14%" }}>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entities.map((e) => (
                      <tr key={e.id}>
                        <td style={{ fontWeight: 600 }}>{e.name}</td>
                        <td>
                          <span className="typechip">{e.kind}</span>
                        </td>
                        <td className="mono-sm fg-2">{e.canonical_name || e.name?.toLowerCase()}</td>
                        <td className="mono-sm fg-2">{e.source || "conversational_curator"}</td>
                        <td>
                          <span className="chip chip-mono">{Math.round((e.confidence || 1.0) * 100)}%</span>
                        </td>
                      </tr>
                    ))}
                    {entities.length === 0 && (
                      <tr>
                        <td colSpan={5} style={{ textAlign: "center", padding: 32, color: "var(--fg-2)" }}>
                          No graph entities registered yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {tab === "ontology" && (
              <div className="row gap3" style={{ alignItems: "flex-start" }}>
                <div className="card grow" style={{ padding: 20 }}>
                  <div className="t-h2" style={{ marginBottom: 4 }}>Allowed Entity Types</div>
                  <div className="fg-2 t-caption" style={{ marginBottom: 14 }}>
                    Standard schema entity kinds recognized by Alberto.
                  </div>
                  <div className="col gap2">
                    {ontologyEntityTypes.map((et) => (
                      <div
                        key={et.canonical_key}
                        className="card row spread"
                        style={{ padding: 12, background: "var(--bg-1)" }}
                      >
                        <span className="typechip" style={{ fontWeight: 600 }}>
                          {et.display_name || et.canonical_key}
                        </span>
                        <span className="t-caption fg-2">{et.description || "System entity type"}</span>
                      </div>
                    ))}
                    {ontologyEntityTypes.length === 0 && (
                      <div className="fg-2 t-body-sm">Standard system ontology active.</div>
                    )}
                  </div>
                </div>

                <div className="card grow" style={{ padding: 20 }}>
                  <div className="t-h2" style={{ marginBottom: 4 }}>Relationship Types</div>
                  <div className="fg-2 t-caption" style={{ marginBottom: 14 }}>
                    Directed edges allowed between graph nodes.
                  </div>
                  <div className="col gap2">
                    {ontologyRelTypes.map((rt) => (
                      <div
                        key={rt.canonical_key}
                        className="card row spread"
                        style={{ padding: 12, background: "var(--bg-1)" }}
                      >
                        <span className="mono" style={{ fontWeight: 600, color: "var(--accent)" }}>
                          {rt.canonical_key}
                        </span>
                        <span className="t-caption fg-2">{rt.description || "Relational edge"}</span>
                      </div>
                    ))}
                    {ontologyRelTypes.length === 0 && (
                      <div className="fg-2 t-body-sm">
                        Standard relationships active (RelatesTo, RunsOn, DeployedAt).
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {tab === "approvals" && <OntologyReviewQueue project={project} />}

            {tab === "engine" && (
              <div className="card" style={{ padding: 22 }}>
                <div className="row spread" style={{ alignItems: "flex-start", marginBottom: 16 }}>
                  <div>
                    <div className="row gap2" style={{ alignItems: "center" }}>
                      <span className="t-h1">LadybugDB Native Graph Engine</span>
                      <span className="badge" style={{ color: "var(--ok)", background: "rgba(34,197,94,0.15)" }}>
                        Active Singleton
                      </span>
                    </div>
                    <div className="fg-2 t-caption" style={{ marginTop: 4 }}>
                      Embedded C++/Cypher property graph database with isolated multi-tenant namespaces and owner lockfile.
                    </div>
                  </div>
                  <button className="btn btn-secondary btn-sm" onClick={reload} disabled={loading}>
                    <Icon name={loading ? "refresh" : "check"} size={13} /> Refresh
                  </button>
                </div>
                <div className="row gap3" style={{ flexWrap: "wrap", marginTop: 12 }}>
                  <div className="card grow" style={{ padding: 16, minWidth: 220, background: "var(--bg-1)" }}>
                    <div className="t-caption fg-2">Total Scoped Entities</div>
                    <div className="t-display" style={{ marginTop: 4 }}>{stats?.entity_count ?? 0}</div>
                  </div>
                  <div className="card grow" style={{ padding: 16, minWidth: 220, background: "var(--bg-1)" }}>
                    <div className="t-caption fg-2">Total Scoped Relationships</div>
                    <div className="t-display" style={{ marginTop: 4 }}>{stats?.relationship_count ?? 0}</div>
                  </div>
                  <div className="card grow" style={{ padding: 16, minWidth: 220, background: "var(--bg-1)" }}>
                    <div className="t-caption fg-2">Average Degree</div>
                    <div className="t-display" style={{ marginTop: 4 }}>
                      {stats?.entity_count
                        ? ((stats.relationship_count * 2) / stats.entity_count).toFixed(2)
                        : "0.00"}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
