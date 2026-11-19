# TWM — матрица требований и трассируемости

**Baseline:** `main` @ `093e4f8`, 2026-11-19. **Область:** синтетические данные.  
**Статусы:** **I** — реализовано в main и есть соответствующий код/тесты; **P** — частично, необходима доработка; **N** — не реализовано / не подтверждено. Статус I не означает готовности к production.  
**Приоритеты:** P0 — блокирует безопасную эксплуатацию или базовый сценарий; P1 — важно для пилотного рабочего процесса; P2 — последующее развитие.

| ID | Требование / наблюдаемое поведение | Статус | Приоритет | Проверяемый источник / план |
|---|---|---|---|---|
| FR-01 | Произвольное дерево подразделений, перемещение без циклов | I | P1 | [Organization](../backend/app/organization/), [test_organization](../backend/tests/test_organization.py) |
| FR-02 | Tenant isolation и scope для admin/manager/viewer | I | P0 | [Organization access](../backend/app/organization/access.py), [test_organization](../backend/tests/test_organization.py) |
| FR-03 | Датированное основное назначение, перевод, архивирование Person | I | P1 | [Personnel](../backend/app/personnel/), [test_personnel](../backend/tests/test_personnel.py) |
| FR-04 | Версионные шкалы компетенций и независимое review | I | P1 | [Competence](../backend/app/competence/), [test_competence](../backend/tests/test_competence.py) |
| FR-05 | Реестр документов с верификацией, сроками и отзывом | I | P0 | [Credentials](../backend/app/credentials/), [test_credentials](../backend/tests/test_credentials.py) |
| FR-06 | Запрет назначения без действующих навыков и допусков | I | P0 | [Matching](../backend/app/work/service.py), [test_work](../backend/tests/test_work.py) |
| FR-07 | Смены с зонами IANA, отсутствия и резервирование | I | P1 | [Availability](../backend/app/availability/), [test_availability](../backend/tests/test_availability.py) |
| FR-08 | Назначение+резервирование в одной транзакции | I | P0 | [Work](../backend/app/work/), [test_work](../backend/tests/test_work.py) |
| FR-09 | Участники бригады, повторная проверка перед началом и on_hold | I | P0 | [Work execution](../backend/app/work/execution.py), [E2E](../frontend/e2e/tests/03-work.spec.ts) |
| FR-10 | Реестр оборудования, связанные наряды, downtime и цифровое согласование | I | P1 | [Equipment](../backend/app/equipment/), [ADR-0013](adr/0013-equipment-permit-workflow.md) |
| FR-11 | Независимое согласование политики навыков оборудования, версии | I | P1 | [ADR-0018](adr/0018-equipment-policy-governance.md), [ADR-0019](adr/0019-equipment-skill-policy-versions.md) |
| FR-12 | Delegated exact-unit read/propose/review политики и review персонала | I | P1 | [Permissions](../backend/app/organization/permissions.py), [ADR-0021](adr/0021-personnel-review-permissions.md) |
| FR-13 | Dashboard 30 дней с RBAC и документированными метриками | I | P1 | [Analytics](../backend/app/analytics/router.py), [ADR-0011](adr/0011-operational-analytics.md) |
| FR-14 | Дополнительные поля Person: validation → independent approval → publish | I | P1 | [Configuration](../backend/app/configuration/), [test_configuration](../backend/tests/test_configuration.py) |
| FR-15 | Configurator v2: ограниченные формы, состояния и независимые маршруты заявок технической службы | PR #32 (Draft) | P1 | [ADR-0025](adr/0025-configurator-v2-service-intake.md), [Workflow API](../backend/app/configuration/workflow_router.py), [tests](../backend/tests/test_configuration.py) |
| FR-15 | Рабочий трёхколоночный интерфейс, единый контекст и поиск | I | P1 | [App](../frontend/src/App.tsx), [E2E context](../frontend/e2e/tests/05-workspace-context.spec.ts) |
| FR-16 | Полный, постраничный и детерминированный поиск исполнителей | P | P1 | Сейчас первый 100; G4 / PR #31 |
| FR-17 | Версионируемые маршруты, статусы и формы Configurator v2 | N | P1 | G5 / PR #32 |
| FR-18 | Шаблоны ролей, операции Work Management в fine-grained RBAC | P | P1 | Сейчас только 5 operation grants; G3 / PR #30 |
| FR-19 | Импорт/экспорт, интеграция ERP/CMMS/EAM | N | P2 | G7, контракт и синхронизация |
| FR-20 | Настоящее хранилище доказательств и защищённая выдача файлов | N | P0 до пилота при требовании файлов | Метаданные есть, файловое хранилище не подтверждено; G6 |
| NFR-01 | Argon2id, отзывные cookie-сессии, CSRF | I | P0 | [Identity](../backend/app/identity/security.py), [auth test](../backend/tests/test_identity_auth.py) |
| NFR-02 | Rate limit/lockout и противодействие credential stuffing | N | P0 | [login](../backend/app/identity/router.py); G1 / PR #28 |
| NFR-03 | Protected `main`, PR-only merge, обязательные CI checks | N | P0 | Проверено 2026-11-19: main protected=false, rulesets=[]; TD-01 |
| NFR-04 | CI: lint, backend tests/migrations, TS/build, Playwright | I | P0 | [Workflow](../.github/workflows/ci.yml), [CI 44280041886](https://github.com/uzbatsu-beep/HRMS/actions/runs/44280041886) |
| NFR-05 | TLS/secrets/SSO/защита PII в production | P | P0 | Есть dev baseline, отсутствует подтверждённый production-контур; G1/G6 |
| NFR-06 | Восстановление БД (backup/restore), RPO/RTO, retention | N | P0 до пилота | G6, операционный протокол |
| NFR-07 | PostgreSQL race/нагрузочные испытания на нескольких сессиях | P | P1 | Транзакционные проверки в коде; G4 |
| NFR-08 | Воспроизводимый frontend install с lockfile | I | P1 | [package-lock](../frontend/package-lock.json), [CI](../.github/workflows/ci.yml) |
| NFR-09 | Аудит критичных изменений и redacted equipment explorer | I | P1 | [audit explorer](../backend/app/equipment/audit_explorer.py), [ADR-0017](adr/0017-equipment-audit-explorer.md) |
| NFR-10 | Автоматическая реакция на изменения допусков в фоне | P | P0 до использования как эксплуатационный сигнал | Явная revalidation есть; фоновые rechecks/сертифицированные функции нет |

## Правила обновления

- Менять **N → P → I** только после слияния в main и ссылки на конкретные тесты/ADR/PR. Само наличие UI без server enforcement не даёт I.
- Состояние для пилота отмечать **отдельно**, не переименовывать I в «production-ready».
- Каждому последующему PR приложить затронутые ID, тестовые сценарии из [плана приёмки](ACCEPTANCE_PLAN.md), ограничения и миграцию (если есть).
- При изменениях safety-critical policy пересматривать негативные тесты и audit trail даже когда API не меняется.
