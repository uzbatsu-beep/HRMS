import { FormEvent, useEffect, useState } from "react";
import { useWorkspace } from "./WorkspaceContext";

type Session = {
  user: { id: string; username: string; role: "admin" | "manager" | "viewer" };
  csrf_token: string;
};
type Enterprise = { id: string; name: string };
type Person = {
  id: string; resource_id: string; employee_code: string;
  first_name: string; last_name: string;
};
type Link = { person_id: string; enterprise_id: string; enterprise_name: string };
type Shift = {
  id: string; weekday: number; local_start: string; local_end: string;
  time_zone: string; valid_from: string; valid_to: string | null;
  disabled_at: string | null;
};
type Absence = {
  id: string; starts_at: string; ends_at: string;
  category: string | null; note: string | null; cancelled_at: string | null;
};
type Reservation = {
  id: string; starts_at: string; ends_at: string;
  external_reference: string | null; cancelled_at: string | null;
};
type Closure = {
  id: string; local_date: string; label: string; time_zone: string;
};
type Calendar = {
  resource_id: string; shift_rules: Shift[];
  absences: Absence[]; reservations: Reservation[]; closures: Closure[];
};
type Availability = {
  available: boolean; starts_at: string; ends_at: string;
  blockers: { code: string; message: string }[];
};
type Load = {
  reserved_minutes: number; absence_minutes: number; active_reservations: number;
};

const root = "/api/v1/availability";
const weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const utcNow = () => new Date().toISOString().slice(0, 16);
const utcLater = (hours: number) => new Date(
  Date.now() + hours * 3600 * 1000,
).toISOString().slice(0, 16);
const utc = (value: string) => `${value}:00Z`;
const calendarDay = () => new Date().toISOString().slice(0, 10);
const blockerNames: Record<string, string> = {
  NO_SHIFT: "Нет смены, полностью покрывающей интервал.",
  AMBIGUOUS_SHIFT_TIME: "Время смены неоднозначно при переходе часового пояса.",
  CALENDAR_CLOSED: "Нерабочий день предприятия.",
  ABSENT: "Отсутствие специалиста пересекает интервал.",
  BOOKED: "Интервал уже забронирован.",
  NO_ASSIGNMENT: "Нет действующего основного назначения.",
  ASSIGNMENT_CHANGED: "Изменилось основное подразделение в течение интервала.",
  INACTIVE_PERSON: "Специалист или трудовой ресурс неактивен.",
};

async function request<T>(path: string, init: RequestInit = {}, csrf?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(path, { ...init, credentials: "same-origin", headers });
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* Use HTTP code when backend returns no JSON. */ }
    throw new Error(`HTTP ${response.status}${detail ? " — " + detail : ""}`);
  }
  return await response.json() as T;
}

