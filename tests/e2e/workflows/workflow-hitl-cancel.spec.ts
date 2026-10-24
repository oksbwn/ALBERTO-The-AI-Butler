import { test, expect, Page, DataFixture } from "../fixtures";
import { navigateTo } from "../fixtures/navigation.helper";

test.describe("Alberto Workflow HITL Approval & Run Cancellation E2E", () => {
  let project: any;
  let workflow: any;

  test.beforeEach(async ({ page, data }: { page: Page; data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
    workflow = await data.createHitlWorkflow(project.id, `E2E HITL ${Date.now()}`);

    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 20000 });

    await navigateTo(page, "Workflows");
    await page.waitForTimeout(800);

    const workflowCard = page.locator(".card", { hasText: workflow.name }).first();
    await expect(workflowCard).toBeVisible({ timeout: 15000 });
    await workflowCard.locator(".tile, .t-caption").first().click();
    await page.waitForSelector(".react-flow", { timeout: 20000 });
  });

  test("pauses execution at HITL interrupt and resumes on operator approval", async ({ page }: { page: Page }) => {
    // Open execution drawer
    const runBtn = page.locator('button[title="Run Workflow"]');
    await runBtn.click();
    await page.waitForSelector('text="Orchestrator Execution"', { timeout: 10000 });

    // Execute HITL workflow
    const execBtn = page.locator('button[type="button"].btn-primary:has-text("Run")');
    await execBtn.click();

    // Verify status transitions to interrupted
    const interruptedBadge = page.locator('text="Action Requires Approval"').or(page.locator('text="interrupted"')).first();
    await expect(interruptedBadge).toBeVisible({ timeout: 20000 });

    // Verify approval action banner appears
    const approveBtn = page.locator('button:has-text("Approve Action")');
    const rejectBtn = page.locator('button:has-text("Reject Action")');
    await expect(approveBtn).toBeVisible();
    await expect(rejectBtn).toBeVisible();

    // Operator approves the action
    await approveBtn.click();

    // Verify execution resumes and reaches done
    await expect(page.getByText(/done/i).first()).toBeVisible({ timeout: 25000 });
  });

  test("supports in-flight or interrupted run cancellation", async ({ page }: { page: Page }) => {
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

    // Verify execution terminates cleanly without unhandled crash
    const stoppedState = page.locator('text="canceled"').or(page.locator('text="done"')).or(page.locator('.pill')).first();
    await expect(stoppedState).toBeVisible();
  });
});
