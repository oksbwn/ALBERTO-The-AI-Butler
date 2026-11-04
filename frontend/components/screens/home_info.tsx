"use client";
import { useEffect, useState } from "react";
import { Icon } from "../icons";
import { StatusPill } from "../primitives";
import {
  api,
  type Conversation,
  type ProjectCounts,
} from "@/lib/api";


function formatTimeAgo(iso?: string | null): string {
  if (!iso) return "recently";
  try {
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  } catch {
    return "recently";
  }
}

/**
 * HomeInfoScreen - AI Butler Concierge Hub.
 * Displays butler intelligence vitals, memory health, quick action shortcuts,
 * and recent interactions in a clean, professional, local-first dashboard.
 */
export function HomeInfoScreen({
  project,
  onNav,
  onMutate,
}: {
  project: any;
  onNav?: (screen: string) => void;
  onMutate?: () => void;
}) {
  const [counts, setCounts] = useState<ProjectCounts | null>(null);
  const [recentConversations, setRecentConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchHubData = async () => {
    if (!project?.id) return;
    setLoading(true);
    try {
      const [c, convos] = await Promise.allSettled([
        api.projectCounts(project.id),
        api.listConversations(project.id, { limit: 4 }),
      ]);
      if (c.status === "fulfilled") setCounts(c.value);
      if (convos.status === "fulfilled") setRecentConversations(convos.value || []);
    } catch {
      // fallback
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHubData();
  }, [project?.id]);

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: "var(--bg-0)",
        display: "flex",
        flexDirection: "column",
        padding: "16px 20px",
        overflowY: "auto",
      }}
    >
      <div
        style={{
          maxWidth: 850,
          width: "100%",
          margin: "0 auto",
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        {/* 1. Header & Butler Concierge Status */}
        <div className="row spread" style={{ alignItems: "center" }}>
          <div>
            <div className="row gap2" style={{ alignItems: "center" }}>
              <h2 className="t-h2" style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
                Alberto Home
              </h2>
              <StatusPill status="active" label="Butler Online" />
            </div>
            <div className="fg-2 t-caption" style={{ marginTop: 3, fontSize: 11.5 }}>
              AI Home Butler concierge, active automations, and persistent memory.
            </div>
          </div>
          <button
            className="iconbtn"
            title="Refresh concierge status"
            onClick={fetchHubData}
            disabled={loading}
            style={{ width: 30, height: 30 }}
          >
            <Icon name="activity" size={14} className={loading ? "spin" : ""} />
          </button>
        </div>

        {/* 2. Top Metric Cards: Clear Butler Concepts */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 10,
          }}
        >
          {/* Automations */}
          <div
            className="card"
            style={{
              padding: "11px 13px",
              cursor: onNav ? "pointer" : "default",
              transition: "border-color 0.15s ease",
            }}
            onClick={() => onNav?.("workflows")}
            title="View automated home routines and pipelines"
          >
            <div className="row spread" style={{ alignItems: "center", marginBottom: 4 }}>
              <span className="t-caption fg-2" style={{ fontSize: 11.5, fontWeight: 600 }}>
                Automations
              </span>
              <Icon name="workflows" size={15} style={{ color: "var(--accent)" }} />
            </div>
            <div className="t-h1" style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>
              {counts?.workflows ?? 0}
            </div>
            <div className="t-micro fg-2" style={{ fontSize: 10.5, marginTop: 2 }}>
              Home Routines
            </div>
          </div>

          {/* Specialist Agents */}
          <div
            className="card"
            style={{
              padding: "11px 13px",
              cursor: onNav ? "pointer" : "default",
              transition: "border-color 0.15s ease",
            }}
            onClick={() => onNav?.("agents")}
            title="View autonomous sub-agents and personas"
          >
            <div className="row spread" style={{ alignItems: "center", marginBottom: 4 }}>
              <span className="t-caption fg-2" style={{ fontSize: 11.5, fontWeight: 600 }}>
                Specialists
              </span>
              <Icon name="bot" size={15} style={{ color: "var(--io-control)" }} />
            </div>
            <div className="t-h1" style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>
              {counts?.agents ?? 0}
            </div>
            <div className="t-micro fg-2" style={{ fontSize: 10.5, marginTop: 2 }}>
              Active Personas
            </div>
          </div>

          {/* Connected Skills / Tools */}
          <div
            className="card"
            style={{
              padding: "11px 13px",
              cursor: onNav ? "pointer" : "default",
              transition: "border-color 0.15s ease",
            }}
            onClick={() => onNav?.("tools")}
            title="View integrated tools, devices, and connectors"
          >
            <div className="row spread" style={{ alignItems: "center", marginBottom: 4 }}>
              <span className="t-caption fg-2" style={{ fontSize: 11.5, fontWeight: 600 }}>
                Skills & Tools
              </span>
              <Icon name="tools" size={15} style={{ color: "var(--signal)" }} />
            </div>
            <div className="t-h1" style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>
              {(counts?.tools ?? 0) + (counts?.connectors ?? 0)}
            </div>
            <div className="t-micro fg-2" style={{ fontSize: 10.5, marginTop: 2 }}>
              Connected Skills
            </div>
          </div>

          {/* Memory & Knowledge */}
          <div
            className="card"
            style={{
              padding: "11px 13px",
              cursor: onNav ? "pointer" : "default",
              transition: "border-color 0.15s ease",
            }}
            onClick={() => onNav?.("knowledge")}
            title="View long-term memories, facts, and knowledge base"
          >
            <div className="row spread" style={{ alignItems: "center", marginBottom: 4 }}>
              <span className="t-caption fg-2" style={{ fontSize: 11.5, fontWeight: 600 }}>
                Memory
              </span>
              <Icon name="brain" size={15} style={{ color: "#a855f7" }} />
            </div>
            <div className="t-h1" style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1 }}>
              {counts?.knowledge ?? 0}
            </div>
            <div className="t-micro fg-2" style={{ fontSize: 10.5, marginTop: 2 }}>
              Recalled Facts & Docs
            </div>
          </div>
        </div>


        {/* 4. Quick Butler Actions (Direct interactive shortcuts) */}
        <div className="card" style={{ padding: "12px 14px", background: "var(--bg-card)" }}>
          <div className="row spread" style={{ alignItems: "center", marginBottom: 10 }}>
            <div className="row gap2" style={{ alignItems: "center" }}>
              <Icon name="workflow" size={15} style={{ color: "var(--accent)" }} />
              <span style={{ fontWeight: 600, fontSize: 13 }}>Quick Butler Actions</span>
            </div>
            <span className="fg-2 t-micro" style={{ fontSize: 10.5 }}>
              Concierge Shortcuts
            </span>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 8,
            }}
          >
            {/* Action 1: Automate a Task */}
            <div
              className="row gap2"
              style={{
                padding: "10px 12px",
                borderRadius: 6,
                background: "var(--bg-surface)",
                border: "1px solid var(--line)",
                cursor: onNav ? "pointer" : "default",
                alignItems: "center",
                transition: "background 0.15s, border-color 0.15s",
              }}
              onClick={() => onNav?.("playground")}
            >
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 6,
                  background: "rgba(99, 102, 241, 0.12)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <Icon name="sparkles" size={16} style={{ color: "var(--accent)" }} />
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 12.5, lineHeight: 1.2 }}>Automate a Task</div>
                <div className="fg-2 t-caption truncate" style={{ fontSize: 11, marginTop: 2 }}>
                  Design a new intelligent workflow pipeline
                </div>
              </div>
            </div>

            {/* Action 2: Teach Alberto */}
            <div
              className="row gap2"
              style={{
                padding: "10px 12px",
                borderRadius: 6,
                background: "var(--bg-surface)",
                border: "1px solid var(--line)",
                cursor: onNav ? "pointer" : "default",
                alignItems: "center",
                transition: "background 0.15s, border-color 0.15s",
              }}
              onClick={() => onNav?.("knowledge-docs")}
            >
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 6,
                  background: "rgba(168, 85, 247, 0.12)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <Icon name="book-open" size={16} style={{ color: "#a855f7" }} />
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 12.5, lineHeight: 1.2 }}>Teach Alberto</div>
                <div className="fg-2 t-caption truncate" style={{ fontSize: 11, marginTop: 2 }}>
                  Store facts, house manuals, or notes in memory
                </div>
              </div>
            </div>

            {/* Action 3: Connect Devices & Tools */}
            <div
              className="row gap2"
              style={{
                padding: "10px 12px",
                borderRadius: 6,
                background: "var(--bg-surface)",
                border: "1px solid var(--line)",
                cursor: onNav ? "pointer" : "default",
                alignItems: "center",
                transition: "background 0.15s, border-color 0.15s",
              }}
              onClick={() => onNav?.("integrations")}
            >
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 6,
                  background: "rgba(245, 158, 11, 0.12)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <Icon name="plug-zap" size={16} style={{ color: "var(--signal)" }} />
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 12.5, lineHeight: 1.2 }}>Connect Devices & Tools</div>
                <div className="fg-2 t-caption truncate" style={{ fontSize: 11, marginTop: 2 }}>
                  Configure MCP tools, smart home, & connectors
                </div>
              </div>
            </div>

            {/* Action 4: Audit Executions */}
            <div
              className="row gap2"
              style={{
                padding: "10px 12px",
                borderRadius: 6,
                background: "var(--bg-surface)",
                border: "1px solid var(--line)",
                cursor: onNav ? "pointer" : "default",
                alignItems: "center",
                transition: "background 0.15s, border-color 0.15s",
              }}
              onClick={() => onNav?.("traces")}
            >
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 6,
                  background: "rgba(16, 185, 129, 0.12)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <Icon name="activity" size={16} style={{ color: "var(--ok)" }} />
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 12.5, lineHeight: 1.2 }}>Audit Executions</div>
                <div className="fg-2 t-caption truncate" style={{ fontSize: 11, marginTop: 2 }}>
                  View run traces, model turns, and safety logs
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 5. Recent Activity & Conversations Timeline */}
        <div className="card" style={{ padding: "12px 14px", background: "var(--bg-card)" }}>
          <div className="row spread" style={{ alignItems: "center", marginBottom: 10 }}>
            <div className="row gap2" style={{ alignItems: "center" }}>
              <Icon name="inbox" size={15} style={{ color: "var(--accent)" }} />
              <span style={{ fontWeight: 600, fontSize: 13 }}>Recent Butler Interactions</span>
            </div>
            {onNav && (
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => onNav("traces")}
                style={{ fontSize: 11, padding: "2px 8px", height: 24 }}
              >
                All History <Icon name="chevright" size={11} />
              </button>
            )}
          </div>

          {recentConversations.length > 0 ? (
            <div className="col gap2">
              {recentConversations.map((c) => (
                <div
                  key={c.thread_id}
                  className="row spread"
                  style={{
                    padding: "8px 10px",
                    background: "var(--bg-surface)",
                    borderRadius: 6,
                    border: "1px solid var(--line)",
                    alignItems: "center",
                    gap: 10,
                  }}
                >
                  <div className="row gap2" style={{ alignItems: "center", minWidth: 0, flex: 1 }}>
                    <div
                      style={{
                        width: 26,
                        height: 26,
                        borderRadius: 5,
                        background: "rgba(99, 102, 241, 0.1)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                      }}
                    >
                      <Icon name="bot" size={13} style={{ color: "var(--accent)" }} />
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div className="truncate" style={{ fontSize: 12, fontWeight: 600 }}>
                        {c.preview || "Conversation Turn"}
                      </div>
                      <div className="fg-2 t-micro" style={{ fontSize: 10.5, marginTop: 1 }}>
                        {c.turns} {c.turns === 1 ? "turn" : "turns"} · {formatTimeAgo(c.last_activity || c.started_at)}
                      </div>
                    </div>
                  </div>

                  <StatusPill
                    status={c.status === "done" ? "done" : c.status === "error" ? "error" : "running"}
                    label={c.status === "done" ? "Completed" : c.status === "error" ? "Error" : "Active"}
                  />
                </div>
              ))}
            </div>
          ) : (
            <div
              style={{
                padding: "16px 12px",
                textAlign: "center",
                color: "var(--fg-2)",
                fontSize: 12,
                background: "var(--bg-surface)",
                borderRadius: 6,
                border: "1px dashed var(--line)",
              }}
            >
              <Icon name="bot" size={20} style={{ margin: "0 auto 6px", opacity: 0.5 }} />
              <div style={{ fontWeight: 600, color: "var(--fg-1)", marginBottom: 2 }}>
                No recent interactions yet
              </div>
              <div style={{ fontSize: 11, maxWidth: 360, margin: "0 auto" }}>
                Ask Alberto a question in the chat panel on the right or launch an automation to begin.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
