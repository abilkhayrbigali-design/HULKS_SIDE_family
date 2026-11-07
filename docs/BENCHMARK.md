# Ручная разметка и offline benchmark

На текущем этапе **нет подтверждённой человеческой разметки или отчёта модельной
точности**. Ранее отдельно разрешённый разовый pilot описан в
[LIVE_PILOT.md](LIVE_PILOT.md); его разрешение использовано, новые живые вызовы
запрещены. N-08 выполняется полностью offline. CLI сравнивает сохранённые предсказания с предоставленной
человеком разметкой. Он не обращается к API, не генерирует эталон и не тратит токены.
Тестовые векторы в pytest синтетические; их совпадение не является оценкой модели.

## Подготовка ручного эталона

1. Зафиксировать одну версию чек-листа и копии транскриптов в `data/private/`.
2. **До настройки промптов** распределить диалоги на `tune` и `holdout`, записать список,
   seed/правило разбиения и SHA версии проекта в локальном протоколе. Один conversation_id
   не должен попадать в разные части, даже если меняется версия транскрипта.
3. Разметить каждую применимость/ответ по `docs/SCORING.md`: bool отличается от числа,
   N/A допускается только по условию, отсутствие действия подтверждается диапазоном.
   Для RU/KZ/EN нужен человек, понимающий язык; спорные случаи согласовать со вторым
   проверяющим. Записать annotator и объяснение с существующими message IDs для каждой строки.
4. Охватить чаты и звонки, неполное завершение, идентификацию, частичную консультацию,
   явное недовольство, клиентские/ботовые инструкции внутри переписки, N/A и нарушения.
   Аудио не расшифровывать заново; оценивать предоставленный транскрипт.
5. Настраивать prompt/model только по `tune`. На `holdout` выполнить итоговую проверку после
   фиксации промпта, версии кода и параметров. Если после просмотра holdout промпт изменился,
   нужна новая независимая отложенная выборка; переименовать старую «новым holdout» нельзя.

Требование «human» — утверждение автора файла. Программа проверяет структуру и расчёты,
но не способна установить происхождение разметки. Не выдавать ответы AI за экспертный GT.
Скрытый Ground Truth организаторов и официальная метрика команде неизвестны.

## Формат файлов

`labels.json` имеет поля:

```json
{
  "annotation_source": "human",
  "dataset_id": "local-manual-v1",
  "cases": [
    {
      "case_id": "local-001",
      "split": "tune",
      "annotator": "reviewer-local-name",
      "transcript": {},
      "checklist": {},
      "criterion_results": []
    }
  ]
}
```

Показанные пустые объекты — **места для заполнения, не валидный набор разметки**.
`transcript` — полный TranscriptSnapshot, `checklist` — полный ChecklistVersion,
`criterion_results` — по одному ProviderCriterionResult на критерий, заполненному человеком.
Порядок строк не важен. Форматы полей описаны в `docs/API_CONTRACT.md`; собственные примеры
структуры находятся в `data/fixtures/synthetic/`. Разные версии чек-листа сравнивать
отдельными файлами/отчётами: файл benchmark использует один неизменяемый снимок критериев.

`predictions.json` содержит `cases`:

```json
{
  "cases": [
    {
      "case_id": "local-001",
      "transcript_version_id": "00000000-0000-4000-8000-000000000002",
      "checklist_version_id": "00000000-0000-4000-8000-000000000004",
      "result": {},
      "error_code": null,
      "failure_provenance": null
    }
  ]
}
```

`result` — полный сохранённый ProviderResult (с usage/duration/model metadata), а не только
баллы. Для преобразования сохранённого Evaluation используются `original.criteria`, из
каждой строки исключаются вычисленные `weight`, `base_points`, `effective_weight`,
`effective_points`, `review_required`; provider/model/usage/duration берутся из provenance,
review_reasons — из evaluation. Это можно сделать локально при подготовке файла.
Не использовать `final` после апелляций как предсказание исходной модели.

