import { FormEvent, useEffect, useState } from "react";
import { useWorkspace } from "./WorkspaceContext";
import PersonCustomFields from "./PersonCustomFields";

type Session = {
  user: { id: string; username: string; role: "admin" | "manager" | "viewer" };
  csrf_token: string;
};
type Enterprise = { id: string; name: string; code: string };
type Unit = { id: string; name: string; code: string };
type Assignment = {
  id: string;
  unit_id: string;
  position_title: string | null;
  effective_from: string;
  effective_to: string | null;
};
type Team = { id: string; unit_id: string; effective_from: string; effective_to: string | null };
type Person = {
  id: string;
  resource_id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
  middle_name: string | null;
  archived_at: string | null;
  current_unit_id: string | null;
  current_unit_name: string | null;
  position_title: string | null;
  current_since: string | null;
};
type Detail = Person & { assignments: Assignment[]; team_memberships: Team[] };

async function request<T>(path: string, init: RequestInit = {}, csrf?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(path, { credentials: "same-origin", ...init, headers });
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Network and non-JSON errors use the HTTP status.
    }
    throw new Error(`HTTP ${response.status}${detail ? ": " + detail : ""}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const today = () => new Date().toISOString().slice(0, 10);

export default function PersonnelPanel() {
  const [authRevision, setAuthRevision] = useState(0);
  const [session, setSession] = useState<Session | null>(null);
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const {
    enterpriseId, setEnterpriseId, unitId: unitFilter, setUnitId: setUnitFilter,
    personId: selectedId, setPersonId: setSelectedId,
  } = useWorkspace();
  const [units, setUnits] = useState<Unit[]>([]);
  const [people, setPeople] = useState<Person[]>([]);

  const [detail, setDetail] = useState<Detail | null>(null);
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");

  const [includeArchived, setIncludeArchived] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const [code, setCode] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [middle, setMiddle] = useState("");
  const [initialUnit, setInitialUnit] = useState("");
  const [initialRole, setInitialRole] = useState("");
  const [startOn, setStartOn] = useState(today());
  const [assignmentUnit, setAssignmentUnit] = useState("");
  const [assignmentDate, setAssignmentDate] = useState(today());
  const [assignmentTitle, setAssignmentTitle] = useState("");
  const [transferUnit, setTransferUnit] = useState("");
  const [transferDate, setTransferDate] = useState(today());
  const [transferTitle, setTransferTitle] = useState("");
  const [teamUnit, setTeamUnit] = useState("");
  const [teamStart, setTeamStart] = useState(today());
  const [editFirst, setEditFirst] = useState("");
  const [editLast, setEditLast] = useState("");
  const [editMiddle, setEditMiddle] = useState("");

  const admin = session?.user.role === "admin";
  const unitNames = new Map(units.map((unit) => [unit.id, unit.name]));
  const selectedEnterprise = enterprises.find((e) => e.id === enterpriseId);

  useEffect(() => {
    const onAuthChanged = () => {
      setSession(null);
      setAuthRevision((old) => old + 1);
    };
    const onOrgChanged = () => setRefresh((old) => old + 1);
    window.addEventListener("twm-auth-changed", onAuthChanged);
    window.addEventListener("twm-org-changed", onOrgChanged);
    return () => {
      window.removeEventListener("twm-auth-changed", onAuthChanged);
      window.removeEventListener("twm-org-changed", onOrgChanged);
    };
  }, []);

  useEffect(() => {
    let active = true;
    request<Session>("/api/v1/auth/me")
      .then((data) => { if (active) setSession(data); })
      .catch(() => { if (active) setSession(null); });
    return () => { active = false; };
  }, [authRevision]);

  useEffect(() => {
    if (!session) {
      setEnterprises([]);
      setPeople([]);
      setDetail(null);
      setUnits([]);
      return;
    }
    let active = true;
    request<Enterprise[]>("/api/v1/org/enterprises")
      .then((records) => {
        if (!active) return;
        setEnterprises(records);
        setEnterpriseId((previous) =>
          records.some((item) => item.id === previous)
            ? previous : records[0]?.id ?? "");
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Ошибка API");
      });
    return () => { active = false; };
  }, [session?.user.id, refresh]);

  useEffect(() => {
    setDetail(null);
    if (!session || !enterpriseId) {
      setUnits([]);
      setPeople([]);
      return;
    }
    let active = true;
    request<Unit[]>(`/api/v1/org/enterprises/${enterpriseId}/units`)
      .then((records) => { if (active) setUnits(records); })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Ошибка подразделений");
      });
    return () => { active = false; };
  }, [enterpriseId, session?.user.id]);

  useEffect(() => {
    if (!session || !enterpriseId) return;
    let active = true;
    const params = new URLSearchParams({ limit: "100" });
    if (query.trim()) params.set("q", query.trim());
    if (unitFilter) params.set("unit_id", unitFilter);
    if (session.user.role === "admin" && includeArchived) params.set("include_archived", "true");
    request<Person[]>(
      `/api/v1/personnel/enterprises/${enterpriseId}/persons?${params.toString()}`,
    )
      .then((records) => { if (active) setPeople(records); })
      .catch((reason: unknown) => {
        if (active) {
          setPeople([]);
          setError(reason instanceof Error ? reason.message : "Ошибка загрузки персонала");
        }
      });
    return () => { active = false; };
  }, [session?.user.id, enterpriseId, query, unitFilter, includeArchived, refresh]);

  useEffect(() => {
    if (!selectedId || !session) {
      setDetail(null);
      return;
    }
    let active = true;
    request<Detail>(`/api/v1/personnel/persons/${selectedId}`)
      .then((data) => {
        if (!active) return;
        setDetail(data);
        setEditFirst(data.first_name);
        setEditLast(data.last_name);
        setEditMiddle(data.middle_name ?? "");
      })
      .catch((reason: unknown) => {
        if (active) {
          setDetail(null);
          setError(reason instanceof Error ? reason.message : "Карточка недоступна");
        }
      });
    return () => { active = false; };
  }, [selectedId, session?.user.id, refresh]);

  async function perform(action: () => Promise<void>, success: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      setRefresh((old) => old + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Ошибка выполнения");
    } finally {
      setBusy(false);
    }
  }

  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId) return;
    void perform(async () => {
      const created = await request<Detail>(
        `/api/v1/personnel/enterprises/${enterpriseId}/persons`,
        {
          method: "POST",
          body: JSON.stringify({
            employee_code: code, first_name: first,
            last_name: last, middle_name: middle || null,
            unit_id: initialUnit || null,
            position_title: initialRole || null,
            effective_from: startOn,
          }),
        },
        session.csrf_token,
      );
      setSelectedId(created.id);
      setCode("");
      setFirst("");
      setLast("");
      setMiddle("");
      setInitialUnit("");
      setInitialRole("");
    }, "Карточка специалиста создана.");
  }

  function assignPrimary(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !detail || !assignmentUnit) return;
    void perform(async () => {
      await request(
        `/api/v1/personnel/resources/${detail.resource_id}/assignments`,
        {
          method: "POST",
          body: JSON.stringify({
            unit_id: assignmentUnit,
            effective_from: assignmentDate,
            position_title: assignmentTitle || null,
          }),
        },
        session.csrf_token,
      );
      setAssignmentUnit("");
      setAssignmentTitle("");
    }, "Основное назначение зарегистрировано.");
  }

  function closeTeam(item: Team) {
    if (!session || !detail || item.effective_to || item.effective_from > today()) return;
    if (!window.confirm("Завершить участие в этой бригаде сегодняшним числом?")) return;
    void perform(async () => {
      await request(
        `/api/v1/personnel/teams/${item.id}/close`,
        {
          method: "PATCH",
          body: JSON.stringify({ effective_to: today() }),
        },
        session.csrf_token,
      );
    }, "Членство завершено, история сохранена.");
  }

  function transfer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !detail || !transferUnit) return;
    void perform(async () => {
      await request(
        `/api/v1/personnel/resources/${detail.resource_id}/transfer`,
        {
          method: "POST",
          body: JSON.stringify({
            unit_id: transferUnit, effective_on: transferDate,
            position_title: transferTitle || null,
          }),
        },
        session.csrf_token,
      );
      setTransferUnit("");
      setTransferTitle("");
    }, "Перевод зарегистрирован, история сохранена.");
  }

  function addTeam(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !detail || !teamUnit) return;
    void perform(async () => {
      await request(
        `/api/v1/personnel/resources/${detail.resource_id}/teams`,
        {
          method: "POST",
          body: JSON.stringify({ unit_id: teamUnit, effective_from: teamStart }),
        },
        session.csrf_token,
      );
      setTeamUnit("");
    }, "Членство в дополнительной бригаде зарегистрировано.");
  }

  function update(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !detail) return;
    void perform(async () => {
      await request(
        `/api/v1/personnel/persons/${detail.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            first_name: editFirst,
            last_name: editLast,
            middle_name: editMiddle || null,
          }),
        },
        session.csrf_token,
      );
    }, "Данные специалиста обновлены.");
  }

  function archive() {
    if (!session || !detail) return;
    if (!window.confirm("Архивировать карточку? История назначений сохранится.")) return;
    void perform(async () => {
      await request(
        `/api/v1/personnel/persons/${detail.id}/archive`,
        { method: "POST" },
        session.csrf_token,
      );
      setSelectedId("");
    }, "Карточка архивирована. История сохранена.");
  }

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuery(queryDraft);
  }

  return (
    <section className="people-panel" id="personnel" aria-labelledby="people-title">
      <div className="section-heading">
        <div>
          <div className="eyebrow">PERSONNEL · WORKFORCE RESOURCES</div>
          <h2 id="people-title">Технический персонал</h2>
        </div>
        <span className="people-counter">{people.length} карточек</span>
      </div>
      <p className="people-description">
        Карточки специалистов, основное подразделение, дополнительные бригады и история переводов.
        Доступ ограничен серверными правами на подразделения.
      </p>
      {!session && <p className="people-empty">Для просмотра кадровой структуры войдите в систему.</p>}
      {session && (
        <>
          <div className="people-filters">
            <label>Предприятие
              <select value={enterpriseId} onChange={(event) => setEnterpriseId(event.target.value)}>
                {enterprises.length === 0 && <option value="">Нет доступных предприятий</option>}
                {enterprises.map((entry) => (
                  <option key={entry.id} value={entry.id}>{entry.name}</option>
                ))}
              </select>
            </label>
            <label>Подразделение
              <select value={unitFilter} onChange={(event) => setUnitFilter(event.target.value)}>
                <option value="">Все разрешённые</option>
                {units.map((entry) => (
                  <option key={entry.id} value={entry.id}>{entry.name}</option>
                ))}
              </select>
            </label>
            <form onSubmit={search} className="people-search">
              <label>Поиск
                <input value={queryDraft}
                  onChange={(event) => setQueryDraft(event.target.value)}
                  placeholder="Фамилия или табельный код" maxLength={100} />
              </label>
              <button className="people-button people-muted" type="submit">Найти</button>
            </form>
          </div>
          {admin && (
            <label className="people-archived-toggle">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(event) => setIncludeArchived(event.target.checked)}
              />
              Включить архивные карточки
            </label>
          )}
          <div className="people-subtitle">
            <strong>{selectedEnterprise?.name ?? "Реестр специалистов"}</strong>
            <small>Показано не более 100 записей</small>
          </div>
          <div className="people-list">
            {people.map((person) => (
              <button
                type="button"
                key={person.id}
                className={`people-item ${selectedId === person.id ? "selected" : ""}`}
                onClick={() => setSelectedId(person.id)}
              >
                <span className="people-avatar">{person.last_name.charAt(0)}</span>
                <span className="people-item-main">
                  <strong>{person.last_name} {person.first_name} {person.middle_name ?? ""}</strong>
                  <small>{person.employee_code} · {person.current_unit_name ?? "Не назначен"}{person.archived_at ? " · Архив" : ""}</small>
                </span>
                <span className="people-position">{person.position_title ?? "—"}</span>
              </button>
            ))}
            {enterpriseId && people.length === 0 && (
              <p className="people-empty">В выбранном разделе нет доступных специалистов.</p>
            )}
          </div>

          {detail && (
            <div className="people-detail">
              <div className="people-detail-header">
                <div>
                  <h3>{detail.last_name} {detail.first_name} {detail.middle_name ?? ""}</h3>
                  <p>{detail.employee_code} · {detail.position_title ?? "Должность не указана"}</p>
                </div>
                <button className="people-button people-muted" type="button"
                  onClick={() => setSelectedId("")}>Закрыть</button>
              </div>
              <div className="people-facts">
                <div><span>Основное подразделение</span><strong>
                  {detail.current_unit_name ?? "Не назначено"}
                </strong></div>
                <div><span>Дата назначения</span><strong>{detail.current_since ?? "—"}</strong></div>
                <div><span>Статус</span><strong>
                  {detail.archived_at ? "Архив" : "Действующий"}
                </strong></div>
              </div>
              <PersonCustomFields personId={detail.id} archived={Boolean(detail.archived_at)} />
              <h4>История организационных назначений</h4>
              <div className="people-history">
                {detail.assignments.map((item) => (
                  <div key={item.id}>
                    <strong>{unitNames.get(item.unit_id) ?? "Подразделение"}</strong>
                    <span>{item.position_title ?? "—"} · {item.effective_from}
                      {" → "}{item.effective_to ?? "н.в."}</span>
                  </div>
                ))}
                {detail.assignments.length === 0 && (
                  <p className="people-empty">Нет доступной истории назначений.</p>
                )}
              </div>
              <h4>Дополнительные бригады</h4>
              <div className="people-history">
                {detail.team_memberships.map((item) => (
                  <div key={item.id}>
                    <strong>{unitNames.get(item.unit_id) ?? "Бригада"}</strong>
                    <span>{item.effective_from} → {item.effective_to ?? "н.в."}</span>
                    {admin && !detail.archived_at && !item.effective_to &&
                      item.effective_from <= today() && (
                      <button type="button" className="people-button people-muted"
                        onClick={() => closeTeam(item)} disabled={busy}>
                        Завершить
                      </button>
                    )}
                  </div>
                ))}
                {detail.team_memberships.length === 0 && (
                  <p className="people-empty">Нет дополнительных назначений.</p>
                )}
              </div>

              {admin && !detail.archived_at && (
                <div className="people-admin">
                  <form onSubmit={update} className="people-form">
                    <h4>Редактировать карточку</h4>
                    <label>Фамилия
                      <input required maxLength={100} value={editLast}
                        onChange={(event) => setEditLast(event.target.value)} />
                    </label>
                    <label>Имя
                      <input required maxLength={100} value={editFirst}
                        onChange={(event) => setEditFirst(event.target.value)} />
                    </label>
                    <label>Отчество
                      <input maxLength={100} value={editMiddle}
                        onChange={(event) => setEditMiddle(event.target.value)} />
                    </label>
                    <button className="people-button" type="submit" disabled={busy}>
                      Сохранить данные
                    </button>
                  </form>
                  {!detail.current_unit_id && (
                    <form onSubmit={assignPrimary} className="people-form">
                      <h4>Назначить основное подразделение</h4>
                      <label>Подразделение
                        <select required value={assignmentUnit}
                          onChange={(event) => setAssignmentUnit(event.target.value)}>
                          <option value="">Выберите</option>
                          {units.map((unit) => (
                            <option key={unit.id} value={unit.id}>{unit.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>Дата назначения
                        <input type="date" required value={assignmentDate}
                          onChange={(event) => setAssignmentDate(event.target.value)} />
                      </label>
                      <label>Должность
                        <input maxLength={160} value={assignmentTitle}
                          onChange={(event) => setAssignmentTitle(event.target.value)} />
                      </label>
                      <button className="people-button" type="submit" disabled={busy}>
                        Зарегистрировать назначение
                      </button>
                    </form>
                  )}
                  {detail.current_unit_id && (
                    <form onSubmit={transfer} className="people-form">
                    <h4>Перевод в подразделение</h4>
                    <label>Новое подразделение
                      <select required value={transferUnit}
                        onChange={(event) => setTransferUnit(event.target.value)}>
                        <option value="">Выберите</option>
                        {units.filter((unit) => unit.id !== detail.current_unit_id).map((unit) => (
                          <option key={unit.id} value={unit.id}>{unit.name}</option>
                        ))}
                      </select>
                    </label>
                    <label>Дата перевода
                      <input type="date" required value={transferDate}
                        onChange={(event) => setTransferDate(event.target.value)} />
                    </label>
                    <label>Должность
                      <input value={transferTitle} maxLength={160}
                        onChange={(event) => setTransferTitle(event.target.value)}
                        placeholder="Сохранить прежнюю, если пусто" />
                    </label>
                    <button className="people-button" type="submit" disabled={busy}>
                      Зарегистрировать перевод
                    </button>
                    </form>
                  )}
                  <form onSubmit={addTeam} className="people-form">
                    <h4>Дополнительная бригада</h4>
                    <label>Бригада / подразделение
                      <select required value={teamUnit}
                        onChange={(event) => setTeamUnit(event.target.value)}>
                        <option value="">Выберите</option>
                        {units.map((unit) => (
                          <option key={unit.id} value={unit.id}>{unit.name}</option>
                        ))}
                      </select>
                    </label>
                    <label>Дата начала
                      <input type="date" required value={teamStart}
                        onChange={(event) => setTeamStart(event.target.value)} />
                    </label>
                    <button className="people-button" type="submit" disabled={busy}>
                      Добавить членство
                    </button>
                  </form>
                  <button type="button" className="people-button people-danger"
                    onClick={archive} disabled={busy}>Архивировать карточку</button>
                </div>
              )}
            </div>
          )}

          {admin && enterpriseId && (
            <details className="people-create">
              <summary>Добавить специалиста</summary>
              <form className="people-form people-create-grid" onSubmit={create}>
                <label>Табельный код
                  <input value={code} required pattern="[a-zA-Z0-9_.-]+" maxLength={64}
                    onChange={(event) => setCode(event.target.value)} />
                </label>
                <label>Фамилия
                  <input value={last} required maxLength={100}
                    onChange={(event) => setLast(event.target.value)} />
                </label>
                <label>Имя
                  <input value={first} required maxLength={100}
                    onChange={(event) => setFirst(event.target.value)} />
                </label>
                <label>Отчество
                  <input value={middle} maxLength={100}
                    onChange={(event) => setMiddle(event.target.value)} />
                </label>
                <label>Основное подразделение
                  <select value={initialUnit}
                    onChange={(event) => setInitialUnit(event.target.value)}>
                    <option value="">Не назначено</option>
                    {units.map((unit) => (
                      <option key={unit.id} value={unit.id}>{unit.name}</option>
                    ))}
                  </select>
                </label>
                <label>Должность
                  <input value={initialRole} maxLength={160}
                    onChange={(event) => setInitialRole(event.target.value)} />
                </label>
                <label>Дата назначения
                  <input type="date" value={startOn} required
                    onChange={(event) => setStartOn(event.target.value)} />
                </label>
                <button className="people-button" type="submit" disabled={busy}>
                  Создать карточку
                </button>
              </form>
            </details>
          )}
          {error && <p className="people-error" role="alert">{error}</p>}
          {notice && <p className="people-notice" role="status">{notice}</p>}
        </>
      )}
    </section>
  );
}
