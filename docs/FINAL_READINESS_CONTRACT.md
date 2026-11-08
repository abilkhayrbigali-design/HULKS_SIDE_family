# Финальная проверка полноты и бюджета

2026-11-08, D-027. База — PR №6, fdf07bce4665dfc45baaada8e8718b863fb5e94f.
Main и PR №6 не изменяются. Новые живые AI-вызовы и расходы не разрешены.
Проверки используют synthetic provider/MockTransport. Промпт меняется только при
доказанном несоответствии рубрике; human labels и точность не выдумываются.

## Независимая сверка сдачи

В `POST /submission-exports` остаются `batch_id` и `team_name`; добавляются
обязательные `expected_conversation_ids` и `expected_total_records`.
ID — внешние непустые строки организаторов, не внутренние UUID. Применяется
существующая нормализация Text (trim, без преобразования числа/регистра).
Список содержит 1–1000 уникальных ID, total — строгое целое 1–1000,
совпадающее с длиной списка. Невалидный reference/дубликаты/total дают 422.

Ожидаемый набор получает пользователь из отдельного исходного JSON. UI не
выводит его из выбранного batch. Поддерживаются organizer envelope с
`isSuccess=true`, отсутствующей ошибкой, `data.records` и согласованным
`data.total_records`, а также upload-объект `records` (total при наличии
проверяется). Размер файла ограничен 16 MiB; один record даёт строковый
conversation_id. Полный текст/filename не сохраняются в storage/логах.
Источник служит независимым reference; криптографическая подлинность
организаторского набора этим не доказывается.

Side-effect-free `POST /submission-preflights` принимает
`{batch_id, expected_conversation_ids, expected_total_records}` и возвращает:
`{expected_count, batch_count, missing_count, extra_count, matches}`.
Счётчики — неотрицательные целые, matches — boolean. Валидное несовпадение
возвращает 200/matches=false; отсутствующий batch — 404, невалидный ввод — 422.
Нет новых AI-вызовов, записей БД или экспортируемого содержимого.

Сам экспорт повторно сверяет точные множества и при расхождении возвращает
409 `SUBMISSION_SCOPE_MISMATCH`. Message может содержать только безопасные
числовые счётчики в фиксированном шаблоне; details сохраняет loc/type.
Не выводить сами ID в логи/консоль/ошибку. Поведение PR №6 для pending/failed/review
строк, original до апелляций, retry полного состава и официальной схемы не меняется.
UI блокирует download до успешной проверки соответствующего batch/reference;
поздние результаты чтения файла/preflight другого контекста не применяются.

## Общий денежный лимит

Одна SQLite содержит один global account, покрывающий все новые SDK-попытки:
single, batch и retry. Это строже отдельного несвязанного лимита каждого batch.
Настройки сервера: `CQA_AI_BUDGET_USD=0`, `CQA_LLM_SERVICE_TIER=default`,
`CQA_LLM_PRICE_VERSION=`. Сумма — конечный Decimal >=0, не более 6 значащих
дробных знаков, <=9223372036854.775807 USD (int64 microUSD). Секреты не меняются.
Tier поддерживает только default. Известная pricing version:
`gpt-6-luna-standard-2026-11-08-v1`; неподдержанные model/version запрещают SDK,
сохраняя чтение/импорт/экспорт доступными. require_llm остаётся key-only.

База хранит суммы integer microUSD и уникальные reservations `(evaluation_id,
attempt)`. Лимит из настроек применяется при startup как абсолютный потолок:
изменение cap не сбрасывает committed/reserved. Ноль отключает новые вызовы;
уменьшение ниже уже учтённого также не освобождает суммы. Указываем начало учёта:
исторические вызовы до включения ledger не считаются автоматически бесплатными.

