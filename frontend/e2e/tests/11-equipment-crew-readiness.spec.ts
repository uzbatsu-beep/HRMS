import { expect, request, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

type Order = { id: string; status: string; last_safety_check_at: string | null };
type Snapshot = {
  work_order_id: string;
  leader_assigned: boolean;
  members_checked: number;
  crew_blocker_codes: string[];
  equipment_blocker_codes: string[];
  gates_passed: boolean;
  read_only: true;
  crew_eligibility_checked: true;
};

test("dispatcher explicitly checks redacted crew readiness without mutating work", async ({
  page,
}) => {
  const seed = demo();
  await loginUI(page);
  const auth = await page.request.get("/api/v1/auth/me");
  expect(auth.ok()).toBeTruthy();
  const csrf = (await auth.json() as { csrf_token: string }).csrf_token;
  const code = "e2e-crew-review-" + Date.now().toString(36);
  const createdAsset = await page.request.post(
    "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/assets",
    {
      headers: { "X-CSRF-Token": csrf },
      data: {
        unit_id: seed.units.automation,
        kind: "robot", name: "Synthetic crew readiness asset", code,
      },
    },
  );
  expect(createdAsset.status()).toBe(201);
  const asset = await createdAsset.json() as { id: string };

  const workSource = await page.request.get("/api/v1/work/orders/" + seed.work.id);
  const blueprint = await workSource.json() as {
    activity_code: string;
    required_skills: { skill_id: string; min_level_id: string }[];
  };
  const start = new Date(Date.now() + 5 * 60_000);
  const workCode = "e2e-crew-order-" + Date.now().toString(36);
  const createdOrder = await page.request.post(
    "/api/v1/work/enterprises/" + seed.enterprise.id + "/orders",
    {
      headers: { "X-CSRF-Token": csrf },
      data: {
        code: workCode, title: "Synthetic crew review snapshot",
        unit_id: seed.units.automation,
        activity_code: blueprint.activity_code,
        starts_at: start.toISOString(),
        ends_at: new Date(start.getTime() + 30 * 60_000).toISOString(),
        required_skills: blueprint.required_skills.map(x => ({
          skill_id: x.skill_id, min_level_id: x.min_level_id,
        })),
      },
    },
  );
  expect(createdOrder.status()).toBe(201);
  const order = await createdOrder.json() as Order;
  const linked = await page.request.post(
    "/api/v1/equipment/orders/" + order.id + "/equipment", {
      headers: { "X-CSRF-Token": csrf },
      data: { asset_id: asset.id },
    },
  );
  expect(linked.status()).toBe(201);

  await page.goto("/#equipment");
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  const readiness = page.locator(".equipment-readiness-item")
    .filter({ hasText: workCode });
  await expect(readiness).toBeVisible();
  await readiness.getByRole("button", { name: "Проверить бригаду" }).click();
  await expect(readiness).toContainText("Есть блокирующие условия");
  await expect(readiness).toContainText("Руководитель бригады не назначен");
  await expect(readiness).toContainText("Разовый снимок без изменения статуса наряда");

  const result = await page.request.get(
    "/api/v1/equipment/orders/" + order.id + "/crew-readiness",
  );
  expect(result.ok()).toBeTruthy();
  const info = await result.json() as Snapshot;
  expect(info.read_only).toBe(true);
  expect(info.crew_eligibility_checked).toBe(true);
  expect(info.gates_passed).toBe(false);
  expect(info.members_checked).toBe(0);
  expect(info.leader_assigned).toBe(false);
  expect(info.crew_blocker_codes).toContain("LEADER_NOT_ASSIGNED");
  expect(info.equipment_blocker_codes).toContain("WORK_PERMIT_NOT_APPROVED");
  const raw = JSON.stringify(info);
  expect(raw).not.toContain(seed.people.lead.id);
  expect(raw).not.toContain(seed.people.lead.last_name);

  const unchanged = await page.request.get("/api/v1/work/orders/" + order.id);
  const before = await unchanged.json() as Order;
  expect(before.status).toBe("open");
  expect(before.last_safety_check_at).toBeNull();

  // Separate cookie jars exercise cross-role checks without disrupting UI.
  const baseURL = new URL(page.url()).origin;
  const manager = await request.newContext({ baseURL });
  const viewer = await request.newContext({ baseURL });
  try {
    const password = process.env.E2E_ACTOR_PASSWORD!;
    expect((await manager.post("/api/v1/auth/login", {
      data: { username: seed.users.manager, password },
    })).ok()).toBeTruthy();
    const managerResult = await manager.get(
      "/api/v1/equipment/orders/" + order.id + "/crew-readiness",
    );
    expect(managerResult.status()).toBe(200);

    expect((await viewer.post("/api/v1/auth/login", {
      data: { username: seed.users.viewer, password },
    })).ok()).toBeTruthy();
    expect((await viewer.get(
      "/api/v1/equipment/orders/" + order.id + "/crew-readiness",
    )).status()).toBe(403);
  } finally {
    await manager.dispose();
    await viewer.dispose();
  }
});
