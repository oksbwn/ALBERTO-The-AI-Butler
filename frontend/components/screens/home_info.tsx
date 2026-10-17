"use client";
import { useEffect, useState } from "react";
import { Icon } from "../icons";
import { api, DashboardStats, ProjectCounts } from "@/lib/api";

/**
 * HomeInfoScreen - Compact landing page info & vitals dashboard.
 * Designed to fit standard viewport heights without vertical scrolling.
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
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchStats = async () => {
    if (!project?.id) return;
    setLoading(true);
    try {
      const [c, s] = await Promise.allSettled([
        api.projectCounts(project.id),
        api.dashboardStats(),
      ]);
      if (c.status === "fulfilled") setCounts(c.value);
      if (s.status === "fulfilled") setStats(s.value);
    } catch {
      // stats fallback
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
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
        scrollbarWidth: "none", // Hide scrollbar in Firefox
        msOverflowStyle: "none", // Hide scrollbar in IE/Edge
      }}
    >
      <div
        style={{
          maxWidth: 850,
          width: "100%",
          margin: "0 auto",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {/* 1. Header */}
        <div className="row spread" style={{ alignItems: "center" }}>
          <div>
            <h2 className="t-h2" style={{ margin: 0, fontSize: 18 }}>
              Home Overview
            </h2>
            <div className="fg-2 t-caption" style={{ marginTop: 2, fontSize: 12 }}>
              System vitals, active capabilities, and extensible modules.
            </div>
          </div>
          <button
            className="iconbtn"
            title="Refresh stats"
            onClick={fetchStats}
            disabled={loading}
            style={{ width: 28, height: 28 }}
          >
            <Icon name="activity" size={14} className={loading ? "spin" : ""} />
          </button>
        </div>

        {/* 2. Quick Metric Cards (Compact) */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 10,
          }}
        >
          <div
            className="card"
            style={{ padding: "10px 12px", cursor: onNav ? "pointer" : "default" }}
            onClick={() => onNav?.("workflows")}
          >
            <div className="row spread" style={{ alignItems: "center", marginBottom: 4 }}>
              <span className="t-caption fg-2" style={{ fontSize: 11.5 }}>Workflows</span>
              <Icon name="workflow" size={14} style={{ color: "var(--accent)" }} />
            </div>
            <div className="t-h1" style={{ fontSize: 20, fontWeight: 700 }}>
              {counts?.workflows ?? 0}
            </div>
            <div className="t-micro fg-2" style={{ fontSize: 10.5, marginTop: 1 }}>Automations</div>
          </div>

          <div
            className="card"
            style={{ padding: "10px 12px", cursor: onNav ? "pointer" : "default" }}
            onClick={() => onNav?.("agents")}
          >
            <div className="row spread" style={{ alignItems: "center", marginBottom: 4 }}>
              <span className="t-caption fg-2" style={{ fontSize: 11.5 }}>Agents</span>
              <Icon name="bot" size={14} style={{ color: "var(--io-control)" }} />
            </div>
            <div className="t-h1" style={{ fontSize: 20, fontWeight: 700 }}>
              {counts?.agents ?? 0}
            </div>
            <div className="t-micro fg-2" style={{ fontSize: 10.5, marginTop: 1 }}>ReAct loops</div>
          </div>

          <div
            className="card"
            style={{ padding: "10px 12px", cursor: onNav ? "pointer" : "default" }}
            onClick={() => onNav?.("tools")}
          >
            <div className="row spread" style={{ alignItems: "center", marginBottom: 4 }}>
              <span className="t-caption fg-2" style={{ fontSize: 11.5 }}>Capabilities</span>
              <Icon name="tools" size={14} style={{ color: "var(--signal)" }} />
            </div>
            <div className="t-h1" style={{ fontSize: 20, fontWeight: 700 }}>
              {(counts?.tools ?? 0) + (counts?.connectors ?? 0)}
            </div>
            <div className="t-micro fg-2" style={{ fontSize: 10.5, marginTop: 1 }}>Tools & Sets</div>
          </div>

          <div
            className="card"
            style={{ padding: "10px 12px", cursor: onNav ? "pointer" : "default" }}
            onClick={() => onNav?.("knowledge")}
          >
            <div className="row spread" style={{ alignItems: "center", marginBottom: 4 }}>
              <span className="t-caption fg-2" style={{ fontSize: 11.5 }}>Knowledge</span>
              <Icon name="book-open" size={14} style={{ color: "var(--io-vector)" }} />
            </div>
            <div className="t-h1" style={{ fontSize: 20, fontWeight: 700 }}>
              {counts?.knowledge ?? 0}
            </div>
            <div className="t-micro fg-2" style={{ fontSize: 10.5, marginTop: 1 }}>RAG & Q&A</div>
          </div>
        </div>

        {/* 3. System Architecture & Runtime (Inline Pill Grid) */}
        <div className="card" style={{ padding: "12px 14px" }}>
          <div className="row spread" style={{ alignItems: "center", marginBottom: 8 }}>
            <div className="row gap2" style={{ alignItems: "center" }}>
              <Icon name="server" size={14} style={{ color: "var(--accent)" }} />
              <span style={{ fontWeight: 600, fontSize: 13 }}>System Architecture</span>
            </div>
            <span className="t-micro fg-2">Runtime v1.0 · Local-First</span>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 8,
              fontSize: 12,
            }}
          >
            <div style={{ padding: "8px 10px", background: "var(--bg-2)", borderRadius: 6 }}>
              <div className="fg-2 t-micro" style={{ fontSize: 10 }}>Engine Runtime</div>
              <div style={{ fontWeight: 600, marginTop: 2, fontSize: 12 }}>FastAPI + LangGraph</div>
            </div>
            <div style={{ padding: "8px 10px", background: "var(--bg-2)", borderRadius: 6 }}>
              <div className="fg-2 t-micro" style={{ fontSize: 10 }}>Database</div>
              <div style={{ fontWeight: 600, marginTop: 2, fontSize: 12 }}>SQLite (Local)</div>
            </div>
            <div style={{ padding: "8px 10px", background: "var(--bg-2)", borderRadius: 6 }}>
              <div className="fg-2 t-micro" style={{ fontSize: 10 }}>Endpoint</div>
              <div style={{ fontWeight: 600, marginTop: 2, fontSize: 12 }}>127.0.0.1:8000</div>
            </div>
            <div style={{ padding: "8px 10px", background: "var(--bg-2)", borderRadius: 6 }}>
              <div className="fg-2 t-micro" style={{ fontSize: 10 }}>Privacy</div>
              <div style={{ fontWeight: 600, marginTop: 2, fontSize: 12, color: "var(--ok)" }}>100% On-Premise</div>
            </div>
          </div>
        </div>

        {/* 4. Execution Metrics Bar */}
        {stats && (
          <div className="card" style={{ padding: "12px 14px" }}>
            <div className="row spread" style={{ alignItems: "center", marginBottom: 8 }}>
              <div className="row gap2" style={{ alignItems: "center" }}>
                <Icon name="activity" size={14} style={{ color: "var(--signal)" }} />
                <span style={{ fontWeight: 600, fontSize: 13 }}>Execution Metrics</span>
              </div>
              {onNav && (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => onNav("overview")}
                  style={{ fontSize: 11.5, padding: "2px 6px", height: 24 }}
                >
                  Analytics <Icon name="chevright" size={12} />
                </button>
              )}
            </div>
            <div className="row spread" style={{ gap: 12 }}>
              <div>
                <div className="fg-2 t-micro" style={{ fontSize: 10.5 }}>Runs (7 days)</div>
                <div style={{ fontSize: 16, fontWeight: 700, marginTop: 1 }}>
                  {stats.runs_7d.toLocaleString()}
                </div>
              </div>
              <div>
                <div className="fg-2 t-micro" style={{ fontSize: 10.5 }}>Success Rate</div>
                <div style={{ fontSize: 16, fontWeight: 700, marginTop: 1, color: "var(--ok)" }}>
                  {stats.runs_7d ? `${stats.success_rate}%` : "100%"}
                </div>
              </div>
              <div>
                <div className="fg-2 t-micro" style={{ fontSize: 10.5 }}>Avg Latency</div>
                <div style={{ fontSize: 16, fontWeight: 700, marginTop: 1 }}>
                  {stats.avg_latency_ms ? `${stats.avg_latency_ms}ms` : "<100ms"}
                </div>
              </div>
              <div>
                <div className="fg-2 t-micro" style={{ fontSize: 10.5 }}>Total Executions</div>
                <div style={{ fontSize: 16, fontWeight: 700, marginTop: 1 }}>
                  {stats.total_runs ? stats.total_runs.toLocaleString() : stats.runs_7d.toLocaleString()}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 5. Extensible Content Section (Future Widget Slot) */}
        <div
          className="card"
          style={{
            padding: "12px 14px",
            border: "1px dashed var(--line-strong)",
            background: "var(--bg-1)",
          }}
        >
          <div className="row spread" style={{ alignItems: "center", marginBottom: 6 }}>
            <div className="row gap2" style={{ alignItems: "center" }}>
              <Icon name="widget" size={14} style={{ color: "var(--accent)" }} />
              <span style={{ fontWeight: 600, fontSize: 13 }}>Custom Widgets & Integrations</span>
            </div>
            <span className="badge" style={{ fontSize: 10, padding: "1px 6px" }}>
              Extensible Slot
            </span>
          </div>
          <div className="fg-2 t-caption" style={{ marginBottom: 8, fontSize: 11.5 }}>
            Ready for Home Assistant sensors, IoT controls, or custom widget cards.
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 8,
            }}
          >
            <div
              style={{
                padding: "8px 10px",
                borderRadius: 6,
                border: "1px dashed var(--line)",
                background: "var(--bg-2)",
                textAlign: "center",
                fontSize: 11.5,
                color: "var(--fg-2)",
              }}
            >
              <Icon name="plug" size={15} style={{ margin: "0 auto 4px", opacity: 0.6 }} />
              <div>IoT & Devices Slot</div>
            </div>

            <div
              style={{
                padding: "8px 10px",
                borderRadius: 6,
                border: "1px dashed var(--line)",
                background: "var(--bg-2)",
                textAlign: "center",
                fontSize: 11.5,
                color: "var(--fg-2)",
              }}
            >
              <Icon name="bell" size={15} style={{ margin: "0 auto 4px", opacity: 0.6 }} />
              <div>Schedules & Alerts Slot</div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
