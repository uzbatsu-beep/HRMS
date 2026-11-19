import { test, expect } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("candidate paging and code search stay scoped and do not change assignment", async ({ page }) => {
  const s = demo();
  await loginUI(page);
  const original = await page.request.get("/api/v1/work/orders/" + s.work.id);
  expect(original.status()).toBe(200);
  const row = await original.json() as {
    activity_code: string; title: string; unit_id: string;
    required_skills: { skill_id: string; min_level_id: string }[];
  };
  const current = await page.request.get("/api/v1/auth/me");
  const csrf = (await current.json() as { csrf_token: string }).csrf_token;
  const code = "pg-browser-" + Date.now().toString(36);
  const created = await page.request.post(
    "/api/v1/work/enterprises/" + s.enterprise.id + "/orders",
    { headers: { "X-CSRF-Token": csrf }, data: {
      code, title: "Synthetic candidate paging acceptance",
      description: "Synthetic work order used only in browser regression",
      unit_id: row.unit_id, activity_code: row.activity_code,
      required_skills: row.required_skills.map((skill) => ({
        skill_id: skill.skill_id, min_level_id: skill.min_level_id,
      })),
      starts_at: s.work.starts_at, ends_at: s.work.ends_at,
    } },
  );
  expect(created.status()).toBe(201);
  const work = await created.json() as { id: string };
  const api = "/api/v1/work/orders/" + work.id + "/candidates-page";
  const first = await page.request.get(api + "?limit=1");
  expect(first.status()).toBe(200);
  const firstPage = await first.json() as {
    items: { person_id: string }[]; has_more: boolean; next_cursor: string | null;
  };
  expect(firstPage.items).toHaveLength(1);
  expect(firstPage.has_more).toBe(true);
  const next = await page.request.get(
    api + "?limit=1&after=" + firstPage.next_cursor,
  );
  expect(next.status()).toBe(200);
  const nextPage = await next.json() as { items: { person_id: string }[] };
  expect(nextPage.items[0].person_id).not.toBe(firstPage.items[0].person_id);

  await page.goto("/#work");
  await page.locator(".wm-enterprise select").selectOption(s.enterprise.id);
  const orders = page.locator(".wm-orders");
  await expect(orders).toContainText(code);
  await orders.getByRole("button").filter({ hasText: code }).click();
  const input = page.locator(".wm-matching")
    .getByRole("searchbox", { name: "Поиск по ФИО или табельному коду" });
  await input.fill(s.people.unqualified.employee_code);
  const results = page.locator(".wm-matching .wm-candidates");
  await expect(results).toContainText(s.people.unqualified.last_name);
  await expect(results.locator(".wm-candidate")).toHaveCount(1);
  await expect(results).toContainText("Есть блокировки");

  const notFound = await page.request.get(api + "?search=" + encodeURIComponent("%"));
  expect(notFound.status()).toBe(200);
  expect((await notFound.json() as { items: unknown[] }).items).toHaveLength(0);
  const unchanged = await page.request.get("/api/v1/work/orders/" + work.id);
  expect((await unchanged.json() as { status: string }).status).toBe("open");
});
