import type { Page } from "@playwright/test";

/** Must match the WEB_UI_PASSWORD configured in playwright.config.ts. */
export const E2E_WEB_UI_PASSWORD = "e2e-operator-password";
export const E2E_WEB_UI_USERNAME = "admin";

/**
 * Management flows (saved searches, match, boards) are gated behind the
 * operator login; the proxy rejects anonymous writes.
 */
export async function login(page: Page): Promise<void> {
  const response = await page.request.post("/api/login", {
    data: { username: E2E_WEB_UI_USERNAME, password: E2E_WEB_UI_PASSWORD },
  });
  if (response.status() !== 200) {
    throw new Error(`e2e login failed with status ${response.status()}`);
  }
}
