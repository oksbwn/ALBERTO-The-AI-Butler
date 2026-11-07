"use client";

import { useCallback, useEffect, useState } from "react";
import { Icon } from "@/components/icons";
import { Field, Modal, Tile, Toggle } from "@/components/primitives";
import {
  api,
  Channel,
  ChannelDiagnostics,
  ChannelIdentityOut,
  ChannelPairingOut,
} from "@/lib/api";
import { StatusBadge } from "./badges";

export function ChannelDetailView({
  project,
  channel,
  workflows,
  agents,
  onBack,
  onReload,
  onNav,
}: {
  project: any;
  channel: Channel;
  workflows: any[];
  agents: any[];
  onBack: () => void;
  onReload: () => void;
  onNav?: (screen: string) => void;
}) {
  const [tab, setTab] = useState<"overview" | "connection" | "pairing" | "routing" | "diagnostics">("overview");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const isTg = channel.type === "telegram";
  const [name, setName] = useState(channel.name || "");
  const [enabled, setEnabled] = useState(channel.enabled);
  const [tgToken, setTgToken] = useState((channel.config || {}).bot_token || "");
  const [tgTransport, setTgTransport] = useState<"polling" | "webhook">((channel.config || {}).transport || "webhook");

  // Email config
  const smtp = channel.config?.smtp || {};
  const [smtpHost, setSmtpHost] = useState(smtp.host || "");
  const [smtpPort, setSmtpPort] = useState(smtp.port ?? 587);
  const [smtpUser, setSmtpUser] = useState(smtp.username || "");
  const [smtpFrom, setSmtpFrom] = useState(smtp.from || "");
  const [smtpPassRef, setSmtpPassRef] = useState(smtp.password_ref || "");
  const [emailProvider, setEmailProvider] = useState((channel.config || {}).provider || "mailgun");

  // Pairing state
  const [activePairing, setActivePairing] = useState<ChannelPairingOut | null>(null);
  const [pairingTtlRemaining, setPairingTtlRemaining] = useState<number | null>(null);
  const [manualCode, setManualCode] = useState("");
  const [manualSender, setManualSender] = useState("");
  const [manualLabel, setManualLabel] = useState("");
  const [identities, setIdentities] = useState<ChannelIdentityOut[]>([]);
  const [loadingIdentities, setLoadingIdentities] = useState(false);

  // Routing state
  const [targetType, setTargetType] = useState<string>(channel.target_type || "master_agent");
  const [targetId, setTargetId] = useState<string>(channel.target_id || "");
  const [routes, setRoutes] = useState<any[]>(channel.routes || []);
  const [newCmd, setNewCmd] = useState("");
  const [newCmdTargetType, setNewCmdTargetType] = useState("workflow");
  const [newCmdTargetId, setNewCmdTargetId] = useState("");

  // Diagnostics state
  const [diagnostics, setDiagnostics] = useState<ChannelDiagnostics | null>(null);
  const [runningDiag, setRunningDiag] = useState(false);
  const [testRecipient, setTestRecipient] = useState("");
  const [testText, setTestText] = useState("Hello from Alberto channel diagnostics!");
  const [sendingTest, setSendingTest] = useState(false);
  const [testSendResult, setTestSendResult] = useState<any | null>(null);

  // Load identities
  const loadIdentities = useCallback(async () => {
    setLoadingIdentities(true);
    try {
      const list = await api.listChannelIdentities(project.id, channel.id);
      setIdentities(list);
    } catch {
      setIdentities([]);
    } finally {
      setLoadingIdentities(false);
    }
  }, [project.id, channel.id]);

  useEffect(() => {
    loadIdentities();
  }, [loadIdentities]);

  // Pairing TTL timer countdown
  useEffect(() => {
    if (!activePairing) return;
    const interval = setInterval(() => {
      const exp = new Date(activePairing.expires_at).getTime();
      const now = Date.now();
      const diff = Math.max(0, Math.round((exp - now) / 1000));
      setPairingTtlRemaining(diff);
      if (diff <= 0) {
        setActivePairing(null);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [activePairing]);

  const handleToggleEnabled = async () => {
    try {
      const next = !enabled;
      setEnabled(next);
      await api.updateChannel(project.id, channel.id, { enabled: next });
      onReload();
    } catch (e: any) {
      setEnabled(!enabled);
      setErr(e.message || "Failed to update channel status");
    }
  };

  const handleSaveConnection = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const cfg: Record<string, any> = { ...channel.config };
      if (isTg) {
        if (tgToken) cfg.bot_token = tgToken;
        cfg.transport = tgTransport;
      } else {
        cfg.provider = emailProvider;
        cfg.smtp = {
          host: smtpHost,
          port: Number(smtpPort),
          username: smtpUser,
          from: smtpFrom,
          password_ref: smtpPassRef,
        };
      }
      await api.updateChannel(project.id, channel.id, { name, config: cfg });
      setMsg("Connection configuration saved successfully.");
      onReload();
    } catch (e: any) {
      setErr(e.message || "Failed to save connection");
    } finally {
      setBusy(false);
    }
  };

  const handleGeneratePairing = async () => {
    setBusy(true);
    setErr(null);
    try {
      const p = await api.createChannelPairing(project.id, channel.id);
      setActivePairing(p);
      setPairingTtlRemaining(p.ttl_seconds);
      setManualCode(p.code);
    } catch (e: any) {
      setErr(e.message || "Failed to generate pairing challenge");
    } finally {
      setBusy(false);
    }
  };

  const handleConfirmPairing = async () => {
    if (!manualCode.trim()) {
      setErr("Please enter the 6-character pairing code received from your bot.");
      return;
    }
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      const code = manualCode.trim().toUpperCase();
      const res = await api.confirmChannelPairing(project.id, channel.id, code);
      setMsg(`Telegram account successfully paired and verified.`);
      setManualCode("");
      await loadIdentities();
      onReload();
    } catch (e: any) {
      setErr(e.message || "Pairing confirmation failed. Ensure the code is correct and not expired.");
    } finally {
      setBusy(false);
    }
  };

  const handleRevokeIdentity = async (iid: string) => {
    if (!confirm("Revoke this paired external identity?")) return;
    try {
      await api.revokeChannelIdentity(project.id, channel.id, iid);
      await loadIdentities();
    } catch (e: any) {
      setErr(e.message || "Failed to revoke identity");
    }
  };

  const handleSaveRouting = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await api.setChannelRouting(project.id, channel.id, {
        target_type: targetType,
        target_id: targetType === "master_agent" ? null : targetId || null,
        routes,
      });
      setMsg("Channel routing policy updated successfully.");
      onReload();
    } catch (e: any) {
      setErr(e.message || "Failed to update routing policy");
    } finally {
      setBusy(false);
    }
  };

  const handleAddRoute = () => {
    if (!newCmd.trim()) return;
    const formatted = newCmd.trim().startsWith("/") ? newCmd.trim() : `/${newCmd.trim()}`;
    setRoutes((r) => [
      ...r.filter((x) => x.command !== formatted),
      {
        command: formatted,
        target_type: newCmdTargetType,
        target_id: newCmdTargetType === "master_agent" ? null : newCmdTargetId || null,
      },
    ]);
    setNewCmd("");
  };

  const handleRemoveRoute = (cmd: string) => {
    setRoutes((r) => r.filter((x) => x.command !== cmd));
  };

  const handleRunDiagnostics = async () => {
    setRunningDiag(true);
    setErr(null);
    try {
      const rep = await api.diagnoseChannel(project.id, channel.id);
      setDiagnostics(rep);
    } catch (e: any) {
      setErr(e.message || "Diagnostic check failed");
    } finally {
      setRunningDiag(false);
    }
  };

  const handleSendTestMessage = async () => {
    if (!testRecipient.trim() || !testText.trim()) return;
    setSendingTest(true);
    setTestSendResult(null);
    try {
      const res = await api.sendChannelMessage(project.id, channel.id, {
        recipient: testRecipient.trim(),
        text: testText.trim(),
      });
      setTestSendResult(res);
    } catch (e: any) {
      setTestSendResult({ ok: false, error: e.message || "Failed to dispatch message" });
    } finally {
      setSendingTest(false);
    }
  };

  const handleDeleteChannel = async () => {
    if (!confirm("Are you sure you want to delete this channel?")) return;
    try {
      await api.deleteChannel(project.id, channel.id);
      onBack();
      onReload();
    } catch (e: any) {
      alert(e.message || "Failed to delete channel");
    }
  };

  const targetLabel =
    channel.target_type === "subagent"
      ? `Subagent: ${agents.find((a: any) => a.id === channel.target_id)?.name || channel.target_id || "Unset"}`
      : channel.target_type === "workflow"
      ? `Workflow: ${workflows.find((w: any) => w.id === channel.target_id)?.name || channel.target_id || "Unset"}`
      : "Master Agent (Conversational Butler)";

  return (
    <div className="col grow" style={{ minHeight: 0, background: "var(--bg-0)" }}>
      {/* Top Header */}
      <div
        className="row spread"
        style={{
          padding: "16px 24px",
          borderBottom: "1px solid var(--line-strong)",
          background: "var(--bg-1)",
        }}
      >
        <div className="row gap3" style={{ alignItems: "center" }}>
          <button className="btn btn-ghost btn-sm" onClick={onBack}>
            <Icon name="arrow-left" size={14} /> Integrations
          </button>
          <div className="divider-v" />
          <div className="row gap2" style={{ alignItems: "center" }}>
            <Tile icon={isTg ? "msg" : "mail"} color="var(--accent, #6366f1)" size={32} />
            <div className="col">
              <span className="t-h3" style={{ margin: 0 }}>{channel.name}</span>
              <span className="fg-2 t-caption mono-sm">
                {isTg ? "Telegram Bot Channel" : "Email Channel"} · ID: {channel.id}
              </span>
            </div>
            {enabled ? (
              <span className="badge" style={{ background: "rgba(16, 185, 129, 0.15)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.3)" }}>
                ● Active
              </span>
            ) : (
              <span className="badge" style={{ background: "rgba(148, 163, 184, 0.15)", color: "#94a3b8" }}>
                Disabled
              </span>
            )}
            {channel.routing_state === "needs_review" && (
              <span className="badge" style={{ background: "rgba(245, 158, 11, 0.15)", color: "#f59e0b", border: "1px solid rgba(245, 158, 11, 0.3)" }}>
                ⚠ Routing Needs Review
              </span>
            )}
          </div>
        </div>

        <div className="row gap2" style={{ alignItems: "center" }}>
          <Toggle on={enabled} onChange={handleToggleEnabled} />
          <button className="btn btn-ghost btn-sm" title="Delete Channel" onClick={handleDeleteChannel}>
            <Icon name="trash" size={14} />
          </button>
        </div>
      </div>

      {/* Segmented Navigation */}
      <div
        className="row spread"
        style={{
          padding: "0 24px",
          borderBottom: "1px solid var(--line)",
          background: "var(--bg-1)",
        }}
      >
        <div className="row gap1">
          {(["overview", "connection", "pairing", "routing", "diagnostics"] as const).map((t) => (
            <button
              key={t}
              className={`btn btn-sm ${tab === t ? "btn-secondary" : "btn-ghost"}`}
              style={{
                borderRadius: "8px 8px 0 0",
                textTransform: "capitalize",
                borderBottom: tab === t ? "2px solid var(--accent, #6366f1)" : "2px solid transparent",
              }}
              onClick={() => setTab(t)}
            >
              {t === "pairing" ? "Access & Pairing" : t}
            </button>
          ))}
        </div>
      </div>

      {/* Notifications */}
      {err && (
        <div className="row spread" style={{ padding: "10px 24px", background: "rgba(239, 68, 68, 0.15)", borderBottom: "1px solid #ef4444" }}>
          <span style={{ color: "#f87171", fontSize: 13 }}>{err}</span>
          <button className="iconbtn" onClick={() => setErr(null)}>✕</button>
        </div>
      )}
      {msg && (
        <div className="row spread" style={{ padding: "10px 24px", background: "rgba(34, 197, 94, 0.15)", borderBottom: "1px solid #22c55e" }}>
          <span style={{ color: "#4ade80", fontSize: 13 }}>{msg}</span>
          <button className="iconbtn" onClick={() => setMsg(null)}>✕</button>
        </div>
      )}

      {/* Tab Contents */}
      <div className="grow scroll-y" style={{ padding: 24, maxWidth: 860 }}>
        {/* 1. OVERVIEW */}
        {tab === "overview" && (
          <div className="col gap3">
            {(channel.routing_state === "needs_review" || channel.routing_state === "requires_review") && (
              <div
                className="col gap1"
                style={{
                  padding: "12px 16px",
                  borderRadius: 8,
                  background: "rgba(245, 158, 11, 0.12)",
                  border: "1px solid rgba(245, 158, 11, 0.4)",
                  color: "#f59e0b",
                }}
              >
                <div className="row gap2" style={{ alignItems: "center", fontWeight: 600 }}>
                  <Icon name="alert-triangle" size={16} />
                  <span>Legacy Channel Destination Review Required</span>
                </div>
                <div className="t-body-sm" style={{ color: "var(--fg-1)" }}>
                  This historical channel was migrated without an explicit destination workflow. Inbound message execution is paused until an administrator confirms the target destination in the Routing tab.
                </div>
                <div style={{ marginTop: 6 }}>
                  <button className="btn btn-secondary btn-xs" onClick={() => setTab("routing")}>
                    Review & Configure Routing →
                  </button>
                </div>
              </div>
            )}
            {isTg && identities.length === 0 && (
              <div
                className="col gap2"
                style={{
                  padding: "16px 20px",
                  borderRadius: "var(--radius)",
                  background: "rgba(99, 102, 241, 0.08)",
                  border: "1px solid rgba(99, 102, 241, 0.25)",
                }}
              >
                <div className="row gap2" style={{ alignItems: "center", fontWeight: 600 }}>
                  <Icon name="shield-check" size={16} style={{ color: "var(--signal)" }} />
                  <span>Next Step: Link Your Telegram Account</span>
                </div>
                <div className="t-body-sm fg-2">
                  External Telegram users must pair once before interacting with Alberto:
                  <ol style={{ margin: "8px 0 0 16px", padding: 0, lineHeight: 1.6 }}>
                    <li>Open Telegram and send <code>/start</code> to your bot{channel.config?.bot?.username ? ` (@${channel.config.bot.username})` : ""}.</li>
                    <li>The bot will reply with a 6-character pairing code.</li>
                    <li>Enter the code in the <strong>Access &amp; Pairing</strong> tab to link your account.</li>
                  </ol>
                </div>
                <div style={{ marginTop: 4 }}>
                  <button className="btn btn-primary btn-xs" onClick={() => setTab("pairing")}>
                    Go to Access &amp; Pairing →
                  </button>
                </div>
              </div>
            )}
            <div className="card col gap2" style={{ padding: 18, background: "var(--bg-1)" }}>
              <span className="t-h3">Channel Summary</span>
              <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 10, fontSize: 13 }}>
                <span className="fg-2">Default Destination:</span>
                <span style={{ fontWeight: 600 }}>{targetLabel}</span>
                <span className="fg-2">Effective Transport:</span>
                <span className="mono">{channel.state?.effective_transport || (isTg ? "webhook/polling" : "inbound webhook")}</span>
                <span className="fg-2">Routing State:</span>
                <span className="badge" style={{ width: "fit-content" }}>{channel.routing_state || "ok"}</span>
                {channel.inbound_url && (
                  <>
                    <span className="fg-2">Inbound Webhook URL:</span>
                    <div className="row gap1" style={{ alignItems: "center" }}>
                      <span className="mono-sm fg-1 truncate" style={{ maxWidth: 450 }}>{channel.inbound_url}</span>
                      <button className="btn btn-ghost btn-xs" onClick={() => navigator.clipboard.writeText(channel.inbound_url!)}>Copy</button>
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="row gap3 wrap">
              <div className="card col grow gap1" style={{ padding: 14, background: "var(--bg-1)" }}>
                <span className="fg-2 t-caption">Total Inbound Events</span>
                <span className="t-h2">{channel.state?.total_events || 0}</span>
              </div>
              <div className="card col grow gap1" style={{ padding: 14, background: "var(--bg-1)" }}>
                <span className="fg-2 t-caption">Paired Identities</span>
                <span className="t-h2">{channel.state?.paired_identities || identities.length}</span>
              </div>
              <div className="card col grow gap1" style={{ padding: 14, background: "var(--bg-1)" }}>
                <span className="fg-2 t-caption">Connection Status</span>
                <span className="t-h2" style={{ color: channel.state?.connected !== false ? "#4ade80" : "#f87171" }}>
                  {channel.state?.connected !== false ? "Connected" : "Disconnected"}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* 2. CONNECTION CONFIG */}
        {tab === "connection" && (
          <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
            <span className="t-h3">Connection & Secrets</span>
            <Field label="Channel Name">
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>

            {isTg ? (
              <>
                <Field label="Telegram Bot Token" help="Obtained from @BotFather. Securely resolved via project secrets.">
                  <input
                    type="password"
                    className="input mono"
                    placeholder="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
                    value={tgToken}
                    onChange={(e) => setTgToken(e.target.value)}
                  />
                </Field>
                <Field label="Transport Mode">
                  <select
                    className="select"
                    value={tgTransport}
                    onChange={(e) => setTgTransport(e.target.value as any)}
                  >
                    <option value="webhook">Webhook Mode (Recommended for production)</option>
                    <option value="polling">Long Polling Mode (Local dev behind NAT)</option>
                  </select>
                </Field>
                {channel.inbound_url && (
                  <Field label="Inbound Webhook URL (with Secret Token Header)">
                    <input className="input mono" readOnly value={channel.inbound_url} />
                  </Field>
                )}
              </>
            ) : (
              <>
                <Field label="Provider Verification Protocol">
                  <select
                    className="select"
                    value={emailProvider}
                    onChange={(e) => setEmailProvider(e.target.value)}
                  >
                    <option value="mailgun">Mailgun (HMAC-SHA256 signature)</option>
                    <option value="shared_secret">Shared Secret Token / Header</option>
                    <option value="basic_auth">HTTP Basic Authentication</option>
                  </select>
                </Field>
                <span className="t-h4" style={{ marginTop: 8 }}>Outbound SMTP Credentials (for Butler Replies)</span>
                <div className="row gap2">
                  <div style={{ flex: 2 }}>
                    <Field label="SMTP Host">
                      <input className="input mono" placeholder="smtp.mailgun.org" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} />
                    </Field>
                  </div>
                  <div style={{ flex: 1 }}>
                    <Field label="Port">
                      <input type="number" className="input mono" value={smtpPort} onChange={(e) => setSmtpPort(Number(e.target.value))} />
                    </Field>
                  </div>
                </div>
                <div className="row gap2">
                  <div style={{ flex: 1 }}>
                    <Field label="Username">
                      <input className="input mono" value={smtpUser} onChange={(e) => setSmtpUser(e.target.value)} />
                    </Field>
                  </div>
                  <div style={{ flex: 1 }}>
                    <Field label="From Address">
                      <input className="input mono" placeholder="butler@yourdomain.com" value={smtpFrom} onChange={(e) => setSmtpFrom(e.target.value)} />
                    </Field>
                  </div>
                </div>
                <Field label="Password Secret Reference" help="Pointer to encrypted secret store (e.g. secret://proj/smtp_pass).">
                  <input className="input mono" placeholder="secret://proj/smtp_password" value={smtpPassRef} onChange={(e) => setSmtpPassRef(e.target.value)} />
                </Field>
              </>
            )}

            <div className="row end" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={busy} onClick={handleSaveConnection}>
                {busy ? "Saving..." : "Save Connection Settings"}
              </button>
            </div>
          </div>
        )}

        {/* 3. ACCESS & PAIRING */}
        {tab === "pairing" && (
          <div className="col gap3">
            <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
              <div className="col gap1">
                <span className="t-h3">Account Pairing &amp; Security</span>
                <div className="t-caption fg-2">
                  External users must pair their Telegram handle or Email address with an Alberto account before interacting.
                </div>
              </div>

              {/* Step-by-Step Instructions */}
              <div
                className="col gap2"
                style={{
                  padding: "14px 18px",
                  borderRadius: 8,
                  background: "rgba(99, 102, 241, 0.06)",
                  border: "1px solid rgba(99, 102, 241, 0.2)",
                  fontSize: 13,
                  lineHeight: 1.5,
                }}
              >
                <span style={{ fontWeight: 600 }}>How to Pair in 3 Steps:</span>
                <div className="col gap1 fg-2">
                  <div>1. Open Telegram and search for your bot{channel.config?.bot?.username ? ` (@${channel.config.bot.username})` : ""}.</div>
                  <div>2. Send <code>/start</code> or any message. The bot will reply with a one-time 6-character code (valid for 15 minutes).</div>
                  <div>3. Enter the code below and click <strong>Verify &amp; Link Account</strong>.</div>
                </div>
              </div>

              {/* Code Entry Form */}
              <div className="row gap2" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 200, maxWidth: 300 }}>
                  <Field label="Pairing Code">
                    <input
                      className="input mono"
                      placeholder="e.g. ABC123"
                      maxLength={10}
                      value={manualCode}
                      onChange={(e) => setManualCode(e.target.value.toUpperCase())}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && manualCode.trim()) handleConfirmPairing();
                      }}
                    />
                  </Field>
                </div>
                <button
                  className="btn btn-primary"
                  disabled={busy || !manualCode.trim()}
                  onClick={handleConfirmPairing}
                >
                  <Icon name="shield-check" size={14} /> Verify &amp; Link Account
                </button>
              </div>
            </div>

            {/* Paired Identities Table */}
            <div className="card col gap2" style={{ padding: 18, background: "var(--bg-1)" }}>
              <span className="t-h3">Authorized Paired Identities ({identities.length})</span>
              {loadingIdentities ? (
                <div className="t-caption fg-2">Loading paired identities...</div>
              ) : identities.length === 0 ? (
                <div className="t-caption fg-2">No external senders paired yet. Follow the steps above to link your Telegram account.</div>
              ) : (
                <div className="col gap1">
                  {identities.map((id: any) => (
                    <div
                      key={id.id}
                      className="row spread"
                      style={{
                        padding: "10px 14px",
                        borderRadius: 6,
                        background: "var(--bg-2)",
                        alignItems: "center",
                      }}
                    >
                      <div className="row gap3" style={{ alignItems: "center" }}>
                        <span className="mono" style={{ fontWeight: 600 }}>{id.provider_user_id || id.external_user_id}</span>
                        {(id.label || id.display_label) && <span className="typechip">{id.label || id.display_label}</span>}
                        <span
                          className="badge"
                          style={{
                            background: id.status === "verified" ? "rgba(34, 197, 94, 0.15)" : "rgba(245, 158, 11, 0.15)",
                            color: id.status === "verified" ? "#22c55e" : "#f59e0b",
                            fontSize: 11,
                          }}
                        >
                          {id.status === "verified" ? "verified" : (id.status || "pending")}
                        </span>
                        <span className="t-caption fg-3">
                          {(id.verified_at || id.paired_at) ? `Paired ${new Date(id.verified_at || id.paired_at).toLocaleDateString()}` : ""}
                        </span>
                      </div>
                      <button className="btn btn-ghost btn-xs" onClick={() => handleRevokeIdentity(id.id)} title="Revoke pairing">
                        Revoke
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* 4. ROUTING */}
        {tab === "routing" && (
          <div className="col gap3">
            {(channel.routing_state === "needs_review" || channel.routing_state === "requires_review") && (
              <div
                className="col gap1"
                style={{
                  padding: "12px 16px",
                  borderRadius: 8,
                  background: "rgba(245, 158, 11, 0.12)",
                  border: "1px solid rgba(245, 158, 11, 0.4)",
                  color: "#f59e0b",
                }}
              >
                <div className="row gap2" style={{ alignItems: "center", fontWeight: 600 }}>
                  <Icon name="alert-triangle" size={16} />
                  <span>Routing Review Required</span>
                </div>
                <div className="t-body-sm" style={{ color: "var(--fg-1)" }}>
                  Select an explicit conversational target below (Master Agent, Subagent, or Workflow) and click <strong>"Save Routing Policy"</strong> to confirm destination and authorize inbound message execution.
                </div>
              </div>
            )}
            <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
              <span className="t-h3">Conversational Routing Destination</span>
              <div className="t-caption fg-2">
                Channels are decoupled from workflows. By default, incoming messages land in Master Agent.
              </div>

              <div className="col gap2">
                <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="targetType"
                    checked={targetType === "master_agent"}
                    onChange={() => {
                      setTargetType("master_agent");
                      setTargetId("");
                    }}
                  />
                  <div>
                    <span style={{ fontWeight: 600 }}>Master Agent (Recommended Default)</span>
                    <div className="t-caption fg-2">
                      Conversational AI Butler with persistent cross-session memory and autonomous tool delegation.
                    </div>
                  </div>
                </label>

                <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="targetType"
                    checked={targetType === "subagent"}
                    onChange={() => setTargetType("subagent")}
                  />
                  <div>
                    <span style={{ fontWeight: 600 }}>Specialized Subagent</span>
                    <div className="t-caption fg-2">Route directly to an expert subagent (e.g. Integration Manager or Curator).</div>
                  </div>
                </label>

                {targetType === "subagent" && (
                  <div style={{ marginLeft: 24 }}>
                    <Field label="Select Target Subagent">
                      <select className="select" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                        <option value="">Choose subagent...</option>
                        {agents.map((a) => (
                          <option key={a.id} value={a.id}>{a.name} ({a.role || a.id})</option>
                        ))}
                      </select>
                    </Field>
                  </div>
                )}

                <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="targetType"
                    checked={targetType === "workflow"}
                    onChange={() => setTargetType("workflow")}
                  />
                  <div>
                    <span style={{ fontWeight: 600 }}>Specific Workflow</span>
                    <div className="t-caption fg-2">Route messages into a deterministic LangGraph workflow execution.</div>
                  </div>
                </label>

                {targetType === "workflow" && (
                  <div style={{ marginLeft: 24 }}>
                    <Field label="Select Target Workflow">
                      <select className="select" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
                        <option value="">Choose workflow...</option>
                        {workflows.map((w) => (
                          <option key={w.id} value={w.id}>{w.name} ({w.status})</option>
                        ))}
                      </select>
                    </Field>
                  </div>
                )}
              </div>

              {/* Custom Command Rules */}
              <div className="col gap2" style={{ paddingTop: 14, borderTop: "1px solid var(--line)" }}>
                <span className="t-h4">Custom Command Rules (e.g. /status, /help)</span>
                <div className="row gap2">
                  <input
                    className="input mono"
                    placeholder="/status"
                    style={{ flex: 1 }}
                    value={newCmd}
                    onChange={(e) => setNewCmd(e.target.value)}
                  />
                  <select
                    className="select"
                    style={{ flex: 1 }}
                    value={newCmdTargetType}
                    onChange={(e) => setNewCmdTargetType(e.target.value)}
                  >
                    <option value="workflow">Workflow</option>
                    <option value="subagent">Subagent</option>
                    <option value="master_agent">Master Agent</option>
                  </select>
                  {newCmdTargetType !== "master_agent" && (
                    <select
                      className="select"
                      style={{ flex: 2 }}
                      value={newCmdTargetId}
                      onChange={(e) => setNewCmdTargetId(e.target.value)}
                    >
                      <option value="">Select target...</option>
                      {newCmdTargetType === "workflow"
                        ? workflows.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)
                        : agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </select>
                  )}
                  <button className="btn btn-secondary btn-sm" onClick={handleAddRoute}>Add Rule</button>
                </div>

                {routes.length > 0 && (
                  <div className="col gap1" style={{ marginTop: 8 }}>
                    {routes.map((r, i) => (
                      <div key={i} className="row spread" style={{ padding: "8px 12px", background: "var(--bg-2)", borderRadius: 6 }}>
                        <div className="row gap2 mono-sm" style={{ alignItems: "center" }}>
                          <strong>{r.command}</strong> → <span>{r.target_type}: {r.target_id || "default"}</span>
                        </div>
                        <button className="btn btn-ghost btn-xs" onClick={() => handleRemoveRoute(r.command)}>✕</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="row end" style={{ marginTop: 12 }}>
                <button className="btn btn-primary" disabled={busy} onClick={handleSaveRouting}>
                  {busy ? "Saving..." : "Save Routing Policy"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 5. DIAGNOSTICS */}
        {tab === "diagnostics" && (
          <div className="col gap3">
            <div className="card col gap3" style={{ padding: 20, background: "var(--bg-1)" }}>
              <div className="row spread">
                <div className="col gap1">
                  <span className="t-h3">Integration Manager Channel Diagnostics</span>
                  <div className="t-caption fg-2">
                    Evaluates transport connectivity, webhook secrets, pairing health, and delivery metrics.
                  </div>
                </div>
                <button className="btn btn-secondary btn-sm" disabled={runningDiag} onClick={handleRunDiagnostics}>
                  {runningDiag ? "Inspecting..." : "Run Channel Diagnostic"}
                </button>
              </div>

              {diagnostics && (
                <div className="col gap2" style={{ padding: 14, background: "var(--bg-2)", borderRadius: 8 }}>
                  <div className="row spread">
                    <span className="badge">Status: {diagnostics.status.toUpperCase()}</span>
                    <span className="mono-sm">Transport: {diagnostics.effective_transport}</span>
                  </div>
                  {diagnostics.issues.length > 0 ? (
                    <div>
                      <span className="fg-2 t-caption">Issues Identified:</span>
                      <ul style={{ margin: "4px 0", paddingLeft: 18, color: "#f87171", fontSize: 12 }}>
                        {diagnostics.issues.map((iss, i) => <li key={i}>{iss}</li>)}
                      </ul>
                    </div>
                  ) : (
                    <div style={{ color: "#4ade80", fontSize: 12 }}>✓ No critical connectivity issues detected.</div>
                  )}

                  {diagnostics.recommendations.length > 0 && (
                    <div>
                      <span className="fg-2 t-caption">Recommendations:</span>
                      <ul style={{ margin: "4px 0", paddingLeft: 18, fontSize: 12 }}>
                        {diagnostics.recommendations.map((rec, i) => <li key={i}>{rec}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* Test Outbound Send */}
              <div className="col gap2" style={{ paddingTop: 14, borderTop: "1px solid var(--line)" }}>
                <span className="t-h4">Outbound Send Test (Channel Delivery Service)</span>
                <Field label="Recipient (Telegram Chat ID or Email Address)">
                  <input
                    className="input mono"
                    placeholder={isTg ? "e.g. 123456789" : "recipient@example.com"}
                    value={testRecipient}
                    onChange={(e) => setTestRecipient(e.target.value)}
                  />
                </Field>
                <Field label="Test Message Body">
                  <textarea
                    className="textarea mono"
                    rows={2}
                    value={testText}
                    onChange={(e) => setTestText(e.target.value)}
                  />
                </Field>
                <div className="row end">
                  <button className="btn btn-primary btn-sm" disabled={sendingTest || !testRecipient.trim()} onClick={handleSendTestMessage}>
                    {sendingTest ? "Sending..." : "Send Test Message"}
                  </button>
                </div>

                {testSendResult && (
                  <div
                    style={{
                      padding: 10,
                      borderRadius: 6,
                      background: testSendResult.ok ? "rgba(34, 197, 94, 0.15)" : "rgba(239, 68, 68, 0.15)",
                      fontSize: 12,
                    }}
                  >
                    {testSendResult.ok ? (
                      <span style={{ color: "#4ade80" }}>
                        ✓ Message dispatched successfully. Delivery ID: {testSendResult.delivery_id}
                      </span>
                    ) : (
                      <span style={{ color: "#f87171" }}>
                        ✕ Failed to send: {testSendResult.error}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

