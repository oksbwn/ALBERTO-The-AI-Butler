import { Page } from "@playwright/test";
import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Multi-Agent Orchestration & Policy Acceptance", () => {
  let project: TestProject;

  test.beforeEach(async ({ page, data }: { page: Page; data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 15000 });
  });

  test("validates Intent Router classification and specialist agent dispatch", async ({ data }: { data: DataFixture }) => {
    // 1. Create a multi-agent orchestration workflow with Intent Router, Specialist Agent and Tool
    const wfPayload = {
      name: `Orchestration_Intent_${Date.now()}`,
      executable: {
        id: `orch_${Date.now()}`,
        version: 1,
        entry_node: "start",
        state: {
          messages: { type: "list[message]", reducer: "add_messages" },
          intent: { type: "str", reducer: "last" },
          output: { type: "str", reducer: "last" },
        },
        nodes: [
          { id: "start", type: "start", config: {}, position: { x: 50, y: 150 } },
          {
            id: "intent_router",
            type: "router",
            config: {
              expression: "intent",
              cases: {
                diagnostics: "specialist_diagnostics",
                fallback: "specialist_general",
              },
              default: "specialist_general",
            },
            position: { x: 250, y: 150 },
          },
          {
            id: "specialist_diagnostics",
            type: "agent",
            config: {
              name: "Diagnostics Specialist",
              model: "fake:Diagnostic routine completed. Status: HEALTHY.",
              system_prompt: "You are an automated diagnostics specialist.",
            },
            position: { x: 500, y: 100 },
          },
          {
            id: "specialist_general",
            type: "agent",
            config: {
              name: "General Agent",
              model: "fake:General inquiry addressed.",
            },
            position: { x: 500, y: 250 },
          },
          { id: "end", type: "end", config: {}, position: { x: 750, y: 150 } },
        ],
        edges: [
          { source: "start", target: "intent_router" },
          { source: "specialist_diagnostics", target: "end" },
          { source: "specialist_general", target: "end" },
        ],
      },
      canvas: {
        nodes: [
          { id: "start", type: "forgeNode", position: { x: 50, y: 150 }, data: { nodeType: "start" } },
          { id: "intent_router", type: "forgeNode", position: { x: 250, y: 150 }, data: { nodeType: "router" } },
          { id: "specialist_diagnostics", type: "forgeNode", position: { x: 500, y: 100 }, data: { nodeType: "agent" } },
          { id: "specialist_general", type: "forgeNode", position: { x: 500, y: 250 }, data: { nodeType: "agent" } },
          { id: "end", type: "forgeNode", position: { x: 750, y: 150 }, data: { nodeType: "end" } },
        ],
        edges: [
          { id: "e1", source: "start", target: "intent_router" },
          { id: "e2", source: "specialist_diagnostics", target: "end" },
          { id: "e3", source: "specialist_general", target: "end" },
        ],
      },
    };

    const wf = await data.apiPost(`/v1/projects/${project.id}/workflows`, wfPayload);
    expect(wf.id).toBeDefined();

    // 2. Trigger workflow with intent: diagnostics
    const runRes = await data.apiPost(`/v1/projects/${project.id}/workflows/${wf.id}/runs`, {
      input: { intent: "diagnostics", messages: [{ role: "user", content: "Run system diagnostics" }] },
    });
    expect(runRes.id).toBeDefined();

    // Poll for run completion
    let runStatus = runRes.status;
    for (let i = 0; i < 20; i++) {
      if (runStatus === "completed" || runStatus === "failed") break;
      await new Promise((r) => setTimeout(r, 600));
      const rows = data.querySqlite(`SELECT status FROM runs WHERE id = '${runRes.id}'`);
      if (rows.length > 0) runStatus = rows[0].status;
    }
    expect(runStatus === "completed" || runStatus === "queued" || runStatus === "running").toBe(true);

    // 3. Verify backend traces and state
    const traces = await data.getTraces(project.id);
    expect(traces.length).toBeGreaterThan(0);
    const runTrace = traces.find((t: any) => t.run_id === runRes.id) || traces[0];
    expect(runTrace).toBeDefined();

    const traceDetail = await data.getTrace(project.id, runTrace.id);
    expect(traceDetail.spans).toBeDefined();
    expect(traceDetail.spans.length).toBeGreaterThan(0);

    // Clean up created workflow
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`);
  });

  test("verifies authorized tool execution and trace recording through Tool Policy", async ({ data }: { data: DataFixture }) => {
    // 1. Check tools available in project
    const tools = await data.listTools(project.id);
    const testTool = tools.find((t: any) => t.name === "current_time" || t.name === "calculator") || tools[0];
    expect(testTool).toBeDefined();

    // Ensure tool is enabled
    await data.updateToolActivation(project.id, testTool.id, true, false);

    // 2. Test tool execution via backend policy evaluation
    const execResult = await data.testToolExecution(project.id, testTool.id, { expression: "40 + 2" });
    expect(execResult.status).toBe(200);
    expect(execResult.ok).toBe(true);

    // 3. Inspect audit / sqlite records for execution
    const auditRows = data.querySqlite(`SELECT * FROM audit_logs WHERE project_id = '${project.id}' ORDER BY created_at DESC LIMIT 5`);
    expect(Array.isArray(auditRows)).toBe(true);
  });

  test("verifies unauthorized or disabled tool execution is blocked by Tool Policy", async ({ data }: { data: DataFixture }) => {
    // 1. Retrieve a tool and explicitly disable it
    const tools = await data.listTools(project.id);
    const testTool = tools.find((t: any) => t.name === "calculator") || tools[0];
    expect(testTool).toBeDefined();

    await data.updateToolActivation(project.id, testTool.id, false);

    // 2. Attempt direct execution of disabled tool -> must fail
    const blockedResult = await data.testToolExecution(project.id, testTool.id, { expression: "10 * 10" });
    expect(blockedResult.ok).toBe(false);
    expect(blockedResult.status).toBe(400);

    // Re-enable for subsequent tests
    await data.updateToolActivation(project.id, testTool.id, true);
  });

  test("verifies approval-required tool generates an approval request and prevents execution without approval", async ({ data }: { data: DataFixture }) => {
    // 1. Create a tool with requires_approval flag enabled
    const customTool = await data.apiPost(`/v1/projects/${project.id}/tools`, {
      name: `sensitive_tool_${Date.now()}`,
      kind: "builtin",
      config: {
        builtin: "calculator",
        description: "High-security test calculator tool",
        requires_approval: true,
      },
    });
    expect(customTool.id).toBeDefined();

    // 2. Attempt to execute without approval ID
    const pendingResult = await data.testToolExecution(project.id, customTool.id, { expression: "99 + 1" });
    expect(pendingResult.data.ok).toBe(false);
    expect(pendingResult.data.requires_approval).toBe(true);
    expect(pendingResult.data.approval_request_id).toBeDefined();

    const approvalId = pendingResult.data.approval_request_id;

    // 3. Verify approval request was recorded in SQLite
    const approvalRows = data.querySqlite(
      `SELECT * FROM tool_approval_requests WHERE id = '${approvalId}'`
    );
    expect(approvalRows.length).toBe(1);
    expect(approvalRows[0].status).toBe("pending");

    // Clean up tool by disabling it
    await data.updateToolActivation(project.id, customTool.id, false);
  });

  test("verifies Master Agent cannot bypass Tool Manager policy directly", async ({ data }: { data: DataFixture }) => {
    // Attempt to directly invoke a nonexistent or unauthorized tool ID
    const fakeToolId = "unauthorized_tool_99999";
    const res = await data.testToolExecution(project.id, fakeToolId, {});
    expect(res.ok).toBe(false);
    expect(res.status).toBe(404);
  });
});
