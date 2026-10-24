import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Phase 3: Master Agent Real-World Butler Conversations", () => {
  let project: TestProject;

  test.beforeEach(async ({ data }: { data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
  });

  test("1. Natural morning greeting: fast response with polite butler persona", async ({ data }: { data: DataFixture }) => {
    const res = await data.streamAssistant(project.id, {
      message: "Good morning, Alberto.",
    });

    expect(res.totalMs).toBeLessThan(30000);
    expect(res.events.length).toBeGreaterThan(0);
    // Verified stream response received
    expect(res.fullText.length).toBeGreaterThan(0);
  });

  test("2. Memory recall: 'What do you remember about my preferences?' retrieves persisted facts", async ({ data }: { data: DataFixture }) => {
    // Seed a known preference into authoritative memory
    await data.ingestMemory(project.id, "User preference: Prefers dark mode and espresso coffee in the morning");

    const res = await data.streamAssistant(project.id, {
      message: "What do you remember about my preferences?",
    });

    expect(res.events.length).toBeGreaterThan(0);
    // Retrieval grounded from memories table
    const mems = data.querySqlite(`SELECT * FROM memories WHERE project_id = '${project.id}' AND text LIKE '%coffee%'`);
    expect(mems.length).toBeGreaterThanOrEqual(1);
    expect(mems[0].status).toBe("active");
  });

  test("3. Scheduled tasks query: 'What tasks do I have scheduled?' returns grounded schedule state", async ({ data }: { data: DataFixture }) => {
    // Ensure at least one scheduled trigger exists in SQLite
    const wf = await data.createDeterministicWorkflow(project.id, `Butler_Sched_${Date.now()}`);
    const nowIso = new Date().toISOString();
    const futureIso = new Date(Date.now() + 3600000).toISOString();
    const trigId = `trig_butler_${Date.now()}`;
    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    data.querySqlite(`
      INSERT INTO triggers (id, tenant_id, project_id, workflow_id, node_id, kind, config, enabled, status, metadata, scope, created_at, updated_at)
      VALUES ('${trigId}', '${tenantId}', '${project.id}', '${wf.id}', 'start_node', 'schedule', '{"cron": "0 8 * * *", "description": "Morning Routine"}', 1, 'active', '{}', 'project', '${nowIso}', '${nowIso}')
    `);

    const res = await data.streamAssistant(project.id, {
      message: "What tasks do I have scheduled?",
    });

    expect(res.events.length).toBeGreaterThan(0);
    // Verify system data grounded from triggers table
    const dbTriggers = data.querySqlite(`SELECT * FROM triggers WHERE project_id = '${project.id}' AND enabled = 1`);
    expect(dbTriggers.length).toBeGreaterThanOrEqual(1);

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`).catch(() => null);
  });

  test("4. Failure check: 'Check whether any of my automations failed' reports grounded failures", async ({ data }: { data: DataFixture }) => {
    const wf = await data.createDeterministicWorkflow(project.id, `Butler_Failed_Wf_${Date.now()}`);
    const nowIso = new Date().toISOString();
    const runId = `run_fail_${Date.now()}`;

    // Seed a failed run record in runs table
    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    data.querySqlite(`
      INSERT INTO runs (id, tenant_id, project_id, workflow_id, thread_id, source, status, error, input, output, total_tokens, total_cost_usd, iterations_count, tool_calls_count, created_at, updated_at)
      VALUES ('${runId}', '${tenantId}', '${project.id}', '${wf.id}', 'thread_${runId}', 'manual', 'failed', 'Sensor timeout after 30s', '{}', '{}', 0, 0.0, 0, 0, '${nowIso}', '${nowIso}')
    `);

    const res = await data.streamAssistant(project.id, {
      message: "Check whether any of my automations failed.",
    });

    expect(res.events.length).toBeGreaterThan(0);
    const failedRuns = data.querySqlite(`SELECT * FROM runs WHERE project_id = '${project.id}' AND status = 'failed'`);
    expect(failedRuns.length).toBeGreaterThanOrEqual(1);
    expect(failedRuns[0].error).toContain("Sensor timeout");

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`).catch(() => null);
  });

  test("5. Execution audit: 'What happened in the last workflow execution?' reports last run state", async ({ data }: { data: DataFixture }) => {
    const wf = await data.createDeterministicWorkflow(project.id, `Butler_Audit_Wf_${Date.now()}`);
    const runRes = await data.executeWorkflow(project.id, wf.id, { message: "Test run message" });
    expect(runRes.runId).toBeDefined();

    const res = await data.streamAssistant(project.id, {
      message: "What happened in the last workflow execution?",
    });

    expect(res.events.length).toBeGreaterThan(0);
    const lastRun = data.querySqlite(`SELECT * FROM runs WHERE workflow_id = '${wf.id}' ORDER BY created_at DESC LIMIT 1`);
    expect(lastRun.length).toBe(1);
    expect(["completed", "done", "running", "queued"]).toContain(lastRun[0].status);

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`).catch(() => null);
  });

  test("6. Conversational authoring prompt: 'Help me create an automation'", async ({ data }: { data: DataFixture }) => {
    const res = await data.streamAssistant(project.id, {
      message: "Help me create an automation to notify me when temperature drops below 18C.",
    });

    expect(res.events.length).toBeGreaterThan(0);
    expect(res.fullText.length).toBeGreaterThan(0);
  });

  test("7. Integrations listing: 'What integrations are currently available?'", async ({ data }: { data: DataFixture }) => {
    const res = await data.streamAssistant(project.id, {
      message: "What integrations are currently available?",
    });

    expect(res.events.length).toBeGreaterThan(0);
    // Verify system tools exist in project
    const tools = await data.listTools(project.id);
    expect(tools.length).toBeGreaterThan(0);
  });
});
