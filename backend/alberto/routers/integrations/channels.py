"""Channel CRUD, routing, pairing, diagnostics + the public inbound endpoints (email, Telegram).

Channels are workflow-independent communication connections. Inbound traffic goes through the
ChannelGatewayService (identity pairing -> deterministic routing -> Master Agent / subagent /
workflow). Pre-v3 workflow-bound email channels keep their synchronous workflow + handoff flow.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.channels import email as email_ch
from alberto.channels import telegram as tg
from alberto.config import settings
from alberto.db.base import SessionLocal
from alberto.deps import CurrentUser, current_tenant_id, get_run_service, get_session, require_role
from alberto.models import Channel, ChannelEvent, ChannelIdentity, ChannelPairing, Workflow
from alberto.secrets.store import SecretStore
from alberto.services.channel_gateway import (
    ChannelDeliveryService,
    ChannelGatewayService,
    ChannelIdentityService,
    NormalizedMessage,
    RoutingError,
    _set_state,
    ingest_telegram_update,
)
from alberto.services.channels import ChannelService, RoutingConfigError
from alberto.services.handoff import (
    HITL_META_KEY,
    HandoffService,
    interrupt_ack,
    interrupt_hitl_meta,
    interrupt_reason,
)
from alberto.services.runs import RunService
from alberto.util.ratelimit import rate_limiter

log = logging.getLogger("forge.channels.router")

router = APIRouter(prefix="/v1/projects/{project_id}/channels", tags=["channels"])
public = APIRouter(tags=["channels"])  # unauthenticated inbound webhooks

MAX_INBOUND_BYTES = 2 * 1024 * 1024  # request-size ceiling for public webhooks


class ChannelIn(BaseModel):
    type: str
    name: str
    workflow_id: str | None = None  # legacy: bare workflow_id == explicit workflow destination
    target_type: str | None = None  # master_agent (default) | subagent | workflow
    target_id: str | None = None
    routes: list[dict] = Field(default_factory=list)
    config: dict = {}


class ChannelPatch(BaseModel):
    name: str | None = None
    workflow_id: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    target_type: str | None = None
    target_id: str | None = None
    routes: list[dict] | None = None


class PairConfirmIn(BaseModel):
    code: str
    user_id: str | None = None  # admin-only: bind to another user in this tenant


class SendIn(BaseModel):
    identity_id: str
    text: str
    subject: str | None = None


_SECRET_KEYS = ("token", "password", "secret", "api_key")


def _redact_config(cfg: dict) -> dict:
    """Never return raw credentials. `*_ref` values are secret-store pointers (names only)."""
    out: dict = {}
    for k, v in (cfg or {}).items():
        if isinstance(v, dict):
            out[k] = _redact_config(v)
        elif any(s in k.lower() for s in _SECRET_KEYS) and not k.lower().endswith("_ref"):
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


def _out(ch: Channel) -> dict:
    base = settings.public_base_url.rstrip("/")
    st = ch.state or {}
    item = {
        "id": ch.id, "type": ch.type, "name": ch.name, "workflow_id": ch.workflow_id,
        "enabled": ch.enabled, "config": _redact_config(ch.config), "key": ch.key,
        "target_type": ch.target_type, "target_id": ch.target_id,
        "routing_state": ch.routing_state, "routes": ch.routes or [],
        "needs_review": ch.routing_state == "needs_review",
        "connection": {"connected": st.get("connected"), "last_error": st.get("last_error"),
                       "last_poll_at": st.get("last_poll_at")},
    }
    if ch.type == "email":
        item["inbound_url"] = f"{base}/v1/channels/email/{ch.key}/inbound"
        item["verified_transport"] = bool((ch.config or {}).get("verification", {}).get("provider"))
    if ch.type == "telegram":
        item["transport"] = tg.effective_transport(ch)
        item["bot"] = (ch.config or {}).get("bot")
    return item


# ----------------------------------------------------------------- telegram ---

async def _store_telegram_token(session: AsyncSession, ch: Channel, token: str) -> str:
    name = f"channel-telegram-{ch.key[:16]}"
    await SecretStore().write(session, tenant_id=ch.tenant_id, project_id=ch.project_id,
                              name=name, value=token, kind="channel")
    return f"secret://{name}"


async def _store_telegram_webhook_secret(session: AsyncSession, ch: Channel, secret: str) -> str:
    name = f"channel-telegram-webhook-{ch.key[:16]}"
    await SecretStore().write(session, tenant_id=ch.tenant_id, project_id=ch.project_id,
                              name=name, value=secret, kind="channel")
    return f"secret://{name}"


async def _telegram_connect(ch: Channel) -> None:
    """Sync Telegram's transport with the configured one; record outcome in channel.state."""
    token = await tg.resolve_token(ch)
    patch: dict = {}
    if not token:
        patch = {"connected": False, "last_error": "bot token missing"}
    else:
        try:
            patch = {"connected": True, "last_error": None, "transport_active": await tg.apply_transport(ch, token)}
        except tg.TelegramError as e:
            patch = {"connected": False, "last_error": str(e)[:200]}
    async with SessionLocal() as s:
        row = await s.get(Channel, ch.id)
        row.state = {**(row.state or {}), **patch}
        await s.commit()
        await s.refresh(row)
        ch.state = row.state


