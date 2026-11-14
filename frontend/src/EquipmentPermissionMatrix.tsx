import { useEffect, useState } from "react";

type Actor = { id: string; username: string; role: string; is_active: boolean };
type Grant = { id: string; user_id: string; unit_id: string; code: string };
type Scope = { id: string; user_id: string; unit_id: string; include_descendants: boolean };
const names: Record<string, string> = {
  "equipment.policy.read": "Просмотр заявок и истории",
  "equipment.policy.propose": "Создание заявок",
  "equipment.policy.review": "Независимое согласование",
};
const codes = Object.keys(names);

export default function EquipmentPermissionMatrix({
  unitId, csrfToken,
}: { unitId: string; csrfToken?: string }) {
  const [users, setUsers] = useState<Actor[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [scopes, setScopes] = useState<Scope[]>([]);
  const [actorId, setActorId] = useState("");
  const [code, setCode] = useState(codes[0]);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    setError("");
    Promise.all([
      fetch("/api/v1/auth/users", { credentials: "same-origin" }),
      fetch("/api/v1/org/permissions?unit_id=" + unitId,
        { credentials: "same-origin" }),
      fetch("/api/v1/org/scopes", { credentials: "same-origin" }),
    ]).then(async responses => {
      if (responses.some(r => !r.ok)) throw Error("Не удалось загрузить матрицу");
      return await Promise.all(responses.map(r => r.json())) as
        [Actor[], Grant[], Scope[]];
    }).then(([people, rights, units]) => {
      if (!active) return;
      setUsers(people.filter(x => x.is_active && x.role !== "admin"));
      setGrants(rights);
      setScopes(units);
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Ошибка прав");
    });
    return () => { active = false; };
  }, [unitId, revision]);

  async function change(url: string, method: "POST" | "DELETE",
    body: object | undefined, message: string) {
    if (!csrfToken) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(url, {
        method, credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken, ...(body
          ? { "Content-Type": "application/json" } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      setRevision(x => x + 1);
      setNotice(message);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Ошибка изменения прав");
    } finally { setBusy(false); }
  }

  const selected = users.find(x => x.id === actorId);
  const exactScope = scopes.some(x => x.user_id === actorId && x.unit_id === unitId);

  return (
    <section className="equipment-permission-matrix"
      aria-label="Матрица полномочий оборудования">
      <h4>Матрица полномочий подразделения</h4>
      <p>Гранты действуют только в выбранном подразделении и только при
        наличии организационного доступа. Они не дают прав менять станок,
        управлять пользователями или утверждать собственные заявки.</p>
      {error && <p className="equipment-error" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="equipment-actions">
        <label>Сотрудник системы
          <select value={actorId} onChange={e => setActorId(e.target.value)}>
            <option value="">Выберите пользователя</option>
            {users.map(x => <option key={x.id} value={x.id}>
              {x.username} ({x.role})</option>)}
          </select>
        </label>
        <label>Разрешённая операция
          <select value={code} onChange={e => setCode(e.target.value)}>
            {codes.map(x => <option value={x} key={x}>{names[x]}</option>)}
          </select>
        </label>
        <button type="button" disabled={busy || !actorId} onClick={() =>
          void change("/api/v1/org/permissions", "POST",
            { user_id: actorId, unit_id: unitId, code },
            "Полномочие выдано (действует только совместно с организационным доступом).",
          )}>Выдать полномочие</button>
      </div>
      {selected && !exactScope && (
        <p>Проверьте организационный доступ пользователя к подразделению.
          Доступ может быть унаследован от родительского подразделения.
          Для точного доступа к этому подразделению можно выдать отдельный грант.</p>
      )}
      {selected && !exactScope && (
        <button type="button" disabled={busy} onClick={() => void change(
          "/api/v1/org/scopes", "POST", {
            user_id: actorId, unit_id: unitId, include_descendants: false,
          }, "Выдан доступ к этому подразделению без наследования.",
        )}>Выдать доступ к подразделению</button>
      )}
      <div className="equipment-permission-list">
        {grants.map(grant => (
          <div key={grant.id}>
            <span>{users.find(x => x.id === grant.user_id)?.username ?? grant.user_id}
              {" · "}{names[grant.code] ?? grant.code}</span>
            <button type="button" disabled={busy} onClick={() => void change(
              "/api/v1/org/permissions/" + grant.id, "DELETE", undefined,
              "Полномочие отозвано.",
            )}>Отозвать</button>
          </div>
        ))}
        {!grants.length && <p>Отдельных полномочий пока не назначено.</p>}
      </div>
    </section>
  );
}
