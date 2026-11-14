import { useEffect, useState } from "react";

type Unit = { id: string; name: string };
type Actor = { id: string; username: string; role: string };
type Grant = { id: string; user_id: string; unit_id: string; code: string };

const rights: Record<string, string> = {
  "equipment.policy.read": "Оборудование · Просмотр согласований",
  "equipment.policy.propose": "Оборудование · Создание заявок",
  "equipment.policy.review": "Оборудование · Независимое согласование",
  "competence.assessment.review": "Компетенции · Проверка оценки",
  "credentials.record.review": "Допуски · Проверка документа",
};

export default function OrganizationPermissionMatrix({
  users, units, csrfToken,
}: { users: Actor[]; units: Unit[]; csrfToken?: string }) {
  const [unitId, setUnitId] = useState("");
  const [userId, setUserId] = useState("");
  const [code, setCode] = useState("competence.assessment.review");
  const [grants, setGrants] = useState<Grant[]>([]);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const currentUnitId = units.some(unit => unit.id === unitId)
    ? unitId : (units[0]?.id ?? "");

  useEffect(() => {
    let mounted = true;
    setGrants([]); setError("");
    if (!currentUnitId) return;
    fetch("/api/v1/org/permissions?unit_id=" + currentUnitId,
      { credentials: "same-origin" }).then(async response => {
      if (!response.ok) throw Error("HTTP " + response.status);
      return await response.json() as Grant[];
    }).then(data => { if (mounted) setGrants(data); })
      .catch((cause: unknown) => {
        if (mounted) setError(
          cause instanceof Error ? cause.message : "Не удалось получить полномочия",
        );
      });
    return () => { mounted = false; };
  }, [currentUnitId, revision]);

  async function change(url: string, method: "POST" | "DELETE",
    payload: object | null, message: string) {
    if (!csrfToken) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(url, {
        credentials: "same-origin", method,
        headers: {
          "X-CSRF-Token": csrfToken,
          ...(payload !== null ? { "Content-Type": "application/json" } : {}),
        },
        ...(payload !== null ? { body: JSON.stringify(payload) } : {}),
      });
      if (!response.ok) {
        let detail = "";
        try {
          const body = await response.json() as { detail?: string };
          detail = body.detail ?? "";
        } catch { /* HTTP status is enough. */ }
        throw Error("HTTP " + response.status + (detail ? " — " + detail : ""));
      }
      setRevision(x => x + 1); setNotice(message);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Ошибка изменения прав");
    } finally { setBusy(false); }
  }
  return (
    <div className="org-permission-matrix" aria-label="Матрица операций подразделения">
      <div className="org-section-title">
        <h3>Операционные полномочия</h3>
        <span>Только администратор</span>
      </div>
      <p>Право действует только в выбранном подразделении и при наличии
        организационного доступа. Разрешение на проверку не даёт права
        оформлять собственную оценку или подтверждать собственный документ.</p>
      <div className="org-form">
        <label>Подразделение для полномочий
          <select value={currentUnitId} onChange={e => setUnitId(e.target.value)}>
            {units.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </label>
        <label>Пользователь для полномочий
          <select value={userId} onChange={e => setUserId(e.target.value)}>
            <option value="">Выберите пользователя</option>
            {users.filter(u => u.role !== "admin").map(u =>
              <option key={u.id} value={u.id}>{u.username} ({u.role})</option>)}
          </select>
        </label>
        <label>Операция
          <select value={code} onChange={e => setCode(e.target.value)}>
            {Object.entries(rights).map(([key, label]) =>
              <option key={key} value={key}>{label}</option>)}
          </select>
        </label>
        <button type="button" className="org-button" disabled={busy || !userId ||
          !currentUnitId} onClick={() => void change(
          "/api/v1/org/permissions", "POST",
          { user_id: userId, unit_id: currentUnitId, code },
          "Полномочие выдано. Организационная область доступа настраивается отдельно.",
        )}>Выдать полномочие</button>
      </div>
      {error && <p className="org-error" role="alert">{error}</p>}
      {notice && <p className="org-success" role="status">{notice}</p>}
      <div className="org-scopes">
        {grants.map(grant => (
          <div key={grant.id} className="org-scope-row">
            <span><strong>{users.find(x => x.id === grant.user_id)?.username
              ?? "Пользователь"}</strong> · {rights[grant.code] ?? grant.code}</span>
            <button type="button" className="org-button org-button-muted"
              disabled={busy} onClick={() => void change(
                "/api/v1/org/permissions/" + grant.id, "DELETE", null,
                "Полномочие отозвано. Повторный вход не требуется.",
              )}>Отозвать</button>
          </div>
        ))}
        {grants.length === 0 && <p>В этом подразделении полномочий нет.</p>}
      </div>
    </div>
  );
}
