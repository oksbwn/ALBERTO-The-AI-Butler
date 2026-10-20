"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "../icons";
import {
  api,
  CuratorAdvisorySuggestion,
  EdgeApprovalEdit,
  LearningEventApprovalIn,
  LearningEventItem,
  NodeApprovalEdit,
  OntologyEntityType,
  OntologyRelationshipType,
} from "@/lib/api";

interface EventEditState {
  nodes: Record<string, { kind: string; customKind: string; description: string }>;
  edges: Record<
    number,
    {
      kind: string;
      customKind: string;
      direction: "normal" | "reverse";
      source_ref: string;
      target_ref: string;
    }
  >;
}

function formatHumanReason(reason: string): string {
  if (!reason) return "";
  let m = reason.match(/Low confidence \(([\d.]+)\) on entity candidate ['"]?([^'"]+)['"]?/i);
  if (m) return `Alberto isn't completely sure if "${m[2]}" should be saved (${Math.round(parseFloat(m[1]) * 100)}% certainty).`;

  m = reason.match(/Low confidence \(([\d.]+)\) on relationship candidate ['"]?([^'"]+)['"]?/i);
  if (m) return `Alberto is uncertain about the "${m[2]}" connection (${Math.round(parseFloat(m[1]) * 100)}% certainty).`;

  m = reason.match(/Low confidence \(([\d.]+)\) on candidate ['"]?([^'"]+)['"]?/i);
  if (m) return `Uncertain about saving fact: "${m[2]}" (${Math.round(parseFloat(m[1]) * 100)}% certainty).`;

  m = reason.match(/Missing evidence_refs on candidate ['"]?([^'"]+)['"]?/i);
  if (m) return `Needs confirmation from your chat before saving "${m[1]}".`;

  m = reason.match(/Ungrounded evidence_refs on candidate ['"]?([^'"]+)['"]?/i);
  if (m) return `Could not verify "${m[1]}" directly from your message.`;

  m = reason.match(/Proposed deletion requires human confirmation:? ['"]?([^'"]+)['"]?/i);
  if (m) return `Alberto wants to delete "${m[1]}" — please confirm.`;

  m = reason.match(/Candidate entity kind ['"]?([^'"]+)['"]? not in canonical ontology/i);
  if (m) return `Suggested new category: "${m[1]}".`;

  m = reason.match(/Unresolved (?:source|target) entity reference:? ['"]?([^'"]+)['"]?/i);
  if (m) return `Connects to "${m[1]}", which isn't saved in your knowledge graph yet.`;

  if (/sensitive credential/i.test(reason)) {
    return "May contain sensitive info or credentials — review carefully.";
  }

  return reason.replace(/_/g, " ");
}

