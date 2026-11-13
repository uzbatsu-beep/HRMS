import { useEffect, useState } from "react";

type Asset = {
  id: string; code: string; name: string; status: string; unit_id: string;
};
type Permit = {
  id: string; version: number;
  status: "draft" | "submitted" | "approved" | "revoked";
  prepared_by: string; approved_by: string | null;
  hazards_reviewed: boolean; energy_isolation_attested: boolean;
  area_access_attested: boolean; evidence_reference: string | null;
};
type Package = {
  work_order_id: string;
  asset: Asset | null;
  permit: Permit | null;
  equipment_blockers: string[];
};
type Props = {
  work: {
    id: string; enterprise_id: string;
    status: "open" | "assigned" | "in_progress" | "on_hold" | "completed" | "cancelled";
  };
  csrfToken?: string;
  actorRole?: string;
  actorId?: string;
  canDispatch: boolean;
  onChanged: () => void;
};

const labels: Record<string, string> = {
  EQUIPMENT_MISSING: "Оборудование отсутствует",
  EQUIPMENT_OUT_OF_SERVICE: "Оборудование выведено из эксплуатации",
  WORK_PERMIT_NOT_APPROVED: "Нет действующего согласованного разрешения",
  WORK_PERMIT_INCOMPLETE: "Неполные свидетельства проверки места работ",
};

async function api<T>(url: string, csrf?: string, data?: object): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    method: csrf ? "POST" : "GET",
    headers: {
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...(data !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    ...(data !== undefined ? { body: JSON.stringify(data) } : {}),
  });
  if (!response.ok) {
    let detail = "";
    try {
      const result = await response.json() as { detail?: unknown };
      detail = typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail);
    } catch { /* Preserve HTTP status. */ }
    throw new Error("HTTP " + response.status + (detail ? ": " + detail : ""));
  }
  return await response.json() as T;
}

const root = "/api/v1/equipment";

