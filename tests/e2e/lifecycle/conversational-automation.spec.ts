import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Conversational Automation Manager Acceptance", () => {
  let project: TestProject;

  test.beforeEach(async ({ data }: { data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
  });

  test("Scenario A — Natural language instruction to executable workflow lifecycle", async ({ data }: { data: DataFixture }) => {
    // 1. Natural language instruction to Automation Manager
    const instruction = "Create a workflow that accepts a message, converts it into a structured JSON result and returns the output.";
    
    // 2. Discover capabilities
    const capabilities = await data.discoverCapabilities(project.id);
    expect(capabilities).toBeDefined();
    expect(Array.isArray(capabilities.node_catalog)).toBe(true);

    // 3. Initialize conversational authoring session
    const session = await data.createAuthoringSession(project.id, instruction, "Conversational JSON Pipeline");
    expect(session.id).toBeDefined();
    expect(session.status).toBe("planning");

    // 4. Send requirement message turn to authoring planner
    const step = await data.sendAuthoringMessage(
      project.id,
      session.id,
      "Generate the simplest valid start -> agent -> end pipeline that outputs structured JSON."
    );
    expect(step).toBeDefined();
    expect(step.session_id).toBe(session.id);

    // 5. Schema and graph validation
    const valRes = await data.apiPost(`/v1/projects/${project.id}/automate/sessions/${session.id}/validate`, {});
    expect(valRes).toBeDefined();

    // 6. Safe dry-run execution
    const dryRun = await data.testSessionProposal(project.id, session.id);
    expect(dryRun).toBeDefined();
    expect(Array.isArray(dryRun.checks)).toBe(true);

    // 7. Consolidated approval and activation
    const approval = await data.approveSessionProposal(project.id, session.id, {
      revision: step.revision || 1,
      create_agents: true,
      activate: true,
    });
    expect(approval).toBeDefined();
    expect(approval.workflow_id).toBeDefined();

    const wfId = approval.workflow_id;

    // 8. Execute activated workflow through LangGraph
    const runRes = await data.apiPost(`/v1/projects/${project.id}/workflows/${wfId}/runs`, {
      input: { messages: [{ role: "user", content: "Process this text into JSON" }] },
    });
    expect(runRes.id).toBeDefined();
    expect(["completed", "running", "queued"]).toContain(runRes.status);

    // 9. Verify execution history in SQLite runs table
    const runs = data.querySqlite(`SELECT * FROM runs WHERE id = '${runRes.id}'`);
    expect(runs.length).toBe(1);

    // Cleanup
    await data.apiDelete(`/v1/projects/${project.id}/workflows/${wfId}`);
  });

  test("Scenario B & Negative Tests — Rejected proposal does not activate workflow", async ({ data }: { data: DataFixture }) => {
    // 1. Create authoring session
    const session = await data.createAuthoringSession(project.id, "Test rejection workflow", "Draft Flow");
    expect(session.status).toBe("planning");

    // 2. Reject or abandon without approving
    // Session status remains unapproved
    const sessionDetail = await data.apiGet(`/v1/projects/${project.id}/automate/sessions/${session.id}`);
    expect(sessionDetail.status).not.toBe("approved");

    // 3. Confirm no active workflow was spawned from this unapproved session
    const workflows = data.querySqlite(
      `SELECT * FROM workflows WHERE project_id = '${project.id}' AND name LIKE '%Draft Flow%'`
    );
    expect(workflows.length).toBe(0);
  });
});
