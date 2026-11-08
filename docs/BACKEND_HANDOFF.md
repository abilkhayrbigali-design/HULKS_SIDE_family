# Чингиз: backend MVP без живых вызовов

Рабочая ветка `codex/chingiz`; запись разрешена только в HULKS_SIDE_family.
Исходный репозиторий используется исключительно для чтения. Старые инкременты
C-06/C-07/C-08 и их проверки сохранены в ROADMAP/DECISIONS.

## Redesign workspace — C-10

Audit 2026-11-08 на `8d4faad`: backend API для трёхпанельного workspace менять
не требуется. [WORKSPACE_CONTRACT](WORKSPACE_CONTRACT.md) фиксирует привязку
selected evaluation к transcript/checklist snapshots, immutable decision.result,
N/A/flags, пагинацию, импорт и ошибки. Необеспеченные сервером assignment,
SLA/очередь приоритетов и авторы audit-событий не подменяются выдуманными полями.

[Workspace fixtures](../data/fixtures/synthetic/workspace/README.md) согласованы
с Артёмом и Нурсултаном: 120 сообщений четырёх ролей, 12→13 критериев, разные
current/archived snapshots, original65.22/final69.57, отдельные gross/custom flags
и история confirm=false → override=true. Все JSON включены в общую manifest-
проверку; исходные fixture-файлы и frontend files не менялись.

В C-10 выполнены `pytest backend/tests` — **238 passed**, Ruff check/format и
`git diff --check`. Нурсултан независимо проверил wire-схемы, ссылки и полные
Assessment серверным Decimal-расчётом. Живые OpenAI-вызовы и Ground Truth не
использовались; runtime backend/scoring/provider остаются без изменений.
Независимый reviewer выявил и исправлены два fixture-only замечания: override
reason/result.explanation согласованы с actual API; current management explanation
больше не ссылается на оскорбление архивной версии. Связь immutable decision.result,
current/final и причины теперь проверяется явно; после исправлений contract suite
повторно прошёл 50 тестов. ID/ответы/диапазоны/баллы не менялись.
[Targeted UI API review](WORKSPACE_API_REVIEW.md) подтвердил frozen snapshots,
original/final и историю нового React workspace. Найдены два P2 контекста при
ошибке загрузки и отложенном решении; повторная проверка production-сборки R
`6ffdc7f` показала PASS для обоих. Новый Q-01 относится к текущему инкременту,
а не к историческому ревью MVP. Полный итоговый UI/release проверяет интегратор.

## Существующая реализация и передача MVP

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

## C-13/C-14: финальная полнота и lifetime budget (D-027)

`SubmissionExportRequest` теперь требует независимые external IDs и strict total;
Text выполняет только trim. `POST /submission-preflights` читает выбранный batch и
возвращает только counts/matches без записи. Export повторяет exact normalized set
проверку; duplicate external IDs из разных групп не дают matches=true. Это сверка
заявленного source reference, не доказательство подлинности организаторского файла.
Для failed/pending/review сохраняются error rows и весь retry scope. Имя модели
попадает в export только при provenance.usage.request_count>0; иначе `not_run`.

`app.services.budget.SqlBudgetGuard(engine, settings)` реализует N BudgetGuard.
Startup в `start_evaluation_worker` вызывает initialize один раз: c004 global
account получает абсолютный cap, прежние reserved становятся unknown. Committed,
holds и accounting_started_at никогда не сбрасываются изменением cap. SQL-суммы —
integer microUSD; все сравнения/сложения выполняются Python int под BEGIN IMMEDIATE.
Frozen quote и unique(evaluation_id,attempt) не позволяют переиспользовать permission.
Terminal settled/unknown и accounting boundary защищены SQLite triggers.

Reserve использует FIFO asyncio.Lock только для выдачи permissions; settle/status
его не берут. Если активная попытка способна освободить достаточно резерва, guard
ожидает bounded poll0.05 с закрытой транзакцией/connection. Unknown не считается
освобождаемым. Известная проверенная usage освобождает разницу; частичная/неизвестная
сохраняет full hold навсегда. Ошибка после durable reserve переводит orphan в unknown;
если cleanup временно недоступен, следующий reserve сначала повторяет cleanup.
Этот cleanup коммитится в отдельной короткой транзакции до любых новых отказов:
duplicate/exceeded не может откатить unknown recovery. Пока запись недоступна,
read-only status учитывает локально известный orphan как unknown и выдаёт
AI_BUDGET_UNAVAILABLE, не обещая временное освобождение. GET не ремонтирует БД.
Реестр — conservative upper estimate, не invoice. Один engine/account покрывает
single/batch/retry. Режим продукта с обходом guard не добавлен.

Worker устанавливает `evaluation_scope(id)` вокруг прежнего evaluate API. Owned
EvaluationPipeline получает budget_guard; injected synthetic Python pipeline
остается только тестовой зависимостью и не делает SDK-вызовов. `GET /ai-budget`
использует одну read snapshot и не создаёт account/reservation: при сбое безопасный503.
Default cap0 блокирует все настоящие SDK attempts, не меняя чтение/импорт/экспорт.

Проверено offline: combined505 backend tests; из них18 новых ledger tests и26
submission tests. Включены two-guard race, FIFO/closed-tx wait,6jobs/concurrency2,
single/batch/retry conservation/reuse, zero/policy refusal без MockTransport вызова,
cancelled MockTransport full hold, paid-invalid→retry→cancel known charge, restart/
cap/no replay, SQL rollback, commit callback, int64 и отсутствие private markers.
Dependencies: N966ab2b/3e4edc0 и A6d748c7/6e3068e; source PR6 fdf07bc.
Q-01 независимого final SHA выполняется отдельно; реальная точность не измерена.

После Q-01 finding о rollback recovery добавлены две регрессии: durable callback
failure → первый cleanup SQL failure → duplicate/exceeded. Unknown сохраняется
отдельным commit, pending cleanup не отображается как active/WAITING.20 ledger
tests PASS после финального overlay; combined510 backend PASS после recovery fix
и N1ba8c4c (до последнего status-only overlay, отдельно покрытого20 tests).
