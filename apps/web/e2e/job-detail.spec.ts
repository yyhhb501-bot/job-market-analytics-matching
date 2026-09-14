import { expect, test } from "@playwright/test";

test("job detail renders from a search result", async ({ page }) => {
  await page.goto("/?q=analyst");
  const firstCard = page.getByTestId("job-card").first();
  await firstCard.getByRole("link", { name: "查看详情" }).click();

  await expect(page.getByTestId("job-detail")).toBeVisible();
  await expect(page.getByTestId("job-detail").getByRole("heading", { level: 1 })).toHaveText(
    "Data Analyst"
  );
  await expect(page.getByTestId("job-detail")).toContainText("Oz Corp");
  await expect(page.getByTestId("job-detail")).toContainText("返回搜索");
});
