import { useEffect, useState } from "react";
import AuthPanel from "./AuthPanel";
import OrganizationPanel from "./OrganizationPanel";
import PersonnelPanel from "./PersonnelPanel";
import CompetencePanel from "./CompetencePanel";
import CredentialsPanel from "./CredentialsPanel";
import AvailabilityPanel from "./AvailabilityPanel";
import WorkPanel from "./WorkPanel";
import ContextRail, { type PersonFocus } from "./ContextRail";
import { useWorkspace } from "./WorkspaceContext";
import WorkspaceSearch from "./WorkspaceSearch";
import WorkspaceBreadcrumbs from "./WorkspaceBreadcrumbs";

type ReadinessResponse = {
  status: string;
  dependencies: { database: string };
};
type ApiState = "checking" | "ready" | "unavailable";
type Page = "dashboard" | "organization" | "personnel" | "competence"
  | "credentials" | "availability" | "work" | "access" | "system";

const navigation: { page: Page; icon: string; label: string; description: string }[] = [
  { page: "dashboard", icon: "⌂", label: "Обзор", description: "Рабочая панель" },
  { page: "organization", icon: "▤", label: "Оргструктура", description: "Предприятия и службы" },
  { page: "personnel", icon: "♙", label: "Персонал", description: "Карточки специалистов" },
  { page: "competence", icon: "▦", label: "Компетенции", description: "Навыки и оценка" },
  { page: "credentials", icon: "▣", label: "Документы и допуски", description: "Сертификаты и проверка" },
  { page: "availability", icon: "▥", label: "Смены и загрузка", description: "Графики и занятость" },
  { page: "work", icon: "⚒", label: "Наряды и бригады", description: "Работы и исполнители" },
  { page: "access", icon: "◇", label: "Пользователи", description: "Вход и права доступа" },
  { page: "system", icon: "⚙", label: "Система", description: "API и диагностика" },
];

