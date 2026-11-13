import { expect, request, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

type Requirement = { skill_id: string; min_level_id: string; min_ordinal: number;
  version: number };
type Asset = { id: string; required_skills: Requirement[] };
type Policy = { id: string; status: string; kind: string; expected_version: number | null };
type History = { version: number; min_ordinal: number; proposal_id: string | null }[];

test("approved equipment skill revisions are monotonic, independent and visible", async ({
  page,
}) => {
  const seed = demo();
  await loginUI(page);
  const me = await page.request.get("/api/v1/auth/me");
  const csrf = (await me.json() as { csrf_token: string }).csrf_token;
  const suffix = Date.now().toString(36);
  const created = await page.request.post(
    "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/assets", {
      headers: { "X-CSRF-Token": csrf },
      data: {
        code: "e2e-skill-version-" + suffix, name: "Synthetic versioned robot",
        unit_id: seed.units.automation, kind: "robot",
      },
    },
  );
  expect(created.status()).toBe(201);
  const asset = await created.json() as Asset;
  const competence = "/api/v1/competence/enterprises/" + seed.enterprise.id;
  const skills = (await (await page.request.get(competence + "/skills")).json()) as {
    id: string; scale_id: string;
  }[];
  const skill = skills[0];
  const scales = (await (await page.request.get(competence + "/scales")).json()) as {
    id: string; levels: { id: string; ordinal: number }[];
  }[];
  const levels = scales.find(x => x.id === skill.scale_id)!.levels;
  const low = levels.find(x => x.ordinal === 1)!;
  const high = levels.find(x => x.ordinal === 3)!;
  const url = "/api/v1/equipment/assets/" + asset.id + "/policy-proposals";
  const baseline = await page.request.post(url, {
    headers: { "X-CSRF-Token": csrf },
    data: {
      kind: "skill", skill_id: skill.id, min_level_id: low.id,
      reason: "Synthetic skill baseline independently reviewed for new asset",
    },
  });
  expect(baseline.status()).toBe(201);
  const baselinePolicy = await baseline.json() as Policy;

  const reviewer = await request.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const login = await reviewer.post("/api/v1/auth/login", {
      data: { username: seed.users.reviewer, password: process.env.E2E_ACTOR_PASSWORD },
    });
    expect(login.ok()).toBeTruthy();
    const otherCsrf = (await login.json() as { csrf_token: string }).csrf_token;
    const initial = await reviewer.post(url + "/" + baselinePolicy.id + "/approve", {
      headers: { "X-CSRF-Token": otherCsrf },
      data: { note: "Initial minimal robot programming level approved" },
    });
    expect(initial.status()).toBe(200);
    expect((await initial.json() as Asset).required_skills[0].version).toBe(1);

    await page.goto("/#equipment");
    await page.locator(".workspace-rail").getByLabel("Предприятие")
      .selectOption(seed.enterprise.id);
    const panel = page.locator("#equipment");
    await panel.locator(".equipment-list button")
      .filter({ hasText: "e2e-skill-version-" + suffix }).click();
    const governance = panel.locator(".equipment-policy");
    await expect(governance).toContainText("v1");
    await governance.getByLabel("Обоснование нового требования (не менее 10 символов)")
      .fill("Synthetic higher robot programming skill after process change");
    await governance.getByLabel("Повышаемая компетенция").selectOption(skill.id);
    await governance.getByLabel("Новый минимальный уровень").selectOption(high.id);
    await governance.getByRole("button", { name: "Предложить повышение уровня" }).click();
    await expect(governance).toContainText("Ожидает утверждения");

    const pending = (await (await page.request.get(url)).json() as Policy[])
      .find(x => x.kind === "skill_upgrade" && x.status === "pending");
    expect(pending?.expected_version).toBe(1);
    const historyUrl = "/api/v1/equipment/assets/" + asset.id + "/skill-policy-revisions";
    const before = await page.request.get(historyUrl);
    const beforeRows = await before.json() as History;
    expect(beforeRows.map(x => x.version)).toEqual([1]);
    const own = await page.request.post(url + "/" + pending!.id + "/approve", {
      headers: { "X-CSRF-Token": csrf },
      data: { note: "The author cannot approve the proposed upgrade" },
    });
    expect(own.status()).toBe(403);
    const approval = await reviewer.post(url + "/" + pending!.id + "/approve", {
      headers: { "X-CSRF-Token": otherCsrf },
      data: { note: "Independent qualification increase reviewed and approved" },
    });
    expect(approval.status()).toBe(200);
    const active = await approval.json() as Asset;
    expect(active.required_skills[0].version).toBe(2);
    expect(active.required_skills[0].min_ordinal).toBe(3);
    const history = await reviewer.get(historyUrl);
    const rows = await history.json() as History;
    expect(rows.map(x => x.version)).toEqual([1, 2]);
    expect(rows[1].proposal_id).toBe(pending!.id);
    const downgrade = await page.request.post(url, {
      headers: { "X-CSRF-Token": csrf },
      data: {
        kind: "skill_upgrade", skill_id: skill.id,
        min_level_id: low.id, expected_version: 2,
        reason: "A lower level cannot override independently approved policy",
      },
    });
    expect(downgrade.status()).toBe(422);
    await panel.getByRole("button", { name: "Обновить", exact: true }).click();
    await expect(panel.locator(".equipment-detail")).toContainText("v2");
    await expect(governance).toContainText("утверждённая редакция");

    const manager = await request.newContext({ baseURL: new URL(page.url()).origin });
    try {
      expect((await manager.post("/api/v1/auth/login", {
        data: { username: seed.users.manager, password: process.env.E2E_ACTOR_PASSWORD },
      })).ok()).toBeTruthy();
      expect((await manager.get(historyUrl)).status()).toBe(403);
    } finally {
      await manager.dispose();
    }
  } finally {
    await reviewer.dispose();
  }
});
