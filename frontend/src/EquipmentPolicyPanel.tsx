import { useEffect, useState } from "react";

type CredentialType = { id: string; code: string; name: string };
type Skill = { id: string; name: string; code: string; scale_id: string; is_active: boolean };
type Scale = { id: string; levels: { id: string; ordinal: number; label: string }[] };
type Policy = {
  id: string; enterprise_id: string; asset_id: string;
  kind: "skill" | "credential";
  credential_type_id: string | null;
  skill_id: string | null;
  min_level_id: string | null;
  status: "pending" | "approved" | "rejected";
  reason: string; proposed_by: string; proposed_at: string;
  reviewed_by: string | null; reviewed_at: string | null; review_note: string | null;
};
type Props = {
  assetId: string; actorId: string; csrfToken?: string;
  types: CredentialType[]; skills: Skill[]; scales: Scale[];
  activeCredentialIds: string[]; activeSkillIds: string[];
  onChanged: () => void;
};

const root = "/api/v1/equipment/assets/";
async function api<T>(path: string, csrf?: string, data?: object): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin", method: csrf ? "POST" : "GET",
    headers: {
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...(data ? { "Content-Type": "application/json" } : {}),
    },
    ...(data ? { body: JSON.stringify(data) } : {}),
  });
  if (!response.ok) {
    let info = "";
    try {
      const json = await response.json() as { detail?: unknown };
      info = typeof json.detail === "string" ? json.detail : JSON.stringify(json.detail);
    } catch { /* Keep HTTP status. */ }
    throw new Error("HTTP " + response.status + (info ? ": " + info : ""));
  }
  return await response.json() as T;
}

export default function EquipmentPolicyPanel({
  assetId, actorId, csrfToken, types, skills, scales,
  activeCredentialIds, activeSkillIds, onChanged,
}: Props) {
  const [proposals, setProposals] = useState<Policy[]>([]);
  const [credentialId, setCredentialId] = useState("");
  const [skillId, setSkillId] = useState("");
  const [levelId, setLevelId] = useState("");
  const [reason, setReason] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const selected = skills.find(x => x.id === skillId);
  const levels = scales.find(x => x.id === selected?.scale_id)?.levels ?? [];
  const endpoint = root + assetId + "/policy-proposals";

  useEffect(() => {
    let active = true;
    setError("");
    api<Policy[]>(endpoint).then(value => {
      if (active) setProposals(value);
    }).catch((cause: unknown) => {
      if (active) setError(
        cause instanceof Error ? cause.message : "Ошибка получения предложений",
      );
    });
    return () => { active = false; };
  }, [endpoint, revision]);

  async function mutate(path: string, data: object, message: string) {
    if (!csrfToken) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api<unknown>(path, csrfToken, data);
      setNotice(message);
      setRevision(value => value + 1);
      onChanged();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Операция отклонена");
    } finally {
      setBusy(false);
    }
  }

  const isReasonValid = reason.trim().length >= 10;
  const isReviewValid = reviewNote.trim().length >= 10;

  return (
    <section className="equipment-policy" aria-label="Согласование требований оборудования">
      <h4>Согласование новых требований</h4>
      <p>Новые компетенции и допуски вступают в силу только после
        независимого утверждения другим администратором.
        До согласования текущие ограничения остаются без изменений.</p>
      {error && <p role="alert" className="equipment-error">{error}</p>}
      {notice && <p role="status" className="equipment-notice">{notice}</p>}

      <label>Обоснование нового требования (не менее 10 символов)
        <textarea value={reason} minLength={10} maxLength={400}
          onChange={e => setReason(e.target.value)} />
      </label>
      <div className="equipment-actions">
        <label>Компетенция оборудования
          <select value={skillId} onChange={e => {
            setSkillId(e.target.value); setLevelId("");
          }}>
            <option value="">Выберите компетенцию</option>
            {skills.filter(x => x.is_active && !activeSkillIds.includes(x.id)
              && !proposals.some(p => p.kind === "skill" && p.skill_id === x.id
                && p.status === "pending")).map(x => (
              <option key={x.id} value={x.id}>{x.name}</option>
            ))}
          </select>
        </label>
        <label>Уровень компетенции оборудования
          <select value={levelId} onChange={e => setLevelId(e.target.value)}>
            <option value="">Выберите уровень</option>
            {levels.map(x => (
              <option key={x.id} value={x.id}>{x.ordinal} — {x.label}</option>
            ))}
          </select>
        </label>
        <button type="button"
          disabled={busy || !isReasonValid || !skillId || !levelId}
          onClick={() => void mutate(endpoint, {
            kind: "skill", skill_id: skillId, min_level_id: levelId, reason,
          }, "Заявка на компетенцию отправлена для независимого согласования.")}>
          Предложить требование к навыку
        </button>
      </div>
      <div className="equipment-actions">
        <label>Допуск оборудования
          <select value={credentialId} onChange={e => setCredentialId(e.target.value)}>
            <option value="">Выберите тип документа</option>
            {types.filter(x => !activeCredentialIds.includes(x.id)
              && !proposals.some(p => p.kind === "credential"
                && p.credential_type_id === x.id && p.status === "pending"))
              .map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </label>
        <button type="button"
          disabled={busy || !isReasonValid || !credentialId}
          onClick={() => void mutate(endpoint, {
            kind: "credential", credential_type_id: credentialId, reason,
          }, "Заявка на допуск отправлена для независимого согласования.")}>
          Предложить требование к допуску
        </button>
      </div>

      <h4>История согласования</h4>
      {proposals.length === 0 && <p>Заявок на изменение требований пока нет.</p>}
      <label>Мотивировка решения (не менее 10 символов)
        <input value={reviewNote} minLength={10} maxLength={400}
          onChange={e => setReviewNote(e.target.value)} />
      </label>
      <div className="equipment-policy-list">
        {proposals.map(p => (
          <article className="equipment-policy-row" key={p.id}>
            <strong>{p.kind === "skill" ? "Компетенция" : "Допуск"} · {
              p.kind === "skill"
                ? skills.find(x => x.id === p.skill_id)?.name ?? p.skill_id
                : types.find(x => x.id === p.credential_type_id)?.name
                    ?? p.credential_type_id
            }</strong>
            <small>{new Date(p.proposed_at).toLocaleString("ru-RU")}</small>
            <small>Статус: {p.status === "pending" ? "Ожидает утверждения"
              : p.status === "approved" ? "Утверждено" : "Отклонено"}</small>
            <p>Основание: {p.reason}</p>
            {p.review_note && <p>Решение: {p.review_note}</p>}
            {p.status === "pending" && p.proposed_by === actorId && (
              <small>Для решения требуется другой администратор.</small>
            )}
            {p.status === "pending" && p.proposed_by !== actorId && (
              <div className="equipment-policy-review">
                <button type="button" disabled={busy || !isReviewValid}
                  onClick={() => void mutate(
                    endpoint + "/" + p.id + "/approve", { note: reviewNote },
                    "Новая политика утверждена и вступила в силу.",
                  )}>Утвердить</button>
                <button type="button" disabled={busy || !isReviewValid}
                  onClick={() => void mutate(
                    endpoint + "/" + p.id + "/reject", { note: reviewNote },
                    "Заявка отклонена; действующая политика не менялась.",
                  )}>Отклонить</button>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
