import { expect, test } from "@playwright/test";

import { PASSWORD, signup } from "./helpers";

test("CEO runs an objective end to end: plan, parallel work, approval, report", async ({ page }) => {
  const email = await signup(page, "E2E Labs");
  await expect(page.getByRole("heading", { name: /Good (morning|afternoon|evening), Karim/ })).toBeVisible();
  await expect(page.getByText("Engineering").first()).toBeVisible();
  await page.screenshot({ path: "test-results/screens/01-headquarters-empty.png", fullPage: true });

  await page.getByRole("link", { name: "New objective" }).first().click();
  await page.getByLabel("Title").fill("AI meeting assistant launch");
  await page
    .getByLabel("Instruction")
    .fill("Research and prepare a launch plan for an AI meeting assistant with product, architecture and marketing.");
  await page.getByRole("button", { name: "Start objective" }).click();
  await expect(page).toHaveURL(/\/objectives\/[0-9a-f-]+$/);

  // Persisted plan with dependencies is visible
  await expect(page.getByRole("list", { name: "Task dependency graph" })).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "Design the technical architecture" })).toBeVisible();

  // Level 3 action stops at human approval
  const approve = page.getByRole("button", { name: "Approve" }).first();
  await expect(approve).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: "test-results/screens/02-objective-awaiting-approval.png", fullPage: true });
  await approve.click();

  await expect(page.getByText("Completed", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole("tab", { name: "Executive report" }).click();
  await expect(page.getByText("Recommendation")).toBeVisible();
  await expect(page.getByText("No failures")).toBeVisible();
  await page.screenshot({ path: "test-results/screens/03-executive-report.png", fullPage: true });

  await page.getByRole("tab", { name: /Communication/ }).click();
  await expect(page.getByText("Revision requested", { exact: false }).first()).toBeVisible();

  await page.getByRole("tab", { name: /Artifacts/ }).click();
  await page.getByRole("link", { name: /Executive Report/ }).click();
  await expect(page.getByRole("heading", { name: /Executive Report/ }).first()).toBeVisible();
  await page.screenshot({ path: "test-results/screens/04-artifact.png", fullPage: true });

  await page.goto(page.url().replace(/\/artifacts\/.*/, "/inbox"));
  await expect(page.getByText(/Completed/).first()).toBeVisible();
  await page.goto(page.url().replace(/\/inbox$/, "/headquarters"));
  await expect(page.getByText("Tasks completed today")).toBeVisible();
  await page.screenshot({ path: "test-results/screens/05-headquarters-after.png", fullPage: true });

  // Session survives a fresh login
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/headquarters$/);
});

test("another organization cannot see the first one", async ({ browser }) => {
  const first = await browser.newPage();
  await signup(first, "Isolated Alpha");
  const alphaUrl = first.url();
  const context = await browser.newContext();
  const intruder = await context.newPage();
  await signup(intruder, "Isolated Beta");
  await intruder.goto(alphaUrl);
  await expect(intruder.getByText("This organization does not exist or you are not a member.")).toBeVisible();
  await Promise.all([first.close(), context.close()]);
});
