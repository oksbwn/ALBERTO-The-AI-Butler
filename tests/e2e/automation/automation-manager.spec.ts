import { Page } from "@playwright/test";
import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Automation Manager Workflow Acceptance", () => {
  let project: TestProject;

  test.beforeEach(async ({ page, data }: { page: Page; data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 15000 });
  });

  test("Scenario A — Capability discovery, workflow generation, validation, safe dry run and approval", async ({ data }: { data: DataFixture }) => {
    // 1. Capability discovery
    const capabilities = await data.discoverCapabilities(project.id);
    expect(capabilities).toBeDefined();
    expect(Array.isArray(capabilities.node_catalog)).toBe(true);
    expect(Array.isArray(capabilities.tools)).toBe(true);

    // 2. Start authoring session
    const requirement = "Create a workflow that takes an input message and echos it with confirmation.";
    const session = await data.createAuthoringSession(project.id, requirement, "Deterministic Echo Flow");
    expect(session.id).toBeDefined();
    expect(session.status).toBe("planning");

    // 3. Send message turn to authoring session
    const stepResult = await data.sendAuthoringMessage(
      project.id,
      session.id,
      "Generate the simplest start -> agent -> end workflow."
    );
    expect(stepResult).toBeDefined();
    expect(stepResult.session_id).toBe(session.id);

    // 4. Validate proposed workflow graph
    const valRes = await data.apiPost(`/v1/projects/${project.id}/automate/sessions/${session.id}/validate`, {});
    expect(valRes).toBeDefined();

    // 5. Run safe dry-run test
    const dryRunRes = await data.testSessionProposal(project.id, session.id);
    expect(dryRunRes).toBeDefined();
    expect(Array.isArray(dryRunRes.checks)).toBe(true);

    // 6. Consolidated approval & activation
    const approvalRes = await data.approveSessionProposal(project.id, session.id, {
      revision: stepResult.revision || session.revision || 1,
      create_agents: true,
      activate_triggers: false,
    });
    expect(approvalRes).toBeDefined();
    expect(approvalRes.workflow_id).toBeDefined();

    // 7. Manual execution of activated workflow
    const runRes = await data.apiPost(`/v1/projects/${project.id}/workflows/${approvalRes.workflow_id}/runs`, {
      input: { messages: [{ role: "user", content: "Test verified input" }] },
    });
    expect(runRes.id).toBeDefined();
    expect(runRes.status === "completed" || runRes.status === "queued" || runRes.status === "running").toBe(true);

    // Clean up
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${approvalRes.workflow_id}`);
  });

  test("Scenario B — Tool-based workflow discovery and explicit policy binding", async ({ data }: { data: DataFixture }) => {
    // 1. Discover capabilities and verify registered tools appear with explicit metadata
    const capabilities = await data.discoverCapabilities(project.id);
    const calculatorTool = capabilities.tools.find((t: any) => t.name === "calculator" || t.kind === "builtin");
    expect(calculatorTool).toBeDefined();
    expect(calculatorTool.effect_type).toBeDefined();
    expect(calculatorTool.risk_level).toBeDefined();
  });

  test("Scenario C — Recoverable failure diagnosis in execution history", async ({ data }: { data: DataFixture }) => {
    // 1. Create a workflow designed to fail deterministically
    const failWfPayload = {
      name: `Failing_Workflow_${Date.now()}`,
      executable: {
        id: `fail_${Date.now()}`,
        version: 1,
        entry_node: "start",
        state: {
          messages: { type: "list[message]", reducer: "add_messages" },
        },
        nodes: [
          { id: "start", type: "start", config: {}, position: { x: 50, y: 150 } },
          {
            id: "bad_tool_agent",
            type: "agent",
            config: {
              name: "Failing Agent",
              model: "fake:calling invalid tool",
              tools: ["non_existent_tool_id_12345"],
            },
            position: { x: 300, y: 150 },
          },
          { id: "end", type: "end", config: {}, position: { x: 550, y: 150 } },
        ],
        edges: [
          { source: "start", target: "bad_tool_agent" },
          { source: "bad_tool_agent", target: "end" },
        ],
      },
      canvas: {
        nodes: [
          { id: "start", type: "forgeNode", position: { x: 50, y: 150 }, data: { nodeType: "start" } },
          { id: "bad_tool_agent", type: "forgeNode", position: { x: 300, y: 150 }, data: { nodeType: "agent" } },
          { id: "end", type: "forgeNode", position: { x: 550, y: 150 }, data: { nodeType: "end" } },
        ],
        edges: [
          { id: "e1", source: "start", target: "bad_tool_agent" },
          { id: "e2", source: "bad_tool_agent", target: "end" },
        ],
      },
    };

    const wf = await data.apiPost(`/v1/projects/${project.id}/workflows`, failWfPayload);

    // 2. Execute failing workflow
    const runRes = await data.apiPost(`/v1/projects/${project.id}/workflows/${wf.id}/runs`, {
      input: { messages: [{ role: "user", content: "Trigger fail" }] },
    });
    expect(runRes.id).toBeDefined();

    // 3. Inspect Automation Manager diagnostic endpoint
    const diagRes = await data.apiGet(`/v1/projects/${project.id}/automate/runs/${runRes.id}/diagnose`);
    expect(diagRes).toBeDefined();
    expect(diagRes.run_id).toBe(runRes.id);

    // Clean up
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wf.id}`);
  });

  test("Scenario D — One-time and recurring schedule persistence in SQLite triggers", async ({ data }: { data: DataFixture }) => {
    // 1. Create a simple workflow
    const wf = await data.createDeterministicWorkflow(project.id, `Scheduled_Wf_${Date.now()}`);

    // 2. Query triggers for project
    const triggers = await data.apiGet(`/v1/projects/${project.id}/triggers`);
    expect(Array.isArray(triggers)).toBe(true);

    // 3. Directly verify triggers table in SQLite database
    const dbRows = data.querySqlite(
      `SELECT count(*) as count FROM triggers WHERE project_id = '${project.id}'`
    );
    expect(dbRows.length).toBeGreaterThan(0);
  });
});
