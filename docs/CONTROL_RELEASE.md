# Контрольная сдача FBroker — 2026-11-08

Организаторы выдали FBroker и Swap через GET; пользователь поручил оценить
только FBroker по основному чек-листу и отправить результат в Git в течение часа.
Начало обработки в этой сессии: 11:17 Asia/Almaty. Подписанные ссылки и
исходники сохранены только в игнорируемом data/private.

## Фактический результат

- FBroker:10 уникальных исходных ID,4 RU/4 KZ/2 EN, все agent chat.
- Ровно10 настоящих OpenAI HTTP-попыток, без retry;10completed/0failed.
- Модель requested/reported: gpt-6-luna; prompt cqa-2026-11-07-v1.
- Исходные восемь критериев, medium/max_output_tokens12000/timeout90s,
  concurrency2. Подстройки по контрольным ответам и human labels не было.
- Время полного локального batch:95650ms, около96секунд.
- Usage всех10:24101input/18210output/42311total, cached0, reasoning10555.
  Reasoning уже входит в output и повторно не прибавляется.
  Фактическая стоимость неизвестна, estimated_cost_usd=null.
- Официальный results/prod/results.json:10statusok,80критериев,
  исходные ID, обоснования и доказательства всех ролей с1, Decimal/N/A,
  отдельный critical_flag. Четыре оценки диалогов имеют review_reasons; они не
  заменены человеческими ответами и не скрыты как ошибки обработки.
- Ground Truth организаторов неизвестен. Точность на PROD не измерена.

Swap:3 записи (RU/KZ/EN), сохранены в отдельной группе новой SQLite и в
приватном JSON. **Ни одной оценки Swap нет; в PROD он не включён.**
Ожидается дополнительная инструкция организаторов.

## Сохранность и проверки

Прогон использовал настоящий worker/SQLite/EvaluationPipeline/OpenAIProvider.
Локальный HTTP-транспорт ограничивал число внешних POST до10, SDK и provider
retries отключены. Все запуски оценки создавались только для FBroker. Исходные версии,
ProviderResult, evaluations и manifest сохранены приватно; оба dataset checksum
после обработки неизменны. DEV-файл и прежние оценки не менялись.

Первая локальная подготовка остановилась на неверном source enum импортера
до первого внешнего запроса:0APIпопыток. Исправлен только одноразовый приватный
runner на допустимое source=dataset; не production-код. Предыдущие артефакты
сохранены, официальный полный прогон выполнен один раз.

Фактически выполнены:

- CLI export и check:10records/10ok/0errors.
- Read-only Chromium/HTTP:10FBrokercompleted и3Swapunassessed видны в работающем
  приложении,8критериев,openai provenance безsyntheticbanner, переход к
  доказательству PASS;pageerrors0,externalbrowserrequests0,consoleprivacyPASS.
  Локальный просмотр на127.0.0.1:8040 использует явно пустой AI-ключ;
  дополнительных AI-вызовов при проверке0.
- 27 синтетических тестов экспорта, Ruff/format56, contracts check и diff check.
- Синтетическая проверка budget transport: после лимита новые запросы
  отклоняются до сети, actual counter не растёт; внешних запросов в тесте0.
- Privacy scan опубликованных обоснований:0URL/email/телефонных шаблонов/
  длинных чисел/ключевых шаблонов/полных исходных реплик длиннее100символов.
  Поля transcript/audio_url/messages/usage/annotation_source/failure_provenance
  не публикуются. Исходные ссылки и ключи отсутствуют в tracked-файлах.

В Git входят только официальный PROD JSON, инструкции и безопасные агрегаты.
Одноразовые runner, логи, endpoint, исходники, БД и полные ответы остаются
в игнорируемых data/private и artifacts. Они не являются кодом новой установки.

## Диагностика и публикация

Существующие журналы: cqa.import/dataset_import_completed,
cqa.evaluation/evaluation_queued/ai_request_started/ai_request_completed,
cqa.worker/evaluation_started/evaluation_completed и cqa.submission/
submission_export_started/submission_export_completed/submission_export_failed.
Одноразовый runner использует cqa.control/control_request_started,
control_result_saved, control_batch_completed/control_batch_failed.
Intake: cqa.control_import/control_download_completed/swap_download_completed.
Логи содержат только статусы, счётчики, длительность и фиксированные коды.
Ошибка подготовки дала CONTROL_BATCH_FAILED и одну безопасную диагностику
cqa.errors без URL, ключей, текста диалогов и исходного исключения.

Независимый gpt-6.1-sol/xhigh одобрил base9e697b4/headcca74ad без findings:
10/10source snapshots/versions/checklist и80/80actual model answers/rationale/
evidence совпадают,25inclusive ranges и140non-operator context references
проверены,10итогов независимо пересчитаны Decimal. SQLite integrity/FK,
source/provenance/history,Swap0,attempts10/retry0/usage/privacy и52ссылки PASS.
Reviewer не менял файлы и не вызывал OpenAI. Самостоятельную браузерную
проверку он не повторял; выше приведён фактический read-only прогон интегратора.

Оба CI codecca74ad завершились SUCCESS: push42454779547 иPR42454852832,
включая Python3.12/3.13,frontend,fullapplication,container. Финальный status-only
SHA повторно подтверждает тот же reviewer; точные base/head/итоговыйCI/merge —
в PR№10. До завершения этих проверок merge не выполняется. Архитектура,
API и prompt не менялись; миграции и зависимости прежние.