# ----------------------------------------------------------------- CRUD ---

@router.get("")
async def list_channels(project_id: str, session: AsyncSession = Depends(get_session),
                        tenant_id: str = Depends(current_tenant_id)):
    return [_out(c) for c in await ChannelService.list(session, tenant_id, project_id)]


@router.post("", status_code=201)
async def create_channel(project_id: str, body: ChannelIn, session: AsyncSession = Depends(get_session),
                         tenant_id: str = Depends(current_tenant_id),
                         _: CurrentUser = Depends(require_role("editor"))):
    config = dict(body.config or {})
    token = None
    bot = None
    if body.type == "telegram":
        token = (config.pop("bot_token", None) or "").strip()
        if not token:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "telegram channels need a bot_token")
        try:
            bot = await tg.get_me(token)  # validates the credential + bot identity
        except tg.TelegramError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"bot token rejected: {tg.redact(str(e), token)}") from None
        config["bot"] = {"id": bot.get("id"), "username": bot.get("username")}
        config.setdefault("transport", "auto")
        if config["transport"] not in ("auto", "webhook", "polling"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "transport must be auto, webhook or polling")
    try:
        ch = await ChannelService.create(
            session, tenant_id, project_id, type_=body.type, name=body.name, workflow_id=body.workflow_id,
            config=config, target_type=body.target_type, target_id=body.target_id, routes=body.routes,
        )
    except (ValueError, RoutingConfigError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    if token:
        import secrets as _secrets
        wh_secret = _secrets.token_urlsafe(32)
        wh_ref = await _store_telegram_webhook_secret(session, ch, wh_secret)
        ch.config = {**ch.config, "bot_token_ref": await _store_telegram_token(session, ch, token), "webhook_secret_ref": wh_ref}
        await session.commit()
        await session.refresh(ch)
        await _telegram_connect(ch)
    return _out(ch)


@router.patch("/{channel_id}")
async def update_channel(project_id: str, channel_id: str, body: ChannelPatch,
                         session: AsyncSession = Depends(get_session),
                         tenant_id: str = Depends(current_tenant_id),
                         _: CurrentUser = Depends(require_role("editor"))):
    ch = await ChannelService.get(session, tenant_id, channel_id)
    if not ch or ch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    config = body.config
    reconnect = False
    if ch.type == "telegram" and config is not None:
        config = dict(config)
        new_token = (config.pop("bot_token", None) or "").strip()
        if new_token:
            try:
                bot = await tg.get_me(new_token)
            except tg.TelegramError as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"bot token rejected: {tg.redact(str(e), new_token)}") from None
            config["bot"] = {"id": bot.get("id"), "username": bot.get("username")}
            config["bot_token_ref"] = await _store_telegram_token(session, ch, new_token)
        if "transport" in config and config["transport"] not in ("auto", "webhook", "polling"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "transport must be auto, webhook or polling")
        config = {**(ch.config or {}), **config}  # merge: never drop the secret ref
        reconnect = True
    try:
        ch = await ChannelService.update(session, ch, name=body.name, workflow_id=body.workflow_id,
                                         config=config, enabled=body.enabled)
        if body.target_type is not None or body.routes is not None:
            ch = await ChannelService.set_routing(session, ch, target_type=body.target_type,
                                                  target_id=body.target_id, routes=body.routes)
    except RoutingConfigError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    if ch.type == "telegram":
        if body.enabled is False:
            await tg.disconnect(ch)
            await _set_state(ch.id, connected=False)
        elif body.enabled is True or reconnect:
            await _telegram_connect(ch)
    return _out(ch)


