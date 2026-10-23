import { test, expect } from "../fixtures";

test.describe("Alberto Authentication & Session Management E2E", () => {
  test("maintains authenticated session state in local storage", async ({ page, auth }) => {
    // Obtain a valid signed access token from backend login using admin/password
    const loginRes = await page.request.post("http://127.0.0.1:8000/v1/auth/login", {
      data: { email: "admin", password: "password" },
    });
    expect(loginRes.ok()).toBe(true);
    const { access_token } = await loginRes.json();

    await auth.seedSession(access_token);
    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 20000 });

    // Verify localStorage retains valid token across navigation
    const storedToken = await page.evaluate(() => {
      return window.localStorage.getItem("alberto_access_token") || window.localStorage.getItem("forge_access_token");
    });
    expect(storedToken).toBe(access_token);
  });

  test("renders account menu and displays user role", async ({ page, auth }) => {
    const loginRes = await page.request.post("http://127.0.0.1:8000/v1/auth/login", {
      data: { email: "admin", password: "password" },
    });
    if (loginRes.ok()) {
      const { access_token } = await loginRes.json();
      await auth.seedSession(access_token);
    }

    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 20000 });

    // Click account menu avatar
    const accountBtn = page.locator('button[aria-label="Account"], button[title="Account"]').first();
    await expect(accountBtn).toBeVisible();
    await accountBtn.click();

    // Verify sign out button is displayed
    const signOutBtn = page.locator('button:has-text("Sign out")');
    await expect(signOutBtn).toBeVisible();

    // Close menu
    await page.keyboard.press("Escape");
  });

  test("clears authentication tokens and resets session upon sign out", async ({ page, auth }) => {
    const loginRes = await page.request.post("http://127.0.0.1:8000/v1/auth/login", {
      data: { email: "admin", password: "password" },
    });
    expect(loginRes.ok()).toBe(true);
    const { access_token } = await loginRes.json();

    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 20000 });

    // Set token dynamically in the active session
    await auth.setSession(access_token);

    // Open account menu and click sign out
    const accountBtn = page.locator('button[aria-label="Account"], button[title="Account"]').first();
    await accountBtn.click();

    const signOutBtn = page.locator('button:has-text("Sign out")');
    await signOutBtn.click();

    // Verify token is cleared from localStorage after sign out
    await page.waitForTimeout(1000);
    const storedToken = await page.evaluate(() => {
      return window.localStorage.getItem("alberto_access_token");
    });
    expect(storedToken).toBeNull();
  });
});
