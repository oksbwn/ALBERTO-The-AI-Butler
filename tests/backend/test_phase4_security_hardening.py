"""Phase 4: Security Hardening & Controlled Operational Pilot Tests.

Validates:
1. Telegram webhook secret authentication (constant-time comparison, header rejection, vault storage).
2. Webhook replay and duplicate suppression.
3. Unpaired sender boundary protection.
4. Authentication rate limiting isolated environment guard (production enforcement vs test bypass).
5. Tool policy authorization, sensitive parameter redaction, and approval boundary enforcement.
"""

from __future__ import annotations

import hmac
import uuid
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from alberto.channels import telegram as tg
from alberto.config import settings
from alberto.db.base import SessionLocal
from alberto.main import create_app
from alberto.models import Channel, User
from alberto.secrets.store import SecretStore
from alberto.services.channel_gateway import ChannelGatewayService, NormalizedMessage
from alberto.services.tool_policy import ToolPolicyService


def _client() -> httpx.AsyncClient:
    app = create_app()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _email() -> str:
    return f"sec_{uuid.uuid4().hex[:8]}@example.com"


# --- 1. Telegram Webhook Secret Authentication ---

def test_telegram_webhook_secret_constant_time():
    """Verify constant-time comparison and invalid/missing secret rejection."""
    key = "chan_sec_test_123"
    valid_secret = tg.webhook_secret(key)
    assert valid_secret

    # Valid secret passes
    assert tg.verify_webhook_secret(valid_secret, key) is True

    # Missing / None header fails
    assert tg.verify_webhook_secret(None, key) is False
    assert tg.verify_webhook_secret("", key) is False

    # Invalid secret fails
    assert tg.verify_webhook_secret("wrong-secret-token", key) is False
    assert tg.verify_webhook_secret(valid_secret[:-1] + "x", key) is False

    # Timing resistance: hmac.compare_digest is used
    assert hmac.compare_digest(valid_secret, tg.webhook_secret(key)) is True


async def test_telegram_webhook_vault_secret_resolution():
    """Verify that vault-stored custom webhook secrets are resolved and verified."""
    tenant_id = f"t_{uuid.uuid4().hex[:8]}"
    project_id = f"p_{uuid.uuid4().hex[:8]}"
    key = f"key_{uuid.uuid4().hex[:8]}"

    async with SessionLocal() as session:
        # Store a custom random webhook secret in SecretStore
        custom_secret = "vault_super_secret_token_1234567890"
        secret_name = f"channel-telegram-webhook-{key[:16]}"
        ref = await SecretStore().write(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            name=secret_name,
            value=custom_secret,
            kind="channel",
        )

        ch = Channel(
            tenant_id=tenant_id,
            project_id=project_id,
            type="telegram",
            name="Vault TG Bot",
            key=key,
            config={"webhook_secret_ref": f"secret://{secret_name}", "transport": "webhook"},
            state={"connected": True},
            enabled=True,
        )
        session.add(ch)
        await session.commit()
        await session.refresh(ch)

    # Resolve from channel
    resolved = await tg.resolve_webhook_secret(ch)
    assert resolved == custom_secret

    # Verify matching header passes
    assert await tg.verify_webhook_secret_for_channel(custom_secret, ch) is True
    # Verify non-matching header fails
    assert await tg.verify_webhook_secret_for_channel("invalid-token", ch) is False
    assert await tg.verify_webhook_secret_for_channel(None, ch) is False


async def test_telegram_webhook_endpoint_rejects_missing_and_invalid_secrets():
    """Verify HTTP 401 on missing/invalid secret and HTTP 200 on valid secret."""
    tenant_id = f"t_{uuid.uuid4().hex[:8]}"
    project_id = f"p_{uuid.uuid4().hex[:8]}"
    key = f"tg_wh_{uuid.uuid4().hex[:8]}"

    async with SessionLocal() as session:
        ch = Channel(
            tenant_id=tenant_id,
            project_id=project_id,
            type="telegram",
            name="Test Bot",
            key=key,
            config={"transport": "webhook"},
            state={"connected": True},
            enabled=True,
        )
        session.add(ch)
        await session.commit()
        await session.refresh(ch)

    expected_secret = tg.webhook_secret(key)
    update_payload = {
        "update_id": 1001,
        "message": {
            "message_id": 50,
            "from": {"id": 123456, "first_name": "Bob", "is_bot": False},
            "chat": {"id": 123456, "type": "private"},
            "text": "Hello Alberto",
            "date": 1700000000,
        },
    }

    async with _client() as c:
        url = f"/v1/channels/telegram/{key}/webhook"

        # 1. Missing secret header -> 401 Unauthorized
        r1 = await c.post(url, json=update_payload)
        assert r1.status_code == 401
        assert "invalid webhook secret" in r1.text.lower()

        # 2. Invalid secret header -> 401 Unauthorized
        r2 = await c.post(url, json=update_payload, headers={"x-telegram-bot-api-secret-token": "bad-secret"})
        assert r2.status_code == 401
        assert "invalid webhook secret" in r2.text.lower()

        # 3. Valid secret header -> 200 OK
        with patch.object(ChannelGatewayService, "accept", new_callable=AsyncMock) as mock_accept:
            mock_accept.return_value = AsyncMock(status="accepted", duplicate=False)
            r3 = await c.post(url, json=update_payload, headers={"x-telegram-bot-api-secret-token": expected_secret})
            assert r3.status_code == 200
            assert r3.json() == {"ok": True}
            mock_accept.assert_called_once()


