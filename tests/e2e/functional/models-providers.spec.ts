import { test, expect } from "../fixtures";
import { navigateTo } from "../fixtures/navigation.helper";

test.describe("Alberto Models & Providers Configuration E2E", () => {
  test.beforeEach(async ({ page, data }) => {
    await data.getOrCreateDefaultProject();
    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 20000 });

    // Navigate to Settings
    await navigateTo(page, "Settings");
    await expect(page.locator('button:has-text("Models & Providers")').first()).toBeVisible({ timeout: 15000 });
  });

  test("renders Models & Providers configuration tab by default", async ({ page }) => {
    // Verify Models & Providers section button is active or displayed
    const modelsTab = page.locator('button:has-text("Models & Providers")');
    await expect(modelsTab).toBeVisible();

    // Verify main content container renders settings options
    const content = page.locator(".col.grow").first();
    await expect(content).toBeVisible();
  });

  test("navigates through settings sections without crash", async ({ page }) => {
    // 1. Secrets & Credentials
    const secretsTab = page.locator('button:has-text("Secrets & Credentials")');
    if (await secretsTab.isVisible()) {
      await secretsTab.click();
      await page.waitForTimeout(300);
    }

    // 2. Members & Roles
    const membersTab = page.locator('button:has-text("Members & Roles")');
    if (await membersTab.isVisible()) {
      await membersTab.click();
      await page.waitForTimeout(300);
    }

    // 3. Guardrails & Egress
    const guardrailsTab = page.locator('button:has-text("Guardrails & Egress")');
    if (await guardrailsTab.isVisible()) {
      await guardrailsTab.click();
      await page.waitForTimeout(300);
    }

    // 4. Return to Models & Providers
    const modelsTab = page.locator('button:has-text("Models & Providers")');
    await modelsTab.click();
    await page.waitForTimeout(300);
    await expect(modelsTab).toBeVisible();
  });
});
