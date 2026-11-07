# Synthetic workspace fixtures

Вымышленный набор для regression-тестов трёхпанельного React workspace.
Это вручную заданные wire-примеры, не данные клиентов, ответы модели или
человеческая Ground Truth. `provider=synthetic`; request_count иллюстрирует
формат происхождения результата, а не фактический AI-вызов. Токены и стоимость
неизвестны и равны null. Набор не добавляется в seed и не является fallback продукта.

Два снимка одного вымышленного диалога содержат по 120 сообщений с operator,
client, bot и system. Никаких действительных счётов, документов, вложений,
аудиоссылок или внешних URL в них нет. Навигация учебного приложения вымышлена.
Расширенные чек-листы имеют 12/13 критериев; их сокращённые учебные инструкции
не заменяют начальный чек-лист из `checklist.initial.json`.

| Файл | Назначение |
| --- | --- |
| conversation.current.json | Текущий transcript v2; latest_evaluation указывает на evaluation.current |
| conversation.archived.json | Ответ GET карточки с transcript_version_id от evaluation.archived. current_transcript_version_id продолжает указывать на v2 |
| checklist.v1.json / checklist.v2.json | Неизменяемые правила старого/нового запуска, 12/13 критериев. Новый критерий имеет section=null |
| evaluation.archived.json | Сохранённый старый запуск: original65.22, final69.57, revision2, gross_error=true |
| evaluation.current.json | Новый запуск с другими снимками: original/final100, revision0, gross_error=false |
| evaluations.page.json | История двух завершённых запусков, новый первым |
| appeals.page.json | Две resolved-апелляции старого запуска, более поздняя первой |
| decision.override.response.json | Ответ сохранения второго решения, совпадающий с текущим старым запуском |
| evaluation.failed.json | **Альтернативный** ответ текущего запуска для отдельного сценария AI_TIMEOUT. Не добавляется третьим запуском в базовую историю |

Для альтернативного failed-сценария route helper должен согласованно заменить
evaluation.current и соответствующие summary/list значения; одновременно отдавать
completed и failed с одним ID нельзя. Это обычные fixture-варианты, не мутация
сохранённого терминального запуска настоящего сервера.

Основные проверки:

- Сопоставлять карточку и правила по ID выбранного запуска. Для old run выдавать
  conversation.archived и checklist.v1 даже при наличии latest/current v2.
- Gross=true в архиве подтверждается оскорблением m0014. В v2 оно заменено на
  корректную реакцию. Custom flag supervisor_offer=true есть в обоих снимках:
  он не делает gross_error=true автоматически и не влияет на баллы.
- Waiting_notice=N/A исключает вес5. У v1 сумма весов120, применимо115;
  original base75 →65.22. После override next_step base80 →69.57.
  У v2 весов140, применимо135, все применимые критерии выполнены →100.
- Исходный next_step=false намеренно является ошибкой **учебной** первичной
  разметки: в m0017 действие есть. Первое confirm сохраняет false; второе
  override исправляет его. Историческое decision.result первого обращения
  остаётся false, хотя appeal.current.answer уже true. Это проверка сохранности
  аудита, не пример правильной работы модели или проверяющего.
- Идентификация ссылается на range m0006–m0009: system m0008 подтверждает
  результат, затем operator m0009 передаёт документ. System является контекстом
  действия оператора. Отсутствие прощания подтверждено диапазоном m0118–m0120.

`manifest.json` регистрирует каждый JSON по действующему `contracts/openapi.json`.
Проверки из корня репозитория:

```bash
uv run --project backend --locked pytest backend/tests/test_contracts.py
```

Они проверяют wire-формат, полноту manifest, принадлежность снимков, пересчёт
original/final серверной функцией, отдельные flags и неизменяемую историю.
Никакой provider или сетевой клиент при подготовке этого набора не вызывается.
