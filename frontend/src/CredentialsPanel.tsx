import { FormEvent, useEffect, useState } from "react";

type User = { id: string; role: "admin" | "manager" | "viewer"; username: string };
type Session = { user: User; csrf_token: string };
type Enterprise = { id: string; name: string; code: string };
type Person = { id: string; last_name: string; first_name: string; employee_code: string };
type Link = { person_id: string; enterprise_id: string; enterprise_name: string };
type CredentialType = {
  id: string; code: string; name: string; kind: string;
  requires_expiry: boolean; is_safety_critical: boolean;
};
type Requirement = { id: string; activity_code: string; type_id: string };
type Credential = {
  id: string; person_id: string; type_id: string; status: string;
  document_reference: string; issuer: string; issued_on: string; valid_from: string;
  expires_on: string | null; submitted_by: string; reviewed_by: string | null;
  reviewed_at: string | null; review_note: string | null; revoke_reason: string | null;
};
type Eligibility = {
  eligible: boolean; activity_code: string; checked_on: string;
  blockers: { code: string; type_id: string | null; message: string }[];
  valid_credentials: { type_id: string; credential_id: string; expires_on: string | null }[];
};

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
    } catch { /* Keep the HTTP status for non-JSON errors. */ }
    throw new Error(`HTTP ${response.status}${detail ? " — " + detail : ""}`);
  }
  return (await response.json()) as T;
}

const root = "/api/v1/credentials";
const localDate = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};

const blockerText: Record<string, string> = {
  NO_POLICY: "Нет утверждённого перечня обязательных документов для вида работ.",
  INACTIVE_PERSON: "Сотрудник или его трудовой ресурс неактивен.",
  NO_ASSIGNMENT: "Нет основного назначения в подразделение на дату проверки.",
  MISSING_CREDENTIAL: "Отсутствует обязательный документ.",
  UNVERIFIED_CREDENTIAL: "Документ не прошёл независимую проверку.",
  EXPIRED_CREDENTIAL: "Срок действия документа истёк.",
  REVOKED_CREDENTIAL: "Документ отозван.",
  REJECTED_CREDENTIAL: "Документ был отклонён.",
  NOT_YET_VALID: "Срок действия документа ещё не начался.",
  MISSING_EXPIRATION: "У обязательного документа отсутствует срок окончания.",
  INVALID_POLICY: "Нарушена конфигурация обязательных требований.",
  INVALID_CREDENTIAL: "Нет действующего проверенного документа.",
};

