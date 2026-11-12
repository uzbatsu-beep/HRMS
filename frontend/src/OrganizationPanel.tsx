import { FormEvent, useEffect, useMemo, useState } from "react";

type User = { id: string; username: string; role: "admin" | "manager" | "viewer" };
type Session = { user: User; csrf_token: string };
type Enterprise = { id: string; code: string; name: string };
type UnitType = { id: string; enterprise_id: string; code: string; name: string };
type Unit = {
  id: string;
  enterprise_id: string;
  code: string;
  name: string;
  parent_id: string | null;
  type_id: string;
};
type Scope = {
  id: string;
  user_id: string;
  unit_id: string;
  include_descendants: boolean;
};
type Audit = {
  id: string;
  actor_user_id: string;
  action: string;
  subject_id: string;
  created_at?: string;
};

async function api<T>(
  path: string,
  options: RequestInit = {},
  csrfToken?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
  });
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      // Non-JSON HTTP errors retain the status code.
    }
    throw new Error(`HTTP ${response.status}${detail ? ": " + detail : ""}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function hierarchy(units: Unit[]): { unit: Unit; depth: number }[] {
  const children = new Map<string, Unit[]>();
  const ids = new Set(units.map((unit) => unit.id));
  for (const unit of units) {
    const key = unit.parent_id && ids.has(unit.parent_id) ? unit.parent_id : "";
    const siblings = children.get(key) ?? [];
    siblings.push(unit);
    children.set(key, siblings);
  }
  const result: { unit: Unit; depth: number }[] = [];
  const visited = new Set<string>();
  function traverse(parentId: string, depth: number) {
    const siblings = [...(children.get(parentId) ?? [])].sort((a, b) =>
      a.name.localeCompare(b.name, "ru"),
    );
    for (const unit of siblings) {
      if (visited.has(unit.id)) continue;
      visited.add(unit.id);
      result.push({ unit, depth });
      traverse(unit.id, depth + 1);
    }
  }
  traverse("", 0);
  for (const unit of units) {
    if (!visited.has(unit.id)) result.push({ unit, depth: 0 });
  }
  return result;
}

export default function OrganizationPanel() {
  const [authRevision, setAuthRevision] = useState(0);
  const [session, setSession] = useState<Session | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [enterpriseId, setEnterpriseId] = useState("");
  const [types, setTypes] = useState<UnitType[]>([]);
  const [units, setUnits] = useState<Unit[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [scopes, setScopes] = useState<Scope[]>([]);
  const [events, setEvents] = useState<Audit[]>([]);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [working, setWorking] = useState(false);

  const [enterpriseCode, setEnterpriseCode] = useState("");
  const [enterpriseName, setEnterpriseName] = useState("");
  const [typeCode, setTypeCode] = useState("");
  const [typeName, setTypeName] = useState("");
  const [unitCode, setUnitCode] = useState("");
  const [unitName, setUnitName] = useState("");
  const [unitType, setUnitType] = useState("");
  const [unitParent, setUnitParent] = useState("");
  const [editUnit, setEditUnit] = useState<Unit | null>(null);
  const [editName, setEditName] = useState("");
  const [editType, setEditType] = useState("");
  const [editParent, setEditParent] = useState("");
  const [scopeUser, setScopeUser] = useState("");
  const [scopeUnit, setScopeUnit] = useState("");
  const [includeDescendants, setIncludeDescendants] = useState(true);

  const isAdmin = session?.user.role === "admin";
  const tree = useMemo(() => hierarchy(units), [units]);
  const activeEnterprise = enterprises.find((enterprise) => enterprise.id === enterpriseId);
  const typesById = useMemo(
    () => new Map(types.map((type) => [type.id, type.name])),
    [types],
  );
  const unitsById = useMemo(
    () => new Map(units.map((unit) => [unit.id, unit.name])),
    [units],
  );
  const usersById = useMemo(
    () => new Map(users.map((user) => [user.id, user.username])),
    [users],
  );

  useEffect(() => {
    function onAuthChanged() {
      setAuthRevision((old) => old + 1);
    }
    window.addEventListener("twm-auth-changed", onAuthChanged);
    return () => window.removeEventListener("twm-auth-changed", onAuthChanged);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setAuthLoading(true);
    api<Session>("/api/v1/auth/me")
      .then((data) => {
        if (!cancelled) setSession(data);
      })
      .catch(() => {
        if (!cancelled) setSession(null);
      })
      .finally(() => {
        if (!cancelled) setAuthLoading(false);
      });
    return () => { cancelled = true; };
  }, [authRevision]);

  useEffect(() => {
    if (!session) {
      setEnterprises([]);
      setUnits([]);
      setTypes([]);
      setScopes([]);
      setUsers([]);
      setEvents([]);
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const list = await api<Enterprise[]>("/api/v1/org/enterprises");
        if (cancelled) return;
        setEnterprises(list);
        setEnterpriseId((current) =>
          list.some((enterprise) => enterprise.id === current)
            ? current : list[0]?.id ?? "",
        );
        if (session?.user.role === "admin") {
          const [allUsers, allScopes] = await Promise.all([
            api<User[]>("/api/v1/auth/users"),
            api<Scope[]>("/api/v1/org/scopes"),
          ]);
          if (!cancelled) {
            setUsers(allUsers);
            setScopes(allScopes);
          }
        }
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Ошибка API");
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [session?.user.id, session?.user.role, refresh]);

  useEffect(() => {
    if (!session || !enterpriseId) {
      setUnits([]);
      setTypes([]);
      setEvents([]);
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const [unitTypes, orgUnits] = await Promise.all([
          api<UnitType[]>(`/api/v1/org/enterprises/${enterpriseId}/types`),
          api<Unit[]>(`/api/v1/org/enterprises/${enterpriseId}/units`),
        ]);
        if (cancelled) return;
        setTypes(unitTypes);
        setUnits(orgUnits);
        setUnitType((old) => unitTypes.some((type) => type.id === old)
          ? old : unitTypes[0]?.id ?? "");
        if (session?.user.role === "admin") {
          const audit = await api<Audit[]>(
            `/api/v1/org/audit?enterprise_id=${enterpriseId}`,
          );
          if (!cancelled) setEvents(audit);
        }
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Ошибка API");
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [enterpriseId, session?.user.id, session?.user.role, refresh]);

  async function change(
    action: () => Promise<void>,
    message: string,
  ) {
    setWorking(true);
    setError("");
    setFeedback("");
    try {
      await action();
      setFeedback(message);
      setRefresh((old) => old + 1);
      window.dispatchEvent(new Event("twm-org-changed"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Ошибка изменения");
    } finally {
      setWorking(false);
    }
  }

  function submitEnterprise(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    void change(async () => {
      const enterprise = await api<Enterprise>(
        "/api/v1/org/enterprises",
        { method: "POST", body: JSON.stringify({
          code: enterpriseCode, name: enterpriseName,
        }) },
        session.csrf_token,
      );
      setEnterpriseCode("");
      setEnterpriseName("");
      setEnterpriseId(enterprise.id);
    }, "Предприятие создано.");
  }

  function submitType(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId) return;
    void change(async () => {
      await api(
        `/api/v1/org/enterprises/${enterpriseId}/types`,
        { method: "POST", body: JSON.stringify({ code: typeCode, name: typeName }) },
        session.csrf_token,
      );
      setTypeCode("");
      setTypeName("");
    }, "Тип подразделения добавлен.");
  }

  function submitUnit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId || !unitType) return;
    void change(async () => {
      await api(
        `/api/v1/org/enterprises/${enterpriseId}/units`,
        { method: "POST", body: JSON.stringify({
          code: unitCode, name: unitName, type_id: unitType,
          parent_id: unitParent || null,
        }) },
        session.csrf_token,
      );
      setUnitCode("");
      setUnitName("");
      setUnitParent("");
    }, "Подразделение добавлено.");
  }

  function beginEdit(unit: Unit) {
    setEditUnit(unit);
    setEditName(unit.name);
    setEditType(unit.type_id);
    setEditParent(unit.parent_id ?? "");
  }

  function submitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !editUnit) return;
    void change(async () => {
      await api(
        `/api/v1/org/units/${editUnit.id}`,
        { method: "PATCH", body: JSON.stringify({
          name: editName, type_id: editType, parent_id: editParent || null,
        }) },
        session.csrf_token,
      );
      setEditUnit(null);
    }, "Подразделение обновлено.");
  }

  function submitGrant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !scopeUser || !scopeUnit) return;
    void change(async () => {
      await api(
        "/api/v1/org/scopes",
        { method: "POST", body: JSON.stringify({
          user_id: scopeUser, unit_id: scopeUnit,
          include_descendants: includeDescendants,
        }) },
        session.csrf_token,
      );
      setScopeUnit("");
    }, "Область доступа назначена.");
  }

  function revoke(scopeId: string) {
    if (!session || !window.confirm("Отозвать доступ к выбранному подразделению?")) return;
    void change(
      () => api<void>(
        `/api/v1/org/scopes/${scopeId}`,
        { method: "DELETE" },
        session.csrf_token,
      ),
      "Разрешение отозвано.",
    );
  }

  const enterpriseScopes = scopes.filter((scope) => unitsById.has(scope.unit_id));

  return (
    <section className="org-panel" id="organization" aria-labelledby="org-title">
      <div className="section-heading">
        <div>
          <div className="eyebrow">ORGANIZATION · RBAC SCOPE</div>
          <h2 id="org-title">Организационная структура</h2>
        </div>
        <span className="org-count">{units.length} подразделений</span>
      </div>
      <p className="org-intro">
        Настраиваемые уровни и типы подразделений. Список формируется сервером
        согласно роли и назначенной области доступа.
      </p>
      {authLoading && <p role="status">Проверка доступа...</p>}
      {!authLoading && !session && (
        <p className="org-notice">Войдите в систему, чтобы просмотреть доступную структуру.</p>
      )}
      {session && (
        <>
          <div className="org-toolbar">
            <label className="org-field">
              Предприятие
              <select
                value={enterpriseId}
                onChange={(event) => setEnterpriseId(event.target.value)}
              >
                {enterprises.length === 0 && <option value="">Нет доступных предприятий</option>}
                {enterprises.map((enterprise) => (
                  <option key={enterprise.id} value={enterprise.id}>
                    {enterprise.name} · {enterprise.code}
                  </option>
                ))}
              </select>
            </label>
            <button className="org-button org-button-muted" type="button"
              disabled={working} onClick={() => setRefresh((old) => old + 1)}>
              Обновить
            </button>
          </div>

          {isAdmin && (
            <details className="org-details">
              <summary>Создать предприятие</summary>
              <form className="org-form" onSubmit={submitEnterprise}>
                <label>Код
                  <input required maxLength={64} pattern="[a-zA-Z0-9_.-]+"
                    value={enterpriseCode}
                    onChange={(event) => setEnterpriseCode(event.target.value)} />
                </label>
                <label>Название
                  <input required maxLength={200} value={enterpriseName}
                    onChange={(event) => setEnterpriseName(event.target.value)} />
                </label>
                <button className="org-button" disabled={working}>Создать</button>
              </form>
            </details>
          )}

          {enterpriseId && (
            <>
              <div className="org-section-title">
                <h3>{activeEnterprise?.name ?? "Подразделения"}</h3>
                <span>Иерархия без фиксированной глубины</span>
              </div>
              {tree.length === 0 && <p className="org-notice">
                Нет доступных подразделений.
                {!isAdmin && " Обратитесь к администратору для назначения доступа."}
              </p>}
              <div className="org-tree" role="list">
                {tree.map(({ unit, depth }) => (
                  <div className="org-tree-row" key={unit.id} role="listitem"
                    style={{ paddingLeft: `${14 + depth * 22}px` }}>
                    <span className="org-branch" aria-hidden="true">↳</span>
                    <div className="org-tree-label">
                      <strong>{unit.name}</strong>
                      <small>{typesById.get(unit.type_id) ?? "Тип"} · {unit.code}</small>
                    </div>
                    {isAdmin && (
                      <button className="org-button org-button-muted" type="button"
                        onClick={() => beginEdit(unit)}>
                        Изменить
                      </button>
                    )}
                  </div>
                ))}
              </div>

              {isAdmin && (
                <>
                  <details className="org-details">
                    <summary>Добавить тип подразделения</summary>
                    <form className="org-form" onSubmit={submitType}>
                      <label>Код типа
                        <input required pattern="[a-zA-Z0-9_.-]+" maxLength={64}
                          value={typeCode} onChange={(event) => setTypeCode(event.target.value)} />
                      </label>
                      <label>Название типа
                        <input required maxLength={120} value={typeName}
                          onChange={(event) => setTypeName(event.target.value)} />
                      </label>
                      <button className="org-button" disabled={working}>Добавить тип</button>
                    </form>
                  </details>
                  <details className="org-details" open={types.length === 0}>
                    <summary>Добавить подразделение</summary>
                    {types.length === 0
                      ? <p className="org-notice">Сначала добавьте хотя бы один тип.</p>
                      : <form className="org-form" onSubmit={submitUnit}>
                          <label>Код
                            <input required pattern="[a-zA-Z0-9_.-]+" maxLength={64}
                              value={unitCode}
                              onChange={(event) => setUnitCode(event.target.value)} />
                          </label>
                          <label>Название
                            <input required maxLength={200} value={unitName}
                              onChange={(event) => setUnitName(event.target.value)} />
                          </label>
                          <label>Тип
                            <select value={unitType}
                              onChange={(event) => setUnitType(event.target.value)}>
                              {types.map((type) => (
                                <option key={type.id} value={type.id}>{type.name}</option>
                              ))}
                            </select>
                          </label>
                          <label>Родительский узел
                            <select value={unitParent}
                              onChange={(event) => setUnitParent(event.target.value)}>
                              <option value="">Корневое подразделение</option>
                              {units.map((unit) => (
                                <option key={unit.id} value={unit.id}>{unit.name}</option>
                              ))}
                            </select>
                          </label>
                          <button className="org-button" disabled={working}>Создать узел</button>
                        </form>}
                  </details>

                  {editUnit && (
                    <form className="org-edit" onSubmit={submitEdit}>
                      <h4>Редактировать: {editUnit.code}</h4>
                      <div className="org-form">
                        <label>Название
                          <input value={editName} onChange={(event) => setEditName(event.target.value)}
                            required maxLength={200} />
                        </label>
                        <label>Тип
                          <select value={editType}
                            onChange={(event) => setEditType(event.target.value)}>
                            {types.map((type) => (
                              <option key={type.id} value={type.id}>{type.name}</option>
                            ))}
                          </select>
                        </label>
                        <label>Родительский узел
                          <select value={editParent}
                            onChange={(event) => setEditParent(event.target.value)}>
                            <option value="">Корень</option>
                            {units.filter((unit) => unit.id !== editUnit.id).map((unit) => (
                              <option key={unit.id} value={unit.id}>{unit.name}</option>
                            ))}
                          </select>
                        </label>
                        <button className="org-button" disabled={working}>Сохранить</button>
                        <button type="button" className="org-button org-button-muted"
                          onClick={() => setEditUnit(null)}>Отмена</button>
                      </div>
                      <p className="org-hint">Сервер отклонит изменение, создающее цикл.</p>
                    </form>
                  )}

                  <div className="org-section-title">
                    <h3>Области доступа</h3>
                    <span>Только администратор</span>
                  </div>
                  <form className="org-form" onSubmit={submitGrant}>
                    <label>Пользователь
                      <select value={scopeUser}
                        onChange={(event) => setScopeUser(event.target.value)} required>
                        <option value="">Выберите пользователя</option>
                        {users.filter((user) => user.role !== "admin").map((user) => (
                          <option key={user.id} value={user.id}>{user.username}</option>
                        ))}
                      </select>
                    </label>
                    <label>Подразделение
                      <select value={scopeUnit}
                        onChange={(event) => setScopeUnit(event.target.value)} required>
                        <option value="">Выберите узел</option>
                        {units.map((unit) => (
                          <option key={unit.id} value={unit.id}>{unit.name}</option>
                        ))}
                      </select>
                    </label>
                    <label className="org-checkbox">
                      <input type="checkbox" checked={includeDescendants}
                        onChange={(event) => setIncludeDescendants(event.target.checked)} />
                      Включая подчинённые узлы
                    </label>
                    <button className="org-button" disabled={working}>Назначить</button>
                  </form>
                  <div className="org-scopes">
                    {enterpriseScopes.map((scope) => (
                      <div className="org-scope-row" key={scope.id}>
                        <span>
                          <strong>{usersById.get(scope.user_id) ?? "Пользователь"}</strong>
                          {" · "}{unitsById.get(scope.unit_id)}
                          {scope.include_descendants ? " · с потомками" : " · только узел"}
                        </span>
                        <button type="button" className="org-button org-button-muted"
                          disabled={working} onClick={() => revoke(scope.id)}>Отозвать</button>
                      </div>
                    ))}
                    {enterpriseScopes.length === 0 && (
                      <p className="org-hint">Для этого предприятия ещё нет разрешений.</p>
                    )}
                  </div>
                  <details className="org-details">
                    <summary>Журнал изменений ({events.length})</summary>
                    <div className="org-log">
                      {events.slice(0, 15).map((event) => (
                        <div key={event.id}>
                          <strong>{event.action}</strong> · {event.subject_id.slice(0, 8)} ·
                          {" "}{usersById.get(event.actor_user_id) ?? "Администратор"}
                        </div>
                      ))}
                      {events.length === 0 && <p>Пока нет изменений.</p>}
                    </div>
                  </details>
                </>
              )}
            </>
          )}
        </>
      )}
      {error && <p className="org-error" role="alert">{error}</p>}
      {feedback && <p className="org-success" role="status">{feedback}</p>}
    </section>
  );
}
