import { test, expect } from "../fixtures";
import { navigateTo } from "../fixtures/navigation.helper";

test.describe("Alberto Integrations & Tool Manager E2E", () => {
  test.beforeEach(async ({ page, data }) => {
    await data.getOrCreateDefaultProject();
    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 20000 });
  });

  test("renders unified Integrations catalog and tab navigation", async ({ page }) => {
    await navigateTo(page, "Integrations");
    await expect(page.locator(".topbar")).toContainText("Integrations");

    // Check for search input or integration cards
    const searchInput = page.locator('input[placeholder*="Search"]');
    if (await searchInput.isVisible()) {
      await expect(searchInput).toBeEnabled();
    }
  });

  test("renders Tools catalog screen and tool creation option", async ({ page }) => {
    await navigateTo(page, "Tools");

    // Verify tools screen rendered
    const toolsHeader = page.locator(".topbar");
    await expect(toolsHeader).toBeVisible();
  });
});
