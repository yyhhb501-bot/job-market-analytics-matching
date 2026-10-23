import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test("saving a search persists it to the alerts page", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await page.getByTestId("search-q").fill("engineer");
  // The save form lives in a collapsed <details>; open it like a user would.
  await page.getByTestId("save-search-form").locator("xpath=..").getByText("保存搜索并接收新职位提醒").click();
  await page.getByTestId("save-search-form").getByLabel("保存此搜索").fill("e2e 工程师告警");
  await page.getByTestId("save-search-submit").click();

  const message = page.getByTestId("save-search-message");
  await expect(message).toBeVisible();
  await expect(message).toContainText("已保存");

  await page.goto("/alerts");
  await expect(page.getByText("e2e 工程师告警")).toBeVisible();
});

test("anonymous visitors cannot write through the proxy", async ({ page }) => {
  const response = await page.request.post("/api/proxy/saved-searches", {
    data: { name: "should-not-persist" },
  });
  expect(response.status()).toBe(401);

  await page.goto("/alerts", { waitUntil: "commit" });
  expect(page.url()).toContain("/login");
});
