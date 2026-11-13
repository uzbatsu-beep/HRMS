import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Page } from "@playwright/test";
import type { DemoSeed } from "./global-setup";

export function demo(): DemoSeed {
  return JSON.parse(
    readFileSync(resolve(process.cwd(), "e2e", ".tmp", "seed.json"), "utf8"),
  ) as DemoSeed;
}

export async function loginUI(
  page: Page, username = process.env.E2E_ADMIN_USERNAME,
  password = process.env.E2E_ADMIN_PASSWORD,
): Promise<void> {
  if (!username || !password) throw new Error("E2E credentials are missing");
  await page.goto("/#access");
  const form = page.locator("form.auth-form").first();
  await form.getByLabel("Имя пользователя").fill(username);
  await form.getByLabel("Пароль").fill(password);
  await form.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.locator(".auth-current").getByText(username)).toBeVisible();
  await expect(page.locator(".workspace-user")).toContainText(username);
}
