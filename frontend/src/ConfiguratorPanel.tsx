import { useEffect, useState, type FormEvent } from "react";
import { useWorkspace } from "./WorkspaceContext";

export type CustomField = {
  code: string; label: string;
  kind: "text" | "integer" | "boolean" | "choice";
  required: boolean;
  max_length: number | null;
  min_value: number | null;
  max_value: number | null;
  options: string[];
};
type Version = {
  id: string; version: number;
  status: "draft" | "validated" | "approved" | "published";
  document: { fields: CustomField[] };
  created_by: string; approved_by: string | null;
  effective_on: string | null; created_at: string;
};
const emptyField = (): CustomField => ({
  code: "", label: "", kind: "text", required: false,
  max_length: 120, min_value: null, max_value: null, options: [],
});
const statuses: Record<Version["status"], string> = {
  draft: "Черновик", validated: "Проверена", approved: "Согласована",
  published: "Опубликована",
};

async function api<T>(url: string, csrf?: string, method = "GET", data?: object): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    method,
    headers: {
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...(data !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    ...(data !== undefined ? { body: JSON.stringify(data) } : {}),
  });
  if (!response.ok) {
    let detail: unknown;
    try { detail = (await response.json() as { detail?: unknown }).detail; }
    catch { detail = null; }
    throw new Error("HTTP " + response.status +
      (typeof detail === "string" ? ": " + detail : ""));
  }
  return await response.json() as T;
}

