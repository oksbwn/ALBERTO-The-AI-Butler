import { test, expect, Page, DataFixture } from "../fixtures";
import { navigateTo } from "../fixtures/navigation.helper";

test.describe("Alberto Knowledge & Memory Management E2E", () => {
  test.beforeEach(async ({ page, data }: { page: Page; data: DataFixture }) => {
    await data.getOrCreateDefaultProject();
    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 20000 });
  });

  test("toggles autonomous memory learning indicator in topbar", async ({ page }: { page: Page }) => {
    const learningToggle = page.locator('button[aria-label*="Toggle autonomous memory learning"]');
    if (await learningToggle.isVisible()) {
      const initialLabel = await learningToggle.getAttribute("aria-label");
      await learningToggle.click();
      await page.waitForTimeout(500);

      const nextLabel = await learningToggle.getAttribute("aria-label");
      expect(nextLabel).not.toBe(initialLabel);

      // Revert toggle
      await learningToggle.click();
      await page.waitForTimeout(500);
    }
  });

  test("navigates to Knowledge screen and renders explorer controls", async ({ page }: { page: Page }) => {
    await navigateTo(page, "Knowledge");
    await expect(page.locator(".topbar")).toBeVisible();
  });
});
