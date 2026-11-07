"use client";
/* Forge app shell: topbar, project sidebar, command palette, assistant. */
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./icons";
import { Avatar, Tile } from "./primitives";
import { PROJECT_NAV, NavLeaf, NavGroup } from "@/lib/data";
import { Markdown } from "./markdown";
import { api } from "@/lib/api";

/* ---------------- Theme hook ---------------- */
export function useTheme(): [string, (t: string) => void] {
  const [theme, setTheme] = useState("light");
  useEffect(() => {
    const cur = document.documentElement.getAttribute("data-theme") || "light";
    setTheme(cur);
  }, []);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
  return [theme, setTheme];
}

/* ---------------- Account menu (avatar + sign out) ---------------- */
function AccountMenu() {
  const [open, setOpen] = useState(false);
  const [me, setMe] = useState<{ email: string; role: string } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let live = true;
    import("@/lib/api")
      .then(({ api }) => api.me())
      .then((m: any) => { if (live) setMe({ email: m.email, role: m.role }); })
      .catch(() => {});
    return () => { live = false; };
  }, []);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("mousedown", h);
    return () => window.removeEventListener("mousedown", h);
  }, [open]);
  async function signOut() {
    const { clearTokens } = await import("@/lib/api");
    clearTokens();
    window.location.reload();
  }
  return (
    <div ref={ref} style={{ position: "relative", flex: "none" }}>
      <button onClick={() => setOpen((o) => !o)} title="Account" aria-label="Account"
        style={{ border: "none", background: "none", cursor: "pointer", padding: 0, borderRadius: "50%", display: "flex" }}>
        <Avatar name={me?.email || "You"} size={30} />
      </button>
      {open && (
        <div className="card fade-in" style={{ position: "absolute", top: "100%", right: 0, marginTop: 6, zIndex: 6000, minWidth: 210, padding: 6, boxShadow: "var(--sh-pop)" }}>
          <div style={{ padding: "6px 9px 8px" }}>
            <div className="t-body-sm truncate" style={{ fontWeight: 600 }}>{me?.email || "Signed in"}</div>
            {me?.role && <div className="t-caption fg-2" style={{ textTransform: "capitalize", marginTop: 1 }}>{me.role}</div>}
          </div>
          <div className="divider" style={{ margin: "2px 0 4px" }} />
          <button onClick={signOut}
            style={{ display: "flex", alignItems: "center", gap: 9, width: "100%", textAlign: "left", padding: "7px 9px", border: "none", background: "none", cursor: "pointer", borderRadius: 6, fontSize: 13, fontFamily: "var(--font-ui)", color: "var(--err)" }}>
            <Icon name="logout" size={15} />Sign out
          </button>
        </div>
      )}
    </div>
  );
}

