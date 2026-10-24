import { Page } from "@playwright/test";

export interface TestUser {
  email: string;
  password: string;
  workspace?: string;
  token?: string;
}

export const DEFAULT_ADMIN_USER: TestUser = {
  email: "admin",
  password: "password",
};

export class AuthFixture {
  constructor(private page: Page) {}

  async seedSession(token: string) {
    await this.page.addInitScript((jwt) => {
      window.localStorage.setItem("alberto_access_token", jwt);
      window.localStorage.setItem("forge_access_token", jwt);
    }, token);
  }

  async setSession(token: string) {
    await this.page.evaluate((jwt) => {
      window.localStorage.setItem("alberto_access_token", jwt);
      window.localStorage.setItem("forge_access_token", jwt);
    }, token);
  }

  async clearSession() {
    await this.page.evaluate(() => {
      window.localStorage.removeItem("alberto_access_token");
      window.localStorage.removeItem("forge_access_token");
      window.localStorage.removeItem("alberto_refresh_token");
      window.localStorage.removeItem("forge_refresh_token");
    });
  }

  async login(user: { email: string; password: string } = DEFAULT_ADMIN_USER) {
    await this.page.goto("/");
    const loginForm = this.page.locator("form");
    if (await loginForm.isVisible()) {
      await this.page.fill('input[autoComplete="username"]', user.email);
      await this.page.fill('input[autoComplete="current-password"]', user.password);
      await this.page.click('button[type="submit"]');
      await this.page.waitForSelector(".topbar", { timeout: 15000 });
    }
  }

  async register(user: { email: string; password: string; workspace: string }) {
    await this.page.goto("/");
    const toggleBtn = this.page.locator('button:has-text("Create a workspace")');
    if (await toggleBtn.isVisible()) {
      await toggleBtn.click();
    }
    await this.page.fill('input[placeholder="Acme Inc"]', user.workspace);
    await this.page.fill('input[type="email"]', user.email);
    await this.page.fill('input[type="password"]', user.password);
    await this.page.click('button[type="submit"]');
    await this.page.waitForSelector(".topbar", { timeout: 15000 });
  }
}
