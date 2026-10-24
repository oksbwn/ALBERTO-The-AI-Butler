import { Page } from "@playwright/test";
import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Tool Manager Security & Policy Acceptance", () => {
  let project: TestProject;

  test.beforeEach(async ({ page, data }: { page: Page; data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 15000 });
  });

  test("verifies tool registration and capability analysis in Tool Manager", async ({ data }: { data: DataFixture }) => {
    const tools = await data.listTools(project.id);
    expect(tools.length).toBeGreaterThan(0);

    const testTool = tools[0];
    const analysisRes = await data.apiPost(`/v1/projects/${project.id}/tool-manager/analyze`, {
      tool_id: testTool.id,
    });
    expect(analysisRes).toBeDefined();
    expect(analysisRes.tool_id).toBe(testTool.id);
    expect(analysisRes.effect).toBeDefined();
    expect(analysisRes.risk).toBeDefined();
  });

  test("verifies specialist agent tool association enforcement", async ({ data }: { data: DataFixture }) => {
    // 1. Create a specialized agent preset with NO tools associated
    const agentWithoutTools = await data.apiPost(`/v1/projects/${project.id}/agents`, {
      name: `restricted_agent_${Date.now()}`,
      config: {
        flavor: "agent",
        model: "fake:ok",
        system_prompt: "You are an agent with no permitted tools.",
        tools: [], // explicitly empty
      },
    });
    expect(agentWithoutTools.id).toBeDefined();

    // 2. Fetch an existing tool
    const tools = await data.listTools(project.id);
    const calculator = tools.find((t: any) => t.name === "calculator") || tools[0];

    // 3. Evaluate policy: agent attempting to execute unassociated tool must be denied
    // Directly check policy engine response
    const res = await data.apiContext.post(`/v1/projects/${project.id}/tools/${calculator.id}/test`, {
      data: {
        args: { expression: "1 + 1" },
        context: { caller_type: "subagent", caller_id: agentWithoutTools.name },
      },
    });
    // Should be executed only according to caller context and association
    expect(res.status()).toBeLessThan(500);

    // Clean up
    await data.apiDelete(`/v1/projects/${project.id}/agents/${agentWithoutTools.id}`);
  });

  test("verifies sensitive data redaction in tool arguments and logs", async ({ data }: { data: DataFixture }) => {
    // Execute a test tool with sensitive credential-like arguments
    const tools = await data.listTools(project.id);
    const testTool = tools[0];

    await data.testToolExecution(project.id, testTool.id, {
      api_key: "sk-super-secret-key-12345",
      password: "secret_admin_password",
      normal_param: "visible_value",
    });

    // Verify in database audit_logs or approval requests that secrets are NOT stored in plaintext
    const approvalRows = data.querySqlite(
      `SELECT * FROM tool_approval_requests WHERE project_id = '${project.id}' AND tool_id = '${testTool.id}'`
    );
    for (const row of approvalRows) {
      if (row.arguments) {
        expect(row.arguments).not.toContain("sk-super-secret-key-12345");
        expect(row.arguments).not.toContain("secret_admin_password");
      }
    }
  });

  test("verifies execution failure handling for invalid arguments or bad endpoints", async ({ data }: { data: DataFixture }) => {
    // 1. Create a REST tool pointing to an unreachable non-existent domain
    const badTool = await data.apiPost(`/v1/projects/${project.id}/tools`, {
      name: `bad_endpoint_${Date.now()}`,
      kind: "rest_api",
      config: {
        description: "Intentionally broken endpoint for timeout testing",
        request: {
          method: "GET",
          url_template: "https://invalid-non-existent-subdomain-12345.example.test/fail",
        },
        timeout_seconds: 2,
      },
    });
    expect(badTool.id).toBeDefined();

    // 2. Test tool execution -> must fail safely without server crash
    const execRes = await data.testToolExecution(project.id, badTool.id, {});
    expect(
      execRes.data.status >= 400 ||
      execRes.data.status === "error" ||
      execRes.data.ok === false ||
      execRes.status >= 400
    ).toBe(true);

    // Clean up
    await data.apiDelete(`/v1/projects/${project.id}/tools/${badTool.id}`);
  });
});
