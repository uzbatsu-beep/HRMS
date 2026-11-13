import { FormEvent, useEffect, useMemo, useState } from "react";
import { useWorkspace } from "./WorkspaceContext";
import WorkExecutionPanel from "./WorkExecutionPanel";
import WorkEquipmentPermitPanel from "./WorkEquipmentPermitPanel";

type User = { id: string; username: string; role: "admin" | "manager" | "viewer" };
type Session = { user: User; csrf_token: string };
type Enterprise = { id: string; name: string; code: string };
type Unit = { id: string; name: string; code: string };
type Skill = { id: string; name: string; code: string; scale_id: string; is_active: boolean };
type ScaleLevel = { id: string; ordinal: number; label: string };
type Scale = { id: string; code: string; version: number; name: string; levels: ScaleLevel[] };
type Requirement = { id: string; activity_code: string; type_id: string };
type WorkRequirement = {
  id: string; skill_id: string; skill_name: string;
  min_level_id: string; min_ordinal: number;
};
type WorkAssignment = {
  id: string; person_id: string; resource_id: string;
  reservation_id: string; assigned_at: string;
};
type Work = {
  id: string; enterprise_id: string; unit_id: string; code: string; title: string;
  description: string | null; activity_code: string;
  starts_at: string; ends_at: string;
  status: "open" | "assigned" | "in_progress" | "on_hold" | "completed" | "cancelled";
  priority: "routine" | "normal" | "urgent" | "critical";
  crew: { id: string; person_id: string; role: string; reservation_id: string; removed_at: string | null }[];
  hold_reason: string | null; last_safety_check_at: string | null;
  required_skills: WorkRequirement[];
  assignment: WorkAssignment | null;
};
type Candidate = {
  person_id: string; resource_id: string | null; employee_code: string;
  full_name: string; eligible: boolean;
  blockers: { source: string; code: string; message: string }[];
  verified_skills: string[]; verified_credentials: string[];
};
type DraftRequirement = { skill_id: string; min_level_id: string };

const base = "/api/v1/work";
const statuses: Record<Work["status"], string> = {
  open: "Открыт", assigned: "Исполнитель назначен",
  in_progress: "В работе", on_hold: "На удержании",
  completed: "Выполнен", cancelled: "Отменён",
};
const sources: Record<string, string> = {
  person: "Сотрудник", organization: "Подразделение", equipment: "Оборудование",
  skill: "Компетенция", credential: "Допуск", calendar: "График",
};
const readableCodes: Record<string, string> = {
  WRONG_WORK_UNIT: "Специалист состоит в другом подразделении",
  MISSING_VERIFIED_SKILL: "Отсутствует утверждённый уровень компетенции",
  INSUFFICIENT_SKILL_LEVEL: "Подтверждённый уровень ниже обязательного",
  INVALID_SKILL_POLICY: "Требуемый навык архивирован или неверен",
  NO_POLICY: "Не настроены обязательные документы для вида работ",
  MISSING_CREDENTIAL: "Отсутствует обязательный допуск",
  UNVERIFIED_CREDENTIAL: "Документ ещё не подтверждён",
  EXPIRED_CREDENTIAL: "Документ просрочен",
  REVOKED_CREDENTIAL: "Документ отозван",
  NO_SHIFT: "Нет смены, полностью покрывающей период",
  BOOKED: "Интервал уже занят",
  ABSENT: "Отсутствие пересекает интервал",
  CALENDAR_CLOSED: "Нерабочий день предприятия",
};
const localInput = (value: Date) => {
  const pad = (x: number) => String(x).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
};
const futureInput = (hours: number) => localInput(new Date(Date.now() + hours * 3600000));
const dateLabel = (s: string) => new Date(s).toLocaleString("ru-RU", {
  day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
});
async function api<T>(path: string, options: RequestInit = {}, csrf?: string): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const result = await fetch(path, { credentials: "same-origin", ...options, headers });
  if (!result.ok) {
    let message: string | undefined;
    try {
      const error = (await result.json()) as {
        detail?: string | { message?: string; blockers?: Candidate["blockers"] };
      };
      if (typeof error.detail === "string") message = error.detail;
      else if (error.detail && typeof error.detail === "object") {
        message = error.detail.message;
        if (error.detail.blockers?.length) {
          message += ": " + error.detail.blockers.map((block) =>
            `${sources[block.source] ?? block.source}: ${readableCodes[block.code] ?? block.message}`,
          ).join("; ");
        }
      }
    } catch { /* Preserve the HTTP error code. */ }
    throw new Error(`HTTP ${result.status}${message ? ": " + message : ""}`);
  }
  return await result.json() as T;
}

