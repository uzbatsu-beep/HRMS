import { useEffect, useState } from "react";
import { useWorkspace } from "./WorkspaceContext";

type DailyTrend = { day: string; created: number; completed: number };
type DashboardData = {
  enterprise_id: string;
  unit_id: string | null;
  as_of: string;
  period_days: number;
  renewal_days: number;
  period_start: string;
  workforce: {
    active_resources: number;
    reservable_next_15m: number;
    blocked_next_15m: number;
  };
  work_orders: {
    open: number; assigned: number; in_progress: number;
    on_hold: number; completed: number; cancelled: number;
  };
  credentials: {
    expiring_within_30d: number;
    expired_records: number;
    pending_records: number;
  };
  workload: {
    reserved_hours: number;
    resources_with_reservations: number;
    by_unit: { unit_id: string; unit_name: string; reserved_hours: number }[];
  };
  trends: DailyTrend[];
  holds: {
    id: string; code: string; title: string; priority: string; unit_id: string;
  }[];
};

const workLabels: { key: keyof DashboardData["work_orders"]; label: string }[] = [
  { key: "open", label: "Открытые" },
  { key: "assigned", label: "Назначенные" },
  { key: "in_progress", label: "В работе" },
  { key: "on_hold", label: "Приостановлены" },
  { key: "completed", label: "Завершены" },
  { key: "cancelled", label: "Отменены" },
];

const hours = (value: number) => value.toLocaleString("ru-RU", {
  minimumFractionDigits: 0, maximumFractionDigits: 2,
});

function Kpi({
  label, value, detail, action, urgent = false,
}: {
  label: string; value: number | string; detail: string;
  action?: () => void; urgent?: boolean;
}) {
  return (
    <div className={"ops-kpi" + (urgent ? " ops-kpi-alert" : "")}>
      <span className="ops-kpi-label">{label}</span>
      <strong>{value}</strong>
      <span className="ops-kpi-detail">{detail}</span>
      {action && <button type="button" onClick={action}>Открыть раздел ›</button>}
    </div>
  );
}

