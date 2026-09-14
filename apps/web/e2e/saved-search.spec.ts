import { expect, test } from "@playwright/test";

test("saving a search persists it to the alerts page", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("search-q").fill("engineer");
  await page.getByTestId("save-search-form").getByLabel("保存此搜索").fill("e2e 工程师告警");
  await page.getByTestId("save-search-submit").click();

  const message = page.getByTestId("save-search-message");
  await expect(message).toBeVisible();
  await expect(message).toContainText("已保存");

  await page.goto("/alerts");
  await expect(page.getByText("e2e 工程师告警")).toBeVisible();
});
