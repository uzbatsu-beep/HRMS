import { FormEvent, useEffect, useMemo, useState } from "react";

type User = { id: string; username: string; role: "admin" | "manager" | "viewer" };
type Session = { user: User; csrf_token: string };
type Enterprise = { id: string; name: string; code: string };
type Person = {
  id: string; first_name: string; last_name: string; employee_code: string;
};
type Link = { user_id: string; person_id: string };
type Category = { id: string; code: string; name: string; parent_id: string | null };
type Level = { id: string; scale_id: string; ordinal: number; label: string; description: string | null };
type DraftLevel = { ordinal: number; label: string; description: string };
type Scale = { id: string; code: string; name: string; version: number; levels: Level[] };
type Skill = {
  id: string; category_id: string; scale_id: string; code: string;
  name: string; is_active: boolean;
};
type Evidence = { id: string; kind: string; description: string; reference: string | null };
type Assessment = {
  id: string; skill_id: string; level_id: string; source: "self" | "expert";
  status: "pending" | "approved" | "rejected"; submitted_by: string;
  reviewed_by: string | null; review_note: string | null; evidence: Evidence[];
  submitted_at: string;
};
type MatrixRow = {
  person_id: string; full_name: string; employee_code: string;
  skill_id: string; skill_name: string; level_ordinal: number;
  level_label: string; reviewed_at: string;
};

async function api<T>(path: string, options: RequestInit = {}, csrf?: string): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(path, { ...options, credentials: "same-origin", headers });
  if (!response.ok) {
    let detail = "";
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
    } catch { /* HTTP code remains available. */ }
    throw new Error(`HTTP ${response.status}${detail ? " — " + detail : ""}`);
  }
  return (await response.json()) as T;
}

const apiBase = "/api/v1/competence";
const defaultLevels: DraftLevel[] = [
  { ordinal: 0, label: "Не владеет", description: "" },
  { ordinal: 1, label: "Базовый уровень", description: "" },
  { ordinal: 2, label: "Самостоятельная работа", description: "" },
  { ordinal: 3, label: "Эксперт", description: "" },
];

