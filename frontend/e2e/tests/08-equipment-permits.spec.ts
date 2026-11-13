import { expect, request, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("asset catalog, linked order and independent human permit are persisted", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  await page.goto("/#equipment");
  const equipment = page.locator("#equipment");
  await expect(equipment).toBeVisible();
  const create = equipment.locator("details.equipment-editor");
  await create.locator("summary").click();
  const code = "e2e-asset-" + Date.now().toString(36);
  await create.getByLabel("Код актива").fill(code);
  await create.getByLabel("Наименование").fill("Синтетический робот участка");
  await create.getByLabel("Подразделение оборудования").selectOption(seed.units.automation);
  await create.getByLabel("Класс").selectOption("robot");
  await create.getByRole("button", { name: "Создать актив" }).click();
  await expect(equipment.locator(".equipment-list")).toContainText(code);

  const assetsResponse = await page.request.get(
    "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/assets",
  );
  expect(assetsResponse.ok()).toBeTruthy();
  const asset = (await assetsResponse.json() as { id: string; code: string }[])
    .find(x => x.code === code);
  expect(asset).toBeDefined();

  // Create an independent work order. Other E2E tests may have already closed
  // the shared demonstration work order, so do not reuse its lifecycle.
  const me = await page.request.get("/api/v1/auth/me");
  expect(me.ok()).toBeTruthy();
  const csrf = (await me.json() as { csrf_token: string }).csrf_token;
  const seededWork = await page.request.get("/api/v1/work/orders/" + seed.work.id);
  const blueprint = await seededWork.json() as {
    activity_code: string; unit_id: string; required_skills: {
      skill_id: string; min_level_id: string;
    }[];
  };
  const workCode = "e2e-permit-" + Date.now().toString(36);
  const startsAt = new Date(Date.now() + 5 * 60000);
  const orderCreate = await page.request.post(
    "/api/v1/work/enterprises/" + seed.enterprise.id + "/orders",
    { headers: { "X-CSRF-Token": csrf }, data: {
      code: workCode, title: "Синтетический тест наряда на роботе",
      unit_id: seed.units.automation, activity_code: blueprint.activity_code,
      starts_at: startsAt.toISOString(),
      ends_at: new Date(startsAt.getTime() + 20 * 60000).toISOString(),
      required_skills: blueprint.required_skills.map(x => ({
        skill_id: x.skill_id, min_level_id: x.min_level_id,
      })),
    } },
  );
  expect(orderCreate.status()).toBe(201);
  const work = await orderCreate.json() as { id: string };

  await page.goto("/#work");
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  await page.locator(".wm-order").filter({ hasText: workCode }).click();
  const permit = page.getByRole("region", { name: "Оборудование и разрешение на работы" });
  await expect(permit).toBeVisible();
  await permit.getByLabel("Оборудование наряда").selectOption(asset!.id);
  await permit.getByRole("button", { name: "Привязать оборудование" }).click();
  await expect(permit).toContainText(code);
  await expect(permit).toContainText("Нет действующего согласованного разрешения");

  await permit.getByLabel(/Риски рабочего места рассмотрены/).check();
  await permit.getByLabel(/Изоляция источников энергии/).check();
  await permit.getByLabel(/Доступ на рабочее место/).check();
  await permit.getByLabel(/Ссылка или идентификатор документа/).fill(
    "SYNTHETIC-WORK-PERMIT-001",
  );
  await permit.getByRole("button", { name: "Зарегистрировать черновик" }).click();
  await permit.getByRole("button", { name: "Отправить на согласование" }).click();
  await expect(permit).toContainText("На согласовании");
  await expect(permit.getByRole("button", { name: /Согласовать разрешение/ })).toBeDisabled();

  const latest = await page.request.get(
    "/api/v1/equipment/orders/" + work.id + "/safety-package",
  );
  const state = await latest.json() as { permit: { id: string; status: string } };
  expect(state.permit.status).toBe("submitted");

  // Separate isolated APIRequestContext ensures the reviewer session does not
  // replace the engineer's browser cookie or its workspace selection.
  const adminUsername = process.env.E2E_ADMIN_USERNAME!;
  const adminPassword = process.env.E2E_ADMIN_PASSWORD!;
  const reviewerPassword = process.env.E2E_ACTOR_PASSWORD!;
  const reviewerUsername = "e2e-permit-reviewer-" + Date.now().toString(36);
  const reviewer = await request.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const adminLogin = await page.request.post("/api/v1/auth/login", {
      data: { username: adminUsername, password: adminPassword },
    });
    const adminCsrf = (await adminLogin.json() as { csrf_token: string }).csrf_token;
    const userCreate = await page.request.post("/api/v1/auth/users", {
      headers: { "X-CSRF-Token": adminCsrf },
      data: { username: reviewerUsername, password: reviewerPassword, role: "admin" },
    });
    expect(userCreate.status()).toBe(201);
    const login = await reviewer.post("/api/v1/auth/login", {
      data: { username: reviewerUsername, password: reviewerPassword },
    });
    expect(login.ok()).toBeTruthy();
    const reviewCsrf = (await login.json() as { csrf_token: string }).csrf_token;
    const approved = await reviewer.post(
      "/api/v1/equipment/orders/" + work.id + "/permit/" + state.permit.id + "/approve",
      { headers: { "X-CSRF-Token": reviewCsrf } },
    );
    expect(approved.status()).toBe(200);
    const reviewData = await approved.json() as { status: string; approved_by: string };
    expect(reviewData.status).toBe("approved");
    expect(reviewData.approved_by).toBeTruthy();

    const viewer = await request.newContext({ baseURL: new URL(page.url()).origin });
    try {
      const viewLogin = await viewer.post("/api/v1/auth/login", {
        data: { username: seed.users.viewer, password: reviewerPassword },
      });
      expect(viewLogin.ok()).toBeTruthy();
      const hidden = await viewer.get(
        "/api/v1/equipment/orders/" + work.id + "/safety-package",
      );
      expect(hidden.status()).toBe(404);
    } finally {
      await viewer.dispose();
    }
  } finally {
    await reviewer.dispose();
  }

  const checked = await page.request.get(
    "/api/v1/equipment/orders/" + work.id + "/safety-package",
  );
  expect((await checked.json() as { permit: { status: string } }).permit.status).toBe("approved");
});