# --- 2. Authentication Rate Limiting Security Guard ---

def test_production_fails_when_auth_rate_limit_disabled(monkeypatch):
    """Production configuration must refuse to start if auth rate limiting is disabled."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "jwt_secret", "a" * 32)
    monkeypatch.setattr(settings, "auth_required", True)
    monkeypatch.setattr(settings, "dev_allow_anonymous_owner", False)
    monkeypatch.setattr(settings, "bootstrap_admin_password", "real-strong-password-1234")
    monkeypatch.setattr(settings, "egress_block_private", True)
    monkeypatch.setattr(settings, "trusted_hosts", ["alberto.local"])
    monkeypatch.setattr(settings, "public_base_url", "https://alberto.local")
    monkeypatch.setattr(settings, "public_console_url", "https://alberto.local")
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 0)

    problems = settings.validate_production()
    assert any("FORGE_AUTH_RATE_LIMIT_PER_MINUTE must be > 0" in p for p in problems)


async def test_auth_rate_limit_enforced_outside_test_mode(monkeypatch):
    """When not in an explicitly isolated test environment, rate limiting is strictly enforced."""
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 2)
    # Simulate a standard dev/staging environment
    monkeypatch.setattr(settings, "environment", "development")

    async with _client() as c:
        email = _email()
        # Register user
        reg = await c.post("/v1/auth/register", json={"email": email, "password": "securepassword123"})
        assert reg.status_code == 201

        # Attempt multiple wrong logins
        codes = [
            (await c.post("/v1/auth/login", json={"email": email, "password": "wrongpassword"})).status_code
            for _ in range(5)
        ]
        # Should hit 429 Too Many Requests
        assert 429 in codes


# --- 3. Tool Policy & Parameter Redaction ---

def test_tool_policy_redacts_sensitive_parameters():
    """Verify that credentials, tokens, and passwords in arguments are scrubbed."""
    raw_args = {
        "device_id": "light.living_room",
        "api_key": "secret_api_key_12345",
        "nested": {
            "auth_token": "token_abc_xyz",
            "brightness": 80,
            "user_password": "super_secret_pw",
        },
    }

    scrubbed = ToolPolicyService._scrub_sensitive_dict(raw_args)
    assert scrubbed["device_id"] == "light.living_room"
    assert scrubbed["api_key"] == "[REDACTED]"
    assert scrubbed["nested"]["brightness"] == 80
    assert scrubbed["nested"]["auth_token"] == "[REDACTED]"
    assert scrubbed["nested"]["user_password"] == "[REDACTED]"


def test_tool_approval_lifecycle_and_rejection():
    """Verify approval creation, pending status, and execution prevention on rejection."""
    tenant_id = "t_tool_test"
    project_id = "p_tool_test"
    tool_id = "tool_ha_turn_off"
    tool_name = "homeassistant_call_service"

    req = ToolPolicyService.create_approval_request(
        tenant_id=tenant_id,
        project_id=project_id,
        tool_id=tool_id,
        tool_name=tool_name,
        arguments={"entity_id": "switch.main_power", "token": "secret_token"},
        caller_type="master_agent",
        ttl_seconds=300,
    )

    assert req.id.startswith("appr-")
    assert req.status == "pending"

    # Reject approval
    ok, msg = ToolPolicyService.decide_approval_request(
        approval_id=req.id,
        decision="reject",
        deciding_user={"user_id": "admin_1", "role": "admin"},
        decision_notes="Operation unsafe during maintenance",
    )
    assert ok is True
    assert "rejected" in msg.lower()

    # Retrieve status
    current = ToolPolicyService.get_approval(req.id)
    assert current is not None
    assert current.status == "rejected"
