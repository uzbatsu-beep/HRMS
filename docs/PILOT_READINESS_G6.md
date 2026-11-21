# G6 — план и протокол допуска TWM/HRMS к пилотной эксплуатации

**Актуализация: 2026-11-21. NO-GO для реальных данных сотрудников.**
PR #33 (HTTPS/DR), [#39](https://github.com/uzbatsu-beep/HRMS/pull/39) (документация), [#38](https://github.com/uzbatsu-beep/HRMS/pull/38) (локальный ПК) и [#36](https://github.com/uzbatsu-beep/HRMS/pull/36) (частичный read audit / masking) включены в `main`. Эти изменения **не разрешают** пилот с реальными персональными данными. Выбран отдельный Windows/Linux ПК только для localhost TEST-ONLY; конкретный хост и подтверждение smoke отсутствуют. [Issue #37](https://github.com/uzbatsu-beep/HRMS/issues/37) · [Матрица инфраструктуры](PILOT_INFRASTRUCTURE_DECISIONS.md).

## Архитектура пилотного контура (проект)

`Клиент HTTPS → Nginx/TLS:8443 → FastAPI:8000 → PostgreSQL:5432`.
Публичен только TLS-порт; backend и БД доступны лишь в Docker network.
Отдельный одноразовый миграционный контейнер обновляет схему до старта API.
Образ API без autoreload, без dev-зависимостей, непривилегированный.
Образ UI собран командой Vite build и отдаёт только статические файлы.
Сертификаты, пароль PostgreSQL и HMAC ключ загружаются через secrets files,
а не через открытые параметры CLI и Git.

До запуска с доступом извне: DNS, PKI/корневые сертификаты, правила FW/VLAN,
финальное размещение, ресурсные лимиты и ответственный за инциденты не утверждены.
Начальная цель — изолированный localhost на отдельном Windows/Linux ПК;
см. [LOCAL_TEST_STAND_INF01](LOCAL_TEST_STAND_INF01.md). Не направлять трафик реальных
сотрудников на этот стек до решения владельца.

## Матрица G6

| ID | Критерий | Подготовлено в PR | Блокирующее подтверждение |
|---|---|---|---|
| OPS-00 | `main` защищён | Ruleset #27708090, 5 required checks, блокировка PR #35 и успешные merges #39/#38 | **CI и запрет merge подтверждены**; прямой push владельца ещё не проверен |
| OPS-01 | Сегментация и TLS | `deploy/compose.pilot.yml`, Nginx | **Не доказано**: реальные сертификаты, DNS, FW, TLS handshake/pentest |
| OPS-02 | Production секреты | Проверки `Settings`, Docker secrets | **Не доказано**: vault/ACL, rotate/revoke, секреты и доступ runtime-пользователей |
| OPS-03 | Production образы | Отдельные Dockerfile без dev servers | **Не доказано**: registry, SBOM, сканирование и immutable image digests |
| OPS-04 | Backup + restore | `ops/postgres_dr.py`, CI synthetic drill | **Не доказано**: архивы вне площадки, шифрование, расписание, WAL/PITR, реальные RPO/RTO |
| OPS-05 | ПДн | [Инвентаризация](PRIVACY_IMPACT_CHECKLIST.md), [PR #36](PR36_SECURITY_PRIVACY.md): частичный field masking/read audit | **Не доказано:** полный inventory API/export, historical raw audit, legal basis, retention и юридическая/ИБ-приёмка |
| OPS-06 | Файловые вложения | Встроенного произвольного upload сейчас нет | **Не утверждено**: политика хранения доказательств/антивирусной обработки |
| OPS-07 | Наблюдаемость | Readiness и сквозной load smoke | **Не доказано**: централизованный redacted logging, алерты и инциденты |
| OPS-08 | Runbooks и восстановление | [Backup runbook](BACKUP_RESTORE_RUNBOOK.md) | **Не доказано**: практический независимый DR drill и тренировка команды |
| OPS-09 | Нагрузка | [План](LOAD_TEST_PLAN.md), bounded CI health probe | **Не доказано**: репрезентативные p95 и concurrency на ресурсах пилота |
| OPS-10 | UAT и право использования | Изолированные synthetic E2E | **Не доказано**: протокол приёмки по 4 ролям и финальная подпись |

## Логика допуска

- **BLOCKED / NO-GO:** любой не закрытый P0 в таблице, неизвестная правовая
  база или неподтверждённая процедура допуска к опасным работам.
- **TEST-ONLY:** CI на синтетических данных, private loopback, без доступа
  пользователей к реальным кадровым данным.
- **READY FOR UAT:** все автоматические требования закрыты, стенд изолирован,
  технические и ИБ-тесты с протоколом, матрица рисков и ответственная команда.
- **PILOT GO:** письменная подпись владельца продукта, ИБ/ПДн и эксплуатации
  после выполнения внешних тестов и утверждения RPO/RTO/SLO.

## Безопасный локальный разбор compose

Не используйте dev `docker-compose.yml` как production. Создайте
приватный файл по шаблону `deploy/pilot.env.example`, настройте реальные
пути секретов и корректный HTTPS origin. Пока сертификат/секреты отсутствуют,
**не запускайте** пилотный стек.

```sh
docker compose --env-file /secure/twm-pilot.env \
  -f deploy/compose.pilot.yml config --quiet
docker compose --env-file /secure/twm-pilot.env \
  -f deploy/compose.pilot.yml build
```

Compose bind-mounted secret files требуют отдельной проверки прав на хосте
и возможности чтения внутри непривилегированных контейнеров.
`chmod 600` для файлов может не позволить контейнерному UID прочитать
mount; согласуйте ACL/UID/GID/secret backend и не ослабляйте глобальную
доступность сертификатного ключа ради запуска.

Схема создана как **reference**, не как подтверждённый production release.

## Разграничение с промышленной безопасностью

HRMS не управляет блокировками ПЛК, роботами, emergency stop и не выдаёт
юридически значимый Permit-to-Work/LOTO. Все процедуры производства
независимы от интерфейсных статусов и алгоритмов планирования.

## Решение владельца

- Первоначальный стенд: **отдельный Windows/Linux ПК, локальный TEST-ONLY**, конкретный ПК и ОС не назначены (INF-01 частично определён).
- Последующее production размещение (on-prem/private cloud): **не выбрано**.
- RPO, RTO, SLO и число одновременных пользователей: **не утверждены**.
- Категории ПДн, сроки и правовой режим: **не утверждены**.
- Ключи шифрования, TLS сертификат, владельцы резервных копий: **не назначены**.
- Ответственные за pilot signoff: **не назначены**.

**Действующее решение: NO-GO** для реальных ПДн. **TEST-ONLY localhost** допускается с вымышленными данными после проверки состояния ПК и корректного `docker compose` (без проброса портов за loopback).

Трассировка: [Issue #37](https://github.com/uzbatsu-beep/HRMS/issues/37), [документационный индекс](DOCUMENTATION_INDEX.md).
