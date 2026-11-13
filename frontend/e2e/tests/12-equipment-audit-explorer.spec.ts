import { expect, request, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

type AuditPage = { enterprise_id: string; items: {
  id: string; action: string; actor_username: string;
  subject_id: string;
}[]; next_cursor: string | null; detail_payloads_included: false };

test("admin filters and pages redacted equipment audit without leaking details", async ({ page }) => {
  test.setTimeout(120_000);
  const seed = demo();
  await loginUI(page);
  const me = await page.request.get("/api/v1/auth/me");
  const csrf = (await me.json() as { csrf_token: string }).csrf_token;
  const prefix = "audit-21-" + Date.now().toString(36);
  let selected = "";
  for (let n = 0; n < 22; n++) {
    const asset = await page.request.post(
      "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/assets",
      {
        headers: { "X-CSRF-Token": csrf },
        data: {
          unit_id: seed.units.automation,
          code: prefix + "-" + n,
          name: "Synthetic audit asset " + n,
          kind: "robot",
        },
      },
    );
    expect(asset.status()).toBe(201);
    if (n === 21) selected = (await asset.json() as { id: string }).id;
  }

  await page.goto("/#equipment");
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  const explorer = page.locator(".equipment-audit-explorer");
  await expect(explorer).toBeVisible();
  await explorer.getByLabel("Тип события").selectOption("asset.created");
  await explorer.getByRole("button", { name: "Применить фильтр" }).click();
  await expect(explorer.locator(".equipment-audit-row")).toHaveCount(20);
  await expect(explorer.locator(".equipment-audit-row").first())
    .toContainText("Оборудование зарегистрировано");
  await expect(explorer).toContainText("Страница 1");
  await explorer.getByRole("button", { name: "Далее" }).click();
  await expect(explorer).toContainText("Страница 2");
  await expect(explorer.locator(".equipment-audit-row").first()).toBeVisible();

  await explorer.getByRole("button", { name: "Назад" }).click();
  await expect(explorer.locator(".equipment-audit-row")).toHaveCount(20);
  await expect(explorer).toContainText("Страница 1");

  await explorer.getByLabel("ID объекта события").fill(selected);
  await explorer.getByRole("button", { name: "Применить фильтр" }).click();
  await expect(explorer.locator(".equipment-audit-row")).toHaveCount(1);
  await expect(explorer.locator(".equipment-audit-row")).toContainText(selected);
  await expect(explorer.getByRole("button", { name: "Далее" })).toBeDisabled();
  const url = "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/audit/explorer";
  const result = await page.request.get(url + "?action=asset.created&subject_id=" + selected);
  expect(result.ok()).toBeTruthy();
  const payload = await result.json() as AuditPage;
  expect(payload.detail_payloads_included).toBe(false);
  expect(payload.items).toHaveLength(1);
  expect(payload.items[0].subject_id).toBe(selected);
  expect(payload.items[0].actor_username).toBeTruthy();
  expect(JSON.stringify(payload)).not.toContain("details_json");

  const baseURL = new URL(page.url()).origin;
  const manager = await request.newContext({ baseURL });
  const viewer = await request.newContext({ baseURL });
  try {
    const password = process.env.E2E_ACTOR_PASSWORD!;
    expect((await manager.post("/api/v1/auth/login", {
      data: { username: seed.users.manager, password },
    })).ok()).toBeTruthy();
    expect((await viewer.post("/api/v1/auth/login", {
      data: { username: seed.users.viewer, password },
    })).ok()).toBeTruthy();
    expect((await manager.get(url)).status()).toBe(403);
    expect((await viewer.get(url)).status()).toBe(403);
  } finally {
    await manager.dispose();
    await viewer.dispose();
  }
});
