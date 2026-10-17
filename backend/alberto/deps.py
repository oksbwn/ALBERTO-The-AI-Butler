"""FastAPI dependencies: session, auth/tenant resolution, RBAC.

Auth rollout is gated by `settings.auth_required`:
- True  → every request must carry a valid `Authorization: Bearer <access-token>`;
          the user is loaded from the DB and must be `active`.
- False → requests with no token fall back to the seeded workspace owner so the
          console keeps working during the migration (dev default).

`current_tenant_id` is derived from the resolved user, so every existing route that
already depends on it becomes tenant-scoped automatically.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.config import settings
from alberto.db import SessionLocal
from alberto.security import TokenError, decode_token, tokens_revoked_after
from alberto.services.auth import AuthService, role_at_least
from alberto.services.runs import RunService
from alberto.util.clientip import resolve_client_ip


@dataclass
class CurrentUser:
    id: str
    tenant_id: str
    role: str
    email: str | None = None
    is_fallback: bool = False


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


async def get_current_user(request: Request) -> CurrentUser:
    token = _bearer(request)
    if token:
        # Static service token (trusted server-to-server integrations): a fixed shared secret
        # that authenticates as a least-privilege service identity in the seeded workspace.
        # Checked before JWT decode (it isn't a JWT); constant-time compare to avoid leaking it.
        svc = settings.service_api_token
        if svc and hmac.compare_digest(token, svc):
            tenant_id = getattr(request.app.state, "tenant_id", None)
            if not tenant_id:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "service token: workspace not initialized")
            return CurrentUser(id="service", tenant_id=tenant_id, role="editor", email="service@alberto.local")
        # Per-tenant, role-scoped, revocable API keys (finding h). Recognizable by prefix and
        # not a JWT, so resolve before the JWT decode. Identity is `apikey:<id>` in a specific
        # tenant with the key's assigned role.
        from alberto.services.apikeys import ApiKeyService, looks_like_api_key

        if looks_like_api_key(token):
            async with SessionLocal() as s:
                key = await ApiKeyService.resolve(s, token)
            if key is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or revoked API key")
            return CurrentUser(id=f"apikey:{key.id}", tenant_id=key.tenant_id, role=key.role,
                               email=f"apikey:{key.name}")
        try:
            claims = decode_token(token, expected_type="access")
        except TokenError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}") from e
        # Logout-all / password-change cutoff: reject an access token minted before the user's
        # current revocation horizon even though it's otherwise still valid (finding d).
        if tokens_revoked_after(claims):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session has been signed out")
        async with SessionLocal() as s:
            user = await AuthService.get_user(s, claims.get("sub", ""))
        if user is None or user.status != "active":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account not found or disabled")
        return CurrentUser(id=user.id, tenant_id=user.tenant_id, role=user.role, email=user.email)

    if settings.auth_required:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")

    # In production or security-enforced deployments, anonymous requests are strictly rejected.
    if settings.enforce_security:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required outside development")

    tenant_id = getattr(request.app.state, "tenant_id", None)
    if not tenant_id:
        from alberto.models import Tenant
        from sqlalchemy import select

        async with SessionLocal() as s:
            tenant_id = (await s.execute(select(Tenant.id).limit(1))).scalar_one_or_none()
            if tenant_id:
                request.app.state.tenant_id = tenant_id

    tenant_id = tenant_id or "default"

    # Explicit development shortcut only (must be explicitly enabled in config):
    if settings.dev_allow_anonymous_owner:
        return CurrentUser(id="system-dev", tenant_id=tenant_id, role="owner", email="you@forge.local", is_fallback=True)

    # Safe default for unauthenticated local development: unprivileged viewer role.
    return CurrentUser(id="anonymous", tenant_id=tenant_id, role="viewer", email="anonymous@alberto.local", is_fallback=True)


def current_tenant_id(user: CurrentUser = Depends(get_current_user)) -> str:
    # Bind the tenant for this request so the Postgres RLS GUC listener (forge.db.base) sets
    # app.current_tenant on every transaction that follows in the route body. No-op on SQLite.
    from alberto.db.scoping import set_current_tenant

    set_current_tenant(user.tenant_id)
    return user.tenant_id


async def effective_role(user: CurrentUser, request: Request | None = None) -> str:
    """The caller's household role (owner > admin > editor > viewer)."""
    return user.role


def require_role(minimum: str):
    """Dependency factory: require the caller's household role to be at least `minimum`
    (owner > admin > editor > viewer). Use on mutating/administrative routes."""

    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not role_at_least(user.role, minimum):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role '{minimum}' or higher")
        return user

    return _dep


def client_ip(request: Request) -> str | None:
    """Client IP for per-IP rate limits / audit. Believes X-Forwarded-For only when the socket
    peer is a configured reverse proxy (settings.trusted_proxies); see forge.util.clientip.
    Shared with the audit middleware so the two resolvers can't drift."""
    peer = request.client.host if request.client else None
    return resolve_client_ip(peer, request.headers.get("x-forwarded-for"), settings.trusted_proxies)


# Header carrying ephemeral, per-run request context (a JSON object) that a server-side caller
# passes on a run's EXECUTION request (stream/resume). Its values are exposed to tools as
# {{ctx.<key>}} for on-behalf-of injection (e.g. a per-user session cookie / CSRF token) and
# are NEVER persisted or placed in the LLM prompt. Keep it small - it is a credential/context
# channel, not a data channel.
ALBERTO_CONTEXT_HEADER = "x-alberto-context"
FORGE_CONTEXT_HEADER = "x-forge-context"
_MAX_RUN_CONTEXT_BYTES = 8192


def run_context(request: Request) -> dict | None:
    """Parse the `X-Alberto-Context` (or legacy `X-Forge-Context`) header into a per-run context dict, or None if absent.

    Rejects non-JSON / non-object / oversized payloads. `end_user` is stripped: run identity
    is asserted via the run body / session token, not this header, so it can't be spoofed here.
    """
    raw = request.headers.get(ALBERTO_CONTEXT_HEADER) or request.headers.get(FORGE_CONTEXT_HEADER)
    if not raw:
        return None
    hdr_name = ALBERTO_CONTEXT_HEADER if ALBERTO_CONTEXT_HEADER in request.headers else FORGE_CONTEXT_HEADER
    if len(raw) > _MAX_RUN_CONTEXT_BYTES:
        raise HTTPException(413, f"{hdr_name} header too large")
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{hdr_name} must be a valid JSON object") from e
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{hdr_name} must be a JSON object")
    data.pop("end_user", None)  # identity is not settable via this channel
    return data or None


def get_run_service(request: Request) -> RunService:
    return RunService(
        checkpointer=getattr(request.app.state, "checkpointer", None),
        store=getattr(request.app.state, "store", None),
    )


def get_checkpointer(request: Request):
    return getattr(request.app.state, "checkpointer", None)
