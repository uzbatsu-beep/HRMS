# GitHub — защита основной ветки `main`

**Текущее состояние (проверено по GitHub API, 2026-11-21):** защищённая ветка `main`, active [Ruleset #27708090](https://github.com/uzbatsu-beep/HRMS/rules/27708090) — `HRMS — main branch protection`. Значение `main.protected=true`. Это **действующая настройка**, а не предложение.

## Подтверждённые правила

- Изменения `main` через Pull Request, обязательное разрешение дискуссий.
- Запрещены удаление и `force-push`; permanent bypass actors отсутствуют.
- Обязательные пять GitHub Actions jobs, их **точные имена**:
  1. `Backend - lint, migration and tests`
  2. `Frontend - typecheck and build`
  3. `Browser E2E - Chromium and synthetic data`
  4. `PostgreSQL backup and isolated restore drill`
  5. `Pilot images and synthetic HTTPS smoke`
- Требуется актуальность ветки относительно `main` перед слиянием.
- Число обязательных approvals — **0** для работы одного владельца. При появлении независимых reviewers можно утвердить отдельную политику, не создавая тупиковую блокировку собственных PR.

## Протокол отрицательной проверки — подтверждено частично

| Проверка | Evidence | Статус |
|---|---|---|
| `protected=true` / Active Ruleset | GitHub API, Ruleset #27708090 | PASS |
| Намеренно падающий обязательный CI блокирует merge | [Тестовый PR #35](https://github.com/uzbatsu-beep/HRMS/pull/35), [Actions run #44696619934](https://github.com/uzbatsu-beep/HRMS/actions/runs/44696619934): Ruff FAIL, `mergeable_state=blocked`; PR закрыт без слияния | PASS |
| Основная ветка не получила тестовую синтаксическую ошибку | PR #35 закрыт, `main` не изменился | PASS |
| Реальный отказ прямого `git push` от владельца | Вывод терминала или отдельный audit log **не предоставлен** | NOT VERIFIED |
| Тестовый PR с зелёным CI может быть слит | Предыдущий успешный PR #33 был слит **до** включения Ruleset; новый отдельный проверочный опыт не проводился | NOT VERIFIED |

[Issue #34](https://github.com/uzbatsu-beep/HRMS/issues/34) закрыт владельцем. Статус Issue **не подменяет** две отсутствующие проверки. Не выполнять неконтролируемые попытки перезаписи `main` только ради подтверждения защиты.

## Поддержка и изменения Ruleset

- Владельцу репозитория: [Settings → Rules → Rulesets](https://github.com/uzbatsu-beep/HRMS/settings/rules). Импорт JSON может создать правило, но фактическое действие проверяется GitHub API и отрицательными тестами.
- При переименовании CI job синхронизировать Ruleset и [ci.yml](../.github/workflows/ci.yml), иначе новый job не заменит обязательный старый контекст автоматически.
- Не включать bypass для быстрого слияния; согласовывать отдельное исключение только при реальном инциденте с документированной процедурой и audit evidence.
- Новые PR требуют решения владельца на слияние; проход CI не означает право применять изменения в production.

См. [G6 readiness](PILOT_READINESS_G6.md), [документацию](DOCUMENTATION_INDEX.md) и [политику безопасности](../SECURITY.md).
