"""Telegram channel adapter - Bot API client, update normalisation, transport selection.

Transports (mutually exclusive per bot - Telegram itself refuses getUpdates while a webhook is set):
- webhook: Telegram POSTs updates to /v1/channels/telegram/{key}/webhook; authenticity is the
  X-Telegram-Bot-Api-Secret-Token header (derived per channel, constant-time compared).
- polling: a lightweight in-process loop calls getUpdates (no public HTTPS endpoint needed).
- auto: webhook when PUBLIC_BASE_URL is a public https URL, else polling.

The bot token lives ONLY in the Secret Store (channel.config holds a secret:// ref). It is never
returned to the frontend and never logged - every error string is passed through `redact`.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from alberto.config import settings
from alberto.secrets.store import SecretStore
from alberto.util.http import shared_async_client

log = logging.getLogger("forge.channels.telegram")

API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4096
_TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}")


class TelegramError(RuntimeError):
    """Telegram API failure. Message is already token-redacted."""

    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def redact(text: str, token: str | None = None) -> str:
    """Strip the bot token (and anything shaped like one) from a string before it can be logged."""
    out = text
    if token:
        out = out.replace(token, "[REDACTED]")
    return _TOKEN_RE.sub("[REDACTED]", out)


# ---------------------------------------------------------------- Bot API ---

async def _call(token: str, method: str, payload: dict | None = None, *, timeout: float = 30.0) -> Any:
    url = f"{API_BASE}/bot{token}/{method}"
    try:
        r = await shared_async_client().post(url, json=payload or {}, timeout=timeout)
    except httpx.HTTPError as e:  # httpx messages can embed the token-bearing URL
        raise TelegramError(redact(f"telegram {method} transport error: {type(e).__name__}", token)) from None
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {}
    if r.status_code == 200 and body.get("ok"):
        return body.get("result")
    params = body.get("parameters") or {}
    raise TelegramError(
        redact(f"telegram {method} failed: {body.get('description') or r.status_code}", token),
        status=r.status_code, retry_after=params.get("retry_after"),
    )


async def get_me(token: str) -> dict:
    return await _call(token, "getMe")


async def set_webhook(token: str, url: str, secret: str) -> None:
    await _call(token, "setWebhook", {
        "url": url, "secret_token": secret, "allowed_updates": ["message"],
        "drop_pending_updates": False,
    })


async def delete_webhook(token: str) -> None:
    await _call(token, "deleteWebhook", {"drop_pending_updates": False})


async def get_webhook_info(token: str) -> dict:
    return await _call(token, "getWebhookInfo")


async def get_updates(token: str, offset: int | None, timeout: int = 0) -> list[dict]:
    payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    return await _call(token, "getUpdates", payload, timeout=timeout + 15.0) or []


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    text = text or ""
    if len(text) <= limit:
        return [text] if text else []
    parts: list[str] = []
    while text:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts


async def send_raw_message(token: str, chat_id: str | int, text: str, *, reply_to: int | None = None) -> dict:
    """Send a single message and return Telegram's Message result (containing message_id)."""
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
        payload["allow_sending_without_reply"] = True
    return await _call(token, "sendMessage", payload)


async def edit_message_text(token: str, chat_id: str | int, message_id: int, text: str) -> dict | None:
    """Edit existing Telegram message text in place. Ignores 'message is not modified' gracefully."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        return await _call(token, "editMessageText", payload)
    except TelegramError as e:
        if "message is not modified" in str(e).lower():
            return None
        raise


async def send_message(token: str, chat_id: str | int, text: str, *, reply_to: int | None = None) -> int:
    """Send `text` (chunked at Telegram's 4096-char limit). Returns number of messages sent."""
    sent = 0
    for i, part in enumerate(split_message(text)):
        payload: dict[str, Any] = {"chat_id": chat_id, "text": part, "disable_web_page_preview": True}
        if reply_to and i == 0:
            payload["reply_to_message_id"] = reply_to
            payload["allow_sending_without_reply"] = True
        await _call(token, "sendMessage", payload)
        sent += 1
    return sent



async def send_chat_action(token: str, chat_id: str | int, action: str = "typing") -> bool:
    """Broadcast chat action (e.g. 'typing'). Returns True if successful."""
    try:
        target = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
        res = await _call(token, "sendChatAction", {"chat_id": target, "action": action})
        try:
            with open("data/typing.log", "a") as f:
                f.write(f"send_chat_action {action} to {target}: {res}\n")
        except Exception:
            pass
        return bool(res)
    except Exception as e:
        try:
            with open("data/typing.log", "a") as f:
                f.write(f"send_chat_action {action} to {chat_id} FAILED: {e}\n")
        except Exception:
            pass
        log.warning("telegram sendChatAction %s to chat %s failed: %s", action, chat_id, e)
        return False


class TypingNotifier:
    """Context manager that sends chat action immediately and repeats every interval seconds."""

    def __init__(self, token: str, chat_id: str | int, interval: float = 3.5) -> None:
        self.token = token
        self.chat_id = chat_id
        self.interval = interval
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.interval)
                await send_chat_action(self.token, self.chat_id, "typing")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning("typing notifier loop failed: %s", e)

    async def __aenter__(self):
        await send_chat_action(self.token, self.chat_id, "typing")
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