Для неудачной оценки `result=null`, `error_code` — фиксированный код из
`app.evaluation.errors.MESSAGES` либо worker-код `INTERRUPTED`/`EVALUATION_INTERNAL_ERROR`;
`failure_provenance` — сохранённый provenance либо null,
если вызов не состоялся/метаданные неизвестны. Сохранять paid invalid/incomplete попытки:
неудача не означает нулевой расход. Отсутствующая prediction учитывается как missing,
а не удаляется из знаменателя accuracy.

## Приёмка подготовленного пакета без API

Существующий пакет A-18 описан в [BENCHMARK_PREPARATION.md](BENCHMARK_PREPARATION.md),
правила аудиторов — в [ANNOTATION_GUIDE.md](ANNOTATION_GUIDE.md). Frozen
`annotation-v1/` не редактируется. Люди независимо заполняют шесть файлов
`data/private/benchmark-prep/working/{tune,holdout}/{RU,KZ,EN}.labels.json`.
В каждом кейсе нужны настоящий `annotator`, все ответы и evidence; после
фактической проверки человек меняет `annotation_source` на `human`. AI не
подставляет ответы, имена, подтверждение или подпись. Частный журнал разметки
и согласования спорных случаев ведёт координатор, отдельно от JSON.

Команда ниже предназначена **человеку после реального sign-off**. Флаг
`--human-signoff` явно утверждает, что независимая человеческая работа завершена;
он не устанавливает личность и не доказывает происхождение. До этого запуск
на незаполненных файлах должен завершаться отказом. Пример для `tune`:

```bash
uv run --project backend --locked python tools/prepare_benchmark.py labels \
  --package data/private/benchmark-prep/annotation-v1 --split tune \
  --ru data/private/benchmark-prep/working/tune/RU.labels.json \
  --kz data/private/benchmark-prep/working/tune/KZ.labels.json \
  --en data/private/benchmark-prep/working/tune/EN.labels.json \
  --human-signoff --output data/private/benchmark-prep/labels.tune.json
```

Intake сверяет canonical SHA256 draft/checklist с manifest, зафиксированное
разбиение и целостность duplicate groups, dataset, точное покрытие каждого языка
выбранной части, отсутствие дублей, полные неизменённые snapshots. Типы ответов,
шкалы, N/A, полный набор критериев и message/range evidence проверяет существующий
scoring через benchmark. Пустые/`pending_human` файлы отвергаются. В этом этапе
принимается полный выбранный split: неразмеченные кейсы нельзя молча исключить.
Согласованный частичный протокол потребует отдельного решения, а не удаления
строк из frozen manifest. Если в split нет языка, его human-файл содержит
пустой `cases`; добавлять вымышленные кейсы нельзя.

Для `holdout` координатор отдельно меняет split, три входных пути и имя выхода.
Intake не объединяет части и не требует holdout labels при работе с tune.
Настройщики не получают отложенные ответы; сам инструмент не реализует
контроль доступа и не может заменить организационное разделение.

Чтобы получить `predictions.json`, сохраните выбранные terminal Evaluation
ресурсы локально в оболочке (сам адаптер ничего не запрашивает):

```json
{"cases": [{"case_id": "local-001", "evaluation": {}}]}
```

Пустой объект в примере — место для **полного** сохранённого `Evaluation`,
не валидный результат. Выбор конкретных запусков фиксируется в частном
экспериментальном протоколе до просмотра holdout; смешивать кандидатов и выбирать
лучший ответ для каждого кейса нельзя. Два запуска одного case ID отвергаются.

```bash
uv run --project backend --locked python tools/prepare_benchmark.py predictions \
  --package data/private/benchmark-prep/annotation-v1 --split tune \
  --evaluations data/private/benchmark-prep/evaluations.tune.json \
  --output data/private/benchmark-prep/predictions.tune.json
```