@router.delete("/{channel_id}")
async def delete_channel(project_id: str, channel_id: str, session: AsyncSession = Depends(get_session),
                         tenant_id: str = Depends(current_tenant_id),
                         _: CurrentUser = Depends(require_role("editor"))):
    ch = await ChannelService.get(session, tenant_id, channel_id)
    if not ch or ch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    if ch.type == "telegram":
        await tg.disconnect(ch)
        ref = (ch.config or {}).get("bot_token_ref", "")
        # Only the secret this channel created itself is removed (never a shared credential).
        if ref.startswith("secret://channel-telegram-"):
            from alberto.models import Secret
            sec = (await session.execute(select(Secret).where(
                Secret.tenant_id == tenant_id, Secret.project_id == ch.project_id,
                Secret.name == ref.removeprefix("secret://")))).scalar_one_or_none()
            if sec is not None:
                await session.delete(sec)
    for model in (ChannelIdentity, ChannelPairing, ChannelEvent):
        for row in (await session.execute(select(model).where(model.channel_id == ch.id))).scalars():
            await session.delete(row)
    await ChannelService.delete(session, ch)
    return {"ok": True}


# --------------------------------------------------- identity / pairing / ops ---

@router.get("/{channel_id}/identities")
async def list_identities(project_id: str, channel_id: str, session: AsyncSession = Depends(get_session),
                          tenant_id: str = Depends(current_tenant_id),
                          _: CurrentUser = Depends(require_role("editor"))):
    ch = await ChannelService.get(session, tenant_id, channel_id)
    if not ch or ch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    rows = (await session.execute(select(ChannelIdentity).where(
        ChannelIdentity.channel_id == ch.id, ChannelIdentity.tenant_id == tenant_id,
    ).order_by(ChannelIdentity.created_at.desc()))).scalars().all()
    return [{"id": r.id, "provider_user_id": r.provider_user_id, "label": r.display_label, "user_id": r.user_id,
             "status": r.status, "verified_at": r.verified_at, "revoked_at": r.revoked_at} for r in rows]


@router.post("/{channel_id}/pairings/confirm")
async def confirm_pairing(project_id: str, channel_id: str, body: PairConfirmIn,
                          session: AsyncSession = Depends(get_session),
                          tenant_id: str = Depends(current_tenant_id),
                          user: CurrentUser = Depends(require_role("viewer"))):
    """The authenticated Alberto user proves they own the external account by entering the
    one-time code that account received. Binds to the caller (admins may bind another user)."""
    ch = await ChannelService.get(session, tenant_id, channel_id)
    if not ch or ch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    try:
        ident = await ChannelIdentityService.confirm(
            session, tenant_id=tenant_id, project_id=project_id, channel_id=ch.id, code=body.code,
            acting_user_id=user.id, acting_role=user.role, bind_user_id=body.user_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"id": ident.id, "status": ident.status, "user_id": ident.user_id, "label": ident.display_label}


@router.delete("/{channel_id}/identities/{identity_id}")
async def revoke_identity(project_id: str, channel_id: str, identity_id: str,
                          session: AsyncSession = Depends(get_session),
                          tenant_id: str = Depends(current_tenant_id),
                          _: CurrentUser = Depends(require_role("editor"))):
    ch = await ChannelService.get(session, tenant_id, channel_id)
    if not ch or ch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    if not await ChannelIdentityService.revoke(session, tenant_id, ch.id, identity_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "identity not found")
    return {"ok": True}


@router.get("/{channel_id}/events")
async def list_events(project_id: str, channel_id: str, limit: int = 50,
                      session: AsyncSession = Depends(get_session),
                      tenant_id: str = Depends(current_tenant_id),
                      _: CurrentUser = Depends(require_role("editor"))):
    ch = await ChannelService.get(session, tenant_id, channel_id)
    if not ch or ch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    rows = (await session.execute(select(ChannelEvent).where(
        ChannelEvent.channel_id == ch.id, ChannelEvent.tenant_id == tenant_id,
    ).order_by(ChannelEvent.created_at.desc()).limit(min(max(limit, 1), 200)))).scalars().all()
    return [{"id": r.id, "status": r.status, "route": r.route, "detail": r.detail, "run_id": r.run_id,
             "correlation_id": r.correlation_id, "created_at": r.created_at} for r in rows]


