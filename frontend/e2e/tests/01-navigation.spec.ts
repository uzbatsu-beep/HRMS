import { test, expect } from "@playwright/test";
import { loginUI } from "../fixture";

test("guest has no access to personnel data; login updates topbar", async ({ page }) => {
  await page.goto("/#dashboard");
  await expect(page.getByRole("heading", { name: "Обзор", exact: true })).toBeVisible();
  await expect(page.locator(".workspace-rail")).toContainText("Для просмотра");
  await expect(page.locator(".workspace-navigation")).toBeVisible();
  await loginUI(page);
  await expect(page.locator(".workspace-rail")).toContainText("Структура и персонал");
});

test("left navigation and hash deep links show exactly one module", async ({ page }) => {
  await loginUI(page);
  await page.locator(".workspace-navigation")
    .getByRole("link", { name: /Документы и допуски/ }).click();
  await expect(page).toHaveURL(/#credentials$/);
  await expect(page.locator(".credentials-panel, #credentials").first()).toBeVisible();
  await expect(page.locator("#work")).toHaveCount(0);
  await page.goto("/#work");
  await expect(page.getByRole("heading", { name: "Наряды и бригады", exact: true })).toBeVisible();
  await expect(page.locator("#work")).toBeVisible();
  await page.reload();
  await expect(page.locator("#work")).toBeVisible();
  await page.goto("/#home");
  await expect(page.getByRole("heading", { name: "Обзор", exact: true })).toBeVisible();
});

test("mobile layout has operable navigation and real context below content", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await loginUI(page);
  const menu = page.getByRole("button", { name: "Открыть меню" });
  await expect(menu).toBeVisible();
  await menu.click();
  await expect(page.locator(".workspace-navigation")).toBeVisible();
  await page.locator(".workspace-navigation").getByRole("link", { name: /Персонал/ }).click();
  await expect(page).toHaveURL(/#personnel$/);
  await expect(page.locator(".workspace-navigation")).toBeHidden();
  await expect(page.locator(".workspace-rail")).toBeVisible();
  await expect.poll(async () =>
    page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2),
  ).toBeTruthy();
});
