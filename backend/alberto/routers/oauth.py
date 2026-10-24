"""3-legged OAuth (authorization_code) connect flow for auth providers.

Flow: the console calls `/oauth/start` to get the provider's authorize URL (carrying a
short-lived signed `state`); the user grants access and the provider redirects the
browser to `/v1/oauth/callback`, which validates `state`, exchanges the code for tokens,
and stores them as a secret. The AuthResolver then auto-refreshes on expiry.
"""

from __future__ import annotations

import json
from html import escape

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.auth_providers.oauth_flow import (
    OAuthNotConfigured,
    build_authorize_url,
    redirect_uri,
    token_request,
)
from alberto.auth_providers.resolver import AuthResolver
from alberto.deps import CurrentUser, current_tenant_id, get_session, require_role
from alberto.models import AuthProvider
from alberto.secrets.store import SecretNotFound, SecretStore
from alberto.security import TokenError, decode_token
from alberto.util.http import shared_async_client
from alberto.util.ssrf import guarded_request

router = APIRouter(tags=["oauth"])

_PREFIX = "/v1/projects/{project_id}/auth-providers/{ap_id}/oauth"


class OAuthStartIn(BaseModel):
    # Per-user connect (finding i): the end-user context whose token this connect establishes.
    # Only the dims named in the provider's `per_user_context_keys` are carried through the
    # (signed) state to the callback, which then stores the bundle under the SAME per-user
    # secret name that resolve/refresh read. Omit for a shared, single-account provider.
    context: dict | None = None


async def _load(session, tenant_id: str, project_id: str, ap_id: str) -> AuthProvider:
    ap = (
        await session.execute(
            select(AuthProvider).where(
                AuthProvider.tenant_id == tenant_id, AuthProvider.project_id == project_id, AuthProvider.id == ap_id
            )
        )
    ).scalar_one_or_none()
    if ap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "auth provider not found")
    if ap.kind != "oauth2_authorization_code":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "provider is not an oauth2_authorization_code provider")
    return ap


@router.post(_PREFIX + "/start")
async def oauth_start(
    project_id: str, ap_id: str,
    body: OAuthStartIn | None = None,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("editor")),
):
    ap = await _load(session, tenant_id, project_id, ap_id)
    # PKCE + signed state live in auth_providers.oauth_flow, shared with the Connectors screen
    # so both connect paths have identical security properties (finding i).
    try:
        url = await build_authorize_url(
            ap, tenant_id=tenant_id, project_id=project_id,
            context=(body.context if body else None) or {},
        )
    except OAuthNotConfigured as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"authorize_url": url}


