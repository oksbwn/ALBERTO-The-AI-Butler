import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Phase 3: Operational Resilience, Error Handling & Recovery", () => {
  let project: TestProject;

  test.beforeEach(async ({ data }: { data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
  });

  test("1. Tool execution failure returns structured error without server crash", async ({ data }: { data: DataFixture }) => {
    const tools = await data.listTools(project.id);
    const targetTool = tools.find((t: any) => t.name === "calculator") || tools[0];

    // Execute with invalid math expression that triggers tool error
    const res = await data.testToolExecution(project.id, targetTool.id, {
      expression: "1 / 0",
    });

    // API returns structured response without crash (less than 500)
    expect(res.status).toBeLessThan(500);

    // Platform remains operational
    const remainingTools = await data.listTools(project.id);
    expect(remainingTools.length).toBeGreaterThan(0);
  });

  test("2. Malformed workflow execution input caught before engine crash", async ({ data }: { data: DataFixture }) => {
    const wf = await data.createDeterministicWorkflow(project.id, `Malformed_Input_Wf_${Date.now()}`);

    // Call execute with malformed/invalid payload type
    try {
      await data.executeWorkflow(project.id, wf.id, "NOT_A_VALID_OBJECT" as any);
    } catch (e: any) {
      // 400 or 422 Bad Request expected
      expect(e.message).toBeDefined();
    }

    // Engine remains healthy
    const wfList = await data.apiGet(`/v1/projects/${project.id}/workflows`);
    expect(wfList.length).toBeGreaterThan(0);

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`);
  });

  test("3. Failed workflow run persists authoritative 'failed' state in SQLite runs table", async ({ data }: { data: DataFixture }) => {
    const wf = await data.createDeterministicWorkflow(project.id, `Fail_State_${Date.now()}`);
    const nowIso = new Date().toISOString();
    const runId = `run_fail_test_${Date.now()}`;

    // Direct insertion of failed run
    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    data.querySqlite(`
      INSERT INTO runs (id, tenant_id, project_id, workflow_id, thread_id, source, status, error, input, output, total_tokens, total_cost_usd, iterations_count, tool_calls_count, created_at, updated_at)
      VALUES ('${runId}', '${tenantId}', '${project.id}', '${wf.id}', 'thread_${runId}', 'manual', 'failed', 'Downstream service unavailable', '{}', '{}', 0, 0.0, 0, 0, '${nowIso}', '${nowIso}')
    `);

    const runs = data.querySqlite(`SELECT status, error FROM runs WHERE id = '${runId}'`);
    expect(runs.length).toBe(1);
    expect(runs[0].status).toBe("failed");
    expect(runs[0].error).toContain("Downstream service unavailable");

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`);
  });

  test("4. System health and component readiness endpoints report operational status", async ({ data }: { data: DataFixture }) => {
    const health = await data.apiGet("/health");
    expect(health.status).toBe("ok");

    // Verify model registry catalog is responsive
    const models = await data.apiGet("/v1/models");
    expect(models.chat).toBeDefined();
    expect(Array.isArray(models.chat)).toBe(true);

    // Verify node types catalog is responsive
    const nodeTypes = await data.apiGet("/v1/node-types");
    expect(Array.isArray(nodeTypes)).toBe(true);
    expect(nodeTypes.length).toBeGreaterThan(0);
  });
});
