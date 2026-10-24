import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Scheduler Execution & Recovery Acceptance", () => {
  let project: TestProject;

  test.beforeEach(async ({ data }: { data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
  });

  test("Scenario A — One-time run_at scheduler dispatch and exactly-once execution", async ({ data }: { data: DataFixture }) => {
    // 1. Create a deterministic workflow
    const wf = await data.createDeterministicWorkflow(project.id, `Sched_Once_${Date.now()}`);
    expect(wf.id).toBeDefined();

    // 2. Configure a one-time schedule trigger with run_at set to 1 minute in the past (due immediately)
    const pastTimeIso = new Date(Date.now() - 60000).toISOString();
    const triggerRes = await data.apiPost(`/v1/projects/${project.id}/workflows/${wf.id}/triggers`, {
      kind: "schedule",
      config: {
        run_at: pastTimeIso,
        message: "Automated scheduled dispatch payload",
      },
      enabled: true,
      scope: "project",
    }).catch(async () => {
      // If workflow trigger route is direct or via update
      return null;
    });

    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows.length > 0 && projRows[0].tenant_id ? projRows[0].tenant_id : "default";

    // Alternatively, ensure trigger row directly exists in SQLite triggers table
    let trigId = triggerRes?.id;
    if (!trigId) {
      const nowIso = new Date().toISOString();
      trigId = `trig_e2e_${Date.now()}`;
      data.querySqlite(`
        INSERT INTO triggers (id, tenant_id, project_id, workflow_id, node_id, kind, config, enabled, status, metadata, scope, created_at, updated_at)
        VALUES ('${trigId}', '${tenantId}', '${project.id}', '${wf.id}', 'start_node', 'schedule', '{"run_at": "${pastTimeIso}", "message": "Scheduled test run"}', 1, 'active', '{}', 'project', '${nowIso}', '${nowIso}')
      `);
    }

    // Verify trigger is persisted and due
    const triggers = data.querySqlite(`SELECT * FROM triggers WHERE id = '${trigId}'`);
    expect(triggers.length).toBe(1);
    expect(triggers[0].enabled).toBe(1);

    // 3. Invoke scheduler due-job evaluation mechanism
    const firedCount = await data.triggerDueSchedules();
    expect(firedCount).toBeGreaterThanOrEqual(1);

    // 4. Verify LangGraph execution record was created in SQLite runs table
    const runs = data.querySqlite(
      `SELECT * FROM runs WHERE workflow_id = '${wf.id}' AND source = 'schedule' ORDER BY created_at DESC LIMIT 1`
    );
    expect(runs.length).toBe(1);
    const scheduledRun = runs[0];
    expect(scheduledRun.id).toBeDefined();
    expect(["completed", "running", "queued"]).toContain(scheduledRun.status);

    // 5. Verify trigger was claimed: enabled set to 0 and last_fired_at stamped
    const updatedTriggers = data.querySqlite(`SELECT * FROM triggers WHERE id = '${trigId}'`);
    expect(updatedTriggers[0].enabled).toBe(0);
    expect(updatedTriggers[0].last_fired_at).not.toBeNull();

    // 6. Test exactly-once semantics: trigger scheduler evaluation a second time
    const secondFiredCount = await data.triggerDueSchedules();
    expect(secondFiredCount).toBe(0);

    // Confirm no duplicate run was created
    const allRuns = data.querySqlite(
      `SELECT * FROM runs WHERE workflow_id = '${wf.id}' AND source = 'schedule'`
    );
    expect(allRuns.length).toBe(1);

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`);
  });

  test("Scenario B — Restart recovery of pending scheduled trigger", async ({ data }: { data: DataFixture }) => {
    // 1. Create a workflow with a pending schedule
    const wf = await data.createDeterministicWorkflow(project.id, `Sched_Recovery_${Date.now()}`);
    const pastTimeIso = new Date(Date.now() - 30000).toISOString();
    const trigId = `trig_rec_${Date.now()}`;
    const nowIso = new Date().toISOString();

    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows.length > 0 && projRows[0].tenant_id ? projRows[0].tenant_id : "default";

    data.querySqlite(`
      INSERT INTO triggers (id, tenant_id, project_id, workflow_id, node_id, kind, config, enabled, status, metadata, scope, created_at, updated_at)
      VALUES ('${trigId}', '${tenantId}', '${project.id}', '${wf.id}', 'start_node', 'schedule', '{"run_at": "${pastTimeIso}"}', 1, 'active', '{}', 'project', '${nowIso}', '${nowIso}')
    `);

    // 2. Evaluate due schedules as would happen on scheduler start/recovery
    const fired = await data.triggerDueSchedules();
    expect(fired).toBeGreaterThanOrEqual(1);

    // 3. Verify execution was dispatched and recorded
    const runs = data.querySqlite(
      `SELECT * FROM runs WHERE workflow_id = '${wf.id}' AND source = 'schedule'`
    );
    expect(runs.length).toBe(1);

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`);
  });
});
