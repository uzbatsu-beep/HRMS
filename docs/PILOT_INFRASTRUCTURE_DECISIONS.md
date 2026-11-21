# G6 — инфраструктурные решения для пилотного стенда TWM/HRMS

**Статус:** проект для согласования владельцем и ИБ. Это не инструкция, разрешающая обработку ПДн.

## Контур и варианты

| Решение | Вариант A: on-prem | Вариант B: private cloud | Статус |
|---|---|---|---|
| Размещение | VLAN/VM в площадке предприятия | Изолированный VPC/private subnet | Не выбрано |
| Вход | Корпоративный DNS, Nginx HTTPS и internal PKI | Private ingress HTTPS, corporate CA | Не выбрано |
| Доступ | VPN/корпоративная сеть, ACL и запрет прямой БД | VPN/peering, SG и запрет public DB | Не выбрано |
| PostgreSQL | Отдельный volume, monitoring, off-host backup | Private DB/VM, encrypted storage | Не выбрано |
| Секреты | Vault/ACL-protected files, отдельные UID | Secret manager + rotation | Не выбрано |
| Деплой | Registry с pinned digests и SBOM | То же, private registry | Не выбрано |

## Решения, необходимые до подключения сотрудников

| Код | Решение/параметр | Значение | Ответственный / evidence |
|---|---|---|---|
| INF-01 | Отдельный TEST-ONLY ПК Stage A; последующее hosting/VLAN/CPU/RAM/storage | Stage A: выбран тип Windows/Linux ПК на localhost, конкретный host/acceptance — TBD; production: TBD | Эксплуатация / [Issue #37](https://github.com/uzbatsu-beep/HRMS/issues/37) |
| INF-02 | DNS/FQDN, корпоративная PKI, TLS policy, доверенный proxy | TBD | ИБ/сетевые администраторы |
| INF-03 | Secret manager, ACL непривилегированных контейнеров, rotate/revoke | TBD | ИБ/эксплуатация |
| INF-04 | Image registry, SBOM, CVE scanning, immutable digest pin | TBD | DevOps/ИБ |
| INF-05 | Целевые RPO/RTO, daily/weekly schedule, offsite/immutable backup, WAL/PITR | TBD | Эксплуатация/владелец |
| INF-06 | Retention ПДн, категории полей, минимальная роль, уведомления | TBD | Владелец ПДн/юрист |
| INF-07 | Нагрузка: 1/10/25/50 сессий, 100/1000/10000 синтетических профилей, p95/SLO | TBD | Владелец продукта |
| INF-08 | Централизованные redacted logs, алерты, on-call и реагирование | TBD | Эксплуатация/ИБ |
| INF-09 | UAT 4 ролей, протокол и план возврата после сбоя | TBD | Владелец/приёмка |
| INF-10 | Окно обслуживания, стратегия миграций и совместимость rollback | TBD | DevOps/DBA |

## Порядок параллельных работ

1. Решить INF-01/02 без DNS/сертификатов в открытых PR и без подключения реальных сотрудников.
2. На выделенном стенде с **синтетической** БД выполнить `deploy/compose.pilot.yml`, PKI и secret-file permissions. Проверить отсутствие доступа к портам PostgreSQL/API извне.
3. Зафиксировать immutable image digests, scan/SBOM и secret rotation, результаты — отдельные PR/протоколы.
4. Восстановить зашифрованную синтетическую копию на другой хост; измерить фактические RPO/RTO и отработать loss-of-primary.
5. Запустить реалистичную нагрузку и UAT, согласовать риски. При неподписанном OPS-05 или любом P0 — **NO-GO**.

**Архитектурное предложение:** on-prem целесообразен, если уже есть управляемые VLAN, PKI, backup и ответственные DBA; private cloud — если эти услуги реально предоставляются с изолированными сетями и проверяемыми SLA. Выбор не утверждён, зависит от IT/ИБ возможностей предприятия.