@router.post("/{channel_id}/test")
async def test_channel(project_id: str, channel_id: str, session: AsyncSession = Depends(get_session),
                       tenant_id: str = Depends(current_tenant_id),
                       _: CurrentUser = Depends(require_role("editor"))):
    """Connection test (no message is sent to anyone)."""
    ch = await ChannelService.get(session, tenant_id, channel_id)
    if not ch or ch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    if ch.type == "telegram":
        token = await tg.resolve_token(ch)
        if not token:
            return {"ok": False, "error": "bot token missing from the secret store"}
        try:
            bot = await tg.get_me(token)
            info = await tg.get_webhook_info(token)
        except tg.TelegramError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "bot": {"id": bot.get("id"), "username": bot.get("username")},
                "transport": tg.effective_transport(ch), "webhook_registered": bool(info.get("url"))}
    smtp = (ch.config or {}).get("smtp") or {}
    return {"ok": True, "smtp_configured": bool(smtp.get("host")),
            "verified_transport": bool((ch.config or {}).get("verification", {}).get("provider"))}


@router.get("/{channel_id}/diagnostics")
async def channel_diagnostics(project_id: str, channel_id: str, session: AsyncSession = Depends(get_session),
                              tenant_id: str = Depends(current_tenant_id),
                              _: CurrentUser = Depends(require_role("editor"))):
    ch = await ChannelService.get(session, tenant_id, channel_id)
    if not ch or ch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    from alberto.services.tool_manager import ToolManagerService
    return await ToolManagerService.diagnose_channel(session, ch)


@router.post("/{channel_id}/send")
async def send_via_channel(project_id: str, channel_id: str, body: SendIn,
                           tenant_id: str = Depends(current_tenant_id),
                           user: CurrentUser = Depends(require_role("editor"))):
    """Authorised outbound message to a VERIFIED paired identity. Not an open relay: the
    recipient is an identity id, the actor's authority is derived from the authenticated user."""
    try:
        return await ChannelDeliveryService.send(
            tenant_id=tenant_id, project_id=project_id, channel_id=channel_id,
            actor={"user_id": user.id, "role": user.role, "kind": "user"},
            identity_id=body.identity_id, text=body.text, subject=body.subject)
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


# --------------------------------------------------------------- public inbound ---

async def _resolve(type_: str, key: str) -> Channel:
    async with SessionLocal() as s:
        ch = await ChannelService.by_key(s, type_, key)
    if ch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown or disabled channel")
    return ch


async def _maybe_open_handoff(ch, result: dict, *, customer, customer_message, reply_context) -> str | None:
    """If the run paused at an interrupt, open a HandoffRequest and return a customer-facing
    acknowledgement. Email can't resume an HITL pause inline, so ANY
    interrupt - explicit handoff OR an approval/input pause - must be tracked and acknowledged
    rather than falling through to a stale/empty partial answer (audit F8)."""
    if not result.get("interrupted"):
        return None
    interrupts = result.get("interrupts")
    reason = interrupt_reason(interrupts) or (
        "Conversation paused awaiting input/approval - a team member will follow up."
    )
    # Persist the interrupting node's allowed_decisions so the human's channel reply is coerced
    # to a valid decision before resuming (a Router keyed on approve/reject then matches) - C.
    hitl_meta = interrupt_hitl_meta(interrupts)
    ctx = dict(reply_context or {})
    if hitl_meta.get("allowed_decisions"):
        ctx[HITL_META_KEY] = {
            "allowed_decisions": hitl_meta["allowed_decisions"], "kind": hitl_meta.get("kind"),
            "timeout_default": hitl_meta.get("timeout_default"),
        }
    async with SessionLocal() as s:
        await HandoffService.create(
            s, channel=ch, tenant_id=ch.tenant_id, project_id=ch.project_id,
            workflow_id=result.get("workflow_id"), run_id=result.get("run_id"),
            thread_id=result.get("thread_id"), customer=customer, customer_message=customer_message,
            reason=reason, reply_context=ctx,
        )
    return interrupt_ack(interrupts) or "A team member will follow up with you shortly."


async def _read_body_limited(request: Request) -> bytes:
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_INBOUND_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "payload too large")
    raw = await request.body()
    if len(raw) > MAX_INBOUND_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "payload too large")
    return raw