export default function AvailabilityPanel() {
  const [session, setSession] = useState<Session | null>(null);
  const [authRevision, setAuthRevision] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [companies, setCompanies] = useState<Enterprise[]>([]);
  const { enterpriseId, setEnterpriseId, personId, setPersonId } = useWorkspace();
  const [ownLink, setOwnLink] = useState<Link | null>(null);
  const [people, setPeople] = useState<Person[]>([]);

  const [calendar, setCalendar] = useState<Calendar | null>(null);
  const [load, setLoad] = useState<Load | null>(null);
  const [checkResult, setCheckResult] = useState<Availability | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const [dateFrom, setDateFrom] = useState(utcNow());
  const [dateTo, setDateTo] = useState(utcLater(12));
  const [checkFrom, setCheckFrom] = useState(utcLater(1));
  const [checkTo, setCheckTo] = useState(utcLater(2));
  const [shiftDay, setShiftDay] = useState(0);
  const [shiftStart, setShiftStart] = useState("08:00");
  const [shiftEnd, setShiftEnd] = useState("17:00");
  const [shiftZone, setShiftZone] = useState("UTC");
  const [shiftValidFrom, setShiftValidFrom] = useState(calendarDay());
  const [shiftValidTo, setShiftValidTo] = useState("");
  const [absenceCategory, setAbsenceCategory] = useState("leave");
  const [absenceNote, setAbsenceNote] = useState("");
  const [absenceStart, setAbsenceStart] = useState(utcLater(24));
  const [absenceEnd, setAbsenceEnd] = useState(utcLater(32));
  const [reserveFrom, setReserveFrom] = useState(utcLater(1));
  const [reserveTo, setReserveTo] = useState(utcLater(2));
  const [reservationRef, setReservationRef] = useState("");
  const [closureDate, setClosureDate] = useState(calendarDay());
  const [closureZone, setClosureZone] = useState("UTC");
  const [closureLabel, setClosureLabel] = useState("");

  const admin = session?.user.role === "admin";
  const selected = people.find((p) => p.id === personId);
  const resourceId = calendar?.resource_id ?? selected?.resource_id ?? "";

  useEffect(() => {
    const changed = () => {
      setSession(null);
      setAuthRevision((old) => old + 1);
    };
    const update = () => setRefresh((old) => old + 1);
    window.addEventListener("twm-auth-changed", changed);
    window.addEventListener("twm-org-changed", update);
    window.addEventListener("twm-personnel-changed", update);
    return () => {
      window.removeEventListener("twm-auth-changed", changed);
      window.removeEventListener("twm-org-changed", update);
      window.removeEventListener("twm-personnel-changed", update);
    };
  }, []);

  useEffect(() => {
    let active = true;
    request<Session>("/api/v1/auth/me")
      .then((value) => { if (active) setSession(value); })
      .catch(() => { if (active) setSession(null); });
    return () => { active = false; };
  }, [authRevision]);

  useEffect(() => {
    if (!session) {
      setCompanies([]); setOwnLink(null);
      setPeople([]); setCalendar(null);
      return;
    }
    let active = true;
    Promise.all([
      request<Enterprise[]>("/api/v1/org/enterprises"),
      request<Link | null>("/api/v1/competence/me/link"),
    ]).then(([entries, link]) => {
      if (!active) return;
      const list = [...entries];
      if (link && !list.some((entry) => entry.id === link.enterprise_id)) {
        list.push({ id: link.enterprise_id, name: link.enterprise_name });
      }
      setCompanies(list); setOwnLink(link);
      setEnterpriseId((old) => list.some((entry) => entry.id === old)
        ? old : list[0]?.id ?? "");
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Ошибка загрузки");
    });
    return () => { active = false; };
  }, [session?.user.id, refresh]);

  useEffect(() => {
    if (!enterpriseId || !session) { setPeople([]); return; }
    let active = true;
    request<Person[]>(
      `/api/v1/personnel/enterprises/${enterpriseId}/persons?limit=100`,
    ).catch(() => [] as Person[])
      .then((rows) => {
        if (!active) return;
        setPeople(rows);
        const visible = rows.map((row) => row.id);
        if (ownLink?.enterprise_id === enterpriseId) visible.push(ownLink.person_id);
        setPersonId((old) => visible.includes(old) ? old : visible[0] ?? "");
      });
    return () => { active = false; };
  }, [enterpriseId, session?.user.id, ownLink?.person_id, refresh]);

  useEffect(() => {
    setCheckResult(null);
    if (!personId || !session || !dateFrom || !dateTo) {
      setCalendar(null); setLoad(null); return;
    }
    let active = true;
    const params = new URLSearchParams({ start: utc(dateFrom), end: utc(dateTo) });
    Promise.all([
      request<Calendar>(`${root}/persons/${personId}/calendar?${params}`),
      request<Load>(`${root}/persons/${personId}/load?${params}`),
    ]).then(([data, summary]) => {
      if (active) { setCalendar(data); setLoad(summary); }
    }).catch((cause: unknown) => {
      if (active) {
        setCalendar(null); setLoad(null);
        setError(cause instanceof Error ? cause.message : "Календарь недоступен");
      }
    });
    return () => { active = false; };
  }, [personId, session?.user.id, refresh, dateFrom, dateTo]);

  async function mutate(action: () => Promise<void>, message: string) {
    setBusy(true); setError(""); setNotice(""); setCheckResult(null);
    try {
      await action();
      setNotice(message);
      setRefresh((old) => old + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Ошибка записи");
    } finally { setBusy(false); }
  }

  function submitShift(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !resourceId) return;
    void mutate(() => request(
      `${root}/resources/${resourceId}/shifts`,
      { method: "POST", body: JSON.stringify({
        weekday: shiftDay, local_start: shiftStart, local_end: shiftEnd,
        time_zone: shiftZone, valid_from: shiftValidFrom,
        valid_to: shiftValidTo || null,
      }) }, session.csrf_token,
    ), "Смена добавлена в график.");
  }

  function submitClosure(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId) return;
    void mutate(async () => {
      await request(
        `${root}/enterprises/${enterpriseId}/closures`,
        { method: "POST", body: JSON.stringify({
          local_date: closureDate, time_zone: closureZone, label: closureLabel,
        }) }, session.csrf_token,
      );
      setClosureLabel("");
    }, "Нерабочий день добавлен.");
  }

  function submitAbsence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !resourceId) return;
    void mutate(() => request(
      `${root}/resources/${resourceId}/absences`,
      { method: "POST", body: JSON.stringify({
        starts_at: utc(absenceStart), ends_at: utc(absenceEnd),
        category: absenceCategory, note: absenceNote || null,
      }) }, session.csrf_token,
    ), "Период отсутствия зарегистрирован.");
  }

  function submitReservation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !resourceId) return;
    void mutate(() => request(
      `${root}/resources/${resourceId}/reservations`,
      { method: "POST", body: JSON.stringify({
        starts_at: utc(reserveFrom), ends_at: utc(reserveTo),
        external_reference: reservationRef || null,
      }) }, session.csrf_token,
    ), "Время специалиста забронировано.");
  }

  function cancel(kind: "absences" | "reservations", id: string) {
    if (!session || !window.confirm("Отменить запись? История сохранится.")) return;
    void mutate(() => request(
      `${root}/${kind}/${id}/cancel`,
      { method: "POST" }, session.csrf_token,
    ), "Запись отменена, история сохранена.");
  }

  function disable(id: string) {
    if (!session || !window.confirm("Отключить правило смены?")) return;
    void mutate(() => request(
      `${root}/shifts/${id}/disable`,
      { method: "POST" }, session.csrf_token,
    ), "Правило смены отключено.");
  }

  function checkAvailability(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!personId) return;
    setBusy(true); setError(""); setCheckResult(null);
    const query = new URLSearchParams({ start: utc(checkFrom), end: utc(checkTo) });
    request<Availability>(`${root}/persons/${personId}/check?${query}`)
      .then(setCheckResult)
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : "Ошибка проверки"))
      .finally(() => setBusy(false));
  }

  return (
    <section className="av-panel" id="availability" aria-labelledby="av-title">
      <div className="section-heading">
        <div>
          <div className="eyebrow">AVAILABILITY · SCHEDULING</div>
          <h2 id="av-title">Смены, доступность и загрузка</h2>
        </div>
        <span className="av-badge">UTC + IANA Time Zones</span>
      </div>
      <p className="av-lead">
        Плановые смены, нерабочие дни, отсутствия и бронирование ресурсов.
        Пересекающиеся интервалы блокируются на сервере.
      </p>
      {!session && <p className="av-empty">Для просмотра календаря войдите в систему.</p>}
      {session && (
        <>
          <div className="av-filters">
            <label>Предприятие
              <select value={enterpriseId} onChange={(e) => setEnterpriseId(e.target.value)}>
                {companies.length === 0 && <option value="">Нет доступных предприятий</option>}
                {companies.map((row) => (
                  <option key={row.id} value={row.id}>{row.name}</option>
                ))}
              </select>
            </label>
            <label>Сотрудник
              <select value={personId} onChange={(e) => setPersonId(e.target.value)}>
                <option value="">Выберите</option>
                {people.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.last_name} {person.first_name} · {person.employee_code}
                  </option>
                ))}
                {ownLink && ownLink.enterprise_id === enterpriseId &&
                  !people.some((row) => row.id === ownLink.person_id) && (
                    <option value={ownLink.person_id}>Мой график</option>
                  )}
              </select>
            </label>
            <label>Начало отчётного окна (UTC)
              <input type="datetime-local" required value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)} />
            </label>
            <label>Конец отчётного окна (UTC)
              <input type="datetime-local" required value={dateTo}
                onChange={(e) => setDateTo(e.target.value)} />
            </label>
          </div>
          <p className="av-hint">
            Все поля календарных интервалов ниже вводятся в <strong>UTC</strong>.
            Даты и время самой повторяющейся смены задаются в выбранном часовом поясе.
          </p>

          {personId && (
            <>
              <div className="av-score">
                <div><strong>{calendar?.shift_rules.filter((s) => !s.disabled_at).length ?? 0}</strong>
                  <span>Правила смен</span></div>
                <div><strong>{load?.active_reservations ?? "—"}</strong>
                  <span>Бронирования</span></div>
                <div><strong>{load ? (load.reserved_minutes / 60).toFixed(1) : "—"}</strong>
                  <span>Планово занято, ч</span></div>
                <div><strong>{load ? (load.absence_minutes / 60).toFixed(1) : "—"}</strong>
                  <span>Отсутствия, ч</span></div>
              </div>

              <div className="av-columns">
                <div>
                  <h3>Недельный график смен</h3>
                  <div className="av-records">
                    {calendar?.shift_rules.map((shift) => (
                      <article key={shift.id}>
                        <div className="av-item-head">
                          <strong>{weekdays[shift.weekday]} · {shift.local_start.slice(0, 5)}
                            {" – "}{shift.local_end.slice(0, 5)}</strong>
                          <small>{shift.disabled_at ? "Отключено" : "Активно"}</small>
                        </div>
                        <p>{shift.time_zone} · с {shift.valid_from}
                          {shift.valid_to ? ` по ${shift.valid_to}` : ""}</p>
                        {admin && !shift.disabled_at && (
                          <button className="av-secondary" type="button"
                            disabled={busy} onClick={() => disable(shift.id)}>
                            Отключить смену
                          </button>
                        )}
                      </article>
                    ))}
                    {!calendar?.shift_rules.length &&
                      <p className="av-empty">Смены ещё не заданы.</p>}
                  </div>
                </div>
                <div>
                  <h3>Нерабочие дни предприятия</h3>
                  <div className="av-records">
                    {calendar?.closures.map((closure) => (
                      <article key={closure.id}>
                        <strong>{closure.local_date} · {closure.label}</strong>
                        <p>{closure.time_zone}</p>
                      </article>
                    ))}
                    {!calendar?.closures.length &&
                      <p className="av-empty">Нерабочие дни не заданы.</p>}
                  </div>
                </div>
              </div>

              <div className="av-columns">
                <div>
                  <h3>Отсутствия</h3>
                  <div className="av-records">
                    {calendar?.absences.map((absence) => (
                      <article key={absence.id}>
                        <div className="av-item-head">
                          <strong>{absence.starts_at.slice(0, 16)}
                            {" — "}{absence.ends_at.slice(0, 16)} UTC</strong>
                          <small>{absence.cancelled_at ? "Отменено" : "Недоступен"}</small>
                        </div>
                        {admin && absence.note && <p>{absence.note}</p>}
                        {admin && !absence.cancelled_at && (
                          <button className="av-secondary" type="button" disabled={busy}
                            onClick={() => cancel("absences", absence.id)}>
                            Отменить отсутствие
                          </button>
                        )}
                      </article>
                    ))}
                    {!calendar?.absences.length &&
                      <p className="av-empty">Отсутствия в выбранном периоде не указаны.</p>}
                  </div>
                </div>
                <div>
                  <h3>Плановые бронирования</h3>
                  <div className="av-records">
                    {calendar?.reservations.map((entry) => (
                      <article key={entry.id}>
                        <div className="av-item-head">
                          <strong>{entry.starts_at.slice(0, 16)}
                            {" — "}{entry.ends_at.slice(0, 16)} UTC</strong>
                          <small>{entry.cancelled_at ? "Отменено" : "Занят"}</small>
                        </div>
                        {admin && entry.external_reference && <p>{entry.external_reference}</p>}
                        {admin && !entry.cancelled_at && (
                          <button className="av-secondary" type="button" disabled={busy}
                            onClick={() => cancel("reservations", entry.id)}>
                            Отменить бронь
                          </button>
                        )}
                      </article>
                    ))}
                    {!calendar?.reservations.length &&
                      <p className="av-empty">Нет бронирований за выбранный период.</p>}
                  </div>
                </div>
              </div>

              <div className="av-check">
                <h3>Проверить доступность специалиста</h3>
                <form className="av-form" onSubmit={checkAvailability}>
                  <label>Начало интервала (UTC)
                    <input type="datetime-local" required value={checkFrom}
                      onChange={(e) => setCheckFrom(e.target.value)} />
                  </label>
                  <label>Конец интервала (UTC)
                    <input type="datetime-local" required value={checkTo}
                      onChange={(e) => setCheckTo(e.target.value)} />
                  </label>
                  <button type="submit" className="av-button" disabled={busy}>Проверить</button>
                </form>
                {checkResult && (
                  <div className={`av-result ${checkResult.available ? "ok" : "blocked"}`}
                    role="status">
                    <strong>{checkResult.available
                      ? "Календарный интервал доступен"
                      : "Календарный интервал недоступен"}</strong>
                    {checkResult.blockers.map((b, i) => (
                      <p key={i}>{blockerNames[b.code] ?? b.message}</p>
                    ))}
                  </div>
                )}
                <p className="av-hint">
                  Доступность не означает наличия компетенций и обязательных допусков.
                  Проверка перед назначением работы должна учитывать все три условия.
                </p>
              </div>

              {admin && resourceId && (
                <div className="av-admin">
                  <h3>Администрирование графика</h3>
                  <details>
                    <summary>Добавить повторяющуюся смену</summary>
                    <form className="av-form" onSubmit={submitShift}>
                      <label>День недели
                        <select value={shiftDay} onChange={(e) => setShiftDay(Number(e.target.value))}>
                          {weekdays.map((name, i) => (
                            <option key={name} value={i}>{name}</option>
                          ))}
                        </select>
                      </label>
                      <label>Начало (локальное время)
                        <input type="time" required value={shiftStart}
                          onChange={(e) => setShiftStart(e.target.value)} />
                      </label>
                      <label>Конец (локальное время)
                        <input type="time" required value={shiftEnd}
                          onChange={(e) => setShiftEnd(e.target.value)} />
                      </label>
                      <label>Часовой пояс IANA
                        <input required maxLength={80} value={shiftZone}
                          onChange={(e) => setShiftZone(e.target.value)} />
                      </label>
                      <label>Действует с
                        <input type="date" value={shiftValidFrom} required
                          onChange={(e) => setShiftValidFrom(e.target.value)} />
                      </label>
                      <label>Действует по (необязательно)
                        <input type="date" value={shiftValidTo}
                          onChange={(e) => setShiftValidTo(e.target.value)} />
                      </label>
                      <button className="av-button" type="submit" disabled={busy}>Создать смену</button>
                    </form>
                  </details>
                  <details>
                    <summary>Добавить нерабочий день предприятия</summary>
                    <form className="av-form" onSubmit={submitClosure}>
                      <label>Дата
                        <input type="date" value={closureDate} required
                          onChange={(e) => setClosureDate(e.target.value)} />
                      </label>
                      <label>Часовой пояс
                        <input value={closureZone} required
                          onChange={(e) => setClosureZone(e.target.value)} />
                      </label>
                      <label>Название
                        <input maxLength={180} value={closureLabel} required
                          onChange={(e) => setClosureLabel(e.target.value)} />
                      </label>
                      <button className="av-button" type="submit" disabled={busy}>Добавить день</button>
                    </form>
                  </details>
                  <details>
                    <summary>Зарегистрировать отсутствие</summary>
                    <form className="av-form" onSubmit={submitAbsence}>
                      <label>С (UTC)
                        <input type="datetime-local" value={absenceStart} required
                          onChange={(e) => setAbsenceStart(e.target.value)} />
                      </label>
                      <label>По (UTC)
                        <input type="datetime-local" value={absenceEnd} required
                          onChange={(e) => setAbsenceEnd(e.target.value)} />
                      </label>
                      <label>Категория
                        <select value={absenceCategory}
                          onChange={(e) => setAbsenceCategory(e.target.value)}>
                          <option value="leave">Отпуск</option>
                          <option value="training">Обучение</option>
                          <option value="unavailable">Недоступен</option>
                        </select>
                      </label>
                      <label>Служебная пометка (видит только администратор)
                        <input maxLength={400} value={absenceNote}
                          onChange={(e) => setAbsenceNote(e.target.value)} />
                      </label>
                      <button type="submit" className="av-button" disabled={busy}>
                        Создать отсутствие
                      </button>
                    </form>
                  </details>
                  <details>
                    <summary>Забронировать плановое время</summary>
                    <form className="av-form" onSubmit={submitReservation}>
                      <label>Начало (UTC)
                        <input type="datetime-local" required value={reserveFrom}
                          onChange={(e) => setReserveFrom(e.target.value)} />
                      </label>
                      <label>Конец (UTC)
                        <input type="datetime-local" required value={reserveTo}
                          onChange={(e) => setReserveTo(e.target.value)} />
                      </label>
                      <label>Внешний код задания (необязательно)
                        <input maxLength={100} value={reservationRef}
                          onChange={(e) => setReservationRef(e.target.value)} />
                      </label>
                      <button type="submit" className="av-button" disabled={busy}>
                        Проверить и забронировать
                      </button>
                    </form>
                    <p className="av-hint">
                      Бронирование заблокируется при отсутствии смены, отпуске,
                      закрытом календарном дне или занятом интервале. Это не наряд на работу.
                    </p>
                  </details>
                </div>
              )}
            </>
          )}
        </>
      )}
      {error && <p className="av-error" role="alert">{error}</p>}
      {notice && <p className="av-notice" role="status">{notice}</p>}
    </section>
  );
}
