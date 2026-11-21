# TWM/HRMS — технический аудит GitHub и документации, 2026-11-21

**Проверенный baseline:** [`main` `edd25510c732e97ceb2daf21a870968a4306af13`](https://github.com/uzbatsu-beep/HRMS/commit/edd25510c732e97ceb2daf21a870968a4306af13), public GitHub `uzbatsu-beep/HRMS`. Анализ охватывает Git/PR/CI/ruleset, `.github/workflows/ci.yml`, Compose/Dockerfile, Markdown и жизненный цикл ADR. **Не является** независимым pentest, проверкой исходного кода на каждую уязвимость, юридической экспертизой или испытанием реального ПК.

## 1. Исходные факты

| Объект | Подтверждённое состояние | Evidence |
|---|---|---|
| Основная ветка | `main` защищена; SHA выше | GitHub branch API |
| Ruleset | `HRMS — main branch protection` #27708090, Active, PR + 5 CI jobs | [MAIN_PROTECTION](MAIN_PROTECTION.md) |
| Падающий CI запрещает слияние | FAIL Ruff и `mergeable_state=blocked` | [PR #35](https://github.com/uzbatsu-beep/HRMS/pull/35), [Actions](https://github.com/uzbatsu-beep/HRMS/actions/runs/44696619934) |
| Прямой push владельца | **NOT VERIFIED**: терминальный отказ не зафиксирован | [Issue #34](https://github.com/uzbatsu-beep/HRMS/issues/34) закрыт владельцем |
| Runtime reference | PR #33 merged: HTTPS/Nginx, migrations, isolated DB, secret files, DR script | [PR #33](https://github.com/uzbatsu-beep/HRMS/pull/33), [ADR-0026](adr/0026-pilot-deployment-and-recovery.md) |
| Privacy work | **Draft PR #36, not in main**, последняя проверка 5/5 | [PR #36](https://github.com/uzbatsu-beep/HRMS/pull/36) |
| Local Windows/Linux stand | **Draft PR #38**, конкретный host/OS/CPU/RAM не проверены; локальный TEST-ONLY выбран владельцем | [PR #38](https://github.com/uzbatsu-beep/HRMS/pull/38), [Issue #37](https://github.com/uzbatsu-beep/HRMS/issues/37) |
| Состояние допуска | **G6 NO-GO** для реальных данных сотрудников | [PILOT_READINESS](PILOT_READINESS_G6.md) |

До редакции исходное дерево `main` содержало 230 отслеживаемых файлов, из них 50 Markdown и 26 ADR. Эта цифра фиксирует именно baseline, а не размер текущего PR.

## 2. Выявленные проблемы и принятые изменения

| ID | Обнаружено в исходном `main` | Исправление в документационном PR | Статус |
|---|---|---|---|
| DOC-01 | `MAIN_PROTECTION`, `REQUIREMENTS_MATRIX`, `ROADMAP` утверждали, что `main` не защищена | Факт Ruleset #27708090, доказанный FAIL PR #35, прямой push отдельным NOT VERIFIED | Исправлено в PR |
| DOC-02 | `DEVELOPMENT` описывал 3 CI job, реально требуются 5 | Пять точных проверок и роль required checks документированы | Исправлено в PR |
| DOC-03 | `REQUIREMENTS_MATRIX` содержала дублирование `FR-15` и старые статусы PR #28/#30/#31/#32 | Устранён дубликат (`FR-21` — UI), статусы привязаны к фактическим merged PR, INF/PII отдельно | Исправлено в PR |
| DOC-04 | README ~32 тыс. символов, информация о запуске/статусе погружена в многолетнюю историю | Краткий README, оригинальная подробная история сохранена в `FEATURE_HISTORY` | Исправлено в PR |
| DOC-05 | Старые ADR `Proposed`/ `Draft` воспринимаются как актуальная стадия Git | У всех 26 ADR добавлена **отдельная** текущая отметка merge, без изменения исходного решения | Исправлено в PR |
| DOC-06 | Нет центрального навигатора, смешаны текущие факты, Draft и архив | `DOCUMENTATION_INDEX.md` с реестром ADR, эксплуатационных документов и порядком доверия | Исправлено в PR |
| DOC-07 | `GEMINI.md` обещал Tailwind/shadcn и Vitest без соответствующих зависимостей в `frontend/package.json` | Исправлено описание фактического React/TS/CSS и Playwright стека | Исправлено в PR |
| DOC-08 | Backend README описывал только старую модель proxy trust | Уточнена схема `TWM_TRUSTED_PROXY_HOSTNAME=web`, `--no-proxy-headers`, недоверенный X-Forwarded-For | Исправлено в PR |
| DOC-09 | Не было автоматического блокирующего локального Markdown-link check | `scripts/check_docs.py` и шаг внутри **уже required** Backend CI job | Исправлено в PR; проверить CI |
| DOC-10 | Не были явно исключены типичные файлы G6 дампов/certs | Дополнен `.gitignore`; это защита от случайного `git add`, а не secret scanning ранее committed объектов | Частичный профилактический контроль |
| DOC-11 | Инструкции по Windows/Linux/localhost, PIA и DR были распределены по нескольким текстам | Связаны G6, Issue #37, отдельный Draft #38; дополнены ограничения Docker Desktop/WSL2/NTFS и тестового запуска | Исправлено в PR |

## 3. Что намеренно не менялось

- **Программная логика:** FastAPI, SQLAlchemy модели, конфигуратор, React и safety gates в этом документационном PR не изменяются. Поэтому зелёные runtime-тесты подтверждают отсутствие регрессий, а не новые функции.
- **`CODE_OF_CONDUCT.md`:** исходный Contributor Covenant сохранён без автоматической массовой редакции.
- **Исторические ADR/старый README:** исходные решения и даты сохранены; архив может упоминать устаревшие параметры, обозначен как исторический.
- **Draft PR #36/#38:** остаются самостоятельными ветками; их объединение не следует из документационного аудита.
- **Отдельный ПК:** не был доступен для фактических host-level тестов; инструкция по нему — кандидат в отдельном PR #38.

## 4. Инфраструктурные и security P0

1. INF-01: известен тип стенда — отдельный Windows/Linux ПК, **не известен реальный host и подтверждение localhost smoke**.
2. INF-02/03: корпоративные DNS/TLS trust chain, UID/ACL secret mounts, управление и отзыв секретов, FW/VLAN ещё требуют проверки.
3. INF-04: upstream образы пока без принятого immutable digest pin, security scanning и SBOM-политики.
4. INF-05: CI logical backup/restore на синтетических данных есть, но offsite encrypted backup, WAL/PITR, roles/grants, retention и реальный RPO/RTO не проверены.
5. INF-06: права на реальные ПДн, юридическая база/retention и полная API/export privacy matrix не подписаны; PII hardening Draft #36 частичный.
6. INF-07/08: `/health/ready` latency — не реальная нагрузка на персонал/наряды; monitoring/alerts/on-call не подписаны.
7. INF-09/10: нет независимого UAT и эксплуатационных release/rollback/drill подписей.
8. GitHub direct push negative test — не выполнен при подтверждённом активном Ruleset.
9. HTTPS smoke в CI использует одноразовые тестовые сертификаты и проверяет техническую сборку; не валидирует реальный защищённый секретный store/PKI и не должен восприниматься как инфраструктурный signoff.

## 5. Проверки изменений

- Документационный PR: [#39](https://github.com/uzbatsu-beep/HRMS/pull/39), отдельная ветка `docs/g6-repository-audit-20261121`, **Draft, не слит**.
- Основной GitHub Actions: [workflow CI](https://github.com/uzbatsu-beep/HRMS/actions/workflows/ci.yml).
- Новая проверка `python scripts/check_docs.py` валидирует **локальные пути Markdown без сети**. Она не проверяет удалённые HTTP URLs, корректность anchor-фрагментов или семантическую правдивость утверждений. Потребуется отдельное тестирование чекера.
- Критерий приёмки PR: проверка ссылок PASS, Ruff/migrations/backend, frontend/TS, Playwright, PostgreSQL isolated DR и HTTPS smoke PASS на **последнем** SHA, описание PR обновлено, независимое разрешение владельца на merge.

## 6. Рекомендации после PR

Проверить на выделенном ПК `docker compose config --quiet`, `docker compose up --build -d`, `docker compose ps`, test admin login и scope-denials; сохранить обезличенный протокол. Затем согласовать INF-02/03 для localhost HTTPS reference, INF-05 off-host backup, INF-06 PIA и INF-07 реальные синтетические workload tests, не смешивая их с PR #36 и #38. Обновлять G6 и индекс после каждого фактического доказательства, но **не выдавать GO автоматически**.
