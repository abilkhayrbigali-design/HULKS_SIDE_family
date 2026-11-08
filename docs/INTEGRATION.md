# Передача интеграции A-14/A-15

Рабочий репозиторий — HULKS_SIDE_family. Репозиторий-пример только для чтения. Ниже описаны фактические границы текущей сборки; историческое состояние A-01/A-02 сохранено в Git и журнале роадмапа. Прежняя no-live граница снята пользователем по D-021; четыре живые оценки gpt-6-luna выполнены в SUB-02 (см. LIVE_ACCEPTANCE.md). Offline-тесты по-прежнему не обращаются к OpenAI.

## Сборка и ресурсы

`create_app(settings)` регистрирует data/evaluation API, безопасные обработчики и схемы ошибок. Lifespan выполняет:

1. Создание одного engine с foreign keys, busy timeout и WAL для файловой SQLite.
2. Alembic на connection этого engine; это позволяет мигрировать ту же memory БД, которую используют сессии.
3. `app.state.session_factory = session_factory(engine)` и идемпотентный `seed` исходного чек-листа.
4. `await start_evaluation_worker(app)` после готовности БД.
5. При завершении — `await stop_evaluation_worker(app)`, закрытие memory keeper и `engine.dispose()`.

`:memory:` получает уникальную named shared-memory SQLite и QueuePool с отдельным connection для каждой транзакции. Keeper удерживает БД до завершения lifespan. StaticPool здесь запрещён: polling worker мог бы commit незавершённой транзакции HTTP-запроса.

Все HTTP-обработчики и worker используют `app.state.session_factory`. Повторно вызывать `install_data_api` после `create_app` или создавать второй engine для той же интеграционной проверки не нужно. Для проверки commit-отказа патчится фактический `app.state.engine` после входа в TestClient; чтобы изолировать отказ HTTP от polling, worker можно остановить внутри синтетического теста.

## Backend и AI

Маршруты подключаются через `install_data_api` и `install_evaluation_api`. Worker стартует/останавливается функциями из `app.services.worker`.

```python
pipeline = EvaluationPipeline(settings)
result = await pipeline.evaluate(transcript=transcript_snapshot, checklist=checklist_snapshot)
# result: assessment, provenance, review_required, review_reasons
await pipeline.aclose()
```

Pipeline и `calculate_assessment(criteria=..., results=..., messages=...)` принадлежат AI-модулю. Сохранение результата/ошибки, очередь, атомарность апелляций и snapshot-история принадлежат backend. Сетевой вызов выполняется после закрытия транзакции загрузки снимков. Worker закрывает только созданный им pipeline; тестовый injected pipeline остаётся собственностью теста.

Перед созданием настоящего evaluation проверяется `settings.require_llm()`. При отсутствии ключа API возвращает `503 / AI_NOT_CONFIGURED`, запуск и успешная оценка не создаются. `app.state.evaluation_pipeline` можно внедрить из Python для синтетических тестов; HTTP/настройки приложения не включают такой mock-режим. Startup не выполняет пробный запрос модели; ранее сохранённые queued обрабатываются обычным worker после запуска, если ключ настроен.

SDK импортируется до настройки общих логов. Затем OpenAI/HTTP/SQL payload-логи подавляются даже при `OPENAI_LOG=debug` и `CQA_LOG_LEVEL=DEBUG`. Прикладные события остаются в `cqa.*`, без URL, секретов и текстов диалогов. Подробности — в [LOGGING.md](LOGGING.md).

## Интерфейс и контракты

Frontend использует hash-навигацию, базовый API `/api/v1`. Dev Vite проксирует `/api` на 8000. Production `make build` создаёт `frontend/dist`; API отдаёт `/` и `/assets`. Catch-all отсутствует, поэтому ошибочный API-путь остаётся JSON 404, а неверный метод `/health` сохраняет 405 и `Allow: GET`.

Pydantic response_model документируют и проверяют реальные business-ответы. Общая ErrorResponse применяется к HTTP-ошибкам в runtime OpenAPI. Канонический источник — `contracts/definitions.py`; экспорты и синтетические примеры проверяются автоматически. `test_application.py` сверяет runtime пути/методы/статусы и канонические примеры запросов/ответов с реальными runtime schemas, а также реальные HTTP-ответы импорта/чек-листов/диалогов. Верный JSON не доказывает точность оценок модели.

## Запуск и приёмка

Команды запуска и журналов — в [README.md](../README.md). `make check` проверяет backend, схемы и frontend; `make smoke` запускает отдельный сервер с новой временной БД, пустыми ключом/URL организаторов, собранным UI и проверкой честного отказа AI. Успех помечается `upstream_requests=0`. Процесс останавливается до удаления временной БД.

Docker target `api` содержит backend и Alembic; `app` добавляет Vite-сборку. `compose.yaml` запускает один API-процесс и сохраняемый volume. Docker daemon локально недоступен; конфигурация проверяется `docker compose config --quiet`, фактическую сборку/health должен подтвердить CI итогового коммита.

Живая интеграция A-03 подтверждена SUB-02 на собственных синтетических входах; API-изменение критерия, snapshots и история проверены отдельно от UI-редактора offline. Пользовательская разметка получена:65диалогов/520ответов; первый BEN-01 на45tune дал319/360совпадений(88.61%),MAE7.2542/100 (TUNE_BASELINE.md). N-04 остаётся открытым: N-08/разбор tune,4примечания holdout,finalfreeze и независимый holdout-прогон. Синтетические тесты и успешные живые ответы не заменяют этот этап.
