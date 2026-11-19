import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useWorkspace } from "./WorkspaceContext";
import WorkflowDesigner, {
  initialWorkflow, type WorkflowDocument, type WorkflowVersion,
  type FormField, type WorkflowTransition,
} from "./WorkflowDesigner";

type ServiceCase = {
  id: string; enterprise_id: string; unit_id: string;
  workflow_code: string; workflow_version: number;
  title: string; state: string; created_by: string;
  values: Record<string, string | number | boolean>;
};

type CaseEvent = {
  id: string; from_state: string | null; to_state: string;
  transition_code: string; actor_id: string; created_at: string; note: string;
};

const base = "/api/v1/configuration";

async function api<T>(
  path: string, csrf?: string, method = "GET", payload?: unknown,
): Promise<T> {
  const response = await fetch(base + path, {
    credentials: "same-origin", method,
    headers: {
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...(payload === undefined ? {} : { "Content-Type": "application/json" }),
    },
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  });
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json() as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch { /* HTTP status remains actionable. */ }
    throw Error("HTTP " + response.status + (detail ? " — " + detail : ""));
  }
  return await response.json() as T;
}

function formValue(field: FormField, values: Record<string, unknown>): string | number | boolean {
  const v = values[field.code];
  return field.kind === "boolean" ? Boolean(v) : typeof v === "string" || typeof v === "number"
    ? v : "";
}

