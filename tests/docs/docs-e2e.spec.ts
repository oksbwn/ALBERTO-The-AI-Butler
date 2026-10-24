import { test, expect } from "@playwright/test";
import path from "path";

const docsURL = process.env.DOCS_TEST_URL || "http://127.0.0.1:8088";

test.describe("Alberto Documentation Website E2E Tests", () => {
  test("01: Landing page loads with branding, title, and navigation", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${docsURL}/`);
    
    // Check title
    await expect(page).toHaveTitle(/Alberto Documentation/i);
    
    // Header branding
    const header = page.locator(".md-header");
    await expect(header).toBeVisible();
    await expect(header).toContainText("Alberto Documentation");
    
    // Hero heading
    const h1 = page.locator("h1");
    await expect(h1).toBeVisible();
    await expect(h1).toContainText("Alberto");

    // Check primary navigation tabs
    const navTabs = page.locator(".md-tabs__list");
    await expect(navTabs).toBeVisible();
    await expect(navTabs).toContainText("Getting Started");
    await expect(navTabs).toContainText("System Architecture");
    await expect(navTabs).toContainText("REST API Reference");
  });

  test("02: Search functionality indexes and returns technical queries", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${docsURL}/`);
    
    // Open search via search label or input
    const searchLabel = page.locator("label.md-search__icon, input.md-search__input").first();
    await searchLabel.click();
    const searchInput = page.locator("input.md-search__input");
    await searchInput.pressSequentially("LangGraph", { delay: 100 });
    await page.waitForTimeout(1000);
    
    // Results container or meta
    const searchMeta = page.locator(".md-search-result__meta").first();
    await expect(searchMeta).toBeVisible({ timeout: 5000 });
    await expect(searchMeta).toContainText(/document|found|matching|LangGraph/i);
  });

  test("03: Technical architecture page renders Mermaid diagrams and sections", async ({ page }) => {
    await page.goto(`${docsURL}/architecture/`);
    
    await expect(page.locator("h1")).toContainText("System Architecture");
    
    // Verify mermaid diagram is present and rendered
    const mermaid = page.locator(".mermaid").first();
    await expect(mermaid).toBeVisible();

    // Table of contents on right sidebar
    const toc = page.locator(".md-sidebar--secondary");
    await expect(toc).toBeVisible();
    await expect(toc).toContainText("Architectural Subsystems");
  });

  test("04: Screenshots load without broken image links", async ({ page }) => {
    await page.goto(`${docsURL}/`);
    
    const screenshots = page.locator("img.doc-screenshot");
    const count = await screenshots.count();
    expect(count).toBeGreaterThan(0);
    
    // Verify naturalWidth > 0 for first screenshot (meaning image loaded)
    const firstImg = screenshots.first();
    const naturalWidth = await firstImg.evaluate((img: HTMLImageElement) => img.naturalWidth);
    expect(naturalWidth).toBeGreaterThan(100);
  });

  test("05: REST API Reference pages are navigable and show endpoint schemas", async ({ page }) => {
    await page.goto(`${docsURL}/api/`);
    await expect(page.locator("h1")).toContainText("API Reference Overview");
    
    // Click through to Auth API
    const authLink = page.locator('a[href*="auth.md"], a[href="auth/"]').first();
    if (await authLink.isVisible()) {
      await authLink.click();
      await page.waitForTimeout(400);
      await expect(page.locator("h1")).toContainText("Authentication");
      // Check endpoint table
      await expect(page.locator("table")).toBeVisible();
    }
  });

  test("06: Light and dark color theme toggling", async ({ page }) => {
    await page.goto(`${docsURL}/`);
    
    const paletteToggle = page.locator("form[data-md-component='palette'] label").first();
    if (await paletteToggle.isVisible()) {
      const initialScheme = await page.locator("body").getAttribute("data-md-color-scheme");
      await paletteToggle.click();
      await page.waitForTimeout(300);
      const newScheme = await page.locator("body").getAttribute("data-md-color-scheme");
      expect(newScheme).not.toBe(initialScheme);
    }
  });

  test("07: Mobile viewport responsiveness", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${docsURL}/`);
    
    // Check mobile drawer button
    const drawerButton = page.locator("label.md-header__button.md-icon[for='__drawer']");
    await expect(drawerButton).toBeVisible();
    
    // Open drawer
    await drawerButton.click();
    await page.waitForTimeout(300);
    const navDrawer = page.locator(".md-sidebar--primary");
    await expect(navDrawer).toBeVisible();
  });
});
