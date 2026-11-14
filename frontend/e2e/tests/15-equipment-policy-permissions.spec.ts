import { expect, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

type Caps = { can_read: boolean; can_propose: boolean; can_review: boolean };
type Item = { id: string; code?: string };
type Policy = { id: string; status: string; proposed_by: string; reviewed_by: string | null };

test("scoped engineer and safety reviewer use policy matrix without admin rights",
  async ({ page, browser }) => {
    const seed = demo();
    await loginUI(page);
    const me = await page.request.get("/api/v1/auth/me");
    const csrf = (await me.json() as { csrf_token: string }).csrf_token;
    const actorPass = process.env.E2E_ACTOR_PASSWORD!;
    const root = "/api/v1/equipment";
    const code = "matrix-24-" + Date.now().toString(36);
    const created = await page.request.post(
      root + "/enterprises/" + seed.enterprise.id + "/assets",
      { headers: { "X-CSRF-Token": csrf },
        data: { code, name: "Synthetic permission matrix robot",
          unit_id: seed.units.automation, kind: "robot" } },
    );
    expect(created.status()).toBe(201);
    const asset = await created.json() as Item;
    const capsUrl = root + "/assets/" + asset.id + "/policy-capabilities";
    const proposalUrl = root + "/assets/" + asset.id + "/policy-proposals";

    // Existing demo Viewer has a mechanics-only grant, so issue a separate,
    // exact-unit organizational scope for the synthetic safety reviewer.
    const users = await (await page.request.get("/api/v1/auth/users")).json() as {
      id: string; username: string;
    }[];
    const reviewer = users.find(x => x.username === seed.users.viewer)!;
    const scope = await page.request.post("/api/v1/org/scopes", {
      headers: { "X-CSRF-Token": csrf },
      data: { user_id: reviewer.id, unit_id: seed.units.automation,
        include_descendants: false },
    });
    expect(scope.status()).toBe(201);

    await page.goto("/#equipment");
    await page.locator(".workspace-rail").getByLabel("Предприятие")
      .selectOption(seed.enterprise.id);
    const panel = page.locator("#equipment");
    await panel.locator(".equipment-list button").filter({ hasText: code }).click();
    const matrix = panel.locator(".equipment-permission-matrix");
    await expect(matrix).toBeVisible();
    await matrix.getByLabel("Сотрудник системы").selectOption(
      { label: seed.users.manager + " (manager)" },
    );
    await matrix.getByLabel("Разрешённая операция")
      .selectOption("equipment.policy.propose");
    await matrix.getByRole("button", { name: "Выдать полномочие" }).click();
    await expect(matrix).toContainText(seed.users.manager + " · Создание заявок");
    await matrix.getByLabel("Сотрудник системы").selectOption(
      { label: seed.users.viewer + " (viewer)" },
    );
    await matrix.getByLabel("Разрешённая операция")
      .selectOption("equipment.policy.review");
    await matrix.getByRole("button", { name: "Выдать полномочие" }).click();
    await expect(matrix).toContainText(seed.users.viewer + " · Независимое согласование");

    const managerPage = await browser.newPage();
    const reviewerPage = await browser.newPage();
    try {
      await loginUI(managerPage, seed.users.manager, actorPass);
      const mc = await managerPage.request.get(capsUrl);
      expect(await mc.json() as Caps).toEqual({
        can_read: true, can_propose: true, can_review: false,
      });
      await managerPage.goto("/#equipment");
      await managerPage.locator(".workspace-rail").getByLabel("Предприятие")
        .selectOption(seed.enterprise.id);
      const engineer = managerPage.locator("#equipment");
      await engineer.locator(".equipment-list button").filter({ hasText: code }).click();
      const editor = engineer.locator(".equipment-policy");
      await expect(editor).toContainText("создавать заявки");
      await expect(editor.getByRole("button", { name: "Утвердить" })).toHaveCount(0);

      const skill = (await (await managerPage.request.get(
        "/api/v1/competence/enterprises/" + seed.enterprise.id + "/skills",
      )).json() as { id: string; scale_id: string }[])[0];
      const scales = await (await managerPage.request.get(
        "/api/v1/competence/enterprises/" + seed.enterprise.id + "/scales",
      )).json() as { id: string; levels: { id: string; ordinal: number }[] }[];
      const min = scales.find(x => x.id === skill.scale_id)!.levels.find(
        x => x.ordinal === 1,
      )!;
      await editor.getByLabel("Обоснование нового требования (не менее 10 символов)")
        .fill("New robot qualification proposed by delegated engineer");
      await editor.getByLabel("Компетенция оборудования").selectOption(skill.id);
      await editor.getByLabel("Уровень компетенции оборудования").selectOption(min.id);
      await editor.getByRole("button", { name: "Предложить требование к навыку" })
        .click();
      await expect(editor).toContainText("Ожидает утверждения");
      const pending = (await (await managerPage.request.get(proposalUrl)).json()
        as Policy[]).find(x => x.status === "pending");
      expect(pending).toBeDefined();

      await loginUI(reviewerPage, seed.users.viewer, actorPass);
      const rc = await reviewerPage.request.get(capsUrl);
      expect(await rc.json() as Caps).toEqual({
        can_read: true, can_propose: false, can_review: true,
      });
      await reviewerPage.goto("/#equipment");
      await reviewerPage.locator(".workspace-rail").getByLabel("Предприятие")
        .selectOption(seed.enterprise.id);
      const safety = reviewerPage.locator("#equipment");
      await safety.locator(".equipment-list button").filter({ hasText: code }).click();
      const review = safety.locator(".equipment-policy");
      await expect(review).toContainText("Ожидает утверждения");
      await expect(review.getByRole("button",
        { name: "Предложить требование к навыку" })).toHaveCount(0);
      await review.getByLabel("Мотивировка решения (не менее 10 символов)")
        .fill("Independent safety review confirms required skill threshold");
      await review.getByRole("button", { name: "Утвердить" }).click();
      await expect(review).toContainText("Утверждено");
      const latest = (await (await reviewerPage.request.get(proposalUrl)).json()
        as Policy[])[0];
      expect(latest.reviewed_by).not.toBe(latest.proposed_by);
      const reviewerAuth = await reviewerPage.request.get("/api/v1/auth/me");
      const reviewCsrf = (await reviewerAuth.json() as { csrf_token: string }).csrf_token;
      const stateDenied = await reviewerPage.request.post(
        root + "/assets/" + asset.id + "/state",
        { headers: { "X-CSRF-Token": reviewCsrf },
          data: { status: "out_of_service",
            reason: "Non-admin reviewer cannot change physical machine status" } },
      );
      expect(stateDenied.status()).toBe(403);

      // Permission revocation is evaluated live, without session renewal.
      const grants = (await (await page.request.get(
        "/api/v1/org/permissions?unit_id=" + seed.units.automation,
      )).json()) as { id: string; code: string; user_id: string }[];
      const manager = users.find(x => x.username === seed.users.manager)!;
      const remove = grants.find(x => x.user_id === manager.id
        && x.code === "equipment.policy.propose")!;
      expect((await page.request.delete(
        "/api/v1/org/permissions/" + remove.id,
        { headers: { "X-CSRF-Token": csrf } },
      )).status()).toBe(204);
      expect(await (await managerPage.request.get(capsUrl)).json() as Caps).toEqual({
        can_read: false, can_propose: false, can_review: false,
      });
      expect((await managerPage.request.get(proposalUrl)).status()).toBe(403);
    } finally {
      await managerPage.close();
      await reviewerPage.close();
    }
  },
);
