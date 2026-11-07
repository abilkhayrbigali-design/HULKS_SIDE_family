# Передача AI/scoring — Нурсултан

Проверки текущего этапа исключительно offline: пользователь попросил не выполнять живые
OpenAI вызовы. Наличие адаптера не подтверждает доступность аккаунта или точность модели.

## Граница с backend

```python
from app.evaluation.pipeline import EvaluationPipeline
from app.evaluation.errors import EvaluationError
from app.evaluation.scoring import calculate_assessment

pipeline = EvaluationPipeline(settings)  # no API call, client created lazily
result = await pipeline.evaluate(transcript=transcript_snapshot, checklist=checklist_snapshot)
# result.assessment, result.provenance, result.review_required, result.review_reasons
await pipeline.aclose()  # shutdown: closes owned SDK client
```

Входы соответствуют `TranscriptSnapshot` и `ChecklistVersion` из INTEGRATION/API_CONTRACT.
Можно передать dict либо модели из `app.evaluation.schemas`. Вызов делается вне SQL-транзакции;
worker сохраняет исходный результат и `failed` самостоятельно. `EvaluationError` содержит
`.code`, `.safe_message` (также `.message`), `.retryable`, `.provenance`. Полный exception/ответ
модели не журналировать. Адаптер уже израсходовал свой предел повторов: worker не должен
автоматически запускать новую цепочку поверх него. При graceful shutdown адаптер добавляет
`.provenance` в `asyncio.CancelledError` и повторно выбрасывает отмену; worker сохраняет это
поле для `INTERRUPTED`. Usage локален конкретному вызову, включая оплаченные ответы до
backoff; если отменён уже следующий in-flight request, его токенные счётчики неизвестны.

Для апелляции берутся исходные provider-поля текущих строк (criterion_id, applicability,
answer, explanation, evidence, review_reasons), заменяется одна строка и вызывается:

```python
assessment = calculate_assessment(
    criteria=checklist_snapshot["criteria"], results=provider_results,
    messages=transcript_snapshot["messages"],
)
```

Функция не изменяет входы, требует полный набор критериев, различает bool/number/null,
проверяет шкалу, N/A и ссылки. Все пользовательские флаги остаются в строках; `gross_error`
заполняется только при наличии флага `gross_errors`. Системное подтверждение допустимо как
контекст evidence. Смысловая корректность объяснения требует ручной проверки/benchmark.

## Provider и настройки

`OpenAIProvider(settings, client=..., sleep=...)` поддерживает внедрение AsyncOpenAI с локальным
MockTransport для тестов. Внедрённый клиент закрывает его создатель; собственный закрывается
через `pipeline.aclose()`. В реальном адаптере retries SDK отключены. При внедрении SDK-клиента
для проверки также задаётся `max_retries=0`. Каждая попытка использует текущие критерии,
все роли и ID, Responses `text.format` с поддерживаемым strict-подмножеством схемы, `store=False`.
Метаданные провайдера никогда не просим модель генерировать. `OPENAI_MODEL=gpt-6-luna`;
таймаут и общее число повторов берутся из существующих Settings. Интегратор добавляет
`CQA_LLM_REASONING_EFFORT=medium`, `CQA_LLM_MAX_OUTPUT_TOKENS=12000`.

Использована официальная [документация GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)
и [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
Подтверждение настоящего endpoint/аккаунта отложено до разрешения пользователя.

## Логи и воспроизведение ошибок

Журнал `cqa.evaluation`: INFO `ai_request_started`, `ai_request_completed`; WARNING
`ai_request_retry`, `ai_request_failed`, `ai_request_interrupted`, `evaluation_validation_failed`. Поля — фиксированный
код, фактическая попытка, длительность. Worker пишет финальный ERROR и сохраняет ошибку;
диагностика неожиданного сбоя остаётся на обрабатывающей границе, без дублирования traceback.

`test_evaluation_provider.py` через MockTransport воспроизводит 401/403/404/400/429/503,
таймаут, отказ, incomplete, повреждённый JSON (включая сырой HTTP envelope), неверный тип
ответа, отмену в backoff/in-flight и учёт платных повторов.
`test_missing_key_never_calls_client` проверяет честный отказ без ключа. `caplog` проверяет
отсутствие синтетического приватного маркера. Необходимое подавление SDK DEBUG-логов в общей
конфигурации согласовано с интегратором.

Проверки:

```bash
uv run --project backend --locked pytest backend/tests/test_evaluation_scoring.py backend/tests/test_evaluation_provider.py
uv run --project backend --locked ruff check backend/app/evaluation backend/tests/test_evaluation*
```

Это проверки арифметики/валидации/SDK, не модельной точности. Инструкции для будущей ручной
разметки и offline benchmark находятся в `docs/BENCHMARK.md` после реализации N-04.

Фактически выполнено на финальном AI-коде: `make check UV=/tmp/dataton-review-tools/bin/uv` —
194 passed (23 scoring, 28 provider, 14 benchmark), Ruff/format/contract exports успешны.
Standalone CLI из `/tmp` на временных synthetic protocol vectors вернул JSON/exit 0;
повреждённый файл дал только safe error/exit 2 без приватного маркера. Чингиз подтвердил
совместимость своим набором worker/appeals/data; окончательная интеграционная проверка
и отдельный Q-01 относятся к SHA объединённой версии. Новых живых вызовов/GT-метрик нет.
