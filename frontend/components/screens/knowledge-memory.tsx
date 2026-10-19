"use client";

import { useCallback, useEffect, useState } from "react";
import { Icon } from "../icons";
import { Field, Modal } from "../primitives";
import {
  api,
  LearningEventItem,
  MarkdownMemoryFile,
  MemoryLearningSettings,
  MemoryRecordDetail,
} from "@/lib/api";
import { KnowledgeHistory } from "./knowledge-history";
import { OntologyReviewQueue } from "./ontology-review-queue";

export function KnowledgeMemoryScreen({ project }: { project: any }) {
  const [tab, setTab] = useState<"records" | "markdown" | "reviews" | "settings">("records");
  const [records, setRecords] = useState<MemoryRecordDetail[]>([]);
  const [reviewEvents, setReviewEvents] = useState<LearningEventItem[]>([]);
  const [mdFiles, setMdFiles] = useState<MarkdownMemoryFile[]>([]);
  const [selectedMd, setSelectedMd] = useState<string | null>(null);
  const [mdContent, setMdContent] = useState<string | null>(null);
  const [settings, setSettings] = useState<MemoryLearningSettings | null>(null);
  const [editingRecord, setEditingRecord] = useState<MemoryRecordDetail | null>(null);
  const [editText, setEditText] = useState("");
  const [editKind, setEditKind] = useState("note");
  const [loading, setLoading] = useState(true);
  const [histOpen, setHistOpen] = useState(false);

  const reload = useCallback(() => {
    if (!project?.id) return;
    setLoading(true);
    Promise.all([
      api.listMemoryRecords(project.id, { status: "active" }).catch(() => []),
      api.listLearningEvents(project.id, "review_required").catch(() => []),
      api.listMarkdownMemoryFiles(project.id).catch(() => []),
      api.getMemoryLearningSettings(project.id).catch(() => null),
    ])
      .then(([recs, revs, mdf, setts]) => {
        setRecords(recs || []);
        setReviewEvents(revs || []);
        setMdFiles(mdf || []);
        setSettings(setts);
      })
      .finally(() => setLoading(false));
  }, [project?.id]);

  useEffect(() => {
    reload();
  }, [reload]);

  const toggleLearning = async () => {
    if (!project?.id || !settings) return;
    const next = !settings.memory_learning_enabled;
    const updated = await api.updateMemoryLearningSettings(project.id, {
      memory_learning_enabled: next,
    });
    setSettings(updated);
    window.dispatchEvent(
      new CustomEvent("alberto:learning-changed", { detail: updated })
    );
  };

  const handleCountChange = useCallback((c: number) => {
    setReviewEvents((prev) => (prev.length === c ? prev : Array(c).fill({} as any)));
  }, []);

  const openMdFile = async (fn: string) => {
    setSelectedMd(fn);
    try {
      const files = await api.listMarkdownMemoryFiles(project.id, fn);
      const target = files.find((f) => f.filename === fn);
      setMdContent(target?.content || "(empty)");
    } catch {
      setMdContent("Failed to load file.");
    }
  };

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
              <span className="t-display">Long-Term Memory</span>
              <span className="typechip" style={{ fontWeight: 600 }}>SQLite &amp; Markdown</span>
            </div>
            <div className="fg-1 t-caption" style={{ marginTop: 3 }}>
              Authoritative long-term memory records, synced Markdown files, and autonomous learning review queue.
            </div>
          </div>
          <div className="row gap2" style={{ alignItems: "center" }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setHistOpen(true)}
              disabled={!project?.id}
              title="Audit trail of memory updates"
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
                  { id: "records", label: "Structured Memories", icon: "brain" },
                  { id: "markdown", label: "Markdown Files", icon: "file" },
                  {
                    id: "reviews",
                    label: "Learning Reviews",
                    icon: "shield-check",
                    count: reviewEvents.length,
                  },
                  { id: "settings", label: "Autonomous Settings", icon: "settings" },
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
                      {t.count != null && t.count > 0 && (
                        <span
                          className="badge"
                          style={{ background: "var(--accent-glow)", color: "var(--accent)" }}
                        >
                          {t.count}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            {tab === "records" && (
              <div className="card" style={{ padding: 22 }}>
                <div className="row spread" style={{ alignItems: "center", marginBottom: 16 }}>
                  <div>
                    <div className="t-h2">Authoritative SQLite Long-Term Memories</div>
                    <div className="fg-2 t-caption" style={{ marginTop: 2 }}>
                      High-confidence user preferences, entity statements, and configuration facts.
                    </div>
                  </div>
                  <span className="chip chip-mono">{records.length} records</span>
                </div>

                <div className="col gap2">
                  {records.map((r) => (
                    <div
                      key={r.id}
                      className="card row spread"
                      style={{ padding: 14, alignItems: "center", background: "var(--bg-1)" }}
                    >
                      <div style={{ flex: 1, minWidth: 0, marginRight: 20 }}>
                        <div className="row gap2" style={{ alignItems: "center", marginBottom: 6 }}>
                          <span className="typechip">{r.kind}</span>
                          <span className="badge" style={{ color: "var(--ok)", background: "rgba(34,197,94,0.15)" }}>
                            {r.status}
                          </span>
                          <span className="t-micro fg-2 mono">{r.provenance}</span>
                          {r.confidence < 1.0 && (
                            <span className="chip chip-mono t-micro">{Math.round(r.confidence * 100)}%</span>
                          )}
                        </div>
                        <div className="t-body-sm" style={{ whiteSpace: "pre-wrap", lineHeight: "20px" }}>
                          {r.text}
                        </div>
                      </div>
                      <div className="row gap2" style={{ flex: "none" }}>
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => {
                            setEditingRecord(r);
                            setEditText(r.text);
                            setEditKind(r.kind);
                          }}
                        >
                          <Icon name="edit" size={13} /> Edit
                        </button>
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={async () => {
                            await api.deleteMemoryRecord(project.id, r.id);
                            reload();
                          }}
                        >
                          <Icon name="trash" size={13} />
                        </button>
                      </div>
                    </div>
                  ))}
                  {records.length === 0 && (
                    <div className="fg-2" style={{ padding: 32, textAlign: "center" }}>
                      No memory records stored yet.
                    </div>
                  )}
                </div>
              </div>
            )}

            {tab === "markdown" && (
              <div className="card" style={{ padding: 22 }}>
                <div className="t-h2" style={{ marginBottom: 4 }}>Persistent Markdown Memory Files</div>
                <div className="fg-2 t-caption" style={{ marginBottom: 18 }}>
                  Human-readable, git-trackable memory projections stored directly under <code>data/memory/</code>.
                </div>
                <div className="row gap2 wrap" style={{ marginBottom: 16 }}>
                  {mdFiles.map((f) => (
                    <button
                      key={f.filename}
                      className={`btn btn-sm ${selectedMd === f.filename ? "btn-primary" : "btn-secondary"}`}
                      onClick={() => openMdFile(f.filename)}
                    >
                      <Icon name="file" size={13} /> {f.filename}
                    </button>
                  ))}
                  {mdFiles.length === 0 && (
                    <span className="fg-2 t-body-sm">No markdown memory files created yet.</span>
                  )}
                </div>
                {selectedMd && (
                  <pre
                    className="card"
                    style={{
                      padding: 16,
                      background: "var(--bg-0)",
                      maxHeight: 460,
                      overflowY: "auto",
                      whiteSpace: "pre-wrap",
                      fontSize: 13,
                      lineHeight: "20px",
                    }}
                  >
                    {mdContent || "Loading…"}
                  </pre>
                )}
              </div>
            )}

            {tab === "reviews" && (
              <OntologyReviewQueue
                project={project}
                onCountChange={handleCountChange}
              />
            )}

            {tab === "settings" && (
              <div className="card" style={{ padding: 22 }}>
                <div className="t-h2" style={{ marginBottom: 6 }}>
                  Autonomous Memory Learning Configuration
                </div>
                <div className="fg-2 t-caption" style={{ marginBottom: 18 }}>
                  Control whether Alberto extracts and updates long-term preferences during chat turns.
                </div>
                <div
                  className="row spread"
                  style={{
                    padding: "16px 20px",
                    background: "var(--bg-1)",
                    borderRadius: 8,
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600 }}>Autonomous Memory Extraction</div>
                    <div className="t-caption fg-2" style={{ marginTop: 2 }}>
                      Background curator parses turns and proposes structured memories.
                    </div>
                  </div>
                  <button
                    className={`btn btn-sm ${
                      settings?.memory_learning_enabled ? "btn-primary" : "btn-secondary"
                    }`}
                    onClick={toggleLearning}
                  >
                    {settings?.memory_learning_enabled ? "Enabled (ON)" : "Disabled (OFF)"}
                  </button>
                </div>
              </div>
            )}

            {/* Edit Modal */}
            {editingRecord && (
              <Modal open={true} onClose={() => setEditingRecord(null)} title="Correct Memory Record">
                <div className="col gap3" style={{ padding: 18 }}>
                  <Field label="Memory Content">
                    <textarea
                      className="input"
                      rows={4}
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                    />
                  </Field>
                  <Field label="Category / Kind">
                    <input
                      className="input"
                      value={editKind}
                      onChange={(e) => setEditKind(e.target.value)}
                    />
                  </Field>
                  <div className="row end gap2" style={{ marginTop: 12 }}>
                    <button className="btn btn-secondary" onClick={() => setEditingRecord(null)}>
                      Cancel
                    </button>
                    <button
                      className="btn btn-primary"
                      onClick={async () => {
                        await api.updateMemoryRecord(project.id, editingRecord.id, {
                          text: editText,
                          kind: editKind,
                        });
                        setEditingRecord(null);
                        reload();
                      }}
                    >
                      Save Correction
                    </button>
                  </div>
                </div>
              </Modal>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
