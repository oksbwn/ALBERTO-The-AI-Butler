import { defineConfig, devices } from "@playwright/test";
import path from "path";
import fs from "fs";

const repoRoot = path.resolve(__dirname, "../..");
const pythonBin = process.platform === "win32"
  ? (fs.existsSync(path.join(repoRoot, "backend/.venv/Scripts/python.exe"))
      ? path.join(repoRoot, "backend/.venv/Scripts/python.exe")
      : "python")
  : (fs.existsSync(path.join(repoRoot, "backend/.venv/bin/python"))
      ? path.join(repoRoot, "backend/.venv/bin/python")
      : "python3");

const testDataDir = path.join(repoRoot, "data/test_e2e");
const testPort = process.env.PLAYWRIGHT_PORT || "3000";
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${testPort}`;
const isCI = !!process.env.CI;

export default defineConfig({
  testDir: __dirname,
  timeout: 45000,
  expect: {
    timeout: 10000,
  },
  fullyParallel: false, // Ensure sequential test runs on SQLite test database
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: 1,
  outputDir: path.join(repoRoot, "test-results"),
  reporter: [
    ["list"],
    [
      "html",
      {
        outputFolder: path.join(repoRoot, "playwright-report"),
        open: "never",
      },
    ],
    [
      "json",
      {
        outputFile: path.join(repoRoot, "test-results/test-results.json"),
      },
    ],
  ],
  use: {
    baseURL,
    actionTimeout: 10000,
    navigationTimeout: 15000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: "e2e",
      testMatch: [
        /functional\/.*\.spec\.ts/,
        /workflows\/.*\.spec\.ts/,
        /agents\/.*\.spec\.ts/,
        /orchestration\/.*\.spec\.ts/,
        /memory-graph\/.*\.spec\.ts/,
        /security\/.*\.spec\.ts/,
        /automation\/.*\.spec\.ts/,
      ],
      use: {
        ...devices["Desktop Chrome"],
      },
    },
    {
      name: "live",
      testMatch: [/live-llm\/.*\.spec\.ts/],
      use: {
        ...devices["Desktop Chrome"],
      },
    },
    {
      name: "docker",
      testMatch: [/docker\/.*\.spec\.ts/],
      use: {
        ...devices["Desktop Chrome"],
        baseURL: process.env.DOCKER_TEST_URL || "http://127.0.0.1:8000",
      },
    },
  ],
  webServer: process.env.PLAYWRIGHT_NO_WEBSERVER
    ? undefined
    : [
        {
          command: `"${pythonBin}" -m uvicorn alberto.main:app --host 127.0.0.1 --port 8000`,
          url: "http://127.0.0.1:8000/health",
          reuseExistingServer: true,
          timeout: 40000,
          cwd: repoRoot,
          env: {
            ...process.env,
            PYTHONPATH: path.join(repoRoot, "backend"),
            ALBERTO_DATA_DIR: testDataDir,
            FORGE_DATA_DIR: testDataDir,
            ALBERTO_DATABASE_URL: `sqlite+aiosqlite:///${path.join(testDataDir, "db/alberto.db").replace(/\\/g, "/")}`,
            ALBERTO_CHECKPOINT_DB: path.join(testDataDir, "db/checkpoints.sqlite").replace(/\\/g, "/"),
            ALBERTO_CHECKPOINT_BACKEND: "sqlite",
            ALBERTO_ENABLE_SCHEDULER: "false",
            FORGE_AUTH_REQUIRED: "false",
            ALBERTO_DEV_ALLOW_ANONYMOUS_OWNER: "true",
            FORGE_DEV_ALLOW_ANONYMOUS_OWNER: "true",
            ALBERTO_BOOTSTRAP_ADMIN_EMAIL: "admin",
            FORGE_BOOTSTRAP_ADMIN_EMAIL: "admin",
            ALBERTO_BOOTSTRAP_ADMIN_PASSWORD: "password",
            FORGE_BOOTSTRAP_ADMIN_PASSWORD: "password",
            ALBERTO_SEED_DEMO: "true",
          },
        },
        {
          command: "npm run dev",
          url: "http://127.0.0.1:3000",
          reuseExistingServer: true,
          timeout: 40000,
          cwd: path.join(repoRoot, "frontend"),
          env: {
            ...process.env,
            PORT: "3000",
            ALBERTO_API_URL: "http://127.0.0.1:8000",
            FORGE_API_URL: "http://127.0.0.1:8000",
          },
        },
      ],
});
