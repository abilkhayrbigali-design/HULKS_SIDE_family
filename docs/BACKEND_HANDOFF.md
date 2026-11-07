# Чингиз: backend MVP без живых вызовов

Рабочая ветка `codex/chingiz`; запись разрешена только в HULKS_SIDE_family.
Исходный репозиторий используется исключительно для чтения. Старые инкременты
C-06/C-07/C-08 и их проверки сохранены в ROADMAP/DECISIONS.

Реализованы JSON/HTTP-импорт, immutable snapshots, versioned checklists,
persisted evaluations, bounded worker, апелляции и confirm/override.
Все business routes имеют реальные Pydantic response_model. List checklist
возвращает latest_version_id/latest_version_number, detail — current_version/versions.
Ошибки валидации используют details.loc; приватный input/ctx не возвращается.

Подключение интегратору:

```python
from app.api.evaluations import install_evaluation_api
from app.services.worker import start_evaluation_worker, stop_evaluation_worker

install_evaluation_api(app)  # после install_data_api
# lifespan после миграций, session_factory, seed:
await start_evaluation_worker(app)
# finally перед engine.dispose():
await stop_evaluation_worker(app)
```

Worker использует app.state.session_factory/settings. Старт создаёт
EvaluationPipeline(settings), если Python-тест не внедрил evaluation_pipeline.
Инъекция не является режимом продукта. Отсутствующий ключ даёт 503
AI_NOT_CONFIGURED до создания запуска; успешного fake fallback нет.
Stop идемпотентен и закрывает принадлежащий приложению pipeline.

Граница AI согласована с Нурсултаном:
`await pipeline.evaluate(transcript=dict, checklist=dict)` → PipelineResult
(assessment/provenance/review_required/review_reasons). DB Session уже закрыта
во время await. Ошибка EvaluationError сохраняет безопасный код и известный
provenance. CancelledError.provenance передаёт известный usage при graceful stop
во время retry/backoff; отменённая попытка с неизвестными токенами не выдаётся за ноль.
Очередь хранится в SQLite: queued восстанавливаются; running при
рестарте/отмене становятся failed/INTERRUPTED, платный повтор не выполняется.

Апелляции сериализуются короткой BEGIN IMMEDIATE транзакцией; один open на
criterion/evaluation, revision409 при гонке и повторном решении. Original,
snapshot references и immutable decisions защищены SQL-триггерами.
Final пересчитывается calculate_assessment без AI. Run-level review flags
сохраняют исходные предупреждения; final criteria содержат текущие причины.

Миграции Alembic c001/c002 рассчитаны на SQLite; разрушительного downgrade нет.
Импорт выполняет HTTP до DB-транзакции. Исходные тексты/timestamp и подписанные
URL сохраняются без нормализации; URL/тексты не попадают в логи.

Проверки: 148 backend tests passed до дополнительной cancellation-регрессии;
после её исправления с N 473bd33 отдельно 57 tests (20 evaluation/appeals +37 data)
passed и lifecycle integration PASS против combined startup. Ruff check/format,
git diff --check чистые. Итоговый общий suite выполняет интегратор.
До интеграции тесты запускались с AI-пакетом sibling worktree d44a128:

```bash
uv run --project backend --locked python -c 'import app, pytest, sys; app.__path__.append("/home/abilkhayr/.codex/worktrees/cqa-nursultan/side_family/backend/app"); sys.exit(pytest.main(["backend/tests", "-q"]))'
```

После объединения с N-модулями достаточно `uv run --project backend --locked pytest
backend/tests`. Синтетический test pipeline явно именован synthetic-test-only и
не доказывает качество модели. Реальные API/стоимость/точность не проверялись:
пользователь попросил пока работать без живых OpenAI-вызовов.

Журналы и воспроизведение:

- cqa.evaluation: evaluation_queued, appeal_created, appeal_decision_saved — INFO
  после commit; appeal_open_conflict/appeal_decision_conflict — WARNING при 409.
- cqa.worker: evaluation_worker_started/stopped, evaluation_started/completed — INFO;
  evaluation_recovered — WARNING для прежнего running; evaluation_failed — ERROR
  при AI_TIMEOUT, INTERRUPTED или EVALUATION_INTERNAL_ERROR. Только фиксированные
  коды/состояния/числовые счётчики; никаких ID/текстов/промптов/URL.
- cqa.errors: безопасные места кода при внутренней ошибке worker/DB.
- Сценарии test_evaluations_api: RuntimeError с секретным маркером → failed без
  утечки и ровно одна диагностика; AI_TIMEOUT сохраняет usage; before_commit fault
  решения → 503, полное rollback, без события успеха; restart/concurrent decisions.
- Импорт/checklists сохраняют события из исходного LOGGING.md после commit.

Независимое ревью Q-01 текущего инкремента выполняется отдельно и передаётся
интегратору с финальными base/head SHA; исторический DONE не заменяет его.
