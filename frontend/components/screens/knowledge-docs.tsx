"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Icon } from "../icons";
import { Field, Modal, Segmented, StatusPill } from "../primitives";
import { api, KbSource, SearchHit } from "@/lib/api";
import { KnowledgeHistory } from "./knowledge-history";

const DEFAULT_CHUNK_STRATEGY = "recursive";
const DEFAULT_CHUNK_SIZE = 1000;
const DEFAULT_CHUNK_OVERLAP = 200;
const UNFILED = "";

export function KnowledgeDocsScreen({ project }: { project: any }) {
  const [tab, setTab] = useState<"files" | "search">("files");
  const [histOpen, setHistOpen] = useState(false);

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
              <span className="t-display">Documents &amp; Files</span>
              <span className="typechip" style={{ fontWeight: 600 }}>RAG Sources</span>
            </div>
            <div className="fg-1 t-caption" style={{ marginTop: 3 }}>
              Document files, folder hierarchy, chunking parameters, and semantic search debugger.
            </div>
          </div>
          <div className="row gap2" style={{ alignItems: "center" }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setHistOpen(true)}
              disabled={!project?.id}
              title="Audit trail of added, edited, or deleted files"
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
                  { id: "files", label: "Sources & Files", icon: "file" },
                  { id: "search", label: "Search Debugger", icon: "search" },
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

            {tab === "files" && <FilesTable project={project} />}
            {tab === "search" && <SearchDebugger project={project} />}
          </div>
        </div>
      </div>
    </div>
  );
}