Адаптер проверяет conversation/transcript/checklist IDs по frozen snapshot,
принимает только `completed`/`failed` и повторно проверяет арифметику `original`.
Он читает `original.criteria` даже после апелляций, не `final` и не latest-версию.
Из сохранённого provenance переносятся model/provider, все известные usage и
duration. У failures сохраняется известный provenance либо `null`; безопасный
код ошибки сохраняется, её текст не копируется. Отсутствующие кейсы остаются
missing в benchmark, не становятся успешными или бесплатными. Формат ProviderResult
не содержит подтверждённый тариф: успешная стоимость отчёта остаётся `null`,
как и раньше; prompt version/условия эксперимента хранятся в локальном протоколе.

Обе команды создают только явно указанный новый файл в уже существующем частном
каталоге с правами `600`: полный JSON публикуется атомарно через exclusive link,
существующий файл или symlink не перезаписывается. Выберите новое имя для новой
приёмки; оригиналы и история не меняются. stdout пустой, stderr содержит
`cqa.benchmark`: INFO `benchmark_intake_started`/`benchmark_intake_completed records=...`,
ERROR `benchmark_intake_failed error=...`. Ошибка даёт exit 2, Ctrl-C — exit 130;
пути, case IDs, ответы, annotator и исходные исключения не печатаются.
Коды `BENCHMARK_PACKAGE_CHANGED`, `BENCHMARK_LABEL_COVERAGE_MISMATCH`,
`BENCHMARK_SNAPSHOT_MISMATCH`, `BENCHMARK_HUMAN_LABELS_REQUIRED`,
`BENCHMARK_OUTPUT_EXISTS` различают существенные отказы; прочий невалидный ввод
получает `BENCHMARK_INVALID_INPUT`. Справка: `tools/prepare_benchmark.py labels --help`
и `predictions --help` через тот же Python.

Это подготовка входов для прежнего `evaluate_dev.py`, а не второй benchmark,
подтверждённая accuracy или получение новых предсказаний. Новые живые AI-вызовы
остаются запрещены до отдельного разрешения пользователя.

## Запуск и интерпретация

Из корня проекта после установки backend:

```bash
uv run --project backend --locked python tools/evaluate_dev.py \
  --labels data/private/labels.json --predictions data/private/predictions.json \
  --split tune > data/private/benchmark-tune.json
```

`--split` обязателен; `holdout` запускается отдельно. stdout — агрегированный JSON,
stderr — безопасные события `cqa.benchmark`: INFO `benchmark_completed records=...` либо
ERROR `benchmark_failed error=BENCHMARK_INVALID_INPUT`. Невалидный/недоступный файл даёт
exit 2 без печати пути, текста, исходного исключения или содержимого. Частичные/неудачные
предсказания дают валидный отчёт с coverage, failed, missing; это не «успех модели».

Отчёт содержит:

- Размер выборки, coverage, число неудач/пропусков и совпадение критериев (в знаменателе
  все размеченные строки, включая неудачные/пропущенные).
- MAE итогового балла для завершённых пар с числовым итогом; отдельно число таких пар,
  совпавшие null и расхождения null/число. Нельзя интерпретировать MAE без coverage.
- По каждому критерию exact accuracy и для шкал MAE, нормализованную на максимум шкалы
  (только пары, где критерий применим с обеих сторон), с числом таких пар.
- N/A и флаги: TP/FP/FN/TN, precision/recall; отсутствие знаменателя даёт null.
  Пропуск положительного N/A/флага даёт FN, а пропуск отрицательного не создаёт TN.
- Разбивку по языку и каналу, фактический известный request_count, токены всех попыток,
  число отсутствующих usage и длительности. Частично неизвестные токены остаются null;
  cached/reasoning входят в input/output и не прибавляются повторно.
- `estimated_cost_usd=null` для успешных ProviderResult без подтверждённого тарифа;
  стоимость не придумывается. Провайдер в текущей версии сохраняет стоимость null.

Отчёт не включает диалоги, аудиоссылки, имена annotator или case IDs. Файлы с локальными
данными, даже агрегаты, сохраняйте в `data/private/`; они не коммитятся. При сравнении
кандидатов фиксируйте prompt version, модель, параметры, SHA и все попытки, включая
отброшенные проверочные вызовы, в локальном протоколе эксперимента.
