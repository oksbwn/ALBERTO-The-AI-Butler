"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "../icons";
import { api } from "@/lib/api";
import { ChatScreen } from "./chat";
import { KnowledgeHistory } from "./knowledge-history";

const STORE_CONFIG: Record<
  string,
  { label: string; color: string; bg: string; icon: string }
> = {
  sqlite_memory: {
    label: "SQLite Fact",
    color: "var(--accent, #6366f1)",
    bg: "rgba(99, 102, 241, 0.12)",
    icon: "brain",
  },
  ladybug_graph: {
    label: "Knowledge Graph",
    color: "#a855f7",
    bg: "rgba(168, 85, 247, 0.12)",
    icon: "workflows",
  },
  chroma_memory: {
    label: "Vector Store",
    color: "#10b981",
    bg: "rgba(16, 185, 129, 0.12)",
    icon: "server",
  },
  qa_pairs: {
    label: "Q&A Pair",
    color: "#f59e0b",
    bg: "rgba(245, 158, 11, 0.12)",
    icon: "help",
  },
  markdown: {
    label: "Doc File",
    color: "#06b6d4",
    bg: "rgba(6, 182, 212, 0.12)",
    icon: "knowledge",
  },
};

export function KnowledgePlaygroundScreen({ project }: { project: any }) {
  // Draggable split percentage: defaults to 50% (half half), identical to HomeScreen
  const [splitPct, setSplitPct] = useState(50);
  const containerRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);

  // Handle draggable divider
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    isDraggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDraggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const rawPct = ((moveEvent.clientX - rect.left) / rect.width) * 100;
      // Clamp between 20% and 80%
      const clamped = Math.max(20, Math.min(80, Math.round(rawPct)));
      setSplitPct(clamped);
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  };

  // --- Explorer State (Left Panel) ---
  const [query, setQuery] = useState("Mac hardware specs and Gemma 12B model setup");
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
  const [expandedRecord, setExpandedRecord] = useState<string | null>(null);

  // Cross-panel communication: sends inquiry from Explorer into the Chat on the right
  const [externalChatInput, setExternalChatInput] = useState<string>("");

  const toggleSource = (s: string) => {
    setSources((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]
    );
  };

  const runProbe = async (searchQuery?: string) => {
    const q = (searchQuery !== undefined ? searchQuery : query).trim();
    if (!project?.id || !q || probing) return;
    setProbing(true);
    setErr(null);
    try {
      const res = await api.recallMemory(project.id, {
        query: q,
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

  const handleAskAboutRecord = (r: any) => {
    const prompt = `Can you explain or audit this stored memory record from ${r.source}: "${r.content}"?`;
    setExternalChatInput(prompt);
  };

  return (
    <div
      ref={containerRef}
      style={{
        display: "flex",
        width: "100%",
        height: "100%",
        minHeight: 0,
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* ==================================================================== */}
      {/* LEFT HALF: Knowledge & Memory Explorer                               */}
      {/* ==================================================================== */}
      <div
        style={{
          width: `${splitPct}%`,
          height: "100%",
          minWidth: 320,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          background: "var(--bg-0)",
        }}
      >
        {/* Explorer Header */}
        <div
          style={{
            padding: "16px 24px 12px",
            borderBottom: "1px solid var(--line)",
            background: "var(--bg-1)",
            flex: "none",
          }}
        >
          <div className="row spread" style={{ alignItems: "center" }}>
            <div>
              <div className="row gap2" style={{ alignItems: "center" }}>
                <Icon name="search" size={17} style={{ color: "var(--accent)" }} />
                <span className="t-h2" style={{ fontSize: 16 }}>
                  Knowledge &amp; Memory Explorer
                </span>
                <span
                  className="badge"
                  style={{
                    background: "var(--accent-glow)",
                    color: "var(--accent)",
                    fontWeight: 600,
                    fontSize: 11,
                  }}
                >
                  {results.length} found
                </span>
              </div>
              <div className="fg-2 t-caption" style={{ marginTop: 2 }}>
                Live multi-store retrieval probe across SQLite, Ladybug Graph, and Chroma.
              </div>
            </div>

            <div className="row gap2" style={{ alignItems: "center" }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setHistOpen(true)}
                disabled={!project?.id}
                title="View memory learning audit history"
              >
                <Icon name="clock" size={13} /> History
              </button>
            </div>
          </div>

          {/* Search Query Input */}
          <div className="row gap2" style={{ marginTop: 14, alignItems: "center" }}>
            <div style={{ position: "relative", flex: 1 }}>
              <input
                className="input mono-sm"
                style={{
                  width: "100%",
                  height: 36,
                  paddingLeft: 32,
                  paddingRight: 28,
                  fontSize: 13,
                }}
                placeholder="Search memories across all stores or test recall…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runProbe()}
              />
              <span
                style={{
                  position: "absolute",
                  left: 10,
                  top: 9,
                  color: "var(--fg-2)",
                  pointerEvents: "none",
                }}
              >
                <Icon name="search" size={15} />
              </span>
              {query && (
                <button
                  onClick={() => setQuery("")}
                  style={{
                    position: "absolute",
                    right: 8,
                    top: 8,
                    background: "none",
                    border: "none",
                    color: "var(--fg-2)",
                    cursor: "pointer",
                    padding: 2,
                  }}
                >
                  <Icon name="x" size={13} />
                </button>
              )}
            </div>

            <button
              className="btn btn-primary"
              style={{ height: 36, padding: "0 16px", flex: "none" }}
              disabled={probing || !query.trim()}
              onClick={() => runProbe()}
            >
              {probing ? (
                <>
                  <Icon name="clock" size={13} /> Probing…
                </>
              ) : (
                <>
                  <Icon name="play" size={13} /> Probe
                </>
              )}
            </button>
          </div>

          {/* Source Filter Chips */}
          <div className="row gap1 wrap" style={{ marginTop: 10, alignItems: "center" }}>
            <span className="t-caption fg-2" style={{ marginRight: 4, fontSize: 11 }}>
              Stores:
            </span>
            {Object.entries(STORE_CONFIG).map(([srcKey, cfg]) => {
              const active = sources.includes(srcKey);
              return (
                <button
                  key={srcKey}
                  onClick={() => toggleSource(srcKey)}
                  style={{
                    fontSize: 11,
                    padding: "3px 9px",
                    borderRadius: 14,
                    border: `1px solid ${active ? cfg.color : "var(--line)"}`,
                    background: active ? cfg.bg : "var(--bg-2)",
                    color: active ? cfg.color : "var(--fg-2)",
                    fontWeight: active ? 600 : 500,
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    transition: "all var(--dur-fast)",
                  }}
                >
                  <Icon name={cfg.icon as any} size={11} />
                  <span>{cfg.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Results List */}
        <div
          className="scroll-y"
          style={{ flex: 1, minHeight: 0, padding: "16px 20px" }}
        >
          {err && (
            <div
              className="card"
              style={{
                padding: "10px 14px",
                marginBottom: 12,
                color: "var(--err, #ef4444)",
                background: "rgba(239, 68, 68, 0.08)",
                border: "1px solid var(--err, #ef4444)",
                fontSize: 12.5,
              }}
            >
              {err}
            </div>
          )}

          {probing && results.length === 0 && (
            <div
              className="col center gap2"
              style={{ padding: 48, color: "var(--fg-2)" }}
            >
              <Icon name="clock" size={24} style={{ color: "var(--accent)" }} />
              <div className="t-caption">Executing multi-source grounding probe…</div>
            </div>
          )}

          {!probing && results.length === 0 && (
            <div
              className="card col center gap2"
              style={{
                padding: 40,
                textAlign: "center",
                color: "var(--fg-2)",
                background: "var(--bg-1)",
              }}
            >
              <Icon name="search" size={28} style={{ opacity: 0.5 }} />
              <div style={{ fontWeight: 600, color: "var(--fg-1)" }}>
                No records matched this probe
              </div>
              <div className="t-caption" style={{ maxWidth: 360 }}>
                Try testing with a broader query or chat on the right panel to extract and persist new facts.
              </div>
            </div>
          )}

          <div className="col gap2">
            {results.map((r, i) => {
              const cfg =
                STORE_CONFIG[r.source] || {
                  label: r.source,
                  color: "var(--fg-1)",
                  bg: "var(--bg-2)",
                  icon: "db",
                };
              const isExpanded = expandedRecord === (r.record_id || `idx-${i}`);

              return (
                <div
                  key={r.record_id || i}
                  className="card col gap1"
                  style={{
                    padding: "12px 14px",
                    background: "var(--bg-1)",
                    border: "1px solid var(--line)",
                    transition: "border-color 0.15s ease",
                  }}
                >
                  {/* Card Header */}
                  <div className="row spread" style={{ alignItems: "center" }}>
                    <div className="row gap1" style={{ alignItems: "center" }}>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 600,
                          padding: "2px 7px",
                          borderRadius: 4,
                          background: cfg.bg,
                          color: cfg.color,
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        <Icon name={cfg.icon as any} size={11} />
                        {cfg.label}
                      </span>

                      {r.provenance && (
                        <span
                          className="mono-sm fg-2"
                          style={{
                            fontSize: 10.5,
                            padding: "1px 6px",
                            borderRadius: 4,
                            background: "var(--bg-2)",
                          }}
                        >
                          {r.provenance}
                        </span>
                      )}
                    </div>

                    <div className="row gap2" style={{ alignItems: "center" }}>
                      {typeof r.score === "number" && (
                        <span
                          className="mono-sm"
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            color:
                              r.score >= 0.8
                                ? "#10b981"
                                : r.score >= 0.5
                                ? "var(--accent)"
                                : "var(--fg-2)",
                          }}
                        >
                          {(r.score * 100).toFixed(0)}% match
                        </span>
                      )}

                      <button
                        className="btn btn-secondary btn-sm"
                        style={{
                          height: 22,
                          padding: "0 8px",
                          fontSize: 11,
                          gap: 4,
                        }}
                        onClick={() => handleAskAboutRecord(r)}
                        title="Send this record to the chat panel on the right to inquire or audit"
                      >
                        <Icon name="sparkles" size={11} style={{ color: "var(--accent)" }} />
                        <span>Inquire in Chat →</span>
                      </button>

                      <button
                        className="iconbtn"
                        style={{ width: 22, height: 22 }}
                        onClick={() =>
                          setExpandedRecord(
                            isExpanded ? null : r.record_id || `idx-${i}`
                          )
                        }
                        title={isExpanded ? "Collapse metadata" : "Inspect raw metadata"}
                      >
                        <Icon
                          name="chevron"
                          size={12}
                          style={{
                            transform: isExpanded ? "rotate(180deg)" : "none",
                            transition: "transform 0.15s ease",
                          }}
                        />
                      </button>
                    </div>
                  </div>

                  {/* Content Snippet */}
                  <div
                    className="t-body-sm"
                    style={{
                      whiteSpace: "pre-wrap",
                      lineHeight: "19px",
                      marginTop: 2,
                      fontSize: 12.5,
                      color: "var(--fg-0)",
                    }}
                  >
                    {r.content}
                  </div>

                  {/* Expandable Metadata Inspection Drawer */}
                  {isExpanded && (
                    <div
                      style={{
                        marginTop: 6,
                        paddingTop: 8,
                        borderTop: "1px solid var(--line)",
                        fontSize: 11,
                      }}
                    >
                      <div className="mono-sm fg-2" style={{ marginBottom: 4 }}>
                        Record ID: {r.record_id || "N/A"}
                      </div>
                      {r.metadata && Object.keys(r.metadata).length > 0 && (
                        <pre
                          className="mono-sm"
                          style={{
                            margin: 0,
                            padding: 8,
                            borderRadius: 6,
                            background: "var(--bg-2)",
                            overflowX: "auto",
                            fontSize: 11,
                            maxHeight: 180,
                          }}
                        >
                          {JSON.stringify(r.metadata, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ==================================================================== */}
      {/* DRAGGABLE DIVIDER (1px hairline matching HomeScreen)                 */}
      {/* ==================================================================== */}
      <div
        onMouseDown={handleMouseDown}
        style={{
          width: 1,
          flex: "none",
          position: "relative",
          background: "var(--line)",
          cursor: "col-resize",
          userSelect: "none",
          outline: "none",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: -4,
            right: -4,
            cursor: "col-resize",
            zIndex: 10,
          }}
          title="Drag to resize Explorer and Chat panels"
        />
      </div>

      {/* ==================================================================== */}
      {/* RIGHT HALF: Chat Panel (identical to Landing Page ChatScreen)        */}
      {/* ==================================================================== */}
      <div
        style={{
          width: `${100 - splitPct}%`,
          height: "100%",
          minWidth: 320,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <ChatScreen
          project={project}
          externalInput={externalChatInput}
          onExternalInputConsumed={() => setExternalChatInput("")}
          persona="memory_curator"
        />
      </div>

      {/* Audit History Drawer Modal */}
      <KnowledgeHistory
        project={project}
        open={histOpen}
        onClose={() => setHistOpen(false)}
      />
    </div>
  );
}
