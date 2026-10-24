import { Page } from "@playwright/test";

const SECTION_TO_GROUP: Record<string, string> = {
  Workflows: "Automate",
  Playground: "Automate",
  Agents: "Automate",
  Components: "Automate",
  Documents: "Knowledge",
  "Vector Store": "Knowledge",
  "Knowledge Graph": "Knowledge",
  "Long-Term Memory": "Knowledge",
  "Q&A Pairs": "Knowledge",
  Integrations: "Integrations",
  Tools: "Integrations",
  Triggers: "Integrations",
  "Auth & Credentials": "Integrations",
  Analytics: "Observability",
  Traces: "Observability",
  Evaluations: "Observability",
};

export async function ensureSidebarExpanded(page: Page) {
  // Wait for ProjectSidebar to mount (project loaded from backend)
  await page.waitForSelector("button[title='Expand sidebar'], button[title='Collapse sidebar']", { timeout: 15000 }).catch(() => {});

  const expandBtn = page.locator('button[title="Expand sidebar"]');
  try {
    if (await expandBtn.isVisible().catch(() => false)) {
      await expandBtn.click();
      await page.locator('button[title="Collapse sidebar"]').waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
    }
  } catch {}
}

export async function navigateTo(page: Page, sectionName: string) {
  await ensureSidebarExpanded(page);

  const parentGroup = SECTION_TO_GROUP[sectionName];
  if (parentGroup) {
    // If leaf is already visible on the page
    const directLeaf = page.locator(`nav button.sidenav-item:has-text("${sectionName}")`).first();
    if (await directLeaf.isVisible().catch(() => false)) {
      await directLeaf.click();
      await page.waitForTimeout(400);
      return;
    }

    // Locate group header button and click to expand
    const groupHeader = page.locator(`nav button:has-text("${parentGroup}")`).first();
    if (await groupHeader.isVisible().catch(() => false)) {
      await groupHeader.click();
      await page.waitForTimeout(400);
    }

    const leafInsideGroup = page.locator(`nav button.sidenav-item:has-text("${sectionName}")`).first();
    if (await leafInsideGroup.isVisible({ timeout: 5000 }).catch(() => false)) {
      await leafInsideGroup.click();
      await page.waitForTimeout(400);
      return;
    }
  }

  // Fallback for top-level leaves (Home, Settings, etc.)
  const topLeaf = page.locator(`button[title*="${sectionName}"], nav button:has-text("${sectionName}"), button:has-text("${sectionName}")`).first();
  if (await topLeaf.isVisible({ timeout: 5000 }).catch(() => false)) {
    await topLeaf.click();
    await page.waitForTimeout(400);
  }
}
