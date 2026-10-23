import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8011;
const WEB_PORT = 3011;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "line",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"],
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  } }],
  webServer: [
    {
      command: "node e2e/api-server.mjs",
      url: `http://127.0.0.1:${API_PORT}/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run build && npm run start -- --hostname 127.0.0.1 --port 3011",
      url: `http://127.0.0.1:${WEB_PORT}/`,
      timeout: 240_000,
      reuseExistingServer: !process.env.CI,
      env: {
        API_BASE_URL: `http://127.0.0.1:${API_PORT}`,
        NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${API_PORT}`,
        API_KEY: "e2e-api-key",
        WEB_UI_USERNAME: "admin",
        WEB_UI_PASSWORD: "e2e-operator-password",
        SESSION_SECRET: "e2e-session-secret",
      },
    },
  ],
});
