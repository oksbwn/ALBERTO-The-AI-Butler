"use client";

import { useEffect, useState } from "react";
import { Icon } from "../icons";
import { Drawer } from "../primitives";
import { api, ActivityEntry } from "@/lib/api";

export function knRelTime(iso?: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return String(iso);
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

const ACTION: Record<string, { label: string; cls: string; icon: string }> = {
  added: { label: "added", cls: "pill-ok", icon: "plus" },
  changed: { label: "changed", cls: "pill-warn", icon: "edit" },
  removed: { label: "removed", cls: "pill-err", icon: "trash" },
};

export function KnowledgeHistory({
  project,
  open,
  onClose,
}: {
  project: any;
  open: boolean;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<ActivityEntry[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !project?.id) return;
    api
      .knowledgeActivity(project.id)
      .then(setRows)
      .catch((e) => setErr(e?.message || "Failed to load activity."));
  }, [open, project?.id]);

  return (
    <Drawer open={open} onClose={onClose} title="Knowledge Activity" width={440}>
      <div className="col gap2" style={{ padding: "14px 18px" }}>
        {err && (
          <div className="card" style={{ padding: 10, color: "var(--err)" }}>
            {err}
          </div>
        )}
        {rows?.map((r) => {
          const a = ACTION[r.action || ""] || {
            label: r.action || "changed",
            cls: "pill-muted",
            icon: "minus",
          };
          return (
            <div key={r.id} className="card" style={{ padding: "10px 12px" }}>
              <div className="row gap2" style={{ alignItems: "center" }}>
                <span className={`pill ${a.cls}`} style={{ fontSize: 11 }}>
                  <Icon name={a.icon as any} size={11} /> {a.label}
                </span>
                <span className="typechip">
                  {r.entity_type === "qa_pair" ? "Q&A" : "Doc"}
                </span>
                <span
                  className="mono-sm fg-2"
                  style={{ marginLeft: "auto", fontSize: 11 }}
                >
                  {knRelTime(r.created_at)}
                </span>
              </div>
              <div
                style={{ marginTop: 6, fontWeight: 550, fontSize: 13 }}
                className="truncate"
                title={r.title}
              >
                {r.title}
              </div>
              {r.author_email && (
                <div className="fg-2 t-micro" style={{ marginTop: 2 }}>
                  by {r.author_email}
                </div>
              )}
            </div>
          );
        })}
        {rows && rows.length === 0 && (
          <div
            className="card"
            style={{ padding: 20, textAlign: "center", color: "var(--fg-2)" }}
          >
            No recent activity recorded.
          </div>
        )}
      </div>
    </Drawer>
  );
}
