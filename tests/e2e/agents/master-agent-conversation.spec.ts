import { Page } from "@playwright/test";
import { test, expect } from "../fixtures";
import { DataFixture } from "../fixtures/data.fixture";

test.describe("Alberto Master Agent & Conversational Intelligence E2E", () => {
  test.beforeEach(async ({ page, data }: { page: Page; data: DataFixture }) => {
    await data.getOrCreateDefaultProject();
    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 15000 });
  });

  test("renders Master Agent chat composer and context metrics", async ({ page }: { page: Page }) => {
    // Check for chat composer textarea
    const chatInput = page.locator('textarea[placeholder*="Ask Alberto anything"]');
    await expect(chatInput).toBeVisible();

    // Check for thinking toggle button (Fast / Deep)
    const thinkingBtn = page.locator('button[title*="Thinking:"]');
    await expect(thinkingBtn).toBeVisible();

    // Check for send message button
    const sendBtn = page.locator('button[title*="Send message"]');
    await expect(sendBtn).toBeVisible();
  });

  test("toggles thinking mode between Fast Butler and Deep Agent", async ({ page }: { page: Page }) => {
    const thinkingBtn = page.locator('button[title*="Thinking:"]');
    const initialText = await thinkingBtn.innerText();

    await thinkingBtn.click();
    await page.waitForTimeout(300);

    const nextText = await thinkingBtn.innerText();
    expect(nextText).not.toBe(initialText);

    // Toggle back
    await thinkingBtn.click();
    await page.waitForTimeout(300);
    expect(await thinkingBtn.innerText()).toBe(initialText);
  });

  test("sends message and manages conversational turn state", async ({ page }: { page: Page }) => {
    const chatInput = page.locator('textarea[placeholder*="Ask Alberto anything"]');
    await chatInput.fill("Hello Alberto, summarize system capabilities.");

    const sendBtn = page.locator('button[title*="Send message"]');
    await sendBtn.click();

    // Expect user message tile to appear in conversational stream
    await expect(page.locator('text="Hello Alberto, summarize system capabilities."')).toBeVisible({ timeout: 10000 });

    // Verify input clears after submission
    await expect(chatInput).toHaveValue("");
  });
});
