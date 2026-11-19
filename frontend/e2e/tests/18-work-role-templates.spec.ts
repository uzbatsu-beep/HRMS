import { test, expect } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("admin applies scoped work template; worker cannot bypass org scope", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  await page.goto("/#organization");
  await page.locator(".org-toolbar").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  const matrix = page.locator(".org-permission-matrix");
  await expect(matrix).toBeVisible();
  await matrix.getByLabel("Подразделение для полномочий")
    .selectOption(seed.units.automation);
  await matrix.getByLabel("Пользователь для полномочий")
    .selectOption({ label: seed.users.viewer + " (viewer)" });
  const template = matrix.getByLabel("Шаблон должностной функции");
  await expect(template.locator("option")).toHaveCount(4);
  await template.selectOption("work.dispatcher");
  await matrix.getByRole("button", { name: "Применить шаблон" }).click();
  await expect(matrix.getByRole("status")).toContainText("Шаблон применён");

  await loginUI(page, seed.users.viewer, process.env.E2E_ACTOR_PASSWORD);
  const url = "/api/v1/work/orders/" + seed.work.id + "/capabilities";
  const inaccessible = await page.request.get(url);
  expect(inaccessible.status()).toBe(404);

  await loginUI(page);
  const me = await page.request.get("/api/v1/auth/me");
  const csrf = (await me.json() as { csrf_token: string }).csrf_token;
  const userResponse = await page.request.get("/api/v1/auth/users");
  const users = await userResponse.json() as { id: string; username: string }[];
  const viewer = users.find((user) => user.username === seed.users.viewer);
  expect(viewer).toBeDefined();
  const scope = await page.request.post("/api/v1/org/scopes", {
    headers: { "X-CSRF-Token": csrf },
    data: {
      user_id: viewer!.id,
      unit_id: seed.units.automation, include_descendants: false,
    },
  });
  expect(scope.status()).toBe(201);
  await loginUI(page, seed.users.viewer, process.env.E2E_ACTOR_PASSWORD);
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
