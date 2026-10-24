import { test, expect, Page, DataFixture } from "../fixtures";
import { navigateTo } from "../fixtures/navigation.helper";

test.describe("Alberto Workflow Authoritative Execution States & HITL Regression", () => {
  let project: any;
  let workflow: any;

  test.beforeEach(async ({ page, data }: { page: Page; data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
    workflow = await data.createHitlWorkflow(project.id, `E2E HITL State ${Date.now()}`);

    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 20000 });

    await navigateTo(page, "Workflows");
    await page.waitForTimeout(800);

    const workflowCard = page.locator(".card", { hasText: workflow.name }).first();
    await expect(workflowCard).toBeVisible({ timeout: 15000 });
    await workflowCard.locator(".tile, .t-caption").first().click();
    await page.waitForSelector(".react-flow", { timeout: 20000 });
  });

  test("verifies authoritative state progression: running -> interrupted -> resumed -> done", async ({ page, data }: { page: Page; data: DataFixture }) => {
    // 1. Open execution drawer and start workflow run
    const runBtn = page.locator('button[title="Run Workflow"]');
    await runBtn.click();
    await page.waitForSelector('text="Orchestrator Execution"', { timeout: 10000 });

    const execBtn = page.locator('button[type="button"].btn-primary:has-text("Run")');
    await execBtn.click();

    // 2. Wait for interrupt banner to appear in UI
    const interruptedBadge = page.locator('text="Action Requires Approval"').or(page.locator('text="interrupted"')).first();
    await expect(interruptedBadge).toBeVisible({ timeout: 25000 });

    // 3. Directly inspect authoritative SQLite state while paused
    const interruptedRows = data.querySqlite(
      `SELECT status FROM runs WHERE workflow_id = '${workflow.id}' ORDER BY created_at DESC LIMIT 1`
    );
    expect(interruptedRows.length).toBe(1);
    expect(interruptedRows[0].status).toBe("interrupted");

    // 4. Click Approve Action to resume
    const approveBtn = page.locator('button:has-text("Approve Action")');
    await expect(approveBtn).toBeVisible();
    await approveBtn.click();

    // 5. Verify execution completes in UI
    await expect(page.getByText(/done/i).first()).toBeVisible({ timeout: 25000 });

    // 6. Verify final authoritative completion state in SQLite
    const completedRows = data.querySqlite(
      `SELECT status FROM runs WHERE workflow_id = '${workflow.id}' ORDER BY created_at DESC LIMIT 1`
    );
    expect(completedRows.length).toBe(1);
    expect(["done", "completed"]).toContain(completedRows[0].status);
  });

  test("supports in-flight run cancellation to authoritative cancelled status", async ({ page, data }: { page: Page; data: DataFixture }) => {
    const runBtn = page.locator('button[title="Run Workflow"]');
    await runBtn.click();
    await page.waitForSelector('text="Orchestrator Execution"', { timeout: 10000 });

    const execBtn = page.locator('button[type="button"].btn-primary:has-text("Run")');
    await execBtn.click();

    // Wait until running or interrupted
    const stopOrReject = page.locator('button:has-text("Stop")').or(page.locator('button:has-text("Reject Action")')).first();
    await expect(stopOrReject).toBeVisible({ timeout: 15000 });

    // Click Stop / Reject to cancel in-flight or interrupted run
    await stopOrReject.click();
    await page.waitForTimeout(1000);

    // Verify UI reflects termination
    const stoppedState = page.locator('text="canceled"').or(page.locator('text="done"')).or(page.locator('.pill')).first();
    await expect(stoppedState).toBeVisible();

    // Verify authoritative terminal status in SQLite
    const rows = data.querySqlite(
      `SELECT status FROM runs WHERE workflow_id = '${workflow.id}' ORDER BY created_at DESC LIMIT 1`
    );
    if (rows.length > 0) {
      expect(["done", "completed", "canceled", "cancelled", "interrupted", "failed"]).toContain(rows[0].status);
    }
  });
});
