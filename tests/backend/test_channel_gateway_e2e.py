import pytest
import uuid
from unittest.mock import AsyncMock, patch

from alberto.channels import telegram as tg
from alberto.db.base import SessionLocal
from alberto.models import Channel, User, Agent, Workflow
from alberto.services.channel_gateway import (
    ChannelIdentityService,
    ChannelGatewayService,
    ChannelDeliveryService,
    NormalizedMessage,
    RoutingError,
)
from alberto.services.channels import ChannelService, RoutingConfigError


@pytest.mark.asyncio
async def test_scenario_a_new_channel_to_master_agent():
    """Scenario A: New Channel without Workflow -> Pair User -> Receive Message -> Master Agent -> Reply."""
    tenant_id = f"tenant-sc-a-{uuid.uuid4().hex[:6]}"
    project_id = f"proj-sc-a-{uuid.uuid4().hex[:6]}"

    async with SessionLocal() as db:
        user = User(
            tenant_id=tenant_id,
            email="owner_a@example.com",
            password_hash="hash",
            role="editor",
            status="active",
        )
        db.add(user)
        channel = await ChannelService.create(
            db,
            tenant_id,
            project_id,
            type_="telegram",
            name="Butler Channel",
            # No workflow specified -> defaults to master_agent
        )
        await db.commit()
        await db.refresh(channel)
        await db.refresh(user)

        assert channel.target_type == "master_agent"
        assert channel.routing_state == "ok"
        assert channel.workflow_id is None

        # Step 1: External sender sends message before pairing
        msg1 = NormalizedMessage(
            channel_id=channel.id,
            provider="telegram",
            external_sender_id="tg_user_42",
            external_conversation_id="tg_chat_42",
            provider_message_id=f"msg_{uuid.uuid4().hex[:8]}",
            text="Turn on kitchen lights",
            tenant_id=tenant_id,
            project_id=project_id,
            verified=True,
            display_label="User42",
        )

        # Before pairing -> gateway returns pairing_required with one-time challenge code
        with patch.object(ChannelGatewayService, "deliver", new_callable=AsyncMock) as mock_deliver:
            mock_deliver.return_value = True
            res1 = await ChannelGatewayService.accept(channel, msg1, wait=True)
            assert res1.status == "pairing_required"
            assert "one-time code" in (res1.reply or "")
            pairing_code = (res1.reply or "").rsplit(": ", 1)[-1].strip()
            assert len(pairing_code) == 9

        # Step 2: Authenticated Alberto user confirms pairing code
        identity = await ChannelIdentityService.confirm(
            db,
            tenant_id=tenant_id,
            project_id=project_id,
            channel_id=channel.id,
            code=pairing_code,
            acting_user_id=user.id,
            acting_role="editor",
        )
        assert identity.status == "verified"
        assert identity.user_id == user.id

        # Step 3: Message is sent again with paired identity -> routes to Master Agent -> delivers reply
        msg2 = NormalizedMessage(
            channel_id=channel.id,
            provider="telegram",
            external_sender_id="tg_user_42",
            external_conversation_id="tg_chat_42",
            provider_message_id=f"msg_{uuid.uuid4().hex[:8]}",
            text="Turn on kitchen lights",
            tenant_id=tenant_id,
            project_id=project_id,
            verified=True,
            display_label="User42",
        )

        with patch.object(ChannelGatewayService, "_run_assistant", new_callable=AsyncMock) as mock_asst, \
             patch.object(ChannelGatewayService, "deliver", new_callable=AsyncMock) as mock_deliver:
            mock_asst.return_value = "I have turned on the kitchen lights for you."
            mock_deliver.return_value = True

            result = await ChannelGatewayService.accept(channel, msg2, wait=True)

            assert result.status == "delivered"
            assert result.reply == "I have turned on the kitchen lights for you."
            mock_asst.assert_awaited_once()
            mock_deliver.assert_awaited_once()
            # deliver signature: (channel, msg, text)
            delivered_text = mock_deliver.call_args[0][2]
            assert "kitchen lights" in delivered_text


