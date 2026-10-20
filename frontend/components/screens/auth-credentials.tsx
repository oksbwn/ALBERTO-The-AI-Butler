"use client";
/* Auth & Credentials Screen: Dedicated console for Authentication Providers
   and workspace-wide Shared OAuth 2.0 client configurations. */

import { useState } from "react";
import { Icon } from "../icons";
import { AuthProvidersScreen } from "./auth";

export function AuthCredentialsScreen({
  project,
  onNav,
}: {
  project: any;
  onNav?: (screen: string) => void;
}) {
  const [subTab, setSubTab] = useState<"auth" | "oauth">("auth");
  const [copiedCallback, setCopiedCallback] = useState(false);

  const callbackUri = typeof window !== "undefined"
    ? `${window.location.origin}/v1/auth/callback/oauth2`
    : "/v1/auth/callback/oauth2";

  const handleCopyCallback = () => {
    if (navigator?.clipboard) {
      navigator.clipboard.writeText(callbackUri);
      setCopiedCallback(true);
      setTimeout(() => setCopiedCallback(false), 2000);
    }
  };

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
        <div className="col" style={{ gap: 4 }}>
          <div className="row gap2" style={{ alignItems: "center" }}>
            <Icon name="key" size={20} style={{ color: "var(--signal)" }} />
            <h1 className="t-h2" style={{ margin: 0 }}>Auth & Credentials</h1>
          </div>
          <div className="t-body-sm fg-2">
            Manage authentication providers, token secrets, and shared OAuth 2.0 app credentials.
          </div>
        </div>

        <div className="row gap3" style={{ alignItems: "center" }}>
          <div className="row gap1" style={{ background: "var(--bg-2)", padding: 3, borderRadius: 8 }}>
            <button
              className={`btn btn-sm ${subTab === "auth" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setSubTab("auth")}
            >
              <Icon name="shield-check" size={13} /> Auth Providers
            </button>
            <button
              className={`btn btn-sm ${subTab === "oauth" ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setSubTab("oauth")}
            >
              <Icon name="key" size={13} /> Shared OAuth
            </button>
          </div>
        </div>
      </div>

      {/* Main Body */}
      {subTab === "auth" ? (
        <div className="grow col" style={{ minHeight: 0 }}>
          <AuthProvidersScreen project={project} />
        </div>
      ) : (
        <div className="grow scroll-y" style={{ padding: 24 }}>
          <div className="col gap4" style={{ maxWidth: 880, margin: "0 auto" }}>
            <div className="card col gap3" style={{ padding: 24, background: "var(--bg-1)", border: "1px solid var(--line)" }}>
              <div className="col gap1">
                <div className="t-h3" style={{ margin: 0 }}>Shared OAuth 2.0 Client Configuration</div>
                <div className="t-body-sm fg-2">
                  Alberto manages workspace-wide OAuth 2.0 client credentials for Google, Microsoft, GitHub, and custom IdPs.
                </div>
              </div>

              <div className="col gap2" style={{ padding: 16, background: "var(--bg-2)", borderRadius: 8 }}>
                <div className="row spread" style={{ alignItems: "center" }}>
                  <span className="mono-sm fg-2">Default Callback URI:</span>
                  <div className="row gap2" style={{ alignItems: "center" }}>
                    <span className="mono-sm" style={{ fontWeight: 600 }}>{callbackUri}</span>
                    <button
                      className="btn btn-ghost btn-xs"
                      onClick={handleCopyCallback}
                      title="Copy callback URI"
                    >
                      <Icon name="copy" size={12} /> {copiedCallback ? "Copied" : "Copy"}
                    </button>
                  </div>
                </div>
                <div className="row spread">
                  <span className="mono-sm fg-2">Credential Storage:</span>
                  <span className="badge" style={{ color: "var(--signal)" }}>Fernet AES-256 encrypted</span>
                </div>
                <div className="row spread">
                  <span className="mono-sm fg-2">Token Refresh Policy:</span>
                  <span className="mono-sm">Autonomous pre-expiry renewal via refresh_token</span>
                </div>
                <div className="row spread">
                  <span className="mono-sm fg-2">Supported Grant Types:</span>
                  <span className="mono-sm">Authorization Code (PKCE) · Client Credentials</span>
                </div>
              </div>

              <div className="col gap2" style={{ marginTop: 8 }}>
                <div className="t-body-sm" style={{ fontWeight: 600 }}>Supported Identity Providers</div>
                <div className="grid grid-3 gap2">
                  <div className="card col gap1" style={{ padding: 12, background: "var(--bg-2)", border: "1px solid var(--line)" }}>
                    <span style={{ fontWeight: 600 }}>Google Workspace</span>
                    <span className="t-caption fg-2">Drive, Gmail, Calendar, Vertex AI</span>
                  </div>
                  <div className="card col gap1" style={{ padding: 12, background: "var(--bg-2)", border: "1px solid var(--line)" }}>
                    <span style={{ fontWeight: 600 }}>Microsoft Entra ID</span>
                    <span className="t-caption fg-2">Graph API, Outlook, SharePoint, Teams</span>
                  </div>
                  <div className="card col gap1" style={{ padding: 12, background: "var(--bg-2)", border: "1px solid var(--line)" }}>
                    <span style={{ fontWeight: 600 }}>GitHub / GitLab</span>
                    <span className="t-caption fg-2">Repos, Pull Requests, Issues, Actions</span>
                  </div>
                </div>
              </div>

              <div className="row spread" style={{ marginTop: 12, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
                <div className="t-caption fg-3">
                  To register a new OAuth provider client, open the <strong>Auth Providers</strong> tab or configure credentials in Integrations.
                </div>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => setSubTab("auth")}
                >
                  <Icon name="plus" size={13} /> Add Auth Provider
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
