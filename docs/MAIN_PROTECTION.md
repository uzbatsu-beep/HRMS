# GitHub: обязательная защита основной ветки перед пилотом

**Факт на 2026-11-20:** `main.protected=false`, rulesets пусты;
проверка branch-protection API через интеграцию возвращает HTTP 403.
Ни создание документа, ни успешный CI **не включают** защиту ветки.

## Действия владельца/администратора репозитория

1. Перейти в [Repository Settings → Rules → Rulesets](https://github.com/uzbatsu-beep/HRMS/settings/rules).
2. Создать **New branch ruleset**, статус **Active**, target branch `main`
   (не только default-branch pattern, если он не совпадает).
3. Включить **Require a pull request before merging**, как минимум одно
   одобрение независимым reviewer (если это технически возможно в команде),
   **Dismiss stale approvals** и **Require conversation resolution**.
   Если владелец работает один, отдельный reviewer/временный процесс
   утверждения нужно определить до активации обязательных approvals:
   не создавать тупиковую политику, которую затем обходят администраторы.
4. Включить **Require status checks to pass**. Выбрать точные job names:
   - `Backend - lint, migration and tests`
   - `Frontend - typecheck and build`
   - `Browser E2E - Chromium and synthetic data`
   - `PostgreSQL backup and isolated restore drill` (появится после PR G6)
5. Заблокировать **force push**, удаление `main` и прямые push.
   Не создавать постоянные широкие bypass-исключения.
6. Включить required code review и блокировать merge при падающих проверках;
   при необходимости обсудить linear history / signed commits отдельно,
   исходя из реального workflow и доступа разработчиков.

## Проверка фактического применения

- Попытка **обычного прямого push** в `main` должна быть отклонена. Делать
  только тестовое изменение без секретов, не подвергая риску рабочие файлы.
- Тестовый PR с намеренно неуспешным job должен блокировать merge.
- Убедиться, что зелёный PR с нужным review можно объединить через UI.
- Повторно проверить API: `protected=true`, `rulesets` содержит Active.
- Сохранить ссылку на ruleset и скриншот настройки в протоколе G6.

Задача **открыта**, пока эти действия не выполнены и не подтверждены;
текущий GitHub connector не предоставляет право изменять правила репозитория.
