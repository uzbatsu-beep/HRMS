import { test, expect } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("work matching rejects unqualified staff and dispatches verified crew", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  await page.goto("/#work");
  const orders = page.locator(".wm-orders");
  await expect(orders).toContainText(seed.work.code);
  await orders.getByRole("button").filter({ hasText: seed.work.code }).click();
  const list = page.locator(".wm-candidates");
  await expect(list).toContainText(seed.people.lead.last_name);
  await expect(list).toContainText(seed.people.unqualified.last_name);
  const blocked = list.locator(".wm-candidate").filter({
    hasText: seed.people.unqualified.last_name,
  });
  await expect(blocked).toContainText("Есть блокировки");
  await expect(blocked).toContainText(/Допуск|Компетенция/);
  const notReady = await page.request.post(
    "/api/v1/work/orders/" + seed.work.id + "/assign",
    {
      headers: { "X-CSRF-Token": (await (
        await page.request.get("/api/v1/auth/me")
      ).json()).csrf_token },
      data: { person_id: seed.people.unqualified.id },
    },
  );
  expect(notReady.status()).toBe(409);
  const lead = list.locator(".wm-candidate").filter({ hasText: seed.people.lead.last_name });
  await lead.getByRole("button", { name: /Назначить и забронировать/ }).click();
  await expect(page.locator(".wm-detail")).toContainText("Ответственный");
  await expect(page.locator(".wm-detail")).toContainText("Исполнитель назначен");

  const execution = page.locator(".wm-execution");
  await execution.getByLabel("Свободный кандидат").selectOption(seed.people.crew.id);
  await execution.getByRole("button", { name: "Добавить в бригаду" }).click();
  await expect(execution).toContainText(seed.people.crew.id);
  await expect(execution.locator(".wm-roster-line")).toHaveCount(2);

  await page.locator(".wm-detail").getByRole("button", {
    name: "Начать с повторной проверкой",
  }).click();
  await expect(page.locator(".wm-detail")).toContainText("В работе");

  const session = await (await page.request.get("/api/v1/auth/me")).json();
  const revoked = await page.request.post(
    "/api/v1/credentials/records/" + seed.credentials.crew + "/revoke",
    {
      headers: { "X-CSRF-Token": session.csrf_token },
      data: { reason: "E2E artificial revocation after technical work started." },
    },
  );
  expect(revoked.status()).toBe(200);
  await page.locator(".wm-execution").getByRole("button", {
    name: "Зафиксировать повторную проверку",
  }).click();
  await expect(page.locator(".wm-detail")).toContainText("На удержании");
  await expect(page.locator(".wm-execution")).toContainText(/Допуск|REVOKED/);
  await expect(page.locator(".wm-detail").getByRole("button", {
    name: "Отметить выполненным",
  })).toHaveCount(0);

  page.on("dialog", (dialog) => dialog.accept());
  await page.locator(".wm-detail").getByRole("button", { name: "Отменить наряд" }).click();
  await expect(page.locator(".wm-detail")).toContainText("Отменён");
  const finalOrder = await (await page.request.get(
    "/api/v1/work/orders/" + seed.work.id,
  )).json();
  expect(finalOrder.status).toBe("cancelled");
});