# ------------------------------------------------------------- credentials ---

async def resolve_token(channel) -> str | None:
    ref = (channel.config or {}).get("bot_token_ref")
    if not ref:
        return None
    try:
        value = await SecretStore().read_ref(tenant_id=channel.tenant_id, project_id=channel.project_id, ref=ref)
    except Exception:  # noqa: BLE001 - missing/deleted secret => channel reports disconnected
        return None
    return str(value) if value else None


def webhook_secret(channel_key: str) -> str:
    """Per-channel Telegram `secret_token` (1-256 chars of A-Za-z0-9_-). Derived from the
    unguessable channel key so nothing extra needs storing; distinct from the URL path."""
    return hmac.new(channel_key.encode(), b"alberto-telegram-webhook", hashlib.sha256).hexdigest()


async def resolve_webhook_secret(channel) -> str:
    """Resolve the webhook secret from SecretStore if configured, else fallback to deterministic HMAC."""
    if not channel:
        return ""
    ref = (channel.config or {}).get("webhook_secret_ref")
    if ref:
        try:
            val = await SecretStore().read_ref(tenant_id=channel.tenant_id, project_id=channel.project_id, ref=ref)
            if val:
                return str(val)
        except Exception:
            pass
    return webhook_secret(channel.key)


def verify_webhook_secret(header_value: str | None, channel_key: str, expected_secret: str | None = None) -> bool:
    if not header_value or not channel_key:
        return False
    target = expected_secret if expected_secret is not None else webhook_secret(channel_key)
    return hmac.compare_digest(header_value, target)


async def verify_webhook_secret_for_channel(header_value: str | None, channel) -> bool:
    if not header_value or not channel:
        return False
    expected = await resolve_webhook_secret(channel)
    return hmac.compare_digest(header_value, expected)


# --------------------------------------------------------------- transport ---

def _is_public_https(url: str) -> bool:
    try:
        u = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and bool(host) and host not in ("localhost", "127.0.0.1", "::1") \
        and not host.endswith(".local")


def webhook_url(channel_key: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/v1/channels/telegram/{channel_key}/webhook"


def effective_transport(channel) -> str:
    """'webhook' | 'polling' for a telegram channel (never both)."""
    want = ((channel.config or {}).get("transport") or "auto").lower()
    if want == "webhook":
        return "webhook"
    if want == "polling":
        return "polling"
    return "webhook" if _is_public_https(settings.public_base_url) else "polling"


async def apply_transport(channel, token: str) -> str:
    """Make Telegram match the chosen transport (mutual exclusion). Returns the active transport."""
    transport = effective_transport(channel)
    if transport == "webhook":
        secret = await resolve_webhook_secret(channel)
        await set_webhook(token, webhook_url(channel.key), secret)
    else:
        await delete_webhook(token)  # polling is impossible while a webhook is registered
    return transport


async def disconnect(channel) -> None:
    """Best-effort: unregister the webhook so the bot stops POSTing to a deleted channel."""
    token = await resolve_token(channel)
    if token:
        try:
            await delete_webhook(token)
        except TelegramError:
            log.warning("telegram webhook cleanup failed for channel %s", channel.id)


# ------------------------------------------------------------ normalisation ---

def parse_update(update: dict) -> dict | None:
    """Normalise a Telegram update. Returns None for updates we never act on (non-message,
    bots, groups). `text` is None for unsupported message types so the gateway can say so."""
    if not isinstance(update, dict) or "update_id" not in update:
        return None
    msg = update.get("message")
    if not isinstance(msg, dict):
        return None
    frm = msg.get("from") or {}
    chat = msg.get("chat") or {}
    if frm.get("is_bot"):  # bot-to-bot loop protection
        return None
    if chat.get("type") != "private":  # v1: private chats only
        return None
    if frm.get("id") is None or chat.get("id") is None:
        return None
    label = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x) or frm.get("username") or None
    text = msg.get("text")
    return {
        "update_id": int(update["update_id"]),
        "message_id": msg.get("message_id"),
        "user_id": str(frm["id"]),
        "chat_id": str(chat["id"]),
        "label": label,
        "text": text if isinstance(text, str) else None,
        "timestamp": msg.get("date"),
    }


def strip_bot_suffix(command: str) -> str:
    """'/status@MyBot' -> '/status'."""
    return command.split("@", 1)[0]