@pytest.mark.asyncio
async def test_scenario_b_existing_workflow_channel():
    """Scenario B: Existing Workflow Channel -> preserves workflow routing."""
    tenant_id = f"tenant-sc-b-{uuid.uuid4().hex[:6]}"
    project_id = f"proj-sc-b-{uuid.uuid4().hex[:6]}"

    async with SessionLocal() as db:
        user = User(tenant_id=tenant_id, email="owner_b@example.com", password_hash="h", role="editor", status="active")
        db.add(user)
        wf = Workflow(
            tenant_id=tenant_id, project_id=project_id, name="Security Workflow",
            canvas={}, executable={}, status="active",
        )
        db.add(wf)
        await db.commit()
        await db.refresh(wf)
        await db.refresh(user)

        channel = await ChannelService.create(
            db,
            tenant_id,
            project_id,
            type_="email",
            name="Security Email",
            workflow_id=wf.id,  # Explicit workflow binding
        )
        await db.commit()
        await db.refresh(channel)

        assert channel.target_type == "workflow"
        assert channel.target_id == wf.id
        assert channel.workflow_id == wf.id
        assert channel.routing_state == "ok"

        # Pair identity
        msg_init = NormalizedMessage(
            channel_id=channel.id, provider="email", external_sender_id="sec@example.com",
            external_conversation_id="thread-1", provider_message_id="msg-sec-0",
            text="alert", tenant_id=tenant_id, project_id=project_id, verified=True,
        )
        code = await ChannelIdentityService.issue_pairing(channel, msg_init)
        assert code is not None
        await ChannelIdentityService.confirm(
            db, tenant_id=tenant_id, project_id=project_id, channel_id=channel.id,
            code=code, acting_user_id=user.id, acting_role="editor",
        )

        # Inbound message routes to workflow
        msg = NormalizedMessage(
            channel_id=channel.id, provider="email", external_sender_id="sec@example.com",
            external_conversation_id="thread-1", provider_message_id="msg-sec-1",
            text="Security scan report", tenant_id=tenant_id, project_id=project_id, verified=True,
        )
        with patch("alberto.services.dispatch.dispatch_message", new_callable=AsyncMock) as mock_dispatch, \
             patch.object(ChannelGatewayService, "deliver", new_callable=AsyncMock) as mock_deliver:
            mock_dispatch.return_value = {"answer": "Workflow scan complete: all secure", "run_id": "run-42"}
            mock_deliver.return_value = True

            res = await ChannelGatewayService.accept(channel, msg, wait=True)
            assert res.status == "delivered"
            assert "Workflow scan complete" in (res.reply or "")
            mock_dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_scenario_c_legacy_implicit_fallback_requires_review():
    """Scenario C: Legacy channel with NULL workflow_id sets needs_review and blocks execution until confirmed."""
    tenant_id = f"tenant-sc-c-{uuid.uuid4().hex[:6]}"
    project_id = f"proj-sc-c-{uuid.uuid4().hex[:6]}"

    async with SessionLocal() as db:
        user = User(tenant_id=tenant_id, email="owner_c@example.com", password_hash="h", role="editor", status="active")
        db.add(user)

        # Simulate migrated pre-v3 record with NULL workflow_id and needs_review state
        channel = Channel(
            tenant_id=tenant_id,
            project_id=project_id,
            type="telegram",
            name="Legacy Telegram Channel",
            key=uuid.uuid4().hex,
            config={},
            workflow_id=None,
            target_type=None,
            target_id=None,
            routing_state="needs_review",  # Migration 0023 flags this
            enabled=True,
        )
        db.add(channel)
        await db.commit()
        await db.refresh(channel)

        # Resolve route must raise RoutingError because destination needs review
        with pytest.raises(RoutingError, match="has not been confirmed yet"):
            ChannelGatewayService.resolve_route(channel, "Hello")

        # Inbound message must be rejected without executing any agent or workflow
        msg = NormalizedMessage(
            channel_id=channel.id, provider="telegram", external_sender_id="user_99",
            external_conversation_id="chat_99", provider_message_id="msg-leg-1",
            text="Hi", tenant_id=tenant_id, project_id=project_id, verified=True,
        )
        # Pair identity first
        code = await ChannelIdentityService.issue_pairing(channel, msg)
        assert code is not None
        await ChannelIdentityService.confirm(
            db, tenant_id=tenant_id, project_id=project_id, channel_id=channel.id,
            code=code, acting_user_id=user.id, acting_role="editor",
        )

        with patch.object(ChannelGatewayService, "deliver", new_callable=AsyncMock) as mock_deliver:
            mock_deliver.return_value = True
            res = await ChannelGatewayService.accept(channel, msg, wait=True)
            assert res.status == "rejected"
            assert "destination has not been confirmed yet" in (res.reply or "")

        # Confirm routing explicitly as Master Agent
        updated = await ChannelService.set_routing(
            db, channel,
            target_type="master_agent", target_id=None, routes=[],
        )
        assert updated.routing_state == "ok"
        assert updated.target_type == "master_agent"

        # Now route resolves cleanly
        target_type, target_id, label, _ = ChannelGatewayService.resolve_route(updated, "Hello")
        assert target_type == "master_agent"
        assert label == "default:master_agent"


