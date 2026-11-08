import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig({
  ...base,
  testMatch: "submission.backend.spec.ts",
  testIgnore: [],
  timeout: 60000,
  use: { ...base.use, baseURL: "http://127.0.0.1:8019", actionTimeout: 7000 },
  webServer: {
    command: "../backend/.venv/bin/python ../tools/offline_acceptance_server.py",
    url: "http://127.0.0.1:8019/health",
    reuseExistingServer: false,
    timeout: 15000,
  },
});
