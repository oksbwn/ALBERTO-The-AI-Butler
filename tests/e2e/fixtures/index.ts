import { test as baseTest, expect, Page } from "@playwright/test";
import { TelemetryCollector } from "./telemetry.fixture";
import { AuthFixture } from "./auth.fixture";
import { DataFixture } from "./data.fixture";

export interface AlbertoTestFixtures {
  telemetry: TelemetryCollector;
  auth: AuthFixture;
  data: DataFixture;
}

export const test = baseTest.extend<AlbertoTestFixtures>({
  data: async ({}, use: (r: DataFixture) => Promise<void>) => {
    const apiBase = process.env.ALBERTO_API_URL || "http://127.0.0.1:8000";
    const data = new DataFixture(apiBase);
    await data.init();
    await use(data);
    await data.cleanup();
  },
  page: async ({ page, data }: { page: Page; data: DataFixture }, use: (p: Page) => Promise<void>, testInfo) => {
    const isSignOutTest = testInfo.title.toLowerCase().includes("sign out");
    if (data.token && !isSignOutTest) {
      await page.addInitScript((jwt) => {
        window.localStorage.setItem("alberto_access_token", jwt);
        window.localStorage.setItem("forge_access_token", jwt);
      }, data.token);
    }
    await use(page);
  },
  telemetry: async ({ page }: { page: Page }, use: (r: TelemetryCollector) => Promise<void>) => {
    const collector = new TelemetryCollector(page);
    await use(collector);
    collector.assertNoCriticalErrors();
  },
  auth: async ({ page }: { page: Page }, use: (r: AuthFixture) => Promise<void>) => {
    const auth = new AuthFixture(page);
    await use(auth);
  },
});

export { expect };
export type { Page };
export { DataFixture };
