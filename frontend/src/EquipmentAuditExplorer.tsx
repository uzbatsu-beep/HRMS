import { useEffect, useState, type FormEvent } from "react";

type AuditRow = {
  id: string;
  action: string;
  actor_id: string;
  actor_username: string;
  subject_id: string;
  created_at: string;
};
type AuditPage = {
  enterprise_id: string;
  items: AuditRow[];
  next_cursor: string | null;
  has_more: boolean;
  detail_payloads_included: false;
};
type Filters = { action: string; subject: string; actor: string;
  since: string; until: string };

const labels: Record<string, string> = {
  "asset.created": "Оборудование зарегистрировано",
  "asset.state_changed": "Состояние оборудования изменено",
  "asset.credential_required": "Добавлен обязательный допуск",
  "asset.skill_required": "Добавлена обязательная компетенция",
  "asset.downtime_scheduled": "Зарегистрировано обслуживание",
  "asset.downtime_cancelled": "Обслуживание отменено",
  "work.equipment_linked": "Оборудование связано с нарядом",
  "permit.prepared": "Разрешение подготовлено",
  "permit.submitted": "Разрешение направлено",
  "permit.approved": "Разрешение согласовано",
  "permit.revoked": "Разрешение отозвано",
};
const empty: Filters = { action: "", subject: "", actor: "", since: "", until: "" };
const format = (value: string) => new Date(value).toLocaleString("ru-RU");
const iso = (value: string) => value ? new Date(value).toISOString() : "";

export default function EquipmentAuditExplorer({ enterpriseId }: { enterpriseId: string }) {
  const [draft, setDraft] = useState<Filters>(empty);
  const [filters, setFilters] = useState<Filters>(empty);
  const [stack, setStack] = useState<(string | null)[]>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState<AuditPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ limit: "20" });
    if (filters.action) params.set("action", filters.action);
    if (filters.subject) params.set("subject_id", filters.subject.trim());
    if (filters.actor) params.set("actor_id", filters.actor.trim());
    if (filters.since) params.set("since", iso(filters.since));
    if (filters.until) params.set("until", iso(filters.until));
    if (stack[pageIndex]) params.set("cursor", stack[pageIndex]!);
    setLoading(true); setError(""); setPage(null);
    fetch(
      "/api/v1/equipment/enterprises/" + enterpriseId +
      "/audit/explorer?" + params.toString(),
      { credentials: "same-origin", signal: controller.signal },
    ).then(async response => {
      if (!response.ok) {
        const raw = await response.json() as { detail?: unknown };
        throw new Error("HTTP " + response.status + ": " + JSON.stringify(raw.detail));
      }
      return await response.json() as AuditPage;
    }).then(result => {
      if (!controller.signal.aborted) {
        if (result.detail_payloads_included !== false)
          throw new Error("Неожиданный формат журнала");
        setPage(result);
      }
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(
        cause instanceof Error ? cause.message : "Ошибка чтения журнала",
      );
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [enterpriseId, filters, stack, pageIndex, revision]);

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPageIndex(0); setStack([null]); setFilters({ ...draft });
    setRevision(n => n + 1);
  }
  function next() {
    if (!page?.next_cursor) return;
    setStack(prev => [...prev.slice(0, pageIndex + 1), page.next_cursor]);
    setPageIndex(prev => prev + 1);
  }
  function previous() {
    if (pageIndex > 0) setPageIndex(prev => prev - 1);
  }
  return (
    <section className="equipment-audit-explorer" aria-label="Журнал событий оборудования">
      <div className="equipment-audit-heading">
        <div>
          <h3>Журнал событий оборудования</h3>
          <p>Доступен администраторам. Выводятся только метаданные:
            дата, тип операции, исполнитель и ID объекта. Содержимое документов,
            причины и произвольные поля журнала сюда не передаются.</p>
        </div>
        <button type="button" onClick={() => setRevision(x => x + 1)}
          disabled={loading}>Обновить журнал</button>
      </div>
      <form className="equipment-audit-filters" onSubmit={apply}>
        <label>Тип события
          <select value={draft.action} onChange={e => setDraft(x => ({
            ...x, action: e.target.value,
          }))}>
            <option value="">Все события</option>
            {Object.entries(labels).map(([code, label]) => (
              <option value={code} key={code}>{label}</option>
            ))}
          </select>
        </label>
        <label>ID объекта события
          <input value={draft.subject} placeholder="UUID (необязательно)"
            onChange={e => setDraft(x => ({ ...x, subject: e.target.value }))} />
        </label>
        <label>ID исполнителя
          <input value={draft.actor} placeholder="UUID (необязательно)"
            onChange={e => setDraft(x => ({ ...x, actor: e.target.value }))} />
        </label>
        <label>От (локальное время)
          <input type="datetime-local" value={draft.since}
            onChange={e => setDraft(x => ({ ...x, since: e.target.value }))} />
        </label>
        <label>До (локальное время)
          <input type="datetime-local" value={draft.until}
            onChange={e => setDraft(x => ({ ...x, until: e.target.value }))} />
        </label>
        <button type="submit">Применить фильтр</button>
        <button type="button" onClick={() => {
          setDraft(empty); setFilters(empty);
          setStack([null]); setPageIndex(0); setRevision(x => x + 1);
        }}>Сбросить</button>
      </form>
      {loading && <p role="status">Загрузка истории…</p>}
      {error && <p role="alert" className="equipment-error">{error}</p>}
      {page && (
        <>
          <div className="equipment-audit-list">
            {page.items.map(event => (
              <article key={event.id} className="equipment-audit-row">
                <strong>{labels[event.action] ?? event.action}</strong>
                <small>{format(event.created_at)} · {event.actor_username}</small>
                <small title={event.subject_id}>Объект: {event.subject_id}</small>
                <small title={event.id}>Событие: {event.id}</small>
              </article>
            ))}
            {page.items.length === 0 && <p>По выбранным фильтрам событий нет.</p>}
          </div>
          <div className="equipment-audit-pages">
            <button type="button" onClick={previous} disabled={pageIndex === 0 || loading}>
              Назад
            </button>
            <span>Страница {pageIndex + 1} · записей: {page.items.length}</span>
            <button type="button" onClick={next}
              disabled={!page.has_more || !page.next_cursor || loading}>Далее</button>
          </div>
        </>
      )}
      <p className="workspace-warning">Этот журнал — представление событий
        приложения, а не независимое доказательство действий на оборудовании
        или соответствия нормативным требованиям.</p>
    </section>
  );
}