export default function ConfiguratorPanel() {
  const { session, enterpriseId, enterprises } = useWorkspace();
  const admin = session?.user.role === "admin";
  const [versions, setVersions] = useState<Version[]>([]);
  const [active, setActive] = useState<Version | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [fields, setFields] = useState<CustomField[]>([]);
  const [effectiveDate, setEffectiveDate] = useState(
    () => new Date().toISOString().slice(0, 10),
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [noticeScope, setNoticeScope] = useState("");
  const scopeKey = (session?.user.id ?? "") + ":" + enterpriseId;
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    setVersions([]); setActive(null); setSelectedId(""); setFields([]);
    setError("");
    if (!session || !enterpriseId) { setLoading(false); return; }
    let live = true;
    setLoading(true);
    const root = "/api/v1/configuration/enterprises/" + enterpriseId;
    const run = async () => {
      try {
        const published = await api<Version | null>(root + "/active");
        const all = admin ? await api<Version[]>(root + "/versions") : [];
        if (!live) return;
        setActive(published);
        setVersions(all);
        setSelectedId((old) => all.some((item) => item.id === old) ? old : all[0]?.id ?? "");
        setFields(all[0]?.document.fields ?? published?.document.fields ?? []);
      } catch (reason: unknown) {
        if (live) setError(reason instanceof Error ? reason.message : "Ошибка API");
      } finally {
        if (live) setLoading(false);
      }
    };
    void run();
    return () => { live = false; };
  }, [session?.user.id, session?.user.role, enterpriseId, admin, refresh]);

  const selected = versions.find((item) => item.id === selectedId);
  const editable = admin && (!selected || selected.status === "draft");
  const root = "/api/v1/configuration";

  function changeField(index: number, patch: Partial<CustomField>) {
    setFields((old) => old.map((field, i) => i === index ? { ...field, ...patch } : field));
  }

  async function action(task: () => Promise<Version>, message: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await task();
      setNotice(message + " Версия " + result.version + ".");
      setNoticeScope(scopeKey);
      setRefresh((value) => value + 1);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Ошибка операции");
    } finally { setBusy(false); }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !enterpriseId || !admin) return;
    const data = { document: { fields } };
    void action(
      () => selected
        ? api<Version>(root + "/versions/" + selected.id,
          session.csrf_token, "PUT", data)
        : api<Version>(
          root + "/enterprises/" + enterpriseId + "/versions",
          session.csrf_token, "POST", data),
      selected ? "Черновик сохранён." : "Новый черновик создан.",
    );
  }

  function transition(step: "validate" | "approve" | "publish") {
    if (!selected || !session || !admin) return;
    const message = {
      validate: "Конфигурация прошла валидацию.",
      approve: "Конфигурация согласована.",
      publish: "Конфигурация опубликована.",
    }[step];
    void action(
      () => api<Version>(
        root + "/versions/" + selected.id + "/" + step,
        session.csrf_token, "POST",
        step === "publish" ? { effective_on: effectiveDate } : undefined,
      ), message,
    );
  }

  if (!session) return <section className="config-panel">Для работы с конфигуратором войдите.</section>;
  if (!enterpriseId) return <section className="config-panel">Выберите предприятие в правой панели.</section>;
  const company = enterprises.find((row) => row.id === enterpriseId);
  return (
    <section className="config-panel" id="configuration">
      <div className="config-heading">
        <div>
          <div className="eyebrow">GOVERNED CONFIGURATION</div>
          <h2>Конфигуратор дополнительных полей</h2>
          <p>{company?.name ?? "Предприятие"} · Только информационные поля сотрудника.
            Допуски, роли, safety gates и жизненный цикл нарядов не конфигурируются.</p>
        </div>
        <button type="button" disabled={busy} onClick={() => setRefresh((v) => v + 1)}>
          Обновить
        </button>
      </div>
      {loading && <p role="status">Загрузка конфигурации…</p>}
      {error && <p role="alert" className="config-error">{error}</p>}
      {noticeScope === scopeKey && notice &&
        <p role="status" className="config-notice">{notice}</p>}
      {!loading && (
        <>
          <div className="config-published">
            <strong>Действующая версия:</strong>
            {active ? " v" + active.version +
              " (с " + active.effective_on + "), полей: " + active.document.fields.length
              : " ещё не опубликована"}
          </div>
          {!admin && (
            <div className="config-readonly">
              <h3>Опубликованные поля</h3>
              {active?.document.fields.map((field) => (
                <p key={field.code}>{field.label} · {field.kind}
                  {field.required ? " · обязательное" : ""}</p>
              )) ?? <p>Дополнительных полей нет.</p>}
              <p>Изменение конфигураций доступно только администраторам.</p>
            </div>
          )}
          {admin && (
            <>
              <div className="config-toolbar">
                <label>Версия
                  <select aria-label="Версия конфигурации"
                    value={selectedId}
                    onChange={(event) => {
                      const id = event.target.value;
                      setSelectedId(id);
                      const version = versions.find((row) => row.id === id);
                      setFields(version?.document.fields ?? active?.document.fields ?? []);
                    }}>
                    <option value="">Новая версия</option>
                    {versions.map((row) => (
                      <option key={row.id} value={row.id}>
                        v{row.version} — {statuses[row.status]}
                        {row.effective_on ? " · " + row.effective_on : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="button" disabled={busy}
                  onClick={() => {
                    setSelectedId("");
                    setFields(active?.document.fields ?? []);
                  }}>
                  Новый черновик на основе действующей
                </button>
              </div>
              <form onSubmit={submit} className="config-form">
                <h3>Состав полей {selected ? "v" + selected.version : "новой версии"}</h3>
                <p>Разрешены только декларативные проверки ввода. Коды уникальны;
                  после валидации редактор блокируется.</p>
                {fields.map((field, index) => (
                  <fieldset className="config-field" key={index} disabled={!editable || busy}>
                    <legend>Поле {index + 1}</legend>
                    <label>Код
                      <input value={field.code} pattern="[a-z][a-z0-9_]*"
                        minLength={2} maxLength={32} required
                        onChange={(event) => changeField(index, { code: event.target.value })} />
                    </label>
                    <label>Название
                      <input value={field.label} maxLength={80} required
                        onChange={(event) => changeField(index, { label: event.target.value })} />
                    </label>
                    <label>Тип
                      <select value={field.kind} onChange={(event) => {
                        const kind = event.target.value as CustomField["kind"];
                        changeField(index, {
                          kind, max_length: kind === "text" ? 120 : null,
                          options: kind === "choice" ? ["Вариант А", "Вариант Б"] : [],
                          min_value: null, max_value: null,
                        });
                      }}>
                        <option value="text">Текст</option>
                        <option value="integer">Целое число</option>
                        <option value="boolean">Да / нет</option>
                        <option value="choice">Выбор из списка</option>
                      </select>
                    </label>
                    <label className="config-checkbox">
                      <input type="checkbox" checked={field.required}
                        onChange={(event) => changeField(index, { required: event.target.checked })} />
                      Обязательное
                    </label>
                    {field.kind === "text" && (
                      <label>Максимум символов
                        <input type="number" min={1} max={400}
                          value={field.max_length ?? 120}
                          onChange={(event) => changeField(index, {
                            max_length: Number(event.target.value),
                          })} />
                      </label>
                    )}
                    {field.kind === "integer" && (
                      <>
                        <label>Минимум
                          <input type="number" value={field.min_value ?? ""}
                            onChange={(event) => changeField(index, {
                              min_value: event.target.value === "" ? null : Number(event.target.value),
                            })} />
                        </label>
                        <label>Максимум
                          <input type="number" value={field.max_value ?? ""}
                            onChange={(event) => changeField(index, {
                              max_value: event.target.value === "" ? null : Number(event.target.value),
                            })} />
                        </label>
                      </>
                    )}
                    {field.kind === "choice" && (
                      <label>Значения через запятую
                        <input value={field.options.join(", ")}
                          onChange={(event) => changeField(index, {
                            options: event.target.value.split(",").map((x) => x.trim()),
                          })} />
                      </label>
                    )}
                    <button type="button" onClick={() =>
                      setFields((old) => old.filter((_, i) => i !== index))
                    }>Удалить поле</button>
                  </fieldset>
                ))}
                {editable && (
                  <div className="config-actions">
                    <button type="button" disabled={busy || fields.length >= 24}
                      onClick={() => setFields((old) => [...old, emptyField()])}>
                      Добавить поле
                    </button>
                    <button type="submit" disabled={busy}>
                      {selected ? "Сохранить черновик" : "Создать черновик"}
                    </button>
                  </div>
                )}
              </form>
              {selected && (
                <div className="config-workflow">
                  <h3>Согласование и публикация v{selected.version}</h3>
                  <p>Статус: <strong>{statuses[selected.status]}</strong>. Создатель:{" "}
                    <code>{selected.created_by.slice(0, 8)}</code>.
                    Проверка и согласование выполняются через серверные переходы.</p>
                  {selected.status === "draft" && (
                    <button disabled={busy} onClick={() => transition("validate")}>
                      Проверить схему
                    </button>
                  )}
                  {selected.status === "validated" && (
                    <button disabled={busy || selected.created_by === session.user.id}
                      onClick={() => transition("approve")}>
                      Согласовать (другой администратор)
                    </button>
                  )}
                  {selected.status === "approved" && (
                    <div className="config-actions">
                      <label>Дата вступления в силу (UTC)
                        <input type="date" value={effectiveDate}
                          onChange={(event) => setEffectiveDate(event.target.value)} />
                      </label>
                      <button disabled={busy} onClick={() => transition("publish")}>
                        Опубликовать версию
                      </button>
                    </div>
                  )}
                  {selected.status === "published" &&
                    <p>Версия опубликована и неизменяема. Для изменений создайте новую.</p>}
                </div>
              )}
            </>
          )}
          <p className="workspace-warning">
            Конфигурации предназначены только для разработки на синтетических данных.
            Управляемые поля не подтверждают квалификации и допуски.
          </p>
        </>
      )}
    </section>
  );
}
