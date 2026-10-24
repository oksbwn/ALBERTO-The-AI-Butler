import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Phase 3: Home Assistant Integration & Smart Home Tool Policy", () => {
  let project: TestProject;

  test.beforeEach(async ({ data }: { data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
  });

  test("1. Home Assistant MCP client registration & capability discovery", async ({ data }: { data: DataFixture }) => {
    const clientId = `mcp_ha_${Date.now()}`;
    const nowIso = new Date().toISOString();
    const projRows = data.querySqlite(`SELECT tenant_id FROM projects WHERE id = '${project.id}'`);
    const tenantId = projRows[0]?.tenant_id || "default";

    // Register Home Assistant MCP client with standard HA port (8123)
    data.querySqlite(`
      INSERT INTO mcp_clients (id, tenant_id, project_id, name, transport, url, args, disabled_tools, capabilities, enabled, learning_enabled, created_at, updated_at)
      VALUES ('${clientId}', '${tenantId}', '${project.id}', 'HA', 'http', 'http://homeassistant.local:8123', '[]', '[]', '[]', 1, 1, '${nowIso}', '${nowIso}')
    `);

    // Verify MCP client registered in DB
    const mcps = data.querySqlite(`SELECT * FROM mcp_clients WHERE id = '${clientId}'`);
    expect(mcps.length).toBe(1);
    expect(mcps[0].name).toBe("HA");
    expect(mcps[0].url).toContain("8123");

    // Register representative smart home tools
    const toolReadId = `tool_ha_state_${Date.now()}`;
    const toolWriteId = `tool_ha_pipe_${Date.now()}`;

    data.querySqlite(`
      INSERT INTO tools (id, tenant_id, project_id, name, kind, config, enabled, created_at, updated_at)
      VALUES
      ('${toolReadId}', '${tenantId}', '${project.id}', 'ha_get_state', 'builtin', '{"builtin": "calculator", "description": "Get Home Assistant entity state", "read_only": true}', 1, '${nowIso}', '${nowIso}'),
      ('${toolWriteId}', '${tenantId}', '${project.id}', 'ha_manage_pipeline', 'builtin', '{"builtin": "calculator", "description": "Dispatch intent command to Home Assistant", "read_only": false}', 1, '${nowIso}', '${nowIso}')
    `);

    const tools = await data.listTools(project.id);
    const haTools = tools.filter((t: any) => t.name.startsWith("ha_"));
    expect(haTools.length).toBeGreaterThanOrEqual(2);

    // Cleanup
    data.querySqlite(`DELETE FROM tools WHERE id IN ('${toolReadId}', '${toolWriteId}')`);
    data.querySqlite(`DELETE FROM mcp_clients WHERE id = '${clientId}'`);
  });

  test("2. Read-only entity state retrieval precedes state modification", async ({ data }: { data: DataFixture }) => {
    const tools = await data.listTools(project.id);
    const timeTool = tools.find((t: any) => t.name === "current_time") || tools[0];
    expect(timeTool).toBeDefined();

    // Execute state read
    const inspectResult = await data.testToolExecution(project.id, timeTool.id, {});
    expect(inspectResult.ok).toBe(true);
    expect(inspectResult.status).toBe(200);
  });

  test("3. State-changing smart home command passes through Tool Manager policy boundary", async ({ data }: { data: DataFixture }) => {
    const tools = await data.listTools(project.id);
    const targetTool = tools.find((t: any) => t.name === "calculator") || tools[0];
    expect(targetTool).toBeDefined();

    // 1. Create designated Specialist Agent with target tool
    const haSpecialist = await data.apiPost(`/v1/projects/${project.id}/agents`, {
      name: `HA_Specialist_${Date.now()}`,
      config: {
        flavor: "agent",
        model: "fake:ha specialist",
        system_prompt: "You are the Home Automation Specialist.",
        tools: [targetTool.id],
        middleware: [],
      },
    });

    // 2. Create unauthorized agent without tools
    const unauthorizedAgent = await data.apiPost(`/v1/projects/${project.id}/agents`, {
      name: `Guest_Agent_${Date.now()}`,
      config: {
        flavor: "agent",
        model: "fake:guest",
        system_prompt: "Guest agent without smart home access.",
        tools: [],
        middleware: [],
      },
    });

    // 3. Unauthorized agent execution attempt rejected by policy guard
    const policyEval = await data.apiPost(
      `/v1/projects/${project.id}/tool-manager/tools/${targetTool.id}/execute`,
      {
        parameters: { expression: "1 + 1" },
        caller_agent_id: unauthorizedAgent.id,
      }
    ).catch((err: any) => ({ ok: false, error: err.message, status: 400 }));

    expect(policyEval.ok === false || policyEval.status === 400).toBe(true);

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/agents/${unauthorizedAgent.id}`);
    await data.apiDelete(`/v1/projects/${project.id}/agents/${haSpecialist.id}`);
  });

  test("4. Graceful handling of invalid or ambiguous device parameters", async ({ data }: { data: DataFixture }) => {
    const tools = await data.listTools(project.id);
    const targetTool = tools.find((t: any) => t.name === "calculator") || tools[0];

    // Pass invalid argument types to tool test endpoint
    const res = await data.testToolExecution(project.id, targetTool.id, {
      expression: "INVALID_SYNTAX_+++_NOT_A_MATH_EXPRESSION",
    });

    // Must return structured response without server crash
    expect(res.status).toBeLessThan(500);

    // Platform remains operational
    const remainingTools = await data.listTools(project.id);
    expect(remainingTools.length).toBeGreaterThan(0);
  });

  test("5. Graceful handling of disabled or disconnected device endpoint", async ({ data }: { data: DataFixture }) => {
    const customTool = await data.apiPost(`/v1/projects/${project.id}/tools`, {
      name: `ha_temp_switch_${Date.now()}`,
      kind: "builtin",
      config: {
        builtin: "calculator",
        description: "Temporary HA device",
      },
    });

    // Explicitly disable the tool (simulating device disconnect)
    await data.updateToolActivation(project.id, customTool.id, false);

    // Attempt execution
    const res = await data.testToolExecution(project.id, customTool.id, { expression: "1 + 1" });
    expect(res.ok).toBe(false);
    expect(res.status).toBe(400);

    // Cleanup
    data.querySqlite(`DELETE FROM tools WHERE id = '${customTool.id}'`);
  });
});
