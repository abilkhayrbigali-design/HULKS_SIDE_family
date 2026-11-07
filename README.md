# HULK’S FAMILY — Conversation Quality Analytics

CQA для оценки работы оператора: настраиваемый чек-лист, доказательства из переписки и апелляции с сохранением исходного результата. Рабочий репозиторий — [HULKS_SIDE_family](https://github.com/abilkhayrbigali-design/HULKS_SIDE_family). `HULK-S_FAMILY_REPO` — защищённый пример только для чтения.

Приложение собирается из FastAPI/SQLite и React/TypeScript/Vite. Один API-процесс выполняет ограниченное число сохранённых задач оценки; Redis, регистрация и распознавание речи не требуются. Модель приложения — OpenAI `gpt-6-luna`, выбирается через `OPENAI_MODEL`. Модель приложения и модели агентов разработки — разные настройки.

**Текущая граница проверки:** живые вызовы OpenAI во время разработки не выполнялись по просьбе пользователя; ключ в примере настроек пустой. Без ключа импорт, редактор и чтение работают, а запуск AI возвращает `503 / AI_NOT_CONFIGURED`; успешная оценка не подставляется. Проверки провайдера используют синтетические ответы и не подтверждают точность модели на Ground Truth. Точный статус задач — в [роадмапе](docs/ROADMAP.md).

## Локальный запуск

Нужны Python 3.12–3.14 (основная версия 3.13), uv, Node.js 22 с npm и Make. Из корня:

```bash
cp .env.example .env
make setup
make build
make api
```

Откройте [приложение](http://127.0.0.1:8000/). API автоматически применяет Alembic-миграции, создаёт исходный чек-лист один раз и запускает worker. SQLite хранится в `data/private/cqa.sqlite3`. Повторный запуск сохраняет данные и версии. Относительные пути БД и собранного интерфейса считаются от корня проекта, независимо от текущего каталога терминала.

Для разработки интерфейса оставьте `make api` в первом терминале и запустите `make web` во втором. Vite открывается на [localhost:5173](http://localhost:5173/) и проксирует `/api` на API. После изменения frontend для раздачи на 8000 повторите `make build`.

Сервер отдельно: `make setup-api` и `make api`. Если frontend ещё не собран, `/` возвращает 404; [API-документация](http://127.0.0.1:8000/docs) и [health](http://127.0.0.1:8000/health) доступны. `/health` проверяет реальное соединение с SQLite и возвращает `{"status":"ok"}`; при недоступной БД — 503.

## Docker Compose

Нужен Docker с Compose v2. Полное приложение, frontend и БД:

```bash
docker compose up --build --wait
```

Откройте [127.0.0.1:8000](http://127.0.0.1:8000/). Named volume `cqa-data` сохраняет БД между перезапусками. `docker compose down` останавливает контейнер; `down --volumes` удаляет локальные данные и для обычной остановки не нужен. Backend отдельно: `make docker-api` (файл `compose.api.yaml`, Docker target `api`). Полная сборка использует target `app` и включает `frontend/dist`.

Compose читает локальный `.env`, если он есть. Порт привязан к localhost. Не запускайте несколько API-процессов/реплик на одной SQLite: в MVP worker внутрипроцессный. Docker daemon и контейнерная сборка требуют отдельной проверки в среде с доступным Docker; `docker compose config --quiet` проверяет только конфигурацию.

## Настройки и данные

`.env.example` содержит названия настроек без секретов. Ключ `OPENAI_API_KEY` и подписанный `CQA_DATASET_API_URL` остаются на сервере. Не отправляйте их в чат, браузерный код или Git. Сейчас ключ добавлять не требуется: живые вызовы отложены.

- `OPENAI_MODEL=gpt-6-luna`, `CQA_LLM_REASONING_EFFORT=medium`, `CQA_LLM_MAX_OUTPUT_TOKENS=12000` — параметры анализа.
- `CQA_LLM_MAX_RETRIES=2` — до двух дополнительных попыток в общем бюджете, `CQA_LLM_TIMEOUT_SECONDS=90` — таймаут.
- `CQA_EVALUATION_CONCURRENCY=2` — параллельность worker; сетевой вызов выполняется вне транзакции БД.
- `CQA_DATABASE_URL` — локальная SQLite; `CQA_FRONTEND_DIST=frontend/dist` — каталог собранного клиента.
- `CQA_ALLOWED_ORIGINS=http://localhost:5173` — CORS для разработки. При одном origin на 8000 отдельное разрешение CORS не требуется.

Можно загрузить собственный JSON в формате организаторов или импортировать группу через серверный URL. Приватные данные храните в `data/private/`. В Git находятся только явно обозначенные синтетические примеры из `data/fixtures/synthetic/`. Содержимое диалога — данные для анализа; инструкции внутри него не изменяют чек-лист или настройки.

## Проверки

```bash
make check
make smoke
```

`make check` выполняет Ruff, сверку экспортов контрактов, серверные pytest, TypeScript, frontend-тесты и сборку. `make smoke` требует собранный frontend, поднимает настоящий HTTP-сервер с новой временной БД, проверяет миграции/seed, импорт/чтение и явный отказ AI без ключа. Он принудительно очищает ключ и URL организаторов для дочернего сервера и не вызывает внешние API. Для backend без frontend: `uv run --project backend --locked python tools/smoke_app.py --api-only`.

CI проверяет Python 3.12/3.13, frontend, полный локальный smoke и сборку/health контейнера. Наличие workflow не означает пройденный запуск: смотрите результат CI конкретного коммита. Серверные контрактные тесты сравнивают реальные ответы с общими JSON Schema; успешный JSON не является оценкой качества модели.

## Логи для диагностики

Журнал приложения выводится в терминал. Для локального сохранения:

```bash
mkdir -p artifacts
make api 2>&1 | tee artifacts/api.log
```

Контейнер: `docker compose logs --tail=100 api`. Значимые события запуска — `cqa.lifecycle`: `application_starting`, `database_ready`, `application_ready`, `application_stopped`. HTTP-сводки — `cqa.requests`; внутренние ошибки — `cqa.errors` с фиксированным кодом и безопасными местами в коде. Сбой запуска даёт `APPLICATION_STARTUP_FAILED`, недоступная БД — `DATABASE_UNAVAILABLE`.

Сводки не включают URL, ключи, транскрипты и payload. Подробные логи SDK/HTTP/SQL отключены даже при `CQA_LOG_LEVEL=DEBUG`. Файлы `artifacts/` и `*.log` игнорируются Git. Правила и события модулей — в [LOGGING.md](docs/LOGGING.md).

## Работа команды

| Участник | Ветка | Зона |
| --- | --- | --- |
| Абулхаир | `codex/abulkhair` | Интеграция, запуск, CI |
| Чингиз | `codex/chingiz` | Backend, БД, версии, апелляции |
| Нурсултан | `codex/nursultan` | AI, доказательства, расчёт, точность |
| Артём | `codex/artem` | Интерфейс и браузерные сценарии |

Все основные агенты наследуют модель и уровень рассуждения родительского агента и работают в отдельных рабочих копиях. Перед слиянием каждого изменения обязателен независимый reviewer `gpt-6.1-sol / xhigh` на итоговом SHA по [CODE_REVIEW.md](docs/CODE_REVIEW.md).

Начните с [AGENTS.md](AGENTS.md), [ROADMAP.md](docs/ROADMAP.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md), [API_CONTRACT.md](docs/API_CONTRACT.md), [SCORING.md](docs/SCORING.md) и своего задания в [AGENT_TASKS.md](docs/AGENT_TASKS.md). Роадмап обновляется вместе с реализацией; исходные записи истории не являются автоматическим подтверждением готовности этой версии.
