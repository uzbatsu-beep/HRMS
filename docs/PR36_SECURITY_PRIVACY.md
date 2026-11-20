# PR #36 — границы усиления приватности и RBAC

**Статус:** proposed / PR review. **NO-GO** для реальных персональных данных и рабочих пользователей.

## Проверяемые проблемы

1. `person.updated` содержал `before/after` ФИО в текстовом журнале; `person.created` — табельный код.
2. `credential.revoked` сохранял произвольное текстовое обоснование в `details_json`.
3. `GET /credentials/persons/{id}` выдавал номер документа, issuer и review/revoke free text всем пользователям с областью видимости сотрудника.
4. Успешное чтение персональных записей ранее не оставляло отдельного минимизированного журнала чтения.

## Изменения в PR

- `credentials.record.read_sensitive` — **новое точечное право** на активное основное подразделение сотрудника; выдаётся администратором через `POST /api/v1/org/permissions`. Наличие организационной видимости ОБЯЗАТЕЛЬНО. `credentials.record.review` не даёт этого права. Admin видит все поля в рамках существующей глобальной административной модели.
- Без права: `document_reference`, `issuer`, `submitted_by`, `reviewed_by`, `revoked_by`, `review_note`, `revoke_reason` возвращаются как `null`. Статус, даты действительности, тип и ID сохраняются: оценка safety eligibility неизменна.
- Для обычного `viewer` без собственного Person link и review permission доказательства компетенций в `GET /competence/persons/{id}/assessments` не выдаются, `review_note=null`; одобренные уровни доступны.
- Новые `PersonnelAuditEvent` и `CredentialAuditEvent` перестают записывать ФИО, табельные коды и текст обоснования отзыва в перечисленных операциях. GET audit маскирует потенциально содержащие ПДн исторические события этих типов; **сырые исторические строки в БД остаются без изменений**.
- Таблица `personal_data_read_events` и миграция `0021_personal_data_read_audit`: субъект-user UUID, предприятие UUID, optional person UUID, фиксированный тип чтения, количество, время. Никаких поисковых строк, ФИО, документов, body, cookie или текста замечаний.
- Фиксированные точки чтения: `personnel.list`, `personnel.detail`, `credentials.list`, `credentials.eligibility`, `competence.assessments`, `competence.matrix`. Запись **до** ответа, неудача сохранения = HTTP 503 (fail-closed), чтобы не выпускать ПДн без учёта.
- `GET /api/v1/privacy/read-events` — только admin, фильтры enterprise/person и ограничение до 100 событий. Клиентские ответы персонала/компетенций/допусков/аудита = `Cache-Control: private, no-store`.

## Политика по ролям

| Контекст | Администратор | Менеджер с org scope | Viewer с org scope |
|---|---|---|---|
| ФИО, должность и действующая принадлежность | Да | Только видимые люди | Только видимые люди |
| История назначений по чужим unit | Да | Нет | Нет |
| Credential status / expiry / eligibility | Да | Только видимые люди | Только видимые люди |
| Номер документа и free-text notes | Да | Только с `credentials.record.read_sensitive` | Только с `credentials.record.read_sensitive` |
| Содержимое evidence assessment | Да | Только видимые люди | Нет по умолчанию (кроме self/reviewer) |
| Metadata audit read-events | Да | Нет | Нет |

**Негативные тесты:** чужой unit 404, скрытие реквизитов по умолчанию, grant даёт раскрытие только нужному unit, revoke скрывает сразу, скрытие evidence, отсутствие raw PII в новых mutation audit, отключение выдачи при недоступной audit DB, admin-only audit API.

## Известные ограничения — P0 для реального пилота

1. **Неполный охват маршрутов чтения:** analytics, работы/наряды, Configurator custom forms, audit explorer, exports, произвольные тексты других доменов требуют инвентаризации и отдельных правил.
2. **Исторический raw audit в PostgreSQL** ещё может содержать персональные значения. Нужны ограничение DB admin, правовая политика, безопасный план scrub/retention и тест backup. Нельзя удалять историю автоматически.
3. **Retention, legal basis, consent/notification, full access register** не утверждены. Рост write-traffic audit должен быть оценён в нагрузочных тестах; исключения и отказ доступности audit надо учитывать в SLO.
4. **UI/работа администраторов:** настройка `credentials.record.read_sensitive` выполняется через API; UX назначения и пояснения «скрыто» доработать после согласования политики полей.
5. Поле free text в других API не гарантировано безопасным; HTTP `no-store` не защищает от SQL-администраторов, скриншотов, логов reverse proxy или экспорта.
6. Изменения не создают юридический Permit-to-Work и не меняют блокировки или safety-интеграцию.

## Проверка

После PR CI: Ruff, Alembic upgrade на PostgreSQL 16, pytest, TS build, Playwright E2E, backup/restore drill и HTTPS smoke. Отдельно до внешнего пилота — threat model, инвентаризация всех GET/export и управляемый юридически retention.
