import pytest
import hmac
import hashlib
import time
from unittest.mock import AsyncMock, patch

from alberto.channels import telegram as tg
from alberto.channels import email as email_ch
from alberto.db.base import SessionLocal
from alberto.models import Channel, User
from alberto.services.channel_gateway import (
    ChannelIdentityService,
    ChannelGatewayService,
    NormalizedMessage,
)


def test_telegram_adapter_update_parsing():
    """Verify Telegram update payload parsing into normalized dict."""
    payload = {
        "update_id": 998877,
        "message": {
            "message_id": 12345,
            "from": {
                "id": 987654321,
                "first_name": "Alice",
                "last_name": "Smith",
                "username": "alicesmith",
                "is_bot": False,
            },
            "chat": {
                "id": 987654321,
                "type": "private",
            },
            "date": 1700000000,
            "text": "Hello Butler, turn on the lights",
        },
    }

    parsed = tg.parse_update(payload)
    assert parsed is not None
    assert parsed["message_id"] == 12345
    assert parsed["user_id"] == "987654321"
    assert parsed["label"] == "Alice Smith"
    assert parsed["text"] == "Hello Butler, turn on the lights"

    # Bot-to-bot messages are ignored
    bot_payload = {
        "update_id": 998878,
        "message": {
            "message_id": 12346,
            "from": {"id": 111, "is_bot": True},
            "chat": {"id": 222, "type": "private"},
            "text": "ping",
        },
    }
    assert tg.parse_update(bot_payload) is None


def test_telegram_adapter_webhook_secret_verification():
    """Verify Telegram HMAC-SHA256 secret token derivation and verification."""
    channel_key = "chan-key-xyz-123"
    secret = tg.webhook_secret(channel_key)
    assert tg.verify_webhook_secret(secret, channel_key) is True
    assert tg.verify_webhook_secret("bad-secret", channel_key) is False
    assert tg.verify_webhook_secret(None, channel_key) is False


def test_email_adapter_parsing_and_verification():
    """Verify inbound email parsing and signature verification."""
    payload = {
        "Message-Id": "<msg-001@mail.example.com>",
        "sender": "bob@example.com",
        "from": "Bob Jones <bob@example.com>",
        "subject": "System Status Query",
        "body-plain": "Can you provide the morning report?",
    }
    parsed = email_ch.parse_inbound(payload)
    assert parsed["message_id"] == "<msg-001@mail.example.com>"
    assert parsed["from_addr"] == "bob@example.com"
    assert parsed["from_name"] == "Bob Jones"
    assert parsed["subject"] == "System Status Query"
    assert parsed["text"] == "Can you provide the morning report?"

    text = email_ch.build_input_text(parsed, include_subject=True)
    assert "Subject: System Status Query" in text
    assert "Can you provide the morning report?" in text

    # Verify shared secret (X-Alberto-Webhook-Secret)
    headers = {"x-alberto-webhook-secret": "secret-token-xyz"}
    verified, method, _ = email_ch.verify_inbound(
        secret="secret-token-xyz",
        verification={"provider": "shared_secret"},
        headers=headers,
        payload=payload,
    )
    assert verified is True
    assert method == "shared_secret"

    # Verify Mailgun HMAC signature
    api_key = "mailgun-signing-key"
    token = "token-12345"
    now_ts = str(int(time.time()))
    signature = hmac.new(api_key.encode(), f"{now_ts}{token}".encode(), hashlib.sha256).hexdigest()
    mailgun_payload = {
        **payload,
        "signature": {
            "token": token,
            "timestamp": now_ts,
            "signature": signature,
        },
    }
    v_mg, m_mg, _ = email_ch.verify_inbound(
        secret=api_key,
        verification={"provider": "mailgun"},
        headers={},
        payload=mailgun_payload,
    )
    assert v_mg is True
    assert m_mg == "mailgun"


