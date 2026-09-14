import { expect, test } from "@playwright/test";

test("compare page renders US vs AU metrics", async ({ page }) => {
  await page.goto("/compare?a_country=US&b_country=AU");
  await expect(page.getByTestId("compare-summary")).toBeVisible();
  await expect(page.locator("table.runs-table")).toBeVisible();
  await expect(page.locator("table.runs-table")).toContainText("指标");
});

test("compare form submits and shows results", async ({ page }) => {
  await page.goto("/compare");
  await page.getByTestId("compare-form").locator("button[type=submit]").click();
  await expect(page).toHaveURL(/a_country=/);
  await expect(page.getByTestId("compare-summary")).toBeVisible();
});
