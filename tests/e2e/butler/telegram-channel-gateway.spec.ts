import crypto from "crypto";
import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Phase 3: Telegram Channel Gateway & Identity Validation", () => {
  let project: TestProject;

  test.beforeEach(async ({ data }: { data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
  });

  test("1. Credential validation: Channel creation with invalid bot token is rejected with 400", async ({ data }: { data: DataFixture }) => {
    try {
      await data.apiPost(`/v1/projects/${project.id}/channels`, {
        type: "telegram",
        name: "Invalid Telegram Bot",
        config: {
          bot_token: "123456:INVALID_TOKEN_FORMAT_XYZ",
          transport: "webhook",
        },
      });
      expect(true).toBe(false); // Should not reach here
    } catch (e: any) {
      expect(e.message).toContain("400");
    }
  });

  test("2. Webhook security boundary: Inbound POST with invalid secret token is rejected with 401", async ({ data }: { data: DataFixture }) => {
    const channelKey = `tg_key_${Date.now()}`;
    const channelId = `ch_tg_${Date.now()}`;
    const nowIso = new Date().toISOString();

    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    // Seed test telegram channel in DB
    data.querySqlite(`
      INSERT INTO channels (id, tenant_id, project_id, type, name, key, enabled, config, target_type, routing_state, routes, state, created_at, updated_at)
      VALUES ('${channelId}', '${tenantId}', '${project.id}', 'telegram', 'Test Butler Telegram', '${channelKey}', 1, '{"transport": "webhook", "bot": {"id": 12345, "username": "AlbertoButlerBot"}}', 'master_agent', 'ready', '[]', '{}', '${nowIso}', '${nowIso}')
    `);

    // Inbound webhook with wrong secret
    const webhookRes = await fetch(`http://127.0.0.1:8005/v1/channels/telegram/${channelKey}/webhook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-telegram-bot-api-secret-token": "WRONG_SECRET_TOKEN",
      },
      body: JSON.stringify({
        update_id: 10001,
        message: {
          message_id: 1,
          from: { id: 99991, is_bot: false, first_name: "Attacker" },
          chat: { id: 99991, type: "private" },
          text: "Malicious injection",
        },
      }),
    });

    expect(webhookRes.status).toBe(401);

    // Cleanup
    data.querySqlite(`DELETE FROM channels WHERE id = '${channelId}'`);
  });

  test("3. Identity pairing challenge: Unpaired sender receives one-time code without workflow access", async ({ data }: { data: DataFixture }) => {
    const channelKey = `tg_pair_${Date.now()}`;
    const channelId = `ch_pair_${Date.now()}`;
    const nowIso = new Date().toISOString();

    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    data.querySqlite(`
      INSERT INTO channels (id, tenant_id, project_id, type, name, key, enabled, config, target_type, routing_state, routes, state, created_at, updated_at)
      VALUES ('${channelId}', '${tenantId}', '${project.id}', 'telegram', 'Pairing Test TG', '${channelKey}', 1, '{"transport": "webhook", "bot": {"id": 12345, "username": "AlbertoButlerBot"}}', 'master_agent', 'ready', '[]', '{}', '${nowIso}', '${nowIso}')
    `);

    // Calculate valid HMAC secret token
    const secret = crypto.createHmac("sha256", channelKey).update("alberto-telegram-webhook").digest("hex");
    const externalSenderId = `tg_user_${Date.now()}`;
    const updateId = Math.floor(Math.random() * 1000000);

    const webhookRes = await fetch(`http://127.0.0.1:8005/v1/channels/telegram/${channelKey}/webhook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-telegram-bot-api-secret-token": secret,
      },
      body: JSON.stringify({
        update_id: updateId,
        message: {
          message_id: 1,
          from: { id: externalSenderId, is_bot: false, first_name: "NewUser" },
          chat: { id: externalSenderId, type: "private" },
          text: "Hello Alberto, turn on the lights",
        },
      }),
    });

    expect(webhookRes.status).toBe(200);

    // Verify pairing_required or delivery_failed (graceful delivery without real Telegram token) event was recorded
    let events: any[] = [];
    for (let i = 0; i < 10; i++) {
      events = data.querySqlite(
        `SELECT * FROM channel_events WHERE channel_id = '${channelId}' AND direction = 'inbound' ORDER BY created_at DESC LIMIT 1`
      );
      if (events.length > 0) break;
      await new Promise((r) => setTimeout(r, 200));
    }
    expect(events.length).toBe(1);
    expect(["pairing_required", "delivery_failed"]).toContain(events[0].status);

    // Verify pending identity was created
    const idents = data.querySqlite(
      `SELECT * FROM channel_identities WHERE channel_id = '${channelId}' AND provider_user_id = '${externalSenderId}'`
    );
    expect(idents.length).toBe(1);
    expect(idents[0].status).toBe("pending");

    // Verify pairing code was generated
    const pairings = data.querySqlite(
      `SELECT * FROM channel_pairings WHERE identity_id = '${idents[0].id}'`
    );
    expect(pairings.length).toBe(1);
    expect(pairings[0].code_hash).toBeDefined();

    // Cleanup
    data.querySqlite(`DELETE FROM channel_pairings WHERE channel_id = '${channelId}'`);
    data.querySqlite(`DELETE FROM channel_identities WHERE channel_id = '${channelId}'`);
    data.querySqlite(`DELETE FROM channel_events WHERE channel_id = '${channelId}'`);
    data.querySqlite(`DELETE FROM channels WHERE id = '${channelId}'`);
  });

  test("4. Paired user conversation: Direct routing to Master Agent without requiring a workflow", async ({ data }: { data: DataFixture }) => {
    const channelKey = `tg_paired_${Date.now()}`;
    const channelId = `ch_paired_${Date.now()}`;
    const nowIso = new Date().toISOString();
    const externalSenderId = `tg_verified_${Date.now()}`;

    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    // Get current user id
    const userRows = data.querySqlite(`SELECT id FROM users LIMIT 1`);
    const userId = userRows[0]?.id || "admin_user_id";

    // 1. Create channel in DB
    data.querySqlite(`
      INSERT INTO channels (id, tenant_id, project_id, type, name, key, enabled, config, target_type, routing_state, routes, state, created_at, updated_at)
      VALUES ('${channelId}', '${tenantId}', '${project.id}', 'telegram', 'Paired Butler TG', '${channelKey}', 1, '{"transport": "webhook", "bot": {"id": 12345, "username": "AlbertoButlerBot"}}', 'master_agent', 'ready', '[]', '{}', '${nowIso}', '${nowIso}')
    `);

    // 2. Pre-verify channel identity (simulating successful pairing code confirmation)
    const identId = `ident_${Date.now()}`;
    data.querySqlite(`
      INSERT INTO channel_identities (id, tenant_id, project_id, channel_id, provider_user_id, provider_chat_id, display_label, user_id, status, verified_at, created_at, updated_at)
      VALUES ('${identId}', '${tenantId}', '${project.id}', '${channelId}', '${externalSenderId}', '${externalSenderId}', 'Verified Owner', '${userId}', 'verified', '${nowIso}', '${nowIso}', '${nowIso}')
    `);

    // 3. Post inbound message
    const secret = crypto.createHmac("sha256", channelKey).update("alberto-telegram-webhook").digest("hex");
    const updateId = Math.floor(Math.random() * 1000000);

    const webhookRes = await fetch(`http://127.0.0.1:8005/v1/channels/telegram/${channelKey}/webhook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-telegram-bot-api-secret-token": secret,
      },
      body: JSON.stringify({
        update_id: updateId,
        message: {
          message_id: 42,
          from: { id: externalSenderId, is_bot: false, first_name: "Owner" },
          chat: { id: externalSenderId, type: "private" },
          text: "/help",
        },
      }),
    });

    expect(webhookRes.status).toBe(200);

    // 4. Verify inbound event was routed to help and delivered/processed
    let events: any[] = [];
    for (let i = 0; i < 15; i++) {
      events = data.querySqlite(
        `SELECT * FROM channel_events WHERE channel_id = '${channelId}' AND provider_event_id = 'tg-update-${updateId}'`
      );
      if (events.length > 0 && events[0].route) break;
      await new Promise((r) => setTimeout(r, 200));
    }
    expect(events.length).toBe(1);
    expect(events[0].route).toBe("help");
    expect(events[0].user_id).toBe(userId);

    // 5. Test message deduplication: send identical update_id
    const dupRes = await fetch(`http://127.0.0.1:8005/v1/channels/telegram/${channelKey}/webhook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-telegram-bot-api-secret-token": secret,
      },
      body: JSON.stringify({
        update_id: updateId,
        message: {
          message_id: 42,
          from: { id: externalSenderId, is_bot: false, first_name: "Owner" },
          chat: { id: externalSenderId, type: "private" },
          text: "/help",
        },
      }),
    });

    expect(dupRes.status).toBe(200);
    // Total events for this update_id should remain exactly 1 (deduplicated)
    const allEvents = data.querySqlite(
      `SELECT * FROM channel_events WHERE channel_id = '${channelId}' AND provider_event_id = 'tg-update-${updateId}'`
    );
    expect(allEvents.length).toBe(1);

    // Cleanup
    data.querySqlite(`DELETE FROM channel_identities WHERE channel_id = '${channelId}'`);
    data.querySqlite(`DELETE FROM channel_events WHERE channel_id = '${channelId}'`);
    data.querySqlite(`DELETE FROM channels WHERE id = '${channelId}'`);
  });

  test("5. Webhook authentication hardening: Missing header rejected and vault-stored secret verified", async ({ data }: { data: DataFixture }) => {
    const channelKey = `tg_vault_${Date.now()}`;
    const channelId = `ch_vault_${Date.now()}`;
    const nowIso = new Date().toISOString();
    const customVaultSecret = `vsec_${Date.now()}_abc123xyz`;

    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    // 1. Create secret in SecretStore via API (properly encrypted)
    const secretName = `channel-telegram-webhook-${channelKey.slice(0, 16)}`;
    await data.apiPost(`/v1/projects/${project.id}/secrets`, {
      name: secretName,
      value: customVaultSecret,
      kind: "channel",
    });

    // 2. Create channel referencing vault secret
    data.querySqlite(`
      INSERT INTO channels (id, tenant_id, project_id, type, name, key, enabled, config, target_type, routing_state, routes, state, created_at, updated_at)
      VALUES ('${channelId}', '${tenantId}', '${project.id}', 'telegram', 'Vault Webhook Bot', '${channelKey}', 1, '{"transport": "webhook", "webhook_secret_ref": "secret://${secretName}", "bot": {"id": 8888, "username": "VaultButlerBot"}}', 'master_agent', 'ready', '[]', '{}', '${nowIso}', '${nowIso}')
    `);

    // 3. Test missing secret header -> 401
    const missingRes = await fetch(`http://127.0.0.1:8005/v1/channels/telegram/${channelKey}/webhook`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ update_id: 8801, message: { text: "test" } }),
    });
    expect(missingRes.status).toBe(401);

    // 4. Test wrong secret header -> 401
    const wrongRes = await fetch(`http://127.0.0.1:8005/v1/channels/telegram/${channelKey}/webhook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-telegram-bot-api-secret-token": "not-the-vault-secret",
      },
      body: JSON.stringify({ update_id: 8802, message: { text: "test" } }),
    });
    expect(wrongRes.status).toBe(401);

    // 5. Test valid vault-stored secret -> 200
    const validRes = await fetch(`http://127.0.0.1:8005/v1/channels/telegram/${channelKey}/webhook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-telegram-bot-api-secret-token": customVaultSecret,
      },
      body: JSON.stringify({
        update_id: 8803,
        message: {
          message_id: 1,
          from: { id: "vault_sender_1", is_bot: false, first_name: "Tester" },
          chat: { id: "vault_sender_1", type: "private" },
          text: "/help",
        },
      }),
    });
    expect(validRes.status).toBe(200);

    // Cleanup
    data.querySqlite(`DELETE FROM channel_events WHERE channel_id = '${channelId}'`);
    data.querySqlite(`DELETE FROM channels WHERE id = '${channelId}'`);
    data.querySqlite(`DELETE FROM secrets WHERE name = '${secretName}'`);
  });
});

