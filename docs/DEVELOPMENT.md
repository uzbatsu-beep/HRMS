# Разработка и проверка TWM

> **Актуальность на 2026-11-21:** `main` `edd25510`, только синтетические данные. Документация PR #36/#38 — Draft, не в `main`. Штатный Compose только для localhost; отдельный Windows/Linux тестовый ПК выбран как тип стенда, но ещё не проверен. [Индекс](DOCUMENTATION_INDEX.md) · [G6](PILOT_READINESS_G6.md).

## Первый запуск

Потребуется Docker с Compose v2. Команды выполняются из корня репозитория и подходят для PowerShell. Локальный стек открывает порты 5173 (интерфейс), 8000 (API) и 5432 (PostgreSQL).

```sh
docker compose up --build -d
docker compose ps
docker compose exec backend python -m app.identity.bootstrap_admin
```

Дождитесь состояния `healthy` у backend. Команда создания администратора запросит имя и пароль длиной от 12 символов. При следующих запусках используйте созданную учётную запись. Откройте [приложение](http://localhost:5173) и войдите в разделе «Доступ к системе». Новый стенд имеет пустой реестр. Создание предприятия начинается в «Оргструктуре».

Если интерфейс не получает данные, откройте [проверку готовности API и БД](http://localhost:8000/api/v1/health/ready) и посмотрите `docker compose logs backend db`. Схемы запросов доступны в [Swagger UI](http://localhost:8000/docs). Для остановки с сохранением локальных данных выполните `docker compose down`.

## Где менять код

| Задача | Файлы |
|---|---|
| Оргструктура, область видимости, делегирование прав | [organization](../backend/app/organization/), [personnel](../backend/app/personnel/) |
| Подбор и назначение бригады | [work](../backend/app/work/), [availability](../backend/app/availability/), [equipment](../backend/app/equipment/) |
| Оценка навыков и проверка документов | [competence](../backend/app/competence/), [credentials](../backend/app/credentials/) |
| Рабочее окно, панели, общий контекст | [App.tsx](../frontend/src/App.tsx), [WorkspaceContext.tsx](../frontend/src/WorkspaceContext.tsx) |
| Изменение данных и проверка поведения | [миграции](../backend/migrations/versions/), [тесты API](../backend/tests/), [браузерные сценарии](../frontend/e2e/tests/) |

## Проверки перед PR

Backend можно проверить в работающем локальном Compose. Сервис применяет миграции при старте. Сравните вывод `current` и `heads`, чтобы убедиться, что БД обновлена до последней ревизии.

```sh
docker compose exec backend alembic current
docker compose exec backend alembic heads
docker compose exec backend ruff check .
docker compose exec backend pytest
```

Для проверок интерфейса установите Node.js 22, как в CI. Из корня репозитория выполните:

```sh
cd frontend
npm ci
npm run check
npm run test:e2e:check
npm run build
```

Для новой зависимости запустите `npm install <имя-пакета>` в каталоге `frontend/` и включите обновлённый lock-файл в тот же PR. После изменения зависимостей в уже созданном Compose-стенде обновите именованный том модулей командой `docker compose exec frontend npm ci` из корня и перезапустите сервис через `docker compose restart frontend`.

Браузерная приёмка использует отдельный стек PostgreSQL, вымышленных пользователей и порты 5174/8001. Полная последовательность для Windows, переменные запуска и расположение отчёта приведены в [E2E_ACCEPTANCE.md](E2E_ACCEPTANCE.md). В CI миграции и E2E используют PostgreSQL 16. Многие модульные сценарии pytest используют SQLite в памяти. Команды пяти обязательных заданий CI можно сверить в [ci.yml](../.github/workflows/ci.yml).

## Проверки INF-01 и полный CI

На выбранном Windows/Linux ПК проверить версии ОС, CPU/RAM/SSD, `docker version`, `docker compose version`, Linux containers, а также доступ к портам `5173/8000/5432` только по `127.0.0.1`. В Windows необходимы WSL2/виртуализация и проверка лицензии Docker Desktop. Ни один dev HTTP порт не открывать для корпоративной LAN.

GitHub Actions содержит **пять** требуемых jobs: backend/Ruff/PG16 Alembic/pytest; frontend TS/Vite; Playwright Chromium; backup/isolated PostgreSQL restore; pilot images/HTTPS smoke. Они синхронизированы с [Ruleset](MAIN_PROTECTION.md). Сохраняйте commit SHA и URL соответствующего run; успешный CI не подтверждает PROD/TLS PKI, ПДн, DR RPO/RTO и нагрузочный SLO. Для восстановления не использовать `docker compose down -v`.
