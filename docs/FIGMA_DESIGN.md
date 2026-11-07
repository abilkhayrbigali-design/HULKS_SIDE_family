# Figma: рабочая станция CQA

A-16: основной редактируемый макет готов, 2026-11-08. Dark прошёл структурную и визуальную проверку. Light создан и проверен чтением bindings; его финальная визуальная проверка остановлена лимитом Figma Starter MCP.

## Файл и кадры

- [Figma Design: HULK’S FAMILY — CQA Workspace](https://www.figma.com/design/vEvqJlR06dJtBMkgZUQRwl).
- [Основной Dark, node 3:103](https://www.figma.com/design/vEvqJlR06dJtBMkgZUQRwl?node-id=3-103).
- [Основной Light, node 8:122](https://www.figma.com/design/vEvqJlR06dJtBMkgZUQRwl?node-id=8-122).
- Страницы: Workspace `0:1`, Components `3:110`.
- Dark screenshot: `/home/abilkhayr/.codex/visualizations/2026/11/07/01a1b701-6abb-74a2-8720-d09bf72174aa/figma-redesign/cqa-workspace-dark.png` (1440 × 900). PNG — только доказательство QA; в Figma он не загружался.
- `cqa-workspace-light-pre-correction.png` — промежуточное непрошедшее изображение, не финальный результат. После него instance text bindings исправлены отдельным вызовом; финальный screenshot недоступен из-за квоты.

## Геометрия и иерархия

Desktop — 1440 × 900. Header 56 px; тело 844 px. Rail 56, очередь 264, транскрипт 700, оценка 420 px. Центральная переписка шире обеих боковых панелей. Вложенные блоки и повторяемые строки используют auto-layout.

| Часть | Dark node ID | Назначение |
| --- | --- | --- |
| Root | `3:103` | Полная рабочая станция |
| Header | `3:104` | Brand, контекст и synthetic disclosure |
| Rail | `3:106` | Диалоги и чек-листы |
| Queue | `3:107` | Три синтетических диалога; только доступные API-поля |
| Transcript | `3:108` | Сообщения, роли, ID и исходные timestamp |
| Audit | `3:109` | Исходный/финальный итог, критерии, объяснение, апелляция |
| Transcript scroll | `5:245` | Независимая область переписки; длинное содержимое намеренно за viewport |
| Audit scroll | `5:318` | Независимая область критериев и объяснения |
| Queue list | `5:188` | Отдельная область списка |
| Selected criterion | `5:347` | Контакт; нейтральная подсветка |

Figma — редактируемый макет, не исполняемый React. Указанные scroll properties и кнопки описывают поведение для реализации; интерактивные переходы и responsive проверяет frontend QA.

## Discovery и переиспользование

До построения просмотрены App.tsx, ui.tsx, ConversationView.tsx, styles.css и API-типы. Code Connect `*.figma.*` в текущем frontend отсутствует. Исходный CSS stack — Manrope / Inter / Arial; для redesign с Артёмом согласован **Inter** в Figma и React.

Выполнены get_libraries и scoped search_design_system по добавленным библиотекам: whole-view inbox, Button, Badge, text field, surface/space и body/border styles. Подходящего общего inbox composite не найдено. Отобран Simple Design System Button, component set key `cc8b558dc7d9684011b6b99ce8e6509399bc836b`: 18 вариантов, Small 32 px, Inter. Его экземпляры остаются связанными с библиотекой; применены CQA color/type overrides. Остальные найденные mobile/Material роли не совпадают с согласованными graphite/Inter/compact семантиками; для CQA созданы локальные reusable компоненты.

| Локальный компонент | Main node ID | Использование |
| --- | --- | --- |
| CQA/Queue item | `4:2` | 3 instances, TEXT properties ID/Language/Title/Status/Score |
| CQA/Message | `4:10` | 8 instances, TEXT role/ID/time/body и BOOLEAN Evidence |
| CQA/Criterion row | `4:17` | 8 instances, TEXT name/answer/weight/points |
| CQA/Score metric | `4:22` | 2 instances, TEXT label/value |

Дополнительно в каждом основном кадре 5 instances выбранного библиотечного Button. Lucide SVG взяты из установленного lucide-react и импортированы как редактируемые vector paths; иконки не перерисованы вручную. Полных UI image fills нет.

## Tokens и типографика

Общие primitives: 36 COLOR variables. Семантические Dark/Light: по 19 COLOR aliases к primitives. Layout/font: 15 переменных. Итого 89 variables в четырёх коллекциях; scopes и WEB code syntax заданы явно.

Starter Plugin API вернул `Limited to 1 modes only`. Поэтому использованы две согласованные коллекции **CQA Theme Dark** и **CQA Theme Light**, каждая с одним разрешённым mode. Они ссылаются на общие primitives. Это не нативная двухрежимная коллекция: Light instances имеют явные overrides на Light variables. Другой план не подключался и не оплачивался.

| CSS semantic variable | Dark | Light |
| --- | --- | --- |
| `--cqa-app` | `#101113` | `#F6F7F9` |
| `--cqa-panel` | `#17191D` | `#FFFFFF` |
| `--cqa-raised` | `#202329` | `#F5F6F8` |
| `--cqa-selected` | `#292D34` | `#E8EBF0` |
| `--cqa-border` | `#30343A` | `#DDE1E7` |
| `--cqa-text` | `#F3F4F6` | `#181B21` |
| `--cqa-muted` | `#ADB3BF` | `#536072` |
| `--cqa-faint` | `#87909E` | `#687487` |
| `--cqa-brand` | `#78C634` | `#78C634` |
| `--cqa-on-brand` | `#13200B` | `#13200B` |
| `--cqa-evidence-bg` | `#1A2718` | `#EFF8E8` |
| `--cqa-evidence-border` | `#557C31` | `#7AA84B` |
| `--cqa-evidence-text` | `#B6E78F` | `#345B17` |
| `--cqa-pass-bg` | `#14302B` | `#E6F5EF` |
| `--cqa-pass-text` | `#66D0BA` | `#17664F` |
| `--cqa-warning-bg` | `#352B1D` | `#FFF2D9` |
| `--cqa-warning-text` | `#EDC17D` | `#845617` |
| `--cqa-danger-bg` | `#361F24` | `#FCECEE` |
| `--cqa-danger-text` | `#F49DAA` | `#A32E45` |

Brand остаётся `#78C634` для primary/evidence. Selected — нейтральный `selected`; pass — отдельный teal `pass-text/pass-bg`, нарушение — danger, N/A — muted. Поля не различаются одним цветом: видны ответы Да/Нет/N/A, ID доказательств и подписи.

Spacing: 4/8/12/16/20/24/32; radius 4/6/8. Layout sizes: header 56, rail 56, queue 264, audit 420. Внешняя desktop геометрия намеренно фиксирована; React должен сохранять широкую переписку и сворачиваемые панели.

Восемь локальных text styles: Caption 11/16 Regular; Meta 12/16 Regular; Body 13/20 Regular; Label 13/20 Medium; Section 16/24 Medium; Heading 18/26 Semi Bold; Score 28/36 Semi Bold; Brand 14/20 Semi Bold. Font styles сначала проверены через listAvailableFontsAsync, затем загружены. Явный family assertion всех 117 текстовых узлов Dark: только Inter. Для Light при создании также только Inter.

## Синтетические данные и семантика

Основной кадр использует авторский synthetic-ru-001 из предварительного preview: 8 сообщений и 8 исходных критериев. Контакт = Нет, идентификация = N/A; применимый вес 80; итог 81,25. Исходная и финальная оценки совпадают, revision 0, решений проверяющего нет. AI не вызывался — это явно указано в header и источнике оценки.

Выбранный контакт имеет исходный вес 10 и вклад 0,00. Нейтральный selected row связан с зелёным диапазоном m0001–m0002. N/A исключён из суммы весов; gross_errors — отдельный флаг с весом 0, без автоматического обнуления. Queue дополнительно содержит авторские KZ 87,50 и EN 76,92; EN демонстрирует отдельный gross flag. Эти значения не являются human Ground Truth или измерением модели.

Число критериев в Figma — снимок восьми исходных правил. Оно не задаёт лимит API/React: реализация должна отображать любую сохранённую версию и обеспечивать прокрутку. Состояния длинных/старых snapshots проверяются frontend/backend synthetic fixtures отдельно.

## Фактически выполненная QA

| Проверка | Результат |
| --- | --- |
| Dark 3:103 | 247 descendants: 65 FRAME, 39 VECTOR, 117 TEXT, 26 INSTANCE |
| Light 8:122 | Те же native counts при создании; текстовые overrides после clone исправлены отдельным вызовом |
| Растровый UI | 0 IMAGE-filled nodes в обоих кадрах; никаких screenshot-child/background |
| Font assertion | Dark PASS: все 117 TEXT — Inter; Light create readback — Inter |
| Dark visual | Первый screenshot обнаружил black fallback у same-variable instance overrides; targeted RGB fallback исправлен, corrected screenshot проверен |
| Light color readback | После отдельного hydrated rebind текст m0001 имеет Light variable `VariableID:3:66`, цвет #181B21 |
| Семантика Dark | Нурсултан read-only проверил PNG: N/A/веса/81,25/отдельный флаг/исходный и финальный/диапазон верны |
| Контраст | Локальная формула относительной яркости: важные текстовые пары обеих тем ≥4,5:1 |
| Дополнительные narrow/loading/error/history frames | NOT_CREATED; работу остановил фактический Starter MCP limit |

Контраст text/panel: Dark 15,992:1 / Light 17,247:1; muted/panel 8,362 / 6,395; faint/panel 5,458 / 4,733; on-brand/brand 8,010 в обеих темах; evidence 10,997 / 7,256; pass 7,595 / 6,122; warning 8,269 / 5,701; danger 7,436 / 6,055. Это проверка точных token pairs, не заменяет QA итогового browser UI.

## Лимит и оставшаяся синхронизация

Финальный get_screenshot Light вернул фактический отказ: `You've reached the Figma MCP tool call limit on the Starter plan`. whoami подтвердил Starter. После этого новые Figma edit/read/screenshot операции не выполнялись; другой инструмент для обхода лимита не использовался. Светлый кадр не объявляется прошедшим финальную визуальную проверку.

Два замечания переданы в React и остаются **pending Figma sync** до восстановления штатного доступа:

1. Колонка «Баллы» должна стать «Вклад /100» либо иметь явное объяснение нормализации: 18,75 может превышать исходный вес 15 при N/A.
2. Footer «Бот и система скрыты» следует заменить фактическим состоянием: в основном synthetic RU нет этих ролей; не обещать отсутствующий контекст.

В Figma пока нет отдельных кадров подачи/решения апелляции, ошибок, narrow и истории. Нельзя использовать основной screenshot как доказательство их работы. Базовый editable frame с геометрией и токенами передан Артёму перед началом React; затем переданы заполненный Dark и corrected PNG для синхронизации. Финальное сравнение с React и browser QA ведёт интегратор.

## Референсы

Использованы паттерны, без копирования чужих assets или интерфейса:

- [Intercom Inbox](https://www.intercom.com/helpdesk/inbox): рабочая очередь, переписка и раскрываемый контекст.
- [Linear UI redesign](https://linear.app/changelog/2024-03-20-new-linear-ui): спокойная иерархия, плотность, согласованные светлая и тёмная темы.
- [Zendesk Conversations](https://support.zendesk.com/hc/en-us/articles/7043661945370-Using-the-Conversations-view): связность переписки, оценок, комментариев и review.

Все Figma данные авторские и синтетические. Private datasets, БД, .env и реальные транскрипты в документ не переносились. Живых OpenAI, Weave или генеративных Figma вызовов не было.
