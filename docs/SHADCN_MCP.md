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

После завершения реализации интегратор выполняет `get_audit_checklist`
через тот же MCP и записывает фактический результат в итоговый отчёт проверок.
Чек-лист MCP дополняет TypeScript, браузер, Playwright и независимое Q-01;
его получение не означает автоматического прохождения этих проверок.
