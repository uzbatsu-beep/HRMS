import { useEffect, useState, type FormEvent } from "react";
import { useWorkspace } from "./WorkspaceContext";
import EquipmentDowntimePanel from "./EquipmentDowntimePanel";
import EquipmentCrewSnapshot from "./EquipmentCrewSnapshot";
import EquipmentAuditExplorer from "./EquipmentAuditExplorer";
import EquipmentPolicyPanel from "./EquipmentPolicyPanel";
import EquipmentPermissionMatrix from "./EquipmentPermissionMatrix";

type Asset = {
  id: string; enterprise_id: string; unit_id: string; code: string; name: string;
  kind: "machine" | "robot" | "production_line" | "other";
  serial_number: string | null;
  status: "active" | "out_of_service";
  required_credential_type_ids: string[];
  required_skills: AssetSkill[];
};
type CredentialType = { id: string; code: string; name: string };
type AssetSkill = { id: string; skill_id: string; skill_code: string;
  skill_name: string; min_level_id: string; min_ordinal: number; version: number };
type Skill = { id: string; name: string; code: string; scale_id: string; is_active: boolean };
type Scale = { id: string; levels: { id: string; ordinal: number; label: string }[] };
type Readiness = { enterprise_id: string; total: number; blocked: number;
  on_hold: number; items: ReadinessWork[] };
type ReadinessWork = { work_order_id: string; work_code: string; title: string;
  asset_code: string; unit_id: string; status: string;
  permit_status: string | null; software_blockers: string[] };
const blockerNames: Record<string, string> = {
  EQUIPMENT_OUT_OF_SERVICE: "Оборудование выведено из эксплуатации",
  WORK_PERMIT_NOT_APPROVED: "Нет согласованного разрешения",
  WORK_PERMIT_INCOMPLETE: "Контрольный лист разрешения неполон",
  EQUIPMENT_MISSING: "Оборудование недоступно",
  EQUIPMENT_DOWNTIME_CONFLICT: "Плановое обслуживание пересекается с работой",
};

async function api<T>(url: string, csrf?: string, method = "GET", data?: object): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin", method,
    headers: {
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...(data !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    ...(data !== undefined ? { body: JSON.stringify(data) } : {}),
  });
  if (!response.ok) {
    let message = "";
    try {
      const payload = await response.json() as { detail?: unknown };
      message = typeof payload.detail === "string"
        ? payload.detail : JSON.stringify(payload.detail ?? "");
    } catch { /* Preserve the status code. */ }
    throw new Error("HTTP " + response.status + (message ? ": " + message : ""));
  }
  return await response.json() as T;
}

const kinds: Record<Asset["kind"], string> = {
  machine: "Станок", robot: "Робот", production_line: "Линия", other: "Другое",
};

