
import { useEffect, useState } from "react";

type ReadinessResponse = {
  status: string;
  dependencies: { database: string };
};

type ApiState = "checking" | "ready" | "unavailable";

const modules = [
  { number: "01", title: "Organization", description: "Структура предприятия, службы, подразделения и бригады." },
  { number: "02", title: "Personnel", description: "Профили технических специалистов и трудовые ресурсы." },
  { number: "03", title: "Competence", description: "Компетенции, шкалы оценки и подтверждение навыков." },
  { number: "04", title: "Credentials", description: "Квалификации, сертификаты и допуски." },
  { number: "05", title: "Availability", description: "Смены, календари и загрузка специалистов." },
  { number: "06", title: "Work Management", description: "Заявки, технические задания и назначение исполнителей." },
];

export default function App() {
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [databaseState, setDatabaseState] = useState("Проверка...");

  useEffect(() => {
    const controller = new AbortController();

    fetch("/api/v1/health/ready", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("API returned " + response.status);
        return (await response.json()) as ReadinessResponse;
      })
      .then((data) => {
        setApiState("ready");
        setDatabaseState(data.dependencies.database === "ok" ? "Подключена" : "Не готова");
      })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setApiState("unavailable");
        setDatabaseState("Нет соединения");
      });

    return () => controller.abort();
  }, []);

  const statusText = {
    checking: "Проверяем сервисы",
    ready: "Сервисы доступны",
    unavailable: "Backend недоступен",
  }[apiState];

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="#home" aria-label="TWM — главная">
          <span className="brand-mark">T</span>
          <span>
            <strong>TWM</strong>
            <small>TECHNICAL WORKFORCE MANAGEMENT</small>
          </span>
        </a>
        <div className="topbar-meta">
          <span className="environment">DEVELOPMENT</span>
          <span className={"status-dot " + apiState} aria-hidden="true" />
          <span className="status-text" role="status">{statusText}</span>
        </div>
      </header>

      <section className="hero" id="home">
        <div className="eyebrow">PROJECT FOUNDATION · 0.1.0</div>
        <h1>Управление техническими<br /><span>компетенциями и ресурсами</span></h1>
        <p>
          Единая рабочая среда для внутренних технических служб производственного предприятия:
          от профиля специалиста и подтверждённых допусков до доступности и назначения работ.
        </p>
        <div className="hero-note">
          <span className="note-icon">i</span>
          <span>Это базовая версия приложения. Функциональные доменные модули будут подключаться последовательно.</span>
        </div>
      </section>

      <section className="system-panel" aria-labelledby="system-title">
        <div className="section-heading">
          <div>
            <div className="eyebrow">RUNTIME</div>
            <h2 id="system-title">Состояние системы</h2>
          </div>
          <span className={"state-pill " + apiState}>
            {apiState === "ready" ? "ONLINE" : apiState === "checking" ? "CHECKING" : "OFFLINE"}
          </span>
        </div>
        <div className="runtime-grid">
          <div className="runtime-item">
            <span className="runtime-label">REST API</span>
            <strong>{apiState === "ready" ? "Доступен" : apiState === "checking" ? "Проверка" : "Недоступен"}</strong>
            <small>/api/v1/health/ready</small>
          </div>
          <div className="runtime-item">
            <span className="runtime-label">PostgreSQL</span>
            <strong>{databaseState}</strong>
            <small>Проверка через SELECT 1</small>
          </div>
          <div className="runtime-item">
            <span className="runtime-label">API documentation</span>
            <strong><a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">Открыть Swagger ↗</a></strong>
            <small>OpenAPI / FastAPI</small>
          </div>
        </div>
        {apiState === "unavailable" && (
          <p className="error-hint">Проверьте, что Docker Compose запущен и backend прошёл миграции базы данных.</p>
        )}
      </section>

      <section className="modules-section" aria-labelledby="modules-title">
        <div className="section-heading">
          <div>
            <div className="eyebrow">DOMAIN MAP</div>
            <h2 id="modules-title">Функциональная архитектура</h2>
          </div>
          <span className="section-caption">Целевые домены платформы</span>
        </div>
        <div className="module-grid">
          {modules.map((module) => (
            <article className="module-card" key={module.number}>
              <span className="module-number">{module.number}</span>
              <h3>{module.title}</h3>
              <p>{module.description}</p>
              <span className="module-state">ЗАПЛАНИРОВАНО</span>
            </article>
          ))}
        </div>
      </section>

      <footer className="footer">
        <span>TWM · Technical Workforce Management</span>
        <span>Foundation build · 0.1.0</span>
      </footer>
    </main>
  );
}