@pytest.mark.asyncio
async def test_scenario_d_revoked_external_identity_denied():
    """Scenario D: Revoked external identity is immediately denied access."""
    tenant_id = f"tenant-sc-d-{uuid.uuid4().hex[:6]}"
    project_id = f"proj-sc-d-{uuid.uuid4().hex[:6]}"

    async with SessionLocal() as db:
        user = User(tenant_id=tenant_id, email="owner_d@example.com", password_hash="h", role="editor", status="active")
        db.add(user)
        channel = await ChannelService.create(db, tenant_id, project_id, type_="telegram", name="Revoke Test Channel")
        await db.commit()
        await db.refresh(channel)
        await db.refresh(user)

        # Pair identity
        msg_init = NormalizedMessage(
            channel_id=channel.id, provider="telegram", external_sender_id="bad_actor_9",
            external_conversation_id="chat_9", provider_message_id="msg-rev-0",
            text="pair", tenant_id=tenant_id, project_id=project_id, verified=True,
        )
        code = await ChannelIdentityService.issue_pairing(channel, msg_init)
        assert code is not None
        ident = await ChannelIdentityService.confirm(
            db, tenant_id=tenant_id, project_id=project_id, channel_id=channel.id,
            code=code, acting_user_id=user.id, acting_role="editor",
        )
        assert ident.status == "verified"

        # Revoke identity
        revoked = await ChannelIdentityService.revoke(db, tenant_id=tenant_id, channel_id=channel.id, identity_id=ident.id)
        assert revoked is True

        # Next inbound message must fail closed with pairing_required (revoked users cannot execute agent commands)
        msg = NormalizedMessage(
            channel_id=channel.id, provider="telegram", external_sender_id="bad_actor_9",
            external_conversation_id="chat_9", provider_message_id="msg-rev-1",
            text="Execute admin command", tenant_id=tenant_id, project_id=project_id, verified=True,
        )
        with patch.object(ChannelGatewayService, "_run_assistant", new_callable=AsyncMock) as mock_asst, \
             patch.object(ChannelGatewayService, "deliver", new_callable=AsyncMock) as mock_deliver:
            mock_deliver.return_value = True
            res = await ChannelGatewayService.accept(channel, msg, wait=True)
            assert res.status == "pairing_required"
            # Assistant should not have been called
            mock_asst.assert_not_called()


