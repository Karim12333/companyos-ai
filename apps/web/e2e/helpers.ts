import { expect, type Page } from "@playwright/test";

export const PASSWORD = "e2e-password-123";

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e4)}@example.com`;
}

export async function signup(page: Page, organization: string, email = uniqueEmail("ceo")): Promise<string> {
  await page.goto("/signup");
  await page.getByLabel("Your name").fill("Karim Test");
  await page.getByLabel("Organization name").fill(organization);
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page).toHaveURL(/\/headquarters$/);
  return email;
}