export default function DashboardPanel({
  navigate,
}: { navigate: (page: string) => void }) {
  const { session, enterpriseId, unitId, enterprises, units } = useWorkspace();
  const [revision, setRevision] = useState(0);
  const contextKey = session && enterpriseId
    ? [session.user.id, enterpriseId, unitId].join(":") : "";
  const [loaded, setLoaded] = useState<{ key: string; value: DashboardData } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);

  useEffect(() => {
    if (!contextKey) return;
    const controller = new AbortController();
    setFailure(null);
    setLoaded(null);
    const url = "/api/v1/analytics/enterprises/" + encodeURIComponent(enterpriseId)
      + "/summary" + (unitId ? "?unit_id=" + encodeURIComponent(unitId) : "");
    fetch(url, { credentials: "same-origin", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(response.status === 404
            ? "Нет доступа к выбранной организационной области."
            : "Не удалось получить аналитику (HTTP " + response.status + ").");
        }
        return await response.json() as DashboardData;
      })
      .then((value) => {
        if (!controller.signal.aborted) setLoaded({ key: contextKey, value });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setFailure({
          key: contextKey,
          message: error instanceof Error ? error.message : "Ошибка загрузки.",
        });
      });
    return () => controller.abort();
  }, [contextKey, enterpriseId, unitId, revision]);

  if (!session) {
    return (
      <section className="ops-panel">
        <h2>Операционная аналитика</h2>
        <p>Авторизуйтесь, чтобы открыть показатели в разрешённой области доступа.</p>
        <button type="button" onClick={() => navigate("access")}>Перейти к входу</button>
      </section>
    );
  }
  if (!enterpriseId) {
    return (
      <section className="ops-panel">
        <h2>Операционная аналитика</h2>
        <p>Выберите доступное предприятие в правой панели.</p>
        {enterprises.length === 0 &&
          <p>Для этой учётной записи нет разрешённой организационной области.</p>}
      </section>
    );
  }
  const data = loaded?.key === contextKey ? loaded.value : null;
  const error = failure?.key === contextKey ? failure.message : null;
  const enterprise = enterprises.find((item) => item.id === enterpriseId);
  const unit = units.find((item) => item.id === unitId);
  if (error) {
    return (
      <section className="ops-panel" role="alert">
        <h2>Аналитика недоступна</h2>
        <p>{error}</p>
        <button type="button" onClick={() => setRevision((value) => value + 1)}>
          Повторить запрос
        </button>
      </section>
    );
  }
  if (!data) {
    return <section className="ops-panel" role="status">Загрузка показателей…</section>;
  }

  const maxTrend = Math.max(1, ...data.trends.flatMap((d) => [d.created, d.completed]));
  const maxUnit = Math.max(1, ...data.workload.by_unit.map((row) => row.reserved_hours));

  return (
    <section className="ops-dashboard" aria-label="Операционная аналитика">
      <header className="ops-panel ops-dashboard-header">
        <div>
          <div className="eyebrow">OPERATIONAL DASHBOARD / RBAC</div>
          <h2>Состояние технических ресурсов</h2>
          <p>
            {enterprise?.name ?? "Предприятие"}
            {unit ? " / " + unit.name : " / Все разрешённые подразделения"}
          </p>
          <small>
            Период: {data.period_days} календарных дней · Продление допусков:
            {" "}{data.renewal_days} дней · Срез:{" "}
            <time dateTime={data.as_of}>{new Date(data.as_of).toLocaleString("ru-RU")}</time>
          </small>
        </div>
        <button type="button" onClick={() => setRevision((value) => value + 1)}>
          Обновить данные
        </button>
      </header>

      <div className="ops-kpi-grid" aria-label="Ключевые показатели">
        <Kpi label="Активные ресурсы" value={data.workforce.active_resources}
          detail="По текущему основному подразделению" action={() => navigate("personnel")} />
        <Kpi label="Доступны на 15 минут" value={data.workforce.reservable_next_15m}
          detail="Проверка смен, отсутствий и резервов" action={() => navigate("availability")} />
        <Kpi label="Наряды в работе" value={data.work_orders.in_progress}
          detail={"Назначены: " + data.work_orders.assigned} action={() => navigate("work")} />
        <Kpi label="Приостановленные наряды" value={data.work_orders.on_hold}
          detail="Незакрытые safety holds" action={() => navigate("work")}
          urgent={data.work_orders.on_hold > 0} />
        <Kpi label="Допуски к продлению" value={data.credentials.expiring_within_30d}
          detail={"Просроченных записей: " + data.credentials.expired_records}
          action={() => navigate("credentials")}
          urgent={data.credentials.expiring_within_30d > 0} />
        <Kpi label="Резервирование за 30 дней"
          value={hours(data.workload.reserved_hours) + " ч"}
          detail={"Ресурсов с резервами: " + data.workload.resources_with_reservations}
          action={() => navigate("availability")} />
      </div>

      <div className="ops-section-grid">
        <section className="ops-panel">
          <div className="ops-section-heading">
            <div>
              <h3>Динамика нарядов</h3>
              <p>Созданы и завершены по датам UTC за последние 30 календарных дней</p>
            </div>
          </div>
          <div className="ops-chart-legend">
            <span><i className="ops-swatch ops-created" /> Созданы</span>
            <span><i className="ops-swatch ops-completed" /> Завершены</span>
          </div>
          <div className="ops-chart-scroll">
            <div className="ops-chart" role="img"
              aria-label="Столбчатая диаграмма количества созданных и завершённых нарядов по дням">
              {data.trends.map((row, index) => (
                <div className="ops-chart-day" key={row.day}>
                  <div className="ops-chart-bars">
                    <div className="ops-bar ops-created"
                      style={{ height: (row.created / maxTrend * 100) + "%" }}
                      title={row.day + ": создано " + row.created} />
                    <div className="ops-bar ops-completed"
                      style={{ height: (row.completed / maxTrend * 100) + "%" }}
                      title={row.day + ": завершено " + row.completed} />
                  </div>
                  <small>{index % 5 === 0 || index === data.trends.length - 1
                    ? row.day.slice(8) : " "}</small>
                </div>
              ))}
            </div>
          </div>
          {data.trends.every((row) => row.created === 0 && row.completed === 0) &&
            <p className="ops-empty">За указанный период событий нет.</p>}
        </section>

        <section className="ops-panel">
          <h3>Статусы нарядов</h3>
          <p>Текущее состояние всех нарядов в выбранной области</p>
          <div className="ops-status-list">
            {workLabels.map(({ key, label }) => (
              <div className="ops-status-row" key={key}>
                <span>{label}</span><strong>{data.work_orders[key]}</strong>
              </div>
            ))}
          </div>
          <p className="ops-footnote">
            Резервирование — плановая занятость, не процент фактической загрузки.
          </p>
        </section>

        <section className="ops-panel">
          <h3>Резервирование по подразделениям</h3>
          <p>Часы за 30 дней, сгруппированные по текущей принадлежности ресурсов</p>
          {data.workload.by_unit.length === 0
            ? <p className="ops-empty">В выбранной области резервирований нет.</p>
            : <div className="ops-load-list">
              {data.workload.by_unit.map((row) => (
                <div className="ops-load-row" key={row.unit_id}>
                  <div><span>{row.unit_name}</span><strong>{hours(row.reserved_hours)} ч</strong></div>
                  <div className="ops-load-track">
                    <div style={{ width: (row.reserved_hours / maxUnit * 100) + "%" }} />
                  </div>
                </div>
              ))}
            </div>}
        </section>

        <section className="ops-panel">
          <h3>Контроль допусков</h3>
          <p>Только записи видимых активных сотрудников</p>
          <div className="ops-status-list">
            <div className="ops-status-row">
              <span>Истекают в течение 30 дней</span>
              <strong>{data.credentials.expiring_within_30d}</strong>
            </div>
            <div className="ops-status-row">
              <span>Просроченные записи</span>
              <strong>{data.credentials.expired_records}</strong>
            </div>
            <div className="ops-status-row">
              <span>Ожидают проверки</span>
              <strong>{data.credentials.pending_records}</strong>
            </div>
          </div>
          <button type="button" onClick={() => navigate("credentials")}>
            К документам и допускам ›
          </button>
        </section>
      </div>

      <section className="ops-panel">
        <h3>Наряды на удержании</h3>
        <p>До 8 незакрытых работ; приоритетные показаны первыми</p>
        {data.holds.length === 0 ? <p className="ops-empty">Приостановленных нарядов нет.</p>
          : <ul className="ops-holds">
            {data.holds.map((item) => (
              <li key={item.id}>
                <span><strong>{item.code}</strong> — {item.title}</span>
                <span className="ops-priority">{item.priority}</span>
              </li>
            ))}
          </ul>}
        <button type="button" onClick={() => navigate("work")}>Открыть наряды ›</button>
      </section>
      <p className="workspace-warning">
        Только синтетические данные: это операционная аналитика, а не разрешение
        на выполнение опасных работ. Safety gates применяются исключительно сервером.
        Показатели не заменяют проверку персонала, допусков и бригады перед назначением.
      </p>
    </section>
  );
}
