import { expect, test } from "@playwright/test";

test("status page shows the empty state on a fresh database", async ({ page }) => {
  await page.goto("/status");
  await expect(page.getByTestId("status-empty")).toBeVisible();
});
