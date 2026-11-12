
# TWM — Technical Workforce Management

Конфигурируемое веб-приложение для управления внутренними техническими службами производственного предприятия: механика, электрика, энергетика, АСУ ТП, робототехника, метрология и другие инженерные подразделения.

**Репозиторий:** uzbatsu-beep/HRMS  
**План разработки:** docs/DEVELOPMENT_PLAN.md  
**Инструкции Gemini:** GEMINI.md  
**Архитектурное решение:** docs/adr/0001-modular-monolith.md  
**Прототип:** TWM_Configurable_Prototype_v0.1.html

## Назначение

TWM помогает руководителю технической службы управлять организационной структурой, компетенциями, квалификациями и допусками специалистов, сменами, доступностью, техническими заданиями и назначением исполнителей.

TWM не является системой расчёта заработной платы, SCADA или полноценной EAM/CMMS.

## Состояние проекта

Проект находится на этапе foundation. HTML-прототип сохраняется как визуальный и функциональный референс. Текущая foundation-сборка добавляет React frontend, FastAPI backend, PostgreSQL, начальную Alembic-миграцию, health/readiness endpoints и CI.

## Быстрый запуск через Docker Compose

Требования:
- Docker Engine / Docker Desktop с Compose v2;
- свободные локальные порты 5173, 5432 и 8000.

1. При необходимости скопируйте .env.example в .env и измените локальные параметры.
2. Запустите:

    docker compose up --build

3. Откройте:
- Web application: http://localhost:5173
- API root: http://localhost:8000/
- Swagger / OpenAPI: http://localhost:8000/docs
- Liveness: http://localhost:8000/api/v1/health/live
- Readiness (включает PostgreSQL): http://localhost:8000/api/v1/health/ready

Остановить контейнеры: Ctrl+C, затем docker compose down. Чтобы также удалить локальный том базы данных, выполните docker compose down -v (данные будут удалены).

Учетные данные по умолчанию предназначены только для разработки. Для общей или production-среды нужны отдельные секреты, TLS, политика сетевого доступа, аутентификация и защищённое файловое хранилище.

## Локальный запуск backend без Docker

Из корня репозитория создайте виртуальное окружение и установите backend:

    python -m venv .venv
    python -m pip install -e "./backend[dev]"

Для Windows PowerShell активируйте окружение командой:

    .venv\Scripts\Activate.ps1

Установите TWM_DATABASE_URL на доступный PostgreSQL, затем:

    cd backend
    alembic upgrade head
    uvicorn app.main:app --reload

## Локальный запуск frontend

Во втором терминале:

    cd frontend
    npm install
    npm run dev

Vite проксирует /api в http://127.0.0.1:8000. Для изменения адреса задайте VITE_API_PROXY_TARGET.

## Проверки

Backend, из backend/:

    ruff check .
    pytest

Frontend, из frontend/:

    npm install
    npm run check
    npm run build

GitHub Actions выполняет backend lint, миграции и тесты на PostgreSQL, а также TypeScript check и production build frontend при Pull Request и push в main.

## Ограничения

Это foundation-сборка, а не production-система. Аутентификация, серверный RBAC, аудит, защита персональных данных, документное хранилище, предметные модули и назначение технических работ ещё не реализованы. Не вводите реальные персональные данные, юридически значимые документы и не используйте эту версию для принятия решений по промышленной безопасности.