SQL-free N quote использует полный input ceiling модели 1 050 000 и заданный
max_output_tokens <=128000. Худшая Standard ставка для input/cache/long/region:
0.50 USD/M input и 0.75 USD/M output, с множителем 1.10. При output12000 резерв
равен 0.587400 USD. Это верхняя бронь, а не счёт. Источники проверены 2026-11-08:
[модель](https://developers.openai.com/api/docs/models/gpt-6-luna),
[тарифы](https://developers.openai.com/api/docs/pricing).

Перед КАЖДЫМ responses.create атомарная короткая транзакция резервирует quote.
SDK retries/redirects отключены, default tier/store=false/no tools закреплены.
Пока нет резерва, SDK не вызывается и request_count не увеличивается.
Повторное использование reservation не разрешает второй сетевой запрос.
SQL-транзакция не удерживается во время сети или ожидания.

Known validated usage получает консервативную верхнюю стоимость (ceil microUSD)
по frozen quote/catalog; неиспользованный резерв освобождается. Cached/reasoning
не суммируются второй раз. Partial/invalid/unknown usage, несовместимый reported
model, отмена или неопределённый сбой сохраняют полный резерв. Неизвестное не
становится нулём. `estimated_cost_usd` в прежнем provenance остаётся null:
новые суммы — отдельные верхние оценки ledger, не подтверждённый invoice.

При restart незавершённые reserved становятся unknown без освобождения денег.
Settlement идемпотентен; unknown не разблокируется автоматически. Прямая
production pipeline без guard/evaluation context fail-closed; тестовая Python
инъекция synthetic provider не делает сетевых запросов и не является продуктовым
обходом. Worker связывает evaluation через ContextVar scope, не меняя контракт
evaluate(transcript, checklist) у injected fake pipeline.

Важная конкуренция: если денег хватит после завершения активной попытки, guard
асинхронно ожидает освобождения её резерва без нового SDK/attempt/retry-count.
Нельзя быстро пометить весь пакет failed только из-за временно занятой квоты.
Unknown holds не считаются временно освобождаемыми; постоянной нехватке соответствует
nonretryable отказ. Сессии/транзакции БД на время ожидания закрываются.

## Read-only budget API

`GET /api/v1/ai-budget` ничего не резервирует и не меняет баланс. Ответ:

- currency: literal USD;
- limit_usd, committed_upper_usd, reserved_usd, available_usd: строки с 6 знаками;
- next_request_upper_usd: такая же строка либо null для неизвестной policy;
- active_reservations, unknown_reservations: неотрицательные целые;
- model: строка; service_tier: default; pricing_version: известная строка либо null;
- accounting_started_at: ISO UTC; enabled: boolean; blocked_reason: nullable code.

available=max(0,limit-committed-reserved). enabled только при доступном полном
следующем резерве и известной policy. Коды:
`AI_BUDGET_DISABLED`, `AI_BUDGET_EXCEEDED`, `AI_BUDGET_POLICY_UNSUPPORTED`,
`AI_BUDGET_UNAVAILABLE`, `AI_BUDGET_RESERVATION_CONFLICT` — nonretryable.
`AI_BUDGET_WAITING` применяется к read-only статусу временно занятой квоты;
не является оплаченной попыткой или поводом для автоматического POST retry.
Ошибка чтения БД — безопасный 503; UI при unknown/loading/error не включает
новые AI-действия, но сохраняет импорт, чтение, апелляции и экспорт.

UI показывает общий статус в shell и у single/batch/retry controls, суммы
объясняет как upper estimate/reservation. Нет полей денег или ключей в браузере.
Обновление после mutations/terminal и явной команды, без логов render/polling.

## Проверки и владельцы

A-20/Абулхаир: settings, canonical contracts/fixtures/exports и их тесты.
C-13/C-14/Чингиз: Pydantic/routes/services/DB/migration/worker ledger.
N-09/N-10/Нурсултан: pricing/protocol/provider/pipeline, AI-тесты и bounded rubric audit.
R-11/R-12/Артём: reference/preflight и budget UI с frontend/E2E тестами.
A-21/root: интеграция, документация, synthetic HTTP/SQLite/worker QA, полный check,
build/smoke/Playwright и отдельный Sol/xhigh Q-01 на final base/head.

Проверки включают wrong set при равных count, missing/extra/duplicates/declaredtotal,
legacy request422, mixed/error rows/retry lineage, budget0/no SDK, параллельный
reserve, временное ожидание, unknown/failure/cancel/restart/no replay/atomic rollback,
partial usage/paid invalid/retry и boundary/overflow. Ни одна проверка не обращается
к живой модели. User human files/holdout/frozen annotation package не меняются.
