import { useEffect, useState, type FormEvent } from "react";

type Window = {
  id: string; asset_id: string; starts_at: string; ends_at: string;
  reason: string; cancelled_at: string | null; cancel_reason: string | null;
};
type Props = {
  assetId: string; admin: boolean; csrfToken?: string; onChanged: () => void;
};

const url = "/api/v1/equipment/assets/";
const display = (iso: string) => new Date(iso).toLocaleString("ru-RU");
const localInput = (date: Date) => {
  const pad = (n: number) => String(n).padStart(2, "0");
  return String(date.getFullYear()) + "-" + pad(date.getMonth() + 1)
    + "-" + pad(date.getDate()) + "T"
    + pad(date.getHours()) + ":" + pad(date.getMinutes());
};

async function api<T>(path: string, method: "GET" | "POST", csrf?: string, body?: object) {
  const response = await fetch(path, {
    credentials: "same-origin", method,
    headers: {
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    let reason = "";
    try {
      const json = await response.json() as { detail?: unknown };
      reason = typeof json.detail === "string" ? json.detail : JSON.stringify(json.detail);
    } catch { /* Keep status. */ }
    throw new Error("HTTP " + response.status + (reason ? ": " + reason : ""));
  }
  return await response.json() as T;
}

export default function EquipmentDowntimePanel({
  assetId, admin, csrfToken, onChanged,
}: Props) {
  const [windows, setWindows] = useState<Window[]>([]);
  const [starts, setStarts] = useState(localInput(new Date(Date.now() + 86400000)));
  const [ends, setEnds] = useState(localInput(new Date(Date.now() + 90000000)));
  const [reason, setReason] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    setError("");
    api<Window[]>(url + assetId + "/downtime", "GET")
      .then(rows => { if (active) setWindows(rows); })
      .catch((cause: unknown) => {
        if (active) setError(
          cause instanceof Error ? cause.message : "Ошибка чтения графика",
        );
      });
    return () => { active = false; };
  }, [assetId, revision]);

  async function change(path: string, body: object, notice: string) {
    if (!csrfToken || !admin) return;
    setBusy(true); setError(""); setSuccess("");
    try {
      await api<Window>(path, "POST", csrfToken, body);
      setSuccess(notice);
      setRevision(x => x + 1);
      onChanged();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Операция отклонена");
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!starts || !ends) return;
    const start = new Date(starts), end = new Date(ends);
    if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf())) {
      setError("Введите корректное время");
      return;
    }
    void change(url + assetId + "/downtime", {
      starts_at: start.toISOString(),
      ends_at: end.toISOString(),
      reason,
    }, "Окно обслуживания зарегистрировано в HRMS.");
  }

  return (
    <div className="equipment-downtime" aria-label="График недоступности оборудования">
      <h4>График обслуживания и недоступности</h4>
      <p>Время вводится по часовому поясу браузера. Программная блокировка
        действует при пересечении интервала обслуживания с периодом наряда.</p>
      {error && <p role="alert" className="equipment-error">{error}</p>}
      {success && <p role="status" className="equipment-notice">{success}</p>}
      {admin && (
        <details className="equipment-downtime-editor">
          <summary>Запланировать окно недоступности</summary>
          <form className="equipment-downtime-form" onSubmit={submit}>
            <label>Начало обслуживания
              <input type="datetime-local" required value={starts}
                onChange={e => setStarts(e.target.value)} />
            </label>
            <label>Окончание обслуживания
              <input type="datetime-local" required value={ends}
                onChange={e => setEnds(e.target.value)} />
            </label>
            <label>Причина / задание на обслуживание
              <textarea required minLength={10} maxLength={400}
                value={reason} onChange={e => setReason(e.target.value)} />
            </label>
            <button type="submit" disabled={busy || reason.trim().length < 10}>
              Зарегистрировать обслуживание
            </button>
          </form>
        </details>
      )}
      <div className="equipment-downtime-list">
        {windows.map(window => (
          <article key={window.id} className="equipment-downtime-row">
            <strong>{display(window.starts_at)} — {display(window.ends_at)}</strong>
            <p>{window.reason}</p>
            <small>{window.cancelled_at
              ? "Отменено: " + display(window.cancelled_at)
              : "Запланировано / действует"}
              {window.cancel_reason ? " · " + window.cancel_reason : ""}
            </small>
            {admin && !window.cancelled_at && new Date(window.ends_at) > new Date() && (
              <div className="equipment-downtime-cancel">
                <label>Причина отмены окна
                  <input maxLength={400} minLength={10}
                    value={cancelReason} onChange={e => setCancelReason(e.target.value)} />
                </label>
                <button type="button" disabled={busy || cancelReason.trim().length < 10}
                  onClick={() => void change(
                    url + assetId + "/downtime/" + window.id + "/cancel",
                    { reason: cancelReason },
                    "Обслуживание отменено; связанные наряды автоматически не возобновляются.",
                  )}>Отменить окно</button>
              </div>
            )}
          </article>
        ))}
        {windows.length === 0 && <p>Запланированных или прошедших окон обслуживания нет.</p>}
      </div>
      <p>Статусы и окна обслуживания в HRMS не подтверждают фактическую остановку,
        изоляцию энергии или безопасное состояние промышленного оборудования.</p>
    </div>
  );
}
