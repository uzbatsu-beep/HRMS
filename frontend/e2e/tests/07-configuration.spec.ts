import { expect, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("configurator publishes independent-approved person fields end-to-end", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  await page.goto("/#configuration");
  await page.locator(".workspace-rail").getByLabel("Предприятие").selectOption(seed.enterprise.id);
  const panel = page.locator("#configuration");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("Конфигуратор дополнительных полей");
  await panel.getByRole("button", { name: "Новый черновик на основе действующей" }).click();
  await panel.getByRole("button", { name: "Добавить поле" }).click();
  const field = panel.locator("fieldset.config-field");
  await field.getByLabel("Код").fill("service_note");
  await field.getByLabel("Название").fill("Примечание к участку");
  await panel.getByRole("button", { name: "Создать черновик" }).click();
  await expect(panel).toContainText("Новый черновик создан");
  await panel.getByRole("button", { name: "Проверить схему" }).click();
  await expect(panel).toContainText("Конфигурация прошла валидацию");
  await expect(panel.getByRole("button", { name: /Согласовать/ })).toBeDisabled();

  const adminAuth = await page.request.get("/api/v1/auth/me");
  expect(adminAuth.status()).toBe(200);
  const adminUser = (await adminAuth.json() as { user: { username: string } }).user.username;
  const adminPassword = process.env.E2E_ADMIN_PASSWORD!;
  const actorPassword = process.env.E2E_ACTOR_PASSWORD!;
  const adminLogin = await page.request.post("/api/v1/auth/login", {
    data: { username: adminUser, password: adminPassword },
  });
  expect(adminLogin.ok()).toBeTruthy();
  const csrf = (await adminLogin.json() as { csrf_token: string }).csrf_token;
  const unique = "e2e-config-reviewer-" + Date.now().toString(36);
  const createReviewer = await page.request.post("/api/v1/auth/users", {
    data: { username: unique, password: actorPassword, role: "admin" },
    headers: { "X-CSRF-Token": csrf },
  });
  expect(createReviewer.status()).toBe(201);
  const reviewed = await page.request.post("/api/v1/auth/login", {
    data: { username: unique, password: actorPassword },
  });
  expect(reviewed.ok()).toBeTruthy();
  const reviewerCsrf = (await reviewed.json() as { csrf_token: string }).csrf_token;

  const list = await page.request.get(
    "/api/v1/configuration/enterprises/" + seed.enterprise.id + "/versions",
  );
  expect(list.ok()).toBeTruthy();
  const version = (await list.json() as { id: string; status: string }[])[0];
  expect(version.status).toBe("validated");
  const approve = await page.request.post(
    "/api/v1/configuration/versions/" + version.id + "/approve",
    { headers: { "X-CSRF-Token": reviewerCsrf } },
  );
  expect(approve.status()).toBe(200);

  const back = await page.request.post("/api/v1/auth/login", {
    data: { username: adminUser, password: adminPassword },
  });
  const backCsrf = (await back.json() as { csrf_token: string }).csrf_token;
  const publish = await page.request.post(
    "/api/v1/configuration/versions/" + version.id + "/publish",
    { headers: { "X-CSRF-Token": backCsrf },
      data: { effective_on: new Date().toISOString().slice(0, 10) } },
  );
  expect(publish.status()).toBe(200);
  await page.goto("/#configuration");
  await page.reload(); // API mutation occurs outside React; reload session and published config.
  await expect(panel).toContainText("Действующая версия:");
  await expect(panel).toContainText("v1 (с");

  await page.goto("/#personnel");
  const item = page.locator(".people-item").filter({ hasText: seed.people.lead.last_name });
  await item.click();
  const custom = page.getByRole("region", { name: "Дополнительные поля сотрудника" });
  await expect(custom).toBeVisible();
  await custom.getByLabel("Примечание к участку").fill("Лабораторные данные");
  await custom.getByRole("button", { name: "Сохранить дополнительные поля" }).click();
  await expect(custom).toContainText("историей изменений");
  const saved = await page.request.get(
    "/api/v1/configuration/persons/" + seed.people.lead.id + "/fields",
  );
  const value = await saved.json() as { values: { service_note: string } };
  expect(value.values.service_note).toBe("Лабораторные данные");

  await page.request.post("/api/v1/auth/login", {
    data: { username: seed.users.viewer, password: actorPassword },
  });
  const hidden = await page.request.get(
    "/api/v1/configuration/persons/" + seed.people.lead.id + "/fields",
  );
  expect(hidden.status()).toBe(404);
});