function FilesTable({ project }: { project: any }) {
  const [rows, setRows] = useState<KbSource[]>([]);
  const [folder, setFolder] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [addErr, setAddErr] = useState<string | null>(null);
  const [newFolder, setNewFolder] = useState<string | null>(null);
  const [targetFolder, setTargetFolder] = useState<string>("");
  const [form, setForm] = useState<{
    kind: string;
    name: string;
    text: string;
    uri: string;
    file: globalThis.File | null;
    chunkStrategy: string;
  }>({
    kind: "text",
    name: "",
    text: "",
    uri: "",
    file: null,
    chunkStrategy: "recursive",
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rechunkOpen, setRechunkOpen] = useState(false);
  const [rechunkTargets, setRechunkTargets] = useState<string[]>([]);
  const [rechunkBusy, setRechunkBusy] = useState(false);
  const [rechunkErr, setRechunkErr] = useState<string | null>(null);
  const [rechunkForm, setRechunkForm] = useState<{
    strategy: string;
    size: number;
    overlap: number;
  }>({
    strategy: DEFAULT_CHUNK_STRATEGY,
    size: DEFAULT_CHUNK_SIZE,
    overlap: DEFAULT_CHUNK_OVERLAP,
  });
  const [dedupeBusy, setDedupeBusy] = useState(false);
  const [dedupeMsg, setDedupeMsg] = useState<string | null>(null);

  const reload = useCallback(() => {
    if (!project?.id) return;
    api.listSources(project.id).then(setRows).catch(() => {});
  }, [project?.id]);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    const pending = rows.some((s) => s.status === "queued" || s.status === "processing");
    if (!pending || !project?.id) return;
    const t = setTimeout(async () => {
      const next = await api.listSources(project.id).catch(() => null);
      if (!next) return;
      setRows(next);
    }, 1500);
    return () => clearTimeout(t);
  }, [rows, project?.id]);

  const folders = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((s) => {
      if (s.folder) set.add(s.folder);
    });
    return [...set].sort();
  }, [rows]);

  const inNamedFolder = folder !== null && folder !== UNFILED;
  const visible =
    folder === null
      ? rows
      : folder === UNFILED
      ? rows.filter((s) => !s.folder)
      : rows.filter((s) => s.folder === folder);
  const showFolderCol = folder === null;
  const allVisibleSelected = visible.length > 0 && visible.every((s) => selected.has(s.id));

  function toggleSel(id: string) {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  function toggleAllVisible() {
    setSelected((prev) => {
      const n = new Set(prev);
      if (allVisibleSelected) visible.forEach((s) => n.delete(s.id));
      else visible.forEach((s) => n.add(s.id));
      return n;
    });
  }

  function openRechunk(ids: string[]) {
    if (!ids.length) return;
    const first = rows.find((r) => r.id === ids[0]);
    setRechunkForm({
      strategy: first?.chunking_strategy || DEFAULT_CHUNK_STRATEGY,
      size: first?.chunk_size || DEFAULT_CHUNK_SIZE,
      overlap: first?.chunk_overlap ?? DEFAULT_CHUNK_OVERLAP,
    });
    setRechunkErr(null);
    setRechunkTargets(ids);
    setRechunkOpen(true);
  }

  async function doRechunk() {
    setRechunkBusy(true);
    setRechunkErr(null);
    try {
      await api.rechunkSources(project.id, rechunkTargets, {
        chunking_strategy: rechunkForm.strategy,
        chunk_size: Number(rechunkForm.size) || undefined,
        chunk_overlap: Number.isFinite(rechunkForm.overlap) ? Number(rechunkForm.overlap) : undefined,
      });
      setRechunkOpen(false);
      setSelected(new Set());
      reload();
    } catch (e: any) {
      setRechunkErr(e?.message || "Re-chunk failed. Please try again.");
    } finally {
      setRechunkBusy(false);
    }
  }

  function openAdd(forFolder?: string) {
    setTargetFolder(forFolder ?? (inNamedFolder ? folder! : ""));
    setAddErr(null);
    setOpen(true);
  }

  async function add() {
    setBusy(true);
    setAddErr(null);
    try {
      if (form.kind === "file") {
        if (!form.file) {
          setAddErr("Choose a file to upload.");
          return;
        }
        await api.uploadSource(project.id, form.file, targetFolder || undefined, form.chunkStrategy);
      } else {
        await api.addSource(project.id, {
          kind: form.kind,
          name: form.name || "Untitled",
          folder: targetFolder || undefined,
          text: form.kind === "text" ? form.text : undefined,
          uri: form.kind === "url" || form.kind === "crawl" ? form.uri : undefined,
          chunking_strategy: form.chunkStrategy,
        });
      }
      setOpen(false);
      setForm({
        kind: "text",
        name: "",
        text: "",
        uri: "",
        file: null,
        chunkStrategy: "recursive",
      });
      reload();
    } catch (e: any) {
      setAddErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function dedupe() {
    if (!window.confirm("Remove exact-duplicate chunks across this project?")) return;
    setDedupeBusy(true);
    setDedupeMsg(null);
    try {
      const r = await api.dedupeChunks(project.id);
      setDedupeMsg(
        r.removed === 0
          ? "No duplicate chunks found."
          : `Removed ${r.removed} duplicate chunks across ${r.sources_affected} sources.`
      );
      reload();
    } catch (e: any) {
      setDedupeMsg(`Dedupe failed: ${e?.message || e}`);
    } finally {
      setDedupeBusy(false);
    }
  }

  function FolderRow({ value, label, count }: { value: string | null; label: string; count: number }) {
    const active = folder === value;
    return (
      <button
        onClick={() => setFolder(value)}
        className="row spread"
        style={{
          width: "100%",
          alignItems: "center",
          padding: "7px 10px",
          borderRadius: 7,
          border: "none",
          cursor: "pointer",
          background: active ? "var(--bg-3)" : "transparent",
          color: active ? "var(--fg-0)" : "var(--fg-1)",
          fontSize: 13,
        }}
      >
        <span className="row gap2" style={{ alignItems: "center", minWidth: 0 }}>
          <Icon name={value === null ? "file" : value === UNFILED ? "file" : "n_router"} size={14} />
          <span className="truncate">{label}</span>
        </span>
        <span className="t-caption fg-2 mono">{count}</span>
      </button>
    );
  }

  return (
    <div className="row" style={{ gap: 20, alignItems: "flex-start" }}>
      {/* Folder sidebar */}
      <div className="card col" style={{ width: 240, flex: "none", padding: 12, gap: 2 }}>
        <div className="fg-2 t-micro" style={{ padding: "4px 8px 6px" }}>FOLDERS</div>
        <FolderRow value={null} label="All files" count={rows.length} />
        <FolderRow value={UNFILED} label="Unfiled" count={rows.filter((s) => !s.folder).length} />
        {folders.map((f) => (
          <FolderRow
            key={f}
            value={f}
            label={f}
            count={rows.filter((s) => s.folder === f).length}
          />
        ))}
        {newFolder === null ? (
          <button
            className="btn btn-ghost btn-sm"
            style={{ justifyContent: "flex-start", marginTop: 6 }}
            onClick={() => setNewFolder("")}
          >
            <Icon name="plus" size={13} /> New folder
          </button>
        ) : (
          <input
            autoFocus
            className="input"
            style={{ marginTop: 6, fontSize: 13 }}
            placeholder="Folder name…"
            value={newFolder}
            onChange={(e) => setNewFolder(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newFolder.trim()) {
                const nf = newFolder.trim();
                setFolder(nf);
                setNewFolder(null);
                openAdd(nf);
              }
              if (e.key === "Escape") setNewFolder(null);
            }}
            onBlur={() => setNewFolder(null)}
          />
        )}
      </div>

      {/* Main Table */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="row spread" style={{ marginBottom: 14 }}>
          <div className="row gap2" style={{ alignItems: "center" }}>
            <span className="t-h2">{folder === null ? "All files" : folder === UNFILED ? "Unfiled" : folder}</span>
            <span className="chip chip-mono">{visible.length}</span>
          </div>
          <div className="row gap2">
            <button className="btn btn-ghost btn-sm" onClick={dedupe} disabled={dedupeBusy}>
              <Icon name={dedupeBusy ? "refresh" : "layers"} size={14} /> Remove duplicates
            </button>
            <button className="btn btn-primary btn-sm" onClick={() => openAdd()}>
              <Icon name="plus" size={14} /> Add source
            </button>
          </div>
        </div>

        {dedupeMsg && (
          <div className="card row spread" style={{ padding: "8px 14px", marginBottom: 12 }}>
            <span className="t-body-sm">{dedupeMsg}</span>
            <button className="iconbtn" onClick={() => setDedupeMsg(null)}>
              <Icon name="close" size={13} />
            </button>
          </div>
        )}

        {selected.size > 0 && (
          <div className="card row spread" style={{ padding: "8px 14px", marginBottom: 12 }}>
            <span className="t-body-sm">
              <b>{selected.size}</b> selected
            </span>
            <div className="row gap2">
              <button className="btn btn-secondary btn-sm" onClick={() => openRechunk([...selected])}>
                Re-chunk selected
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelected(new Set())}>
                Clear
              </button>
            </div>
          </div>
        )}

        <div className="card" style={{ overflow: "hidden" }}>
          <table className="tbl" style={{ width: "100%" }}>
            <thead>
              <tr>
                <th style={{ width: 36 }}>
                  <input type="checkbox" checked={allVisibleSelected} onChange={toggleAllVisible} />
                </th>
                <th>Name</th>
                <th>Kind</th>
                {showFolderCol && <th>Folder</th>}
                <th>Status</th>
                <th>Chunks</th>
                <th>Chunking</th>
                <th style={{ width: 80 }} />
              </tr>
            </thead>
            <tbody>
              {visible.map((s) => (
                <tr key={s.id} style={selected.has(s.id) ? { background: "var(--bg-3)" } : undefined}>
                  <td>
                    <input type="checkbox" checked={selected.has(s.id)} onChange={() => toggleSel(s.id)} />
                  </td>
                  <td style={{ fontWeight: 600 }}>{s.name}</td>
                  <td>
                    <span className="typechip">{s.kind}</span>
                  </td>
                  {showFolderCol && (
                    <td>
                      <select
                        className="select"
                        style={{ fontSize: 12, padding: "2px 6px" }}
                        value={s.folder || UNFILED}
                        onChange={async (e) => {
                          await api.moveSource(project.id, s.id, e.target.value);
                          reload();
                        }}
                      >
                        <option value={UNFILED}>Unfiled</option>
                        {folders.map((f) => (
                          <option key={f} value={f}>
                            {f}
                          </option>
                        ))}
                      </select>
                    </td>
                  )}
                  <td>
                    <StatusPill status={s.status} />
                  </td>
                  <td className="mono-sm">{s.chunks}</td>
                  <td>
                    <span className="typechip">{s.chunking_strategy || DEFAULT_CHUNK_STRATEGY}</span>
                    <div className="t-caption fg-2 mono" style={{ marginTop: 2 }}>
                      {s.chunk_size || DEFAULT_CHUNK_SIZE}/{s.chunk_overlap ?? DEFAULT_CHUNK_OVERLAP}
                    </div>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <div className="row gap1" style={{ justifyContent: "flex-end" }}>
                      <button className="iconbtn" title="Re-chunk" onClick={() => openRechunk([s.id])}>
                        <Icon name="layers" size={14} />
                      </button>
                      <button
                        className="iconbtn"
                        title="Delete"
                        onClick={async () => {
                          await api.deleteSource(project.id, s.id);
                          reload();
                        }}
                      >
                        <Icon name="trash" size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={showFolderCol ? 8 : 7} style={{ textAlign: "center", padding: 32, color: "var(--fg-2)" }}>
                    No sources in this folder.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Modal */}
      <Modal open={open} onClose={() => setOpen(false)} title={`Add source to “${targetFolder || "Unfiled"}”`} width={560}>
        <div className="col gap3" style={{ padding: 18 }}>
          <Field label="Kind">
            <Segmented
              options={[
                { value: "text", label: "Paste text" },
                { value: "url", label: "URL" },
                { value: "file", label: "Upload file" },
              ]}
              value={form.kind}
              onChange={(v) => setForm((f) => ({ ...f, kind: v }))}
            />
          </Field>
          {form.kind !== "file" && (
            <Field label="Name">
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Title / Subject"
              />
            </Field>
          )}
          {form.kind === "text" && (
            <Field label="Text Content">
              <textarea
                className="input"
                rows={6}
                value={form.text}
                onChange={(e) => setForm((f) => ({ ...f, text: e.target.value }))}
                placeholder="Paste document contents…"
              />
            </Field>
          )}
          {form.kind === "url" && (
            <Field label="URL">
              <input
                className="input"
                value={form.uri}
                onChange={(e) => setForm((f) => ({ ...f, uri: e.target.value }))}
                placeholder="https://example.com/docs"
              />
            </Field>
          )}
          {form.kind === "file" && (
            <Field label="File">
              <input type="file" onChange={(e) => setForm((f) => ({ ...f, file: e.target.files?.[0] || null }))} />
            </Field>
          )}
          {addErr && <div style={{ color: "var(--err)", fontSize: 13 }}>{addErr}</div>}
          <div className="row end gap2" style={{ marginTop: 12 }}>
            <button className="btn btn-secondary" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={add} disabled={busy}>
              {busy ? "Ingesting…" : "Add Source"}
            </button>
          </div>
        </div>
      </Modal>

      {/* Rechunk Modal */}
      <Modal open={rechunkOpen} onClose={() => setRechunkOpen(false)} title={`Re-chunk ${rechunkTargets.length} source(s)`} width={480}>
        <div className="col gap3" style={{ padding: 18 }}>
          <Field label="Strategy">
            <select className="input" value={rechunkForm.strategy} onChange={(e) => setRechunkForm((f) => ({ ...f, strategy: e.target.value }))}>
              <option value="recursive">Recursive Character</option>
              <option value="section">By Section (Markdown)</option>
              <option value="sentence">By Sentence</option>
            </select>
          </Field>
          <div className="row gap2">
            <Field label="Chunk Size (chars)">
              <input
                type="number"
                className="input"
                value={rechunkForm.size}
                onChange={(e) => setRechunkForm((f) => ({ ...f, size: Number(e.target.value) }))}
              />
            </Field>
            <Field label="Overlap (chars)">
              <input
                type="number"
                className="input"
                value={rechunkForm.overlap}
                onChange={(e) => setRechunkForm((f) => ({ ...f, overlap: Number(e.target.value) }))}
              />
            </Field>
          </div>
          {rechunkErr && <div style={{ color: "var(--err)", fontSize: 13 }}>{rechunkErr}</div>}
          <div className="row end gap2" style={{ marginTop: 12 }}>
            <button className="btn btn-secondary" onClick={() => setRechunkOpen(false)}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={doRechunk} disabled={rechunkBusy}>
              {rechunkBusy ? "Re-chunking…" : "Re-chunk & Re-embed"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function SearchDebugger({ project }: { project: any }) {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<"vector" | "hybrid">("vector");
  const [folder, setFolder] = useState<string>("");
  const [folders, setFolders] = useState<string[]>([]);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [rerank, setRerank] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (project?.id) api.listFolders(project.id).then(setFolders).catch(() => {});
  }, [project?.id]);

  async function run() {
    if (busy || !q.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const h = await api.searchKnowledge(project.id, q, 8, folder ? [folder] : undefined, mode === "hybrid", rerank);
      setHits(h);
      setSearched(true);
    } catch (e: any) {
      setErr(e?.message || "Search failed.");
      setHits([]);
      setSearched(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="col gap3">
      <div className="row gap2" style={{ alignItems: "center" }}>
        <input
          className="input"
          style={{ flex: 1, height: 38 }}
          placeholder="Query the knowledge base…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
        />
        {folders.length > 0 && (
          <select className="select" style={{ width: 170, height: 38 }} value={folder} onChange={(e) => setFolder(e.target.value)}>
            <option value="">All folders</option>
            {folders.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        )}
        <button className="btn btn-primary" style={{ height: 38, padding: "0 18px" }} onClick={run} disabled={busy || !q.trim()}>
          <Icon name={busy ? "refresh" : "search"} size={14} style={busy ? { animation: "spin 1s linear infinite" } : {}} />
          {busy ? "Searching…" : "Search"}
        </button>
      </div>

      {err && <div className="t-caption" style={{ color: "var(--err)" }}>{err}</div>}

      <div className="row gap2" style={{ alignItems: "center" }}>
        <Segmented
          options={[
            { value: "vector", label: "Vector" },
            { value: "hybrid", label: "Hybrid" },
          ]}
          value={mode}
          onChange={(v) => setMode(v as "vector" | "hybrid")}
        />
        <label className="row gap1" style={{ alignItems: "center", cursor: "pointer", fontSize: 13 }}>
          <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />
          <span>Cross-Encoder Rerank</span>
        </label>
        <span className="t-caption fg-2">
          {mode === "hybrid" ? "BM25 lexical + vector fused via RRF." : "Cosine similarity against Chroma vectors."}
        </span>
      </div>

      <div className="col gap2" style={{ marginTop: 6 }}>
        {hits.map((h, i) => (
          <div key={i} className="card" style={{ padding: 14 }}>
            <div className="row spread" style={{ marginBottom: 6 }}>
              <span className="t-caption fg-2 mono">{h.source_id?.slice(0, 12) || "-"}</span>
              <span className="chip chip-mono">score {h.score.toFixed(3)}</span>
            </div>
            <div className="t-body-sm" style={{ whiteSpace: "pre-wrap", lineHeight: "20px" }}>
              {h.text}
            </div>
          </div>
        ))}
        {searched && hits.length === 0 && (
          <div className="card fg-2" style={{ padding: 32, textAlign: "center" }}>
            No matches found for this query.
          </div>
        )}
      </div>
    </div>
  );
}