@pytest.mark.asyncio
async def test_channel_identity_pairing_lifecycle():
    """Test one-time pairing challenge issuance, atomic consumption, and revocation."""
    tenant_id = "tenant-pair-test"
    project_id = "proj-pair-test"

    async with SessionLocal() as db_session:
        user = User(
            tenant_id=tenant_id,
            email="owner@example.com",
            password_hash="pw_hash",
            role="editor",
            status="active",
        )
        db_session.add(user)

        channel = Channel(
            tenant_id=tenant_id,
            project_id=project_id,
            type="telegram",
            name="Telegram Butler",
            config={},
            target_type="master_agent",
            enabled=True,
        )
        db_session.add(channel)
        await db_session.commit()
        await db_session.refresh(user)
        await db_session.refresh(channel)

        msg = NormalizedMessage(
            channel_id=channel.id,
            provider="telegram",
            external_sender_id="998877",
            external_conversation_id="998877",
            provider_message_id="msg_001",
            text="Hello",
            tenant_id=tenant_id,
            project_id=project_id,
            verified=True,
            display_label="Alice",
        )

        # 1. Issue pairing code
        code = await ChannelIdentityService.issue_pairing(channel, msg)
        assert code is not None
        assert len(code) == 9  # format: XXXX-XXXX

        # Identity starts in pending status
        ident = await ChannelIdentityService.find(db_session, channel, "998877")
        assert ident is not None
        assert ident.status == "pending"

        # 2. Confirm pairing with valid code
        confirmed = await ChannelIdentityService.confirm(
            db_session,
            tenant_id=tenant_id,
            project_id=project_id,
            channel_id=channel.id,
            code=code,
            acting_user_id=user.id,
            acting_role="editor",
        )
        assert confirmed.status == "verified"
        assert confirmed.user_id == user.id

        # 3. Second redemption of same code must fail
        with pytest.raises(ValueError, match="invalid or expired"):
            await ChannelIdentityService.confirm(
                db_session,
                tenant_id=tenant_id,
                project_id=project_id,
                channel_id=channel.id,
                code=code,
                acting_user_id=user.id,
                acting_role="editor",
            )

        # 4. Revocation
        revoked = await ChannelIdentityService.revoke(
            db_session,
            tenant_id=tenant_id,
            channel_id=channel.id,
            identity_id=confirmed.id,
        )
        assert revoked is True
        await db_session.refresh(confirmed)
        assert confirmed.status == "revoked"


@pytest.mark.asyncio
async def test_channel_gateway_deduplication_and_routing():
    """Test channel message deduplication ledger and independent routing."""
    tenant_id = "tenant-gw-test"
    project_id = "proj-gw-test"

    async with SessionLocal() as db_session:
        user = User(
            tenant_id=tenant_id,
            email="alice@example.com",
            password_hash="pw_hash",
            role="editor",
            status="active",
        )
        db_session.add(user)

        channel = Channel(
            tenant_id=tenant_id,
            project_id=project_id,
            type="telegram",
            name="Butler Bot",
            config={},
            target_type="master_agent",
            routes=[
                {"command": "/status", "target_type": "workflow", "target_id": "wf-custom-status"},
                {"command": "/expert", "target_type": "subagent", "target_id": "agent-expert"},
            ],
            enabled=True,
        )
        db_session.add(channel)
        await db_session.commit()
        await db_session.refresh(user)
        await db_session.refresh(channel)

        # Pair user
        msg_init = NormalizedMessage(
            channel_id=channel.id,
            provider="telegram",
            external_sender_id="user_123",
            external_conversation_id="chat_123",
            provider_message_id="msg_init",
            text="start",
            tenant_id=tenant_id,
            project_id=project_id,
            verified=True,
        )
        code = await ChannelIdentityService.issue_pairing(channel, msg_init)
        await ChannelIdentityService.confirm(
            db_session,
            tenant_id=tenant_id,
            project_id=project_id,
            channel_id=channel.id,
            code=code,
            acting_user_id=user.id,
            acting_role="editor",
        )

        # 1. Routing resolution checks
        t_type, t_id, r_label, _ = ChannelGatewayService.resolve_route(channel, "What is the weather?")
        assert t_type == "master_agent"
        assert r_label == "default:master_agent"

        t_type2, t_id2, r_label2, _ = ChannelGatewayService.resolve_route(channel, "/status full")
        assert t_type2 == "workflow"
        assert t_id2 == "wf-custom-status"
        assert r_label2 == "command:/status"

        # 2. Acceptance and Deduplication Ledger
        msg1 = NormalizedMessage(
            channel_id=channel.id,
            provider="telegram",
            external_sender_id="user_123",
            external_conversation_id="chat_123",
            provider_message_id="unique_msg_101",
            text="Hi Butler",
            tenant_id=tenant_id,
            project_id=project_id,
            verified=True,
        )

        with patch.object(ChannelGatewayService, "_run_assistant", new_callable=AsyncMock) as mock_asst, \
             patch.object(ChannelGatewayService, "deliver", new_callable=AsyncMock) as mock_deliver:
            mock_asst.return_value = "Hello! How can I assist you today?"
            mock_deliver.return_value = True

            res1 = await ChannelGatewayService.accept(channel, msg1, wait=True)
            assert res1.status in ("accepted", "delivered")
            assert res1.duplicate is False

            # Resending same provider_message_id -> detected as duplicate
            res1_dup = await ChannelGatewayService.accept(channel, msg1, wait=True)
            assert res1_dup.duplicate is True
            assert res1_dup.status == "duplicate"
