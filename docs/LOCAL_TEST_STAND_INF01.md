# G6 / INF-01 — изолированный ПК для первоначальных испытаний TWM/HRMS

**Решение владельца от 2026-11-20:** для **первоначальных испытаний** выбирается отдельный Windows/Linux ПК. Конкретная ОС, модель, характеристики, доступность ИТ-ресурсов и ответственный **ещё не согласованы**. Режим: **TEST-ONLY**, исключительно синтетические данные. Это не производственный пилот и не разрешение на обработку реальных ПДн.

**Связано:** [Issue #37](https://github.com/uzbatsu-beep/HRMS/issues/37), [Draft PR #36](https://github.com/uzbatsu-beep/HRMS/pull/36), [G6 readiness](PILOT_READINESS_G6.md), [Development](DEVELOPMENT.md), [DR](BACKUP_RESTORE_RUNBOOK.md), [Load plan](LOAD_TEST_PLAN.md). Настоящий документ предлагается самостоятельным документационным PR; он не меняет рабочий Compose.

## 1. Классификация стенда и границы

| Этап | Сеть и пользователи | Стек | Статус |
|---|---|---|---|
| **A — функциональный localhost** | Только браузер **на самом испытательном ПК**; loopback-порты 5173/8000/5432 | Штатный `docker-compose.yml`; dev HTTP, autoreload, тестовые учётные записи | **Выбран как первая цель** |
| **B — защищённый однопользовательский стенд** | На том же ПК, HTTPS только на `127.0.0.1:8443` | `deploy/compose.pilot.yml`; локально доверенный TLS-сертификат, file-backed secrets | **Не подготовлен**, требует проверки ACL/PKI и отдельного протокола |
| **C — ограниченный LAN/UAT** | Другие устройства в разрешённой VLAN/VPN, только HTTPS, правила FW | Отдельно проверенная схема TLS/secret/network/backup; **не** dev Compose | **Не утверждён** |
| **PILOT GO с реальными ПДн** | Реальные кадровые сведения и пользователи | Требует всех внешних G6 P0, юридического, ИБ и эксплуатационного согласования | **NO-GO** |

**Ключевой инвариант:** штатный `docker-compose.yml` — для разработки, не публиковать даже на тестовой корпоративной сети. Объявление портов в нём уже сделано как `127.0.0.1:...:...`, поэтому с другого устройства доступ в штатной конфигурации не предполагается. Не заменять адрес на `0.0.0.0` ради удобства без отдельного решения по INF-02.

## 2. Профиль ПК и измеряемые параметры

Числа ниже — **проектные ориентиры**, не фактический benchmark HRMS. После INF-07 размеры корректируются по CPU, RAM, диску и IO.

| Ресурс | Минимум для пробного запуска | Рекомендуемое значение | Проверка |
|---|---:|---:|---|
| Архитектура | x86_64/amd64 | x86_64/amd64 | CPU/OS, контейнеры Linux amd64 |
| CPU | 4 логических потока | 6–8 логических потоков | `nproc` / Win32_Processor |
| RAM | 8 ГБ | 16 ГБ (32 ГБ если разработка+IDE+нагрузка на одном ПК) | Реально доступная RAM/WSL |
| SSD | 60 ГБ **свободного** места под тестовый стек/образы/БД | 120–256 ГБ доступного места | Свободное место и прирост Docker volumes |
| Сеть | Доступ к GitHub и registry для установки; после установки — localhost | Управляемая корпоративная/LAN с запретом внешних публикаций | FW/слушающие порты |
| ОС | Поддерживаемая Windows 11 с WSL2 либо Linux x86_64 | Windows 11 Pro/Enterprise или Ubuntu Server 24.04 LTS | Версия ОС, обновления безопасности |
| Резервирование | Отдельная копия **синтетической** БД на другом носителе | Зашифрованное хранилище вне ПК + restore drill | Проверенный результат восстановления |

**Не являются требованиями к HRMS:** выделенная GPU, NVIDIA/CUDA, SQL Server, Active Directory, доступ к АСУ ТП/PLC. Для теста не соединять этот ПК с OT/технологической сетью.

### Windows 11

- Использовать Docker Desktop **в режиме Linux containers + WSL2**. В BIOS/UEFI нужна аппаратная виртуализация; версия Windows должна оставаться в актуальной поддержке производителя.
- В корпоративной среде заранее проверить условия лицензии Docker Desktop: для более крупных компаний его коммерческое применение требует соответствующей подписки. Альтернатива — Linux + Docker Engine.
- Предпочесть диск SSD и ограничить ресурсы WSL2; для конфиденциальных файлов не считать Windows ACL эквивалентом Linux mode 0600 без реального теста Docker secret mounts.
- **Не** применять инструкции Docker Desktop к Windows Server; Windows Server не является целевой ОС этого стенда.

### Linux

- Рекомендуем Ubuntu Server 24.04 LTS x86_64 (без графической оболочки при удалённом администрировании). Docker Engine и Compose plugin — из официального репозитория Docker.
- Выделить системный аккаунт обслуживания, включить обновления ОС и файрвол; доступ к Docker socket означает высокий уровень привилегий. Не помещать всех пользователей в `docker` group.
- Хранить DB volume на SSD с контролем свободного места, не подменять регулярную копию снапшотом тома.

Документация производителя:
- https://docs.docker.com/desktop/setup/install/windows-install/
- https://docs.docker.com/subscription-billing/desktop-license/
- https://docs.docker.com/engine/install/ubuntu/
- https://docs.docker.com/compose/how-tos/use-secrets/

## 3. Preflight — до установки HRMS

**Windows PowerShell (с установленными Git, WSL2, Docker Desktop — последние три команды):**

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture,TotalVisibleMemorySize
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
Get-Volume -DriveLetter C | Select-Object DriveLetter,SizeRemaining,Size
wsl --status
docker version
docker compose version
docker info --format '{{.OSType}}'
```

**Ubuntu/Linux shell (после установки Docker Engine + Compose plugin):**

```bash
cat /etc/os-release
uname -m
nproc
free -h
df -h /
docker version
docker compose version
docker info --format '{{.OSType}}'
```

Ожидаемый тип Docker — `linux`. Проверить дисковую квоту Docker/WSL, наличие аппаратной виртуализации, актуальные обновления, доступность registry и отсутствие использования чужих production-секретов. Записать в локальный протокол ОС, CPU, RAM, SSD, версии Docker/Compose и дату; **не публиковать в открытом GitHub серийные номера ПК, внутренние IP/пользователей, ключи и корпоративные схемы сети**.

## 4. Безопасный первый запуск — этап A (только localhost)

Команды из корня репозитория в PowerShell либо Linux shell, после установки Git и Docker.

```sh
git clone https://github.com/uzbatsu-beep/HRMS.git
cd HRMS
git switch main
git rev-parse --short HEAD
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose exec backend alembic current
docker compose exec backend alembic heads
docker compose exec backend python -m app.identity.bootstrap_admin
```

Создать **отдельного тестового администратора**; учётные записи только синтетические, пароль не пересылать в чате, GitHub или логах. До первого теста убедиться, что все healthcheck healthy. Открыть на **этом же ПК**:

- UI: http://localhost:5173
- Readiness: http://localhost:8000/api/v1/health/ready
- API docs (только dev): http://localhost:8000/docs

Проверить: авторизацию, организационную структуру, создание вымышленных сотрудников, роли `admin/manager/viewer`, компетенции, допуски, смены, наряды, поиск, Dashboard. Для PR #36 проверить отдельное право `credentials.record.read_sensitive` **только после его согласованного слияния и обновления стенда**. Поскольку PR #36 остаётся Draft, `main` пока содержит предыдущие политики доступа.

Диагностика:

```sh
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 db
docker compose exec db pg_isready -U twm -d twm
```

Не передавать сырые логи в публичные issues; просматривать на предмет персональных данных, токенов и ошибок конфигурации. Для штатной остановки **без удаления БД**: `docker compose down`. **Не выполнять** `docker compose down -v`, `docker volume prune` или уничтожение volume, если нужно сохранить тестовые данные.

## 5. Этап B — production-mode на localhost (после согласования секретов)

Референс `deploy/compose.pilot.yml`:
- DB: PostgreSQL 16, только внутренняя Docker network `data`;
- API: FastAPI, UID 10001, миграционный job, только `edge/data`;
- Web: Nginx HTTPS `:8443`, снаружи по умолчанию **только** `127.0.0.1:8443`;
- Dev сервер Vite и `--reload` отсутствуют;
- сертификат TLS, пароль DB и HMAC ключ поступают в контейнер через file-backed secrets.

Нужно: создать **локальные тестовые** секреты и PEM-сертификат, не включать их в Git, зафиксировать раздельные UID/ACL/монтирование/доступность внутри непривилегированных контейнеров. Нельзя делать private key world-readable только ради старта Nginx. Для локального HTTPS origin учитывать **точный порт** (пример `https://localhost:8443` при корректном сертификате). Не использовать пример `https://twm.example.invalid` из `pilot.env.example` как готовое имя. При отсутствии проверенного TLS/secret provisioning этап B **не запускать**, продолжать этап A.

После реальной подготовки файлов:
```sh
docker compose --env-file /absolute/secure/path/pilot.env -f deploy/compose.pilot.yml config --quiet
docker compose --env-file /absolute/secure/path/pilot.env -f deploy/compose.pilot.yml build
```
Это проверка конфигурации и сборки, **не запуск**, не проверка полномочий чтения файлов контейнерами и не подтверждение возможности обработки ПДн. На Windows абсолютные host paths и права Docker Desktop/WSL2 проверять отдельно; синтаксис `/absolute/secure/path` здесь — пример для Linux.

## 6. INF-02 — INF-10: порядок решений для локального тестирования

| ID | Решаем сейчас | До ограниченного LAN/UAT | До использования реальных ПДн |
|---|---|---|---|
| INF-02 Сеть и TLS | Изоляция `localhost`, firewall, без port forwarding; зафиксировать `127.0.0.1` | FQDN, корпоративная CA/PKI, trusted proxy, тест TLS и VLAN/VPN | ИБ-подпись и проверка доступа |
| INF-03 Secrets | Только синтетические пароли, никаких ключей в Git/Issues | File-backed secrets, ACL/UID, ротация, отзыв, защищённый доступ контейнеров | Контролируемый vault/политика доступа |
| INF-04 Images | Фиксировать Git SHA, версии образов и Docker | SBOM, CVE scan, immutable digest pin, registry | Принятая supply-chain policy |
| INF-05 Backup/DR | Синтетический backup отдельно от ПК, restore в **новую** БД | Регулярный зашифрованный off-host backup, проверка RPO/RTO | WAL/PITR, retention, immutable/off-site и DR |
| INF-06 ПДн | Полный запрет реальных ПДн | Инвентаризация API/fields/retention, security review | Правовая база, уведомления, согласование владельца ПДн |
| INF-07 Нагрузка | 1/5/10 сессий, 100/1000 синтетических записей, baseline | 25/50 сессий и 10000 записей на выделенном стенде | Утверждённый SLO/p95 и исправленные узкие места |
| INF-08 Monitoring | Docker health, CPU/RAM/disk, красные/жёлтые события | Централизованные обезличенные логи/алерты, DB locks | On-call, SLA, incident response |
| INF-09 UAT | Ручные сценарии admin/manager/viewer/delegated reviewer | Воспроизводимый отчёт, роли, запреты, негативные тесты | Подписанная приёмка и risk decision |
| INF-10 Release | Git SHA, миграция, release note, backup перед обновлением | Runbook deploy/rollback, окно сопровождения | DBA/эксплуатационный signoff |

**Не объявлять INF-01 выполненным только по выбору ПК:** минимум требуются фактический host inventory, успешный `docker compose up`, health checks и ручной доступ по `localhost`. Решение «отдельный ПК» согласовано, **ввод в эксплуатацию ещё не доказан**.

## 7. Протокол INF-01 и критерии закрытия

Заполнить после установки: 
- ОС и версия: TBD; CPU логических: TBD; RAM: TBD; SSD свободно: TBD.
- Ответственный за ПК, обновления и локальный тест: TBD (не публиковать персональные реквизиты).
- Docker Engine/Desktop и Compose версии: TBD; Desktop licensing: TBD/not applicable.
- Git SHA `main` и Alembic revision: TBD.
- Наличие одного локального `http://localhost:5173`, ready API `status=ready`, отсутствие доступа с других ПК: TBD.
- Успешный login тестового администратора, создание синтетической структуры и контроль RBAC: TBD.
- Бэкап/restore и повторный старт: TBD; фиксация результатов без секретов.

**INF-01 CLOSED (только локальный этап A)** при протоколе хоста, здоровом Docker Compose, доступе из локального браузера, результатах синтетического функционального smoke, а также подтверждении отсутствия публикации портов наружу. **Issue #37** остаётся открытым, пока INF-02—INF-10 не пройдут свою приёмку.

## 8. Известные ограничения и решения

1. Windows PC удобен для разработки, но Docker Desktop + WSL2 зависит от состояния пользовательской сессии, политики обновлений, виртуализации и корпоративной лицензии.
2. Ubuntu Server проще как непрерывно работающий headless-пилот с управлением сервисами, но требует навыков Linux/Docker и управления секретами.
3. 8 ГБ RAM — минимальный опытный порог, не обещание работы 50 одновременных пользователей. Для нагрузочного стенда потребуется отдельное профилирование.
4. Существующий Compose dev публикует только loopback; безопасный доступ по LAN через HTTPS **ещё не реализован и не проверен**.
5. Замер CI `/health/ready` не демонстрирует производительность экранов, поиска и назначения бригад.
6. Контроль промышленной безопасности/Permit-to-Work/LOTO не заменяется HRMS и не входит в разрешение на пилот.
