import { expect, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

type Item = { id: string };
function localInput(value: Date): string {
  const p = (x: number) => String(x).padStart(2, "0");
  return String(value.getFullYear()) + "-" + p(value.getMonth() + 1)
    + "-" + p(value.getDate()) + "T" + p(value.getHours()) + ":" + p(value.getMinutes());
}

test("planned downtime is recorded, blocks linked job and can be cancelled", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  const auth = await page.request.get("/api/v1/auth/me");
  const csrf = (await auth.json() as { csrf_token: string }).csrf_token;
  const stamp = Date.now().toString(36);
  const code = "e2e-down-" + stamp;
  const assetCreated = await page.request.post(
    "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/assets", {
      headers: { "X-CSRF-Token": csrf },
      data: { code, name: "Synthetic maintenance robot", kind: "robot",
        unit_id: seed.units.automation },
    },
  );
  expect(assetCreated.status()).toBe(201);
  const asset = await assetCreated.json() as Item;
  const workSource = await page.request.get("/api/v1/work/orders/" + seed.work.id);
  const source = await workSource.json() as {
    activity_code: string; required_skills: { skill_id: string; min_level_id: string }[];
  };
  const begins = new Date(Date.now() + 5 * 60000);
  const ends = new Date(begins.getTime() + 30 * 60000);
  const workCreated = await page.request.post(
    "/api/v1/work/enterprises/" + seed.enterprise.id + "/orders", {
      headers: { "X-CSRF-Token": csrf },
      data: {
        code: "e2e-work-" + stamp,
        title: "Synthetic equipment service blocked by downtime",
        unit_id: seed.units.automation, activity_code: source.activity_code,
        starts_at: begins.toISOString(), ends_at: ends.toISOString(),
        required_skills: source.required_skills.map(x => ({
          skill_id: x.skill_id, min_level_id: x.min_level_id,
        })),
      },
    },
  );
  expect(workCreated.status()).toBe(201);
  const work = await workCreated.json() as Item;
  const link = await page.request.post(
    "/api/v1/equipment/orders/" + work.id + "/equipment", {
      headers: { "X-CSRF-Token": csrf }, data: { asset_id: asset.id },
    },
  );
  expect(link.status()).toBe(201);

  await page.goto("/#equipment");
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  const catalog = page.locator("#equipment");
  await catalog.locator(".equipment-list button").filter({ hasText: code }).click();
  const downtime = catalog.locator(".equipment-downtime");
  await expect(downtime).toBeVisible();
  await downtime.locator("summary").click();
  await downtime.getByLabel("Начало обслуживания")
    .fill(localInput(new Date(begins.getTime() + 5 * 60000)));
  await downtime.getByLabel("Окончание обслуживания")
    .fill(localInput(new Date(begins.getTime() + 15 * 60000)));
  await downtime.getByLabel("Причина / задание на обслуживание")
    .fill("Synthetic planned robot maintenance in disposable test");
  await downtime.getByRole("button", { name: "Зарегистрировать обслуживание" }).click();
  await expect(downtime).toContainText("Запланировано / действует");

  const before = await page.request.get(
    "/api/v1/equipment/orders/" + work.id + "/safety-package",
  );
  expect((await before.json() as { equipment_blockers: string[] }).equipment_blockers)
    .toContain("EQUIPMENT_DOWNTIME_CONFLICT");

  await expect(catalog.locator(".equipment-readiness")).toContainText(
    "Плановое обслуживание пересекается с работой",
  );
  await downtime.getByLabel("Причина отмены окна")
    .fill("Synthetic repair schedule cancelled after review");
  await downtime.getByRole("button", { name: "Отменить окно" }).click();
  await expect(downtime).toContainText("Отменено:");

  const after = await page.request.get(
    "/api/v1/equipment/orders/" + work.id + "/safety-package",
  );
  expect((await after.json() as { equipment_blockers: string[] }).equipment_blockers)
    .not.toContain("EQUIPMENT_DOWNTIME_CONFLICT");

  const retained = await page.request.get(
    "/api/v1/equipment/assets/" + asset.id + "/downtime",
  );
  expect(retained.ok()).toBeTruthy();
  const history = await retained.json() as {
    id: string; cancelled_at: string | null; cancel_reason: string | null;
  }[];
  expect(history).toHaveLength(1);
  expect(history[0].cancelled_at).not.toBeNull();
  expect(history[0].cancel_reason).toContain("cancelled");
});
