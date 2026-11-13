import { useState } from "react";

type CrewSnapshot = {
  work_order_id: string;
  work_status: string;
  checked_at: string;
  last_persisted_safety_check_at: string | null;
  leader_assigned: boolean;
  members_checked: number;
  members_blocked: number;
  equipment_blocker_codes: string[];
  crew_blocker_codes: string[];
  gates_passed: boolean;
  crew_eligibility_checked: true;
  read_only: true;
};

const labels: Record<string, string> = {
  LEADER_NOT_ASSIGNED: "Руководитель бригады не назначен",
  WORK_PERMIT_NOT_APPROVED: "Разрешение на работу не согласовано",
  WORK_PERMIT_INCOMPLETE: "Разрешение на работу неполное",
  EQUIPMENT_DOWNTIME_CONFLICT: "Период наряда пересекается с обслуживанием",
  EQUIPMENT_OUT_OF_SERVICE: "Оборудование выведено из эксплуатации",
  EQUIPMENT_MISSING: "Оборудование не найдено",
  MISSING_VERIFIED_SKILL: "Нет подтверждённой компетенции",
  INSUFFICIENT_SKILL_LEVEL: "Недостаточный уровень компетенции",
  EQUIPMENT_SKILL_UNVERIFIED: "Навык для оборудования не подтверждён",
  EQUIPMENT_SKILL_BELOW_MINIMUM: "Недостаточный навык для оборудования",
  MISSING_CREDENTIAL: "Обязательный допуск отсутствует",
  REVOKED_CREDENTIAL: "Допуск отозван",
  EXPIRED_CREDENTIAL: "Срок допуска истёк",
  EQUIPMENT_CREDENTIAL_MISSING: "Отсутствует допуск для оборудования",
  ABSENT: "Сотрудник отсутствует по календарю",
  RESERVATION_INVALID: "Бронирование специалиста недействительно",
};

export default function EquipmentCrewSnapshot({ orderId }: { orderId: string }) {
  const [snapshot, setSnapshot] = useState<CrewSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function inspect() {
    setLoading(true);
    setError("");
    setSnapshot(null);
    try {
      const response = await fetch(
        "/api/v1/equipment/orders/" + orderId + "/crew-readiness",
        { credentials: "same-origin" },
      );
      if (!response.ok) throw new Error("HTTP " + response.status);
      const result = await response.json() as CrewSnapshot;
      if (!result.crew_eligibility_checked || !result.read_only) {
        throw new Error("Ответ проверки не соответствует контракту");
      }
      setSnapshot(result);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Ошибка проверки бригады");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="equipment-crew-snapshot">
      <button type="button" onClick={() => void inspect()} disabled={loading}>
        {loading ? "Проверка…" : snapshot ? "Повторить проверку бригады"
          : "Проверить бригаду"}
      </button>
      {error && <p role="alert" className="equipment-error">{error}</p>}
      {snapshot && (
        <div role="status" className="equipment-crew-result">
          <strong>{snapshot.gates_passed
            ? "Текущие программные проверки пройдены"
            : "Есть блокирующие условия"}</strong>
          <small>Проверено: {new Date(snapshot.checked_at).toLocaleString("ru-RU")}
            {" · "}Участников: {snapshot.members_checked}
            {" · "}С проблемами: {snapshot.members_blocked}
          </small>
          {[...snapshot.equipment_blocker_codes, ...snapshot.crew_blocker_codes]
            .map(code => (
              <span key={code} className="wm-warning">{labels[code] ?? code}</span>
            ))}
          <small>Разовый снимок без изменения статуса наряда. Не является
            допуском к работе или подтверждением физической безопасности.
            Для повторной проверки с фиксацией и удержанием используйте
            действия в разделе «Наряды».</small>
        </div>
      )}
    </div>
  );
}
