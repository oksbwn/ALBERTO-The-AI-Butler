import React from "react";
import { UnifiedIntegrationItem } from "./types";

export function StatusBadge({ status }: { status: UnifiedIntegrationItem["status"] }) {
  if (status === "connected") {
    return (
      <span className="badge" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.3)" }}>
        ● Connected
      </span>
    );
  }
  if (status === "needs_auth") {
    return (
      <span className="badge" style={{ background: "rgba(245, 158, 11, 0.15)", color: "#f59e0b", border: "1px solid rgba(245, 158, 11, 0.3)" }}>
        ○ Needs Auth
      </span>
    );
  }
  return (
    <span className="badge" style={{ background: "rgba(239, 68, 68, 0.15)", color: "#ef4444", border: "1px solid rgba(239, 68, 68, 0.3)" }}>
      ✕ {status}
    </span>
  );
}

export function EffectBadge({ effect }: { effect: string }) {
  const colors: Record<string, { bg: string; fg: string }> = {
    read: { bg: "rgba(16, 185, 129, 0.15)", fg: "#10b981" },
    write: { bg: "rgba(59, 130, 246, 0.15)", fg: "#3b82f6" },
    delete: { bg: "rgba(239, 68, 68, 0.15)", fg: "#ef4444" },
    unknown: { bg: "rgba(156, 163, 175, 0.15)", fg: "#9ca3af" },
  };
  const c = colors[effect] || colors.unknown;
  return (
    <span className="typechip" style={{ background: c.bg, color: c.fg }}>
      {effect.toUpperCase()}
    </span>
  );
}

export function RiskBadge({ risk }: { risk: string }) {
  const colors: Record<string, string> = {
    low: "#10b981",
    medium: "#f59e0b",
    high: "#ef4444",
    critical: "#8b5cf6",
  };
  return (
    <span className="t-caption" style={{ color: colors[risk] || "#9ca3af", fontWeight: 600 }}>
      {risk.toUpperCase()}
    </span>
  );
}

