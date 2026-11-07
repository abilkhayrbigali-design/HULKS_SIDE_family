# shadcn MCP в redesign CQA

Дата: 2026-11-08. Выбор компонентов выполнялся через официальный
[shadcn MCP](https://ui.shadcn.com/docs/mcp), запущенный по stdio командой
`npx --yes shadcn@4.23.0 mcp` в рабочем каталоге frontend Артёма.
Глобальная конфигурация Codex не изменялась.

## Фактическое обращение к серверу

После JSON-RPC `initialize` и `notifications/initialized` сервер сообщил
`serverInfo.name=shadcn`, `serverInfo.version=1.0.0`. Через `tools/list`
проверены доступные методы. Затем выполнены восемь `tools/call`:

1. `get_project_registries` — registry `@shadcn` из `components.json` проекта.
2. Четыре `search_items_in_registries` — resizable, sheet, tooltip и tabs.
3. `view_items_in_registries` — button, badge, tooltip, sheet, scroll-area,
   resizable, separator и tabs.
4. `get_item_examples_from_registries` — `resizable-demo`, включая исходник
   актуального примера, а не только описание компонента.
5. `get_add_command_for_items` — команда установки этих восьми компонентов.

Установку исходников и зависимостей выполняет CLI той же закреплённой версии.
CLI-установка сама по себе не считается обращением к MCP: выше перечислены
отдельные фактически выполненные вызовы сервера. В MCP передавались только
имена компонентов и параметры registry; переписка и секреты не передавались.

Совместимость актуального resizable API проверяется по официальному примеру:
`Group`, `Separator`, `orientation`, процентные размеры, `panelRef` и
`onLayoutChange`. Изменения пакетов и компонентов находятся в frontend;
Lucide сохраняется как источник иконок.

## Финальная проверка

После реализации UI delta `f6ef226` (интегрирован как `1ee7005`) выполнен
девятый `tools/call` — `get_audit_checklist`. Сервер вернул проверки импортов,
зависимостей, TypeScript, lint и браузера, а также условный пункт `next/image`.

Импорты и зависимости проверены чистой `npm ci` и production build;
TypeScript и 7 Vitest прошли. Next.js/`next/image` в проекте нет.
Отдельный frontend lint не настроен; его прохождение не заявляется.
Backend Ruff и форматирование прошли. Интерфейс проверен через native CUA
с Playwright API и отдельный Playwright Chromium runner по обычному HTTP.
Финальные версии, сценарии и результаты записаны в отчётах workspace QA и PR №2.
Получение чек-листа само по себе не объявляется автоматическим аудитом кода.
