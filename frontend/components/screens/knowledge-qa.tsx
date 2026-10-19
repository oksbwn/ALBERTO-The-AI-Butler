"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Icon } from "../icons";
import { Field, Modal } from "../primitives";
import { api, QaPair } from "@/lib/api";
import { KnowledgeHistory } from "./knowledge-history";

const BUILTIN_KINDS = ["faq", "policy", "troubleshooting", "pricing"];

export function KnowledgeQaScreen({ project }: { project: any }) {
  const [tab, setTab] = useState<"catalog" | "categories" | "test">("catalog");
  const [rows, setRows] = useState<QaPair[]>([]);
  const [kind, setKind] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ question: string; answer: string; kind: string; tags: string }>({
    question: "",
    answer: "",
    kind: "faq",
    tags: "",
  });
  const [form, setForm] = useState<{ question: string; answer: string; kind: string; tags: string }>({
    question: "",
    answer: "",
    kind: "faq",
    tags: "",
  });
  const [testQ, setTestQ] = useState("");
  const [testHit, setTestHit] = useState<any>(null);
  const [testing, setTesting] = useState(false);
  const [histOpen, setHistOpen] = useState(false);

  const reload = useCallback(() => {
    if (!project?.id) return;
    api.listQa(project.id).then(setRows).catch(() => {});
  }, [project?.id]);

  useEffect(() => {
    reload();
  }, [reload]);

  const kinds = useMemo(() => {
    const set = new Set<string>(BUILTIN_KINDS);
    rows.forEach((q) => {
      if (q.kind) set.add(q.kind);
    });
    return [...set].sort();
  }, [rows]);

  const visible = kind === null ? rows : rows.filter((q) => q.kind === kind);

  async function add() {
    if (!form.question.trim()) return;
    const tags = form.tags.split(",").map((t) => t.trim()).filter(Boolean);
    await api.addQa(project.id, {
      question: form.question,
      answer: form.answer,
      kind: form.kind || "faq",
      tags,
    });
    setForm({ question: "", answer: "", kind: "faq", tags: "" });
    reload();
  }

  async function saveEdit() {
    if (!editing) return;
    await api.updateQa(project.id, editing, {
      question: edit.question,
      answer: edit.answer,
      kind: edit.kind,
      tags: edit.tags.split(",").map((t) => t.trim()).filter(Boolean),
    });
    setEditing(null);
    reload();
  }

  async function runDeflectionTest() {
    if (!testQ.trim() || !project?.id) return;
    setTesting(true);
    try {
      const res = await api.searchKnowledge(project.id, testQ, 3);
      setTestHit(res?.[0] || null);
    } catch {
      setTestHit(null);
    } finally {
      setTesting(false);
    }
  }

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
              <span className="t-display">Q&amp;A Pairs</span>
              <span className="typechip" style={{ fontWeight: 600 }}>FAQ Deflection</span>
            </div>
            <div className="fg-1 t-caption" style={{ marginTop: 3 }}>
              Curated question-and-answer pairs for deterministic deflection and high-confidence matching.
            </div>
          </div>
          <div className="row gap2" style={{ alignItems: "center" }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setHistOpen(true)}
              disabled={!project?.id}
              title="Audit trail of Q&A edits"
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
                  { id: "catalog", label: "Q&A Catalog", icon: "n_qa" },
                  { id: "categories", label: "Categories & Kinds", icon: "list" },
                  { id: "test", label: "Deflect Matcher Test", icon: "search" },
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

            {tab === "catalog" && (
              <div className="row" style={{ gap: 20, alignItems: "flex-start" }}>
                {/* Kind filters sidebar */}
                <div className="card col" style={{ width: 220, flex: "none", padding: 12, gap: 2 }}>
                  <div className="fg-2 t-micro" style={{ padding: "4px 8px 6px" }}>CATEGORIES</div>
                  <button
                    onClick={() => setKind(null)}
                    className="row spread"
                    style={{
                      padding: "7px 10px",
                      borderRadius: 7,
                      border: "none",
                      cursor: "pointer",
                      background: kind === null ? "var(--bg-3)" : "transparent",
                      color: kind === null ? "var(--fg-0)" : "var(--fg-1)",
                      fontSize: 13,
                    }}
                  >
                    <span>All pairs</span>
                    <span className="mono-sm">{rows.length}</span>
                  </button>
                  {kinds.map((k) => (
                    <button
                      key={k}
                      onClick={() => setKind(k)}
                      className="row spread"
                      style={{
                        padding: "7px 10px",
                        borderRadius: 7,
                        border: "none",
                        cursor: "pointer",
                        background: kind === k ? "var(--bg-3)" : "transparent",
                        color: kind === k ? "var(--fg-0)" : "var(--fg-1)",
                        fontSize: 13,
                      }}
                    >
                      <span className="truncate">{k}</span>
                      <span className="mono-sm">{rows.filter((r) => r.kind === k).length}</span>
                    </button>
                  ))}
                </div>

                {/* Table & Add form */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="card" style={{ padding: 18, marginBottom: 18 }}>
                    <div className="t-h3" style={{ marginBottom: 10 }}>Add Curated Q&amp;A Pair</div>
                    <div className="col gap2">
                      <input
                        className="input"
                        placeholder="User Question / Trigger pattern…"
                        value={form.question}
                        onChange={(e) => setForm((f) => ({ ...f, question: e.target.value }))}
                      />
                      <textarea
                        className="input"
                        rows={3}
                        placeholder="Authoritative Answer…"
                        value={form.answer}
                        onChange={(e) => setForm((f) => ({ ...f, answer: e.target.value }))}
                      />
                      <div className="row gap2">
                        <input
                          className="input"
                          style={{ width: 170 }}
                          placeholder="Kind (faq, policy…)"
                          value={form.kind}
                          onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value }))}
                        />
                        <input
                          className="input grow"
                          placeholder="Tags (comma-separated)…"
                          value={form.tags}
                          onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
                        />
                        <button className="btn btn-primary" onClick={add} disabled={!form.question.trim()}>
                          Add Pair
                        </button>
                      </div>
                    </div>
                  </div>

                  <div className="card" style={{ overflow: "hidden" }}>
                    <table className="tbl" style={{ width: "100%" }}>
                      <thead>
                        <tr>
                          <th style={{ width: "30%" }}>Question</th>
                          <th style={{ width: "42%" }}>Answer</th>
                          <th style={{ width: "12%" }}>Kind</th>
                          <th style={{ width: "10%" }}>Tags</th>
                          <th style={{ width: "6%" }} />
                        </tr>
                      </thead>
                      <tbody>
                        {visible.map((q) => (
                          <tr key={q.id}>
                            <td style={{ fontWeight: 600 }}>{q.question}</td>
                            <td className="t-body-sm" style={{ lineHeight: "19px" }}>
                              {q.answer}
                            </td>
                            <td>
                              <span className="typechip">{q.kind}</span>
                            </td>
                            <td>
                              {(q.tags || []).map((t) => (
                                <span key={t} className="chip chip-mono" style={{ marginRight: 4 }}>
                                  {t}
                                </span>
                              ))}
                            </td>
                            <td style={{ textAlign: "right" }}>
                              <div className="row gap1" style={{ justifyContent: "flex-end" }}>
                                <button
                                  className="iconbtn"
                                  onClick={() => {
                                    setEditing(q.id);
                                    setEdit({
                                      question: q.question,
                                      answer: q.answer,
                                      kind: q.kind,
                                      tags: (q.tags || []).join(", "),
                                    });
                                  }}
                                >
                                  <Icon name="edit" size={13} />
                                </button>
                                <button
                                  className="iconbtn"
                                  onClick={async () => {
                                    await api.deleteQa(project.id, q.id);
                                    reload();
                                  }}
                                >
                                  <Icon name="trash" size={13} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                        {visible.length === 0 && (
                          <tr>
                            <td colSpan={5} style={{ textAlign: "center", padding: 32, color: "var(--fg-2)" }}>
                              No Q&amp;A pairs found in this category.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {tab === "categories" && (
              <div className="card" style={{ padding: 22 }}>
                <div className="t-h2" style={{ marginBottom: 6 }}>Curated Q&amp;A Categories</div>
                <div className="fg-2 t-caption" style={{ marginBottom: 16 }}>
                  Kinds allow intelligent agent retrieval policy to narrow FAQ deflection lookups by intent.
                </div>
                <div className="row gap3" style={{ flexWrap: "wrap" }}>
                  {kinds.map((k) => (
                    <div key={k} className="card" style={{ padding: 16, minWidth: 220, background: "var(--bg-1)" }}>
                      <div className="row spread" style={{ alignItems: "center" }}>
                        <span className="typechip" style={{ fontSize: 13, textTransform: "capitalize" }}>
                          {k}
                        </span>
                        <span className="chip chip-mono">{rows.filter((r) => r.kind === k).length} pairs</span>
                      </div>
                      <div className="t-caption fg-2" style={{ marginTop: 10 }}>
                        Curated knowledge deflection category for intent filtering.
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tab === "test" && (
              <div className="card" style={{ padding: 22 }}>
                <div className="t-h2" style={{ marginBottom: 6 }}>Test Intent Deflection</div>
                <div className="fg-2 t-caption" style={{ marginBottom: 16 }}>
                  Test whether user queries match against your curated Q&amp;A pairs before hitting external LLM generation.
                </div>
                <div className="row gap2" style={{ marginBottom: 16 }}>
                  <input
                    className="input"
                    style={{ height: 38 }}
                    placeholder="Simulated user prompt (e.g. How do I reset Wi-Fi?)…"
                    value={testQ}
                    onChange={(e) => setTestQ(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && runDeflectionTest()}
                  />
                  <button
                    className="btn btn-primary"
                    style={{ height: 38, padding: "0 18px" }}
                    onClick={runDeflectionTest}
                    disabled={testing || !testQ.trim()}
                  >
                    {testing ? "Testing…" : "Test Matcher"}
                  </button>
                </div>
                {testHit && (
                  <div className="card" style={{ padding: 18, background: "var(--bg-1)" }}>
                    <div className="row spread" style={{ marginBottom: 8 }}>
                      <span className="badge" style={{ color: "var(--ok)", background: "rgba(34,197,94,0.15)" }}>
                        Matched Pair
                      </span>
                      <span className="chip chip-mono">
                        Relevance Score: {testHit.score?.toFixed(3) || "1.000"}
                      </span>
                    </div>
                    <div className="t-body-sm" style={{ whiteSpace: "pre-wrap", lineHeight: "20px" }}>
                      {testHit.text}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Edit Modal */}
            {editing && (
              <Modal open={true} onClose={() => setEditing(null)} title="Edit Q&A Pair">
                <div className="col gap3" style={{ padding: 18 }}>
                  <Field label="Question">
                    <input
                      className="input"
                      value={edit.question}
                      onChange={(e) => setEdit((ed) => ({ ...ed, question: e.target.value }))}
                    />
                  </Field>
                  <Field label="Answer">
                    <textarea
                      className="input"
                      rows={4}
                      value={edit.answer}
                      onChange={(e) => setEdit((ed) => ({ ...ed, answer: e.target.value }))}
                    />
                  </Field>
                  <Field label="Kind">
                    <input
                      className="input"
                      value={edit.kind}
                      onChange={(e) => setEdit((ed) => ({ ...ed, kind: e.target.value }))}
                    />
                  </Field>
                  <Field label="Tags">
                    <input
                      className="input"
                      value={edit.tags}
                      onChange={(e) => setEdit((ed) => ({ ...ed, tags: e.target.value }))}
                    />
                  </Field>
                  <div className="row end gap2" style={{ marginTop: 12 }}>
                    <button className="btn btn-secondary" onClick={() => setEditing(null)}>
                      Cancel
                    </button>
                    <button className="btn btn-primary" onClick={saveEdit}>
                      Save
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
