import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";

const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3000";
const apiURL = process.env.ALBERTO_API_URL || "http://127.0.0.1:8000";
const repoRoot = path.resolve(__dirname, "../..");
const screenshotsDir = path.join(repoRoot, "docs/assets/screenshots");

async function getAuthToken(): Promise<string | null> {
  try {
    const res = await fetch(`${apiURL}/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "admin", password: "password" }),
    });
    if (res.ok) {
      const data = await res.json();
      return data.access_token;
    }
  } catch (err) {
    console.warn("Could not obtain auth token:", err);
  }
  return null;
}

test.describe("Alberto Documentation Screenshot Suite", () => {
  let token: string | null = null;

  test.beforeAll(async () => {
    token = await getAuthToken();
    const dirs = [
      "auth",
      "home",
      "chat",
      "agents",
      "automate",
      "integrations",
      "knowledge",
      "observability",
      "settings",
      "mobile",
    ];
    for (const d of dirs) {
      const p = path.join(screenshotsDir, d);
      if (!fs.existsSync(p)) {
        fs.mkdirSync(p, { recursive: true });
      }
    }
  });

  test("01: Login Screen", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${baseURL}/`);
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.goto(`${baseURL}/`);
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: path.join(screenshotsDir, "auth/login.png"),
      fullPage: false,
    });
  });

  test("02: Core Navigation & Subsystems", async ({ page }) => {
    test.setTimeout(60000);
    await page.setViewportSize({ width: 1440, height: 900 });

    if (token) {
      await page.addInitScript((jwt) => {
        window.localStorage.setItem("alberto_access_token", jwt);
        window.localStorage.setItem("forge_access_token", jwt);
      }, token);
    }

    await page.goto(`${baseURL}/`);
    await page.waitForSelector(".topbar", { timeout: 15000 }).catch(() => {});
    await page.evaluate(() => {
      const style = document.createElement("style");
      style.textContent = "* { transition: none !important; animation: none !important; }";
      document.head.appendChild(style);
    });
    await page.waitForTimeout(1200);

    // Expand sidebar if collapsed
    const expandBtn = page.locator('button[title="Expand sidebar"]');
    if (await expandBtn.isVisible().catch(() => false)) {
      await expandBtn.click({ timeout: 2000 }).catch(() => {});
      await page.waitForTimeout(300);
    }

    async function clickNav(groupName: string | null, itemName: string) {
      if (groupName) {
        const groupBtn = page.locator(`button:has-text("${groupName}")`).first();
        if (await groupBtn.isVisible().catch(() => false)) {
          await groupBtn.click({ timeout: 2000 }).catch(() => {});
          await page.waitForTimeout(200);
        }
      }
      const leaf = page.locator(`button.sidenav-item:has-text("${itemName}"), nav button:has-text("${itemName}"), button:has-text("${itemName}")`).first();
      if (await leaf.isVisible().catch(() => false)) {
        await leaf.click({ timeout: 2000 }).catch(() => {});
        await page.waitForTimeout(600);
      }
    }

    // 1. Home / Assistant Dashboard
    await clickNav(null, "Home");
    await page.screenshot({
      path: path.join(screenshotsDir, "home/dashboard.png"),
      fullPage: false,
    });

    // 2. Chat / Conversation view
    const chatInput = page.locator("textarea, input[placeholder*='Ask Alberto'], input[placeholder*='Ask']").first();
    if (await chatInput.isVisible().catch(() => false)) {
      await chatInput.fill("What can you help me with today?");
      await page.waitForTimeout(300);
    }
    await page.screenshot({
      path: path.join(screenshotsDir, "chat/chat-interface.png"),
      fullPage: false,
    });

    // 3. Workflows List
    await clickNav("Automate", "Workflows");
    await page.screenshot({
      path: path.join(screenshotsDir, "automate/workflows-list.png"),
      fullPage: false,
    });

    // 4. Workflow Canvas
    const wfCard = page.locator(".card, tr, .tile, div[class*='card']").filter({ hasText: /Untitled|workflow|Demo|Agent/i }).first();
    if (await wfCard.isVisible().catch(() => false)) {
      await wfCard.click({ timeout: 2000 }).catch(() => {});
      await page.waitForTimeout(1000);
      await page.screenshot({
        path: path.join(screenshotsDir, "automate/workflow-canvas.png"),
        fullPage: false,
      });
      await clickNav("Automate", "Workflows");
    }

    // 5. Automate Playground
    await clickNav("Automate", "Playground");
    await page.screenshot({
      path: path.join(screenshotsDir, "automate/playground.png"),
      fullPage: false,
    });

    // 6. Agents List
    await clickNav("Automate", "Agents");
    await page.screenshot({
      path: path.join(screenshotsDir, "agents/agent-list.png"),
      fullPage: false,
    });

    // 7. Integrations
    await clickNav("Integrations", "Integrations");
    await page.screenshot({
      path: path.join(screenshotsDir, "integrations/integrations-list.png"),
      fullPage: false,
    });

    // 8. Tools
    await clickNav("Integrations", "Tools");
    await page.screenshot({
      path: path.join(screenshotsDir, "integrations/tools-list.png"),
      fullPage: false,
    });

    // 9. Auth & Credentials
    await clickNav("Integrations", "Auth & Credentials");
    await page.screenshot({
      path: path.join(screenshotsDir, "integrations/auth-credentials.png"),
      fullPage: false,
    });

    // 10. Documents
    await clickNav("Knowledge", "Documents");
    await page.screenshot({
      path: path.join(screenshotsDir, "knowledge/documents.png"),
      fullPage: false,
    });

    // 11. Vector Store
    await clickNav("Knowledge", "Vector Store");
    await page.screenshot({
      path: path.join(screenshotsDir, "knowledge/vector-store.png"),
      fullPage: false,
    });

    // 12. Knowledge Graph
    await clickNav("Knowledge", "Knowledge Graph");
    await page.screenshot({
      path: path.join(screenshotsDir, "knowledge/knowledge-graph.png"),
      fullPage: false,
    });

    // 13. Long-Term Memory
    await clickNav("Knowledge", "Long-Term Memory");
    await page.screenshot({
      path: path.join(screenshotsDir, "knowledge/memory.png"),
      fullPage: false,
    });

    // 14. Q&A Pairs
    await clickNav("Knowledge", "Q&A Pairs");
    await page.screenshot({
      path: path.join(screenshotsDir, "knowledge/qa-pairs.png"),
      fullPage: false,
    });

    // 15. Analytics
    await clickNav("Observability", "Analytics");
    await page.screenshot({
      path: path.join(screenshotsDir, "observability/analytics.png"),
      fullPage: false,
    });

    // 16. Traces
    await clickNav("Observability", "Traces");
    await page.screenshot({
      path: path.join(screenshotsDir, "observability/traces.png"),
      fullPage: false,
    });

    // 17. Settings & Tabs
    const settingsBtn = page.locator('button:has-text("Settings"), button[title="Settings"]').first();
    if (await settingsBtn.isVisible().catch(() => false)) {
      await settingsBtn.click({ timeout: 2000 }).catch(() => {});
      await page.waitForTimeout(800);
      await page.screenshot({
        path: path.join(screenshotsDir, "settings/models-providers.png"),
        fullPage: false,
      });

      const tabs = [
        { name: "Secrets & Credentials", file: "settings/secrets-credentials.png" },
        { name: "Members & Roles", file: "settings/members.png" },
        { name: "Guardrails & Egress", file: "settings/guardrails.png" },
        { name: "Advanced", file: "settings/advanced.png" },
      ];
      for (const t of tabs) {
        const tabBtn = page.locator(`button:has-text("${t.name}")`).first();
        if (await tabBtn.isVisible().catch(() => false)) {
          await tabBtn.click({ timeout: 2000 }).catch(() => {});
          await page.waitForTimeout(400);
          await page.screenshot({
            path: path.join(screenshotsDir, t.file),
            fullPage: false,
          });
        }
      }
    }
  });

  test("03: Mobile Viewport Screenshots", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    if (token) {
      await page.addInitScript((jwt) => {
        window.localStorage.setItem("alberto_access_token", jwt);
        window.localStorage.setItem("forge_access_token", jwt);
      }, token);
    }
    await page.goto(`${baseURL}/`);
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: path.join(screenshotsDir, "mobile/home-mobile.png"),
      fullPage: false,
    });

    const chatTab = page.locator('button:has-text("Chat"), button:has-text("Assistant"), nav button').first();
    if (await chatTab.isVisible().catch(() => false)) {
      await chatTab.click({ timeout: 2000 }).catch(() => {});
      await page.waitForTimeout(500);
    }
    await page.screenshot({
      path: path.join(screenshotsDir, "mobile/chat-mobile.png"),
      fullPage: false,
    });
  });
});