export default function CredentialsPanel() {
  const [authRevision, setAuthRevision] = useState(0);
  const [session, setSession] = useState<Session | null>(null);
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [enterpriseId, setEnterpriseId] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [ownLink, setOwnLink] = useState<Link | null>(null);
  const [personId, setPersonId] = useState("");
  const [types, setTypes] = useState<CredentialType[]>([]);
  const [rules, setRules] = useState<Requirement[]>([]);
  const [records, setRecords] = useState<Credential[]>([]);
  const [activity, setActivity] = useState("");
  const [checkDate, setCheckDate] = useState(localDate());
  const [eligibility, setEligibility] = useState<Eligibility | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);

  const [typeCode, setTypeCode] = useState("");
  const [typeName, setTypeName] = useState("");
  const [kind, setKind] = useState("permit");
  const [safety, setSafety] = useState(true);
  const [expiryRequired, setExpiryRequired] = useState(true);
  const [ruleCode, setRuleCode] = useState("");
  const [ruleType, setRuleType] = useState("");
  const [recordType, setRecordType] = useState("");
  const [reference, setReference] = useState("");
  const [issuer, setIssuer] = useState("");
  const [issued, setIssued] = useState(localDate());
  const [validFrom, setValidFrom] = useState(localDate());
  const [expires, setExpires] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});

  const admin = session?.user.role === "admin";
  const reviewer = admin || session?.user.role === "manager";
  const typeById = new Map(types.map((type) => [type.id, type]));
  const activeRecordType = typeById.get(recordType);

  useEffect(() => {
    const changed = () => { setSession(null); setAuthRevision((old) => old + 1); };
    const refresh = () => setRevision((old) => old + 1);
    window.addEventListener("twm-auth-changed", changed);
    window.addEventListener("twm-org-changed", refresh);
    window.addEventListener("twm-personnel-changed", refresh);
    return () => {
      window.removeEventListener("twm-auth-changed", changed);
      window.removeEventListener("twm-org-changed", refresh);
      window.removeEventListener("twm-personnel-changed", refresh);
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
      setEnterprises([]); setEnterpriseId(""); setOwnLink(null); setPersonId("");
      setPeople([]); setTypes([]); setRules([]); setRecords([]); setEligibility(null);
      return;
    }
    let active = true;
    async function load() {
      try {
        const [companies, own] = await Promise.all([
          request<Enterprise[]>("/api/v1/org/enterprises"),
          request<Link | null>("/api/v1/competence/me/link"),
        ]);
        if (!active) return;
        const result = [...companies];
        if (own && !result.some((item) => item.id === own.enterprise_id)) {
          result.push({
            id: own.enterprise_id, name: own.enterprise_name, code: "own",
          });
        }
        setOwnLink(own); setEnterprises(result);
        setEnterpriseId((old) =>
          result.some((item) => item.id === old) ? old : result[0]?.id ?? "");
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Ошибка входа");
      }
    }
    void load();
    return () => { active = false; };
  }, [session?.user.id, revision]);

  useEffect(() => {
    setRecords([]); setEligibility(null);
    if (!enterpriseId || !session) {
      setTypes([]); setRules([]); setPeople([]); setPersonId("");
      return;
    }
    let active = true;
    async function load() {
      try {
        const [kinds, requirements, persons] = await Promise.all([
          request<CredentialType[]>(`${root}/enterprises/${enterpriseId}/types`),
          request<Requirement[]>(`${root}/enterprises/${enterpriseId}/requirements`),
          request<Person[]>(
            `/api/v1/personnel/enterprises/${enterpriseId}/persons?limit=100`,
          ).catch(() => []),
        ]);
        if (!active) return;
        setTypes(kinds); setRules(requirements); setPeople(persons);
        const options = persons.map((p) => p.id);
        if (ownLink?.enterprise_id === enterpriseId && ownLink.person_id) {
          options.push(ownLink.person_id);
        }
        setPersonId((old) => options.includes(old) ? old : options[0] ?? "");
        setRecordType((old) => kinds.some((item) => item.id === old)
          ? old : kinds[0]?.id ?? "");
        setRuleType((old) => kinds.some((item) => item.id === old)
          ? old : kinds[0]?.id ?? "");
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Ошибка загрузки");
      }
    }
    void load();
    return () => { active = false; };
  }, [enterpriseId, session?.user.id, revision, ownLink?.person_id]);

  useEffect(() => {
    setEligibility(null);
    if (!personId || !session) { setRecords([]); return; }
    let active = true;
    request<Credential[]>(`${root}/persons/${personId}`)
      .then((rows) => { if (active) setRecords(rows); })
      .catch((reason) => {
        if (active) {
          setRecords([]);
          setError(reason instanceof Error ? reason.message : "Документы недоступны");
        }
      });
    return () => { active = false; };
  }, [personId, session?.user.id, revision]);

  async function change(action: () => Promise<void>, message: string) {
    setBusy(true); setError(""); setSuccess("");
    try {
      await action();
      setSuccess(message); setRevision((old) => old + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Ошибка операции");
    } finally { setBusy(false); }
  }

  function createType(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId) return;
    void change(async () => {
      await request(
        `${root}/enterprises/${enterpriseId}/types`,
        { method: "POST", body: JSON.stringify({
          code: typeCode, name: typeName, kind,
          is_safety_critical: safety, requires_expiry: safety || expiryRequired,
        }) },
        session.csrf_token,
      );
      setTypeCode(""); setTypeName("");
    }, "Тип документа добавлен.");
  }

  function addRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId || !ruleType) return;
    void change(async () => {
      await request(
        `${root}/enterprises/${enterpriseId}/requirements`,
        { method: "POST", body: JSON.stringify({
          activity_code: ruleCode, type_id: ruleType,
        }) },
        session.csrf_token,
      );
      setRuleCode("");
    }, "Обязательное требование добавлено.");
  }

  function addRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId || !personId || !recordType) return;
    void change(async () => {
      await request(
        `${root}/enterprises/${enterpriseId}/records`,
        { method: "POST", body: JSON.stringify({
          person_id: personId, type_id: recordType,
          document_reference: reference, issuer, issued_on: issued,
          valid_from: validFrom,
          expires_on: expires || null,
        }) },
        session.csrf_token,
      );
      setReference(""); setIssuer(""); setExpires("");
    }, "Документ зарегистрирован и ожидает независимой проверки.");
  }

  function decision(record: Credential, target: "verified" | "rejected") {
    if (!session) return;
    const note = notes[record.id]?.trim() ?? "";
    if (note.length < 10) {
      setError("Для проверки документа требуется обоснование от 10 символов.");
      return;
    }
    void change(
      () => request(
        `${root}/records/${record.id}/review`,
        { method: "POST", body: JSON.stringify({ decision: target, note }) },
        session.csrf_token,
      ),
      target === "verified" ? "Документ отмечен как проверенный." : "Документ отклонён.",
    );
  }

  function revoke(record: Credential) {
    if (!session) return;
    const reason = notes[record.id]?.trim() ?? "";
    if (reason.length < 10) {
      setError("Для отзыва укажите причину не короче 10 символов.");
      return;
    }
    if (!window.confirm("Отозвать документ? Повторное утверждение невозможно.")) return;
    void change(
      () => request(
        `${root}/records/${record.id}/revoke`,
        { method: "POST", body: JSON.stringify({ reason }) },
        session.csrf_token,
      ),
      "Документ отозван. Для восстановления требуется новая запись.",
    );
  }

  function check(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!personId || !activity) return;
    setBusy(true); setError(""); setEligibility(null);
    const query = new URLSearchParams({ on: checkDate });
    request<Eligibility>(
      `${root}/persons/${personId}/eligibility/${encodeURIComponent(activity)}?${query}`,
    ).then(setEligibility)
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Ошибка проверки");
      })
      .finally(() => setBusy(false));
  }

  return (
    <section className="credential-panel" id="credentials" aria-labelledby="credential-title">
      <div className="section-heading">
        <div>
          <div className="eyebrow">CREDENTIALS · MANDATORY SAFETY GATES</div>
          <h2 id="credential-title">Квалификации, сертификаты и допуски</h2>
        </div>
        <span className="credential-flag">Проверка на сервере</span>
      </div>
      <p className="credential-intro">
        Учёт документов с независимой проверкой, сроками действия и отзывом.
        Отдельно от оценки технических навыков.
      </p>
      {!session && <p className="credential-empty">Войдите в систему для просмотра допусков.</p>}
      {session && (
        <>
          <div className="credential-controls">
            <label>Предприятие
              <select value={enterpriseId} onChange={(e) => setEnterpriseId(e.target.value)}>
                {enterprises.length === 0 && <option value="">Нет доступных предприятий</option>}
                {enterprises.map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </select>
            </label>
            <label>Специалист
              <select value={personId} onChange={(e) => setPersonId(e.target.value)}>
                <option value="">Выберите специалиста</option>
                {people.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.last_name} {item.first_name} · {item.employee_code}
                  </option>
                ))}
                {ownLink && ownLink.enterprise_id === enterpriseId &&
                  !people.some((p) => p.id === ownLink.person_id) && (
                    <option value={ownLink.person_id}>Моя карточка</option>
                  )}
              </select>
            </label>
          </div>
          {enterpriseId && (
            <>
              <div className="credential-overview">
                <div><strong>{types.length}</strong><span>Типов документов</span></div>
                <div><strong>{rules.length}</strong><span>Обязательных требований</span></div>
                <div><strong>{records.filter((r) => r.status === "verified").length}</strong>
                  <span>Проверенных записей</span></div>
                <div><strong>{records.filter((r) => r.status === "pending").length}</strong>
                  <span>На проверке</span></div>
              </div>
              <div className="credential-section">
                <h3>Требования для выполнения работ</h3>
                <div className="credential-rules">
                  {rules.map((rule) => (
                    <div key={rule.id}>
                      <strong>{rule.activity_code}</strong>
                      <span>{typeById.get(rule.type_id)?.name ?? "Документ"}</span>
                    </div>
                  ))}
                  {rules.length === 0 && <p className="credential-empty">
                    Требования не настроены. Проверка пригодности будет запрещающей.
                  </p>}
                </div>
              </div>
              {admin && (
                <div className="credential-config">
                  <h3>Настройка документов и обязательных требований</h3>
                  <details>
                    <summary>Создать тип документа</summary>
                    <form className="credential-form" onSubmit={createType}>
                      <label>Код
                        <input required maxLength={64} pattern="[A-Za-z0-9_.-]+"
                          value={typeCode} onChange={(e) => setTypeCode(e.target.value)} />
                      </label>
                      <label>Наименование
                        <input required maxLength={180}
                          value={typeName} onChange={(e) => setTypeName(e.target.value)} />
                      </label>
                      <label>Категория
                        <select value={kind} onChange={(e) => setKind(e.target.value)}>
                          <option value="permit">Производственный допуск</option>
                          <option value="certificate">Сертификат</option>
                          <option value="qualification">Квалификация</option>
                          <option value="training">Обучение</option>
                        </select>
                      </label>
                      <label className="credential-check">
                        <input type="checkbox" checked={safety}
                          onChange={(e) => setSafety(e.target.checked)} />
                        Критичный для безопасности
                      </label>
                      <label className="credential-check">
                        <input type="checkbox" checked={safety || expiryRequired}
                          disabled={safety}
                          onChange={(e) => setExpiryRequired(e.target.checked)} />
                        Обязательный срок окончания
                      </label>
                      <button type="submit" className="credential-button"
                        disabled={busy}>Добавить тип</button>
                    </form>
                  </details>
                  <details>
                    <summary>Добавить обязательный документ для вида работ</summary>
                    <form className="credential-form" onSubmit={addRule}>
                      <label>Код вида работ
                        <input required maxLength={64} pattern="[A-Za-z0-9_.-]+"
                          placeholder="robot-maintenance" value={ruleCode}
                          onChange={(e) => setRuleCode(e.target.value)} />
                      </label>
                      <label>Обязательный тип документа
                        <select required value={ruleType}
                          onChange={(e) => setRuleType(e.target.value)}>
                          <option value="">Выберите</option>
                          {types.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                      <button type="submit" className="credential-button"
                        disabled={busy}>Добавить обязательное правило</button>
                    </form>
                    <p className="credential-hint">
                      Все документы в требованиях для одного вида работ обязательны одновременно.
                      Для безопасного изменения политики требуется отдельный процесс ревизии.
                    </p>
                  </details>
                </div>
              )}
              {personId && (
                <>
                  <div className="credential-section">
                    <h3>Документы выбранного специалиста</h3>
                    <div className="credential-list">
                      {records.map((record) => {
                        const label = typeById.get(record.type_id)?.name ?? "Документ";
                        const expired = record.expires_on && record.expires_on < localDate();
                        const notStarted = record.valid_from > localDate();
                        const statusLabel = record.status === "pending" ? "Ожидает проверки" :
                          record.status === "verified"
                            ? expired ? "Срок истёк" :
                              notStarted ? "Ещё не действует" : "Проверен"
                            : record.status === "revoked" ? "Отозван" : "Отклонён";
                        return (
                          <article className="credential-card" key={record.id}>
                            <div className="credential-card-head">
                              <strong>{label}</strong>
                              <span className={`credential-state ${record.status} ${expired ? "is-expired" : notStarted ? "is-future" : ""}`}>
                                {statusLabel}
                              </span>
                            </div>
                            <p>№ {record.document_reference} · {record.issuer}</p>
                            <p>Выдан: {record.issued_on} · действует: {record.valid_from} —
                              {record.expires_on ?? "без даты окончания"}</p>
                            {record.review_note && <p>Решение: {record.review_note}</p>}
                            {record.revoke_reason && <p>Отзыв: {record.revoke_reason}</p>}
                            {((reviewer && record.status === "pending" &&
                                record.submitted_by !== session.user.id) ||
                              (admin && record.status === "verified")) && (
                              <div className="credential-review">
                                <label>Обоснование проверки / отзыва
                                  <textarea minLength={10} maxLength={1200}
                                    value={notes[record.id] ?? ""}
                                    onChange={(e) => setNotes((old) => ({
                                      ...old, [record.id]: e.target.value,
                                    }))} />
                                </label>
                                {reviewer && record.status === "pending" &&
                                  record.submitted_by !== session.user.id && (
                                    <>
                                      <button type="button" className="credential-button"
                                        disabled={busy}
                                        onClick={() => decision(record, "verified")}>
                                        Подтвердить
                                      </button>
                                      <button type="button" className="credential-button secondary"
                                        disabled={busy}
                                        onClick={() => decision(record, "rejected")}>
                                        Отклонить
                                      </button>
                                    </>
                                  )}
                                {admin && record.status === "verified" && (
                                  <button type="button" className="credential-button danger"
                                    disabled={busy} onClick={() => revoke(record)}>
                                    Отозвать
                                  </button>
                                )}
                              </div>
                            )}
                          </article>
                        );
                      })}
                      {records.length === 0 && <p className="credential-empty">
                        Документы специалиста ещё не зарегистрированы.
                      </p>}
                    </div>
                  </div>
                  {admin && (
                    <details className="credential-editor">
                      <summary>Зарегистрировать новый документ</summary>
                      <form className="credential-form" onSubmit={addRecord}>
                        <label>Тип документа
                          <select required value={recordType}
                            onChange={(e) => setRecordType(e.target.value)}>
                            <option value="">Выберите</option>
                            {types.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                        </label>
                        <label>Номер документа
                          <input required maxLength={180} value={reference}
                            onChange={(e) => setReference(e.target.value)} />
                        </label>
                        <label>Организация, выдавшая документ
                          <input required maxLength={180} value={issuer}
                            onChange={(e) => setIssuer(e.target.value)} />
                        </label>
                        <label>Дата выдачи
                          <input required type="date" value={issued}
                            onChange={(e) => setIssued(e.target.value)} />
                        </label>
                        <label>Начало действия
                          <input required type="date" value={validFrom}
                            onChange={(e) => setValidFrom(e.target.value)} />
                        </label>
                        <label>Окончание действия
                          <input type="date" value={expires}
                            required={activeRecordType?.requires_expiry ?? false}
                            onChange={(e) => setExpires(e.target.value)} />
                        </label>
                        <button type="submit" className="credential-button"
                          disabled={busy}>Зарегистрировать</button>
                      </form>
                      <p className="credential-hint">
                        Запись до независимой проверки не даёт допуска к работам.
                        Оригинал документа проверяется вне приложения.
                      </p>
                    </details>
                  )}
                  <div className="credential-eligibility">
                    <h3>Проверка допуска к конкретному виду работ</h3>
                    <form className="credential-form" onSubmit={check}>
                      <label>Код вида работ
                        <input required pattern="[A-Za-z0-9_.-]+" maxLength={64}
                          placeholder="robot-maintenance" value={activity}
                          onChange={(e) => setActivity(e.target.value)} />
                      </label>
                      <label>Дата выполнения
                        <input type="date" required value={checkDate}
                          onChange={(e) => setCheckDate(e.target.value)} />
                      </label>
                      <button type="submit" className="credential-button" disabled={busy}>
                        Проверить допуск
                      </button>
                    </form>
                    {eligibility && (
                      <div className={`credential-result ${eligibility.eligible ? "allowed" : "blocked"}`}
                        role="status">
                        <strong>{eligibility.eligible
                          ? "Все заданные обязательные документы действуют"
                          : "Допуск к выполнению работ заблокирован"}</strong>
                        <p>{eligibility.activity_code} · на дату {eligibility.checked_on}</p>
                        {eligibility.blockers.map((blocker, index) => (
                          <p key={index} className="credential-blocker">
                            {blockerText[blocker.code] ?? blocker.message}
                            {blocker.type_id && ` — ${typeById.get(blocker.type_id)?.name ?? "Тип"}`}
                          </p>
                        ))}
                        {eligibility.eligible && <p>
                          Найдено проверенных обязательных документов:
                          {" "}{eligibility.valid_credentials.length}.
                        </p>}
                      </div>
                    )}
                    <p className="credential-hint">
                      Это диагностическая проверка по учётным сведениям, а не юридическое
                      разрешение. Назначение исполнителей пока не выполняется.
                    </p>
                  </div>
                </>
              )}
            </>
          )}
        </>
      )}
      {error && <p role="alert" className="credential-error">{error}</p>}
      {success && <p role="status" className="credential-success">{success}</p>}
    </section>
  );
}
