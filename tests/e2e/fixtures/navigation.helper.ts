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
  const expandBtn = page.locator('button[title="Expand sidebar"]');
  if (await expandBtn.isVisible().catch(() => false)) {
    await expandBtn.click();
    await page.waitForTimeout(400);
  }
}

export async function navigateTo(page: Page, sectionName: string) {
  await ensureSidebarExpanded(page);

  const parentGroup = SECTION_TO_GROUP[sectionName];
  if (parentGroup) {
    // Locate group container by header text
    const groupContainer = page.locator("nav > div").filter({ has: page.locator(`button:has-text("${parentGroup}")`) });
    const leafInsideGroup = groupContainer.locator(`button:has-text("${sectionName}")`).last();

    // If leaf not visible, expand the parent group accordion
    if (!(await leafInsideGroup.isVisible().catch(() => false))) {
      const headerBtn = groupContainer.locator(`button:has-text("${parentGroup}")`).first();
      if (await headerBtn.isVisible().catch(() => false)) {
        await headerBtn.click();
        await page.waitForTimeout(400);
      }
    }

    // Click the specific leaf inside its parent group container
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
