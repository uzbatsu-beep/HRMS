import { test, expect } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("server enforces CSRF, organizational scope and permit gates", async ({ page }) => {
  const seed = demo();
  await loginUI(page, seed.users.manager, process.env.E2E_ACTOR_PASSWORD);
  const work = await page.request.get("/api/v1/work/orders/" + seed.work.id);
  expect(work.status()).toBe(200);
  const wrongUnit = await page.request.get(
    "/api/v1/personnel/persons/" + seed.people.otherUnit.id,
  );
  expect(wrongUnit.status()).toBe(404);
  const withoutCsrf = await page.request.post(
    "/api/v1/work/orders/" + seed.work.id + "/cancel",
  );
  expect(withoutCsrf.status()).toBe(403);
  const check = await page.request.get(
    "/api/v1/work/orders/" + seed.work.id + "/candidates/" + seed.people.unqualified.id,
  );
  expect(check.status()).toBe(200);
  const candidate = await check.json() as { eligible: boolean; blockers: { code: string }[] };
  expect(candidate.eligible).toBe(false);
  expect(candidate.blockers.some((item) => item.code === "MISSING_CREDENTIAL")).toBe(true);
});