@pytest.mark.asyncio
async def test_scenario_e_inbound_event_deduplication():
    """Scenario E: Webhook/Polling replay produces at most one authorized dispatch."""
    tenant_id = f"tenant-sc-e-{uuid.uuid4().hex[:6]}"
    project_id = f"proj-sc-e-{uuid.uuid4().hex[:6]}"

    async with SessionLocal() as db:
        user = User(tenant_id=tenant_id, email="owner_e@example.com", password_hash="h", role="editor", status="active")
        db.add(user)
        channel = await ChannelService.create(db, tenant_id, project_id, type_="telegram", name="Dedup Test Channel")
        await db.commit()
        await db.refresh(channel)
        await db.refresh(user)

        # Pair user
        msg = NormalizedMessage(
            channel_id=channel.id, provider="telegram", external_sender_id="user_e",
            external_conversation_id="chat_e", provider_message_id="idempotent_event_1",
            text="Hello once", tenant_id=tenant_id, project_id=project_id, verified=True,
        )
        code = await ChannelIdentityService.issue_pairing(channel, msg)
        assert code is not None
        await ChannelIdentityService.confirm(
            db, tenant_id=tenant_id, project_id=project_id, channel_id=channel.id,
            code=code, acting_user_id=user.id, acting_role="editor",
        )

        with patch.object(ChannelGatewayService, "_run_assistant", new_callable=AsyncMock) as mock_asst, \
             patch.object(ChannelGatewayService, "deliver", new_callable=AsyncMock) as mock_deliver:
            mock_asst.return_value = "Response 1"
            mock_deliver.return_value = True

            # First delivery
            res1 = await ChannelGatewayService.accept(channel, msg, wait=True)
            assert res1.duplicate is False
            assert res1.status in ("accepted", "delivered")
            assert mock_asst.await_count == 1

            # Second delivery with identical provider_message_id
            res2 = await ChannelGatewayService.accept(channel, msg, wait=True)
            assert res2.duplicate is True
            assert res2.status == "duplicate"
            # Assistant should NOT be invoked a second time
            assert mock_asst.await_count == 1


@pytest.mark.asyncio
async def test_scenario_f_protected_system_subagents_blocked():
    """Scenario F: Channels cannot be configured to route directly to internal management subagents."""
    tenant_id = f"tenant-sc-f-{uuid.uuid4().hex[:6]}"
    project_id = f"proj-sc-f-{uuid.uuid4().hex[:6]}"

    async with SessionLocal() as db:
        # Create an internal system subagent with system_key = "tool_manager"
        mgr = Agent(
            tenant_id=tenant_id, project_id=project_id, name="Integration Manager",
            system_key="tool_manager", config={"role": "Integration Manager"}, is_system=True,
        )
        db.add(mgr)
        # Create an allowed custom conversational agent
        custom_bot = Agent(
            tenant_id=tenant_id, project_id=project_id, name="Recipe Assistant",
            system_key=None, config={"role": "Culinary helper"}, is_system=False,
        )
        db.add(custom_bot)
        await db.commit()
        await db.refresh(mgr)
        await db.refresh(custom_bot)

        # 1. Attempting to target tool_manager directly must raise RoutingConfigError
        with pytest.raises(RoutingConfigError, match="cannot be a conversational destination"):
            await ChannelService.validate_target(db, tenant_id, project_id, "subagent", mgr.id)

        # 2. Custom conversational agent is permitted
        await ChannelService.validate_target(db, tenant_id, project_id, "subagent", custom_bot.id)

        # 3. Create channel with allowed custom subagent
        channel = await ChannelService.create(
            db, tenant_id, project_id, type_="telegram", name="Recipe Channel",
            target_type="subagent", target_id=custom_bot.id,
        )
        assert channel.target_type == "subagent"
        assert channel.target_id == custom_bot.id