export default function EquipmentPanel() {
  const { session, enterpriseId, units } = useWorkspace();
  const admin = session?.user.role === "admin";
  const canReviewCrew = admin || session?.user.role === "manager";
  const [assets, setAssets] = useState<Asset[]>([]);
  const [types, setTypes] = useState<CredentialType[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [scales, setScales] = useState<Scale[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [unitId, setUnitId] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Asset["kind"]>("machine");
  const [serialNumber, setSerialNumber] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [rev, setRev] = useState(0);

  useEffect(() => {
    setAssets([]); setTypes([]); setSkills([]); setScales([]);
    setReadiness(null); setError("");
    if (!session || !enterpriseId) return;
    const controller = new AbortController();
    const root = "/api/v1/equipment/enterprises/" + enterpriseId;
    Promise.all([
      fetch(root + "/assets", {
        credentials: "same-origin", signal: controller.signal,
      }).then(async response => {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return await response.json() as Asset[];
      }),
      fetch(
        "/api/v1/credentials/enterprises/" + enterpriseId + "/types", {
          credentials: "same-origin", signal: controller.signal,
        },
      ).then(async response => {
        if (!response.ok) throw new Error("Credential types HTTP " + response.status);
        return await response.json() as CredentialType[];
      }),
      fetch(
        "/api/v1/competence/enterprises/" + enterpriseId + "/skills", {
          credentials: "same-origin", signal: controller.signal,
        },
      ).then(async response => {
        if (!response.ok) throw new Error("Skills HTTP " + response.status);
        return await response.json() as Skill[];
      }),
      fetch(
        "/api/v1/competence/enterprises/" + enterpriseId + "/scales", {
          credentials: "same-origin", signal: controller.signal,
        },
      ).then(async response => {
        if (!response.ok) throw new Error("Scales HTTP " + response.status);
        return await response.json() as Scale[];
      }),
      fetch(root + "/readiness", {
        credentials: "same-origin", signal: controller.signal,
      }).then(async response => {
        if (!response.ok) throw new Error("Readiness HTTP " + response.status);
        return await response.json() as Readiness;
      }),
    ]).then(([list, kindsList, skillList, scaleList, report]) => {
      if (controller.signal.aborted) return;
      setAssets(list); setTypes(kindsList);
      setSkills(skillList); setScales(scaleList); setReadiness(report);
      setSelectedId((old) => list.some(x => x.id === old) ? old : list[0]?.id ?? "");
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(
        cause instanceof Error ? cause.message : "Ошибка загрузки оборудования",
      );
    });
    return () => controller.abort();
  }, [session?.user.id, admin, enterpriseId, rev]);

  async function mutate<T>(action: () => Promise<T>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      await action();
      setNotice(success);
      setRev(value => value + 1);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Ошибка запроса");
    } finally {
      setBusy(false);
    }
  }
  const asset = assets.find(x => x.id === selectedId);
  const root = "/api/v1/equipment";
  const csrf = session?.csrf_token;

  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!csrf || !enterpriseId || !admin) return;
    void mutate(() => api<Asset>(
      root + "/enterprises/" + enterpriseId + "/assets",
      csrf, "POST", {
        unit_id: unitId, code, name, kind, serial_number: serialNumber || null,
      },
    ), "Оборудование зарегистрировано.");
  }

  if (!session) return <section className="equipment-panel">Для просмотра оборудования необходим вход.</section>;
  if (!enterpriseId) return <section className="equipment-panel">Выберите предприятие в правой панели.</section>;

  return (
    <section id="equipment" className="equipment-panel">
      <div className="equipment-heading">
        <div>
          <div className="eyebrow">EQUIPMENT / ASSET INVENTORY</div>
          <h2>Реестр оборудования</h2>
          <p>Единый реестр станков, роботов и линий с учётом прав доступа.
            Все ограничения на запуск работ проверяются сервером.</p>
        </div>
        <button type="button" disabled={busy} onClick={() => setRev(x => x + 1)}>
          Обновить
        </button>
      </div>
      {error && <p className="equipment-error" role="alert">{error}</p>}
      {notice && <p className="equipment-notice" role="status">{notice}</p>}
      {admin && (
        <details className="equipment-editor">
          <summary>Зарегистрировать оборудование</summary>
          <form onSubmit={create}>
            <label>Код актива
              <input value={code} minLength={2} maxLength={64}
                pattern="[A-Za-z0-9_.-]+" required
                onChange={(e) => setCode(e.target.value)} />
            </label>
            <label>Наименование
              <input value={name} minLength={2} maxLength={180} required
                onChange={(e) => setName(e.target.value)} />
            </label>
            <label>Подразделение оборудования
              <select required value={unitId} onChange={e => setUnitId(e.target.value)}>
                <option value="">Выберите подразделение</option>
                {units.map(x => <option value={x.id} key={x.id}>{x.name}</option>)}
              </select>
            </label>
            <label>Класс
              <select value={kind} onChange={e => setKind(e.target.value as Asset["kind"])}>
                {Object.entries(kinds).map(([key, value]) =>
                  <option key={key} value={key}>{value}</option>)}
              </select>
            </label>
            <label>Заводской номер
              <input value={serialNumber} maxLength={120}
                onChange={e => setSerialNumber(e.target.value)} />
            </label>
            <button type="submit" disabled={busy}>Создать актив</button>
          </form>
        </details>
      )}
      <div className="equipment-layout">
        <div className="equipment-list">
          <h3>Активы в разрешённых подразделениях</h3>
          {assets.map(item => (
            <button className={selectedId === item.id ? "active" : ""}
              key={item.id} type="button" onClick={() => setSelectedId(item.id)}>
              <strong>{item.code} — {item.name}</strong>
              <small>{kinds[item.kind]} · {item.status === "active"
                ? "В эксплуатации" : "Выведено из эксплуатации"}</small>
            </button>
          ))}
          {assets.length === 0 && <p>Нет доступных активов.</p>}
        </div>
        <div className="equipment-detail">
          <h3>Карточка оборудования</h3>
          {!asset && <p>Выберите актив из реестра.</p>}
          {asset && (
            <>
              <p><strong>{asset.code}</strong> — {asset.name}</p>
              <p>Класс: {kinds[asset.kind]} · №: {asset.serial_number || "—"}</p>
              <p>Подразделение: {units.find(x => x.id === asset.unit_id)?.name ?? "—"}</p>
              <p>Состояние: <strong>{asset.status === "active"
                ? "В эксплуатации" : "Выведено из эксплуатации"}</strong></p>
              <EquipmentDowntimePanel
                key={asset.id}
                assetId={asset.id}
                admin={Boolean(admin)}
                csrfToken={csrf}
                onChanged={() => setRev(x => x + 1)}
              />
              <h4>Обязательные дополнительные допуски</h4>
              {asset.required_credential_type_ids.length ? (
                <ul>
                  {asset.required_credential_type_ids.map(id => (
                    <li key={id}>{types.find(type => type.id === id)?.name
                      ?? "Тип документа: " + id}</li>
                  ))}
                </ul>
              ) : <p>Дополнительные требования не указаны. Основные требования
                вида работ сохраняются.</p>}
              <h4>Обязательные компетенции на оборудовании</h4>
              {asset.required_skills.length > 0 ? (
                <ul>
                  {asset.required_skills.map(rule => (
                    <li key={rule.id}>{rule.skill_name}: v{rule.version}, уровень ≥ {rule.min_ordinal}</li>
                  ))}
                </ul>
              ) : <p>Специфические навыки оборудования ещё не заданы.
                Требования самого наряда сохраняются.</p>}
              <EquipmentPolicyPanel
                    key={asset.id}
                    assetId={asset.id}
                    actorId={session.user.id}
                    csrfToken={csrf}
                    types={types}
                    skills={skills}
                    scales={scales}
                    activeCredentialIds={asset.required_credential_type_ids}
                    activeSkillIds={asset.required_skills.map(x => x.skill_id)}
                    activeSkills={asset.required_skills}
                    onChanged={() => setRev(x => x + 1)}
                  />
              {admin && (
                <>
                  <EquipmentPermissionMatrix
                    key={"permission-" + asset.id}
                    unitId={asset.unit_id} csrfToken={csrf}
                  />
                  <label>Причина смены состояния (не менее 10 символов)
                    <textarea value={reason} minLength={10} maxLength={400}
                      onChange={e => setReason(e.target.value)} />
                  </label>
                  <button type="button" disabled={busy || reason.trim().length < 10}
                    onClick={() => void mutate(() => api<Asset>(
                      root + "/assets/" + asset.id + "/state", csrf, "POST", {
                        status: asset.status === "active" ? "out_of_service" : "active",
                        reason,
                      },
                    ), "Состояние оборудования обновлено.")}>
                    {asset.status === "active" ? "Вывести из эксплуатации" : "Вернуть в эксплуатацию"}
                  </button>
                </>
              )}
            </>
          )}
        </div>
      </div>
      <div className="equipment-readiness" aria-label="Операционная сводка оборудования">
        <h3>Операционная сводка связанных нарядов</h3>
        <p>Сводка автоматически проверяет только актив, обслуживание и разрешение.
          Руководитель может отдельно запросить текущую проверку всей бригады.
          Ни один показатель не является допуском к опасным работам.</p>
        {readiness && (
          <>
            <div className="equipment-readiness-kpis">
              <strong>Связано: {readiness.total}</strong>
              <strong>Блокирующие условия: {readiness.blocked}</strong>
              <strong>Приостановлено в HRMS: {readiness.on_hold}</strong>
            </div>
            {readiness.items.map(item => (
              <div className="equipment-readiness-item" key={item.work_order_id}>
                <strong>{item.work_code} · {item.title}</strong>
                <small>{item.asset_code} · {item.status}
                  {" · "}{item.permit_status ?? "Нет разрешения"}</small>
                {item.software_blockers.map(code => (
                  <span key={code} className="wm-warning">{blockerNames[code] ?? code}</span>
                ))}
                {canReviewCrew && (
                  <EquipmentCrewSnapshot key={rev + "-" + item.work_order_id}
                    orderId={item.work_order_id} />
                )}
              </div>
            ))}
            {readiness.items.length === 0 &&
              <p>Активных связанных нарядов в доступных подразделениях нет.</p>}
          </>
        )}
      </div>
      {admin && <EquipmentAuditExplorer key={enterpriseId} enterpriseId={enterpriseId} />}
      <p className="workspace-warning">Только прототип и синтетические данные.
        Статус оборудования в HRMS не управляет станком, роботом, защитными ограждениями
        или промышленными safety-цепями.</p>
    </section>
  );
}
