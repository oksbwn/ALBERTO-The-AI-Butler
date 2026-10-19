"""ChannelGatewayService - workflow-independent inbound/outbound routing for communication channels.

Responsibilities (coordination only - it never executes tools itself):
  validate transport -> normalise -> dedup -> verify external identity (pairing) -> resolve the
  Alberto user -> deterministic route (command rule, else the channel default) -> dispatch to the
  existing Master Agent / authorised subagent / configured workflow runtime -> deliver the reply
  through the ORIGINAL channel adapter -> persist safe diagnostics.

Security invariants:
- No verified identity => no Master Agent / subagent / tool access, ever. Unknown senders get a
  one-time pairing challenge only.
- The Master Agent runs as the *paired* Alberto user (their role, tenant, project); tool calls still
  go through delegate_tool_execution -> ToolPolicyService (HITL etc.). The gateway has no tool
  exemption of its own.
- Routing is explicit. No implicit workflow fallback; an unavailable destination yields a controlled
  routing error rather than a silent switch to another (possibly more privileged) target.
- Inbound text is untrusted user data: it is only ever passed as a user message.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from alberto.channels import email as email_ch
from alberto.channels import telegram as tg
from alberto.channels.retry import retry_send
from alberto.db.base import SessionLocal
from alberto.models import (
    Agent,
    Channel,
    ChannelEvent,
    ChannelIdentity,
    ChannelPairing,
    User,
    Workflow,
)
from alberto.services.audit import AuditService
from alberto.services.auth import role_at_least
from alberto.util.ratelimit import rate_limiter
from alberto.util.tasks import spawn

log = logging.getLogger("forge.channels.gateway")

PAIRING_TTL = timedelta(minutes=10)
PAIRING_MAX_PER_HOUR = 3
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
_MAX_INBOUND_CHARS = 8000

PAIRING_REQUIRED_TEXT = (
    "Hi! I don't know this account yet. To pair it, sign in to Alberto, open "
    "Integrations -> {channel} -> Access & Pairing and enter this one-time code "
    "(valid {minutes} minutes): {code}"
)


@dataclass
class NormalizedMessage:
    """Minimal typed contract between channel adapters and the gateway. No credentials and no raw
    provider payloads. `reply_context` is adapter-private (e.g. email threading headers) and is
    never persisted."""

    channel_id: str
    provider: str
    external_sender_id: str
    external_conversation_id: str
    provider_message_id: str
    text: str | None
    tenant_id: str
    project_id: str
    verified: bool
    timestamp: float | None = None
    display_label: str | None = None
    direction: str = "inbound"
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    reply_context: dict = field(default_factory=dict)
    # Filled by the gateway:
    user_id: str | None = None
    thread_key: str | None = None


@dataclass
class GatewayResult:
    status: str
    reply: str | None = None
    event_id: str | None = None
    duplicate: bool = False
    delivered: bool | None = None


class RoutingError(Exception):
    """Controlled routing failure (safe to show the sender)."""


# ------------------------------------------------------------------ helpers ---

def _hash_code(code: str) -> str:
    norm = code.replace("-", "").replace(" ", "").upper()
    return hashlib.sha256(norm.encode()).hexdigest()


def _new_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def conversation_thread_id(channel: Channel, msg: NormalizedMessage, epoch: int = 0) -> str:
    """Stable, collision-free assistant thread id: channel + verified provider user + external
    chat + tenant/project (+ reset epoch). Survives restarts (derived, not in-memory)."""
    basis = "|".join([channel.id, msg.external_sender_id, msg.external_conversation_id,
                      channel.tenant_id, channel.project_id, str(epoch)])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"alberto-channel:{basis}"))


_locks: dict[str, asyncio.Lock] = {}


class _ConvLock:
    """Serialise messages of ONE conversation (ordering) without blocking others."""

    def __init__(self, key: str) -> None:
        self.key = key

    async def __aenter__(self):
        lock = _locks.setdefault(self.key, asyncio.Lock())
        self.lock = lock
        await lock.acquire()

    async def __aexit__(self, *exc):
        self.lock.release()
        if not self.lock.locked() and not getattr(self.lock, "_waiters", None):
            _locks.pop(self.key, None)


# ----------------------------------------------------------------- identity ---

class ChannelIdentityService:
    @staticmethod
    async def find(s, channel: Channel, provider_user_id: str) -> ChannelIdentity | None:
        return (await s.execute(select(ChannelIdentity).where(
            ChannelIdentity.channel_id == channel.id, ChannelIdentity.provider_user_id == provider_user_id,
        ))).scalar_one_or_none()

    @staticmethod
    async def issue_pairing(channel: Channel, msg: NormalizedMessage) -> str | None:
        """Create/refresh the pending identity and a fresh one-time code. Returns the plaintext
        code ONCE (never stored or logged) or None when the sender is rate limited."""
        async with SessionLocal() as s:
            ident = await ChannelIdentityService.find(s, channel, msg.external_sender_id)
            if ident is None:
                ident = ChannelIdentity(
                    tenant_id=channel.tenant_id, project_id=channel.project_id, channel_id=channel.id,
                    provider_user_id=msg.external_sender_id, provider_chat_id=msg.external_conversation_id,
                    display_label=msg.display_label, status="pending",
                )
                s.add(ident)
                try:
                    await s.commit()
                except IntegrityError:  # concurrent first contact
                    await s.rollback()
                    ident = await ChannelIdentityService.find(s, channel, msg.external_sender_id)
                    if ident is None:
                        return None
            if ident.status == "verified":
                return None
            hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent = (await s.execute(select(ChannelPairing).where(
                ChannelPairing.identity_id == ident.id, ChannelPairing.created_at >= hour_ago,
            ))).scalars().all()
            if len(recent) >= PAIRING_MAX_PER_HOUR:
                return None
            # one live code per identity: invalidate older unconsumed ones
            await s.execute(update(ChannelPairing).where(
                ChannelPairing.identity_id == ident.id, ChannelPairing.consumed_at.is_(None),
            ).values(consumed_at=datetime.utcnow()))
            ident.status = "pending"
            ident.provider_chat_id = msg.external_conversation_id
            code = _new_code()
            s.add(ChannelPairing(
                tenant_id=channel.tenant_id, project_id=channel.project_id, channel_id=channel.id,
                identity_id=ident.id, code_hash=_hash_code(code), expires_at=datetime.utcnow() + PAIRING_TTL,
            ))
            await s.commit()
            return code

    @staticmethod
    async def confirm(s, *, tenant_id: str, project_id: str, channel_id: str, code: str,
                      acting_user_id: str, acting_role: str, bind_user_id: str | None = None) -> ChannelIdentity:
        """Bind the identity behind `code` to an Alberto user. The caller must be authenticated
        (router dependency). Raises ValueError with a deliberately generic message on any failure."""
        generic = ValueError("invalid or expired pairing code")
        if not rate_limiter.allow(f"pairing-confirm:{tenant_id}:{acting_user_id}", rate=10, per=60):
            raise ValueError("too many attempts; wait a minute")
        target_user_id = acting_user_id
        if bind_user_id and bind_user_id != acting_user_id:
            if not role_at_least(acting_role, "admin"):
                raise ValueError("only an admin can pair an identity to another user")
            target_user_id = bind_user_id
        user = (await s.execute(select(User).where(User.id == target_user_id, User.tenant_id == tenant_id))).scalar_one_or_none()
        if user is None or user.status != "active":
            raise ValueError("a real, active Alberto user is required to pair an identity")
        now = datetime.utcnow()
        pairing = (await s.execute(select(ChannelPairing).where(
            ChannelPairing.tenant_id == tenant_id, ChannelPairing.project_id == project_id,
            ChannelPairing.channel_id == channel_id, ChannelPairing.code_hash == _hash_code(code),
        ))).scalars().first()
        if pairing is None or pairing.consumed_at is not None or pairing.expires_at < now:
            raise generic
        # atomic one-time consumption (replay protection)
        res = await s.execute(update(ChannelPairing).where(
            ChannelPairing.id == pairing.id, ChannelPairing.consumed_at.is_(None),
        ).values(consumed_at=now))
        if res.rowcount != 1:
            await s.rollback()
            raise generic
        ident = await s.get(ChannelIdentity, pairing.identity_id)
        if ident is None:
            await s.rollback()
            raise generic
        ident.user_id, ident.status, ident.verified_at, ident.revoked_at = user.id, "verified", now, None
        await s.commit()
        await s.refresh(ident)
        return ident

    @staticmethod
    async def revoke(s, tenant_id: str, channel_id: str, identity_id: str) -> bool:
        ident = (await s.execute(select(ChannelIdentity).where(
            ChannelIdentity.id == identity_id, ChannelIdentity.channel_id == channel_id,
            ChannelIdentity.tenant_id == tenant_id,
        ))).scalar_one_or_none()
        if ident is None:
            return False
        ident.status, ident.revoked_at = "revoked", datetime.utcnow()
        await s.execute(update(ChannelPairing).where(
            ChannelPairing.identity_id == ident.id, ChannelPairing.consumed_at.is_(None),
        ).values(consumed_at=datetime.utcnow()))
        await s.commit()
        return True


# ------------------------------------------------------------------ gateway ---

class ChannelGatewayService:
    # --- intake -------------------------------------------------------------------------
    @staticmethod
    async def accept(channel: Channel, msg: NormalizedMessage, *, run_service=None, wait: bool = False) -> GatewayResult:
        """Webhook/poller entry: dedup + persist, then process asynchronously (or inline when
        `wait`). Returns immediately so the provider request is never held for an LLM reply."""
        if not channel.enabled:
            return GatewayResult(status="rejected")
        if not rate_limiter.allow(f"chan-in:{channel.id}:{msg.external_sender_id}", rate=30, per=60):
            return GatewayResult(status="rate_limited")
        event_id = await ChannelGatewayService._record_event(channel, msg)
        if event_id is None:
            return GatewayResult(status="duplicate", duplicate=True)
        coro = ChannelGatewayService.process(channel.id, event_id, msg, run_service=run_service)
        if wait:
            return await coro
        if not spawn(coro, name=f"channel-{channel.id}-{event_id}"):
            await ChannelGatewayService._mark(event_id, "failed", "server busy")
            return GatewayResult(status="failed", event_id=event_id)
        return GatewayResult(status="accepted", event_id=event_id)

    @staticmethod
    async def _record_event(channel: Channel, msg: NormalizedMessage) -> str | None:
        async with SessionLocal() as s:
            ev = ChannelEvent(
                tenant_id=channel.tenant_id, project_id=channel.project_id, channel_id=channel.id,
                provider_event_id=msg.provider_message_id, status="received",
                correlation_id=msg.correlation_id,
            )
            s.add(ev)
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()
                return None
            return ev.id

    @staticmethod
    async def _mark(event_id: str, status: str, detail: str | None = None, **extra: Any) -> None:
        async with SessionLocal() as s:
            ev = await s.get(ChannelEvent, event_id)
            if ev is None:
                return
            ev.status = status
            if detail is not None:
                ev.detail = detail[:300]
            for k, v in extra.items():
                setattr(ev, k, v)
            await s.commit()

    # --- processing ---------------------------------------------------------------------
    @staticmethod
    async def process(channel_id: str, event_id: str, msg: NormalizedMessage, *, run_service=None) -> GatewayResult:
        async with SessionLocal() as s:
            channel = await s.get(Channel, channel_id)
        if channel is None or not channel.enabled:
            await ChannelGatewayService._mark(event_id, "rejected", "channel disabled or removed")
            return GatewayResult(status="rejected", event_id=event_id)
        async with _ConvLock(f"{channel.id}:{msg.external_sender_id}:{msg.external_conversation_id}"):
            try:
                await ChannelGatewayService._mark(event_id, "processing")
                return await ChannelGatewayService._process_locked(channel, event_id, msg, run_service)
            except Exception as e:  # noqa: BLE001 - never leak internals to the sender
                log.exception("channel %s event %s failed", channel.id, event_id)
                await ChannelGatewayService._mark(event_id, "failed", f"{type(e).__name__}")
                return GatewayResult(status="failed", event_id=event_id)

    @staticmethod
    async def _reply(channel: Channel, event_id: str, msg: NormalizedMessage, status: str, text: str | None,
                     detail: str | None = None, **extra: Any) -> GatewayResult:
        delivered = None
        if text:
            delivered = await ChannelGatewayService.deliver(channel, msg, text)
            if delivered is False and status in ("delivered", "pairing_required"):
                status = "delivery_failed"
                detail = detail or "reply could not be delivered"
        elif status == "delivered":
            status = "processed"
        await ChannelGatewayService._mark(event_id, status, detail, **extra)
        return GatewayResult(status=status, reply=text, event_id=event_id, delivered=delivered)

    @staticmethod
    async def _process_locked(channel: Channel, event_id: str, msg: NormalizedMessage, run_service) -> GatewayResult:
        # 1. unverifiable transport (e.g. unsigned email) is quarantined: no identity, no reply.
        if not msg.verified:
            await ChannelGatewayService._mark(event_id, "quarantined", "sender authenticity not verified")
            return GatewayResult(status="quarantined", event_id=event_id)
        # 2. unsupported content (voice, photo, ...)
        if msg.text is None or not msg.text.strip():
            ident = None
            async with SessionLocal() as s:
                ident = await ChannelIdentityService.find(s, channel, msg.external_sender_id)
            if ident is not None and ident.status == "verified":
                return await ChannelGatewayService._reply(channel, event_id, msg, "delivered",
                                                          "I can only read text messages right now.")
            await ChannelGatewayService._mark(event_id, "rejected", "unsupported content from unpaired sender")
            return GatewayResult(status="rejected", event_id=event_id)
        text = msg.text.strip()[:_MAX_INBOUND_CHARS]
        # 3. identity
        async with SessionLocal() as s:
            ident = await ChannelIdentityService.find(s, channel, msg.external_sender_id)
            user = None
            if ident is not None and ident.status == "verified" and ident.user_id:
                user = (await s.execute(select(User).where(
                    User.id == ident.user_id, User.tenant_id == channel.tenant_id))).scalar_one_or_none()
        if ident is None or ident.status != "verified":
            if ident is not None and ident.status == "revoked":
                pass  # a revoked sender may re-pair explicitly via a fresh code
            code = await ChannelIdentityService.issue_pairing(channel, msg)
            if code is None:
                return await ChannelGatewayService._reply(
                    channel, event_id, msg, "pairing_required",
                    "Pairing is unavailable right now (too many requests). Please try again later.",
                    "pairing rate limited")
            reply = PAIRING_REQUIRED_TEXT.format(channel=channel.name, minutes=int(PAIRING_TTL.total_seconds() // 60), code=code)
            return await ChannelGatewayService._reply(channel, event_id, msg, "pairing_required", reply, "pairing code issued")
        if user is None or user.status != "active":
            return await ChannelGatewayService._reply(
                channel, event_id, msg, "rejected",
                "Access for this account has been revoked or disabled. Ask an Alberto admin to pair it again.",
                "user missing or disabled")
        msg.user_id = user.id
        # 4. built-in commands that never reach an agent
        cmd = tg.strip_bot_suffix(text.split()[0].lower()) if text.startswith("/") else ""
        if cmd in ("/reset", "/new"):
            await ChannelGatewayService._bump_epoch(channel.id, msg)
            return await ChannelGatewayService._reply(channel, event_id, msg, "delivered",
                                                      "Conversation reset. Starting fresh.", "session reset", route="reset")
        if cmd in ("/start", "/help") and channel.type == "telegram":
            return await ChannelGatewayService._reply(
                channel, event_id, msg, "delivered",
                "Paired. Just send a message to chat with Alberto. /reset starts a new conversation.", route="help")
        # 5. deterministic routing
        try:
            target_type, target_id, route_label, route_text = ChannelGatewayService.resolve_route(channel, text)
        except RoutingError as e:
            return await ChannelGatewayService._reply(channel, event_id, msg, "rejected",
                                                      f"This channel can't route your message: {e}", str(e), route="error")
        epoch = (channel.state or {}).get("epochs", {}).get(f"{msg.external_sender_id}:{msg.external_conversation_id}", 0)
        thread_id = conversation_thread_id(channel, msg, epoch)
        msg.thread_key = thread_id
        await ChannelGatewayService._mark(event_id, "processing", None, user_id=user.id, route=route_label, thread_key=thread_id)
        # 6. dispatch
        try:
            reply, extra = await ChannelGatewayService._dispatch(
                channel, msg, user, target_type, target_id, route_text, thread_id, run_service)
        except RoutingError as e:
            return await ChannelGatewayService._reply(channel, event_id, msg, "rejected",
                                                      f"This channel can't route your message: {e}", str(e), route=route_label)
        return await ChannelGatewayService._reply(channel, event_id, msg, "delivered", reply, route=route_label, **extra)

    # --- routing ------------------------------------------------------------------------
    @staticmethod
    def resolve_route(channel: Channel, text: str) -> tuple[str, str | None, str, str]:
        """(target_type, target_id, label, text_for_target). Order: exact command rule, else the
        channel default. Never falls back to anything else."""
        if text.startswith("/"):
            first, _, rest = text.partition(" ")
            cmd = tg.strip_bot_suffix(first.lower())
            for r in channel.routes or []:
                if r.get("command") == cmd:
                    return r["target_type"], r.get("target_id"), f"command:{cmd}", (rest.strip() or text)
        if channel.routing_state == "needs_review" or channel.target_type is None:
            raise RoutingError("its destination has not been confirmed yet")
        return channel.target_type, channel.target_id, f"default:{channel.target_type}", text

    @staticmethod
    async def _bump_epoch(channel_id: str, msg: NormalizedMessage) -> int:
        async with SessionLocal() as s:
            ch = await s.get(Channel, channel_id)
            state = dict(ch.state or {})
            epochs = dict(state.get("epochs", {}))
            k = f"{msg.external_sender_id}:{msg.external_conversation_id}"
            epochs[k] = int(epochs.get(k, 0)) + 1
            state["epochs"] = epochs
            ch.state = state
            await s.commit()
            return epochs[k]

    # --- dispatch -----------------------------------------------------------------------
    @staticmethod
    async def _dispatch(channel: Channel, msg: NormalizedMessage, user: User, target_type: str,
                        target_id: str | None, text: str, thread_id: str, run_service) -> tuple[str, dict]:
        if target_type == "master_agent":
            return await ChannelGatewayService._run_assistant(channel, user, text, thread_id, persona=None), {}
        if target_type == "subagent":
            async with SessionLocal() as s:
                agent = (await s.execute(select(Agent).where(
                    Agent.id == target_id, Agent.tenant_id == channel.tenant_id,
                    Agent.project_id == channel.project_id))).scalar_one_or_none()
            if agent is None:
                raise RoutingError("the configured subagent no longer exists")
            if (agent.config or {}).get("status") == "inactive":
                raise RoutingError("the configured subagent is inactive")
            if agent.system_key in ("tool_manager", "graph_manager", "memory_curator"):
                raise RoutingError(f"that agent ({agent.name}) is an internal system agent and not a conversational destination")
            if not role_at_least(user.role, "viewer"):
                raise RoutingError("your account is not allowed to use this subagent")
            persona = agent.system_key or agent.name
            return await ChannelGatewayService._run_assistant(channel, user, text, thread_id, persona=persona), {}
        if target_type == "workflow":
            async with SessionLocal() as s:
                wf = (await s.execute(select(Workflow).where(
                    Workflow.id == target_id, Workflow.tenant_id == channel.tenant_id,
                    Workflow.project_id == channel.project_id))).scalar_one_or_none()
            if wf is None:
                raise RoutingError("the configured workflow no longer exists")
            if wf.status != "active":
                raise RoutingError("the configured workflow is not active")
            if run_service is None:
                from alberto.services.runs import RunService
                run_service = RunService(checkpointer=None, store=None)
            from alberto.services.dispatch import dispatch_message
            result = await dispatch_message(
                run_service, tenant_id=channel.tenant_id, project_id=channel.project_id, workflow_id=wf.id,
                text=text, conversation_key=f"{channel.id}:{msg.external_conversation_id}",
                source=f"channel_{channel.type}", end_user={"id": user.id},
            )
            if result.get("interrupted"):
                return "Your request is waiting for approval or input. A team member will follow up.", {"run_id": result.get("run_id")}
            return (result.get("answer") or "(no reply)"), {"run_id": result.get("run_id")}
        raise RoutingError("unknown destination type")

    @staticmethod
    async def _run_assistant(channel: Channel, user: User, text: str, thread_id: str, persona: str | None) -> str:
        """Run the Master Agent (or a persona) AS the paired user. Tool execution inside still goes
        through delegate_tool_execution -> ToolManagerService -> ToolPolicyService."""
        from alberto.deps import CurrentUser
        from alberto.services.assistant import AssistantService

        cu = CurrentUser(id=user.id, tenant_id=user.tenant_id, role=user.role, email=user.email)
        chunks: list[str] = []
        err: str | None = None
        async for frame in AssistantService.stream(
            tenant_id=channel.tenant_id, project_id=channel.project_id,
            messages=[{"role": "user", "content": text}], thread_id=thread_id,
            checkpointer=None, thinking=False, persona=persona, current_user=cu,
        ):
            ev, data = frame.get("event"), frame.get("data") or {}
            if ev == "messages":
                chunks.append(str(data.get("content", "")))
            elif ev == "error":
                err = str(data.get("message", "error"))
        reply = "".join(chunks).strip()
        if not reply:
            raise RuntimeError(err or "empty assistant reply")
        return reply

    # --- outbound -----------------------------------------------------------------------
    @staticmethod
    async def deliver(channel: Channel, msg: NormalizedMessage, text: str) -> bool:
        """Reply through the ORIGINAL channel adapter. Returns False when undeliverable."""
        try:
            if channel.type == "telegram":
                token = await tg.resolve_token(channel)
                if not token:
                    return False
                reply_to = msg.reply_context.get("reply_to")

                async def _attempt(_n: int) -> int:
                    try:
                        return await tg.send_message(token, msg.external_conversation_id, text, reply_to=reply_to)
                    except tg.TelegramError as e:
                        from alberto.channels.retry import ChannelDeliveryError
                        if e.status in (400, 401, 403, 404):  # permanent (blocked bot, bad chat)
                            raise
                        raise ChannelDeliveryError(str(e), retry_after=e.retry_after) from None

                await retry_send(_attempt, label=f"telegram->{msg.external_conversation_id}")
                return True
            if channel.type == "email":
                parsed = dict(msg.reply_context)
                return bool(await email_ch.send_reply(channel, parsed, text))
        except Exception as e:  # noqa: BLE001
            log.warning("delivery failed on channel %s (%s)", channel.id, tg.redact(type(e).__name__))
        return False

    # --- recovery -----------------------------------------------------------------------
    @staticmethod
    async def recover_stale_events(max_age_s: int = 600) -> int:
        """Startup sweep: events left 'received'/'processing' by a dead process are marked
        'interrupted' and NOT replayed - re-running could repeat an external side effect whose
        outcome is unknown. The sender can simply resend."""
        cutoff = datetime.utcnow() - timedelta(seconds=max_age_s)
        async with SessionLocal() as s:
            res = await s.execute(update(ChannelEvent).where(
                ChannelEvent.status.in_(("received", "processing")), ChannelEvent.updated_at < cutoff,
            ).values(status="interrupted", detail="process restarted before completion; not replayed"))
            await s.commit()
            return res.rowcount or 0


# ----------------------------------------------------------- outbound service ---

class ChannelDeliveryService:
    """Authorised, scoped outbound messaging independent of any inbound workflow run.

    Callers (Master Agent, subagent, workflow, scheduler, notifications) pass an `actor`; the
    recipient must be a VERIFIED paired identity of this channel and the actor must be that
    identity's own Alberto user or an admin. A model/caller can never address an arbitrary chat
    or email address."""

    @staticmethod
    async def send(*, tenant_id: str, project_id: str, channel_id: str, actor: dict,
                   identity_id: str, text: str, subject: str | None = None) -> dict:
        if not text or not text.strip():
            raise ValueError("message text is required")
        async with SessionLocal() as s:
            channel = (await s.execute(select(Channel).where(
                Channel.id == channel_id, Channel.tenant_id == tenant_id, Channel.project_id == project_id,
            ))).scalar_one_or_none()
            if channel is None:
                raise LookupError("channel not found")
            if not channel.enabled:
                raise PermissionError("channel is disabled")
            ident = (await s.execute(select(ChannelIdentity).where(
                ChannelIdentity.id == identity_id, ChannelIdentity.channel_id == channel.id,
                ChannelIdentity.tenant_id == tenant_id,
            ))).scalar_one_or_none()
        if ident is None or ident.status != "verified" or not ident.user_id:
            raise PermissionError("recipient is not a verified paired identity on this channel")
        actor_user = actor.get("user_id")
        if actor_user != ident.user_id and not role_at_least(actor.get("role", ""), "admin"):
            raise PermissionError("not allowed to message this recipient")
        if not rate_limiter.allow(f"chan-out:{channel.id}", rate=60, per=60):
            raise PermissionError("outbound rate limit exceeded")
        ok = False
        if channel.type == "telegram":
            token = await tg.resolve_token(channel)
            if token:
                await tg.send_message(token, ident.provider_chat_id or ident.provider_user_id, text)
                ok = True
        elif channel.type == "email":
            ok = bool(await email_ch.send_outbound(channel, ident.provider_user_id, subject or "", text))
        await AuditService.log(
            tenant_id=tenant_id, project_id=project_id, action="channel.send", actor_id=actor_user,
            resource_type="channel", resource_id=channel.id, status="ok" if ok else "error",
            meta={"identity_id": ident.id, "actor_kind": actor.get("kind", "user"), "chars": len(text)},
        )
        return {"ok": ok, "channel_id": channel.id, "identity_id": ident.id}


# ------------------------------------------------------------ telegram inbound ---

async def ingest_telegram_update(channel: Channel, update: dict, *, run_service=None, wait: bool = False) -> GatewayResult | None:
    """Normalise one Telegram update and hand it to the gateway. Shared by webhook + polling."""
    p = tg.parse_update(update)
    if p is None:
        return None
    msg = NormalizedMessage(
        channel_id=channel.id, provider="telegram", external_sender_id=p["user_id"],
        external_conversation_id=p["chat_id"], provider_message_id=f"tg-update-{p['update_id']}",
        text=p["text"], tenant_id=channel.tenant_id, project_id=channel.project_id,
        verified=True,  # transport authenticity: webhook secret header / bot-token polling
        timestamp=p.get("timestamp"), display_label=p.get("label"),
        reply_context={"reply_to": p.get("message_id")},
    )
    return await ChannelGatewayService.accept(channel, msg, run_service=run_service, wait=wait)


async def _set_state(channel_id: str, **kv: Any) -> None:
    async with SessionLocal() as s:
        ch = await s.get(Channel, channel_id)
        if ch is None:
            return
        state = dict(ch.state or {})
        state.update(kv)
        ch.state = state
        await s.commit()


async def telegram_poll_once(channel_id: str, *, run_service=None, timeout: int = 0, wait: bool = False) -> int:
    """One getUpdates cycle for a polling-mode channel. At-least-once: the offset advances only
    after every update was handed to the gateway, and the event ledger dedups any re-delivery.
    Errors are recorded (token-redacted) with exponential backoff - the loop never dies."""
    import time

    async with SessionLocal() as s:
        ch = await s.get(Channel, channel_id)
    if ch is None or ch.type != "telegram" or not ch.enabled or tg.effective_transport(ch) != "polling":
        return 0
    state = dict(ch.state or {})
    if float(state.get("next_poll_at", 0)) > time.time():
        return 0
    token = await tg.resolve_token(ch)
    if not token:
        await _set_state(ch.id, last_error="bot token missing from secret store", connected=False)
        return 0
    try:
        updates = await tg.get_updates(token, state.get("tg_offset"), timeout=timeout)
    except tg.TelegramError as e:
        n = int(state.get("error_count", 0)) + 1
        extra = {}
        if e.status == 409:  # a webhook is registered: restore mutual exclusion, retry next cycle
            try:
                await tg.delete_webhook(token)
            except tg.TelegramError:
                pass
        await _set_state(ch.id, last_error=str(e)[:200], connected=False, error_count=n,
                         next_poll_at=time.time() + min(60, 2 ** n), **extra)
        return 0
    handled = 0
    for upd in updates:
        await ingest_telegram_update(ch, upd, run_service=run_service, wait=wait)
        handled += 1
    patch: dict[str, Any] = {"last_error": None, "connected": True, "error_count": 0,
                             "last_poll_at": time.time(), "next_poll_at": 0}
    if updates:
        patch["tg_offset"] = max(int(u["update_id"]) for u in updates) + 1
    await _set_state(ch.id, **patch)
    return handled


async def telegram_poll_all(run_service=None) -> int:
    """Poll every enabled polling-mode Telegram channel once."""
    async with SessionLocal() as s:
        ids = [c.id for c in (await s.execute(select(Channel).where(
            Channel.type == "telegram", Channel.enabled.is_(True)))).scalars()]
    total = 0
    for cid in ids:
        total += await telegram_poll_once(cid, run_service=run_service)
    return total