@pytest.mark.asyncio
async def test_scenario_g_independent_outbound_delivery():
    """Scenario G: ChannelDeliveryService sends outbound message without requiring a workflow."""
    tenant_id = f"tenant-sc-g-{uuid.uuid4().hex[:6]}"
    project_id = f"proj-sc-g-{uuid.uuid4().hex[:6]}"

    async with SessionLocal() as db:
        user = User(tenant_id=tenant_id, email="owner_g@example.com", password_hash="h", role="admin", status="active")
        db.add(user)
        channel = await ChannelService.create(
            db, tenant_id, project_id, type_="telegram", name="Outbound Telegram Channel",
            config={"bot_token": "12345:TEST_TOKEN"},
        )
        await db.commit()
        await db.refresh(user)
        await db.refresh(channel)

        # Pair a recipient identity
        msg_init = NormalizedMessage(
            channel_id=channel.id, provider="telegram", external_sender_id="user_out_99",
            external_conversation_id="chat_out_99", provider_message_id="msg-out-0",
            text="pair", tenant_id=tenant_id, project_id=project_id, verified=True,
        )
        code = await ChannelIdentityService.issue_pairing(channel, msg_init)
        assert code is not None
        ident = await ChannelIdentityService.confirm(
            db, tenant_id=tenant_id, project_id=project_id, channel_id=channel.id,
            code=code, acting_user_id=user.id, acting_role="admin",
        )

        with patch("alberto.channels.telegram.resolve_token", new_callable=AsyncMock) as mock_resolve, \
             patch("alberto.channels.telegram.send_message", new_callable=AsyncMock) as mock_tg_send:
            mock_resolve.return_value = "12345:TEST_TOKEN"
            mock_tg_send.return_value = 1

            res = await ChannelDeliveryService.send(
                tenant_id=tenant_id,
                project_id=project_id,
                channel_id=channel.id,
                actor={"kind": "user", "user_id": user.id, "role": "admin"},
                identity_id=ident.id,
                text="Emergency notification: water leak detected!",
            )

            assert res.get("ok") is True
            mock_tg_send.assert_awaited_once_with(
                "12345:TEST_TOKEN",
                "chat_out_99",
                "Emergency notification: water leak detected!",
            )


def test_scenario_h_telegram_webhook_secret_semantics():
    """Scenario H: Telegram webhook secret uses exact secret token header comparison via hmac.compare_digest."""
    channel_key = "secret_chan_key_9988"
    secret = tg.webhook_secret(channel_key)

    # Exact match passes
    assert tg.verify_webhook_secret(secret, channel_key) is True
    # Tampered or empty values fail
    assert tg.verify_webhook_secret("tampered_token", channel_key) is False
    assert tg.verify_webhook_secret("", channel_key) is False
    assert tg.verify_webhook_secret(None, channel_key) is False


@pytest.mark.asyncio
async def test_scenario_i_conversation_context_persistence_across_turns():
    """Scenario I: Master Agent conversation context persists in SQLite and is recalled across turns."""
    from alberto.services.conversations import ConversationService
    from alberto.services.assistant import AssistantService
    from alberto.tracing.tracer import ForgeTracer

    tenant_id = f"tenant-sc-i-{uuid.uuid4().hex[:6]}"
    project_id = f"proj-sc-i-{uuid.uuid4().hex[:6]}"
    thread_id = f"thread-test-{uuid.uuid4().hex}"

    async with SessionLocal() as db:
        # Initial state: no turns for this thread
        turns_initial = await ConversationService.turns(db, tenant_id, project_id, thread_id)
        assert len(turns_initial) == 0

        # Turn 1: User introduces themselves
        tracer1 = ForgeTracer()
        tracer1._open("span-t1", None, "assistant", "chain")
        tracer1._close("span-t1")
        await AssistantService._persist_trace(
            tenant_id=tenant_id,
            project_id=project_id,
            thread_id=thread_id,
            tracer=tracer1,
            user_message="My name is Alice and I live in Seattle.",
            ai_response="Hello Alice! How can I help you today in Seattle?",
            token_metrics={"total_tokens": 25},
            retrieval_meta={},
            error=None,
            status="done",
            persona=None,
        )

        # Verify Turn 1 is persisted in SQLite
        turns_after_t1 = await ConversationService.turns(db, tenant_id, project_id, thread_id)
        assert len(turns_after_t1) == 1
        assert turns_after_t1[0].user_message == "My name is Alice and I live in Seattle."
        assert turns_after_t1[0].ai_response == "Hello Alice! How can I help you today in Seattle?"

        # Turn 2: User asks a follow up
        tracer2 = ForgeTracer()
        tracer2._open("span-t2", None, "assistant", "chain")
        tracer2._close("span-t2")
        await AssistantService._persist_trace(
            tenant_id=tenant_id,
            project_id=project_id,
            thread_id=thread_id,
            tracer=tracer2,
            user_message="What is my name and city?",
            ai_response="Your name is Alice and you live in Seattle.",
            token_metrics={"total_tokens": 30},
            retrieval_meta={},
            error=None,
            status="done",
            persona=None,
        )

        # Verify both turns are persisted in order
        turns_after_t2 = await ConversationService.turns(db, tenant_id, project_id, thread_id)
        assert len(turns_after_t2) == 2
        assert turns_after_t2[0].user_message == "My name is Alice and I live in Seattle."
        assert turns_after_t2[1].user_message == "What is my name and city?"


