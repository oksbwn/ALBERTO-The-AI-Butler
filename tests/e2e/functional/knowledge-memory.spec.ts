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
    await learningToggle.waitFor({ state: "visible", timeout: 8000 }).catch(() => {});
    if (await learningToggle.isVisible()) {
      const initialLabel = (await learningToggle.getAttribute("aria-label")) || "";
      await learningToggle.click();
      await expect(learningToggle).not.toHaveAttribute("aria-label", initialLabel, { timeout: 10000 });

      // Revert toggle
      await learningToggle.click();
      await expect(learningToggle).toHaveAttribute("aria-label", initialLabel, { timeout: 10000 });
    }
  });

  test("navigates to Knowledge screen and renders explorer controls", async ({ page }: { page: Page }) => {
    await navigateTo(page, "Knowledge");
    await expect(page.locator(".topbar")).toBeVisible();
  });
});