def _oauth_html(
    title: str,
    message: str,
    status_code: int = 200,
    is_success: bool = True,
    ap_id: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    event_payload = json.dumps({
        "type": "alberto:oauth_complete",
        "status": "success" if is_success else "error",
        "ap_id": ap_id,
        "error": error,
    })
    close_script = "setTimeout(function() { window.close(); }, 1200);" if is_success else ""
    icon = "✅" if is_success else "❌"
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{escape(title)} - Alberto</title>
    <style>
        body {{
            background: #090a0f;
            color: #eceef4;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            box-sizing: border-box;
        }}
        .card {{
            background: #141724;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 28px 32px;
            max-width: 440px;
            width: 100%;
            text-align: center;
            box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
        }}
        .icon {{
            font-size: 36px;
            margin-bottom: 16px;
        }}
        h2 {{
            margin: 0 0 10px;
            font-size: 20px;
            font-weight: 600;
        }}
        p {{
            margin: 0 0 16px;
            font-size: 14px;
            color: #9ba1b6;
            line-height: 1.5;
        }}
        .note {{
            font-size: 12px;
            color: #686f87;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">{icon}</div>
        <h2>{escape(title)}</h2>
        <p>{escape(message)}</p>
        <div class="note">This window will close automatically. You can return to Alberto.</div>
    </div>
    <script>
        (function() {{
            var payload = {event_payload};
            try {{
                if (window.opener && !window.opener.closed) {{
                    var targetOrigin = window.location.origin;
                    try {{
                        if (window.opener.location && window.opener.location.origin) {{
                            targetOrigin = window.opener.location.origin;
                        }}
                    }} catch (err) {{}}
                    window.opener.postMessage(payload, targetOrigin);
                    {close_script}
                }}
            }} catch (e) {{}}
        }})();
    </script>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=status_code)


@router.get("/v1/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str | None = None, state: str | None = None, error: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    # Every interpolated value below is provider/redirect-controlled, so HTML-escape it to
    # avoid reflected XSS on the API origin's callback page (audit S9).
    if error:
        return _oauth_html("Authorization failed", error, status_code=400, is_success=False, error=error)
    if not code or not state:
        return _oauth_html(
            "Missing authorization parameters",
            "Missing code or state parameters from authorization response.",
            status_code=400,
            is_success=False,
            error="missing_code_or_state",
        )
    try:
        claims = decode_token(state, expected_type="oauth_state")
    except TokenError:
        return _oauth_html(
            "Invalid or expired state",
            "The authorization state has expired or is invalid.",
            status_code=400,
            is_success=False,
            error="invalid_state",
        )
    tenant_id, project_id, ap_id = claims["tid"], claims["pid"], claims["ap"]
    ap = await _load(session, tenant_id, project_id, ap_id)
    cfg = ap.config or {}

    secrets = SecretStore()
    client_id = await secrets.read_ref(tenant_id=tenant_id, project_id=project_id, ref=cfg["client_id_ref"]) if cfg.get("client_id_ref") else None
    client_secret = await secrets.read_ref(tenant_id=tenant_id, project_id=project_id, ref=cfg["client_secret_ref"]) if cfg.get("client_secret_ref") else None

    data = {
        "grant_type": "authorization_code",
        "code": code,
        # The SAME helper build_authorize_url used. OAuth requires the redirect_uri sent at
        # /authorize and at the exchange to match exactly, so the two legs must never be able to
        # compute it differently.
        "redirect_uri": redirect_uri(cfg),
        "client_id": str(client_id) if client_id else None,
        "client_secret": str(client_secret) if client_secret else None,
        # PKCE proof matching the code_challenge sent at /start (finding i).
        "code_verifier": claims.get("cv"),
    }
    # Fetch the token through the SSRF guard (validates the host pre-connect AND re-validates
    # any redirect hop, with httpx's cross-origin credential stripping) rather than a raw POST
    # that would follow a redirect to an internal host (audit S8).
    form, headers = token_request(cfg, data)
    r = await guarded_request(
        shared_async_client(), "POST", cfg["token_url"],
        data=form, headers=headers, timeout=30, follow_redirects=True,
    )
    if r.status_code >= 400:
        return _oauth_html(
            f"Token exchange failed ({r.status_code})",
            r.text[:300],
            status_code=400,
            is_success=False,
            ap_id=ap_id,
            error=f"exchange_failed_{r.status_code}",
        )
    body = r.json()
    import time as _t

    bundle = {
        "access_token": body.get("access_token"),
        "refresh_token": body.get("refresh_token"),
        "token_type": body.get("token_type", "Bearer"),
        "scope": body.get("scope", cfg.get("scope")),
        "expires_at": (_t.time() + int(body["expires_in"])) if body.get("expires_in") else None,
    }
    # Store under the SAME (possibly per-user) secret name resolve/refresh read. The end-user
    # context was carried through the signed state from /start; without it (shared account) this
    # is the default name. Previously the connect always wrote the default name, so a per-user
    # provider's token was stored where resolve never looked (finding i / item 5).
    bundle_name = AuthResolver.bundle_secret_name(ap_id, claims.get("ctx"), cfg.get("per_user_context_keys"))
    await AuthResolver()._store_bundle(tenant_id, project_id, ap_id, bundle, name=bundle_name)
    # The per-user dims this consent was for, carried through the signed state. Discovery below
    # has to ask the server AS THAT USER - it is the only credential that exists.
    note = await _finish_connector_connect(session, tenant_id, project_id, ap_id, claims.get("ctx"))
    return _oauth_html(
        "Connected successfully",
        f"You can close this window and return to Alberto.{note}",
        status_code=200,
        is_success=True,
        ap_id=ap_id,
    )


async def _finish_connector_connect(session, tenant_id: str, project_id: str, ap_id: str,
                                    context: dict | None = None) -> str:
    """If this provider belongs to an installed connector, mark it connected and (for an
    MCP-backed one) discover its tools now that credentials exist.

    An MCP connector cannot list its tools before consent - the server answers 401 - so install
    deliberately leaves the tool set empty and this is where it gets filled. `context` is the end
    user whose token was just stored; without it the discovery call would resolve a shared bundle
    that a per-user connector never writes and get a second 401, leaving the connector connected
    with zero actions. Failures here are reported in the page text but never fail the callback:
    the token IS stored, and a user can always re-sync from the Connectors screen.
    """
    from alberto.connectors.install import ConnectorInstaller
    from alberto.models import ConnectorInstall

    install = (await session.execute(
        select(ConnectorInstall).where(
            ConnectorInstall.tenant_id == tenant_id,
            ConnectorInstall.project_id == project_id,
            ConnectorInstall.auth_provider_id == ap_id,
        )
    )).scalar_one_or_none()
    if install is None:
        return ""
    install.status = "connected"
    install.status_detail = None
    await session.commit()
    if not install.mcp_client_id:
        return ""
    try:
        count = await ConnectorInstaller().sync_tools(session, install, context=context)
    except Exception as e:  # noqa: BLE001 - the connection succeeded; discovery is recoverable
        from alberto.tools.mcp import describe_mcp_error

        return (" (Connected, but listing actions failed: "
                f"{escape(describe_mcp_error(e)[:200])}. Use “Refresh actions”.)")
    return f" {count} action(s) are now available." if count else ""


@router.get(_PREFIX + "/status")
async def oauth_status(
    project_id: str, ap_id: str,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(current_tenant_id),
    _: CurrentUser = Depends(require_role("viewer")),
):
    await _load(session, tenant_id, project_id, ap_id)  # validates existence/kind
    try:
        bundle = await SecretStore().read_ref(
            tenant_id=tenant_id, project_id=project_id,
            ref=f"secret://proj/{AuthResolver.bundle_secret_name(ap_id)}",
        )
    except SecretNotFound:
        return {"connected": False}
    return {
        "connected": bool(isinstance(bundle, dict) and bundle.get("access_token")),
        "expires_at": bundle.get("expires_at") if isinstance(bundle, dict) else None,
        "scope": bundle.get("scope") if isinstance(bundle, dict) else None,
        "has_refresh": bool(isinstance(bundle, dict) and bundle.get("refresh_token")),
    }