def test_scenario_j_cross_user_and_cross_channel_thread_isolation():
    """Scenario J: Different users and different channels derive strictly isolated thread IDs."""
    from alberto.services.channel_gateway import conversation_thread_id

    ch1 = Channel(id="chan-001", tenant_id="tenant-1", project_id="proj-1")
    ch2 = Channel(id="chan-002", tenant_id="tenant-1", project_id="proj-1")

    msg_alice = NormalizedMessage(
        channel_id=ch1.id, provider="telegram", external_sender_id="user_alice",
        external_conversation_id="chat_alice", provider_message_id="m1",
        text="hi", tenant_id="tenant-1", project_id="proj-1", verified=True,
    )
    msg_bob = NormalizedMessage(
        channel_id=ch1.id, provider="telegram", external_sender_id="user_bob",
        external_conversation_id="chat_bob", provider_message_id="m2",
        text="hi", tenant_id="tenant-1", project_id="proj-1", verified=True,
    )

    t_alice_ch1 = conversation_thread_id(ch1, msg_alice, epoch=0)
    t_bob_ch1 = conversation_thread_id(ch1, msg_bob, epoch=0)
    t_alice_ch2 = conversation_thread_id(ch2, msg_alice, epoch=0)
    t_alice_reset = conversation_thread_id(ch1, msg_alice, epoch=1)

    # Cross-user isolation on same channel
    assert t_alice_ch1 != t_bob_ch1
    # Cross-channel isolation for same sender id
    assert t_alice_ch1 != t_alice_ch2
    # Epoch reset isolation (/reset command)
    assert t_alice_ch1 != t_alice_reset


@pytest.mark.asyncio
async def test_scenario_k_email_sender_spoofing_protection():
    """Scenario K: Email parser prioritizes authenticated envelope sender and gateway quarantines unverified transport."""
    from alberto.channels import email as email_ch
    from alberto.services.channel_gateway import ChannelGatewayService

    # 1. Attacker attempts to forge From header while envelope sender is attacker@evil.com
    spoofed_payload = {
        "sender": "attacker@evil.com",
        "from": "CEO <ceo@corporate.com>",
        "subject": "Wire Transfer Approval",
        "body-plain": "Please wire funds immediately.",
    }
    parsed = email_ch.parse_inbound(spoofed_payload)
    # The effective sender identity MUST be the authenticated envelope sender, NOT the forged From header
    assert parsed["from_addr"] == "attacker@evil.com"
    assert parsed["from_name"] == "CEO"

    # 2. Inbound unverified transport is quarantined: no agent or workflow execution
    tenant_id = f"tenant-sc-k-{uuid.uuid4().hex[:6]}"
    project_id = f"proj-sc-k-{uuid.uuid4().hex[:6]}"

    async with SessionLocal() as db:
        ch = await ChannelService.create(db, tenant_id, project_id, type_="email", name="Test Quarantine Email")
        await db.commit()
        await db.refresh(ch)

        unverified_msg = NormalizedMessage(
            channel_id=ch.id, provider="email", external_sender_id="spoofer@evil.com",
            external_conversation_id="thread-spoofer", provider_message_id="spoofer-msg-1",
            text="Malicious payload", tenant_id=tenant_id, project_id=project_id,
            verified=False,  # Unverified webhook transport
        )

        with patch.object(ChannelGatewayService, "_run_assistant", new_callable=AsyncMock) as mock_asst:
            res = await ChannelGatewayService.accept(ch, unverified_msg, wait=True)
            assert res.status == "quarantined"
            # Assistant must never be invoked on quarantined transport
            mock_asst.assert_not_called()

