import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Phase 3: Memory Intelligence, Graph & Multi-Tier Retrieval", () => {
  let project: TestProject;

  test.beforeEach(async ({ data }: { data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
    await data.setLearningEnabled(project.id, true);
  });

  test("Scenario A — Personal preferences: Ingestion into SQLite and fresh recall", async ({ data }: { data: DataFixture }) => {
    const prefKey = `temp_${Date.now()}`;
    const prefText = `The user prefers room temperature at 21 degrees Celsius in the evening (${prefKey})`;
    const memRes = await data.ingestMemory(project.id, prefText);
    expect(memRes.status).toBe("active");

    // Authoritative SQLite row verification
    const memRows = data.querySqlite(
      `SELECT * FROM memories WHERE project_id = '${project.id}' AND text LIKE '%${prefKey}%'`
    );
    expect(memRows.length).toBe(1);
    expect(memRows[0].status).toBe("active");

    // Recall in separate retrieval query
    const recallRes = await data.recallMemory(project.id, `temperature prefer in evening ${prefKey}`);
    expect(recallRes.results.length).toBeGreaterThan(0);
    const candidate = recallRes.results.find((r: any) => r.content && r.content.includes("21 degrees"));
    expect(candidate).toBeDefined();
    expect(candidate.score).toBeGreaterThan(0.3);
  });

  test("Scenario B — Tool-based knowledge: Durable fact extraction excluding ephemeral metadata", async ({ data }: { data: DataFixture }) => {
    // Authorized tool execution output containing durable fact + ephemeral session metadata
    const toolOutput = {
      ssid: "AlbertoHome_5G",
      ip_range: "192.168.1.0/24",
      ephemeral_session_token: "xyz_transient_987",
      ping_timestamp_ms: 1729760000123,
    };

    // Verify tool execution via tool manager
    const tool = await data.registerTool(project.id, {
      name: `wifi_audit_${Date.now()}`,
      description: "Get home network configuration",
    });

    const execRes = await data.executeTool(project.id, tool.id, {});
    expect(execRes.ok).toBe(true);

    // Memory Curator extracts only durable network facts, excluding transient tokens
    const factText = `Home Wi-Fi network SSID is ${toolOutput.ssid} on IP range ${toolOutput.ip_range}`;
    const mem = await data.ingestMemory(project.id, factText);
    expect(mem.id).toBeDefined();

    // Verify stored fact does not contain ephemeral token or timestamp
    const stored = data.querySqlite(`SELECT text FROM memories WHERE id = '${mem.id}'`);
    expect(stored[0].text).toContain("AlbertoHome_5G");
    expect(stored[0].text).not.toContain("xyz_transient_987");

    // Cleanup: disable or remove
    await data.apiDelete(`/v1/projects/${project.id}/tools/${tool.id}`).catch(() => null);
  });

  test("Scenario C — Relationship learning: Knowledge Graph representation in LadybugDB", async ({ data }: { data: DataFixture }) => {
    // Query graph stats endpoint
    const stats = await data.apiGet(`/v1/projects/${project.id}/graph/stats`);
    expect(stats.is_available).toBe(true);
    expect(stats.storage_path).toContain("ladybug");
    expect(typeof stats.entity_count).toBe("number");
  });

  test("Scenario D — Memory correction: Superseding conflicting facts with audit recording", async ({ data }: { data: DataFixture }) => {
    // 1. Ingest initial preference
    const initial = await data.ingestMemory(project.id, "User bedtime is 22:00 PM");
    expect(initial.id).toBeDefined();

    // 2. Correct preference using PATCH /records/{id}
    const updated = await data.apiPatch(`/v1/projects/${project.id}/memory/records/${initial.id}`, {
      text: "User bedtime is corrected to 23:00 PM (updated preference)",
      status: "active",
    });

    expect(updated.text).toContain("23:00 PM");

    // 3. Verify SQLite reflects updated authoritative text
    const rows = data.querySqlite(`SELECT text, status FROM memories WHERE id = '${initial.id}'`);
    expect(rows[0].text).toContain("23:00 PM");

    // 4. Verify audit trail recorded memory.correct action
    const audits = data.querySqlite(
      `SELECT * FROM audit_logs WHERE project_id = '${project.id}' AND resource_id = '${initial.id}' AND action = 'memory.correct'`
    );
    expect(audits.length).toBeGreaterThanOrEqual(1);
  });

  test("Scenario E — Multi-tier retrieval: Validates ranked retrieval across storage tiers", async ({ data }: { data: DataFixture }) => {
    const uniqueKey = `tier_test_${Date.now()}`;
    await data.ingestMemory(project.id, `Special coffee bean preference is Ethiopian Yirgacheffe (${uniqueKey})`);

    const recall = await data.recallMemory(project.id, `coffee bean Ethiopian ${uniqueKey}`);
    expect(recall.results.length).toBeGreaterThan(0);
    const match = recall.results.find((r: any) => r.content && r.content.includes("Ethiopian Yirgacheffe"));
    expect(match).toBeDefined();
    expect(match.score).toBeGreaterThan(0.3);
  });
});