function pageFromHash(): Page {
  const raw = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  if (raw === "home") return "dashboard";
  const found = navigation.find((item) => item.page === raw);
  return found?.page ?? "dashboard";
}

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const { session, focusPerson: focusWorkspacePerson } = useWorkspace();
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [databaseState, setDatabaseState] = useState("Проверка...");
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const onHash = () => { setPage(pageFromHash()); setMenuOpen(false); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/v1/health/ready", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("API returned " + response.status);
        return await response.json() as ReadinessResponse;
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

  function navigate(destination: string) {
    const target = navigation.find((item) => item.page === destination)?.page ?? "dashboard";
    window.location.hash = target;
    setPage(target);
    setMenuOpen(false);
  }

  function focusPerson(person: PersonFocus) {
    focusWorkspacePerson(person.enterpriseId, person.personId, person.unitId);
    navigate("personnel");
  }

  const active = navigation.find((item) => item.page === page) ?? navigation[0];
  const statusText = {
    checking: "Проверяем сервисы",
    ready: "Сервисы доступны",
    unavailable: "Backend недоступен",
  }[apiState];

  return (
    <div className="workspace">
      <header className="workspace-topbar">
        <div className="workspace-brand-group">
          <button type="button" className="workspace-mobile-toggle"
            aria-label={menuOpen ? "Закрыть меню" : "Открыть меню"}
            aria-expanded={menuOpen} onClick={() => setMenuOpen((value) => !value)}>☰</button>
          <a className="brand" href="#dashboard" aria-label="TWM — обзор">
            <span className="brand-mark">T</span>
            <span><strong>TWM</strong><small>TECHNICAL WORKFORCE MANAGEMENT</small></span>
          </a>
          <span className="workspace-divider" aria-hidden="true" />
          <span className="workspace-context">{active.label}</span>
        </div>
        <div className="workspace-top-meta">
          <WorkspaceSearch openPerson={(person) => {
            focusWorkspacePerson(person.enterprise_id, person.id, person.current_unit_id);
            navigate("personnel");
          }} />
          <span className="environment">DEVELOPMENT</span>
          <span className={"status-dot " + apiState} aria-hidden="true" />
          <span className="status-text" role="status">{statusText}</span>
          <button className="workspace-user" type="button" onClick={() => navigate("access")}>
            {session ? session.user.username : "Войти"}
          </button>
        </div>
      </header>

      <div className="workspace-columns">
        <aside className={`workspace-navigation ${menuOpen ? "open" : ""}`}
          aria-label="Основная навигация">
          <div className="nav-section-label">РАБОЧАЯ СРЕДА</div>
          <nav className="workspace-nav">
            {navigation.map((item) => (
              <a href={`#${item.page}`} key={item.page}
                className={`workspace-nav-item ${page === item.page ? "active" : ""}`}
                aria-current={page === item.page ? "page" : undefined}
                onClick={() => { setPage(item.page); setMenuOpen(false); }}>
                <span className="workspace-nav-icon" aria-hidden="true">{item.icon}</span>
                <span className="workspace-nav-label">
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
              </a>
            ))}
          </nav>
          <div className="nav-footer">
            <span className="nav-footer-dot" />
            <span>HRMS · развитие продукта</span>
            <small>Общий контекст предприятия · PR #14</small>
          </div>
        </aside>

        <main className="workspace-main" id="main-content">
          <div className="workspace-page-heading">
            <div>
              <WorkspaceBreadcrumbs pageLabel={active.label} navigate={navigate} />
              <div className="eyebrow">TWM / {active.page.toUpperCase()}</div>
              <h1>{active.label}</h1>
              <p>{active.description}</p>
            </div>
          </div>
          {page === "dashboard" && (
            <>
              <section className="dashboard-intro">
                <div className="eyebrow">WORKFORCE OPERATIONS</div>
                <h2>Управление техническими ресурсами предприятия</h2>
                <p>Организационная структура, персонал, подтверждённые компетенции,
                  производственные допуски, смены и технические работы — в одной среде.
                  Для перехода к модулю используйте меню слева.</p>
              </section>
              {!session && (
                <section className="workspace-info-card">
                  <h2>Доступ к системе</h2>
                  <p>Для работы со структурой предприятия и персоналом необходимо войти.</p>
                  <button type="button" className="workspace-primary-action"
                    onClick={() => navigate("access")}>Перейти к авторизации</button>
                </section>
              )}
              <section className="dashboard-module-grid" aria-label="Доступные модули">
                {navigation.filter((item) =>
                  !["dashboard", "access", "system"].includes(item.page),
                ).map((item) => (
                  <button type="button" className="dashboard-module" key={item.page}
                    onClick={() => navigate(item.page)}>
                    <span className="workspace-nav-icon" aria-hidden="true">{item.icon}</span>
                    <span><strong>{item.label}</strong><small>{item.description}</small></span>
                    <span aria-hidden="true" className="dashboard-module-arrow">›</span>
                  </button>
                ))}
              </section>
              <p className="workspace-warning">
                Среда предназначена для тестирования на синтетических данных.
                Статус допуска в HRMS не является разрешением на опасные работы.
              </p>
            </>
          )}
          {page === "organization" && <OrganizationPanel />}
          {page === "personnel" && <PersonnelPanel />}
          {page === "competence" && <CompetencePanel />}
          {page === "credentials" && <CredentialsPanel />}
          {page === "availability" && <AvailabilityPanel />}
          {page === "work" && <WorkPanel />}
          {page === "access" && <AuthPanel />}
          {page === "system" && (
            <section className="system-panel" aria-labelledby="system-title">
              <div className="section-heading">
                <div><div className="eyebrow">RUNTIME</div>
                  <h2 id="system-title">Диагностика приложения</h2></div>
                <span className={"state-pill " + apiState}>
                  {apiState === "ready" ? "ONLINE" :
                    apiState === "checking" ? "CHECKING" : "OFFLINE"}
                </span>
              </div>
              <div className="runtime-grid">
                <div className="runtime-item">
                  <span className="runtime-label">REST API</span>
                  <strong>{apiState === "ready" ? "Доступен" : statusText}</strong>
                  <small>/api/v1/health/ready</small>
                </div>
                <div className="runtime-item">
                  <span className="runtime-label">PostgreSQL</span>
                  <strong>{databaseState}</strong><small>Проверка через SELECT 1</small>
                </div>
                <div className="runtime-item">
                  <span className="runtime-label">API documentation</span>
                  <strong><a href="http://localhost:8000/docs" target="_blank"
                    rel="noreferrer">Swagger / OpenAPI ↗</a></strong>
                  <small>FastAPI</small>
                </div>
              </div>
              {apiState === "unavailable" && (
                <p className="error-hint">Проверьте Docker Compose и миграции базы данных.</p>
              )}
            </section>
          )}
        </main>

        <ContextRail
          session={session}
          onPersonSelect={focusPerson}
          onNavigate={navigate}
        />
      </div>
    </div>
  );
}
