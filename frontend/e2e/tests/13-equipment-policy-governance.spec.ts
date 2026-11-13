import { expect, request, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

type Proposal = {
  id: string; status: "pending" | "approved" | "rejected";
  proposed_by: string; reviewed_by: string | null;
};
type Asset = { id: string; code: string; required_credential_type_ids: string[] };

test("equipment credential policy requires independent review before activation", async ({ page }) => {
  const seed = demo();
  await loginUI(page);
  const authResponse = await page.request.get("/api/v1/auth/me");
  const csrf = (await authResponse.json() as { csrf_token: string }).csrf_token;
  const stamp = Date.now().toString(36);
  const code = "e2e-policy-" + stamp;
  const created = await page.request.post(
    "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/assets", {
      headers: { "X-CSRF-Token": csrf },
      data: {
        code, name: "Synthetic governed qualification robot",
        kind: "robot", unit_id: seed.units.automation,
      },
    },
  );
  expect(created.status()).toBe(201);
  const asset = await created.json() as Asset;
  const types = await page.request.get(
    "/api/v1/credentials/enterprises/" + seed.enterprise.id + "/types",
  );
  expect(types.ok()).toBeTruthy();
  const typeId = (await types.json() as { id: string }[])[0].id;
  const url = "/api/v1/equipment/assets/" + asset.id + "/policy-proposals";

  await page.goto("/#equipment");
  await page.locator(".workspace-rail").getByLabel("Предприятие")
    .selectOption(seed.enterprise.id);
  const panel = page.locator("#equipment");
  await panel.locator(".equipment-list button").filter({ hasText: code }).click();
  const governance = panel.locator(".equipment-policy");
  await expect(governance).toBeVisible();
  await governance.getByLabel("Обоснование нового требования (не менее 10 символов)")
    .fill("Synthetic maintenance permit requirement awaiting independent review");
  await governance.getByLabel("Допуск оборудования").selectOption(typeId);
  await governance.getByRole("button", { name: "Предложить требование к допуску" })
    .click();
  await expect(governance).toContainText("Ожидает утверждения");

  const list = await page.request.get(url);
  const pending = (await list.json() as Proposal[]).find(x => x.status === "pending");
  expect(pending).toBeDefined();
  const unchanged = await page.request.get(
    "/api/v1/equipment/enterprises/" + seed.enterprise.id + "/assets",
  );
  const inactive = (await unchanged.json() as Asset[]).find(x => x.id === asset.id);
  expect(inactive?.required_credential_type_ids).not.toContain(typeId);
  const duplicate = await page.request.post(url, {
    headers: { "X-CSRF-Token": csrf },
    data: {
      kind: "credential", credential_type_id: typeId,
      reason: "Second concurrent synthetic request should be rejected",
    },
  });
  expect(duplicate.status()).toBe(409);
  const ownApproval = await page.request.post(url + "/" + pending!.id + "/approve", {
    headers: { "X-CSRF-Token": csrf },
    data: { note: "Author cannot approve their own governed policy" },
  });
  expect(ownApproval.status()).toBe(403);
  const direct = await page.request.post(
    "/api/v1/equipment/assets/" + asset.id + "/required-credentials", {
      headers: { "X-CSRF-Token": csrf }, data: { type_id: typeId },
    },
  );
  expect(direct.status()).toBe(409);

  const reviewer = await request.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const login = await reviewer.post("/api/v1/auth/login", {
      data: { username: seed.users.reviewer, password: process.env.E2E_ACTOR_PASSWORD },
    });
    expect(login.ok()).toBeTruthy();
    const reviewerCsrf = (await login.json() as { csrf_token: string }).csrf_token;
    const reject = await reviewer.post(url + "/" + pending!.id + "/reject", {
      headers: { "X-CSRF-Token": reviewerCsrf },
      data: { note: "First proposal rejected following independent review" },
    });
    expect(reject.status()).toBe(200);
    expect((await reject.json() as Proposal).status).toBe("rejected");
    const again = await page.request.post(url, {
      headers: { "X-CSRF-Token": csrf },
      data: {
        kind: "credential", credential_type_id: typeId,
        reason: "Updated synthetic maintenance training requirement",
      },
    });
    expect(again.status()).toBe(201);
    const replacement = await again.json() as Proposal;
    const approval = await reviewer.post(url + "/" + replacement.id + "/approve", {
      headers: { "X-CSRF-Token": reviewerCsrf },
      data: { note: "Updated proposal independently reviewed and approved" },
    });
    expect(approval.status()).toBe(200);
    const active = await approval.json() as Asset;
    expect(active.required_credential_type_ids).toContain(typeId);
    const history = await reviewer.get(url);
    const proposals = await history.json() as Proposal[];
    expect(proposals.map(x => x.status).sort()).toEqual(["approved", "rejected"]);
    expect(proposals.every(x => x.reviewed_by !== x.proposed_by)).toBe(true);
    expect((await reviewer.post(url + "/" + replacement.id + "/approve", {
      headers: { "X-CSRF-Token": reviewerCsrf },
      data: { note: "Second review must fail because proposal is final" },
    })).status()).toBe(409);
  } finally {
    await reviewer.dispose();
  }

  await panel.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(governance).toContainText("Утверждено");
  await expect(panel.locator(".equipment-detail")).toContainText(
    "Обязательные дополнительные допуски",
  );
});
