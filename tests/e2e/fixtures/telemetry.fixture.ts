import { test as base, Page } from "@playwright/test";

export interface TelemetryLogs {
  consoleErrors: string[];
  consoleWarnings: string[];
  pageErrors: Error[];
  failedRequests: { url: string; method: string; failure: string }[];
}

export class TelemetryCollector {
  readonly logs: TelemetryLogs = {
    consoleErrors: [],
    consoleWarnings: [],
    pageErrors: [],
    failedRequests: [],
  };

  constructor(private page: Page) {
    this.attach();
  }

  private attach() {
    this.page.on("console", (msg) => {
      const type = msg.type();
      const text = msg.text();
      if (type === "error") {
        // Filter out expected React dev warnings or benign test errors if any
        this.logs.consoleErrors.push(text);
      } else if (type === "warning") {
        this.logs.consoleWarnings.push(text);
      }
    });

    this.page.on("pageerror", (err) => {
      this.logs.pageErrors.push(err);
    });

    this.page.on("requestfailed", (request) => {
      const failure = request.failure()?.errorText || "Unknown failure";
      // Ignore aborts caused by test navigation
      if (!failure.includes("net::ERR_ABORTED")) {
        this.logs.failedRequests.push({
          url: request.url(),
          method: request.method(),
          failure,
        });
      }
    });
  }

  assertNoCriticalErrors() {
    // Assert no unhandled React runtime exceptions
    const criticalExceptions = this.logs.pageErrors.map((e) => e.message);
    if (criticalExceptions.length > 0) {
      throw new Error(`Critical page errors detected:\n${criticalExceptions.join("\n")}`);
    }

    // Filter out expected benign errors from console errors
    const fatalConsole = this.logs.consoleErrors.filter(
      (m) =>
        !m.includes("Failed to load resource") &&
        !m.includes("favicon") &&
        !m.includes("Fastembed") &&
        !m.includes("ResizeObserver")
    );
    if (fatalConsole.length > 5) {
      throw new Error(`Excessive console errors detected (${fatalConsole.length}):\n${fatalConsole.slice(0, 5).join("\n")}`);
    }
  }
}

export const test = base.extend<{ telemetry: TelemetryCollector }>({
  telemetry: async ({ page }, use) => {
    const telemetry = new TelemetryCollector(page);
    await use(telemetry);
    telemetry.assertNoCriticalErrors();
  },
});

export { expect } from "@playwright/test";
