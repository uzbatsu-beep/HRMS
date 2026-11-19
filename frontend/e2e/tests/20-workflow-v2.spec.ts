import { expect, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("Configurator v2 governs service intake and independent decisions", async ({ page }) => {
  const seed = demo();
  const code = "e2e_intake_" + Date.now().toString(36);
  const label = "Synthetic service flow " + code;
  const intakeTitle = "Synthetic service request " + code;
  const date = new Date().toISOString().slice(0, 10);
  await loginUI(page);
  await page.goto("/#configuration");
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  const v2 = page.locator(".config-workflow-v2");
  await expect(v2).toContainText("Формы и маршруты рассмотрения заявок");
  const editor = v2.locator("details.config-workflow").first();
  await editor.locator("summary").click();
  await editor.getByLabel("Код шаблона").fill(code);
  await editor.getByLabel("Название шаблона").fill(label);
  await editor.getByRole("button", { name: "Сохранить черновик маршрута" }).click();
  await expect(v2).toContainText("Версия сохранена");
  await editor.getByRole("button", { name: "Проверить маршрут" }).click();
  await expect(v2).toContainText("Переход версии выполнен");

  const versions = await page.request.get(
    "/api/v1/configuration/enterprises/" + seed.enterprise.id + "/workflow-versions",
  );
  expect(versions.status()).toBe(200);
  const rows = await versions.json() as { code: string; id: string; status: string }[];
  const version = rows.find((row) => row.code === code);
  expect(version?.status).toBe("validated");
  const auth = await page.request.get("/api/v1/auth/me");
  const adminName = (await auth.json() as { user: { username: string } }).user.username;
  const reviewerLogin = await page.request.post("/api/v1/auth/login", {
    data: { username: seed.users.reviewer, password: process.env.E2E_ACTOR_PASSWORD },
  });
  expect(reviewerLogin.status()).toBe(200);
  const reviewerCsrf = (await reviewerLogin.json() as { csrf_token: string }).csrf_token;
  const approved = await page.request.post(
    "/api/v1/configuration/workflow-versions/" + version!.id + "/approve",
    { headers: { "X-CSRF-Token": reviewerCsrf } },
  );
  expect(approved.status()).toBe(200);
  const back = await page.request.post("/api/v1/auth/login", {
    data: { username: adminName, password: process.env.E2E_ADMIN_PASSWORD },
  });
  expect(back.status()).toBe(200);
  const adminCsrf = (await back.json() as { csrf_token: string }).csrf_token;
  const published = await page.request.post(
    "/api/v1/configuration/workflow-versions/" + version!.id + "/publish",
    { headers: { "X-CSRF-Token": adminCsrf }, data: { effective_on: date } },
  );
  expect(published.status()).toBe(200);
  await page.reload();
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  await v2.getByLabel("Вид заявки").selectOption(code);
  await v2.getByLabel("Подразделение").selectOption(seed.units.automation);
  await v2.getByLabel("Тема").fill(intakeTitle);
  await v2.getByLabel("Описание обращения").fill(
    "Synthetic informational follow-up only, not a physical work permit",
  );
  await v2.getByRole("button", { name: "Создать заявку" }).click();
  await expect(v2).toContainText("Заявка создана в исходном состоянии");
  await v2.getByRole("button", { name: "Передать на рассмотрение" }).click();
  await expect(v2).toContainText("Переход сохранён в журнале заявки");

  const allCases = await page.request.get(
    "/api/v1/configuration/enterprises/" + seed.enterprise.id + "/service-requests",
  );
  expect(allCases.status()).toBe(200);
  const cases = await allCases.json() as { id: string; title: string; state: string }[];
  const record = cases.find((row) => row.title === intakeTitle);
  expect(record?.state).toBe("submitted");
  const move = "/api/v1/configuration/service-requests/" + record!.id + "/transitions";
  // Even an administrator cannot approve their own informational request.
  const selfDecision = await page.request.post(move, {
    headers: { "X-CSRF-Token": adminCsrf },
    data: { transition_code: "resolve", expected_state: "submitted" },
  });
  expect(selfDecision.status()).toBe(403);

  const reviewerAgain = await page.request.post("/api/v1/auth/login", {
    data: { username: seed.users.reviewer, password: process.env.E2E_ACTOR_PASSWORD },
  });
  const reviewerToken = (await reviewerAgain.json() as { csrf_token: string }).csrf_token;
  const resolved = await page.request.post(move, {
    headers: { "X-CSRF-Token": reviewerToken },
    data: { transition_code: "resolve", expected_state: "submitted",
      note: "Independent synthetic review, not any safety clearance" },
  });
  expect(resolved.status()).toBe(200);
  expect((await resolved.json() as { state: string }).state).toBe("resolved");
  const events = await page.request.get(
    "/api/v1/configuration/service-requests/" + record!.id + "/history",
  );
  expect(events.status()).toBe(200);
  const history = await events.json() as { transition_code: string }[];
  expect(history.map((event) => event.transition_code)).toEqual([
    "created", "submit", "resolve",
  ]);
  await page.request.post("/api/v1/auth/login", {
    data: { username: adminName, password: process.env.E2E_ADMIN_PASSWORD },
  });
  await page.reload();
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  await expect(v2).toContainText(intakeTitle);
  await expect(v2).toContainText("resolved");
});