export default function WorkEquipmentPermitPanel({
  work, csrfToken, actorRole, actorId, canDispatch, onChanged,
}: Props) {
  const [report, setReport] = useState<Package | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetId, setAssetId] = useState("");
  const [hazards, setHazards] = useState(false);
  const [isolation, setIsolation] = useState(false);
  const [access, setAccess] = useState(false);
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setReport(null); setError("");
    Promise.all([
      api<Package>(root + "/orders/" + work.id + "/safety-package"),
      api<Asset[]>(root + "/enterprises/" + work.enterprise_id + "/assets"),
    ]).then(([data, list]) => {
      if (controller.signal.aborted) return;
      setReport(data); setAssets(list);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(
        cause instanceof Error ? cause.message : "Не удалось прочитать safety package",
      );
    });
    return () => controller.abort();
  }, [work.id, work.enterprise_id, revision, work.status]);

  async function action(path: string, data: object | undefined, success: string) {
    if (!csrfToken || !canDispatch) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api<unknown>(root + path, csrfToken, data);
      setNotice(success);
      setRevision(value => value + 1);
      onChanged();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Операция отклонена");
    } finally {
      setBusy(false);
    }
  }
  const editable = work.status === "open" || work.status === "assigned"
    || work.status === "on_hold";
  const packageId = "/orders/" + work.id;
  const currentPermit = report?.permit;
  const currentAsset = report?.asset;

  return (
    <section className="wm-permit" aria-label="Оборудование и разрешение на работы">
      <h3>Оборудование и разрешение на работы</h3>
      <p>Человеческая фиксация проверок. Подтверждения не заменяют фактические
        блокировки, LOTO и наряд-допуск предприятия.</p>
      {error && <p role="alert" className="wm-error">{error}</p>}
      {notice && <p role="status" className="wm-success">{notice}</p>}
      {!report && !error && <p role="status">Загрузка связанного оборудования…</p>}
      {report && (
        <>
          {!currentAsset && work.status === "open" && canDispatch && (
            <div className="wm-permit-form">
              <label>Связать с оборудованием до назначения персонала
                <select aria-label="Оборудование наряда" value={assetId}
                  onChange={e => setAssetId(e.target.value)}>
                  <option value="">Выберите оборудование</option>
                  {assets.filter(x => x.status === "active").map(asset => (
                    <option key={asset.id} value={asset.id}>{asset.code} · {asset.name}</option>
                  ))}
                </select>
              </label>
              <button type="button" disabled={!assetId || busy}
                onClick={() => void action(packageId + "/equipment",
                  { asset_id: assetId }, "Оборудование связано с нарядом.")}>
                Привязать оборудование
              </button>
            </div>
          )}
          {!currentAsset && (
            <p className="wm-hint">
              Оборудование не привязано. Для реальной работы со станком или роботом
              его нужно выбрать до назначения исполнителей.
            </p>
          )}
          {currentAsset && (
            <>
              <p><strong>{currentAsset.code} · {currentAsset.name}</strong>
                {" "}— {currentAsset.status === "active"
                  ? "В эксплуатации" : "Выведено из эксплуатации"}</p>
              {report.equipment_blockers.length > 0 && (
                <div className="wm-blockers" role="status">
                  {report.equipment_blockers.map(code => (
                    <p key={code}>{labels[code] ?? code}</p>
                  ))}
                </div>
              )}
              <h4>Последнее разрешение</h4>
              {currentPermit ? (
                <p>Версия {currentPermit.version} · {({
                  draft: "Черновик", submitted: "На согласовании",
                  approved: "Согласовано", revoked: "Отозвано",
                } as Record<string, string>)[currentPermit.status]}
                {currentPermit.evidence_reference
                  ? " · документ " + currentPermit.evidence_reference : ""}</p>
              ) : <p>Разрешение ещё не создано.</p>}
              {canDispatch && editable && (!currentPermit || currentPermit.status === "revoked") && (
                <div className="wm-permit-form">
                  <h4>Подготовить новое разрешение</h4>
                  <label><input type="checkbox" checked={hazards}
                    onChange={e => setHazards(e.target.checked)} />
                    Риски рабочего места рассмотрены (со слов ответственного)</label>
                  <label><input type="checkbox" checked={isolation}
                    onChange={e => setIsolation(e.target.checked)} />
                    Изоляция источников энергии заявлена ответственным</label>
                  <label><input type="checkbox" checked={access}
                    onChange={e => setAccess(e.target.checked)} />
                    Доступ на рабочее место заявлен ответственным</label>
                  <label>Ссылка или идентификатор документа / протокола
                    <input value={reference} minLength={10} maxLength={200}
                      onChange={e => setReference(e.target.value)} />
                  </label>
                  <button type="button" disabled={busy || reference.trim().length < 10}
                    onClick={() => void action(packageId + "/permit", {
                      hazards_reviewed: hazards,
                      energy_isolation_attested: isolation,
                      area_access_attested: access,
                      evidence_reference: reference,
                    }, "Черновик разрешения создан.")}>
                    Зарегистрировать черновик
                  </button>
                </div>
              )}
              {canDispatch && editable && currentPermit?.status === "draft" && (
                <button type="button" disabled={busy}
                  onClick={() => void action(packageId + "/permit/" + currentPermit.id
                    + "/submit", undefined, "Разрешение направлено на согласование.")}>
                  Отправить на согласование
                </button>
              )}
              {actorRole === "admin" && editable
                && currentPermit?.status === "submitted" && (
                <button type="button" disabled={busy || currentPermit.prepared_by === actorId}
                  onClick={() => void action(packageId + "/permit/" + currentPermit.id
                    + "/approve", undefined, "Независимое согласование зарегистрировано.")}>
                  Согласовать разрешение (другой администратор)
                </button>
              )}
              {actorRole === "admin" && currentPermit
                && currentPermit.status !== "revoked"
                && !["cancelled", "completed"].includes(work.status) && (
                <div className="wm-permit-form">
                  <label>Причина отзыва разрешения (не менее 10 символов)
                    <textarea value={reason} minLength={10} maxLength={400}
                      onChange={e => setReason(e.target.value)} />
                  </label>
                  <button type="button" disabled={busy || reason.trim().length < 10}
                    onClick={() => void action(packageId + "/permit/" + currentPermit.id
                      + "/revoke", { reason }, "Разрешение отозвано.")}>
                    Отозвать разрешение
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
