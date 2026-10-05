import { expect, test } from "@playwright/test";

import { signup } from "./helpers";

test("CEO can check status and navigate on mobile", async ({ page }) => {
  await signup(page, "Mobile Co");
  await expect(page.getByText("Waiting for approval")).toBeVisible();
  await page.screenshot({ path: "test-results/screens/mobile-headquarters.png", fullPage: true });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Objectives", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Objectives" })).toBeVisible();
});
