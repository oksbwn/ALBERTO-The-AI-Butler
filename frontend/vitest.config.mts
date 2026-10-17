import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const appRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: "@", replacement: appRoot },
      { find: /^@testing-library\/(.*)/, replacement: resolve(appRoot, "node_modules/@testing-library/$1") },
    ],
  },
  server: {
    fs: {
      allow: [appRoot, resolve(appRoot, "../tests")],
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: [resolve(appRoot, "../tests/frontend/setup.ts")],
    include: ["../tests/frontend/**/*.test.ts", "../tests/frontend/**/*.test.tsx"],
    restoreMocks: true,
  },
});
