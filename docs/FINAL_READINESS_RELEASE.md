# Финальная техническая проверка CQA

2026-11-08, A-21 / D-027. База — PR №6, `fdf07bce4665dfc45baaada8e8718b863fb5e94f`.
Изменения подготовлены отдельно; main не сливается без команды пользователя.

## Результат

Официальный экспорт требует независимый reference из исходного JSON набора.
Preflight показывает ожидаемые, фактические, пропущенные и лишние записи;
экспорт повторяет exact-set проверку. Равное количество с другими ID отклоняется.
Pending/error/review строки, исходные оценки до апелляций и полный состав retry
сохраняются. Reference хранится в памяти интерфейса только как ID и количество.

SQLite хранит общий абсолютный USD-лимит, integer microUSD и одноразовые резервы
для каждой SDK-попытки. Одиночные оценки, пакеты и повторы используют один ledger.
Известный usage учитывается консервативно; неизвестный исход сохраняет полную бронь.
Перезапуск и изменение лимита не обнуляют учёт. Временная занятость квоты вызывает
ожидание без failed storm и дополнительных SDK-запросов. Default cap0 и пустая
pricing version блокируют новые вызовы, сохраняя импорт, чтение, апелляции и экспорт.

Исправлены подтверждённые review-дефекты: повторная строгая проверка повреждённого
Usage без утечки serializer warnings; счётчик только фактических SDK-вызовов;
привязка payload к immutable quote; отдельный durable commit восстановления
abandoned-резервов перед отказом; отклонение пустого имени модели до startup.

## Фактически выполненные проверки

| Проверка | Результат и граница |
| --- | --- |
| `make check` | PASS: исходный combined код —508pytest,19Vitest, TypeScript, Ruff/format, exports --check и production build |
| `make check-api` после последних backend fixes | PASS:518pytest, Ruff/format и canonical exports; runtime SHA `5ba7835bcb076b91a08655a1403139a52dbc9115` |
| `npm --prefix frontend run test:e2e` | PASS:51 Chromium-сценарий, включая AUD-03 success/failure queue refresh, длинную переписку, evidence, апелляции, ошибки, stale responses, reference и бюджет. Frontend после этого не менялся |
| `make smoke` | PASS: настоящий HTTP, временная SQLite, миграции/seed, импорт/чтение и no-key отказ; upstream_requests0 |
| Final HTTP/SQLite/worker/SDK QA | PASS:5 сценариев на exact runtime SHA выше;8 запросов реального AsyncOpenAI только через MockTransport, external/blocked egress0 |
| Production UI через HTTP | PASS: evidence focus, апелляция и reload, точные суммы, wrong-set при равных count, matching preflight, download3 original результатов. API не подменялся; SDK использовал MockTransport |
| Narrow visual QA | PASS:320/390px, завершённая анимация Sheet, ширина содержимого/заголовка/close в viewport, footer достижим прокруткой. Внешние и write-запросы этой проверки0 |

Final HTTP QA проверяет cap0→SDK0, cap1/concurrency2→ожидание→три успешных задачи
без starvation, replay запрет, mixed timeout+success→полный retry, partial usage→
unknown hold, отмену и restart без сброса. Preflight не пишет БД; публичные суммы
сверены с SQLite. Все7 серверов/worker и4 owned SDK/транспорта остановлены;
270 записей логов проверены на отсутствие synthetic private markers, ключа, URL и
traceback. Первоначальный локальный QA harness потребовал исправления cleanup gate;
его failed trial не заявляется прохождением продукта. Финальный отдельный run PASS.

Скриншоты находятся локально в игнорируемом `artifacts/final-readiness/`:
`actual-workspace-desktop.png`, `actual-budget-desktop.png`,
`actual-reference-desktop.png`, `actual-budget-narrow.png`.
Ранний narrow кадр был снят во время500ms анимации; после завершения анимации
горизонтальное обрезание не воспроизведено, screenshot заменён проверенным.
Синтетические QA-ответы не являются измеренными оценками модели.

Независимый reviewer `gpt-6.1-sol / xhigh` подтвердил code SHA выше относительно
базы PR №6: открытых подтверждённых findings нет. Он независимо выполнил518
backend-тестов и21 ledger/reproduced-regression проверку. Финальные base/head SHA,
подтверждение документационной дельты и CI записываются в PR, чтобы не создавать
новый непроверенный коммит ради самого отчёта.

## Ограничения

- Human Ground Truth и модельная accuracy ещё не измерены. Статический tune audit
  проверил передачу рубрики; prompt не менялся, holdout для подгонки не использован.
- Новые живые OpenAI-вызовы и расходы не разрешены и не выполнялись. Локальная
  имитация SDK не проверяет доступность сервиса или фактический счёт провайдера.
- Ledger показывает верхние оценки, а не invoice. Затраты до accounting_started_at
  автоматически не восстановлены. Unknown holds не освобождаются автоматически.
- Подлинность reference-файла проверяет команда; exact-set gate проверяет состав.
- Vite build успешен с предупреждением о JS chunk528.52kB (gzip168.47kB).
  Дальнейшее разделение bundle не включено в этот этап.
- Контейнерная сборка не запускалась локально; её результат и точные final
  base/head SHA независимого Q-01 фиксируются в PR/CI.

Правила эксплуатации: [README](../README.md), wire: [API_CONTRACT](API_CONTRACT.md),
финансовые инварианты: [FINAL_READINESS_CONTRACT](FINAL_READINESS_CONTRACT.md),
безопасные события: [LOGGING](LOGGING.md). Защищённый source repo, локальные секреты
и frozen human annotation package не менялись.
