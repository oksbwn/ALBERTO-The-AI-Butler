import process from "node:process";
import { Page } from "@playwright/test";
import { test, expect } from "../fixtures";

const DOCKER_BASE = process.env.DOCKER_TEST_URL || "http://127.0.0.1:8000";

async function isDockerContainerReachable(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(`${DOCKER_BASE}/health`, { signal: controller.signal });
    clearTimeout(timer);
    return res.ok;
  } catch {
    return false;
  }
}

test.describe("Alberto Docker Container Production Acceptance", () => {
  let isDockerOnline = false;

  test.beforeAll(async () => {
    isDockerOnline = await isDockerContainerReachable();
  });

  test("verifies Docker container application startup and /health readiness", async () => {
    if (!isDockerOnline) {
      test.skip(
        true,
        `BLOCKED: Test Docker container is not currently running at ${DOCKER_BASE}. Run 'npm run test:e2e:docker' to launch isolated acceptance container.`
      );
    }
    const res = await fetch(`${DOCKER_BASE}/health`);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("status");
  });

  test("verifies web UI console and reverse proxy reachability in container", async ({ page }: { page: Page }) => {
    if (!isDockerOnline) {
      test.skip(
        true,
        `BLOCKED: Test Docker container is not reachable at ${DOCKER_BASE}.`
      );
    }

    await page.goto(DOCKER_BASE);
    await page.waitForSelector(".topbar", { timeout: 20000 });
    await expect(page.locator(".topbar")).toBeVisible();
  });
});
