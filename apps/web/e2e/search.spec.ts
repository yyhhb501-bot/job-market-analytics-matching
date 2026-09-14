import { expect, test } from "@playwright/test";

test("home page lists seeded jobs", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("results-head")).toContainText("8 个结果");
  await expect(page.getByTestId("job-grid").locator('[data-testid="job-card"]')).toHaveCount(8);
});

test("keyword search filters results", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("search-q").fill("analyst");
  await page.getByTestId("search-submit").click();
  await expect(page).toHaveURL(/q=analyst/);
  await expect(page.getByTestId("job-grid").locator('[data-testid="job-card"]')).toHaveCount(1);
  await expect(page.getByTestId("job-grid")).toContainText("Oz Corp");
});

test("country filter narrows to AU jobs", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("search-country").selectOption("AU");
  await page.getByTestId("search-submit").click();
  await expect(page).toHaveURL(/country=AU/);
  const cards = page.getByTestId("job-grid").locator('[data-testid="job-card"]');
  await expect(cards).toHaveCount(2);
  await expect(page.getByTestId("job-grid")).toContainText("Woolworths Group");
});

test("no-match query shows empty state", async ({ page }) => {
  await page.goto("/?q=zzz-no-such-job");
  await expect(page.getByTestId("results-empty")).toBeVisible();
});
