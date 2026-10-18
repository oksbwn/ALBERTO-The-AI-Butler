"use client";

import { useCallback, useEffect, useState } from "react";
import { Icon } from "../icons";
import { Segmented } from "../primitives";
import { api, SearchHit } from "@/lib/api";
import { ChunkMap } from "./chunk-map";
import { KnowledgeHistory } from "./knowledge-history";

export function KnowledgeVectorScreen({ project }: { project: any }) {
  const [tab, setTab] = useState<"chunks" | "engine" | "probe">("chunks");
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [histOpen, setHistOpen] = useState(false);

  const loadStatus = useCallback(() => {
    if (!project?.id) return;
    setLoading(true);
    api
      .memoryStatus(project.id)
      .then((s) => setStatus(s))
      .catch(() => setStatus(null))
      .finally(() => setLoading(false));
  }, [project?.id]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const chroma = status?.chroma || {};

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
              <span className="t-display">Vector Store &amp; Index</span>
              <span
                className="badge"
                style={{
                  background:
                    chroma.mode === "native"
                      ? "rgba(34, 197, 94, 0.15)"
                      : "rgba(234, 179, 8, 0.15)",
                  color:
                    chroma.mode === "native"
                      ? "var(--ok, #22c55e)"
                      : "var(--warn, #eab308)",
                  fontWeight: 600,
                  fontSize: 11,
                }}
              >
                {chroma.mode === "native"
                  ? "Native ChromaDB"
                  : chroma.mode === "fallback"
                  ? "Fallback JSON Store"
                  : "Chroma Engine"}
              </span>
            </div>
            <div className="fg-1 t-caption" style={{ marginTop: 3 }}>
              ChromaDB embeddings persistence, chunk distribution visualizer, and vector similarity testing.
            </div>
          </div>
          <div className="row gap2" style={{ alignItems: "center" }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setHistOpen(true)}
              disabled={!project?.id}
              title="Audit trail of knowledge updates"
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
                  { id: "chunks", label: "Chunk Map & Inspector", icon: "layers" },
                  { id: "engine", label: "Vector Engine & Durability", icon: "activity" },
                  { id: "probe", label: "Direct Vector Probe", icon: "search" },
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

            {/* Tab 1: Chunk Map */}
            {tab === "chunks" && <ChunkMap project={project} />}

            {/* Tab 2: Vector Engine & Durability */}
            {tab === "engine" && (
              <div className="col gap3">
                <div className="card" style={{ padding: 22 }}>
                  <div className="row spread" style={{ alignItems: "center", marginBottom: 16 }}>
                    <div>
                      <div className="row gap2" style={{ alignItems: "center" }}>
                        <span className="t-h1">ChromaDB Engine Diagnostics</span>
                        <span
                          className="badge"
                          style={{
                            background:
                              chroma.durable
                                ? "rgba(34, 197, 94, 0.15)"
                                : "rgba(234, 179, 8, 0.15)",
                            color:
                              chroma.durable
                                ? "var(--ok, #22c55e)"
                                : "var(--warn, #eab308)",
                          }}
                        >
                          {chroma.durable ? "Persistent Disk Store" : "In-Memory Volatile"}
                        </span>
                      </div>
                      <div className="fg-2 t-caption" style={{ marginTop: 4 }}>
                        Manages vector collections, embedding dimensions, and fallback compatibility.
                      </div>
                    </div>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={loadStatus}
                      disabled={loading}
                    >
                      <Icon
                        name={loading ? "refresh" : "check"}
                        size={13}
                        style={loading ? { animation: "spin 1s linear infinite" } : {}}
                      />
                      {loading ? "Checking…" : "Refresh Diagnostics"}
                    </button>
                  </div>

                  <div className="row gap3" style={{ flexWrap: "wrap", marginTop: 12 }}>
                    <div className="card grow" style={{ padding: 16, minWidth: 220, background: "var(--bg-1)" }}>
                      <div className="t-caption fg-2">Active Backend Mode</div>
                      <div className="t-display" style={{ marginTop: 4, textTransform: "capitalize" }}>
                        {chroma.backend || chroma.mode || "ChromaDB"}
                      </div>
                      <div className="fg-2 t-micro" style={{ marginTop: 4 }}>
                        Engine runtime: {chroma.mode === "native" ? "Native C++/Python Bindings" : "Safe JSON Storage"}
                      </div>
                    </div>
                    <div className="card grow" style={{ padding: 16, minWidth: 220, background: "var(--bg-1)" }}>
                      <div className="t-caption fg-2">Operational State</div>
                      <div
                        className="t-display"
                        style={{
                          marginTop: 4,
                          color: chroma.status === "healthy" ? "var(--ok)" : "var(--fg-0)",
                        }}
                      >
                        {chroma.status || (chroma.available ? "Healthy" : "Offline")}
                      </div>
                      <div className="fg-2 t-micro" style={{ marginTop: 4 }}>
                        Ready for similarity queries
                      </div>
                    </div>
                    <div className="card grow" style={{ padding: 16, minWidth: 320, background: "var(--bg-1)" }}>
                      <div className="t-caption fg-2">Persistent Vector Path</div>
                      <div className="mono-sm truncate" style={{ marginTop: 6 }}>
                        {chroma.path || "/data/chroma"}
                      </div>
                      <div className="fg-2 t-micro" style={{ marginTop: 4 }}>
                        Durability: {chroma.durable ? "Saved to disk" : "Memory-only"}
                      </div>
                    </div>
                  </div>

                  {chroma.mode === "fallback" && (
                    <div
                      className="card"
                      style={{
                        marginTop: 18,
                        padding: 16,
                        background: "rgba(234, 179, 8, 0.08)",
                        border: "1px solid rgba(234, 179, 8, 0.3)",
                      }}
                    >
                      <div className="row gap2" style={{ alignItems: "center", marginBottom: 6 }}>
                        <Icon name="bolt" size={16} style={{ color: "var(--warn)" }} />
                        <span style={{ fontWeight: 600, color: "var(--warn)" }}>
                          Operating in Fallback Mode
                        </span>
                      </div>
                      <div className="t-caption fg-1" style={{ lineHeight: "20px" }}>
                        Your vector store is safely persisting embeddings inside a structured JSON document store.
                        When native Chroma C++ dependencies are compiled for this platform, data can be
                        transparently indexed into native Chroma without loss.
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Tab 3: Direct Vector Probe */}
            {tab === "probe" && <VectorSearchProbe project={project} />}
          </div>
        </div>
      </div>
    </div>
  );
}

function VectorSearchProbe({ project }: { project: any }) {
  const [q, setQ] = useState("Alberto system architecture");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function runProbe() {
    if (busy || !q.trim() || !project?.id) return;
    setBusy(true);
    setErr(null);
    try {
      const h = await api.searchKnowledge(project.id, q, 8, undefined, false, false);
      setHits(h);
      setSearched(true);
    } catch (e: any) {
      setErr(e?.message || "Vector probe failed.");
      setHits([]);
      setSearched(true);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (project?.id && !searched) {
      runProbe();
    }
  }, [project?.id]);

  return (
    <div className="col gap3">
      <div className="card col gap3" style={{ padding: 22 }}>
        <div>
          <div className="t-h2">Direct Vector Distance Tester</div>
          <div className="fg-2 t-caption" style={{ marginTop: 2 }}>
            Executes pure vector embedding lookups against the active Chroma collection without lexical BM25 blending.
          </div>
        </div>

        <div className="row gap2" style={{ alignItems: "center" }}>
          <input
            className="input mono-sm"
            style={{ flex: 1, height: 38 }}
            placeholder="Query vector space (e.g. database schema)…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runProbe()}
          />
          <button
            className="btn btn-primary"
            style={{ height: 38, padding: "0 18px" }}
            onClick={runProbe}
            disabled={busy || !q.trim()}
          >
            <Icon
              name={busy ? "refresh" : "search"}
              size={14}
              style={busy ? { animation: "spin 1s linear infinite" } : {}}
            />
            {busy ? "Probing…" : "Probe Vectors"}
          </button>
        </div>

        {err && <div className="t-caption" style={{ color: "var(--err)" }}>{err}</div>}
      </div>

      <div className="col gap2">
        <div className="row spread" style={{ alignItems: "center" }}>
          <span className="t-h2">Closest Vector Hits ({hits.length})</span>
          <span className="fg-2 t-caption">Ranked by cosine distance</span>
        </div>

        {hits.map((h, i) => (
          <div key={i} className="card col gap1" style={{ padding: 14 }}>
            <div className="row spread" style={{ alignItems: "center" }}>
              <div className="row gap2" style={{ alignItems: "center" }}>
                <span className="badge" style={{ background: "rgba(6,182,212,0.15)", color: "#06b6d4", fontWeight: 600 }}>
                  Rank #{i + 1}
                </span>
                <span className="mono-sm fg-2">Source: {h.source_id?.slice(0, 12) || "-"}</span>
              </div>
              <span className="chip chip-mono" style={{ fontWeight: 600 }}>
                Score: {h.score.toFixed(4)}
              </span>
            </div>
            <div className="t-body-sm" style={{ whiteSpace: "pre-wrap", lineHeight: "20px", marginTop: 4 }}>
              {h.text}
            </div>
          </div>
        ))}

        {searched && hits.length === 0 && (
          <div className="card fg-2" style={{ padding: 36, textAlign: "center" }}>
            No vector hits found. Ingest documents into the collection first.
          </div>
        )}
      </div>
    </div>
  );
}