export default function WorkflowConfiguratorV2() {
  const { session, enterpriseId, units, unitId } = useWorkspace();
  const admin = session?.user.role === "admin";
  const [versions, setVersions] = useState<WorkflowVersion[]>([]);
  const [active, setActive] = useState<WorkflowVersion[]>([]);
  const [cases, setCases] = useState<ServiceCase[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [templateCode, setTemplateCode] = useState("service_intake");
  const [templateTitle, setTemplateTitle] = useState("Заявка технической службе");
  const [document, setDocument] = useState<WorkflowDocument>(initialWorkflow);
  const [effectiveDate, setEffectiveDate] = useState(
    () => new Date().toISOString().slice(0, 10),
  );
  const [requestTemplate, setRequestTemplate] = useState("");
  const [requestUnit, setRequestUnit] = useState("");
  const [requestTitle, setRequestTitle] = useState("");
  const [requestValues, setRequestValues] = useState<Record<string, unknown>>({});
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [pinned, setPinned] = useState<WorkflowVersion | null>(null);
  const [history, setHistory] = useState<CaseEvent[]>([]);
  const [reviewNote, setReviewNote] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [working, setWorking] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const selectedVersion = versions.find((item) => item.id === selectedVersionId);
  const selectedCase = cases.find((item) => item.id === selectedCaseId);
  const activeTemplate = active.find((item) => item.code === requestTemplate);
  const chosenUnit = units.some((unit) => unit.id === requestUnit) ? requestUnit : unitId;
  const fields = activeTemplate?.document.fields ?? [];
  const allowedRoutes = useMemo(() => {
    if (!pinned || !selectedCase || !session) return [];
    return pinned.document.transitions.filter((route) =>
      route.from_state === selectedCase.state &&
      (!route.independent_review || selectedCase.created_by !== session.user.id) &&
      (route.actor === "creator" ? selectedCase.created_by === session.user.id
        : route.actor === "manager"
          ? session.user.role === "manager" || session.user.role === "admin"
          : session.user.role === "admin")
    );
  }, [pinned, selectedCase, session?.user.id, session?.user.role]);

  useEffect(() => {
    // Security boundary: reset all prior company/account selections immediately.
    setVersions([]); setActive([]); setCases([]);
    setSelectedVersionId(""); setSelectedCaseId(""); setPinned(null);
    setTemplateCode("service_intake");
    setTemplateTitle("Заявка технической службе");
    setDocument(initialWorkflow());
    setRequestTemplate(""); setRequestUnit(""); setRequestTitle("");
    setRequestValues({}); setReviewNote("");
    setNotice(""); setError("");
  }, [enterpriseId, session?.user.id]);

  useEffect(() => {
    if (!enterpriseId || !session) return;
    let live = true;
    setLoading(true);
    Promise.all([
      api<WorkflowVersion[]>(`/enterprises/${enterpriseId}/workflows/active`),
      api<ServiceCase[]>(`/enterprises/${enterpriseId}/service-requests`),
      admin
        ? api<WorkflowVersion[]>(`/enterprises/${enterpriseId}/workflow-versions`)
        : Promise.resolve([] as WorkflowVersion[]),
    ]).then(([published, requestList, all]) => {
      if (!live) return;
      setActive(published); setCases(requestList); setVersions(all);
      const picked = all.find((item) => item.id === selectedVersionId) ?? all[0];
      setSelectedVersionId(picked?.id ?? "");
      if (picked) {
        setTemplateCode(picked.code);
        setTemplateTitle(picked.title);
        setDocument(picked.document);
      }
      setSelectedCaseId((old) =>
        requestList.some((item) => item.id === old) ? old : requestList[0]?.id ?? "");
    }).catch((reason: unknown) => {
      if (live) setError(reason instanceof Error ? reason.message : "Ошибка workflow API");
    }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [enterpriseId, session?.user.id, admin, refresh]);

  useEffect(() => {
    setPinned(null); setHistory([]);
    if (!selectedCaseId || !session) return;
    let active = true;
    Promise.all([
      api<WorkflowVersion>(`/service-requests/${selectedCaseId}/definition`),
      api<CaseEvent[]>(`/service-requests/${selectedCaseId}/history`),
    ]).then(([version, log]) => {
      if (!active) return;
      setPinned(version); setHistory(log);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Ошибка истории");
    });
    return () => { active = false; };
  }, [selectedCaseId, session?.user.id, refresh]);

  useEffect(() => {
    if (!requestTemplate || !active.some((item) => item.code === requestTemplate)) {
      setRequestTemplate(active[0]?.code ?? "");
    }
  }, [active, requestTemplate]);

  async function mutate<T>(task: () => Promise<T>, message: string, after?: (row: T) => void) {
    setWorking(true); setError(""); setNotice("");
    try {
      const row = await task();
      after?.(row);
      setNotice(message);
      setRefresh((old) => old + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Операция отклонена");
    } finally {
      setWorking(false);
    }
  }

  function newDraft() {
    setSelectedVersionId("");
    setDocument(active[0]?.document ?? initialWorkflow());
    setTemplateCode(active[0]?.code ?? "service_intake");
    setTemplateTitle(active[0]?.title ?? "Заявка технической службе");
  }

  function selectVersion(id: string) {
    setSelectedVersionId(id);
    const item = versions.find((version) => version.id === id);
    if (item) {
      setTemplateCode(item.code);
      setTemplateTitle(item.title);
      setDocument(item.document);
    } else newDraft();
  }

  function saveTemplate(event: FormEvent) {
    event.preventDefault();
    if (!session || !enterpriseId || !admin) return;
    const data = { code: templateCode, title: templateTitle, document };
    const url = selectedVersion
      ? `/workflow-versions/${selectedVersion.id}`
      : `/enterprises/${enterpriseId}/workflow-versions`;
    void mutate(
      () => api<WorkflowVersion>(
        url, session.csrf_token, selectedVersion ? "PUT" : "POST", data,
      ), "Версия сохранена. Для публикации требуется независимое согласование.",
      (row) => setSelectedVersionId(row.id),
    );
  }

  function advance(step: "validate" | "approve" | "publish") {
    if (!selectedVersion || !session || !admin) return;
    void mutate(
      () => api<WorkflowVersion>(
        `/workflow-versions/${selectedVersion.id}/${step}`, session.csrf_token,
        "POST", step === "publish" ? { effective_on: effectiveDate } : undefined,
      ), "Переход версии выполнен.",
    );
  }

  function createRequest(event: FormEvent) {
    event.preventDefault();
    if (!enterpriseId || !session || !activeTemplate || !chosenUnit) return;
    const values: Record<string, string | number | boolean> = {};
    for (const field of fields) {
      const v = requestValues[field.code];
      if (field.kind === "boolean" && (typeof v === "boolean" || field.required)) {
        values[field.code] = v === true;
      } else if (field.kind === "integer" && v !== "" && v != null) {
        values[field.code] = Number(v);
      } else if (typeof v === "string" && v.trim()) {
        values[field.code] = v.trim();
      }
    }
    void mutate(() => api<ServiceCase>(
      `/enterprises/${enterpriseId}/service-requests`, session.csrf_token,
      "POST", {
        workflow_code: activeTemplate.code, unit_id: chosenUnit,
        title: requestTitle.trim(), values,
      },
    ), "Заявка создана в исходном состоянии.", (row) => {
      setSelectedCaseId(row.id); setRequestTitle(""); setRequestValues({});
    });
  }

  function perform(route: WorkflowTransition) {
    if (!session || !selectedCase) return;
    void mutate(() => api<ServiceCase>(
      `/service-requests/${selectedCase.id}/transitions`, session.csrf_token,
      "POST", {
        transition_code: route.code, expected_state: selectedCase.state,
        note: reviewNote,
      },
    ), "Переход сохранён в журнале заявки.", () => setReviewNote(""));
  }

  if (!session || !enterpriseId) return null;
  return <section className="config-workflow-v2" aria-label="Конфигуратор маршрутов заявок">
    <div className="config-heading">
      <div>
        <div className="eyebrow">CONFIGURATOR V2 · SERVICE INTAKE</div>
        <h3>Формы и маршруты рассмотрения заявок технической службы</h3>
        <p>Отдельные информационные заявки. Настройки не изменяют наряды, допуски,
          разрешения на работы и правила безопасности.</p>
      </div>
      <button type="button" disabled={working}
        onClick={() => setRefresh((n) => n + 1)}>Обновить маршруты</button>
    </div>
    {loading && <p role="status">Загрузка маршрутов…</p>}
    {error && <p role="alert" className="config-error">{error}</p>}
    {notice && <p role="status" className="config-notice">{notice}</p>}

    {admin && <details className="config-workflow">
      <summary>Редактор форм, состояний и маршрутов согласования</summary>
      <p className="org-hint">Черновик → валидация → независимое согласование
        другого администратора → публикация с датой вступления в силу.</p>
      <label>Версия шаблона
        <select aria-label="Версия маршрута" value={selectedVersionId}
          onChange={(e) => selectVersion(e.target.value)}>
          <option value="">Новая версия</option>
          {versions.map((row) => <option value={row.id} key={row.id}>
            {row.code} · v{row.version} · {row.status}
          </option>)}
        </select>
      </label>
      <button type="button" disabled={working} onClick={newDraft}>
        Новый шаблон или черновик
      </button>
      <form onSubmit={saveTemplate}>
        <label>Код шаблона
          <input required value={templateCode} maxLength={40}
            pattern="[a-z][a-z0-9_]*" disabled={!!selectedVersion || working}
            onChange={(e) => setTemplateCode(e.target.value)} />
        </label>
        <label>Название шаблона
          <input required value={templateTitle} maxLength={100}
            disabled={!!selectedVersion && selectedVersion.status !== "draft" || working}
            onChange={(e) => setTemplateTitle(e.target.value)} />
        </label>
        <WorkflowDesigner value={document} onChange={setDocument}
          disabled={working || (!!selectedVersion && selectedVersion.status !== "draft")} />
        {(!selectedVersion || selectedVersion.status === "draft") && (
          <button type="submit" disabled={working}>Сохранить черновик маршрута</button>
        )}
      </form>
      {selectedVersion && <div className="config-workflow">
        <h4>Управление публикацией v{selectedVersion.version}</h4>
        <p>Состояние: {selectedVersion.status}. Автор: {selectedVersion.created_by.slice(0, 8)}</p>
        {selectedVersion.status === "draft" && <button type="button"
          disabled={working} onClick={() => advance("validate")}>Проверить маршрут</button>}
        {selectedVersion.status === "validated" && <button type="button"
          disabled={working || selectedVersion.created_by === session.user.id}
          onClick={() => advance("approve")}>Согласовать (другой администратор)</button>}
        {selectedVersion.status === "approved" && <>
          <label>Дата вступления в силу (UTC)
            <input type="date" value={effectiveDate}
              onChange={(e) => setEffectiveDate(e.target.value)} />
          </label>
          <button type="button" disabled={working}
            onClick={() => advance("publish")}>Опубликовать маршрут</button>
        </>}
        {selectedVersion.status === "published" &&
          <p>Версия неизменяема. Открытые заявки сохраняют ссылку на эту версию.</p>}
      </div>}
    </details>}

    <div className="config-workflow">
      <h4>Создать информационную заявку</h4>
      {active.length === 0 && <p>Нет действующих опубликованных маршрутов.</p>}
      {active.length > 0 && <form className="config-form" onSubmit={createRequest}>
        <label>Вид заявки
          <select value={requestTemplate} aria-label="Вид заявки"
            onChange={(e) => { setRequestTemplate(e.target.value); setRequestValues({}); }}>
            {active.map((row) => <option key={row.code} value={row.code}>
              {row.title} · v{row.version}</option>)}
          </select>
        </label>
        <label>Подразделение
          <select value={chosenUnit} required
            onChange={(e) => setRequestUnit(e.target.value)}>
            <option value="">Выберите подразделение</option>
            {units.map((unit) => <option key={unit.id} value={unit.id}>
              {unit.name}</option>)}
          </select>
        </label>
        <label>Тема
          <input required minLength={3} maxLength={200} value={requestTitle}
            onChange={(e) => setRequestTitle(e.target.value)} />
        </label>
        {fields.map((field) => <label key={field.code}>
          {field.label}{field.required ? " · обязательно" : ""}
          {field.kind === "boolean" ? <input type="checkbox"
            checked={formValue(field, requestValues) === true}
            onChange={(e) => setRequestValues((old) => ({
              ...old, [field.code]: e.target.checked,
            }))} /> : field.kind === "choice" ? <select
              value={String(formValue(field, requestValues))}
              required={field.required}
              onChange={(e) => setRequestValues((old) => ({
                ...old, [field.code]: e.target.value,
              }))}>
              <option value="">Выберите</option>
              {field.options.map((opt) => <option value={opt} key={opt}>{opt}</option>)}
            </select> : <input
              type={field.kind === "integer" ? "number" : "text"}
              required={field.required} maxLength={field.max_length ?? undefined}
              min={field.min_value ?? undefined} max={field.max_value ?? undefined}
              value={formValue(field, requestValues) as string | number}
              onChange={(e) => setRequestValues((old) => ({
                ...old, [field.code]: e.target.value,
              }))} />}
        </label>)}
        <button type="submit" disabled={working || !chosenUnit || !activeTemplate}>
          Создать заявку
        </button>
      </form>}
    </div>

    <div className="config-workflow">
      <h4>Заявки в области доступа</h4>
      {cases.length === 0 && <p>Заявок пока нет.</p>}
      {cases.length > 0 && <label>Текущая заявка
        <select value={selectedCaseId} onChange={(e) => setSelectedCaseId(e.target.value)}>
          {cases.map((row) => <option key={row.id} value={row.id}>
            {row.title} · {row.state}
          </option>)}
        </select>
      </label>}
      {selectedCase && <>
        <p><strong>{selectedCase.title}</strong> · {selectedCase.workflow_code}
          {" · "}v{selectedCase.workflow_version} · {selectedCase.state}</p>
        <p>Настройки и доступные действия берутся из закреплённой версии маршрута.</p>
        {pinned?.document.fields.map((field) => (
          <p key={field.code}>{field.label}: {String(selectedCase.values[field.code] ?? "—")}</p>
        ))}
        {allowedRoutes.length > 0 && <>
          <label>Комментарий к решению (не менее 10 символов для независимого согласования)
            <input maxLength={400} value={reviewNote}
              onChange={(e) => setReviewNote(e.target.value)} />
          </label>
          <div className="config-actions">
            {allowedRoutes.map((route) => <button key={route.code}
              type="button"
              disabled={working || (route.independent_review && reviewNote.trim().length < 10)}
              onClick={() => perform(route)}>{route.label}</button>)}
          </div>
        </>}
        <details>
          <summary>История рассмотрения ({history.length})</summary>
          {history.map((event) => <p key={event.id}>
            {event.from_state ?? "Создана"} → {event.to_state}
            {" · "}{event.transition_code}
            {event.note ? " · " + event.note : ""}
          </p>)}
        </details>
      </>}
    </div>
    <p className="workspace-warning">
      Маршрут рассмотрения заявки не является физическим допуском к работам,
      изменением наряда, подтверждением квалификации или разрешением на оборудование.
    </p>
  </section>;
}