@public.post("/v1/channels/email/{key}/inbound")
async def email_inbound(key: str, request: Request, run_service: RunService = Depends(get_run_service)):
    ch = await _resolve("email", key)
    if not rate_limiter.allow(f"email:{key}", rate=120, per=60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")
    await _read_body_limited(request)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - provider posts form-encoded
        form = await request.form()
        payload = dict(form)
    # Authenticity: provider-specific verification (the secret URL is an additional control only).
    cfg = ch.config or {}
    verification = cfg.get("verification") or {}
    secret = None
    if verification.get("secret_ref"):
        try:
            secret = str(await SecretStore().read_ref(tenant_id=ch.tenant_id, project_id=ch.project_id,
                                                      ref=verification["secret_ref"]))
        except Exception:  # noqa: BLE001
            secret = None
    verified, method, err = email_ch.verify_inbound(secret, verification, request.headers, payload)
    if verification.get("provider") and not verified:
        log.warning("email webhook verification failed on channel %s (%s)", ch.id, method)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "webhook verification failed")
    parsed = email_ch.parse_inbound(payload)
    text = email_ch.build_input_text(parsed, include_subject=cfg.get("include_subject", True))
    sender = (parsed.get("from_addr") or "").strip().lower()
    conv_key = parsed.get("thread_ref") or sender or None
    event_basis = parsed.get("message_id") or hashlib.sha256(f"{sender}|{parsed.get('subject')}|{text}".encode()).hexdigest()
    try:
        target_type, target_id, label, route_text = ChannelGatewayService.resolve_route(ch, parsed.get("text") or text)
    except RoutingError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"channel routing needs attention: {e}") from e

    msg = NormalizedMessage(
        channel_id=ch.id, provider="email", external_sender_id=sender, external_conversation_id=conv_key or sender,
        provider_message_id=str(event_basis)[:200], text=text, tenant_id=ch.tenant_id, project_id=ch.project_id,
        verified=verified, display_label=parsed.get("from_name") or None, reply_context=parsed,
    )
    if target_type != "workflow":
        res = await ChannelGatewayService.accept(ch, msg, run_service=run_service)
        return {"ok": True, "accepted": res.status in ("accepted", "duplicate"), "duplicate": res.duplicate,
                "verified": verified}

    # --- explicit workflow destination (pre-v3 behaviour preserved) ---
    event_id = await ChannelGatewayService._record_event(ch, msg)
    if event_id is None:
        return {"ok": True, "duplicate": True}
    async with SessionLocal() as s:
        wf = (await s.execute(select(Workflow).where(
            Workflow.id == target_id, Workflow.tenant_id == ch.tenant_id, Workflow.project_id == ch.project_id,
        ))).scalar_one_or_none()
    if wf is None or wf.status != "active":
        await ChannelGatewayService._mark(event_id, "rejected", "configured workflow missing or inactive", route=label)
        raise HTTPException(status.HTTP_409_CONFLICT, "the workflow bound to this channel is missing or inactive")
    from alberto.services.dispatch import dispatch_message
    result = await dispatch_message(run_service, tenant_id=ch.tenant_id, project_id=ch.project_id,
                                    workflow_id=wf.id, text=text, conversation_key=conv_key,
                                    source="channel_email")
    ack = await _maybe_open_handoff(ch, result, customer=parsed.get("from_addr"), customer_message=text, reply_context=parsed)
    reply_text = ack or result.get("answer")
    delivered = None
    if cfg.get("reply", True) and reply_text:
        try:
            # send_reply retries with backoff and returns whether an email was actually sent
            # (False = SMTP not configured); a failure raises so we can record it (audit E).
            delivered = await email_ch.send_reply(ch, parsed, reply_text)
        except Exception:  # noqa: BLE001 - reply delivery failure shouldn't 500 the webhook
            log.warning("email reply delivery failed for channel %s", ch.id, exc_info=True)
            delivered = False
    await ChannelGatewayService._mark(event_id, "delivered" if delivered in (True, None) else "delivery_failed",
                                      None, route=label, run_id=result.get("run_id"))
    return {"ok": True, "handoff": bool(ack), "delivered": delivered}


@public.post("/v1/channels/telegram/{key}/webhook")
async def telegram_webhook(key: str, request: Request, run_service: RunService = Depends(get_run_service)):
    ch = await _resolve("telegram", key)
    if tg.effective_transport(ch) != "webhook":
        raise HTTPException(status.HTTP_409_CONFLICT, "channel is in polling mode")
    secret_header = request.headers.get("x-telegram-bot-api-secret-token")
    if not await tg.verify_webhook_secret_for_channel(secret_header, ch):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook secret")
    if not rate_limiter.allow(f"telegram:{key}", rate=300, per=60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")
    raw = await _read_body_limited(request)
    try:
        import json
        update = json.loads(raw)
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid json") from None
    await ingest_telegram_update(ch, update, run_service=run_service)
    return {"ok": True}