export default function WorkPanel() {
  const [session, setSession] = useState<Session | null>(null);
  const [authVersion, setAuthVersion] = useState(0);
  const [revision, setRevision] = useState(0);
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const { enterpriseId, setEnterpriseId,
    unitId: workspaceUnitId, setUnitId: setWorkspaceUnitId } = useWorkspace();
  const [units, setUnits] = useState<Unit[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [scales, setScales] = useState<Scale[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [orders, setOrders] = useState<Work[]>([]);
  const [selectedOrderId, setSelectedOrderId] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [unitId, setUnitId] = useState("");
  const [activityCode, setActivityCode] = useState("");
  const [priority, setPriority] = useState<Work["priority"]>("normal");
  const [start, setStart] = useState(futureInput(24));
  const [end, setEnd] = useState(futureInput(25));
  const [required, setRequired] = useState<DraftRequirement[]>([
    { skill_id: "", min_level_id: "" },
  ]);

  const dispatcher = session?.user.role === "admin" || session?.user.role === "manager";
  const selectedOrder = orders.find((work) => work.id === selectedOrderId);
  const activeSkills = useMemo(() => skills.filter((s) => s.is_active), [skills]);
  const activityCodes = useMemo(
    () => [...new Set(requirements.map((r) => r.activity_code))].sort(),
    [requirements],
  );
  const skillName = useMemo(
    () => new Map(skills.map((skill) => [skill.id, skill.name])), [skills],
  );
  const unitName = useMemo(
    () => new Map(units.map((unit) => [unit.id, unit.name])), [units],
  );

  useEffect(() => {
    const auth = () => { setSession(null); setAuthVersion((x) => x + 1); };
    const update = () => setRevision((x) => x + 1);
    window.addEventListener("twm-auth-changed", auth);
    window.addEventListener("twm-org-changed", update);
    window.addEventListener("twm-personnel-changed", update);
    return () => {
      window.removeEventListener("twm-auth-changed", auth);
      window.removeEventListener("twm-org-changed", update);
      window.removeEventListener("twm-personnel-changed", update);
    };
  }, []);

  useEffect(() => {
    let active = true;
    api<Session>("/api/v1/auth/me")
      .then((value) => { if (active) setSession(value); })
      .catch(() => { if (active) setSession(null); });
    return () => { active = false; };
  }, [authVersion]);

  useEffect(() => {
    if (!session) {
      setEnterprises([]); setOrders([]); setCandidates([]);
      return;
    }
    let active = true;
    api<Enterprise[]>("/api/v1/org/enterprises")
      .then((rows) => {
        if (!active) return;
        setEnterprises(rows);
        setEnterpriseId((old) => rows.some((row) => row.id === old)
          ? old : rows[0]?.id ?? "");
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Ошибка организации");
      });
    return () => { active = false; };
  }, [session?.user.id, revision]);

  useEffect(() => {
    if (workspaceUnitId && units.some((unit) => unit.id === workspaceUnitId)) {
      setUnitId(workspaceUnitId);
    }
  }, [workspaceUnitId, units]);

  useEffect(() => {
    if (!session || !enterpriseId) {
      setUnits([]); setSkills([]); setScales([]); setOrders([]);
      setRequirements([]); setSelectedOrderId("");
      return;
    }
    let active = true;
    async function load() {
      try {
        const [org, catalog, versions, rules, workOrders] = await Promise.all([
          api<Unit[]>(`/api/v1/org/enterprises/${enterpriseId}/units`),
          api<Skill[]>(`/api/v1/competence/enterprises/${enterpriseId}/skills`),
          api<Scale[]>(`/api/v1/competence/enterprises/${enterpriseId}/scales`),
          api<Requirement[]>(`/api/v1/credentials/enterprises/${enterpriseId}/requirements`),
          api<Work[]>(`${base}/enterprises/${enterpriseId}/orders`),
        ]);
        if (!active) return;
        setUnits(org); setSkills(catalog); setScales(versions);
        setRequirements(rules); setOrders(workOrders);
        setUnitId((old) => org.some((u) => u.id === old) ? old : org[0]?.id ?? "");
        setSelectedOrderId((old) =>
          workOrders.some((w) => w.id === old) ? old : workOrders[0]?.id ?? "");
      } catch (cause) {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "Ошибка загрузки заявок");
        setOrders([]);
      }
    }
    void load();
    return () => { active = false; };
  }, [session?.user.id, enterpriseId, revision]);

  useEffect(() => {
    if (!selectedOrderId || !session || selectedOrder?.status !== "open") {
      setCandidates([]); return;
    }
    let active = true;
    api<Candidate[]>(`${base}/orders/${selectedOrderId}/candidates`)
      .then((rows) => { if (active) setCandidates(rows); })
      .catch((cause: unknown) => {
        if (active) {
          setCandidates([]);
          setError(cause instanceof Error ? cause.message : "Ошибка подбора");
        }
      });
    return () => { active = false; };
  }, [selectedOrderId, selectedOrder?.status, session?.user.id, revision]);

  async function change(action: () => Promise<unknown>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      await action();
      setNotice(success);
      setRevision((x) => x + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Ошибка записи");
    } finally { setBusy(false); }
  }

  function editRequirement(index: number, field: keyof DraftRequirement, value: string) {
    setRequired((old) => old.map((item, i) => {
      if (i !== index) return item;
      if (field === "skill_id") {
        const skill = skills.find((row) => row.id === value);
        const scale = scales.find((row) => row.id === skill?.scale_id);
        return { skill_id: value, min_level_id: scale?.levels[0]?.id ?? "" };
      }
      return { ...item, min_level_id: value };
    }));
  }

  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId || !unitId) return;
    void change(async () => {
      const output = await api<Work>(
        `${base}/enterprises/${enterpriseId}/orders`,
        { method: "POST", body: JSON.stringify({
          code, title, description: description || null,
          unit_id: unitId, activity_code: activityCode,
          starts_at: new Date(start).toISOString(),
          ends_at: new Date(end).toISOString(),
          required_skills: required, priority,
        }) },
        session.csrf_token,
      );
      setSelectedOrderId(output.id);
      setCode(""); setTitle(""); setDescription("");
    }, "Наряд создан с зафиксированными требованиями. Можно проверить кандидатов.");
  }

  function action(orderId: string, task: "assign" | "start" | "complete" | "cancel", person?: string) {
    if (!session) return;
    const method = person ? { method: "POST", body: JSON.stringify({ person_id: person }) }
      : { method: "POST" };
    if (task === "cancel" && !window.confirm("Отменить наряд и освободить время?")) return;
    void change(
      () => api<Work>(`${base}/orders/${orderId}/${task}`, method, session.csrf_token),
      task === "assign" ? "Исполнитель назначен, время забронировано." :
        task === "start" ? "Повторные проверки пройдены: работа начата." :
          task === "complete" ? "Наряд закрыт как выполненный." :
            "Наряд отменён, бронь освобождена.",
    );
  }

  return (
    <section className="wm-panel" id="work" aria-labelledby="wm-title">
      <div className="section-heading">
        <div>
          <div className="eyebrow">WORK MANAGEMENT · EXPLAINABLE MATCHING</div>
          <h2 id="wm-title">Технические задания и назначение специалистов</h2>
        </div>
        <span className="wm-badge">Три обязательных проверки</span>
      </div>
      <p className="wm-lead">
        Подбор по подтверждённым компетенциям, действующим обязательным допускам
        и календарю. Назначение без всех трёх проверок сервером запрещено.
      </p>
      {!session && <p className="wm-empty">Авторизуйтесь для просмотра нарядов.</p>}
      {session && (
        <>
          <label className="wm-enterprise">Предприятие
            <select value={enterpriseId} onChange={(event) => setEnterpriseId(event.target.value)}>
              {enterprises.length === 0 && <option value="">Нет доступных предприятий</option>}
              {enterprises.map((row) => (
                <option key={row.id} value={row.id}>{row.name}</option>
              ))}
            </select>
          </label>
          <div className="wm-stats">
            <article><strong>{orders.length}</strong><small>Нарядов</small></article>
            <article><strong>{orders.filter((w) => w.status === "open").length}</strong>
              <small>Открыто</small></article>
            <article><strong>{orders.filter((w) => w.status === "assigned").length}</strong>
              <small>Назначено</small></article>
            <article><strong>{orders.filter((w) => w.status === "in_progress").length}</strong>
              <small>Выполняется</small></article>
          </div>

          {dispatcher && enterpriseId && (
            <details className="wm-editor">
              <summary>Создать технический наряд</summary>
              <form className="wm-form" onSubmit={create}>
                <label>Код заявки
                  <input value={code} required maxLength={64} pattern="[A-Za-z0-9_.-]+"
                    onChange={(e) => setCode(e.target.value)} placeholder="wo-2026-001" />
                </label>
                <label>Наименование задания
                  <input value={title} required maxLength={200}
                    onChange={(e) => setTitle(e.target.value)} />
                </label>
                <label>Подразделение
                  <select required value={unitId} onChange={(e) => {
                    setUnitId(e.target.value);
                    setWorkspaceUnitId(e.target.value);
                  }}>
                    <option value="">Выберите подразделение</option>
                    {units.map((unit) => (
                      <option key={unit.id} value={unit.id}>{unit.name}</option>
                    ))}
                  </select>
                </label>
                <label>Код вида работ (из политики допусков)
                  <input list="wm-activities" value={activityCode} required
                    pattern="[A-Za-z0-9_.-]+" maxLength={64}
                    onChange={(e) => setActivityCode(e.target.value)} />
                  <datalist id="wm-activities">
                    {activityCodes.map((codeItem) => <option key={codeItem} value={codeItem} />)}
                  </datalist>
                </label>
                <label>Приоритет
                  <select value={priority}
                    onChange={(e) => setPriority(e.target.value as Work["priority"])}>
                    <option value="routine">Плановый</option>
                    <option value="normal">Обычный</option>
                    <option value="urgent">Срочный</option>
                    <option value="critical">Критический</option>
                  </select>
                </label>
                <label>Начало по местному времени браузера
                  <input type="datetime-local" required value={start}
                    onChange={(e) => setStart(e.target.value)} />
                </label>
                <label>Окончание по местному времени браузера
                  <input type="datetime-local" required value={end}
                    onChange={(e) => setEnd(e.target.value)} />
                </label>
                <label className="wm-wide">Описание
                  <textarea maxLength={3000} value={description}
                    onChange={(e) => setDescription(e.target.value)} />
                </label>
                <div className="wm-wide wm-requirements">
                  <h4>Обязательные компетенции и минимальные уровни</h4>
                  {required.map((item, index) => {
                    const skill = skills.find((s) => s.id === item.skill_id);
                    const levels = scales.find((scale) => scale.id === skill?.scale_id)?.levels ?? [];
                    return (
                      <div className="wm-requirement-row" key={index}>
                        <label>Компетенция
                          <select required value={item.skill_id}
                            onChange={(e) => editRequirement(index, "skill_id", e.target.value)}>
                            <option value="">Выберите навык</option>
                            {activeSkills.map((s) => (
                              <option key={s.id} value={s.id}>{s.name}</option>
                            ))}
                          </select>
                        </label>
                        <label>Минимальный подтверждённый уровень
                          <select required value={item.min_level_id}
                            onChange={(e) => editRequirement(index, "min_level_id", e.target.value)}>
                            <option value="">Выберите уровень</option>
                            {levels.map((level) => (
                              <option key={level.id} value={level.id}>
                                {level.ordinal} — {level.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <button type="button" className="wm-button secondary"
                          disabled={required.length <= 1}
                          onClick={() => setRequired((old) => old.filter((_, i) => i !== index))}>
                          Убрать
                        </button>
                      </div>
                    );
                  })}
                  <button type="button" className="wm-button secondary" disabled={required.length >= 20}
                    onClick={() => setRequired((old) => [
                      ...old, { skill_id: "", min_level_id: "" },
                    ])}>
                    + Требование к навыку
                  </button>
                </div>
                <p className="wm-hint wm-wide">
                  Состав требований и временной интервал фиксируются при создании.
                  Работа без политики допусков не может получить исполнителя.
                </p>
                <button className="wm-button" type="submit" disabled={busy}>
                  Создать наряд
                </button>
              </form>
            </details>
          )}

          <div className="wm-layout">
            <div>
              <h3>Журнал нарядов</h3>
              <div className="wm-orders">
                {orders.map((order) => (
                  <button type="button" key={order.id}
                    className={`wm-order ${selectedOrderId === order.id ? "selected" : ""}`}
                    onClick={() => setSelectedOrderId(order.id)}>
                    <span><strong>{order.code} · {order.title}</strong>
                      <small>{order.priority.toUpperCase()} · {" "}
                        {unitName.get(order.unit_id) ?? "Подразделение"} ·
                        {" "}{dateLabel(order.starts_at)}</small></span>
                    <span className={`wm-state ${order.status}`}>{statuses[order.status]}</span>
                  </button>
                ))}
                {orders.length === 0 &&
                  <p className="wm-empty">Наряды пока не зарегистрированы или недоступны.</p>}
              </div>
            </div>
            <div>
              <h3>Карточка задания</h3>
              {selectedOrder ? (
                <article className="wm-detail">
                  <div className="wm-detail-head">
                    <strong>{selectedOrder.title}</strong>
                    <span className={`wm-state ${selectedOrder.status}`}>
                      {statuses[selectedOrder.status]}
                    </span>
                  </div>
                  <p>Код: {selectedOrder.code} · Вид работ: {selectedOrder.activity_code}</p>
                  <p>{dateLabel(selectedOrder.starts_at)} — {dateLabel(selectedOrder.ends_at)}</p>
                  <p>{selectedOrder.description ?? "Без дополнительного описания"}</p>
                  <h4>Обязательные компетенции</h4>
                  {selectedOrder.required_skills.map((rule) => (
                    <p className="wm-criterion" key={rule.id}>
                      {skillName.get(rule.skill_id) ?? rule.skill_name}:
                      {" "}уровень ≥ {rule.min_ordinal}
                    </p>
                  ))}
                  {selectedOrder.assignment && <p className="wm-assignee">
                    Ответственный: {selectedOrder.assignment.person_id} ·
                    бронь {selectedOrder.assignment.reservation_id.slice(0, 8)}
                  </p>}
                  {dispatcher && (
                    <div className="wm-actions">
                      {selectedOrder.status === "assigned" && (
                        <button type="button" className="wm-button" disabled={busy}
                          onClick={() => action(selectedOrder.id, "start")}>Начать с повторной проверкой</button>
                      )}
                      {selectedOrder.status === "in_progress" && (
                        <button type="button" className="wm-button" disabled={busy}
                          onClick={() => action(selectedOrder.id, "complete")}>Отметить выполненным</button>
                      )}
                      {["open", "assigned", "in_progress", "on_hold"].includes(selectedOrder.status) && (
                        <button type="button" className="wm-button danger" disabled={busy}
                          onClick={() => action(selectedOrder.id, "cancel")}>Отменить наряд</button>
                      )}
                    </div>
                  )}
                </article>
              ) : <p className="wm-empty">Выберите наряд в журнале.</p>}
            </div>
          </div>

          {selectedOrder && (
            <WorkEquipmentPermitPanel
              key={"equipment-" + selectedOrder.id}
              work={{
                id: selectedOrder.id,
                enterprise_id: selectedOrder.enterprise_id,
                status: selectedOrder.status,
              }}
              csrfToken={session.csrf_token}
              actorRole={session.user.role}
              actorId={session.user.id}
              canDispatch={dispatcher}
              onChanged={() => setRevision((old) => old + 1)}
            />
          )}

          {selectedOrder && (
            <WorkExecutionPanel
              key={selectedOrder.id}
              order={selectedOrder}
              csrfToken={session.csrf_token}
              canDispatch={dispatcher}
              onChanged={() => setRevision((old) => old + 1)}
            />
          )}

          {selectedOrder?.status === "open" && (
            <div className="wm-matching">
              <h3>Подбор специалистов · причины допуска и блокировки</h3>
              <p className="wm-hint">
                Кандидаты выводятся из подразделения задания. Принятие решения и
                бронирование происходит повторно внутри серверной транзакции.
              </p>
              <div className="wm-candidates">
                {candidates.map((candidate) => (
                  <article key={candidate.person_id} className="wm-candidate">
                    <div className="wm-detail-head">
                      <strong>{candidate.full_name} <small>{candidate.employee_code}</small></strong>
                      <span className={`wm-state ${candidate.eligible ? "eligible" : "blocked"}`}>
                        {candidate.eligible ? "Все требования выполнены" : "Есть блокировки"}
                      </span>
                    </div>
                    {candidate.eligible ? (
                      <p className="wm-hint">
                        Подтверждено навыков: {candidate.verified_skills.length};
                        документов: {candidate.verified_credentials.length}.
                      </p>
                    ) : (
                      <div className="wm-blockers">
                        {candidate.blockers.map((blocker, index) => (
                          <p key={index}>
                            <b>{sources[blocker.source] ?? blocker.source}:</b>{" "}
                            {readableCodes[blocker.code] ?? blocker.message}
                          </p>
                        ))}
                      </div>
                    )}
                    {dispatcher && candidate.eligible && (
                      <button type="button" className="wm-button"
                        disabled={busy} onClick={() => action(
                          selectedOrder.id, "assign", candidate.person_id,
                        )}>Назначить и забронировать</button>
                    )}
                  </article>
                ))}
                {candidates.length === 0 &&
                  <p className="wm-empty">Для этого задания кандидатов в подразделении не найдено.</p>}
              </div>
            </div>
          )}
        </>
      )}
      {error && <p className="wm-error" role="alert">{error}</p>}
      {notice && <p className="wm-success" role="status">{notice}</p>}
      <p className="wm-hint">
        Отображаемые документы — учётные сведения; проверка не заменяет
        физическое подтверждение полномочий, местные правила охраны труда
        и допуск на конкретное оборудование.
      </p>
    </section>
  );
}
