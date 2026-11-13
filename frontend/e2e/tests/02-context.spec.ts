import { test, expect } from "@playwright/test";
import { demo, loginUI } from "../fixture";

test("right rail filters real people by organizational unit and opens person", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  const rail = page.locator(".workspace-rail");
  await rail.getByLabel("Предприятие").selectOption(seed.enterprise.id);
  await expect(rail).toContainText("E2E Автоматизация");
  await expect(rail).toContainText("E2E Механики");
  await rail.getByRole("button", { name: /E2E Автоматизация/ }).click();
  const search = rail.getByPlaceholder("Фамилия, имя или таб. №");
  await search.fill(seed.people.lead.last_name);
  await expect(rail.locator(".rail-people-list")).toContainText(seed.people.lead.last_name);
  await expect(rail.locator(".rail-people-list")).not.toContainText(seed.people.otherUnit.last_name);
  await rail.locator(".rail-person").filter({ hasText: seed.people.lead.last_name }).click();
  await expect(page).toHaveURL(/#personnel$/);
  await expect(page.locator("#personnel")).toBeVisible();
  await expect(page.locator("#personnel")).toContainText(seed.people.lead.last_name);
});

test("out-of-scope viewer sees only authorized units and cannot modify records", async ({ page }) => {
  const seed = demo();
  await loginUI(page, seed.users.viewer, process.env.E2E_ACTOR_PASSWORD);
  const rail = page.locator(".workspace-rail");
  await expect(rail).toContainText("E2E Механики");
  await expect(rail).not.toContainText("E2E Автоматизация");
  await expect(rail).toContainText(seed.people.otherUnit.last_name);
  await expect(rail).not.toContainText(seed.people.lead.last_name);
  const wrongPerson = await page.request.get(
    "/api/v1/personnel/persons/" + seed.people.lead.id,
  );
  expect(wrongPerson.status()).toBe(404);
  const write = await page.request.post(
    "/api/v1/work/orders/" + seed.work.id + "/cancel",
  );
  expect([401, 403, 404]).toContain(write.status());
});
