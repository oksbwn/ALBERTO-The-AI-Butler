import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Phase 3: Practical Scheduled Butler Automations", () => {
  let project: TestProject;

  test.beforeEach(async ({ data }: { data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
  });

  test("1. Daily morning briefing automation: scheduled dispatch produces structured briefing run", async ({ data }: { data: DataFixture }) => {
    // 1. Create a morning briefing workflow
    const wf = await data.createDeterministicWorkflow(project.id, `Morning_Briefing_${Date.now()}`);
    const pastTimeIso = new Date(Date.now() - 10000).toISOString();
    const nowIso = new Date().toISOString();
    const trigId = `trig_brief_${Date.now()}`;

    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    // 2. Configure embedded trigger with due schedule
    data.querySqlite(`
      INSERT INTO triggers (id, tenant_id, project_id, workflow_id, node_id, kind, config, enabled, status, metadata, scope, created_at, updated_at)
      VALUES ('${trigId}', '${tenantId}', '${project.id}', '${wf.id}', 'start_node', 'schedule', '{"run_at": "${pastTimeIso}", "briefing_type": "morning_summary"}', 1, 'active', '{}', 'project', '${nowIso}', '${nowIso}')
    `);

    // 3. Trigger due schedule evaluation
    const fired = await data.triggerDueSchedules();
    expect(fired).toBeGreaterThanOrEqual(1);

    // 4. Verify LangGraph execution record was produced
    const runs = data.querySqlite(
      `SELECT * FROM runs WHERE workflow_id = '${wf.id}' AND source = 'schedule' ORDER BY created_at DESC LIMIT 1`
    );
    expect(runs.length).toBe(1);
    expect(["completed", "running", "queued"]).toContain(runs[0].status);

    // 5. Verify trigger claimed: enabled set to 0 and last_fired_at stamped
    const updatedTrig = data.querySqlite(`SELECT * FROM triggers WHERE id = '${trigId}'`);
    expect(updatedTrig[0].enabled).toBe(0);
    expect(updatedTrig[0].last_fired_at).not.toBeNull();

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`);
  });

  test("2. Periodic integration health check automation with duplicate prevention", async ({ data }: { data: DataFixture }) => {
    const wf = await data.createDeterministicWorkflow(project.id, `Health_Check_${Date.now()}`);
    const pastTimeIso = new Date(Date.now() - 15000).toISOString();
    const nowIso = new Date().toISOString();
    const trigId = `trig_health_${Date.now()}`;

    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    data.querySqlite(`
      INSERT INTO triggers (id, tenant_id, project_id, workflow_id, node_id, kind, config, enabled, status, metadata, scope, created_at, updated_at)
      VALUES ('${trigId}', '${tenantId}', '${project.id}', '${wf.id}', 'start_node', 'schedule', '{"run_at": "${pastTimeIso}", "check": "integrations"}', 1, 'active', '{}', 'project', '${nowIso}', '${nowIso}')
    `);

    // First evaluation: must execute
    const firstFired = await data.triggerDueSchedules();
    expect(firstFired).toBeGreaterThanOrEqual(1);

    // Immediate second evaluation: must not duplicate
    const secondFired = await data.triggerDueSchedules();
    expect(secondFired).toBe(0);

    const totalRuns = data.querySqlite(`SELECT * FROM runs WHERE workflow_id = '${wf.id}' AND source = 'schedule'`);
    expect(totalRuns.length).toBe(1);

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`);
  });

  test("3. Pending schedule recovery on application restart", async ({ data }: { data: DataFixture }) => {
    const wf = await data.createDeterministicWorkflow(project.id, `Restart_Recovery_${Date.now()}`);
    const pastTimeIso = new Date(Date.now() - 30000).toISOString();
    const nowIso = new Date().toISOString();
    const trigId = `trig_rest_${Date.now()}`;

    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    data.querySqlite(`
      INSERT INTO triggers (id, tenant_id, project_id, workflow_id, node_id, kind, config, enabled, status, metadata, scope, created_at, updated_at)
      VALUES ('${trigId}', '${tenantId}', '${project.id}', '${wf.id}', 'start_node', 'schedule', '{"run_at": "${pastTimeIso}"}', 1, 'active', '{}', 'project', '${nowIso}', '${nowIso}')
    `);

    // Simulate recovery sweep during restart
    const recoveredFired = await data.triggerDueSchedules();
    expect(recoveredFired).toBeGreaterThanOrEqual(1);

    const recoveredRuns = data.querySqlite(`SELECT * FROM runs WHERE workflow_id = '${wf.id}' AND source = 'schedule'`);
    expect(recoveredRuns.length).toBe(1);

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`);
  });
});
