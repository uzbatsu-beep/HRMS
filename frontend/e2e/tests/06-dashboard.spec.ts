import { expect, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("dashboard uses server analytics and current enterprise context", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  await page.goto("/#dashboard");
  const rail = page.locator(".workspace-rail");
  await rail.getByLabel("Предприятие").selectOption(seed.enterprise.id);

  const dashboard = page.locator(".ops-dashboard");
  await expect(dashboard).toBeVisible();
  await expect(dashboard).toContainText("Состояние технических ресурсов");
  await expect(dashboard).toContainText("Динамика нарядов");
  await expect(dashboard).toContainText("Приостановленные наряды");
  await expect(dashboard.locator(".ops-chart-day")).toHaveCount(30);

  const response = await page.request.get(
    "/api/v1/analytics/enterprises/" + seed.enterprise.id + "/summary",
  );
  expect(response.status()).toBe(200);
  const report = await response.json() as {
    period_days: number; renewal_days: number;
    workforce: { active_resources: number };
  };
  expect(report.period_days).toBe(30);
  expect(report.renewal_days).toBe(30);
  await expect(dashboard).toContainText(String(report.workforce.active_resources));

  await dashboard.getByRole("button", { name: /Открыть раздел/ }).first().click();
  await expect(page).toHaveURL(/#personnel$/);
});

test("viewer receives only scoped analytics", async ({ page }) => {
  const seed = demo();
  await loginUI(page, seed.users.viewer, process.env.E2E_ACTOR_PASSWORD);
  await page.goto("/#dashboard");
  const report = page.locator(".ops-dashboard");
  await expect(report).toBeVisible();
  await expect(report).toContainText("E2E Механики");
  await expect(report).not.toContainText("E2E Автоматизация");
  const forbidden = await page.request.get(
    "/api/v1/analytics/enterprises/" + seed.enterprise.id + "/summary",
    { params: { unit_id: seed.units.automation } },
  );
  expect(forbidden.status()).toBe(404);
});