/* ---------------- Learning indicator / toggle ---------------- */
export function LearningIndicatorToggle({ project }: { project: any }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchSettings = () => {
    if (!project?.id) return;
    import("@/lib/api")
      .then(({ api }) => api.getMemoryLearningSettings(project.id))
      .then((s) => setEnabled(Boolean(s.memory_learning_enabled)))
      .catch(() => {});
  };

  useEffect(() => {
    fetchSettings();
  }, [project?.id]);

  useEffect(() => {
    const handler = (e: any) => {
      if (e.detail && typeof e.detail.memory_learning_enabled === "boolean") {
        setEnabled(e.detail.memory_learning_enabled);
      } else {
        fetchSettings();
      }
    };
    window.addEventListener("alberto:learning-changed", handler);
    return () => window.removeEventListener("alberto:learning-changed", handler);
  }, [project?.id]);

  if (!project?.id) return null;

  const isEnabled = Boolean(enabled);

  const toggle = async () => {
    if (loading || !project?.id) return;
    setLoading(true);
    try {
      const { api } = await import("@/lib/api");
      const nextState = !isEnabled;
      const updated = await api.updateMemoryLearningSettings(project.id, {
        memory_learning_enabled: nextState,
      });
      setEnabled(Boolean(updated.memory_learning_enabled));
      window.dispatchEvent(new CustomEvent("alberto:learning-changed", { detail: updated }));
    } catch (err: any) {
      alert(`Failed to update learning settings: ${err?.message || err}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={toggle}
      disabled={loading}
      className="row gap2"
      title={`Autonomous Memory Learning: ${isEnabled ? "ON (click to turn OFF)" : "OFF (click to turn ON)"}`}
      aria-label={`Toggle autonomous memory learning, currently ${isEnabled ? "ON" : "OFF"}`}
      style={{
        height: 32,
        padding: "0 8px",
        borderRadius: 6,
        cursor: loading ? "wait" : "pointer",
        fontSize: 11.5,
        fontWeight: 700,
        fontFamily: "var(--font-ui)",
        border: isEnabled ? "1px solid rgba(34, 197, 94, 0.35)" : "1px solid rgba(239, 68, 68, 0.35)",
        background: isEnabled ? "rgba(34, 197, 94, 0.1)" : "rgba(239, 68, 68, 0.08)",
        color: isEnabled ? "var(--ok, #22c55e)" : "var(--err, #ef4444)",
        transition: "all 0.15s ease",
        alignItems: "center",
      }}
    >
      <Icon
        name="brain"
        size={15}
        style={{
          color: isEnabled ? "var(--ok, #22c55e)" : "var(--err, #ef4444)",
          filter: isEnabled ? "drop-shadow(0 0 3px rgba(34, 197, 94, 0.45))" : "none",
          flex: "none",
        }}
      />
      <span>{loading ? "…" : isEnabled ? "ON" : "OFF"}</span>
    </button>
  );
}

/* ---------------- HITL Review Indicator ---------------- */
export function HitlReviewIndicator({
  project,
  onNav,
}: {
  project?: { id: string; name: string } | null;
  onNav?: (screen: string) => void;
}) {
  const [pendingCount, setPendingCount] = useState<number>(0);

  useEffect(() => {
    if (!project?.id) return;
    let live = true;
    const fetchCounts = () => {
      api.projectCounts(project.id)
        .then((res: any) => {
          if (live && res && typeof res.pending_reviews === "number") {
            setPendingCount(res.pending_reviews);
          }
        })
        .catch(() => {});
    };
    fetchCounts();

    const onChange = () => fetchCounts();
    window.addEventListener("alberto:counts-changed", onChange);
    window.addEventListener("forge:counts-changed", onChange);
    const timer = setInterval(fetchCounts, 8000);

    return () => {
      live = false;
      window.removeEventListener("alberto:counts-changed", onChange);
      window.removeEventListener("forge:counts-changed", onChange);
      clearInterval(timer);
    };
  }, [project?.id]);

  if (!project) return null;

  const hasPending = pendingCount > 0;

  return (
    <button
      onClick={() => onNav?.("ontology-review-queue")}
      className="row gap2"
      title={
        hasPending
          ? `${pendingCount} item(s) awaiting Human-in-the-Loop review. Click to open review queue.`
          : "Human-in-the-Loop Review Queue (0 pending)"
      }
      aria-label="HITL Review Queue"
      style={{
        height: 32,
        padding: "0 10px",
        borderRadius: 6,
        cursor: "pointer",
        fontSize: 12,
        fontWeight: 600,
        fontFamily: "var(--font-ui)",
        border: hasPending
          ? "1px solid rgba(245, 158, 11, 0.5)"
          : "1px solid var(--line)",
        background: hasPending
          ? "rgba(245, 158, 11, 0.14)"
          : "var(--bg-2)",
        color: hasPending ? "var(--warn, #f59e0b)" : "var(--fg-2)",
        display: "flex",
        alignItems: "center",
        gap: 6,
        transition: "all 0.15s ease",
        boxShadow: hasPending ? "0 0 10px rgba(245, 158, 11, 0.25)" : "none",
      }}
    >
      <Icon
        name={hasPending ? "shield-alert" : "shield-check"}
        size={14}
        style={{
          color: hasPending ? "var(--warn, #f59e0b)" : "var(--fg-2)",
          flex: "none",
        }}
      />
      <span>HITL Review</span>
      <span
        style={{
          padding: "1px 6px",
          borderRadius: 10,
          fontSize: 10.5,
          fontWeight: 700,
          background: hasPending ? "var(--warn, #f59e0b)" : "var(--bg-3)",
          color: hasPending ? "#000" : "var(--fg-2)",
          minWidth: 18,
          textAlign: "center",
          lineHeight: "15px",
        }}
      >
        {pendingCount}
      </span>
    </button>
  );
}

/* ---------------- Topbar ---------------- */
export interface Crumb { label: string; onClick?: () => void }
export function Topbar({ crumbs, right, left, onCommand, project, onNav }: { crumbs: Crumb[]; right?: ReactNode; left?: ReactNode; onCommand: () => void; project?: any; onNav?: (screen: string) => void }) {
  const [theme, setTheme] = useTheme();

  return (
    <div className="topbar" data-testid="topbar" style={{ height: 52, flex: "none", borderBottom: "1px solid var(--line)", display: "flex", alignItems: "center", padding: "0 16px", gap: 12, background: "var(--bg-1)" }}>
      {left}
      <div className="row gap2" style={{ minWidth: 0 }}>
        {crumbs.map((c, i) => (
          <div key={i} className="row gap2" style={{ minWidth: 0 }}>
            {i > 0 && <Icon name="chevright" size={15} style={{ color: "var(--fg-2)", flex: "none" }} />}
            <button onClick={c.onClick} disabled={!c.onClick}
              style={{ background: "none", border: "none", cursor: c.onClick ? "pointer" : "default", padding: 0, fontFamily: i === crumbs.length - 1 ? "var(--font-display)" : "var(--font-ui)", fontSize: i === crumbs.length - 1 ? 16 : 13, fontWeight: 600, color: i === crumbs.length - 1 ? "var(--fg-0)" : "var(--fg-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {c.label}
            </button>
          </div>
        ))}
      </div>
      <div style={{ flex: 1 }} />
      {project && <HitlReviewIndicator project={project} onNav={onNav} />}
      {project && <LearningIndicatorToggle project={project} />}
      <button className="row gap2" onClick={onCommand}
        style={{ height: 32, padding: "0 10px", border: "1px solid var(--line-strong)", borderRadius: 6, background: "var(--bg-1)", cursor: "pointer", color: "var(--fg-2)", fontSize: 12.5 }}>
        <Icon name="search" size={15} />
        <span style={{ width: 110, textAlign: "left" }}>Search…</span>
        <span className="kbd">⌘K</span>
      </button>
      <button
        className="iconbtn"
        title={theme === "dark" ? "Switch to light mode" : "Switch to dark console"}
        aria-label="Toggle color theme"
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        style={{ width: 32, height: 32, borderRadius: 6 }}
      >
        <Icon name={theme === "dark" ? "sun" : "moon"} size={16} />
      </button>
      {right}
      <AccountMenu />
    </div>
  );
}

/* ---------------- Project sidebar ---------------- */
export function ProjectSidebar({
  project,
  active,
  onNav,
  onBack,
  onAssistant,
  collapsed = true,
  onToggleCollapse,
  refreshKey,
}: {
  project: any;
  active: string;
  onNav: (id: string) => void;
  onBack?: () => void;
  onAssistant?: () => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  refreshKey?: any;
}) {
  const [counts, setCounts] = useState<Record<string, number>>({});
  // api.ts fires this after any create/delete of a counted resource, so the badges
  // refresh immediately instead of waiting for a page reload.
  const [countsBump, setCountsBump] = useState(0);
  useEffect(() => {
    const onChange = () => setCountsBump((n) => n + 1);
    window.addEventListener("alberto:counts-changed", onChange);
    window.addEventListener("forge:counts-changed", onChange);
    return () => {
      window.removeEventListener("alberto:counts-changed", onChange);
      window.removeEventListener("forge:counts-changed", onChange);
    };
  }, []);
  useEffect(() => {
    const pid = project?.id;
    if (!pid) return;
    let live = true;
    const refresh = async () => {
      // One cheap counts call (COUNT(*) per resource) instead of fetching six full lists
      // just to read their `.length`. Re-runs on create/delete via countsBump so badges
      // stay in sync. A short poll also keeps the agent-inbox badge current when a workflow
      // opens a handoff while the operator is on another screen.
      const { api } = await import("@/lib/api");
      try {
        const c = await api.projectCounts(pid);
        if (live) setCounts(c as unknown as Record<string, number>);
      } catch {
        if (live) setCounts({});
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 15_000);
    return () => { live = false; window.clearInterval(timer); };
  }, [project?.id, refreshKey, countsBump]);

  const [hoveredGroup, setHoveredGroup] = useState<string | null>(null);
  const [flyoutPos, setFlyoutPos] = useState<{ top: number } | null>(null);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({
    automate: true,
    knowledge_group: true,
    integrations: true,
    observability: true,
  });
  const hoverTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Auto-expand group containing current active screen
  useEffect(() => {
    PROJECT_NAV.forEach((entry) => {
      if ("items" in entry && entry.items.some((it) => it.id === active)) {
        setOpenGroups((prev) => ({ ...prev, [entry.id]: true }));
      }
    });
  }, [active]);

  const activeFlyoutGroup = useMemo(() => {
    return PROJECT_NAV.find((e): e is NavGroup => "items" in e && e.id === hoveredGroup);
  }, [hoveredGroup]);

  const renderLeaf = (n: NavLeaf, isChild = false) => {
    const on = active === n.id;
    const count = n.countKey ? counts[n.countKey] : undefined;
    const handleClick = () => {
      if (n.id === "assistant" && onAssistant) onAssistant();
      else onNav(n.id);
    };
    if (collapsed) {
      return (
        <div key={n.id} style={{ display: "flex", justifyContent: "center", marginBottom: 3 }}>
          <button
            onClick={handleClick}
            title={n.help ? `${n.label} — ${n.help}` : n.label}
            className={"iconbtn" + (on ? " active" : "")}
            style={{
              width: 38,
              height: 38,
              padding: 0,
              borderRadius: 8,
              border: "none",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: on ? "var(--accent)" : "var(--fg-1)",
              background: on ? "var(--bg-3)" : "transparent",
              position: "relative",
              boxShadow: on ? "inset 0 0 0 1px var(--line)" : "none",
            }}
          >
            <Icon name={n.icon} size={18} />
            {count != null && count > 0 && (
              <span
                style={{
                  position: "absolute",
                  top: 5,
                  right: 5,
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: "var(--accent)",
                }}
              />
            )}
          </button>
        </div>
      );
    }
    return (
      <button
        key={n.id}
        onClick={handleClick}
        title={n.help || n.label}
        className={"sidenav-item" + (on ? " active" : "")}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          width: "100%",
          height: 32,
          padding: isChild ? "0 10px 0 28px" : "0 10px",
          marginBottom: 1,
          borderRadius: 7,
          border: "none",
          cursor: "pointer",
          textAlign: "left",
          color: on ? "var(--accent)" : "var(--fg-1)",
          fontSize: isChild ? 12.5 : 13,
          fontWeight: on ? 600 : 500,
          fontFamily: "var(--font-ui)",
          transition: "color var(--dur-fast)",
        }}
      >
        <Icon name={n.icon} size={isChild ? 14 : 16} style={{ flex: "none", opacity: isChild && !on ? 0.75 : 1 }} />
        <span className="grow truncate">{n.label}</span>
        {count != null && count > 0 && (
          <span className="badge" style={on ? { background: "var(--accent-glow)", color: "var(--accent)" } : {}}>
            {count}
          </span>
        )}
      </button>
    );
  };

  // Settings is pinned to the bottom (rendered in the footer below), so drop it from the scroll list.
  const settingsLeaf = PROJECT_NAV.find((e): e is NavLeaf => "id" in e && e.id === "settings");

  return (
    <div style={{ width: collapsed ? 58 : 224, transition: "width 0.18s cubic-bezier(0.4, 0, 0.2, 1)", flex: "none", background: "var(--bg-1)", borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column", minHeight: 0, position: "relative" }}>
      <div className="row spread" style={{ height: 52, flex: "none", padding: collapsed ? 0 : "0 14px", borderBottom: "1px solid var(--line)", alignItems: "center", justifyContent: collapsed ? "center" : "space-between" }}>
        <div className="row gap2" onClick={() => onNav("home")} style={{ minWidth: 0, alignItems: "center", cursor: "pointer" }}>
          <Icon name="flame" size={20} style={{ color: "var(--accent)" }} />
          {!collapsed && <div className="t-h2 truncate" style={{ minWidth: 0, letterSpacing: "-0.01em" }}>Alberto</div>}
        </div>
        {!collapsed && onToggleCollapse && (
          <button className="iconbtn" title="Collapse sidebar" onClick={onToggleCollapse} style={{ width: 28, height: 28 }}>
            <Icon name="chevleft" size={15} />
          </button>
        )}
      </div>
      <nav className="scroll-y" style={{ flex: 1, minHeight: 0, padding: collapsed ? "6px 0" : 8 }}>
        {PROJECT_NAV.map((entry) => {
          if ("id" in entry && entry.id === "settings") return null; // pinned to the footer
          
          // NavGroup: Automate, Integrations, Observability
          if ("items" in entry) {
            const isGroupActive = entry.items.some((it) => it.id === active);
            const totalGroupCount = entry.items.reduce((acc, it) => acc + (it.countKey ? (counts[it.countKey] || 0) : 0), 0);

            if (collapsed) {
              return (
                <div key={entry.id} style={{ display: "flex", justifyContent: "center", marginBottom: 3 }}>
                  <button
                    onMouseEnter={(e) => {
                      if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
                      const rect = e.currentTarget.getBoundingClientRect();
                      setFlyoutPos({ top: Math.max(10, Math.min(window.innerHeight - 340, rect.top)) });
                      setHoveredGroup(entry.id);
                    }}
                    onMouseLeave={() => {
                      hoverTimerRef.current = setTimeout(() => setHoveredGroup(null), 180);
                    }}
                    onClick={(e) => {
                      if (entry.items.length > 0) {
                        onNav(entry.items[0].id);
                        setHoveredGroup(null);
                      } else {
                        const rect = e.currentTarget.getBoundingClientRect();
                        setFlyoutPos({ top: Math.max(10, Math.min(window.innerHeight - 340, rect.top)) });
                        setHoveredGroup((prev) => (prev === entry.id ? null : entry.id));
                      }
                    }}
                    title={`${entry.section} (Click to open, hover for items)`}
                    className={"iconbtn" + (isGroupActive ? " active" : "")}
                    style={{
                      width: 38,
                      height: 38,
                      padding: 0,
                      borderRadius: 8,
                      border: "none",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: isGroupActive ? "var(--accent)" : "var(--fg-1)",
                      background: isGroupActive ? "var(--bg-3)" : "transparent",
                      position: "relative",
                      boxShadow: isGroupActive ? "inset 0 0 0 1px var(--line)" : "none",
                    }}
                  >
                    <Icon name={entry.icon} size={18} />
                    {totalGroupCount > 0 && (
                      <span
                        style={{
                          position: "absolute",
                          top: 5,
                          right: 5,
                          width: 6,
                          height: 6,
                          borderRadius: "50%",
                          background: "var(--accent)",
                        }}
                      />
                    )}
                  </button>
                </div>
              );
            }

            // Expanded accordion
            const isOpen = openGroups[entry.id] ?? false;
            return (
              <div key={entry.id} style={{ marginBottom: 4 }}>
                <button
                  onClick={() => {
                    const nextOpen = !isOpen;
                    setOpenGroups((prev) => ({ ...prev, [entry.id]: nextOpen }));
                    if (nextOpen && entry.items.length > 0) {
                      onNav(entry.items[0].id);
                    }
                  }}
                  className="row spread"
                  style={{
                    width: "100%",
                    height: 32,
                    padding: "0 10px",
                    border: "none",
                    borderRadius: 7,
                    cursor: "pointer",
                    background: isGroupActive ? "var(--bg-2)" : "transparent",
                    color: isGroupActive ? "var(--accent)" : "var(--fg-1)",
                    fontSize: 12.5,
                    fontWeight: 600,
                    fontFamily: "var(--font-ui)",
                    alignItems: "center",
                    marginBottom: 2,
                    transition: "all 0.12s ease",
                  }}
                >
                  <div className="row gap2" style={{ alignItems: "center" }}>
                    <Icon name={entry.icon} size={15} style={{ color: isGroupActive ? "var(--accent)" : "var(--fg-2)" }} />
                    <span>{entry.section}</span>
                  </div>
                  <Icon name={isOpen ? "chevdown" : "chevright"} size={12} style={{ opacity: 0.6 }} />
                </button>
                {isOpen && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                    {entry.items.map((leaf) => renderLeaf(leaf, true))}
                  </div>
                )}
              </div>
            );
          }

          return renderLeaf(entry);
        })}
      </nav>

      {/* Floating Fan-out Submenu for Collapsed Mode */}
      {collapsed && hoveredGroup && activeFlyoutGroup && (
        <div
          className="card fade-in"
          onMouseEnter={() => {
            if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
          }}
          onMouseLeave={() => {
            hoverTimerRef.current = setTimeout(() => setHoveredGroup(null), 180);
          }}
          style={{
            position: "fixed",
            left: 62,
            top: flyoutPos?.top ?? 60,
            width: 220,
            zIndex: 9999,
            padding: "6px",
            background: "var(--bg-1)",
            border: "1px solid var(--line)",
            borderRadius: 10,
            boxShadow: "0 8px 30px rgba(0,0,0,0.22)",
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          <div className="row spread" style={{ padding: "4px 8px 6px", borderBottom: "1px solid var(--line)", marginBottom: 4 }}>
            <div className="row gap2" style={{ alignItems: "center" }}>
              <Icon name={activeFlyoutGroup.icon} size={14} style={{ color: "var(--accent)" }} />
              <span style={{ fontSize: 11.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--fg-0)" }}>
                {activeFlyoutGroup.section}
              </span>
            </div>
            <span className="fg-2 t-micro">{activeFlyoutGroup.items.length}</span>
          </div>

          <div className="col" style={{ gap: 1, maxHeight: 380, overflowY: "auto" }}>
            {activeFlyoutGroup.items.map((leaf) => {
              const on = active === leaf.id;
              const count = leaf.countKey ? counts[leaf.countKey] : undefined;
              return (
                <button
                  key={leaf.id}
                  onClick={() => {
                    onNav(leaf.id);
                    setHoveredGroup(null);
                  }}
                  title={leaf.help || leaf.label}
                  className={"sidenav-item" + (on ? " active" : "")}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    width: "100%",
                    height: 32,
                    padding: "0 8px",
                    borderRadius: 6,
                    border: "none",
                    cursor: "pointer",
                    textAlign: "left",
                    color: on ? "var(--accent)" : "var(--fg-1)",
                    fontSize: 12.5,
                    fontWeight: on ? 600 : 500,
                    fontFamily: "var(--font-ui)",
                    background: on ? "var(--bg-3)" : "transparent",
                    transition: "all 0.12s ease",
                  }}
                >
                  <Icon name={leaf.icon} size={15} style={{ flex: "none" }} />
                  <span className="grow truncate">{leaf.label}</span>
                  {count != null && count > 0 && (
                    <span className="badge" style={on ? { background: "var(--accent-glow)", color: "var(--accent)" } : {}}>
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {/* Settings pinned to the bottom */}
      <div style={{ flex: "none", position: "relative", zIndex: 2, padding: collapsed ? "6px 0" : 8, borderTop: "1px solid var(--line)", background: "var(--bg-1)", boxShadow: "0 -6px 12px -8px rgba(0,0,0,.18)", display: "flex", flexDirection: "column", gap: 2 }}>
        {settingsLeaf && renderLeaf(settingsLeaf)}
        {onToggleCollapse && (
          <div style={{ display: "flex", justifyContent: "center", padding: collapsed ? "2px 0 0" : "2px 0" }}>
            <button
              className="iconbtn"
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={onToggleCollapse}
              style={{ width: collapsed ? 38 : "100%", height: 32, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: collapsed ? "center" : "flex-start", gap: 10, padding: collapsed ? 0 : "0 10px" }}
            >
              <Icon name={collapsed ? "chevright" : "chevleft"} size={16} />
              {!collapsed && <span className="fg-2 t-caption" style={{ fontSize: 12 }}>Collapse</span>}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------------- Command palette ---------------- */
export function CommandPalette({ open, onClose, onGo, projects }: { open: boolean; onClose: () => void; onGo: (v: any) => void; projects: { id: string; name: string }[] }) {
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (open) { setQ(""); setTimeout(() => inputRef.current?.focus(), 30); }
  }, [open]);
  const cmds = useMemo(() => {
    const first = projects[0]?.id || "default";
    const list = [
      { sec: "Navigation", label: "Home (Chat & Stats)", icon: "home", go: { name: "project", project: first, screen: "home" } },
      { sec: "Navigation", label: "Analytics Overview", icon: "layout-dashboard", go: { name: "project", project: first, screen: "overview" } },
      { sec: "Navigation", label: "Workflows", icon: "workflows", go: { name: "project", project: first, screen: "workflows" } },
      { sec: "Navigation", label: "Agents", icon: "agents", go: { name: "project", project: first, screen: "agents" } },
      { sec: "Navigation", label: "Playground", icon: "playground", go: { name: "project", project: first, screen: "playground" } },
      { sec: "Navigation", label: "Tools", icon: "tools", go: { name: "project", project: first, screen: "tools" } },
      { sec: "Navigation", label: "Knowledge Base", icon: "knowledge", go: { name: "project", project: first, screen: "knowledge" } },
      { sec: "Navigation", label: "Connectors", icon: "plug", go: { name: "project", project: first, screen: "connectors" } },
      { sec: "Navigation", label: "Traces & Monitoring", icon: "traces", go: { name: "project", project: first, screen: "traces" } },
      { sec: "Navigation", label: "Settings & Secrets", icon: "settings", go: { name: "project", project: first, screen: "settings" } },
    ];
    if (!q) return list;
    return list.filter((c) => c.label.toLowerCase().includes(q.toLowerCase()));
  }, [q, projects]);
  const groups = useMemo(() => { const g: Record<string, any[]> = {}; cmds.forEach((c) => (g[c.sec] = g[c.sec] || []).push(c)); return g; }, [cmds]);
  if (!open) return null;
  return (
    <div className="fade-in" style={{ position: "fixed", inset: 0, zIndex: 8500, background: "rgba(8,10,14,.45)", backdropFilter: "blur(3px)", display: "flex", justifyContent: "center", paddingTop: "12vh" }} onMouseDown={onClose}>
      <div className="card fade-up" style={{ width: 600, maxWidth: "92vw", height: "fit-content", maxHeight: "70vh", boxShadow: "var(--sh-pop)", display: "flex", flexDirection: "column", overflow: "hidden" }} onMouseDown={(e) => e.stopPropagation()}>
        <div className="row gap2" style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)" }}>
          <Icon name="search" size={18} style={{ color: "var(--fg-2)" }} />
          <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search workflows, tools, actions, settings…"
            style={{ flex: 1, border: "none", outline: "none", background: "none", fontSize: 15, color: "var(--fg-0)", fontFamily: "var(--font-ui)" }} />
          <span className="kbd">esc</span>
        </div>
        <div className="scroll-y" style={{ padding: 8 }}>
          {Object.entries(groups).map(([sec, items]) => (
            <div key={sec} style={{ marginBottom: 6 }}>
              <div className="t-micro" style={{ padding: "6px 8px 4px" }}>{sec}</div>
              {items.map((c, i) => (
                <button key={i} onClick={() => { onGo(c.go); onClose(); }} className="row gap3"
                  style={{ width: "100%", padding: "8px", border: "none", background: "none", cursor: "pointer", borderRadius: 7, textAlign: "left", color: "var(--fg-1)" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-3)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "none")}>
                  <Icon name={c.icon} size={16} style={{ color: "var(--fg-2)" }} />
                  <span style={{ fontSize: 13.5, color: "var(--fg-0)" }}>{c.label}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
