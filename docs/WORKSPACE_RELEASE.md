# Проверка CQA workspace — DES-01

2026-11-08. Рабочий репозиторий HULKS_SIDE_family; исходный HULK-S_FAMILY_REPO
не изменялся. Итоговые base/head SHA, независимый Q-01 и CI фиксируются в
[PR №2](https://github.com/abilkhayrbigali-design/HULKS_SIDE_family/pull/2).

## Выполненная реализация

Существующий React объединяет постоянную очередь, широкую переписку и панель
критериев/доказательств/апелляций. Сохранены импорт, поиск текущей страницы,
фильтры, пагинация, версии правил, запуск/polling, история и исходный/final.
Есть две темы, resize/collapse, клавиатура, narrow-панели, отдельные scroll areas,
loading/empty/error/retry. Критерии динамические: ответ, исходный вес, вклад /100,
N/A и самостоятельные флаги. Выбор, доказательство и положительный статус имеют
разную семантику. shadcn выбран через настоящий MCP; иконки Lucide.

Контекст защищён generation и неизменяемыми snapshot IDs. Поздние ответы другого
диалога не меняют текущую оценку. Черновики комментариев и решений изолированы
по контексту; поздний успешный ответ не стирает новый ввод. Черновики остаются
в памяти, настройки очереди — в sessionStorage, тема/геометрия — в localStorage.

Последний проверенный frontend соответствует source
`4074b85bf1cfc414010b73d1f906a3fd1498b9c1` (root code `c8f7bfb`). После него
в итоговую ветку объединяются документация и протоколы проверки.

## Фактические проверки интегратора

| Команда/сценарий | Результат |
| --- | --- |
| `make check-api UV=/tmp/dataton-review-tools/bin/uv` | 238 pytest; Ruff, форматирование, экспорты контрактов PASS |
| `npm --prefix frontend test` | 7 Vitest PASS; дополнительно повторены reviewer на последнем code SHA |
| `npm --prefix frontend run build` | TypeScript и production Vite build PASS на последнем code SHA |
| `npm --prefix frontend run test:e2e -- --config /tmp/cqa-root-playwright.config.ts` | 27/27 PASS, 33,1 s; собственный Vite на 5184, Chromium, синтетические API-ответы |
| `make smoke UV=/tmp/dataton-review-tools/bin/uv` | Полный настоящий HTTP/SQLite/static assets smoke PASS, `upstream_requests=0` |
| Официальный shadcn MCP | Discovery, 8 registry/component calls и три финальных `get_audit_checklist` выполнены; детали в SHADCN_MCP.md |
| Native CUA, desktop 1440×900 | Очередь 263 px, переписка 699 px, оценка 420 px; page overflow=false, 120 сообщений/12 архивных критериев; range6–9 включает system |
| Native CUA, narrow 390×844 | Реальное приложение: качество → закрыть → диалог, видимый фокус возвращён, page overflow=false; на учебном 8002 range118–120 остаётся в viewport после 800→390 |
| Native CUA + настоящий API 8000 | Пустое состояние → учебный импорт1 → 4 сообщения → AI_NOT_CONFIGURED503; оценка не создана, консоль содержит только фиксированные event/status/code |

27 E2E покрывают 13 прежних сценариев и 14 workspace-регрессий: frozen snapshots,
12/13 критериев, original/final, evidence bounds, темы, resize/collapse, inert и
focus, короткий viewport/длинные review_reasons, scoped drafts, поздние ответы,
N/A/частичные шкалы/отдельные флаги, filters/route/reload, импорты, ошибки,
101-й чек-лист, pending-save, 409 и неизменяемые решения.

Независимые N/C проверки и их точные версии/ограничения находятся в
[WORKSPACE_QA](WORKSPACE_QA.md) и [WORKSPACE_API_REVIEW](WORKSPACE_API_REVIEW.md).
Reviewer Sol/xhigh независимо выполнил полный 27-suite на функциональной дельте,
а на последней дельте — целевые reload/narrow/resize с ручным чтением, TypeScript и 7 Vitest. Финальное
одобрение всего документационного head фиксируется отдельно в PR.

## Figma и локальные изображения

[Основной editable Dark](https://www.figma.com/design/vEvqJlR06dJtBMkgZUQRwl?node-id=3-103)
создан из native Text/Frame/Vector/Instance, без UI-скриншота как содержимого.
Dark визуально проверен; Light создан и проверен чтением bindings. Starter MCP
quota ограничила финальную визуальную проверку Light и дополнительные кадры.
Эти действия не объявлены выполненными; детали в [FIGMA_DESIGN](FIGMA_DESIGN.md).

Native browser PNG находятся локально в игнорируемом `artifacts/redesign/`:
`react-desktop-dark.png`, `react-desktop-light.png`, `react-narrow-evidence.png`,
`react-real-api-no-key.png`.
Narrow и остальные независимые снимки перечислены в WORKSPACE_QA.
Desktop PNG показывают явно синтетический read-only HTTP-стенд 8002;
настоящий API проверялся отдельно на 8000 с пустым ключом и новой учебной БД
`data/private/cqa-workspace-ui.sqlite3`. Продуктового mock fallback нет.

## Границы результата

Живых OpenAI-вызовов нет. Учебные ответы не являются человеческим Ground Truth
или измерением точности модели. Отдельный frontend lint не настроен; его
прохождение не заявляется. Локальный Docker socket недоступен; контейнерную
сборку/health проверяет CI, результат конкретного финального SHA — в PR №2.
