import { useEffect, useState } from "react";

type CredentialType = { id: string; code: string; name: string };
type Skill = { id: string; name: string; code: string; scale_id: string; is_active: boolean };
type Scale = { id: string; levels: { id: string; ordinal: number; label: string }[] };
type ActiveSkill = { skill_id: string; skill_name: string; min_ordinal: number;
  min_level_id: string; version: number };
type SkillHistory = { requirement_id: string; skill_id: string; version: number;
  min_level_id: string; min_ordinal: number; approved_by: string;
  approved_at: string; proposal_id: string | null };
type Policy = {
  id: string; enterprise_id: string; asset_id: string;
  kind: "skill" | "credential" | "skill_upgrade";
  expected_version: number | null;
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
  activeSkills: ActiveSkill[];
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
  activeCredentialIds, activeSkillIds, activeSkills, onChanged,
}: Props) {
  const [rights, setRights] = useState<{
    can_read: boolean; can_propose: boolean; can_review: boolean;
  } | null>(null);
  const [proposals, setProposals] = useState<Policy[]>([]);
  const [skillHistory, setSkillHistory] = useState<SkillHistory[]>([]);
  const [upgradeSkillId, setUpgradeSkillId] = useState("");
  const [upgradeLevelId, setUpgradeLevelId] = useState("");
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
  const currentUpgrade = activeSkills.find(x => x.skill_id === upgradeSkillId);
  const upgradeSkill = skills.find(x => x.id === upgradeSkillId);
  const upgradeLevels = scales.find(x => x.id === upgradeSkill?.scale_id)?.levels
    .filter(x => x.ordinal > (currentUpgrade?.min_ordinal ?? Number.MAX_SAFE_INTEGER)) ?? [];

  useEffect(() => {
    let active = true;
    setRights(null);
    api<{ can_read: boolean; can_propose: boolean; can_review: boolean }>(
      root + assetId + "/policy-capabilities",
    ).then(x => { if (active) setRights(x); }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Нет доступа");
    });
    return () => { active = false; };
  }, [assetId, revision]);

  useEffect(() => {
    if (!rights?.can_read) return;
    let active = true;
    setError("");
    Promise.all([
      api<Policy[]>(endpoint),
      api<SkillHistory[]>(root + assetId + "/skill-policy-revisions"),
    ]).then(([value, history]) => {
      if (active) { setProposals(value); setSkillHistory(history); }
    }).catch((cause: unknown) => {
      if (active) setError(
        cause instanceof Error ? cause.message : "Ошибка получения предложений",
      );
    });
    return () => { active = false; };
  }, [assetId, endpoint, revision, rights?.can_read]);

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
  if (!rights?.can_read) return null;

  return (
    <section className="equipment-policy" aria-label="Согласование требований оборудования">
      <h4>Согласование новых требований</h4>
      <p>Разрешения: {rights.can_propose ? "создавать заявки · " : ""}
        {rights.can_review ? "согласовывать · " : ""}просматривать историю.</p>
      <p>Новые компетенции и допуски вступают в силу только после
        независимого утверждения другим уполномоченным пользователем.
        До согласования текущие ограничения остаются без изменений.</p>
      {error && <p role="alert" className="equipment-error">{error}</p>}
      {notice && <p role="status" className="equipment-notice">{notice}</p>}

      {rights.can_propose && (<>
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

      <h4>Повышение действующего уровня компетенции</h4>
      <p>Только более высокий уровень и только через новую утверждённую редакцию.
        Понижение и удаление требования в этом процессе запрещены.</p>
      <div className="equipment-actions">
        <label>Повышаемая компетенция
          <select value={upgradeSkillId} onChange={e => {
            setUpgradeSkillId(e.target.value); setUpgradeLevelId("");
          }}>
            <option value="">Выберите действующее требование</option>
            {activeSkills.filter(x => !proposals.some(p =>
              p.status === "pending" && p.skill_id === x.skill_id,
            )).map(x => (
              <option key={x.skill_id} value={x.skill_id}>
                {x.skill_name} · v{x.version}, уровень ≥ {x.min_ordinal}
              </option>
            ))}
          </select>
        </label>
        <label>Новый минимальный уровень
          <select value={upgradeLevelId}
            onChange={e => setUpgradeLevelId(e.target.value)}>
            <option value="">Выберите более высокий уровень</option>
            {upgradeLevels.map(x => <option value={x.id} key={x.id}>
              {x.ordinal} — {x.label}
            </option>)}
          </select>
        </label>
        <button type="button"
          disabled={busy || !isReasonValid || !currentUpgrade || !upgradeLevelId}
          onClick={() => void mutate(endpoint, {
            kind: "skill_upgrade", skill_id: upgradeSkillId,
            min_level_id: upgradeLevelId,
            expected_version: currentUpgrade!.version, reason,
          }, "Повышение уровня отправлено на независимое согласование.")}>
          Предложить повышение уровня
        </button>
      </div>
      </>)}
      <h4>Редакции действующих компетенций</h4>
      <div className="equipment-policy-versions">
        {skillHistory.map(x => (
          <div key={x.requirement_id + "-" + x.version}>
            <strong>{skills.find(s => s.id === x.skill_id)?.name ?? x.skill_id} ·
              {" "}v{x.version} · уровень ≥ {x.min_ordinal}
            </strong>
            <small> · {new Date(x.approved_at).toLocaleString("ru-RU")}
              {x.proposal_id ? " · утверждённая редакция" : " · исходное требование"}
            </small>
          </div>
        ))}
        {skillHistory.length === 0 &&
          <p>Утверждённых компетенций оборудования ещё нет.</p>}
      </div>
      <h4>История согласования</h4>
      {proposals.length === 0 && <p>Заявок на изменение требований пока нет.</p>}
      {rights.can_review && <label>Мотивировка решения (не менее 10 символов)
        <input value={reviewNote} minLength={10} maxLength={400}
          onChange={e => setReviewNote(e.target.value)} />
      </label>}
      <div className="equipment-policy-list">
        {proposals.map(p => (
          <article className="equipment-policy-row" key={p.id}>
            <strong>{p.kind === "skill_upgrade" ? "Повышение компетенции" : p.kind === "skill"
              ? "Компетенция" : "Допуск"} · {
              (p.kind === "skill" || p.kind === "skill_upgrade")
                ? skills.find(x => x.id === p.skill_id)?.name ?? p.skill_id
                : types.find(x => x.id === p.credential_type_id)?.name
                    ?? p.credential_type_id
            }</strong>
            <small>{new Date(p.proposed_at).toLocaleString("ru-RU")}</small>
            <small>{p.expected_version && "Исходная версия: v" + p.expected_version}</small>
            <small>Статус: {p.status === "pending" ? "Ожидает утверждения"
              : p.status === "approved" ? "Утверждено" : "Отклонено"}</small>
            <p>Основание: {p.reason}</p>
            {p.review_note && <p>Решение: {p.review_note}</p>}
            {p.status === "pending" && p.proposed_by === actorId && (
              <small>Для решения требуется другой уполномоченный согласующий.</small>
            )}
            {rights.can_review && p.status === "pending" && p.proposed_by !== actorId && (
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
