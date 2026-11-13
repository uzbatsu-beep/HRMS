import { useEffect, useState } from "react";

type Priority = "routine" | "normal" | "urgent" | "critical";
type Status = "open" | "assigned" | "in_progress" | "on_hold" | "completed" | "cancelled";
type Crew = {
  id: string; person_id: string; role: string;
  reservation_id: string; removed_at: string | null;
};
type Order = {
  id: string; status: Status; priority: Priority;
  assignment: { person_id: string } | null;
  crew: Crew[]; hold_reason: string | null; last_safety_check_at: string | null;
};
type Candidate = {
  person_id: string; full_name: string; employee_code: string;
  eligible: boolean; blockers: { source: string; code: string; message: string }[];
};
type MemberSafety = {
  role: string; person_id: string; reservation_valid: boolean;
  candidate: Candidate;
};
type SafetyResult = {
  passed: boolean; status: string; checked_at: string; members: MemberSafety[];
  equipment_blockers: { code: string; message: string }[];
};

const API = "/api/v1/work";
const priorityNames: Record<Priority, string> = {
  routine: "Плановый", normal: "Обычный", urgent: "Срочный", critical: "Критический",
};
const roleNames: Record<string, string> = {
  lead: "Ответственный", specialist: "Специалист",
  assistant: "Помощник", observer: "Наблюдатель",
};
const blockerText: Record<string, string> = {
  REVOKED_CREDENTIAL: "Допуск отозван",
  EXPIRED_CREDENTIAL: "Срок действия допуска истёк",
  MISSING_CREDENTIAL: "Нет обязательного действующего допуска",
  UNVERIFIED_CREDENTIAL: "Документ не подтверждён",
  MISSING_VERIFIED_SKILL: "Нет подтверждённой компетенции",
  INSUFFICIENT_SKILL_LEVEL: "Уровень компетенции ниже минимального",
  NO_SHIFT: "В заданном интервале нет рабочей смены",
  ABSENT: "Участник отсутствует в указанное время",
  BOOKED: "Сотрудник забронирован для другой работы",
  CALENDAR_CLOSED: "Нерабочий день предприятия",
  RESERVATION_INVALID: "Бронирование работы более недействительно",
  EQUIPMENT_MISSING: "Оборудование отсутствует",
  EQUIPMENT_OUT_OF_SERVICE: "Оборудование выведено из эксплуатации",
  WORK_PERMIT_NOT_APPROVED: "Нет согласованного разрешения на работы",
  WORK_PERMIT_INCOMPLETE: "Недостаточно подтверждений по месту работ",
};

const blockerSource: Record<string, string> = {
  person: "Сотрудник", organization: "Подразделение",
  skill: "Навык", credential: "Допуск", calendar: "График",
};

async function api<T>(path: string, init: RequestInit = {}, csrf?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(path, { ...init, credentials: "same-origin", headers });
  if (!response.ok) {
    let errorText = "";
    try {
      const json = (await response.json()) as { detail?: unknown };
      errorText = typeof json.detail === "string"
        ? json.detail
        : json.detail ? JSON.stringify(json.detail) : "";
    } catch { /* Keep the HTTP status for unexpected response bodies. */ }
    throw new Error(`HTTP ${response.status}${errorText ? " — " + errorText : ""}`);
  }
  return await response.json() as T;
}

