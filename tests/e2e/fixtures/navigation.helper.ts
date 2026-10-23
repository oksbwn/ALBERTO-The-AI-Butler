import { Page } from "@playwright/test";

export async function ensureSidebarExpanded(page: Page) {
  const expandBtn = page.locator('button[title="Expand sidebar"]');
  if (await expandBtn.isVisible()) {
    await expandBtn.click();
    await page.waitForTimeout(300);
  }
}

export async function navigateTo(page: Page, sectionName: string) {
  await ensureSidebarExpanded(page);

  // Target leaf item by class .sidenav-item
  const leafBtn = page.locator(`button.sidenav-item:has-text("${sectionName}")`).first();
  if (await leafBtn.isVisible()) {
    await leafBtn.click();
  } else {
    // If not visible, ensure section group accordion is opened
    const groupBtn = page.locator(`button:has-text("${sectionName}")`).first();
    if (await groupBtn.isVisible()) {
      await groupBtn.click();
      await page.waitForTimeout(300);
      const afterOpenLeaf = page.locator(`button.sidenav-item:has-text("${sectionName}")`).first();
      if (await afterOpenLeaf.isVisible()) {
        await afterOpenLeaf.click();
      }
    }
  }
  await page.waitForTimeout(500);
}
