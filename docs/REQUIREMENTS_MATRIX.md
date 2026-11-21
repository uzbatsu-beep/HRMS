# TWM — матрица требований и трассируемости

**Актуализация:** `main` @ `edd25510` (2026-11-21). Историческая базовая матрица от 2026-11-19 пересмотрена по фактически слитым PR #27–#33. **Область:** только синтетические данные.  
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
| FR-15 | Configurator v2: типизированные формы и управляемые состояния информационных сервисных заявок | I | P1 | [ADR-0025](adr/0025-configurator-v2-service-intake.md), [Workflow API](../backend/app/configuration/workflow_router.py), [tests](../backend/tests/test_configuration.py) |
| FR-16 | Полный, постраничный и детерминированный поиск исполнителей | I | P1 | [ADR-0024](adr/0024-candidate-pagination-postgres-races.md), PR #31 merged, PostgreSQL race CI |
| FR-17 | Независимое утверждение и публикация версий Configurator v2, pinned instance workflows и аудит | I | P1 | [ADR-0025](adr/0025-configurator-v2-service-intake.md), PR #32 merged, ограниченный non-safety scope |
| FR-18 | Шаблоны ролей, операции Work Management в fine-grained RBAC | I | P1 | [ADR-0023](adr/0023-work-operations-role-templates.md), PR #30 merged (exact-unit grants, не полный глобальный RBAC) |
| FR-19 | Импорт/экспорт, интеграция ERP/CMMS/EAM | N | P2 | G7, контракт и синхронизация |
| FR-20 | Настоящее хранилище доказательств и защищённая выдача файлов | N | P0 до пилота при требовании файлов | Метаданные есть, файловое хранилище не подтверждено; G6 |
| FR-21 | Рабочий трёхколоночный интерфейс, единый контекст и поиск | I | P1 | [App](../frontend/src/App.tsx), [E2E context](../frontend/e2e/tests/05-workspace-context.spec.ts) |
| NFR-01 | Argon2id, отзывные cookie-сессии, CSRF | I | P0 | [Identity](../backend/app/identity/security.py), [auth test](../backend/tests/test_identity_auth.py) |
| NFR-02 | Ограничение попыток входа и снижение риска credential stuffing (не полноценная account-lockout/MFA система) | I | P0 | [login](../backend/app/identity/router.py), [ADR-0022](adr/0022-login-throttling-csrf.md), PR #28 merged; не замена MFA/SSO |
| NFR-03 | Protected `main`, PR-only merge, обязательные CI checks | I | P0 | [Ruleset #27708090](MAIN_PROTECTION.md) active, PR #35 blocked on failed CI; прямой push не проверен |
| NFR-04 | CI: пять обязательных jobs (backend, frontend, Playwright, PostgreSQL DR, HTTPS smoke) | I | P0 | [Workflow](../.github/workflows/ci.yml), [main CI](https://github.com/uzbatsu-beep/HRMS/actions/runs/44676505208) |
| NFR-05 | TLS/secrets/SSO/защита PII в production | P | P0 | Есть dev baseline, отсутствует подтверждённый production-контур; G1/G6 |
| NFR-06 | Восстановление БД (backup/restore), RPO/RTO, retention | P | P0 до пилота | [Runbook](BACKUP_RESTORE_RUNBOOK.md), синтетический CI restore в PR #33; нет доказанных offsite/PITR/RPO/RTO |
| NFR-07 | PostgreSQL race/нагрузочные испытания на нескольких сессиях | P | P1 | Гонки на PostgreSQL подтверждены PR #31; реальная нагрузка и SLO остаются open [INF-07](https://github.com/uzbatsu-beep/HRMS/issues/37) |
| NFR-08 | Воспроизводимый frontend install с lockfile | I | P1 | [package-lock](../frontend/package-lock.json), [CI](../.github/workflows/ci.yml) |
| NFR-09 | Аудит критичных изменений и redacted equipment explorer | I | P1 | [audit explorer](../backend/app/equipment/audit_explorer.py), [ADR-0017](adr/0017-equipment-audit-explorer.md) |
| NFR-10 | Автоматическая реакция на изменения допусков в фоне | P | P0 до использования как эксплуатационный сигнал | Явная revalidation есть; фоновые rechecks/сертифицированные функции нет |

| NFR-11 | Полевое маскирование и аудит чтения ПДн | N | P0 до реальных ПДн | [Draft PR #36](https://github.com/uzbatsu-beep/HRMS/pull/36) 5/5 CI, **не в main**, полная PIA не утверждена |
| NFR-12 | Выделенный локальный Windows/Linux тестовый ПК | N | P1 для локального TEST-ONLY | [Draft PR #38](https://github.com/uzbatsu-beep/HRMS/pull/38), [INF-01](https://github.com/uzbatsu-beep/HRMS/issues/37); пока нет подтверждённого хоста и запуска |

## Правила обновления

- Менять **N → P → I** только после слияния в main и ссылки на конкретные тесты/ADR/PR. Само наличие UI без server enforcement не даёт I.
- Состояние для пилота отмечать **отдельно**, не переименовывать I в «production-ready».
- Каждому последующему PR приложить затронутые ID, тестовые сценарии из [плана приёмки](ACCEPTANCE_PLAN.md), ограничения и миграцию (если есть).
- При изменениях safety-critical policy пересматривать негативные тесты и audit trail даже когда API не меняется.
