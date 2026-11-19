import { test, expect, type Page } from "@playwright/test";
import { demo, loginUI } from "../fixture";

async function switchUser(page: Page, username?: string, password?: string) {
  await page.goto("/#access");
  await page.locator(".auth-current").getByRole("button", { name: "Выйти" }).click();
  await loginUI(page, username, password);
}

test("admin applies scoped work template; worker cannot bypass org scope", async ({ page }) => {
  const seed = demo();
  const actor = "e2e-work-" + Date.now().toString(36);
  const password = process.env.E2E_ACTOR_PASSWORD!;
  await loginUI(page);
  const currentAdmin = await page.request.get("/api/v1/auth/me");
  const adminCsrf = (await currentAdmin.json() as { csrf_token: string }).csrf_token;
  const added = await page.request.post("/api/v1/auth/users", {
    headers: { "X-CSRF-Token": adminCsrf },
    data: { username: actor, password, role: "viewer" },
  });
  expect(added.status()).toBe(201);
  const actorId = (await added.json() as { id: string }).id;
  await page.goto("/#organization");
  await page.locator(".org-toolbar").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  const matrix = page.locator(".org-permission-matrix");
  await expect(matrix).toBeVisible();
  await matrix.getByLabel("Подразделение для полномочий")
    .selectOption(seed.units.automation);
  await matrix.getByLabel("Пользователь для полномочий")
    .selectOption({ label: actor + " (viewer)" });
  const template = matrix.getByLabel("Шаблон должностной функции");
  await expect(template.locator("option")).toHaveCount(4);
  await template.selectOption("work.dispatcher");
  await matrix.getByRole("button", { name: "Применить шаблон" }).click();
  await expect(matrix.getByRole("status")).toContainText("Шаблон применён");

  await switchUser(page, actor, password);
  const url = "/api/v1/work/orders/" + seed.work.id + "/capabilities";
  const inaccessible = await page.request.get(url);
  expect(inaccessible.status()).toBe(404);

  await switchUser(page);
  const me = await page.request.get("/api/v1/auth/me");
  const csrf = (await me.json() as { csrf_token: string }).csrf_token;
  const scope = await page.request.post("/api/v1/org/scopes", {
    headers: { "X-CSRF-Token": csrf },
    data: {
      user_id: actorId,
      unit_id: seed.units.automation, include_descendants: false,
    },
  });
  expect(scope.status()).toBe(201);
  await switchUser(page, actor, password);
  const response = await page.request.get(url);
  expect(response.status()).toBe(200);
  const capabilities = await response.json() as {
    assign: boolean; crew: boolean; start: boolean; create: boolean;
  };
  expect(capabilities.assign).toBe(true);
  expect(capabilities.crew).toBe(true);
  expect(capabilities.start).toBe(false);
  expect(capabilities.create).toBe(false);
  const current = await page.request.get("/api/v1/auth/me");
  const viewerCsrf = (await current.json() as { csrf_token: string }).csrf_token;
  const unauthorized = await page.request.post(
    "/api/v1/work/orders/" + seed.work.id + "/cancel",
    { headers: { "X-CSRF-Token": viewerCsrf } },
  );
  expect(unauthorized.status()).toBe(403);
});
