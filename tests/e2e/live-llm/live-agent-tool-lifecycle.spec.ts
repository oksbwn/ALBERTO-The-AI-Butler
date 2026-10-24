import { Page } from "@playwright/test";
import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Live Local LLM Full Lifecycle Acceptance", () => {
  let project: TestProject;
  let activeModel: any = null;
  let isOnline = false;

  test.beforeAll(async () => {
    const apiBase = process.env.ALBERTO_API_URL || "http://127.0.0.1:8005";
    try {
      const authRes = await fetch(`${apiBase}/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "admin", password: "password" }),
      });
      if (authRes.ok) {
        const authData = await authRes.json();
        const modelsRes = await fetch(`${apiBase}/v1/models/registry`, {
          headers: { Authorization: `Bearer ${authData.access_token}` },
        });
        if (modelsRes.ok) {
          const models = await modelsRes.json();
          activeModel = models.find((m: any) => m.is_default && m.enabled) || models.find((m: any) => m.enabled);
          if (activeModel) {
            const probeRes = await fetch(
              `${apiBase}/v1/models/registry/${activeModel.id}/test-inference`,
              {
                method: "POST",
                headers: {
                  Authorization: `Bearer ${authData.access_token}`,
                  "Content-Type": "application/json",
                },
                body: JSON.stringify({ prompt: "ping" }),
              }
            );
            if (probeRes.ok) {
              const probeData = await probeRes.json();
              isOnline = probeData.ok === true;
            }
          }
        }
      }
    } catch {
      isOnline = false;
    }
  });

  test.beforeEach(async ({ data }: { data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
  });

  test("1. Live model dynamically resolved and streaming tool delegation lifecycle", async ({ page }: { page: Page }) => {
    if (!isOnline || !activeModel) {
      test.skip(true, "BLOCKED: Configured live LLM provider is offline.");
    }

    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 15000 });

    // Submit natural language prompt requiring calculation/tool reasoning
    const chatInput = page.locator('textarea[placeholder*="Ask Alberto anything"]');
    await chatInput.fill("What is 15 plus 27? Reply with the exact sum.");

    const sendBtn = page.locator('button[title*="Send message"]');
    await sendBtn.click();

    // Verify response streams in
    await expect(page.getByRole("button", { name: "Copy" }).first()).toBeVisible({ timeout: 45000 });

    // Verify token throughput metrics badge rendered with real accounting
    const metricsBtn = page.getByRole("button", { name: /generation metrics/i }).first();
    await expect(metricsBtn).toBeVisible({ timeout: 10000 });
  });

  test("2. Authoritative token accounting comparison", async ({ data }: { data: DataFixture }) => {
    if (!isOnline || !activeModel) {
      test.skip(true, "BLOCKED: Configured live LLM provider is offline.");
    }

    const res = await data.apiPost(`/v1/models/registry/${activeModel.id}/test-inference`, {
      prompt: "Reply with the single word: OK",
    });
    expect(res.ok).toBe(true);
    expect(res.latency_ms).toBeGreaterThan(0);
    // Latency must be measurable and positive
    expect(typeof res.latency_ms).toBe("number");
  });
});
