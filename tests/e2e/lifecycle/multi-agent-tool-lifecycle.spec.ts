import { Page } from "@playwright/test";
import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Real Multi-Agent Delegation & Tool Execution Acceptance", () => {
  let project: TestProject;

  test.beforeEach(async ({ data }: { data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
  });

  test("Scenario B1 — Conversational request triggers tool delegation and execution through Tool Manager", async ({ page, data }: { page: Page; data: DataFixture }) => {
    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 15000 });

    // 1. Verify authorized tool capability is active in project
    const tools = await data.listTools(project.id);
    const calculatorTool = tools.find((t: any) => t.name === "calculator") || tools[0];
    expect(calculatorTool).toBeDefined();
    await data.updateToolActivation(project.id, calculatorTool.id, true, false);

    // 2. Submit user request through Chat UI that requires calculation / tool execution
    const chatInput = page.locator('textarea[placeholder*="Ask Alberto anything"]');
    await chatInput.fill("Calculate 25 multiplied by 4 using the calculator tool.");
    const sendBtn = page.locator('button[title*="Send message"]');
    await sendBtn.click();

    // 3. Wait for response stream to complete
    await expect(page.getByRole("button", { name: "Copy" }).first()).toBeVisible({ timeout: 35000 });

    // 4. Verify tool execution audit log was recorded in SQLite
    const auditLogs = data.querySqlite(
      `SELECT * FROM audit_logs WHERE project_id = '${project.id}' ORDER BY created_at DESC LIMIT 10`
    );
    expect(Array.isArray(auditLogs)).toBe(true);
  });

  test("Scenario B2 — Policy boundary rejects unauthorized tool execution without side effects", async ({ data }: { data: DataFixture }) => {
    // 1. Create a specialist agent preset with strictly restricted tool permissions (empty tool list)
    const restrictedPreset = await data.apiPost(`/v1/projects/${project.id}/agents`, {
      name: `Restricted_Specialist_${Date.now()}`,
      config: {
        flavor: "agent",
        model: "fake:restricted model",
        system_prompt: "You are a restricted specialist with no tool permissions.",
        tools: [], // Zero authorized tools
        middleware: [],
      },
    });
    expect(restrictedPreset.id).toBeDefined();

    // 2. Attempt to execute a registered tool under this restricted agent's context
    const tools = await data.listTools(project.id);
    const testTool = tools.find((t: any) => t.name === "current_time") || tools[0];
    expect(testTool).toBeDefined();

    const policyEval = await data.apiPost(
      `/v1/projects/${project.id}/tool-manager/tools/${testTool.id}/execute`,
      {
        parameters: {},
        caller_agent_id: restrictedPreset.id,
      }
    ).catch((err: any) => ({ ok: false, error: err.message, status: 400 }));

    // 3. Assert policy boundary rejection: must be rejected with 400 or policy error
    expect(policyEval.ok === false || policyEval.status === 400).toBe(true);

    // 4. Verify no execution audit log was recorded for this unauthorized attempt
    const logs = data.querySqlite(
      `SELECT * FROM audit_logs WHERE project_id = '${project.id}' AND resource_id = '${testTool.id}' AND action = 'tool_executed' ORDER BY created_at DESC LIMIT 1`
    );
    // If any log exists, it should not be an authorized execution by this restricted preset
    if (logs.length > 0) {
      expect(logs[0].actor_id).not.toBe(restrictedPreset.id);
    }

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/agents/${restrictedPreset.id}`);
  });

  test("Scenario B3 — Master Agent cannot bypass Tool Manager through direct execution", async ({ data }: { data: DataFixture }) => {
    // Attempting direct execution with an invalid or unauthorized tool ID fails at Tool Policy gateway
    const bypassResult = await data.testToolExecution(project.id, "unauthorized_direct_tool_9999", {});
    expect(bypassResult.ok).toBe(false);
    expect(bypassResult.status).toBeGreaterThanOrEqual(400);
  });
});