export function OntologyReviewQueue({
  project,
  onCountChange,
}: {
  project: any;
  onCountChange?: (count: number) => void;
}) {
  const [reviewEvents, setReviewEvents] = useState<LearningEventItem[]>([]);
  const [ontologyEntityTypes, setOntologyEntityTypes] = useState<OntologyEntityType[]>([]);
  const [ontologyRelTypes, setOntologyRelTypes] = useState<OntologyRelationshipType[]>([]);
  const [eventEdits, setEventEdits] = useState<Record<string, EventEditState>>({});
  const [suggestions, setSuggestions] = useState<Record<string, CuratorAdvisorySuggestion[]>>({});
  const [fetchingSuggestions, setFetchingSuggestions] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);

  const onCountChangeRef = useRef(onCountChange);
  useEffect(() => {
    onCountChangeRef.current = onCountChange;
  }, [onCountChange]);

  const reload = useCallback(() => {
    if (!project?.id) return;
    setLoading(true);
    Promise.all([
      api.listLearningEvents(project.id, "review_required").catch(() => []),
      api.listOntologyEntityTypes(project.id).catch(() => []),
      api.listOntologyRelationshipTypes(project.id).catch(() => []),
    ])
      .then(([evs, ets, rts]) => {
        setReviewEvents(evs || []);
        setOntologyEntityTypes(ets || []);
        setOntologyRelTypes(rts || []);
        onCountChangeRef.current?.(evs?.length ?? 0);
      })
      .finally(() => setLoading(false));
  }, [project?.id]);

  useEffect(() => {
    reload();
  }, [reload]);

  const handleFetchSuggestions = async (eventId: string) => {
    if (!project?.id) return;
    setFetchingSuggestions((prev) => ({ ...prev, [eventId]: true }));
    try {
      const suggs = await api.getLearningEventSuggestions(project.id, eventId);
      setSuggestions((prev) => ({ ...prev, [eventId]: suggs || [] }));
    } catch (e: any) {
      alert(`Failed to fetch curator suggestions: ${e?.message || e}`);
    } finally {
      setFetchingSuggestions((prev) => ({ ...prev, [eventId]: false }));
    }
  };

  const applySuggestion = (eventId: string, sugg: CuratorAdvisorySuggestion) => {
    if (sugg.target_type === "entity") {
      setEventEdits((prev) => {
        const current = prev[eventId] || { nodes: {}, edges: {} };
        const nodeCurrent = current.nodes[sugg.target_ref] || {
          kind: sugg.suggested_kind || "",
          customKind: "",
          description: "",
        };
        return {
          ...prev,
          [eventId]: {
            ...current,
            nodes: {
              ...current.nodes,
              [sugg.target_ref]: {
                ...nodeCurrent,
                kind: sugg.suggested_kind || nodeCurrent.kind,
              },
            },
          },
        };
      });
    } else if (sugg.target_type === "relationship") {
      setEventEdits((prev) => {
        const current = prev[eventId] || { nodes: {}, edges: {} };
        const idx = parseInt(sugg.target_ref, 10) || 0;
        const edgeCurrent = current.edges[idx] || {
          kind: sugg.suggested_kind || "",
          customKind: "",
          direction: sugg.suggested_direction || "normal",
          source_ref: "",
          target_ref: "",
        };
        return {
          ...prev,
          [eventId]: {
            ...current,
            edges: {
              ...current.edges,
              [idx]: {
                ...edgeCurrent,
                kind: sugg.suggested_kind || edgeCurrent.kind,
                direction: sugg.suggested_direction || edgeCurrent.direction,
              },
            },
          },
        };
      });
    }
  };

  const handleApprove = async (eventId: string) => {
    if (!project?.id) return;
    setApprovingId(eventId);
    const evEdit = eventEdits[eventId];
    const node_edits: NodeApprovalEdit[] = [];
    if (evEdit?.nodes) {
      for (const [tempId, n] of Object.entries(evEdit.nodes)) {
        const finalKind = n.kind === "__custom__" ? n.customKind.trim().toLowerCase() : n.kind;
        const isNew = n.kind === "__custom__";
        node_edits.push({
          temporary_id: tempId,
          kind: finalKind || undefined,
          description: n.description || undefined,
          is_new_ontology_type: isNew,
          ontology_type_description: isNew ? `User-defined entity type ${finalKind}` : undefined,
        });
      }
    }
    const edge_edits: EdgeApprovalEdit[] = [];
    if (evEdit?.edges) {
      for (const [, e] of Object.entries(evEdit.edges)) {
        const finalKind = e.kind === "__custom__" ? e.customKind.trim().toUpperCase() : e.kind;
        const isNew = e.kind === "__custom__";
        edge_edits.push({
          source_ref: e.source_ref,
          target_ref: e.target_ref,
          kind: finalKind || undefined,
          direction: e.direction,
          is_new_ontology_type: isNew,
          ontology_type_description: isNew ? `User-defined relationship type ${finalKind}` : undefined,
        });
      }
    }

    const payload: LearningEventApprovalIn = {
      node_edits: node_edits.length > 0 ? node_edits : undefined,
      edge_edits: edge_edits.length > 0 ? edge_edits : undefined,
    };

    try {
      await api.approveLearningEvent(project.id, eventId, payload);
      reload();
    } catch (e: any) {
      alert(`Approval error: ${e?.message || e}`);
    } finally {
      setApprovingId(null);
    }
  };

  const handleReject = async (eventId: string) => {
    if (!project?.id) return;
    setRejectingId(eventId);
    try {
      await api.rejectLearningEvent(project.id, eventId);
      reload();
    } catch (e: any) {
      alert(`Rejection error: ${e?.message || e}`);
    } finally {
      setRejectingId(null);
    }
  };

  const availableEntityKinds = Array.from(
    new Set([
      ...ontologyEntityTypes.map((t) => t.canonical_key),
      "concept",
      "entity",
      "fact",
      "rule",
      "preference",
      "user",
      "agent",
      "project",
      "document",
      "tool",
      "source",
      "hardware",
      "software",
      "application",
      "device",
      "operating_system",
      "container_runtime",
      "inference_framework",
    ])
  );

  const availableRelKinds = Array.from(
    new Set([
      ...ontologyRelTypes.map((t) => t.canonical_key),
      "RELATES_TO",
      "IS_A",
      "PART_OF",
      "USES",
      "IMPLEMENTS",
      "PREFERS",
      "LEARNED_FROM",
      "LOCATED_AT",
      "RUNS_ON",
      "RUNS",
      "DEPLOYED_VIA",
      "INTERACTS_WITH",
    ])
  );

  if (loading && reviewEvents.length === 0) {
    return (
      <div className="card" style={{ padding: 36, textAlign: "center", color: "var(--fg-2)" }}>
        <Icon name="refresh" size={18} style={{ animation: "spin 1s linear infinite", marginBottom: 8 }} />
        <div>Checking review queue…</div>
      </div>
    );
  }

  return (
    <div className="col gap3">
      <div className="card" style={{ padding: 22 }}>
        <div className="row spread" style={{ alignItems: "center", marginBottom: 14 }}>
          <div>
            <div className="row gap2" style={{ alignItems: "center" }}>
              <span className="t-h1">Memory &amp; Knowledge Reviews</span>
              <span
                className="badge"
                style={{
                  background:
                    reviewEvents.length > 0
                      ? "rgba(234, 179, 8, 0.15)"
                      : "rgba(34, 197, 94, 0.15)",
                  color:
                    reviewEvents.length > 0 ? "var(--warn, #eab308)" : "var(--ok, #22c55e)",
                  fontWeight: 600,
                }}
              >
                {reviewEvents.length > 0
                  ? `${reviewEvents.length} Items to Review`
                  : "All Up to Date"}
              </span>
            </div>
            <div className="fg-2 t-caption" style={{ marginTop: 4 }}>
              Alberto identified new facts, devices, or connections from your conversations. Confirm or adjust them before saving to your home knowledge.
            </div>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={reload} disabled={loading}>
            <Icon
              name={loading ? "refresh" : "check"}
              size={13}
              style={loading ? { animation: "spin 1s linear infinite" } : {}}
            />
            {loading ? "Checking…" : "Refresh"}
          </button>
        </div>

        {reviewEvents.length === 0 && (
          <div
            className="card center col"
            style={{ padding: 48, textAlign: "center", color: "var(--fg-2)", background: "var(--bg-1)" }}
          >
            <Icon name="shield-check" size={32} style={{ color: "var(--ok)", marginBottom: 8 }} />
            <div className="t-h3" style={{ color: "var(--fg-0)" }}>No Pending Reviews</div>
            <div className="t-caption" style={{ maxWidth: 440, marginTop: 4 }}>
              All learned facts, devices, and relationships are confirmed and up to date in your knowledge graph.
            </div>
          </div>
        )}

        <div className="col gap4">
          {reviewEvents.map((ev) => {
            const mems = (ev.extraction_payload as any)?.memories || [];
            const ents = (ev.extraction_payload as any)?.entities || [];
            const rels = (ev.extraction_payload as any)?.relationships || [];
            const entNameMap: Record<string, string> = {};
            for (const e of ents) {
              if (e.temporary_id && e.name) entNameMap[e.temporary_id] = e.name;
              if (e.id && e.name) entNameMap[e.id] = e.name;
            }
            const resolveName = (ref: string) => entNameMap[ref] || ref.replace(/^(ent_|tmp_|node_)/, "");
            const reasons: string[] =
              (ev.extraction_payload as any)?.review_reasons || (ev.error ? [ev.error] : []);
            const evSuggs = suggestions[ev.id] || [];
            const isFetchingSugg = fetchingSuggestions[ev.id] || false;
            const currentEdits = eventEdits[ev.id] || { nodes: {}, edges: {} };
            const isApproving = approvingId === ev.id;
            const isRejecting = rejectingId === ev.id;

            return (
              <div
                key={ev.id}
                className="card col gap3"
                style={{
                  padding: 20,
                  background: "var(--bg-1)",
                  border: "1px solid var(--line)",
                }}
              >
                {/* Event Top Bar */}
                <div className="row spread" style={{ alignItems: "flex-start", flexWrap: "wrap", gap: 10 }}>
                  <div>
                    <div className="row gap2" style={{ alignItems: "center" }}>
                      <span className="badge" style={{ background: "rgba(234, 179, 8, 0.15)", color: "var(--warn)" }}>
                        Needs Confirmation
                      </span>
                      <span className="typechip">Learned from chat</span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="row gap2">
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => handleFetchSuggestions(ev.id)}
                      disabled={isFetchingSugg}
                      title="Ask Alberto for advice on these items"
                    >
                      <Icon
                        name={isFetchingSugg ? "refresh" : "sparkles"}
                        size={13}
                        style={isFetchingSugg ? { animation: "spin 1s linear infinite" } : { color: "var(--accent)" }}
                      />
                      <span>{isFetchingSugg ? "Analyzing…" : "Alberto's Advice"}</span>
                    </button>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => handleReject(ev.id)}
                      disabled={isRejecting || isApproving}
                    >
                      <Icon name="close" size={13} />
                      <span>{isRejecting ? "Dismissing…" : "Dismiss"}</span>
                    </button>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => handleApprove(ev.id)}
                      disabled={isApproving || isRejecting}
                    >
                      <Icon name="check" size={13} />
                      <span>{isApproving ? "Saving…" : "Approve & Save"}</span>
                    </button>
                  </div>
                </div>

                {/* Review Reasons / Warnings */}
                {reasons.length > 0 && (
                  <div
                    className="card"
                    style={{
                      padding: "10px 14px",
                      background: "rgba(234, 179, 8, 0.08)",
                      border: "1px solid rgba(234, 179, 8, 0.25)",
                    }}
                  >
                    <div className="row gap2" style={{ alignItems: "center" }}>
                      <Icon name="bolt" size={14} style={{ color: "var(--warn)" }} />
                      <span className="t-body-sm" style={{ fontWeight: 600, color: "var(--warn)" }}>
                        Why Alberto flagged this:
                      </span>
                    </div>
                    <ul style={{ margin: "6px 0 0 20px", padding: 0 }}>
                      {reasons.map((r, i) => (
                        <li key={i} className="t-caption fg-1" style={{ lineHeight: "19px" }}>
                          {formatHumanReason(r)}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Turn Context Snippet */}
                {(ev.extraction_payload as any)?.turn_user_text && (
                  <div>
                    <div className="t-caption fg-2" style={{ fontWeight: 600, marginBottom: 4 }}>
                      From your conversation:
                    </div>
                    <div
                      className="card"
                      style={{
                        padding: 12,
                        background: "var(--bg-0)",
                        fontStyle: "italic",
                        fontSize: 13,
                        lineHeight: "19px",
                      }}
                    >
                      "{(ev.extraction_payload as any).turn_user_text}"
                    </div>
                  </div>
                )}

                {/* Curator Advisory Suggestions */}
                {evSuggs.length > 0 && (
                  <div
                    className="card col gap2"
                    style={{
                      padding: 14,
                      background: "rgba(99, 102, 241, 0.08)",
                      border: "1px solid rgba(99, 102, 241, 0.3)",
                    }}
                  >
                    <div className="row spread" style={{ alignItems: "center" }}>
                      <span className="t-body-sm" style={{ color: "var(--accent)", fontWeight: 600 }}>
                        Alberto's Suggestions
                      </span>
                      <span className="chip chip-mono t-micro">{evSuggs.length} suggestions</span>
                    </div>
                    <div className="col gap2">
                      {evSuggs.map((sugg, sIdx) => (
                        <div
                          key={sIdx}
                          className="card row spread"
                          style={{ padding: 10, background: "var(--bg-0)", alignItems: "center" }}
                        >
                          <div style={{ flex: 1, minWidth: 0, marginRight: 12 }}>
                            <div className="row gap2" style={{ alignItems: "center", flexWrap: "wrap" }}>
                              <span className="badge">{sugg.target_type}</span>
                              <span className="mono-sm" style={{ fontWeight: 600 }}>
                                {resolveName(sugg.target_ref)}
                              </span>
                              {sugg.suggested_kind && (
                                <span className="t-caption">
                                  → Suggested category:{" "}
                                  <strong style={{ color: "var(--ok)" }}>{sugg.suggested_kind}</strong>
                                </span>
                              )}
                              {sugg.suggested_direction && (
                                <span className="t-caption">
                                  → Flow: <strong>{sugg.suggested_direction}</strong>
                                </span>
                              )}
                            </div>
                            <div className="t-caption fg-2" style={{ marginTop: 4 }}>
                              {sugg.explanation}
                            </div>
                          </div>
                          <button
                            className="btn btn-secondary btn-sm"
                            style={{ flex: "none" }}
                            onClick={() => applySuggestion(ev.id, sugg)}
                          >
                            Apply
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 1. Proposed Entities */}
                {ents.length > 0 && (
                  <div>
                    <div className="t-caption fg-2" style={{ fontWeight: 600, marginBottom: 6 }}>
                      Discovered Items &amp; Devices:
                    </div>
                    <div className="col gap2">
                      {ents.map((e: any) => {
                        const nodeKey = e.temporary_id || e.name;
                        const nodeEdit = currentEdits.nodes[nodeKey] || {
                          kind: e.kind || "entity",
                          customKind: "",
                          description: e.description || "",
                        };
                        const isCustom = nodeEdit.kind === "__custom__";

                        return (
                          <div
                            key={nodeKey}
                            className="card col gap2"
                            style={{ padding: 12, background: "var(--bg-0)" }}
                          >
                            <div className="row spread" style={{ alignItems: "center" }}>
                              <div className="row gap2" style={{ alignItems: "center" }}>
                                <span className="t-body-sm" style={{ fontWeight: 600 }}>
                                  {e.name}
                                </span>
                                <span className="typechip">{e.kind}</span>
                              </div>
                              {e.confidence !== undefined && (
                                <span className="chip chip-mono t-micro">
                                  {Math.round(e.confidence * 100)}% certainty
                                </span>
                              )}
                            </div>

                            <div className="row gap2" style={{ alignItems: "center", flexWrap: "wrap" }}>
                              <span className="t-caption fg-2" style={{ width: 80, flex: "none" }}>
                                Category:
                              </span>
                              <select
                                className="select mono-sm"
                                style={{ flex: 1, minWidth: 220 }}
                                value={nodeEdit.kind}
                                onChange={(evt) => {
                                  const val = evt.target.value;
                                  setEventEdits((prev) => {
                                    const cur = prev[ev.id] || { nodes: {}, edges: {} };
                                    return {
                                      ...prev,
                                      [ev.id]: {
                                        ...cur,
                                        nodes: {
                                          ...cur.nodes,
                                          [nodeKey]: {
                                            ...nodeEdit,
                                            kind: val,
                                          },
                                        },
                                      },
                                    };
                                  });
                                }}
                              >
                                {availableEntityKinds.map((k) => (
                                  <option key={k} value={k}>
                                    {k}
                                  </option>
                                ))}
                                <option value="__custom__">+ Add Custom Category…</option>
                              </select>

                              {isCustom && (
                                <input
                                  className="input mono-sm"
                                  placeholder="Type custom category name…"
                                  style={{ flex: 1, minWidth: 200 }}
                                  value={nodeEdit.customKind}
                                  onChange={(evt) => {
                                    const val = evt.target.value;
                                    setEventEdits((prev) => {
                                      const cur = prev[ev.id] || { nodes: {}, edges: {} };
                                      return {
                                        ...prev,
                                        [ev.id]: {
                                          ...cur,
                                          nodes: {
                                            ...cur.nodes,
                                            [nodeKey]: {
                                              ...nodeEdit,
                                              customKind: val,
                                            },
                                          },
                                        },
                                      };
                                    });
                                  }}
                                />
                              )}
                            </div>

                            <div className="row gap2" style={{ alignItems: "center" }}>
                              <span className="t-caption fg-2" style={{ width: 80, flex: "none" }}>
                                Notes:
                              </span>
                              <input
                                className="input"
                                style={{ flex: 1 }}
                                value={nodeEdit.description}
                                placeholder="Optional notes or details…"
                                onChange={(evt) => {
                                  const val = evt.target.value;
                                  setEventEdits((prev) => {
                                    const cur = prev[ev.id] || { nodes: {}, edges: {} };
                                    return {
                                      ...prev,
                                      [ev.id]: {
                                        ...cur,
                                        nodes: {
                                          ...cur.nodes,
                                          [nodeKey]: {
                                            ...nodeEdit,
                                            description: val,
                                          },
                                        },
                                      },
                                    };
                                  });
                                }}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* 2. Proposed Relationships */}
                {rels.length > 0 && (
                  <div>
                    <div className="t-caption fg-2" style={{ fontWeight: 600, marginBottom: 6 }}>
                      Connections Between Items:
                    </div>
                    <div className="col gap2">
                      {rels.map((r: any, rIdx: number) => {
                        const edgeEdit = currentEdits.edges[rIdx] || {
                          kind: r.kind || "RELATES_TO",
                          customKind: "",
                          direction: "normal" as const,
                          source_ref: r.source_ref,
                          target_ref: r.target_ref,
                        };
                        const isCustom = edgeEdit.kind === "__custom__";
                        const isReversed = edgeEdit.direction === "reverse";
                        const displaySrc = isReversed ? edgeEdit.target_ref : edgeEdit.source_ref;
                        const displayTgt = isReversed ? edgeEdit.source_ref : edgeEdit.target_ref;

                        return (
                          <div
                            key={rIdx}
                            className="card col gap2"
                            style={{ padding: 12, background: "var(--bg-0)" }}
                          >
                            <div className="row spread" style={{ alignItems: "center" }}>
                              <div className="row gap2" style={{ alignItems: "center" }}>
                                <span style={{ fontWeight: 600, color: "var(--fg-0)" }}>
                                  {resolveName(displaySrc)}
                                </span>
                                <span style={{ color: "var(--accent)", fontWeight: 700 }}>→</span>
                                <span style={{ fontWeight: 600, color: "var(--fg-0)" }}>
                                  {resolveName(displayTgt)}
                                </span>
                                {isReversed && (
                                  <span className="badge" style={{ background: "rgba(234,179,8,0.15)", color: "var(--warn)" }}>
                                    Direction Flipped
                                  </span>
                                )}
                              </div>
                              <button
                                className="btn btn-secondary btn-sm"
                                title="Flip relationship direction"
                                onClick={() => {
                                  setEventEdits((prev) => {
                                    const cur = prev[ev.id] || { nodes: {}, edges: {} };
                                    return {
                                      ...prev,
                                      [ev.id]: {
                                        ...cur,
                                        edges: {
                                          ...cur.edges,
                                          [rIdx]: {
                                            ...edgeEdit,
                                            direction: isReversed ? "normal" : "reverse",
                                          },
                                        },
                                      },
                                    };
                                  });
                                }}
                              >
                                <Icon name="refresh" size={12} /> Flip Direction
                              </button>
                            </div>

                            <div className="row gap2" style={{ alignItems: "center", flexWrap: "wrap" }}>
                              <span className="t-caption fg-2" style={{ width: 80, flex: "none" }}>
                                Relationship:
                              </span>
                              <select
                                className="select mono-sm"
                                style={{ flex: 1, minWidth: 220 }}
                                value={edgeEdit.kind}
                                onChange={(evt) => {
                                  const val = evt.target.value;
                                  setEventEdits((prev) => {
                                    const cur = prev[ev.id] || { nodes: {}, edges: {} };
                                    return {
                                      ...prev,
                                      [ev.id]: {
                                        ...cur,
                                        edges: {
                                          ...cur.edges,
                                          [rIdx]: {
                                            ...edgeEdit,
                                            kind: val,
                                          },
                                        },
                                      },
                                    };
                                  });
                                }}
                              >
                                {availableRelKinds.map((rk) => (
                                  <option key={rk} value={rk}>
                                    {rk}
                                  </option>
                                ))}
                                <option value="__custom__">+ Add Custom Relationship…</option>
                              </select>

                              {isCustom && (
                                <input
                                  className="input mono-sm"
                                  placeholder="Type custom relationship name (e.g. CONNECTED_OVER)…"
                                  style={{ flex: 1, minWidth: 200 }}
                                  value={edgeEdit.customKind}
                                  onChange={(evt) => {
                                    const val = evt.target.value;
                                    setEventEdits((prev) => {
                                      const cur = prev[ev.id] || { nodes: {}, edges: {} };
                                      return {
                                        ...prev,
                                        [ev.id]: {
                                          ...cur,
                                          edges: {
                                            ...cur.edges,
                                            [rIdx]: {
                                              ...edgeEdit,
                                              customKind: val,
                                            },
                                          },
                                        },
                                      };
                                    });
                                  }}
                                />
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* 3. Extracted Durable Facts */}
                {mems.length > 0 && (
                  <div>
                    <div className="t-caption fg-2" style={{ fontWeight: 600, marginBottom: 4 }}>
                      Facts to Remember:
                    </div>
                    <div className="col gap1">
                      {mems.map((m: any, mIdx: number) => (
                        <div
                          key={mIdx}
                          className="card row spread"
                          style={{ padding: "6px 12px", background: "var(--bg-0)", alignItems: "center" }}
                        >
                          <div className="t-body-sm">
                            <strong style={{ color: "var(--accent)" }}>[{m.kind || "fact"}]</strong>{" "}
                            {m.content || m.text}
                          </div>
                          {m.confidence !== undefined && (
                            <span className="chip chip-mono t-micro">
                              {Math.round(m.confidence * 100)}% certainty
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
