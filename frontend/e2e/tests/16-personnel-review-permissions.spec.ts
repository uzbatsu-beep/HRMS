import { expect, test } from "@playwright/test";
import { demo, loginUI } from "../fixture";

type Person = { id: string };
type CompetenceSkill = { id: string; scale_id: string };
type Scale = { id: string; levels: { id: string; ordinal: number }[] };
type CredentialType = { id: string };
type Assessment = { id: string; status: string; reviewed_by: string | null };
type Credential = { id: string; status: string; reviewed_by: string | null };

test("scoped technical reviewer verifies skills and credentials without admin rights",
  async ({ page, browser }) => {
    const seed = demo();
    await loginUI(page);
    const auth = await page.request.get("/api/v1/auth/me");
    const csrf = (await auth.json() as { csrf_token: string }).csrf_token;
    const person: Person = seed.people.otherUnit;
    const ent = seed.enterprise.id;
    const skillRoot = "/api/v1/competence/enterprises/" + ent;
    const skills = await (
      await page.request.get(skillRoot + "/skills")
    ).json() as CompetenceSkill[];
    const skill = skills[0];
    const scales = await (await page.request.get(skillRoot + "/scales")).json()
      as Scale[];
    const level = scales.find(x => x.id === skill.scale_id)!.levels
      .find(x => x.ordinal === 1)!;
    const types = await (await page.request.get(
      "/api/v1/credentials/enterprises/" + ent + "/types",
    )).json() as CredentialType[];
    const kind = types[0];
    const assessmentCreate = await page.request.post(
      "/api/v1/competence/persons/" + person.id + "/expert-assessments", {
        headers: { "X-CSRF-Token": csrf },
        data: {
          skill_id: skill.id, level_id: level.id,
          evidence: [{
            kind: "observation",
            description: "Synthetic independent review of industrial PLC programming",
            reference: "RBAC-25-E2E",
          }],
        },
      },
    );
    expect(assessmentCreate.status()).toBe(201);
    const assessment = await assessmentCreate.json() as Assessment;
    const issued = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
    const valid = new Date(Date.now() - 20 * 86400000).toISOString().slice(0, 10);
    const expires = new Date(Date.now() + 35 * 86400000).toISOString().slice(0, 10);
    const documentCreate = await page.request.post(
      "/api/v1/credentials/enterprises/" + ent + "/records", {
        headers: { "X-CSRF-Token": csrf },
        data: {
          person_id: person.id, type_id: kind.id,
          document_reference: "RBAC25-E2E-VERIFY", issuer: "Test training authority",
          issued_on: issued, valid_from: valid, expires_on: expires,
        },
      },
    );
    expect(documentCreate.status()).toBe(201);
    const document = await documentCreate.json() as Credential;

    const access = "/api/v1/personnel/persons/" + person.id + "/review-capabilities";
    const reviewerPage = await browser.newPage();
    try {
      await loginUI(reviewerPage, seed.users.viewer, process.env.E2E_ACTOR_PASSWORD);
      expect((await reviewerPage.request.get(access)).status()).toBe(200);
      expect(await (await reviewerPage.request.get(access)).json()).toEqual({
        competence_review: false, credential_review: false,
      });
      // The reviewer already has organization visibility for mechanics.
      await page.goto("/#organization");
      await page.locator(".workspace-rail").getByLabel("Предприятие")
        .selectOption(ent);
      const matrix = page.getByLabel("Матрица операций подразделения");
      await expect(matrix).toBeVisible();
      await matrix.getByLabel("Подразделение для полномочий")
        .selectOption(seed.units.mechanics);
      await matrix.getByLabel("Пользователь для полномочий")
        .selectOption({ label: seed.users.viewer + " (viewer)" });
      await matrix.getByLabel("Операция")
        .selectOption("competence.assessment.review");
      await matrix.getByRole("button", { name: "Выдать полномочие" }).click();
      await expect(matrix).toContainText("Компетенции · Проверка оценки");
      await matrix.getByLabel("Операция")
        .selectOption("credentials.record.review");
      await matrix.getByRole("button", { name: "Выдать полномочие" }).click();
      await expect(matrix).toContainText("Допуски · Проверка документа");

      expect(await (await reviewerPage.request.get(access)).json()).toEqual({
        competence_review: true, credential_review: true,
      });
      // Reviewer sees pending evidence and can make one reasoned decision.
      await reviewerPage.goto("/#competence");
      await reviewerPage.locator(".workspace-rail").getByLabel("Предприятие")
        .selectOption(ent);
      const competence = reviewerPage.locator(".skill-assessment-section");
      await competence.getByLabel("Сотрудник").selectOption(person.id);
      const rows = competence.locator(".skill-assessment-list");
      await expect(rows).toContainText("На проверке");
      await rows.getByLabel("Обоснование решения")
        .fill("Independent practical exam evidence checked by delegated reviewer");
      await rows.getByRole("button", { name: "Подтвердить" }).click();
      await expect(rows).toContainText("Подтверждено");
      const completed = await reviewerPage.request.get(
        "/api/v1/competence/persons/" + person.id + "/assessments",
      );
      const assessments = await completed.json() as Assessment[];
      expect(assessments.some(x => x.id === assessment.id && x.status === "approved"))
        .toBe(true);
      await reviewerPage.goto("/#credentials");
      const docs = reviewerPage.locator("#credentials");
      await docs.getByLabel("Специалист").selectOption(person.id);
      const row = docs.locator(".credential-card").filter({
        hasText: "RBAC25-E2E-VERIFY",
      });
      await expect(row).toBeVisible();
      await row.getByLabel("Обоснование проверки / отзыва")
        .fill("Document issuer and validity dates independently verified");
      await row.getByRole("button", { name: "Подтвердить" }).click();
      await expect(row).toContainText("Проверен");
      const confirmed = await reviewerPage.request.get(
        "/api/v1/credentials/persons/" + person.id,
      );
      const documentRows = await confirmed.json() as Credential[];
      expect(documentRows.some(x => x.id === document.id && x.status === "verified"))
        .toBe(true);
      const tokenResponse = await reviewerPage.request.get("/api/v1/auth/me");
      const viewerCsrf = (await tokenResponse.json() as { csrf_token: string }).csrf_token;
      expect((await reviewerPage.request.post(
        "/api/v1/credentials/records/" + document.id + "/revoke", {
          headers: { "X-CSRF-Token": viewerCsrf },
          data: { reason: "Review permissions cannot revoke certificates" },
        },
      )).status()).toBe(403);
      // Revoke credential review: live capability check, no new login.
      const grants = await (await page.request.get(
        "/api/v1/org/permissions?unit_id=" + seed.units.mechanics,
      )).json() as { id: string; code: string; user_id: string }[];
      const users = await (
        await page.request.get("/api/v1/auth/users")
      ).json() as { id: string; username: string }[];
      const actor = users.find(x => x.username === seed.users.viewer)!;
      const revoke = grants.find(x => x.user_id === actor.id &&
        x.code === "credentials.record.review")!;
      expect((await page.request.delete(
        "/api/v1/org/permissions/" + revoke.id,
        { headers: { "X-CSRF-Token": csrf } },
      )).status()).toBe(204);
      expect(await (await reviewerPage.request.get(access)).json()).toEqual({
        competence_review: true, credential_review: false,
      });
    } finally { await reviewerPage.close(); }
  },
);
