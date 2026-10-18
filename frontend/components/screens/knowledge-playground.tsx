"use client";

import { useEffect, useState } from "react";
import { Icon } from "../icons";
import { api } from "@/lib/api";
import { KnowledgeHistory } from "./knowledge-history";

export function KnowledgePlaygroundScreen({ project }: { project: any }) {
  const [tab, setTab] = useState<"probe" | "subagent" | "provenance">("probe");
  const [query, setQuery] = useState("Alberto system architecture and server IP");
  const [sources, setSources] = useState<string[]>([
    "sqlite_memory",
    "chroma_memory",
    "ladybug_graph",
    "qa_pairs",
    "markdown",
  ]);
  const [results, setResults] = useState<any[]>([]);
  const [probing, setProbing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [histOpen, setHistOpen] = useState(false);

  const toggleSource = (s: string) => {
    setSources((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]
    );
  };

  const runProbe = async () => {
    if (!project?.id || !query.trim() || probing) return;
    setProbing(true);
    setErr(null);
    try {
      const res = await api.recallMemory(project.id, {
        query: query.trim(),
        sources: sources.length > 0 ? sources : undefined,
        top_k: 12,
      });
      setResults(res?.results || []);
    } catch (e: any) {
      setErr(e?.message || "Recall probe failed.");
      setResults([]);
    } finally {
      setProbing(false);
    }
  };

  useEffect(() => {
    if (project?.id && results.length === 0) {
      runProbe();
    }
  }, [project?.id]);

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
              <span className="t-display">Memory &amp; Recall Playground</span>
              <span
                className="badge"
                style={{
                  background: "var(--accent-glow)",
                  color: "var(--accent)",
                  fontWeight: 600,
                  fontSize: 11,
                }}
              >
                Interactive
              </span>
            </div>
            <div className="fg-1 t-caption" style={{ marginTop: 3 }}>
              Multi-source retrieval probe, memory sub-agent simulator, and cross-store grounding matrix.
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

      <KnowledgeHistory
        project={project}
        open={histOpen}
        onClose={() => setHistOpen(false)}
      />

      {/* Main Body */}
      <div
        className="scroll-y"
        style={{ flex: 1, minWidth: 0, padding: "20px 32px 48px" }}
      >
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
                  { id: "probe", label: "Live Recall Probe", icon: "search" },
                  { id: "subagent", label: "Memory Sub-Agent Simulator", icon: "bot" },
                  { id: "provenance", label: "Cross-Store Provenance Matrix", icon: "layers" },
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

            {/* Tab 1: Live Recall Probe */}
            {tab === "probe" && (
              <div className="col gap3">
                <div className="card col gap3" style={{ padding: 20 }}>
                  <div className="row spread" style={{ alignItems: "center" }}>
                    <div>
                      <div className="t-h2">Multi-Store Query Tester</div>
                      <div className="fg-2 t-caption" style={{ marginTop: 2 }}>
                        Simulates the exact memory grounding pass Alberto executes before running an agent turn.
                      </div>
                    </div>
                  </div>

                  <div className="row gap2" style={{ alignItems: "center" }}>
                    <input
                      className="input mono-sm"
                      style={{ flex: 1, minWidth: 280, height: 38 }}
                      placeholder="Type a natural language recall prompt…"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && runProbe()}
                    />
                    <button
                      className="btn btn-primary"
                      style={{ height: 38, padding: "0 18px" }}
                      disabled={probing || !query.trim()}
                      onClick={runProbe}
                    >
                      {probing ? (
                        <>
                          <Icon name="clock" size={14} /> Probing…
                        </>
                      ) : (
                        <>
                          <Icon name="search" size={14} /> Execute Probe
                        </>
                      )}
                    </button>
                  </div>

                  {/* Storage Source Toggles */}
                  <div className="col gap1">
                    <div className="t-caption fg-2">Active retrieval sources:</div>
                    <div className="row gap2 wrap" style={{ alignItems: "center" }}>
                      {[
                        { id: "sqlite_memory", label: "SQLite Memory (Authoritative)" },
                        { id: "chroma_memory", label: "Chroma Vector Space" },
                        { id: "ladybug_graph", label: "LadybugDB Graph Nodes" },
                        { id: "qa_pairs", label: "Curated Q&A Pairs" },
                        { id: "markdown", label: "Markdown Flat Files" },
                      ].map((s) => {
                        const checked = sources.includes(s.id);
                        return (
                          <button
                            key={s.id}
                            type="button"
                            onClick={() => toggleSource(s.id)}
                            className="row gap1"
                            style={{
                              alignItems: "center",
                              padding: "5px 11px",
                              borderRadius: 6,
                              fontSize: 12,
                              cursor: "pointer",
                              border: "1px solid var(--line)",
                              background: checked ? "var(--bg-3)" : "var(--bg-0)",
                              color: checked ? "var(--fg-0)" : "var(--fg-2)",
                            }}
                          >
                            <span
                              style={{
                                width: 8,
                                height: 8,
                                borderRadius: "50%",
                                background: checked ? "var(--accent)" : "var(--border)",
                              }}
                            />
                            <span>{s.label}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>

                {err && (
                  <div className="card" style={{ padding: 12, color: "var(--err)" }}>
                    {err}
                  </div>
                )}

                {/* Probe Results */}
                <div className="col gap2">
                  <div className="row spread" style={{ alignItems: "center" }}>
                    <span className="t-h2">Retrieved Memory Records ({results.length})</span>
                    <span className="fg-2 t-caption">Ranked by provenance and semantic relevance</span>
                  </div>

                  {results.map((r, i) => (
                    <div key={i} className="card col gap2" style={{ padding: 14 }}>
                      <div className="row spread" style={{ alignItems: "center" }}>
                        <div className="row gap2" style={{ alignItems: "center" }}>
                          <span
                            className="badge"
                            style={{
                              background:
                                r.source === "sqlite_memory"
                                  ? "rgba(59,130,246,0.15)"
                                  : r.source === "ladybug_graph"
                                  ? "rgba(168,85,247,0.15)"
                                  : r.source === "qa_pairs"
                                  ? "rgba(16,185,129,0.15)"
                                  : "var(--bg-2)",
                              color:
                                r.source === "sqlite_memory"
                                  ? "var(--accent)"
                                  : r.source === "ladybug_graph"
                                  ? "#c084fc"
                                  : r.source === "qa_pairs"
                                  ? "var(--ok)"
                                  : "var(--fg-1)",
                              fontWeight: 600,
                              fontSize: 11,
                            }}
                          >
                            {r.source}
                          </span>
                          <span className="mono-sm fg-2">{r.record_id}</span>
                        </div>
                        {r.score !== undefined && (
                          <span className="mono-sm fg-2">
                            Score: {(r.score * 100).toFixed(1)}%
                          </span>
                        )}
                      </div>
                      <div
                        className="t-body-sm"
                        style={{ whiteSpace: "pre-wrap", lineHeight: "20px" }}
                      >
                        {r.content}
                      </div>
                    </div>
                  ))}

                  {results.length === 0 && !probing && (
                    <div
                      className="card"
                      style={{ padding: 36, textAlign: "center", color: "var(--fg-2)" }}
                    >
                      No records matched this probe across enabled storage engines.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Tab 2: Memory Sub-Agent Simulator */}
            {tab === "subagent" && (
              <div className="card" style={{ padding: 36, textAlign: "center" }}>
                <div className="row center" style={{ marginBottom: 14 }}>
                  <span
                    className="badge"
                    style={{
                      padding: "4px 10px",
                      fontSize: 12,
                      background: "var(--accent-glow)",
                      color: "var(--accent)",
                    }}
                  >
                    Phase 2.3 · Coming Soon
                  </span>
                </div>
                <div className="t-display" style={{ marginBottom: 8 }}>
                  Memory Curator Sub-Agent Harness
                </div>
                <div
                  className="fg-2 t-body"
                  style={{ maxWidth: 680, margin: "0 auto 24px" }}
                >
                  Direct interactive dialogue with Alberto's autonomous Memory Curator agent.
                  Converse with your memory sub-agent to audit contradictions, prune stale facts,
                  and inspect how facts are extracted from conversation history.
                </div>
                <div
                  className="card row gap3 center"
                  style={{
                    maxWidth: 580,
                    margin: "0 auto",
                    padding: 18,
                    background: "var(--bg-1)",
                  }}
                >
                  <Icon name="bot" size={26} style={{ color: "var(--accent)" }} />
                  <div style={{ textAlign: "left" }}>
                    <div style={{ fontWeight: 600 }}>Conversational Memory Audit</div>
                    <div className="t-caption fg-2" style={{ marginTop: 2 }}>
                      "Alberto, summarize what you know about my Mac server and remove outdated IP references."
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Tab 3: Provenance Matrix */}
            {tab === "provenance" && (
              <div className="card" style={{ padding: 36, textAlign: "center" }}>
                <div className="row center" style={{ marginBottom: 14 }}>
                  <span
                    className="badge"
                    style={{
                      padding: "4px 10px",
                      fontSize: 12,
                      background: "var(--accent-glow)",
                      color: "var(--accent)",
                    }}
                  >
                    Phase 2.3 · Coming Soon
                  </span>
                </div>
                <div className="t-display" style={{ marginBottom: 8 }}>
                  Cross-Store Grounding &amp; Provenance Matrix
                </div>
                <div
                  className="fg-2 t-body"
                  style={{ maxWidth: 680, margin: "0 auto 24px" }}
                >
                  Audit how memories move through trust boundaries: from conversational extractions
                  into SQLite, vector embeddings in Chroma, ontology relations in LadybugDB, and flat markdown files.
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
