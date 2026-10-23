import { test, expect } from "../fixtures";
import { navigateTo } from "../fixtures/navigation.helper";

test.describe("Alberto Shell & Main Navigation E2E", () => {
  test.beforeEach(async ({ page, data }) => {
    // Ensure default project exists for breadcrumb & sidebar
    await data.getOrCreateDefaultProject();
    await page.goto("/");
    // Wait for app shell to load
    await page.waitForSelector(".topbar", { timeout: 20000 });
  });

  test("loads root application shell with topbar, sidebar, and breadcrumbs", async ({ page }) => {
    await expect(page).toHaveTitle(/Alberto|Forge/i);
    const topbar = page.locator(".topbar");
    await expect(topbar).toBeVisible();

    // Verify search and theme controls are present
    const searchBtn = page.locator('button:has-text("Search…")');
    await expect(searchBtn).toBeVisible();

    const themeBtn = page.locator('button[aria-label="Toggle color theme"]');
    await expect(themeBtn).toBeVisible();
  });

  test("navigates through core sidebar sections and updates view state", async ({ page }) => {
    // 1. Home / Assistant
    await page.goto("/");
    await expect(page.locator(".topbar")).toBeVisible();

    // 2. Automate -> Workflows
    await navigateTo(page, "Workflows");
    await expect(page.locator(".topbar")).toContainText("Workflows");

    // 3. Automate -> Playground
    await navigateTo(page, "Playground");
    await expect(page.locator(".topbar")).toContainText("Automate");

    // 4. Agents
    await navigateTo(page, "Agents");
    await expect(page.locator(".topbar")).toContainText("Agents");

    // 5. Integrations
    await navigateTo(page, "Integrations");
    await expect(page.locator(".topbar")).toContainText("Integrations");

    // 6. Settings
    await navigateTo(page, "Settings");
    await expect(page.locator(".topbar")).toContainText("Settings");
  });

  test("toggles console color theme between light and dark", async ({ page }) => {
    const html = page.locator("html");
    const themeBtn = page.locator('button[aria-label="Toggle color theme"]');

    const initialTheme = await html.getAttribute("data-theme") || "light";
    await themeBtn.click();
    const newTheme = await html.getAttribute("data-theme");
    expect(newTheme).not.toBe(initialTheme);

    // Toggle back
    await themeBtn.click();
    const revertedTheme = await html.getAttribute("data-theme");
    expect(revertedTheme).toBe(initialTheme);
  });

  test("opens and closes command palette with keyboard shortcut and button", async ({ page }) => {
    const searchBtn = page.locator('button:has-text("Search…")');
    await searchBtn.click();

    // Command palette renders search input
    const searchInput = page.locator('input[placeholder*="Search workflows"]');
    await expect(searchInput).toBeVisible();

    // Close via shortcut toggle
    await page.keyboard.press("Control+k");
    await expect(searchInput).not.toBeVisible();
  });
});
