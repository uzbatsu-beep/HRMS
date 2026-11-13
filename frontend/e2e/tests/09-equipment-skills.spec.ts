import { expect, request, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("asset skill gates persist and scoped readiness shows permit blockers", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  await page.goto("/#equipment");
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  const panel = page.locator("#equipment");
  await expect(panel).toBeVisible();

  const stamp = Date.now().toString(36);
  const code = "e2e-robot-skill-" + stamp;
  const editor = panel.locator("details.equipment-editor");
  await editor.locator("summary").click();
  await editor.getByLabel("Код актива").fill(code);
  await editor.getByLabel("Наименование").fill("Синтетический робот обучения");
  await editor.getByLabel("Подразделение оборудования")
    .selectOption(seed.units.automation);
  await editor.getByRole("button", { name: "Создать актив" }).click();
  const assetItem = panel.locator(".equipment-list button").filter({ hasText: code });
  await expect(assetItem).toBeVisible();
  await assetItem.click();
  const assetList = await page.request.get(
    "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/assets",
  );
  const asset = (await assetList.json() as { id: string; code: string }[])
    .find(x => x.code === code);
  expect(asset).toBeDefined();

  const competence = "/api/v1/competence/enterprises/" + seed.enterprise.id;
  const skillsResponse = await page.request.get(competence + "/skills");
  const skill = (await skillsResponse.json() as { id: string; scale_id: string }[])[0];
  expect(skill).toBeDefined();
  const scalesResponse = await page.request.get(competence + "/scales");
  const scale = (await scalesResponse.json() as {
    id: string; levels: { id: string; ordinal: number }[];
  }[]).find(x => x.id === skill.scale_id);
  const high = scale!.levels.find(x => x.ordinal === 3);
  expect(high).toBeDefined();

  await panel.getByLabel("Компетенция оборудования").selectOption(skill.id);
  await panel.getByLabel("Уровень компетенции оборудования").selectOption(high!.id);
  await panel.getByLabel("Обоснование нового требования (не менее 10 символов)")
    .fill("Synthetic independently governed robot qualification requirement");
  await panel.getByRole("button", { name: "Предложить требование к навыку" }).click();
  await expect(panel.locator(".equipment-policy")).toContainText(
    "Ожидает утверждения",
  );
  const endpoint = "/api/v1/equipment/assets/" + asset!.id + "/policy-proposals";
  const proposals = await page.request.get(endpoint);
  const pending = (await proposals.json() as {
    id: string; skill_id: string; status: string;
  }[]).find(x => x.skill_id === skill.id && x.status === "pending");
  expect(pending).toBeDefined();
  const before = await page.request.get(
    "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/assets",
  );
  const notActive = (await before.json() as {
    id: string; required_skills: unknown[];
  }[]).find(x => x.id === asset!.id);
  expect(notActive?.required_skills).toHaveLength(0);

  const reviewer = await request.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const login = await reviewer.post("/api/v1/auth/login", {
      data: { username: seed.users.reviewer,
        password: process.env.E2E_ACTOR_PASSWORD },
    });
    expect(login.ok()).toBeTruthy();
    const reviewerCsrf = (await login.json() as { csrf_token: string }).csrf_token;
    const approval = await reviewer.post(endpoint + "/" + pending!.id + "/approve", {
      headers: { "X-CSRF-Token": reviewerCsrf },
      data: { note: "Independent reviewer approves synthetic robot skill requirement" },
    });
    expect(approval.status()).toBe(200);
  } finally {
    await reviewer.dispose();
  }
  await panel.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(panel.locator(".equipment-detail")).toContainText("уровень ≥ 3");
  const again = await page.request.get(
    "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/assets",
  );
  const updated = (await again.json() as {
    id: string; required_skills: { skill_id: string; min_ordinal: number }[];
  }[]).find(x => x.id === asset!.id);
  expect(updated?.required_skills[0].skill_id).toBe(skill.id);
  expect(updated?.required_skills[0].min_ordinal).toBe(3);

  const me = await page.request.get("/api/v1/auth/me");
  const csrf = (await me.json() as { csrf_token: string }).csrf_token;
  const workBefore = await page.request.get("/api/v1/work/orders/" + seed.work.id);
  const workSource = await workBefore.json() as {
    activity_code: string; required_skills: { skill_id: string; min_level_id: string }[];
  };
  const workCode = "e2e-readiness-" + stamp;
  const start = new Date(Date.now() + 5 * 60000);
  const created = await page.request.post(
    "/api/v1/work/enterprises/" + seed.enterprise.id + "/orders", {
      headers: { "X-CSRF-Token": csrf },
      data: {
        code: workCode, title: "Синтетическое задание проверки оборудования",
        unit_id: seed.units.automation, activity_code: workSource.activity_code,
        starts_at: start.toISOString(),
        ends_at: new Date(start.getTime() + 20 * 60000).toISOString(),
        required_skills: workSource.required_skills.map(x => ({
          skill_id: x.skill_id, min_level_id: x.min_level_id,
        })),
      },
    },
  );
  expect(created.status()).toBe(201);
  const work = await created.json() as { id: string };
  const attached = await page.request.post(
    "/api/v1/equipment/orders/" + work.id + "/equipment",
    { headers: { "X-CSRF-Token": csrf }, data: { asset_id: asset!.id } },
  );
  expect(attached.status()).toBe(201);

  await page.reload();
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  await expect(panel.locator(".equipment-readiness")).toContainText(workCode);
  await expect(panel.locator(".equipment-readiness")).toContainText(
    "Нет согласованного разрешения",
  );
  const current = await page.request.get(
    "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/readiness",
  );
  expect(current.ok()).toBeTruthy();
  const summary = await current.json() as {
    items: { work_order_id: string; crew_eligibility_checked: boolean;
      software_blockers: string[] }[];
  };
  const row = summary.items.find(x => x.work_order_id === work.id);
  expect(row).toBeDefined();
  expect(row?.crew_eligibility_checked).toBe(false);
  expect(row?.software_blockers).toContain("WORK_PERMIT_NOT_APPROVED");

  const viewer = await request.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const login = await viewer.post("/api/v1/auth/login", {
      data: { username: seed.users.viewer, password: process.env.E2E_ACTOR_PASSWORD },
    });
    expect(login.ok()).toBeTruthy();
    expect((await viewer.get(
      "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/readiness",
    )).status()).toBe(200); // Viewer has mechanics scope, not the linked work.
    const scoped = await viewer.get(
      "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/readiness",
    );
    expect((await scoped.json() as { total: number }).total).toBe(0);
  } finally {
    await viewer.dispose();
  }
});
