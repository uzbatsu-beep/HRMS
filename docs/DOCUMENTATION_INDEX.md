# TWM / HRMS — единый индекс документации

**Текущая сверка:** 2026-11-21, `main` `edd25510`. Этот индекс разграничивает текущее состояние кода, предложенные изменения и исторические решения. **Ни один документ не подтверждает готовность к обработке реальных персональных данных сам по себе.**

## Приоритет источников

1. **GitHub `main` + последний успешный CI + Ruleset:** фактически слитая реализация, технические доказательства.
2. **[IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md), [REQUIREMENTS_MATRIX](REQUIREMENTS_MATRIX.md), [PILOT_READINESS_G6](PILOT_READINESS_G6.md):** актуальное отражение продукта, задач и эксплуатационных блокировок.
3. **[ROADMAP_V0_3](ROADMAP_V0_3.md), [Issue #37](https://github.com/uzbatsu-beep/HRMS/issues/37):** план, приоритеты, открытые решения.
4. **[ADR](adr/), [DEVELOPMENT_PLAN](DEVELOPMENT_PLAN.md), [FEATURE_HISTORY](FEATURE_HISTORY.md):** историческая основа. Статусы `Proposed` внутри ADR могут отражать дату написания **до слияния соответствующего PR**.
5. **Draft PR [#36](https://github.com/uzbatsu-beep/HRMS/pull/36) и [#38](https://github.com/uzbatsu-beep/HRMS/pull/38):** предложенные средства, пока **не входят в `main`**.

[Аудит Git и документации на 2026-11-21](REPOSITORY_AUDIT_2026-11-21.md) — отдельный протокол исходного состояния, найденных проблем, исправлений и оставшихся P0.

## Операционный справочник

| Задача | Документы | Действующий статус |
|---|---|---|
| Общее описание и localhost запуск | [README](../README.md), [DEVELOPMENT](DEVELOPMENT.md) | Разработка, synthetic test |
| Отдельный Windows/Linux ПК (INF-01) | [Draft #38 / LOCAL_TEST_STAND_INF01](https://github.com/uzbatsu-beep/HRMS/blob/docs/g6-local-test-stand-inf01/docs/LOCAL_TEST_STAND_INF01.md) | Инструкция в Draft; ПК ещё не проверен |
| Browser E2E и synthetic fixtures | [E2E_ACCEPTANCE](E2E_ACCEPTANCE.md) | Автоматическая приёмка |
| Текущий набор функций | [IMPLEMENTATION_STATUS](IMPLEMENTATION_STATUS.md), [FEATURE_HISTORY](FEATURE_HISTORY.md) | Не означает pilot GO |
| Трассировка требований | [REQUIREMENTS_MATRIX](REQUIREMENTS_MATRIX.md) | Текущий реестр |
| Roadmap и архитектура | [ROADMAP_V0_3](ROADMAP_V0_3.md), [DEVELOPMENT_PLAN](DEVELOPMENT_PLAN.md) | Состояние + история |
| Приёмка и роль владельца | [ACCEPTANCE_PLAN](ACCEPTANCE_PLAN.md) | План тестов и evidence |
| UX | [UI_UX_ROADMAP](UI_UX_ROADMAP.md) | Изменения + первоначальные предложения |
| Основная ветка и CI | [MAIN_PROTECTION](MAIN_PROTECTION.md), [CI](../.github/workflows/ci.yml) | Ruleset active; пять обязательных jobs |
| Security threat model | [SECURITY_HARDENING_PLAN](SECURITY_HARDENING_PLAN.md), [SECURITY](../SECURITY.md) | Внешние P0 остаются |
| Privacy/персональные данные | [PRIVACY_IMPACT_CHECKLIST](PRIVACY_IMPACT_CHECKLIST.md), [Draft PR #36](https://github.com/uzbatsu-beep/HRMS/pull/36) | Не готово к реальным ПДн |
| TLS, секреты и развёртывание | [PILOT_READINESS_G6](PILOT_READINESS_G6.md), [ADR-0026](adr/0026-pilot-deployment-and-recovery.md) | Reference без signoff |
| Backup/DR | [BACKUP_RESTORE_RUNBOOK](BACKUP_RESTORE_RUNBOOK.md) | CI drill без offsite/PITR |
| Нагрузочные испытания | [LOAD_TEST_PLAN](LOAD_TEST_PLAN.md) | План; реальные p95 не измерены |
| Обратная связь | [CONTRIBUTING](../CONTRIBUTING.md), [SECURITY](../SECURITY.md) | Никаких секретов/ПДн в issues |
| Инструкции ИИ-агентов | [AGENTS](../AGENTS.md), [GEMINI](../GEMINI.md) | Соблюдать границы решений |

## Архитектурные решения

Каждый ADR сохраняет исходные инженерные решения. Пометка «merged» отражает **исключительно программный PR**, не допуск к промышленной эксплуатации.

| ADR | Область | Фактический этап в `main` |
|---|---|---|
| [ADR-0001](adr/0001-modular-monolith.md) | Модульный монолит | Foundation merged (test-only) |
| [ADR-0002](adr/0002-local-identity.md) | Идентификация и сессии | #4 merged (test-only) |
| [ADR-0003](adr/0003-organization-scopes.md) | Оргструктура и область видимости | #5 merged (test-only) |
| [ADR-0004](adr/0004-personnel.md) | Карточки и назначение персонала | #6 merged (test-only) |
| [ADR-0005](adr/0005-competence.md) | Компетенции и независимые решения | #7 merged (test-only) |
| [ADR-0006](adr/0006-credentials-safety.md) | Документы и проверка допусков | #8 merged (test-only) |
| [ADR-0007](adr/0007-availability-scheduling.md) | Смены и резервирование | #9 merged (test-only) |
| [ADR-0008](adr/0008-work-management.md) | Наряды | #10 merged (test-only) |
| [ADR-0009](adr/0009-work-crews-and-safety-holds.md) | Бригады, hold/revalidate | #11 merged (test-only) |
| [ADR-0010](adr/0010-shared-workspace-context.md) | Общий рабочий контекст | #14 merged (test-only) |
| [ADR-0011](adr/0011-operational-analytics.md) | Аналитика | #15 merged (test-only) |
| [ADR-0012](adr/0012-governed-configuration.md) | Контролируемые атрибуты | #16 merged (test-only) |
| [ADR-0013](adr/0013-equipment-permit-workflow.md) | Оборудование и разрешения | #17 merged (test-only) |
| [ADR-0014](adr/0014-equipment-skill-readiness.md) | Готовность по навыкам | #18 merged (test-only) |
| [ADR-0015](adr/0015-equipment-downtime.md) | Простои | #19 merged (test-only) |
| [ADR-0016](adr/0016-crew-readiness-snapshot.md) | Срез готовности бригады | #20 merged (test-only) |
| [ADR-0017](adr/0017-equipment-audit-explorer.md) | Аудит оборудования | #21 merged (test-only) |
| [ADR-0018](adr/0018-equipment-policy-governance.md) | Согласование оборудования | #22 merged (test-only) |
| [ADR-0019](adr/0019-equipment-skill-policy-versions.md) | Версии требований к навыкам | #23 merged (test-only) |
| [ADR-0020](adr/0020-scoped-permissions.md) | Полномочия exact-unit | #24 merged (test-only) |
| [ADR-0021](adr/0021-personnel-review-permissions.md) | Review персонала | #25 merged (test-only) |
| [ADR-0022](adr/0022-login-throttling-csrf.md) | Троттлинг/CSRF | #28 merged (test-only) |
| [ADR-0023](adr/0023-work-operations-role-templates.md) | Work operation grants | #30 merged (test-only) |
| [ADR-0024](adr/0024-candidate-pagination-postgres-races.md) | Пагинация/race | #31 merged (test-only) |
| [ADR-0025](adr/0025-configurator-v2-service-intake.md) | Configurator v2 | #32 merged (test-only) |
| [ADR-0026](adr/0026-pilot-deployment-and-recovery.md) | G6 TLS/DR reference | #33 merged (test-only) |

## Разграничение статусов

- **Merged:** код вошёл в `main`; для безопасного пилота этого недостаточно.
- **Draft:** код/документ рассматривается и может иметь зелёный CI, но отсутствует в `main`.
- **TEST-ONLY:** отдельный локальный Windows/Linux ПК, localhost, тестовый администратор и синтетические данные.
- **READY FOR UAT:** только после доказанного стенда, политики доступа, PKI/TLS, backup/DR и плана тестов.
- **PILOT GO:** подписанные product + ИБ/ПДн + operations acceptance, без незакрытых P0.
- На 2026-11-21 **G6 остаётся NO-GO для реальных ПДн**.

## Поддержание документации

- Изменение API/permissions/schema — тесты, Alembic и обновление ADR/трассировки. Историю не переписывать задним числом; добавлять текущие пояснения.
- После слияния PR обновлять статус в индексе и матрице. До слияния всегда писать `Draft PR`.
- Указывать Git SHA и Actions run; старые количества PASS нельзя приписывать новому коммиту.
- В CI локальные ссылки Markdown проверяются автоматически. Внешние ссылки и семантическую актуальность нужно перепроверять по первоисточнику.
- [CODE_OF_CONDUCT](../CODE_OF_CONDUCT.md) — самостоятельная policy сообщества; её лицензионный текст не изменяется массовой технической редактурой.
