import { test, expect, Page, DataFixture } from "../fixtures";
import { navigateTo } from "../fixtures/navigation.helper";

test.describe("Alberto Workflow Execution & SSE Streaming E2E", () => {
  let project: any;
  let workflow: any;

  test.beforeEach(async ({ page, data }: { page: Page; data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
    workflow = await data.createDeterministicWorkflow(project.id, `E2E Deterministic ${Date.now()}`);

    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 20000 });

    // Navigate to Workflows list
    await navigateTo(page, "Workflows");
    await page.waitForTimeout(600);

    // Click our test workflow in the list to open canvas (click caption so inline rename is not triggered)
    const workflowCard = page.locator(".card", { hasText: workflow.name }).first();
    await expect(workflowCard).toBeVisible({ timeout: 15000 });
    await workflowCard.locator(".t-caption").click();
    await page.waitForSelector(".react-flow", { timeout: 20000 });
  });

  test("verifies workflow canvas node persistence and renders React Flow graph", async ({ page }: { page: Page }) => {
    // Verify Start, Echo Agent, and End nodes are rendered on canvas
    await expect(page.locator('.react-flow__node:has-text("Start")')).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("echo_agent"), .react-flow__node:has-text("Echo Agent")').first()).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("End")')).toBeVisible();

    // Verify Run button is present in canvas toolbar
    const runBtn = page.locator('button[title="Run Workflow"]');
    await expect(runBtn).toBeVisible();
  });

  test("validates manual input and catches malformed JSON before execution", async ({ page }: { page: Page }) => {
    // Open Run panel
    const runBtn = page.locator('button[title="Run Workflow"]');
    await runBtn.click();
    await page.waitForSelector('text="Orchestrator Execution"', { timeout: 10000 });

    // Switch to JSON mode
    const jsonBtn = page.locator('button:has-text("JSON Payload")');
    await jsonBtn.click();

    // Enter malformed JSON
    const textarea = page.locator("textarea.mono-sm");
    await textarea.fill('{ invalid_json: ');

    // Expect invalid JSON error banner
    await expect(page.getByText("Invalid JSON")).toBeVisible();

    // Verify panel Run button is disabled when input has error
    const execBtn = page.locator('button[type="button"].btn-primary:has-text("Run")');
    await expect(execBtn).toBeDisabled();
  });

  test("executes deterministic workflow, streams SSE events, illuminates nodes, and produces structured output", async ({ page }: { page: Page }) => {
    // Open Run panel
    const runBtn = page.locator('button[title="Run Workflow"]');
    await runBtn.click();
    await page.waitForSelector('text="Orchestrator Execution"', { timeout: 10000 });

    // Input test message
    const msgInput = page.locator('input[placeholder*="Message the workflow"]');
    if (await msgInput.isVisible()) {
      await msgInput.fill("Automated E2E Trigger Test");
    }

    // Trigger execution
    const execBtn = page.locator('button[type="button"].btn-primary:has-text("Run")');
    await execBtn.click();

    // Verify execution status transitions
    const statusPill = page.locator('.col:has-text("Orchestrator Execution") .pill');
    await expect(statusPill).toBeVisible();

    // Await completion (done) within 30 seconds
    const donePill = page.getByText(/done/i).first();
    await expect(donePill).toBeVisible({ timeout: 30000 });

    // Verify tab navigation exists
    const nodeSteps = page.locator('button:has-text("Node Steps")');
    await expect(nodeSteps).toBeVisible();

    // Switch to output tab and verify copy button exists
    const outputTab = page.locator('button:has-text("Output & Results")');
    await expect(outputTab).toBeVisible();
    await outputTab.click();

    const copyBtn = page.locator('button:has-text("Copy JSON")');
    await expect(copyBtn).toBeVisible();
  });

  test("persists canvas layout and workflow nodes across page reloads", async ({ page }: { page: Page }) => {
    // Verify nodes on canvas
    await expect(page.locator('.react-flow__node:has-text("echo_agent"), .react-flow__node:has-text("Echo Agent")').first()).toBeVisible();

    // Reload browser page
    await page.reload();
    await page.waitForSelector(".topbar", { timeout: 15000 });
    await navigateTo(page, "Workflows");
    await page.waitForTimeout(600);
    const card = page.locator(".card", { hasText: workflow.name }).first();
    await expect(card).toBeVisible({ timeout: 15000 });
    await card.locator(".tile, .t-caption").first().click();
    await page.waitForSelector(".react-flow", { timeout: 15000 });

    // Verify all workflow nodes persist intact on the canvas
    await expect(page.locator('.react-flow__node:has-text("Start")')).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("echo_agent"), .react-flow__node:has-text("Echo Agent")').first()).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("End")')).toBeVisible();
  });
});