export default function WorkExecutionPanel({
  order, csrfToken, canDispatch, onChanged,
}: {
  order: Order; csrfToken: string | undefined;
  canDispatch: boolean; onChanged: () => void;
}) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [checked, setChecked] = useState<SafetyResult | null>(null);
  const [priority, setPriority] = useState<Priority>(order.priority);
  const [priorityReason, setPriorityReason] = useState("");
  const [selectedPerson, setSelectedPerson] = useState("");
  const [role, setRole] = useState("specialist");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const assigned = order.status === "assigned";
  const running = order.status === "in_progress";
  const onHold = order.status === "on_hold";

  useEffect(() => {
    // Preserve the just-returned safety report when the parent reloads after
    // an on_hold transition. The panel is keyed by order ID, so selecting a
    // different work order already resets this state.
    setPriority(order.priority);
    setCandidates([]); setSelectedPerson("");
    if (!assigned) return;
    let active = true;
    api<Candidate[]>(`${API}/orders/${order.id}/candidates`)
      .then((rows) => {
        if (active) {
          setCandidates(rows);
          setSelectedPerson(rows.find((row) => row.eligible)?.person_id ?? "");
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Ошибка подбора");
      });
    return () => { active = false; };
  }, [order.id, order.status, order.priority, order.crew.length,
    order.assignment?.person_id]);

  async function action(path: string, payload?: unknown, message?: string) {
    if (!canDispatch || !csrfToken) return;
    setBusy(true); setError(""); setSuccess("");
    try {
      await api<unknown>(`${API}/orders/${order.id}/${path}`, {
        method: "POST", ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
      }, csrfToken);
      if (message) setSuccess(message);
      onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Операция отклонена");
    } finally { setBusy(false); }
  }

  function readSafety() {
    setBusy(true); setError(""); setChecked(null);
    api<SafetyResult>(`${API}/orders/${order.id}/safety`)
      .then(setChecked)
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : "Проверка недоступна"))
      .finally(() => setBusy(false));
  }

  async function revalidate() {
    if (!csrfToken || !canDispatch) return;
    setBusy(true); setError(""); setChecked(null);
    try {
      const result = await api<SafetyResult>(
        `${API}/orders/${order.id}/revalidate`,
        { method: "POST" }, csrfToken,
      );
      setChecked(result);
      onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Проверка недоступна");
    } finally { setBusy(false); }
  }

  return (
    <div className="wm-execution">
      <h3>Бригада, приоритет и контроль безопасности</h3>
      <p className="wm-hint">
        Каждый член бригады проходит те же обязательные проверки, что и ответственный.
        Проверка после начала работы запускается вручную; аппаратной блокировки нет.
      </p>
      <div className="wm-execution-toolbar">
        <span className={`wm-priority ${order.priority}`}>
          Приоритет: {priorityNames[order.priority]}
        </span>
        {order.last_safety_check_at && (
          <small>Проверено: {new Date(order.last_safety_check_at).toLocaleString("ru-RU")}</small>
        )}
      </div>

      {canDispatch && ["open", "assigned"].includes(order.status) && (
        <details className="wm-execution-detail">
          <summary>Изменить приоритет</summary>
          <div className="wm-crew-editor">
            <label>Новый приоритет
              <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
                {Object.entries(priorityNames).map(([key, value]) =>
                  <option key={key} value={key}>{value}</option>)}
              </select>
            </label>
            <label>Обоснование изменения
              <input value={priorityReason} minLength={10} maxLength={400}
                onChange={(e) => setPriorityReason(e.target.value)} />
            </label>
            <button type="button" className="wm-button" disabled={busy ||
              priority === order.priority || priorityReason.trim().length < 10}
              onClick={() => void action("priority", {
                priority, reason: priorityReason,
              }, "Приоритет изменён")}>
              Применить
            </button>
          </div>
        </details>
      )}
      {order.assignment && (
        <div className="wm-crew-roster">
          <div className="wm-roster-line">
            <strong>Ответственный</strong>
            <span>{order.assignment.person_id}</span>
          </div>
          {order.crew.map((member) => (
            <div className="wm-roster-line" key={member.id}>
              <strong>{roleNames[member.role] ?? member.role}
                {member.removed_at ? " · удалён" : ""}</strong>
              <span>{member.person_id}</span>
              {assigned && canDispatch && !member.removed_at && (
                <button className="wm-button secondary" type="button" disabled={busy ||
                  note.trim().length < 10}
                  onClick={() => void action(`crew/${member.id}/remove`, {
                    reason: note,
                  }, "Участник исключён; бронь освобождена")}>
                  Исключить
                </button>
              )}
            </div>
          ))}
          {order.crew.length === 0 && (
            <p className="wm-empty">Дополнительные специалисты не назначены.</p>
          )}
        </div>
      )}
      {assigned && canDispatch && (
        <div className="wm-execution-detail">
          <h4>Сформировать бригаду / заменить ответственного</h4>
          <div className="wm-crew-editor">
            <label>Свободный кандидат
              <select value={selectedPerson} onChange={(e) => setSelectedPerson(e.target.value)}>
                <option value="">Выберите кандидата</option>
                {candidates.filter((candidate) => candidate.eligible).map((candidate) => (
                  <option key={candidate.person_id} value={candidate.person_id}>
                    {candidate.full_name} · {candidate.employee_code}
                  </option>
                ))}
              </select>
            </label>
            <label>Роль
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="specialist">Специалист</option>
                <option value="assistant">Помощник</option>
                <option value="observer">Наблюдатель</option>
              </select>
            </label>
            <label className="wm-wide">Причина замены / исключения (не менее 10 символов)
              <input value={note} maxLength={400}
                onChange={(e) => setNote(e.target.value)} />
            </label>
            <button type="button" className="wm-button" disabled={busy || !selectedPerson}
              onClick={() => void action("crew", {
                person_id: selectedPerson, role,
              }, "Участник добавлен и забронирован")}>
              Добавить в бригаду
            </button>
            <button type="button" className="wm-button secondary" disabled={busy ||
              !selectedPerson || note.trim().length < 10}
              onClick={() => void action("replace-lead", {
                person_id: selectedPerson, reason: note,
              }, "Ответственный заменён, история и старые брони сохранены")}>
              Заменить ответственного
            </button>
          </div>
          <p className="wm-hint">
            Уже забронированные и не прошедшие проверки специалисты не могут быть
            назначены. После начала работ состав бригады блокируется.
          </p>
        </div>
      )}

      {["assigned", "in_progress", "on_hold"].includes(order.status) && (
        <div className="wm-execution-check">
          <h4>Явная проверка действительности состава бригады</h4>
          <div className="wm-actions">
            <button type="button" className="wm-button secondary" disabled={busy}
              onClick={readSafety}>Проверить (без изменения статуса)</button>
            {canDispatch && (
              <button type="button" className="wm-button" disabled={busy}
                onClick={() => void revalidate()}>
                Зафиксировать повторную проверку
              </button>
            )}
          </div>
          {checked && (
            <div role="status" className={`wm-result ${checked.passed ? "allowed" : "blocked"}`}>
              <strong>{checked.passed ? "Все назначенные участники прошли проверки" :
                "Обнаружены блокирующие условия"}</strong>
              <p>Состояние: {checked.status} · {new Date(checked.checked_at).toLocaleString("ru-RU")}</p>
              {checked.equipment_blockers?.map((block, index) => (
                <p key={index} className="wm-warning">
                  Оборудование: {blockerText[block.code] ?? block.message}
                </p>
              ))}
              {checked.members.map((member) => (
                <div key={member.person_id} className="wm-member-check">
                  <b>{roleNames[member.role] ?? member.role} ·
                    {" "}{member.candidate.full_name}</b>
                  {member.candidate.eligible ? (
                    <span> · проверен</span>
                  ) : member.candidate.blockers.map((block, index) => (
                    <p key={index}>{blockerSource[block.source] ?? block.source}:{" "}
                      {blockerText[block.code] ?? block.message}</p>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {(running || onHold) && canDispatch && (
        <div className="wm-execution-detail">
          <h4>{onHold ? "Работа требует разрешения ответственного лица" :
            "Ручная приостановка выполнения"}</h4>
          {order.hold_reason && <p className="wm-warning">{order.hold_reason}</p>}
          <label>Причина и решение ответственного (не менее 10 символов)
            <textarea value={note} minLength={10} maxLength={400}
              onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="wm-actions">
            {running && (
              <button type="button" className="wm-button danger" disabled={busy ||
                note.trim().length < 10}
                onClick={() => void action("hold", { reason: note },
                  "Статус изменён на «На удержании»")}>
                Приостановить в HRMS
              </button>
            )}
            {onHold && (
              <button type="button" className="wm-button" disabled={busy ||
                note.trim().length < 10}
                onClick={() => void action("resume", { reason: note },
                  "Все требования проверены; выполнение возобновлено в HRMS")}>
                Проверить и возобновить
              </button>
            )}
          </div>
          <p className="wm-hint">
            «На удержании» запрещает закрытие наряда в системе, но не
            управляет оборудованием. Фактическая остановка и допуск выполняются
            по процедурам предприятия.
          </p>
        </div>
      )}
      {error && <p role="alert" className="wm-error">{error}</p>}
      {success && <p role="status" className="wm-success">{success}</p>}
    </div>
  );
}