export default function CompetencePanel() {
  const [authRevision, setAuthRevision] = useState(0);
  const [session, setSession] = useState<Session | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [enterpriseId, setEnterpriseId] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [scales, setScales] = useState<Scale[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [links, setLinks] = useState<Link[]>([]);
  const [ownLink, setOwnLink] = useState<Link | null>(null);
  const [selectedPerson, setSelectedPerson] = useState("");
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [matrix, setMatrix] = useState<MatrixRow[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const [catCode, setCatCode] = useState("");
  const [catName, setCatName] = useState("");
  const [catParent, setCatParent] = useState("");
  const [scaleCode, setScaleCode] = useState("");
  const [scaleName, setScaleName] = useState("");
  const [scaleVersion, setScaleVersion] = useState("1");
  const [levels, setLevels] = useState<DraftLevel[]>(defaultLevels);
  const [skillCode, setSkillCode] = useState("");
  const [skillName, setSkillName] = useState("");
  const [skillCategory, setSkillCategory] = useState("");
  const [skillScale, setSkillScale] = useState("");
  const [linkUser, setLinkUser] = useState("");
  const [linkPerson, setLinkPerson] = useState("");

  const [assessmentMode, setAssessmentMode] = useState<"self" | "expert">("expert");
  const [assessmentSkill, setAssessmentSkill] = useState("");
  const [assessmentLevel, setAssessmentLevel] = useState("");
  const [evidenceKind, setEvidenceKind] = useState("observation");
  const [evidenceDescription, setEvidenceDescription] = useState("");
  const [evidenceReference, setEvidenceReference] = useState("");
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});

  const isAdmin = session?.user.role === "admin";
  const mayReview = session?.user.role === "admin" || session?.user.role === "manager";
  const isOwnPerson = ownLink?.person_id === selectedPerson;
  const currentSkill = skills.find((skill) => skill.id === assessmentSkill);
  const currentScale = scales.find((scale) => scale.id === currentSkill?.scale_id);
  const categoryName = useMemo(
    () => new Map(categories.map((item) => [item.id, item.name])), [categories],
  );
  const skillNameById = useMemo(
    () => new Map(skills.map((item) => [item.id, item.name])), [skills],
  );
  const levelById = useMemo(() => {
    const rows = scales.flatMap((scale) => scale.levels);
    return new Map(rows.map((level) => [level.id, level.label]));
  }, [scales]);

  useEffect(() => {
    const changed = () => { setSession(null); setAuthRevision((value) => value + 1); };
    const orgChanged = () => setRefresh((value) => value + 1);
    const peopleChanged = () => setRefresh((value) => value + 1);
    window.addEventListener("twm-auth-changed", changed);
    window.addEventListener("twm-org-changed", orgChanged);
    window.addEventListener("twm-personnel-changed", peopleChanged);
    return () => {
      window.removeEventListener("twm-auth-changed", changed);
      window.removeEventListener("twm-org-changed", orgChanged);
      window.removeEventListener("twm-personnel-changed", peopleChanged);
    };
  }, []);

  useEffect(() => {
    let active = true;
    api<Session>("/api/v1/auth/me")
      .then((value) => { if (active) setSession(value); })
      .catch(() => { if (active) setSession(null); });
    return () => { active = false; };
  }, [authRevision]);

  useEffect(() => {
    if (!session) {
      setEnterprises([]); setEnterpriseId(""); setPeople([]);
      setCategories([]); setScales([]); setSkills([]);
      setAssessments([]); setMatrix([]); setOwnLink(null); setSelectedPerson("");
      return;
    }
    let active = true;
    async function load() {
      try {
        const [ents, link] = await Promise.all([
          api<Enterprise[]>("/api/v1/org/enterprises"),
          api<Link | null>(`${apiBase}/me/link`),
        ]);
        if (!active) return;
        setEnterprises(ents);
        setOwnLink(link);
        setEnterpriseId((old) => ents.find((item) => item.id === old)?.id ?? ents[0]?.id ?? "");
        if (session?.user.role === "admin") {
          const [u, l] = await Promise.all([
            api<User[]>("/api/v1/auth/users"),
            api<Link[]>(`${apiBase}/links`),
          ]);
          if (active) { setUsers(u); setLinks(l); }
        }
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "Ошибка авторизации");
      }
    }
    void load();
    return () => { active = false; };
  }, [session?.user.id, session?.user.role, refresh]);

  useEffect(() => {
    if (!session || !enterpriseId) {
      setCategories([]); setScales([]); setSkills([]); setPeople([]); setMatrix([]);
      return;
    }
    let active = true;
    async function load() {
      try {
        const [c, scalesData, skillsData, matrixData, workers] = await Promise.all([
          api<Category[]>(`${apiBase}/enterprises/${enterpriseId}/categories`),
          api<Scale[]>(`${apiBase}/enterprises/${enterpriseId}/scales`),
          api<Skill[]>(`${apiBase}/enterprises/${enterpriseId}/skills?include_archived=true`),
          api<MatrixRow[]>(`${apiBase}/enterprises/${enterpriseId}/matrix`),
          api<Person[]>(`/api/v1/personnel/enterprises/${enterpriseId}/persons?limit=100`)
            .catch(() => []),
        ]);
        if (!active) return;
        setCategories(c); setScales(scalesData); setSkills(skillsData);
        setPeople(workers); setMatrix(matrixData);
        setSelectedPerson((previous) =>
          workers.some((person) => person.id === previous) || previous === ownLink?.person_id
            ? previous : workers[0]?.id ?? ownLink?.person_id ?? "");
        setSkillCategory((old) => c.some((x) => x.id === old) ? old : c[0]?.id ?? "");
        setSkillScale((old) => scalesData.some((x) => x.id === old)
          ? old : scalesData[0]?.id ?? "");
        setAssessmentSkill((old) => skillsData.some((x) => x.id === old && x.is_active)
          ? old : skillsData.find((x) => x.is_active)?.id ?? "");
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "Ошибка каталога");
      }
    }
    void load();
    return () => { active = false; };
  }, [session?.user.id, enterpriseId, refresh, ownLink?.person_id]);

  useEffect(() => {
    const first = currentScale?.levels[0]?.id ?? "";
    setAssessmentLevel((old) =>
      currentScale?.levels.some((item) => item.id === old) ? old : first);
  }, [assessmentSkill, currentScale?.id]);

  useEffect(() => {
    if (!selectedPerson || !session) { setAssessments([]); return; }
    let active = true;
    api<Assessment[]>(`${apiBase}/persons/${selectedPerson}/assessments`)
      .then((data) => { if (active) setAssessments(data); })
      .catch((cause) => {
        if (active) {
          setAssessments([]);
          setError(cause instanceof Error ? cause.message : "Ошибка истории оценок");
        }
      });
    return () => { active = false; };
  }, [selectedPerson, session?.user.id, refresh]);

  async function submit(action: () => Promise<void>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      await action();
      setNotice(success);
      setRefresh((old) => old + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Ошибка сохранения");
    } finally { setBusy(false); }
  }

  function createCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId) return;
    void submit(async () => {
      await api(
        `${apiBase}/enterprises/${enterpriseId}/categories`,
        { method: "POST", body: JSON.stringify({
          code: catCode, name: catName, parent_id: catParent || null,
        }) },
        session.csrf_token,
      );
      setCatCode(""); setCatName(""); setCatParent("");
    }, "Категория добавлена.");
  }

  function createScale(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId) return;
    void submit(async () => {
      await api(
        `${apiBase}/enterprises/${enterpriseId}/scales`,
        { method: "POST", body: JSON.stringify({
          code: scaleCode, name: scaleName, version: Number(scaleVersion), levels,
        }) },
        session.csrf_token,
      );
      setScaleCode(""); setScaleName("");
      setScaleVersion("1"); setLevels(defaultLevels);
    }, "Новая неизменяемая версия шкалы опубликована.");
  }

  function editLevel(index: number, field: keyof DraftLevel, value: string) {
    setLevels((old) => old.map((level, i) => i === index
      ? { ...level, [field]: field === "ordinal" ? Number(value) : value }
      : level));
  }

  function createSkill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId) return;
    void submit(async () => {
      await api(
        `${apiBase}/enterprises/${enterpriseId}/skills`,
        { method: "POST", body: JSON.stringify({
          code: skillCode, name: skillName,
          category_id: skillCategory, scale_id: skillScale,
        }) },
        session.csrf_token,
      );
      setSkillCode(""); setSkillName("");
    }, "Новая компетенция добавлена.");
  }

  function linkAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    void submit(async () => {
      await api(
        `${apiBase}/links`,
        { method: "POST", body: JSON.stringify({
          user_id: linkUser, person_id: linkPerson,
        }) },
        session.csrf_token,
      );
      setLinkPerson(""); setLinkUser("");
    }, "Учётная запись связана с сотрудником.");
  }

  function addAssessment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !selectedPerson || !assessmentSkill || !assessmentLevel) return;
    const type = assessmentMode === "self" ? "self" : "expert";
    void submit(async () => {
      await api(
        `${apiBase}/persons/${selectedPerson}/${type}-assessments`,
        {
          method: "POST",
          body: JSON.stringify({
            skill_id: assessmentSkill, level_id: assessmentLevel,
            evidence: evidenceDescription.trim()
              ? [{
                kind: evidenceKind,
                description: evidenceDescription,
                reference: evidenceReference || null,
              }]
              : [],
          }),
        },
        session.csrf_token,
      );
      setEvidenceDescription(""); setEvidenceReference("");
    }, "Оценка отправлена на независимую проверку.");
  }

  function review(id: string, decision: "approved" | "rejected") {
    if (!session) return;
    const note = reviewNotes[id]?.trim() ?? "";
    if (note.length < 10) { setError("Укажите обоснование решения не короче 10 символов."); return; }
    void submit(
      () => api(
        `${apiBase}/assessments/${id}/review`,
        { method: "POST", body: JSON.stringify({ decision, note }) },
        session.csrf_token,
      ),
      decision === "approved" ? "Оценка подтверждена." : "Оценка отклонена.",
    );
  }

  const activeSkills = skills.filter((skill) => skill.is_active);
  const ownUser = session?.user.id;

  return (
    <section className="skill-panel" id="competence" aria-labelledby="skill-title">
      <div className="section-heading">
        <div>
          <div className="eyebrow">COMPETENCE MANAGEMENT · VERIFIED SKILLS</div>
          <h2 id="skill-title">Компетенции и квалификационная матрица</h2>
        </div>
        <span className="skill-kpi">{matrix.length} подтверждённых записей</span>
      </div>
      <p className="skill-lead">
        Каталог навыков, версионированные шкалы, самооценки и независимое подтверждение.
        Матрица учитывает только утверждённые оценки.
      </p>
      {!session && <p className="skill-empty">Авторизуйтесь, чтобы открыть доступный каталог.</p>}
      {session && (
        <>
          <label className="skill-select-enterprise">
            Предприятие
            <select value={enterpriseId} onChange={(e) => setEnterpriseId(e.target.value)}>
              {enterprises.length === 0 && <option value="">Нет доступных предприятий</option>}
              {enterprises.map((ent) => (
                <option key={ent.id} value={ent.id}>{ent.name}</option>
              ))}
            </select>
          </label>

          <div className="skill-overview">
            <article><strong>{categories.length}</strong><span>Категории</span></article>
            <article><strong>{activeSkills.length}</strong><span>Активные навыки</span></article>
            <article><strong>{scales.length}</strong><span>Версии шкал</span></article>
            <article><strong>{assessments.filter((a) => a.status === "pending").length}</strong>
              <span>Ожидают оценки (выбранный сотрудник)</span></article>
          </div>

          <div className="skill-two-column">
            <div>
              <h3>Каталог компетенций</h3>
              <div className="skill-collection">
                {activeSkills.map((skill) => {
                  const scale = scales.find((item) => item.id === skill.scale_id);
                  return (
                    <div key={skill.id} className="skill-catalog-item">
                      <strong>{skill.name}</strong>
                      <small>{skill.code} · {categoryName.get(skill.category_id) ?? "—"} ·
                        {scale ? ` ${scale.name}, v${scale.version}` : " Шкала не найдена"}</small>
                    </div>
                  );
                })}
                {activeSkills.length === 0 && <p className="skill-empty">Навыков пока нет.</p>}
              </div>
            </div>
            <div>
              <h3>Версии шкал</h3>
              <div className="skill-collection">
                {scales.map((scale) => (
                  <div className="skill-catalog-item" key={scale.id}>
                    <strong>{scale.name} · v{scale.version}</strong>
                    <small>{scale.levels.map((level) =>
                      `${level.ordinal}: ${level.label}`).join(" · ")}</small>
                  </div>
                ))}
                {scales.length === 0 && <p className="skill-empty">Создайте шкалу для оценки.</p>}
              </div>
            </div>
          </div>

          {isAdmin && enterpriseId && (
            <div className="skill-config">
              <h3>Конфигуратор компетенций</h3>
              <details>
                <summary>Добавить категорию навыков</summary>
                <form className="skill-form" onSubmit={createCategory}>
                  <label>Код<input required pattern="[a-zA-Z0-9_.-]+" maxLength={64}
                    value={catCode} onChange={(e) => setCatCode(e.target.value)} /></label>
                  <label>Название<input required maxLength={160}
                    value={catName} onChange={(e) => setCatName(e.target.value)} /></label>
                  <label>Родительская категория
                    <select value={catParent} onChange={(e) => setCatParent(e.target.value)}>
                      <option value="">Корневая</option>
                      {categories.map((row) => (
                        <option key={row.id} value={row.id}>{row.name}</option>
                      ))}
                    </select>
                  </label>
                  <button className="skill-button" disabled={busy}>Добавить</button>
                </form>
              </details>
              <details>
                <summary>Опубликовать версию шкалы оценки</summary>
                <form className="skill-form" onSubmit={createScale}>
                  <label>Код шкалы
                    <input required pattern="[a-zA-Z0-9_.-]+" maxLength={64}
                      value={scaleCode} onChange={(e) => setScaleCode(e.target.value)} />
                  </label>
                  <label>Название
                    <input required maxLength={160} value={scaleName}
                      onChange={(e) => setScaleName(e.target.value)} />
                  </label>
                  <label>Версия
                    <input type="number" min={1} value={scaleVersion}
                      onChange={(e) => setScaleVersion(e.target.value)} required />
                  </label>
                  <div className="skill-levels">
                    {levels.map((level, index) => (
                      <div className="skill-level-edit" key={index}>
                        <label>Уровень
                          <input type="number" min={0} max={100} required
                            value={level.ordinal}
                            onChange={(e) => editLevel(index, "ordinal", e.target.value)} />
                        </label>
                        <label>Название уровня
                          <input maxLength={100} required value={level.label}
                            onChange={(e) => editLevel(index, "label", e.target.value)} />
                        </label>
                        <label>Описание
                          <input maxLength={1000} value={level.description}
                            onChange={(e) => editLevel(index, "description", e.target.value)} />
                        </label>
                        <button type="button" className="skill-button skill-secondary"
                          disabled={levels.length <= 2}
                          onClick={() => setLevels((old) => old.filter((_, i) => i !== index))}>
                          Удалить
                        </button>
                      </div>
                    ))}
                    <button type="button" className="skill-button skill-secondary"
                      disabled={levels.length >= 10}
                      onClick={() => setLevels((old) => [...old, {
                        ordinal: Math.max(...old.map((item) => item.ordinal)) + 1,
                        label: "", description: "",
                      }])}>
                      + Уровень
                    </button>
                  </div>
                  <p className="skill-hint">После публикации значения не меняются. Для новой
                    шкалы создайте следующую версию с тем же кодом.</p>
                  <button className="skill-button" disabled={busy}>Опубликовать</button>
                </form>
              </details>
              <details>
                <summary>Создать навык</summary>
                <form className="skill-form" onSubmit={createSkill}>
                  <label>Код<input required pattern="[a-zA-Z0-9_.-]+" maxLength={64}
                    value={skillCode} onChange={(e) => setSkillCode(e.target.value)} /></label>
                  <label>Название<input required maxLength={160} value={skillName}
                    onChange={(e) => setSkillName(e.target.value)} /></label>
                  <label>Категория
                    <select required value={skillCategory}
                      onChange={(e) => setSkillCategory(e.target.value)}>
                      <option value="">Выберите категорию</option>
                      {categories.map((cat) => <option key={cat.id}
                        value={cat.id}>{cat.name}</option>)}
                    </select>
                  </label>
                  <label>Шкала (зафиксированная версия)
                    <select required value={skillScale}
                      onChange={(e) => setSkillScale(e.target.value)}>
                      <option value="">Выберите шкалу</option>
                      {scales.map((scale) => (
                        <option key={scale.id} value={scale.id}>
                          {scale.name} v{scale.version}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button className="skill-button" disabled={busy}>Создать навык</button>
                </form>
              </details>
              <details>
                <summary>Связать пользователя с сотрудником для самооценки</summary>
                <form className="skill-form" onSubmit={linkAccount}>
                  <label>Учётная запись
                    <select required value={linkUser}
                      onChange={(e) => setLinkUser(e.target.value)}>
                      <option value="">Выберите пользователя</option>
                      {users.filter((u) => !links.some((l) => l.user_id === u.id))
                        .map((user) => (
                          <option key={user.id} value={user.id}>{user.username}</option>
                        ))}
                    </select>
                  </label>
                  <label>Сотрудник
                    <select required value={linkPerson}
                      onChange={(e) => setLinkPerson(e.target.value)}>
                      <option value="">Выберите сотрудника</option>
                      {people.filter((p) => !links.some((l) => l.person_id === p.id))
                        .map((person) => (
                          <option key={person.id} value={person.id}>
                            {person.last_name} {person.first_name} · {person.employee_code}
                          </option>
                        ))}
                    </select>
                  </label>
                  <button className="skill-button" disabled={busy}>Связать</button>
                </form>
              </details>
            </div>
          )}

          {enterpriseId && (
            <div className="skill-assessment-section">
              <h3>Оценки специалиста</h3>
              <label className="skill-select-enterprise">
                Сотрудник
                <select value={selectedPerson}
                  onChange={(e) => setSelectedPerson(e.target.value)}>
                  <option value="">Выберите сотрудника</option>
                  {people.map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.last_name} {person.first_name} · {person.employee_code}
                    </option>
                  ))}
                  {ownLink && !people.some((p) => p.id === ownLink.person_id) && (
                    <option value={ownLink.person_id}>Моя карточка</option>
                  )}
                </select>
              </label>

              {selectedPerson && (mayReview || isOwnPerson) && (
                <form className="skill-form skill-assess-form" onSubmit={addAssessment}>
                  <h4>Новая оценка (статус «На проверке»)</h4>
                  <label>Источник оценки
                    <select value={isOwnPerson ? "self" : assessmentMode}
                      onChange={(e) => setAssessmentMode(e.target.value as "self" | "expert")}>
                      {isOwnPerson && <option value="self">Самооценка</option>}
                      {mayReview && !isOwnPerson && <option value="expert">Экспертная оценка</option>}
                    </select>
                  </label>
                  <label>Навык
                    <select required value={assessmentSkill}
                      onChange={(e) => setAssessmentSkill(e.target.value)}>
                      <option value="">Выберите навык</option>
                      {activeSkills.map((skill) => (
                        <option value={skill.id} key={skill.id}>{skill.name}</option>
                      ))}
                    </select>
                  </label>
                  <label>Уровень по шкале
                    <select required value={assessmentLevel}
                      onChange={(e) => setAssessmentLevel(e.target.value)}>
                      <option value="">Выберите уровень</option>
                      {currentScale?.levels.map((level) => (
                        <option key={level.id} value={level.id}>
                          {level.ordinal} — {level.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>Вид подтверждения
                    <select value={evidenceKind}
                      onChange={(e) => setEvidenceKind(e.target.value)}>
                      <option value="observation">Наблюдение</option>
                      <option value="training">Обучение</option>
                      <option value="document">Документ</option>
                      <option value="other">Другое</option>
                    </select>
                  </label>
                  <label className="skill-wide">Описание подтверждения (от 10 символов)
                    <textarea minLength={10} maxLength={1500} required
                      value={evidenceDescription}
                      onChange={(e) => setEvidenceDescription(e.target.value)} />
                  </label>
                  <label>Номер или ссылка на подтверждение (не файл)
                    <input maxLength={250} value={evidenceReference}
                      onChange={(e) => setEvidenceReference(e.target.value)} />
                  </label>
                  <button className="skill-button" disabled={busy || !assessmentLevel}>
                    Отправить на проверку
                  </button>
                </form>
              )}

              <div className="skill-assessment-list">
                {assessments.map((item) => {
                  const canDecide = mayReview && item.status === "pending" &&
                    item.submitted_by !== ownUser && !isOwnPerson;
                  return (
                    <article className="skill-assessment" key={item.id}>
                      <div className="skill-assessment-heading">
                        <strong>{skillNameById.get(item.skill_id) ?? "Навык"}</strong>
                        <span className={`skill-state skill-state-${item.status}`}>
                          {item.status === "pending" ? "На проверке" :
                            item.status === "approved" ? "Подтверждено" : "Отклонено"}
                        </span>
                      </div>
                      <p>Уровень: <strong>{levelById.get(item.level_id) ?? "—"}</strong> ·
                        {item.source === "self" ? " Самооценка" : " Экспертная оценка"}</p>
                      {item.evidence.map((ev) => (
                        <p className="skill-evidence" key={ev.id}>
                          {ev.kind}: {ev.description}
                          {ev.reference && ` · № ${ev.reference}`}
                        </p>
                      ))}
                      {item.review_note && <p className="skill-evidence">
                        Решение: {item.review_note}
                      </p>}
                      {canDecide && (
                        <div className="skill-review">
                          <label>Обоснование решения
                            <input value={reviewNotes[item.id] ?? ""} minLength={10}
                              maxLength={1200} placeholder="Не менее 10 символов"
                              onChange={(e) => setReviewNotes((old) => ({
                                ...old, [item.id]: e.target.value,
                              }))} />
                          </label>
                          <button className="skill-button" type="button" disabled={busy}
                            onClick={() => review(item.id, "approved")}>Подтвердить</button>
                          <button className="skill-button skill-secondary" type="button"
                            disabled={busy} onClick={() => review(item.id, "rejected")}>
                            Отклонить
                          </button>
                        </div>
                      )}
                    </article>
                  );
                })}
                {selectedPerson && assessments.length === 0 &&
                  <p className="skill-empty">Оценок для сотрудника пока нет.</p>}
              </div>
            </div>
          )}

          <div className="skill-matrix">
            <h3>Матрица подтверждённых компетенций</h3>
            <p className="skill-hint">
              Показывается последняя утверждённая оценка по каждому навыку
              каждого доступного сотрудника. Непроверенные оценки не учитываются.
            </p>
            <div className="skill-table-wrap">
              <table>
                <thead><tr>
                  <th>Сотрудник</th><th>Компетенция</th><th>Уровень</th><th>Подтверждено</th>
                </tr></thead>
                <tbody>
                  {matrix.map((row) => (
                    <tr key={`${row.person_id}-${row.skill_id}`}>
                      <td>{row.full_name}<small>{row.employee_code}</small></td>
                      <td>{row.skill_name}</td>
                      <td>{row.level_ordinal} — {row.level_label}</td>
                      <td>{row.reviewed_at.slice(0, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {matrix.length === 0 && <p className="skill-empty">
                Подтверждённых оценок в разрешённой области пока нет.
              </p>}
            </div>
          </div>
        </>
      )}
      {error && <p className="skill-error" role="alert">{error}</p>}
      {notice && <p className="skill-notice" role="status">{notice}</p>}
    </section>
  );
}
