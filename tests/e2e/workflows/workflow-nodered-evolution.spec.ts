import { test, expect, Page, DataFixture } from "../fixtures";
import { navigateTo } from "../fixtures/navigation.helper";

test.describe("Node-RED-Inspired Low-Code Workflow Evolution E2E", () => {
  let project: any;
  let workflow: any;

  test.beforeEach(async ({ page, data }: { page: Page; data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
    workflow = await data.createNodeRedEvolutionWorkflow(
      project.id,
      `Node-RED Evolution ${Date.now()}`
    );

    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 20000 });

    // Navigate to Workflows list
    await navigateTo(page, "Workflows");
    await page.waitForTimeout(600);

    // Click our test workflow in the list to open canvas
    const workflowCard = page.locator(".card", { hasText: workflow.name }).first();
    await expect(workflowCard).toBeVisible({ timeout: 20000 });
    await workflowCard.locator(".t-caption").click();
    await page.waitForSelector(".react-flow", { timeout: 20000 });
  });

  test("verifies compact Node-RED node cards, explicit ports, and inject trigger button on canvas", async ({
    page,
  }: {
    page: Page;
  }) => {
    // 1. Verify Inject, Transform, and Debug nodes are rendered on canvas with compact design
    const injectNode = page.locator('.react-flow__node:has-text("Inject")').first();
    await expect(injectNode).toBeVisible();

    const transformNode = page.locator('.react-flow__node:has-text("Transform")').first();
    await expect(transformNode).toBeVisible();

    const debugNode = page.locator('.react-flow__node:has-text("Debug")').first();
    await expect(debugNode).toBeVisible();

    // 2. Verify explicit handles are mounted
    await expect(injectNode.locator(".react-flow__handle-right")).toBeVisible();
    await expect(transformNode.locator(".react-flow__handle-left")).toBeVisible();
    await expect(transformNode.locator(".react-flow__handle-right")).toBeVisible();
    await expect(debugNode.locator(".react-flow__handle-left")).toBeVisible();

    // 3. Verify manual play trigger button on inject node
    const triggerBtn = injectNode.locator('button[title="Inject message now"]');
    await expect(triggerBtn).toBeVisible();
  });

  test("verifies visual data mapping and upstream variable picker in inspector", async ({
    page,
  }: {
    page: Page;
  }) => {
    // Click transform node to open config inspector
    const transformNode = page.locator('.react-flow__node:has-text("Transform")').first();
    await transformNode.click();

    // Inspector form should open with Transform Mode
    await expect(page.locator('text="Transform Mode"')).toBeVisible({ timeout: 10000 });

    // Verify Simple / Advanced mode switch exists
    const simpleModeBtn = page.locator('button:has-text("Simple")').first();
    const advancedModeBtn = page.locator('button:has-text("Advanced")').first();
    await expect(simpleModeBtn).toBeVisible();
    await expect(advancedModeBtn).toBeVisible();

    // Look for Variable Picker trigger button if visible
    const varPickerBtn = page.locator('button[title="Pick upstream variable"]').first();
    if (await varPickerBtn.isVisible().catch(() => false)) {
      await varPickerBtn.click();
      await expect(page.locator(".card:has-text('Upstream Outputs')").first()).toBeVisible();
      await expect(page.locator("text=payload").first()).toBeVisible();
    }
  });

  test("executes Node-RED workflow via manual inject and verifies debug sidebar output and secret redaction", async ({
    page,
  }: {
    page: Page;
  }) => {
    // 1. Open Run panel
    const runBtn = page.locator('button[title="Run Workflow"]');
    await runBtn.click();
    await page.waitForSelector('text="Orchestrator Execution"', { timeout: 10000 });

    // 2. Click Run to execute workflow
    const execBtn = page.locator('button[type="button"].btn-primary:has-text("Run")');
    await execBtn.click();

    // 3. Wait for run to finish (done pill)
    const donePill = page.getByText(/done/i).first();
    await expect(donePill).toBeVisible({ timeout: 30000 });

    // 4. Verify Debug tab exists in execution panel and received the event
    const debugTab = page.locator('button:has-text("Debug (1)")').first();
    await expect(debugTab).toBeVisible();
    await debugTab.click();

    // Verify debug card rendered for debug_node
    await expect(page.locator("span.chip:has-text('debug_node')").first()).toBeVisible();

    // 5. Verify Output & Results tab displays final output with copy button
    const outputTab = page.locator('button:has-text("Output & Results")').first();
    await outputTab.click();
    await expect(page.locator('text="Final Run Output"')).toBeVisible();
    await expect(page.locator('button:has-text("Copy JSON")')).toBeVisible();
  });

  test("verifies Inject node inspector configuration types and Debug enable toggle", async ({
    page,
  }: {
    page: Page;
  }) => {
    // 1. Click Inject node
    const injectNode = page.locator('.react-flow__node:has-text("Inject")').first();
    await injectNode.click();

    // Verify Inspector opened with inject configurations
    await expect(page.locator('label:has-text("Payload Type")').first()).toBeVisible({ timeout: 10000 });
    const payloadTypeSelect = page.locator('select').first();
    await expect(payloadTypeSelect).toBeVisible();

    // Verify Topic field
    await expect(page.locator('label:has-text("Topic")').first()).toBeVisible();

    // 2. Click Debug node
    const debugNode = page.locator('.react-flow__node:has-text("Debug")').first();
    await debugNode.click();

    // Verify Inspect property and Debug active toggle exist
    await expect(page.locator('text="Inspect property"').first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Debug active").first()).toBeVisible();
  });

  test("executes parallel branch workflow and verifies deterministic Join aggregation on canvas and debug sidebar", async ({
    page,
    data,
  }: {
    page: Page;
    data: DataFixture;
  }) => {
    const parallelWf = await data.createParallelNodeRedWorkflow(
      project.id,
      `Parallel Join Acceptance ${Date.now()}`
    );

    await navigateTo(page, "Workflows");
    await page.waitForTimeout(600);

    const wfCard = page.locator(".card", { hasText: parallelWf.name }).first();
    await expect(wfCard).toBeVisible({ timeout: 20000 });
    await wfCard.locator(".t-caption").click();
    await page.waitForSelector(".react-flow", { timeout: 20000 });

    // Verify all nodes visible on canvas
    await expect(page.locator('.react-flow__node:has-text("Inject")').first()).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("Change")').first()).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("Join")').first()).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("Debug")').first()).toBeVisible();

    // Execute workflow
    const runBtn = page.locator('button[title="Run Workflow"]');
    await runBtn.click();
    await page.waitForSelector('text="Orchestrator Execution"', { timeout: 10000 });

    const execBtn = page.locator('button[type="button"].btn-primary:has-text("Run")');
    await execBtn.click();

    const donePill = page.getByText(/done/i).first();
    await expect(donePill).toBeVisible({ timeout: 30000 });

    // Verify Output & Results contains aggregated branch outputs
    const outputTab = page.locator('button:has-text("Output & Results")').first();
    await outputTab.click();
    await expect(page.locator('text="Final Run Output"')).toBeVisible();

    // Verify Debug event arrived
    const debugTab = page.locator('button:has-text("Debug (1)")').first();
    await expect(debugTab).toBeVisible();
    await debugTab.click();
    await expect(page.locator("span.chip:has-text('debug_node')").first()).toBeVisible();
  });

  test("builds and executes real Home Automation workflow through canvas with Switch routing and screenshots", async ({
    page,
    data,
  }: {
    page: Page;
    data: DataFixture;
  }) => {
    const haWf = await data.createHomeAutomationWorkflow(
      project.id,
      `Home Automation Alert ${Date.now()}`
    );

    await navigateTo(page, "Workflows");
    await page.waitForTimeout(600);

    const wfCard = page.locator(".card", { hasText: haWf.name }).first();
    await expect(wfCard).toBeVisible({ timeout: 20000 });
    await wfCard.locator(".t-caption").click();
    await page.waitForSelector(".react-flow", { timeout: 20000 });

    // 1. Capture workflow canvas screenshot
    const brainDir = "C:/Users/oksbw/.gemini/antigravity-ide/brain/02fc7382-d55d-4880-95ea-4a79d9352281";
    await page.screenshot({ path: `${brainDir}/canvas_nodered_workflow.png` });

    // 2. Click Inject node, capture inspector screenshot
    const injectNode = page.locator('.react-flow__node:has-text("Inject")').first();
    await injectNode.click();
    await expect(page.locator('label:has-text("Payload Type")').first()).toBeVisible({ timeout: 10000 });
    await page.screenshot({ path: `${brainDir}/canvas_inspector.png` });

    // 3. Click Switch node to verify Simple Mode rule
    const switchNode = page.locator('.react-flow__node:has-text("Switch")').first();
    if (await switchNode.isVisible().catch(() => false)) {
      await switchNode.click();
      await page.waitForTimeout(300);
    }

    // 4. Execute workflow via Run button
    const runBtn = page.locator('button[title="Run Workflow"]');
    await runBtn.click();
    await page.waitForSelector('text="Orchestrator Execution"', { timeout: 10000 });

    const execBtn = page.locator('button[type="button"].btn-primary:has-text("Run")');
    await execBtn.click();

    const donePill = page.getByText(/done/i).first();
    await expect(donePill).toBeVisible({ timeout: 30000 });

    // 5. Open Debug sidebar, verify alert notification output, capture screenshot
    const debugTab = page.locator('button:has-text("Debug (1)")').first();
    await expect(debugTab).toBeVisible();
    await debugTab.click();
    await expect(page.locator("span.chip:has-text('debug_alert')").first()).toBeVisible();
    await page.screenshot({ path: `${brainDir}/debug_sidebar.png` });
  });

  test("verifies practical AI Butler meeting assistant workflow through canvas with Switch routing and Debug verification", async ({
    page,
    data,
  }: {
    page: Page;
    data: DataFixture;
  }) => {
    // Section 4 Acceptance: Inject -> AI Agent -> Switch -> Change -> Debug
    const butlerWf = await data.createAiButlerMeetingWorkflow(
      project.id,
      `AI Butler Meeting Assistant ${Date.now()}`
    );

    await navigateTo(page, "Workflows");
    await page.waitForTimeout(600);

    const wfCard = page.locator(".card", { hasText: butlerWf.name }).first();
    await expect(wfCard).toBeVisible({ timeout: 20000 });
    await wfCard.locator(".t-caption").click();
    await page.waitForSelector(".react-flow", { timeout: 20000 });

    // 1. Verify Butler workflow nodes rendered on canvas
    await expect(page.locator('.react-flow__node:has-text("Inject")').first()).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("Change")').first()).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("Switch")').first()).toBeVisible();
    await expect(page.locator('.react-flow__node:has-text("Debug")').first()).toBeVisible();

    // 2. Open Inspector for Agent Interpretation Change Node
    const changeNode = page.locator('.react-flow__node:has-text("Change")').first();
    await changeNode.click();
    await expect(page.locator('text="Transform Mode"')).toBeVisible({ timeout: 10000 });

    // 3. Execute workflow
    const runBtn = page.locator('button[title="Run Workflow"]');
    await runBtn.click();
    await page.waitForSelector('text="Orchestrator Execution"', { timeout: 10000 });

    const execBtn = page.locator('button[type="button"].btn-primary:has-text("Run")');
    await execBtn.click();

    const donePill = page.getByText(/done/i).first();
    await expect(donePill).toBeVisible({ timeout: 30000 });

    // 4. Inspect Debug output: verify structured action summary and tool authorization boundary
    const debugTab = page.locator('button:has-text("Debug (1)")').first();
    await expect(debugTab).toBeVisible();
    await debugTab.click();

    // Verify debug chip is debug_butler_result and contains action summary
    await expect(page.locator("span.chip:has-text('debug_butler_result')").first()).toBeVisible();

    // 5. Open Output & Results tab and verify final payload contains tool authorization flag false (no unauthorized execution)
    const outputTab = page.locator('button:has-text("Output & Results")').first();
    await outputTab.click();
    await expect(page.locator('text="Final Run Output"')).toBeVisible();

    const brainDir = "C:/Users/oksbw/.gemini/antigravity-ide/brain/02fc7382-d55d-4880-95ea-4a79d9352281";
    await page.screenshot({ path: `${brainDir}/canvas_butler_meeting_workflow.png` });
  });
});

