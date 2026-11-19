import { test, expect } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("keyboard skip moves to main without corrupting hash route", async ({ page }) => {
  await page.goto("/#dashboard");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("button", { name: "Перейти к основному содержимому" });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  await expect(page).toHaveURL(/#dashboard$/);
});

test("mobile navigation closes with Escape and backdrop, preserving focus", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await loginUI(page);
  const menu = page.getByRole("button", { name: "Открыть меню" });
  await menu.click();
  await expect(page.locator("#workspace-navigation")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#workspace-navigation")).toBeHidden();
  await expect(menu).toBeFocused();
  await menu.click();
  await page.getByRole("button", { name: "Закрыть навигацию" }).click({
    position: { x: 370, y: 400 },
  });
  await expect(page.locator("#workspace-navigation")).toBeHidden();
  await expect(menu).toBeFocused();
});

test("global staff search supports keyboard selection and scoped navigation", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  const input = page.getByRole("combobox", { name: "Глобальный поиск сотрудников" });
  await input.fill(seed.people.otherUnit.last_name);
  const list = page.getByRole("listbox", { name: "Найденные сотрудники" });
  const match = list.getByRole("option", { name: /E2E Механикова/ });
  await expect(match).toBeVisible();
  await input.press("ArrowDown");
  await expect(match).toHaveAttribute("aria-selected", "true");
  await expect(input).toHaveAttribute("aria-activedescendant", /workspace-search-option-/);
  await input.press("Enter");
  await expect(page).toHaveURL(/#personnel$/);
  await expect(page.locator("#personnel")).toContainText(seed.people.otherUnit.last_name);
});

test("rail shows actionable error instead of claiming no employees", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  const rail = page.locator(".workspace-rail");
  await rail.getByLabel("Предприятие").selectOption(seed.enterprise.id);
  await expect(rail).toContainText(seed.people.lead.last_name);
  await page.route("**/api/v1/personnel/enterprises/*/persons?*", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json",
      body: '{"detail":"Temporary test failure"}' });
  });
  await rail.getByRole("button", { name: "Обновить данные" }).click();
  await expect(rail.getByRole("alert")).toContainText("Не удалось загрузить персонал");
  await expect(rail).not.toContainText("Сотрудники не найдены");
  await page.unroute("**/api/v1/personnel/enterprises/*/persons?*");
  await rail.getByRole("button", { name: "Повторить запрос" }).click();
  await expect(rail).toContainText(seed.people.lead.last_name);
});
