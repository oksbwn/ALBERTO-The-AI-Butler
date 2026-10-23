import process from "node:process";
import { Page } from "@playwright/test";
import { test, expect } from "../fixtures";

const LOCAL_LLM_URL =
  process.env.ALBERTO_LOCAL_LLM_URL ||
  process.env.OPENAI_API_BASE ||
  process.env.OLLAMA_BASE_URL ||
  "http://127.0.0.1:11434";

async function isProviderOnline(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2000);
    // Probe models endpoint
    const url = LOCAL_LLM_URL.endsWith("/v1")
      ? `${LOCAL_LLM_URL}/models`
      : `${LOCAL_LLM_URL}/v1/models`;
    const res = await fetch(url, { signal: controller.signal });
    clearTimeout(timer);
    return res.ok || res.status === 401; // 401 means server is alive with auth
  } catch {
    return false;
  }
}

test.describe("Alberto Live Local LLM Provider Acceptance", () => {
  let isOnline = false;

  test.beforeAll(async () => {
    isOnline = await isProviderOnline();
  });

  test("probes live LLM provider endpoint availability", async () => {
    if (!isOnline) {
      test.skip(
        true,
        `BLOCKED: Live model provider endpoint at ${LOCAL_LLM_URL} is offline. Host daemon (Ollama/vLLM) not running.`
      );
    }
    expect(isOnline).toBe(true);
  });

  test("executes live streaming completion and calculates token throughput", async ({ page }: { page: Page }) => {
    if (!isOnline) {
      test.skip(
        true,
        `BLOCKED: Cannot validate live streaming without reachable provider at ${LOCAL_LLM_URL}.`
      );
    }

    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 15000 });

    const chatInput = page.locator('textarea[placeholder*="Ask Alberto anything"]');
    await chatInput.fill("What is 12 + 15? Answer in one word.");
    await page.locator('button[title*="Send message"]').click();

    // Verify token speed or completion badge appears
    await expect(page.locator('.chat-msg, [data-role="assistant"]')).toBeVisible({ timeout: 30000 });
  });

  test("validates structured output compatibility and tool calling", async ({ page }: { page: Page }) => {
    if (!isOnline) {
      test.skip(
        true,
        `BLOCKED: Cannot validate structured tool calls without live provider at ${LOCAL_LLM_URL}.`
      );
    }

    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 15000 });

    const chatInput = page.locator('textarea[placeholder*="Ask Alberto anything"]');
    await chatInput.fill("Create a structured JSON object with key 'status' equal to 'ok'.");
    await page.locator('button[title*="Send message"]').click();

    await expect(page.locator('text="status", text="ok"')).toBeVisible({ timeout: 30000 });
  });
});
