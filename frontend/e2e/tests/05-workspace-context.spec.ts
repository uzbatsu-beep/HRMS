import { test, expect } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("enterprise and department context is shared with personnel and work modules", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  const rail = page.locator(".workspace-rail");
  await rail.getByLabel("Предприятие").selectOption(seed.enterprise.id);
  await expect(rail).toContainText("E2E Автоматизация");
  await rail.getByRole("button", { name: /E2E Автоматизация/ }).click();
  await expect(page.getByRole("navigation", { name: "Контекстная навигация" }))
    .toContainText("E2E Автоматизация");
  await page.locator(".workspace-navigation").getByRole("link", { name: /Персонал/ }).click();
  await expect(page.locator("#personnel").getByLabel("Предприятие"))
    .toHaveValue(seed.enterprise.id);
  await expect(page.locator("#personnel .people-filters select").nth(1))
    .toHaveValue(seed.units.automation);
  await page.locator(".workspace-navigation").getByRole("link", {
    name: /Наряды и бригады/,
  }).click();
  await expect(page.locator("#work").getByLabel("Предприятие"))
    .toHaveValue(seed.enterprise.id);
  await expect(page.locator("#work").getByLabel("Подразделение"))
    .toHaveValue(seed.units.automation);
});

test("global search finds scoped staff across departments and preserves person focus", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  const rail = page.locator(".workspace-rail");
  await rail.getByLabel("Предприятие").selectOption(seed.enterprise.id);
  await rail.getByRole("button", { name: /E2E Автоматизация/ }).click();

  const input = page.getByRole("combobox", { name: "Глобальный поиск сотрудников" });
  await input.fill(seed.people.otherUnit.last_name);
  const matches = page.getByRole("listbox", { name: "Найденные сотрудники" });
  await expect(matches).toContainText(seed.people.otherUnit.last_name);
  await matches.getByRole("option", { name: /E2E Механикова/ }).click();
  await expect(page).toHaveURL(/#personnel$/);
  await expect(page.locator("#personnel")).toContainText(seed.people.otherUnit.last_name);
  await expect(rail.getByRole("button", { name: /E2E Механики/ }))
    .toHaveClass(/active/);

  const breadcrumbs = page.getByRole("navigation", { name: "Контекстная навигация" });
  await expect(breadcrumbs).toContainText(seed.people.otherUnit.last_name);
  await page.locator(".workspace-navigation").getByRole("link", {
    name: /Документы и допуски/,
  }).click();
  await expect(page.locator("#credentials").getByLabel("Специалист"))
    .toHaveValue(seed.people.otherUnit.id);
  await page.locator(".workspace-navigation").getByRole("link", {
    name: /Смены и загрузка/,
  }).click();
  await expect(page.locator(".av-panel").getByLabel("Сотрудник"))
    .toHaveValue(seed.people.otherUnit.id);
});

test("logout clears enterprise/person context before showing scoped viewer", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  const rail = page.locator(".workspace-rail");
  await rail.getByLabel("Предприятие").selectOption(seed.enterprise.id);
  await rail.getByRole("button", { name: /E2E Автоматизация/ }).click();
  await rail.locator(".rail-person").filter({
    hasText: seed.people.lead.last_name,
  }).click();
  await expect(page.getByRole("navigation", { name: "Контекстная навигация" }))
    .toContainText(seed.people.lead.last_name);

  await page.goto("/#access");
  await page.locator(".auth-current").getByRole("button", { name: "Выйти" }).click();
  await expect(rail).toContainText("Для просмотра структуры предприятия");
  await expect(page.getByRole("navigation", { name: "Контекстная навигация" }))
    .not.toContainText(seed.people.lead.last_name);
  await loginUI(page, seed.users.viewer, process.env.E2E_ACTOR_PASSWORD);
  await expect(rail).toContainText("E2E Механики");
  await expect(rail).not.toContainText("E2E Автоматизация");
  await expect(rail).not.toContainText(seed.people.lead.last_name);
  await expect(page.getByRole("navigation", { name: "Контекстная навигация" }))
    .not.toContainText(seed.people.lead.last_name);
});
