import { request, type APIRequestContext } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";

type Item = { id: string; [key: string]: unknown };
type Person = { id: string; resource_id: string; last_name: string; employee_code: string };
export type DemoSeed = {
  enterprise: { id: string; name: string };
  units: { root: string; automation: string; mechanics: string };
  people: { lead: Person; crew: Person; unqualified: Person; otherUnit: Person };
  credentials: { lead: string; crew: string };
  users: { manager: string; viewer: string };
  work: { id: string; code: string; starts_at: string; ends_at: string };
};

const base = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173";
const output = resolve(process.cwd(), "e2e", ".tmp", "seed.json");
const later = (moment: Date, minutes: number) => new Date(moment.getTime() + minutes * 60000);
const day = (moment: Date) => moment.toISOString().slice(0, 10);
const pad = (n: number) => String(n).padStart(2, "0");

function guard() {
  const url = new URL(base);
  if (process.env.E2E_ALLOW_SEED !== "1")
    throw new Error("Refusing to seed: E2E_ALLOW_SEED=1 is required for disposable test DB.");
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname))
    throw new Error("Seeding must target a local HTTP loopback URL.");
}
async function login(ctx: APIRequestContext, user: string, password: string) {
  const response = await ctx.post("/api/v1/auth/login", { data: { username: user, password } });
  if (!response.ok()) throw new Error("E2E login failed: " + response.status());
  return await response.json() as { user: { id: string }; csrf_token: string };
}
async function post<T>(
  ctx: APIRequestContext, csrf: string, path: string, data: object,
): Promise<T> {
  const response = await ctx.post(path, { data, headers: { "X-CSRF-Token": csrf } });
  if (![200, 201].includes(response.status()))
    throw new Error("Seed " + path + " -> " + response.status() + ": " + await response.text());
  return await response.json() as T;
}
export default async function globalSetup(): Promise<void> {
  guard();
  const adminName = process.env.E2E_ADMIN_USERNAME;
  const adminPassword = process.env.E2E_ADMIN_PASSWORD;
  const actorPassword = process.env.E2E_ACTOR_PASSWORD;
  if (!adminName || !adminPassword || !actorPassword)
    throw new Error("E2E_ADMIN_USERNAME, E2E_ADMIN_PASSWORD and E2E_ACTOR_PASSWORD are required.");

  const admin = await request.newContext({ baseURL: base });
  const reviewer = await request.newContext({ baseURL: base });
  try {
    const ready = await admin.get("/api/v1/health/ready");
    if (!ready.ok()) throw new Error("Backend health/readiness check failed.");
    const adminAuth = await login(admin, adminName, adminPassword);
    const stamp = Date.now().toString(36);
    const code = (part: string) => ("e2e-" + part + "-" + stamp).slice(0, 62);
    const create = <T>(path: string, data: object) =>
      post<T>(admin, adminAuth.csrf_token, path, data);
    const reviewerName = code("reviewer");
    const managerName = code("manager");
    const viewerName = code("viewer");
    await create<Item>("/api/v1/auth/users", {
      username: reviewerName, password: actorPassword, role: "admin",
    });
    const manager = await create<Item>("/api/v1/auth/users", {
      username: managerName, password: actorPassword, role: "manager",
    });
    const viewer = await create<Item>("/api/v1/auth/users", {
      username: viewerName, password: actorPassword, role: "viewer",
    });
    const reviewerAuth = await login(reviewer, reviewerName, actorPassword);
    const approve = <T>(path: string, data: object) =>
      post<T>(reviewer, reviewerAuth.csrf_token, path, data);

    const enterprise = await create<{ id: string; name: string }>(
      "/api/v1/org/enterprises",
      { code: code("plant"), name: "E2E Демонстрационный завод" },
    );
    const org = "/api/v1/org/enterprises/" + enterprise.id;
    const kind = await create<Item>(org + "/types", {
      code: code("type"), name: "Служба предприятия",
    });
    const root = await create<Item>(org + "/units", {
      code: code("service"), name: "E2E Техническая служба", type_id: kind.id,
    });
    const automation = await create<Item>(org + "/units", {
      code: code("asu"), name: "E2E Автоматизация",
      parent_id: root.id, type_id: kind.id,
    });
    const mechanics = await create<Item>(org + "/units", {
      code: code("mechanics"), name: "E2E Механики",
      parent_id: root.id, type_id: kind.id,
    });
    await create<Item>("/api/v1/org/scopes", {
      user_id: manager.id, unit_id: automation.id, include_descendants: true,
    });
    await create<Item>("/api/v1/org/scopes", {
      user_id: viewer.id, unit_id: mechanics.id, include_descendants: true,
    });
    const person = (codePart: string, first_name: string, last_name: string, unit_id: string) =>
      create<Person>("/api/v1/personnel/enterprises/" + enterprise.id + "/persons", {
        employee_code: code(codePart), first_name, last_name, unit_id,
        position_title: "Синтетический специалист АСУ ТП", effective_from: "2020-01-01",
      });
    const lead = await person("001", "Иван", "E2E Тестов", automation.id);
    const crew = await person("002", "Ольга", "E2E Инженерова", automation.id);
    const unqualified = await person("003", "Павел", "E2E БезДопуска", automation.id);
    const otherUnit = await person("004", "Мария", "E2E Механикова", mechanics.id);

    const skillsRoot = "/api/v1/competence/enterprises/" + enterprise.id;
    const category = await create<Item>(skillsRoot + "/categories", {
      code: code("controls"), name: "E2E Системы управления",
    });
    const scale = await create<{ id: string; levels: { id: string; ordinal: number }[] }>(
      skillsRoot + "/scales", {
        code: code("levels"), name: "Уровни E2E", version: 1,
        levels: [
          { ordinal: 0, label: "Начальный" }, { ordinal: 1, label: "Базовый" },
          { ordinal: 3, label: "Эксперт" },
        ],
      },
    );
    const skill = await create<Item>(skillsRoot + "/skills", {
      code: code("st"), name: "E2E Программирование IEC 61131-3",
      category_id: category.id, scale_id: scale.id,
    });
    const expert = scale.levels.find((x) => x.ordinal === 3);
    const basic = scale.levels.find((x) => x.ordinal === 1);
    if (!expert || !basic) throw new Error("Invalid scale response");

    const permit = await create<Item>(
      "/api/v1/credentials/enterprises/" + enterprise.id + "/types", {
        code: code("safety"), name: "E2E Электробезопасность",
        kind: "permit", is_safety_critical: true, requires_expiry: true,
      },
    );
    const activity = code("plc-maint");
    await create<Item>("/api/v1/credentials/enterprises/" + enterprise.id + "/requirements", {
      activity_code: activity, type_id: permit.id,
    });
    const now = new Date();
    async function verified(p: Person, tag: string): Promise<string> {
      const assessment = await create<Item>(
        "/api/v1/competence/persons/" + p.id + "/expert-assessments", {
          skill_id: skill.id, level_id: expert!.id,
          evidence: [{ kind: "observation",
            description: "Independent synthetic E2E commissioning assessment",
            reference: "E2E-" + tag }],
        },
      );
      await approve<Item>("/api/v1/competence/assessments/" + assessment.id + "/review", {
        decision: "approved", note: "Independent E2E review: trial completed successfully.",
      });
      const record = await create<Item>(
        "/api/v1/credentials/enterprises/" + enterprise.id + "/records", {
          person_id: p.id, type_id: permit.id,
          document_reference: "SYNTHETIC-E2E-" + tag,
          issuer: "Synthetic testing authority",
          issued_on: day(later(now, -10 * 1440)),
          valid_from: day(later(now, -9 * 1440)),
          expires_on: day(later(now, 365 * 1440)),
        },
      );
      await approve<Item>("/api/v1/credentials/records/" + record.id + "/review", {
        decision: "verified", note: "Independent synthetic certificate verification.",
      });
      return record.id;
    }
    const leadCredential = await verified(lead, "LEAD");
    const crewCredential = await verified(crew, "CREW");

    // An 17-hour UTC overnight shift covers now on all weekdays and at midnight.
    const anchor = later(now, -360);
    for (const p of [lead, crew, unqualified]) {
      await create<Item>("/api/v1/availability/resources/" + p.resource_id + "/shifts", {
        weekday: (anchor.getUTCDay() + 6) % 7,
        local_start: pad(anchor.getUTCHours()) + ":00:00",
        local_end: pad((anchor.getUTCHours() + 17) % 24) + ":00:00",
        time_zone: "UTC", valid_from: "2020-01-01",
      });
    }
    const work = await create<DemoSeed["work"]>(
      "/api/v1/work/enterprises/" + enterprise.id + "/orders", {
        code: code("wo"), title: "E2E Диагностика ПЛК линии",
        description: "Только синтетическое функциональное тестирование Playwright",
        unit_id: automation.id, activity_code: activity,
        starts_at: later(now, -2).toISOString(),
        ends_at: later(now, 90).toISOString(), priority: "urgent",
        required_skills: [{ skill_id: skill.id, min_level_id: basic.id }],
      },
    );
    const seed: DemoSeed = {
      enterprise, units: { root: root.id, automation: automation.id, mechanics: mechanics.id },
      people: { lead, crew, unqualified, otherUnit },
      credentials: { lead: leadCredential, crew: crewCredential },
      users: { manager: managerName, viewer: viewerName }, work,
    };
    await mkdir(dirname(output), { recursive: true });
    await writeFile(output, JSON.stringify(seed, null, 2), { mode: 0o600 });
    console.log("E2E fixture created in a loopback test environment; no passwords saved.");
  } finally {
    await admin.dispose();
    await reviewer.dispose();
  }
}
