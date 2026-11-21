# TWM / HRMS — Technical Workforce Management

Конфигурируемое приложение для управления специалистами технических служб: АСУ ТП, КИПиА, электрика, механика, робототехника, энергетика и метрология. Объединяет оргструктуру, сотрудников, подтверждённые компетенции, допуски, смены, наряды, оборудование и бригады.

**Актуализация: 2026-11-21 · `main`: после PR #39/#38/#36 · [GPL-3.0-only](LICENSE).** Система **не** является SCADA, промышленной системой функциональной безопасности, юридически значимой PTW/LOTO либо системой расчёта зарплаты.

## Режим эксплуатации: TEST-ONLY

**NO-GO для реальных персональных данных сотрудников и производственного пилота.** Успешные CI, пользовательский интерфейс и PR не подтверждают юридическую, ИБ- и эксплуатационную готовность. Для первоначальных испытаний выбран **отдельный Windows/Linux ПК, только localhost, только синтетические данные**; оборудование и его характеристики ещё не подтверждены.

## Быстрый запуск на локальном ПК

Нужны Git и Docker Compose v2 (Windows 11: Docker Desktop + WSL2 с Linux containers; Linux: Docker Engine + Compose plugin). Команды из терминала на **самом ПК**:

```bash
git clone https://github.com/uzbatsu-beep/HRMS.git
cd HRMS
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose exec backend alembic current
docker compose exec backend python -m app.identity.bootstrap_admin
```

Создайте отдельного тестового администратора. Откройте интерфейс `http://localhost:5173`, readiness `http://localhost:8000/api/v1/health/ready`. Остановка **с сохранением данных**: `docker compose down` (не `down -v`).

Штатный `docker-compose.yml` использует HTTP, Vite dev server, `--reload` и тестовые значения; он **не** предназначен для LAN/production. Нельзя менять его `127.0.0.1` на `0.0.0.0` ради доступа с соседнего ПК. Отдельный `deploy/compose.pilot.yml` содержит reference TLS/secret-baseline, но требует настройки PKI, ACL и внешней приёмки. Подробнее: [DEVELOPMENT](docs/DEVELOPMENT.md) · [инструкция тестового ПК](docs/LOCAL_TEST_STAND_INF01.md).

## Технологии

| Компонент | Реализация |
|---|---|
| Frontend | React 19, TypeScript, Vite; трёхколоночный интерфейс, контекст предприятия/подразделения/сотрудника |
| Backend | Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2.x |
| База данных | PostgreSQL 16, Alembic, история и версионируемые правила |
| Безопасность | Argon2id, cookie/CSRF, persisted login throttle, enterprise/unit RBAC и operation grants |
| Автоматические проверки | Ruff + pytest + migrations, TS/Vite, Playwright Chromium, backup/restore и HTTPS smoke |
| Развёртывание | Docker Compose для dev; отдельный reference профиль для G6 |

Основная последовательность: оргструктура → ресурс сотрудника → компетенции/допуски → доступность → наряды и бригады → оборудование → аналитика → ограниченный Configurator. Backend остаётся источником полномочий и safety gates, UI их не обходит.

## Состояние разработки и G6

- В `main` объединены PR #3–#33 и дополнительно PR #39, #38 и #36. Защита `main` [Ruleset #27708090](docs/MAIN_PROTECTION.md) активна и обязательны **5 GitHub Actions checks**.
- [PR #36](https://github.com/uzbatsu-beep/HRMS/pull/36): частичное маскирование ПДн и аудит чтения реализованы; **полная PIA и G6 не утверждены**.
- [PR #38](https://github.com/uzbatsu-beep/HRMS/pull/38): инструкция отдельного Windows/Linux ПК в `main`; физический хост ещё не принят.
- [Issue #37](https://github.com/uzbatsu-beep/HRMS/issues/37): инфраструктура, TLS/секреты, RPO/RTO, PIA, нагрузка, UAT остаются открытыми. Выбор локального ПК **не означает** допуск реальных сотрудников.
- Подтверждённые программные проверки — не альтернатива заводским процедурам безопасности, LOTO/permit и аппаратным interlocks.

## Контроль качества

```bash
# Из корня при работающем Compose
docker compose exec backend ruff check .
docker compose exec backend pytest

# Из frontend после npm ci
npm run check
npm run test:e2e:check
npm run build
```

Для полной браузерной приёмки используйте изолированную среду [E2E_ACCEPTANCE](docs/E2E_ACCEPTANCE.md). Пять обязательных заданий определены в [.github/workflows/ci.yml](.github/workflows/ci.yml); автоматический HTTP health probe не является продуктовым нагрузочным тестом.

## Документация

- **[Единый индекс документации](docs/DOCUMENTATION_INDEX.md)** — содержание, статус и приоритет источников.
- **[Аудит репозитория 2026-11-21](docs/REPOSITORY_AUDIT_2026-11-21.md)** — подтверждённые факты, исправления, границы CI и открытые риски.
- [Реализация](docs/IMPLEMENTATION_STATUS.md) · [Матрица требований](docs/REQUIREMENTS_MATRIX.md) · [Дорожная карта v0.3](docs/ROADMAP_V0_3.md) · [План приёмки](docs/ACCEPTANCE_PLAN.md).
- [G6 readiness](docs/PILOT_READINESS_G6.md) · [PR36 privacy controls](docs/PR36_SECURITY_PRIVACY.md) · [Инфраструктурные решения](docs/PILOT_INFRASTRUCTURE_DECISIONS.md) · [Backup/restore](docs/BACKUP_RESTORE_RUNBOOK.md) · [Load plan](docs/LOAD_TEST_PLAN.md).
- [История развития](docs/FEATURE_HISTORY.md) · [Архитектурные ADR](docs/adr/) · [DEVELOPMENT](docs/DEVELOPMENT.md).
- [CONTRIBUTING](CONTRIBUTING.md) · [SECURITY](SECURITY.md) · [AGENTS](AGENTS.md) · [GEMINI](GEMINI.md).

Изменения ведутся в отдельных ветках и PR; **слияние — только по явному согласованию владельца**, даже при зелёном CI.
