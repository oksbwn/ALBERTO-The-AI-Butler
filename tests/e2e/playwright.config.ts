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

const nextBin = process.platform === "win32"
  ? path.join(repoRoot, "frontend/node_modules/.bin/next.cmd")
  : path.join(repoRoot, "frontend/node_modules/.bin/next");

const testDataDir = path.join(repoRoot, "data/test_e2e");
const testBackendPort = process.env.PLAYWRIGHT_BACKEND_PORT || "8005";
const testPort = process.env.PLAYWRIGHT_PORT || "3005";
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${testPort}`;
const apiURL = process.env.ALBERTO_API_URL || `http://127.0.0.1:${testBackendPort}`;
process.env.ALBERTO_API_URL = apiURL;
process.env.FORGE_API_URL = apiURL;
process.env.ALBERTO_DATA_DIR = testDataDir;
process.env.FORGE_DATA_DIR = testDataDir;
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
          command: `"${pythonBin}" -m uvicorn alberto.main:app --host 127.0.0.1 --port ${testBackendPort}`,
          url: `http://127.0.0.1:${testBackendPort}/health`,
          reuseExistingServer: false,
          timeout: 45000,
          cwd: repoRoot,
          env: {
            ...process.env,
            PYTHONPATH: path.join(repoRoot, "backend"),
            PORT: testBackendPort,
            ALBERTO_PORT: testBackendPort,
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
            ALBERTO_CORS_ORIGINS: `http://localhost:${testPort},http://127.0.0.1:${testPort},http://localhost:3000,http://127.0.0.1:3000`,
            FORGE_CORS_ORIGINS: `http://localhost:${testPort},http://127.0.0.1:${testPort},http://localhost:3000,http://127.0.0.1:3000`,
          },
        },
        {
          command: `"${nextBin}" dev -p ${testPort}`,
          url: `http://127.0.0.1:${testPort}`,
          reuseExistingServer: false,
          timeout: 60000,
          cwd: path.join(repoRoot, "frontend"),
          env: {
            ...process.env,
            PORT: testPort,
            ALBERTO_API_URL: `http://127.0.0.1:${testBackendPort}`,
            FORGE_API_URL: `http://127.0.0.1:${testBackendPort}`,
            NEXT_PUBLIC_ALBERTO_API_URL: `http://127.0.0.1:${testBackendPort}`,
            NEXT_PUBLIC_FORGE_API_URL: `http://127.0.0.1:${testBackendPort}`,
          },
        },
      ],
});
