# tech.md — ядро проекта

version: v4 (2026-08-24)
changelog:
- v4 — дефолтный источник мониторимых чатов `sources.json` (раздел 8.1), поле `origin` в `MonitoredChat` (раздел 5), эталонная вертикаль скелета переопределена (раздел 14).
- v3 — обязательный набор тестов на фейковых сообщениях для модуля релевантности (раздел 12.1).
- v2 — правило «без комментариев в коде» (раздел 13), убран пункт про комментарии из конвенции коммитов.
- v1 — первая версия ядра.

Единственный источник истины по проекту. Любая сессия (тимлид и разработчик — одна и та же роль, Никита) обязана прочитать этот файл перед началом работы и следовать ему дословно. Контракты (схема БД, DTO, интерфейсы провайдеров, форматы ответов LLM) не выдумываются на месте — если нужного контракта здесь нет, сессия останавливается и выдаёт блок `CONTRACT GAP` (см. раздел «Дисциплина CONTRACT GAP»), не пишет код с придуманным типом.

Файл версионирован, правки только append-only, каждое изменение контракта бампает версию и добавляет строку в changelog.

---

## 1. Проект

Телеграм-бот для поиска фриланс-заказов внутри Telegram.

Два режима работы:

1. **Мониторинг загруженных чатов.** Пользователь добавляет боту чаты (группы/супергруппы), где бот состоит участником. Бот читает входящие сообщения, LLM оценивает, ищет ли автор разработку, подходящую под портфолио владельца. При совпадении бот не пропускает сообщение: сохраняет его текст, ID и username автора в БД и присылает владельцу уведомление с кнопкой «Написать», ведущей в личку автору.
2. **Discovery — автопоиск новых чатов.** Отдельный конвейер сам ищет публичные Telegram-группы/каналы, которые могут содержать заказы по профилю владельца: генерирует поисковые запросы на основе портфолио, ищет чаты через два независимых провайдера, дедуплицирует, обогащает последними сообщениями, прогоняет через LLM-фильтр релевантности и сохраняет подходящие чаты в БД для дальнейшего добавления в мониторинг.

Портфолио (стек, репозитории, описание) подтягивается из GitHub API по токену и username из `.env`, используется как контекст для обоих режимов.

Владелец и единственный пользователь бота — Никита. Бот не публичный, все команды закрыты владельцем.

---

## 2. Стек

- Python 3.12+, менеджер зависимостей и запуска — `uv`.
- Telegram Bot API — `aiogram` 3.x (мониторинг загруженных чатов, команды управления, уведомления).
- Telegram User API (MTProto) — `Telethon` (discovery: глобальный поиск, чтение истории публичных каналов без вступления). Выбор обоснован в разделе 3.
- БД — SQLite, ORM — `SQLAlchemy 2.0` (async, `Mapped`/`mapped_column`), миграции — `Alembic`.
- LLM — DeepSeek API (relevance-классификация сообщений/чатов, генерация поисковых запросов).
- Web-поиск — `SearXNG` (self-hosted, discovery-провайдер №2, запросы `site:t.me`).
- Логи — `loguru`.
- Тесты/линт/типы — `pytest`, `ruff`, `pyright`.
- Инфраструктура — `Docker` + `docker-compose`, запуск на VPS одной командой (`docker compose up -d`).

### 2.1. Telethon vs Hydrogram — решение

Выбран **Telethon**. Причины:
- Прямой, хорошо задокументированный доступ к сырому MTProto-методу `functions.messages.SearchGlobalRequest`, чей ответ (`messages.ChannelMessages` / `messages.MessagesSlice`) содержит поле `.chats` — ровно то, что нужно discovery-провайдеру №1 по ТЗ.
- Зрелая, стабильная библиотека с большим сообществом и предсказуемым API для чтения истории публичных каналов по `access_hash`, полученному из результатов поиска, без вступления в чат.
- Hydrogram (форк Pyrogram) даёт похожий доступ к raw-функциям, но менее документирован именно для `SearchGlobal`-сценария и обладает менее predictable API для этой конкретной задачи.

---

## 3. Архитектура и структура папок

```
project/
  pyproject.toml
  uv.lock
  alembic.ini
  alembic/
    env.py
    versions/
  src/
    app/
      config.py                  # pydantic-settings, читает .env
      logging.py                 # настройка loguru
      db/
        base.py                  # Declarative Base, async engine, session factory
        models.py                # SQLAlchemy 2.0 модели (раздел 5)
      repositories/
        monitored_chats.py
        leads.py
        discovered_chats.py
        search_queries.py
        portfolio.py
      bot/
        main.py                  # entrypoint aiogram, Dispatcher, регистрация роутеров
        middlewares/
          owner_only.py          # пропускает команды только от OWNER_TG_ID
        handlers/
          commands.py            # /start /help /add_chat /list_chats /remove_chat /status
          discovered.py          # /discovered — просмотр и подтверждение найденных чатов
          monitoring.py          # хендлер входящих сообщений в мониторимых чатах
        keyboards.py             # фабрики inline-клавиатур (кнопка «Написать» и др.)
      telethon_client/
        client.py                # фабрика/singleton TelegramClient (user session)
        search.py                # обёртка над SearchGlobalRequest
        history.py                # получение последних N сообщений публичного чата
      discovery/
        candidate.py              # DiscoveredSourceCandidate (раздел 6)
        providers/
          base.py                 # Protocol SourceProvider
          telegram_search.py      # TelethonGlobalSearchProvider
          searxng_search.py       # SearxngProvider
        query_generator.py        # LLM-генерация поисковых запросов из портфолио
        pipeline.py                # оркестрация discovery (раздел 6)
      llm/
        deepseek_client.py         # низкоуровневая обёртка над DeepSeek API
        relevance.py                # промпты + разбор ответа в RelevanceVerdict
        queries.py                  # промпт генерации поисковых запросов
      portfolio/
        github_client.py            # обёртка над GitHub REST API
        service.py                   # синк репозиториев в БД, сборка сводки навыков
      services/
        lead_service.py              # оценка входящего сообщения → сохранение Lead → уведомление
        chat_service.py               # добавление/удаление мониторимых чатов
      scheduler.py                    # периодические задачи (discovery run, portfolio sync)
  tests/
    unit/
    integration/
  docker/
    Dockerfile
    docker-compose.yml
    searxng/
      settings.yml
  sources.json                     # дефолтный источник мониторимых чатов, раздел 8.1
  .env.example
  tech.md
  CLAUDE.md
```

Слои: `handlers` — тонкие, только парсинг апдейта и вызов сервиса. `services` — бизнес-логика. `repositories` — единственная точка доступа к БД (никаких прямых запросов из сервисов/хендлеров). `providers`/`llm`/`telethon_client`/`portfolio` — обёртки над внешними системами за интерфейсами, чтобы в тестах подменяться фейками.

---

## 4. Переменные окружения (`.env.example`)

```
# aiogram
BOT_TOKEN=
OWNER_TG_ID=                     # numeric Telegram user id владельца — единственный, кто может слать боту команды

# Telethon (user account, для discovery)
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELETHON_SESSION_PATH=./data/telethon.session

# DeepSeek
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# GitHub (портфолио)
GITHUB_TOKEN=                    # fine-grained PAT, только read-only public repo scope
GITHUB_USERNAME=

# SearXNG
SEARXNG_BASE_URL=http://searxng:8080

# Дефолтный источник мониторимых чатов (раздел 8.1)
SOURCES_FILE_PATH=./sources.json

# БД
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db

# Прочее
LOG_LEVEL=INFO
DISCOVERY_INTERVAL_MINUTES=180
DISCOVERY_MESSAGES_PER_CHAT=20   # сколько последних сообщений грузить для оценки нового чата
DISCOVERY_QUERIES_PER_RUN=5
```

Конфиг читается один раз через `pydantic-settings` в `app/config.py`, ни один модуль не читает `os.environ` напрямую.

Комментарии в `.env.example` — исключение из правила «код без комментариев» (раздел 13): это конфигурационный формат, не код.

---

## 5. Схема БД (SQLAlchemy 2.0, Alembic)

```python
class DiscoveryProvider(str, enum.Enum):
    telethon_search = "telethon_search"
    searxng = "searxng"


class DiscoveryStatus(str, enum.Enum):
    pending = "pending"  # кандидат найден, метаданные/сообщения ещё не загружены
    fetched = "fetched"  # сообщения загружены, ждёт оценки LLM
    evaluated = "evaluated"  # оценён, но статус ниже точнее — используется approved/rejected
    approved = "approved"  # LLM признал релевантным
    rejected = "rejected"  # LLM признал нерелевантным


class MonitoredChatOrigin(str, enum.Enum):
    sources_file = "sources_file"  # синк из sources.json (раздел 8.1)
    command = "command"  # добавлен вручную через /add_chat


class MonitoredChat(Base):
    __tablename__ = "monitored_chats"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_chat_id: Mapped[int] = mapped_column(unique=True, index=True)
    title: Mapped[str]
    username: Mapped[str | None]
    invite_link: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(default=True)
    origin: Mapped[MonitoredChatOrigin]
    added_at: Mapped[datetime] = mapped_column(default=utcnow)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    monitored_chat_id: Mapped[int] = mapped_column(ForeignKey("monitored_chats.id"), index=True)
    tg_message_id: Mapped[int]
    tg_user_id: Mapped[int] = mapped_column(index=True)
    tg_username: Mapped[str | None]
    tg_first_name: Mapped[str | None]
    message_text: Mapped[str]
    relevance_reason: Mapped[str]
    found_at: Mapped[datetime] = mapped_column(default=utcnow)
    notified_at: Mapped[datetime | None]
    __table_args__ = (UniqueConstraint("monitored_chat_id", "tg_message_id"),)


class DiscoveredChat(Base):
    __tablename__ = "discovered_chats"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_chat_id: Mapped[int | None] = mapped_column(unique=True)
    username: Mapped[str | None] = mapped_column(unique=True)
    title: Mapped[str | None]
    link: Mapped[str]
    provider: Mapped[DiscoveryProvider]
    status: Mapped[DiscoveryStatus] = mapped_column(default=DiscoveryStatus.pending)
    relevance_reason: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    evaluated_at: Mapped[datetime | None]


class SearchQuery(Base):
    __tablename__ = "search_queries"
    id: Mapped[int] = mapped_column(primary_key=True)
    query_text: Mapped[str] = mapped_column(unique=True)
    generated_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_run_at: Mapped[datetime | None]


class PortfolioItem(Base):
    __tablename__ = "portfolio_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    repo_name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    topics: Mapped[str | None]  # JSON-строка списка топиков
    language: Mapped[str | None]
    html_url: Mapped[str]
    synced_at: Mapped[datetime] = mapped_column(default=utcnow)
```

Дедупликация на уровне БД: `MonitoredChat.tg_chat_id`, `DiscoveredChat.tg_chat_id`/`username`, `SearchQuery.query_text` — все `unique`, конфликт ловится через `INSERT ... ON CONFLICT DO NOTHING` либо предварительный `SELECT` в репозитории (единообразно по всем репозиториям — выбрать один подход и не смешивать).

Миграции: только через `alembic revision --autogenerate`, ручные правки `alembic/versions/*` только для проверки корректности сгенерированного скрипта. Каждая задача, меняющая `db/models.py`, обязана нести миграцию в том же коммите/PR.

---

## 6. Discovery-конвейер — контракт

### 6.1. `DiscoveredSourceCandidate` — единый DTO обоих провайдеров

```python
@dataclass(frozen=True)
class DiscoveredSourceCandidate:
    provider: DiscoveryProvider
    username: str | None
    tg_chat_id: int | None
    title: str | None
    link: str
    raw_snippet: str | None
```

Ключ дедупликации — `dedupe_key()`: `username.lower()` если есть, иначе `tg_chat_id`, иначе нормализованный `link`. Ни один провайдер не пишет в БД напрямую — только конвейер (`discovery/pipeline.py`).

### 6.2. Интерфейс провайдера

```python
class SourceProvider(Protocol):
    async def search(self, query: str) -> list[DiscoveredSourceCandidate]: ...
```

- `TelethonGlobalSearchProvider` — вызывает `functions.messages.SearchGlobalRequest` через Telethon-клиент, из `response.chats` берёт публичные группы/каналы (`megagroup` или `broadcast`, не приватные), мапит в `DiscoveredSourceCandidate`.
- `SearxngProvider` — ходит в SearXNG (`SEARXNG_BASE_URL`) с запросом вида `site:t.me {query}`, парсит результаты, извлекает `t.me/<username>` из URL, мапит в `DiscoveredSourceCandidate` (`tg_chat_id=None`, заполняется позже при обогащении).

### 6.3. Оркестрация (`discovery/pipeline.py`)

1. `query_generator.generate(portfolio_summary, limit=DISCOVERY_QUERIES_PER_RUN)` → список запросов, каждый сохраняется в `search_queries` (пропускать уже существующий `query_text`).
2. Для каждого запроса — параллельный вызов обоих провайдеров (`asyncio.gather`), сбор всех `DiscoveredSourceCandidate`.
3. Дедупликация в памяти по `dedupe_key()`.
4. Отсев кандидатов, чей ключ уже есть в `discovered_chats` или `monitored_chats` (репозиторий отдаёт множество существующих ключей одним запросом, не по одному).
5. Для новых кандидатов — обогащение через Telethon: `resolve` чата (получить `tg_chat_id`, `access_hash`, актуальный `title`), затем `history.py` грузит последние `DISCOVERY_MESSAGES_PER_CHAT` сообщений без вступления в чат.
6. Собранный текстовый контекст + `portfolio_summary` передаётся в `llm/relevance.py` → `RelevanceVerdict`.
7. Кандидат сохраняется в `discovered_chats` всегда (даже при отказе) со статусом `approved`/`rejected` и `relevance_reason` — это и есть защита от повторной обработки того же чата на следующих прогонах (идемпотентность конвейера). Владельцу через `/discovered` показываются только записи со статусом `approved` — этим выполняется требование «сохранять только подходящие чаты» на уровне пользовательского опыта.

---

## 7. LLM-контракты (DeepSeek)

```python
class RelevanceVerdict(BaseModel):
    is_relevant: bool
    reason: str  # <= 200 символов, по-русски, для показа владельцу
    confidence: float  # 0..1


class GeneratedQueries(BaseModel):
    queries: list[str]  # 3..10 элементов, без дублей
```

Единый контракт `RelevanceVerdict` используется в двух местах с разными промптами, но одной моделью ответа:
- оценка сообщения в мониторимом чате (`services/lead_service.py`);
- оценка нового чата в discovery (`discovery/pipeline.py`).

`llm/deepseek_client.py` — единственное место, где формируется запрос к DeepSeek API и парсится JSON-ответ (`response_format: json_object` либо явный промпт на JSON + `pydantic.model_validate_json` с обработкой ошибки парсинга и одним ретраем). Промпты живут в `llm/relevance.py` и `llm/queries.py`, не размазаны по вызывающему коду.

---

## 8. Мониторинг загруженных чатов — контракт

- Бот должен быть участником чата с отключённым privacy mode, чтобы `aiogram` получал все сообщения группы, а не только адресованные боту напрямую — операционное требование, ботов Telegram нельзя добавить в чужой чат самостоятельно, это делает владелец руками.
- `handlers/monitoring.py` — хендлер на текстовые сообщения в чатах, присутствующих в `monitored_chats` с `is_active=True`.
- `services/lead_service.py.process_message(message)`:
  1. вызывает LLM-оценку (`RelevanceVerdict`) с текстом сообщения и `portfolio_summary`;
  2. если `is_relevant=False` — ничего не сохраняет;
  3. если `is_relevant=True` — сохраняет `Lead` (уникальность по `monitored_chat_id + tg_message_id` защищает от дублей при ретраях), отправляет владельцу (`OWNER_TG_ID`) уведомление с текстом сообщения, автором и причиной релевантности, с inline-кнопкой «Написать»;
  4. кнопка: `https://t.me/{username}` если у автора есть username, иначе `tg://user?id={tg_user_id}` (работает не во всех клиентах без общей истории с ботом, но у автора и владельца уже есть общий чат — обычно открывается корректно; это фиксируется как известное ограничение, не баг);
  5. после успешной отправки уведомления проставляет `notified_at`.

### 8.1. Дефолтный источник чатов — `sources.json`

Чаты, которые владелец вносит сам (не найденные ботом через discovery), задаются файлом `sources.json` в корне репозитория, путь настраивается через `SOURCES_FILE_PATH`. Это основной способ первично загрузить список мониторимых чатов — то, что в исходном требовании названо «чаты, которые я загружу».

Формат — JSON-массив объектов:

```json
[
  {
    "handle": "@freelansim_ru",
    "title": "Хабр Фриланс",
    "enabled": true
  }
]
```

- `handle` — обязательное, telegram username чата с `@` в начале, уникален в пределах файла.
- `title` — необязательное, человекочитаемая пометка для самого владельца, на логику не влияет, в БД не обязателен к использованию как источник истины (актуальный `title` бот всё равно берёт из Telegram при резолве).
- `enabled` — обязательное, `bool`. `false` — запись в файле остаётся (документирует намерение), но чат не мониторится.

Загрузка и синк — `services/chat_service.sync_from_sources_file(path)`, вызывается один раз на старте `bot/main.py` (без периодического опроса файла в рантайме — правки файла требуют перезапуска бота, это осознанное упрощение). Логика синка идемпотентна:

1. Прочитать и провалидировать `sources.json` (Pydantic-модель `SourcesFileEntry`); невалидный файл или дубликат `handle` — сессия останавливается на старте с понятной ошибкой, бот не поднимается с повреждённым источником.
2. Для каждой записи с `enabled=true`: резолвить `handle` через Telethon (получить `tg_chat_id`, актуальный `title`), upsert в `monitored_chats` с `origin=sources_file`, `is_active=true`.
3. Для каждой записи с `enabled=false`: если строка с таким `tg_chat_id`/`username` уже есть в `monitored_chats` — проставить `is_active=false`, не удалять (история `Lead` за этим чатом сохраняется). Если строки нет — ничего не делать (резолвить выключенный чат через Telegram не нужно).
4. Чат, добавленный через `/add_chat` (`origin=command`), синком `sources.json` не трогается и не удаляется, даже если отсутствует в файле — `sources.json` не единственный способ добавить чат, а дефолтный/декларативный, команда остаётся для точечных добавлений без правки файла и перезапуска.

`sources.json` — часть репозитория, коммитится (в нём нет секретов, только публичные handle'ы), в `.gitignore` не входит.

---

## 9. Портфолио — контракт

`portfolio/github_client.py` — обёртка над GitHub REST API (`GET /users/{GITHUB_USERNAME}/repos`), только чтение, авторизация `GITHUB_TOKEN`.

`portfolio/service.py`:
- `sync()` — тянет репозитории, апсертит в `portfolio_items` по `repo_name`;
- `build_summary() -> str` — собирает компактную текстовую сводку (языки, топики, описания) из `portfolio_items`, используется как контекст LLM и в генерации поисковых запросов. Кэшируется в памяти процесса, инвалидируется после `sync()`.

Периодичность синка — задача в `scheduler.py`, интервал не фиксирован жёстко в контракте (настраивается в скелете), не реже раза в сутки.

---

## 10. Владение инфраструктурой

- **Миграции** — только через Alembic autogenerate от `db/models.py`, применяются на старте контейнера (`alembic upgrade head` в entrypoint/CI перед запуском бота).
- **Docker/docker-compose** — сервисы `bot` и `searxng`, volume под `data/` (sqlite-файл + telethon session), `.env` не коммитится, читается через `env_file`. Запуск на VPS — `docker compose up -d`, один шаг.
- **Конфиг** — единый модуль `app/config.py`, `.env.example` обновляется в том же коммите, что добавляет новую переменную.
- Секреты нигде не логируются: `logging.py` настраивает `loguru` без вывода значений токенов/ключей (логировать факт наличия, не значение).

---

## 11. Дисциплина CONTRACT GAP

Если для текущей задачи не хватает контракта (поля в модели, DTO, интерфейса, формата ответа LLM) — сессия останавливается и выдаёт:

```
CONTRACT GAP
Что нужно: ...
Зачем: ...
Предлагаемая форма: ...
```

Код с придуманным контрактом не пишется. Дальше — либо продолжить задачу на локальной заглушке (если возможно без риска разъехаться со схемой), либо остановиться на задаче полностью. Обновление `tech.md` (append, бамп версии, строка в changelog) — следующим шагом в отдельном коммите `docs(tech): ...`, до продолжения работы над контрактом.

---

## 12. Тесты

Тесты выводятся из критериев приёмки задачи, не из реализации — тест кодирует контракт, а не зеркалит написанный код. Обязательные типы на слайс, где применимо:

- **Контрактные на стыках.** Фейковый DeepSeek-клиент и фейковый Telethon-клиент валидируют вход/выход против Pydantic-моделей из раздела 7 — падают, если код шлёт или ожидает не ту форму.
- **Идемпотентность.** Discovery-конвейер, прогнанный дважды с одним и тем же кандидатом, не создаёт вторую строку в `discovered_chats` (unique-констрейнт + upsert-логика репозитория проверяется тестом, а не только полагается на БД). Аналогично `lead_service` — повторная обработка того же `tg_message_id` не создаёт вторую запись `Lead`.
- **Путь ошибки.** Фейки умеют возвращать ошибку/`FloodWaitError`/невалидный JSON от LLM — проверяется, что код ретраит по контракту или деградирует без падения процесса.
- **Property-based (`fast-check`-аналог для Python — `hypothesis`).** Функция нормализации `dedupe_key()` и парсер `t.me/<username>` из произвольных URL — сюда, инварианты: ключ детерминирован, регистронезависим, не падает на мусорном вводе.

Ни один тест не ходит в реальный Telegram/DeepSeek/GitHub/SearXNG — только фейки/стабы за интерфейсами из раздела 3.

### 12.1. Обязательный набор тестов на фейковых сообщениях (модуль релевантности)

Помимо контрактных тестов из раздела 12, модуль оценки релевантности обязан иметь отдельный тестовый набор на подготовленных синтетических (фейковых) сообщениях — это не опциональное дополнение, а обязательная часть Definition of Done для слайсов 1 (мониторинг), 3 (DeepSeek relevance) и 6 (discovery-конвейер) из раздела 14.

Формат: `tests/unit/fixtures/relevance_messages.py` — таблица кейсов `(текст_сообщения_или_чата, ожидаемый is_relevant, комментарий-описание кейса в самом тесте, не в исходном коде)`. Минимальный состав фикстур:

- **Явно релевантные** — сообщения, прямо описывающие заказ на разработку, попадающий в портфолио (например: «ищу разработчика для Telegram-бота на Python», «нужен парсер данных, есть бюджет»).
- **Явно нерелевантные** — обычный чат-шум, не связанный с заказами («кто идёт на созвон в 15:00», мемы, оффтоп).
- **Пограничные** — упоминание разработки не как заказа («у меня есть скрипт на Python»), запрос на технологию вне портфолио, заказ без явного технического стека.
- **Мусорные/пустые** — пустой текст, только эмодзи, только вложение без подписи, слишком длинный текст (граница обрезки контекста).

Тест прогоняет каждый кейс через `services/lead_service.process_message` (и аналогично через `discovery/pipeline` для чат-уровня) с фейковым DeepSeek-клиентом, настроенным отвечать по таблице кейсов, и проверяет итоговую ветку: `Lead`/`DiscoveredChat` создан и владелец уведомлён — только на явно и пограничных релевантных кейсах, размеченных как `is_relevant=True`; на нерелевантных и мусорных — ничего не создаётся и уведомление не уходит. Тест обязателен к прохождению перед мёржем задач, где меняется `llm/relevance.py`, `services/lead_service.py` или `discovery/pipeline.py`.

---

## 13. Правила и конвенции кода

- ООП: внешние системы (Telegram Bot API, Telethon, DeepSeek, GitHub, SearXNG) — только за интерфейсами (`Protocol`/ABC), реализация подменяется в тестах.
- DRY: один `RelevanceVerdict`, один `deepseek_client`, один паттерн upsert в репозиториях — не дублировать по модулям.
- Repository pattern: доступ к БД только через `repositories/*`, ни один `service`/`handler` не строит SQLAlchemy-запрос напрямую.
- Никаких «толстых» хендлеров aiogram — вся логика в `services`, хендлер только парсит апдейт и вызывает сервис.
- Все внешние вызовы (Telethon, DeepSeek, GitHub, SearXNG) — с таймаутом и обработкой ошибки, без голых `except Exception: pass`.
- Типы обязательны везде, `pyright` в strict-режиме без подавлений `# type: ignore`.
- **Код без комментариев.** Никаких `#`-комментариев и docstring-простыней в коде проекта: ни поясняющих, ни закомментированного кода, ни TODO. Если код требует пояснения «почему» — это сигнал вынести шаг в отдельную функцию с говорящим именем, а не приписать комментарий. Единственное исключение — обязательные по формату строки (например, `# type: ignore[код]`, если без него `pyright` не проходит, и то только когда правка типа невозможна) и служебные файлы конфигурации, где комментарий — часть формата (`.env.example`, `docker-compose.yml`, `alembic.ini`). Имена переменных, функций и модулей должны сами объяснять код.

### Коммиты, PR

- Язык коммитов и PR — английский.
- Формат коммита фиксированный, Conventional Commits: `type(scope): summary`, `type` из `feat|fix|test|refactor|chore|docs`, summary в императиве, со строчной, без точки, до ~50 символов. Тело коммита — только если нужно объяснить *почему*.
- Коммитить по ходу работы маленькими логическими шагами, не одним коммитом в конце. Каждый коммит по возможности проходит тайпчек.
- Активный залог, императив, без em-dash, без филлеров — та же дисциплина, что в этом файле.

### Definition of Done одной задачи

- `ruff check` чист.
- `pyright` чист.
- `pytest` зелёный, включая новые тесты слайса (раздел 12).
- Миграция Alembic приложена, если менялась `db/models.py`.
- `.env.example` обновлён, если добавлена новая переменная.
- Секреты не закоммичены.

---

## 14. Дорожная карта по стадиям

### Стадия 1 — Скелет

Собрать и смёрджить до начала фич:

- Каркас проекта: `pyproject.toml`, `uv`, `ruff`/`pyright`-конфиги.
- `app/config.py` + `.env.example` целиком (раздел 4).
- `db/base.py`, `db/models.py` (все таблицы раздела 5), первая Alembic-миграция, применяется на эфемерной SQLite в CI/локально.
- `logging.py` — loguru настроен, секреты не логируются.
- aiogram-скелет: `bot/main.py`, `middlewares/owner_only.py`, команды `/start`, `/help`.
- Telethon-скелет: `telethon_client/client.py`, команда проверки соединения.
- Фейковые реализации `deepseek_client`, `github_client`, `searxng`-клиента за интерфейсами — возвращают детерминированные сид-данные.
- `docker/Dockerfile`, `docker/docker-compose.yml` (сервисы `bot` + `searxng`), volume под `data/`.
- `sources.json` (раздел 8.1) с 1-2 тестовыми записями, `services/chat_service.sync_from_sources_file` вызывается на старте `bot/main.py`.
- **Эталонная вертикаль**: синк `sources.json` — `bot/main.py` (старт) → `services/chat_service.py` → `repositories/monitored_chats.py` → `db`. Полный путь service → repository → db, с тестом (валидный файл, дубликат `handle`, `enabled=false` не резолвится). Все фичи стадии 2 копируют эту структуру.

Чек-лист «скелет готов» (проходится целиком, не на глаз, до старта фич):

- [ ] `ruff`/`pyright`/`pytest` зелёные на тривиальном коммите;
- [ ] бот отвечает на `/start`/`/help` только `OWNER_TG_ID`, на остальных — молчит;
- [ ] Telethon-клиент коннектится и проходит health-check;
- [ ] миграции применяются на чистой SQLite «с нуля»;
- [ ] фейки `deepseek`/`github`/`searxng` отдают сид-данные, реальные ключи не нужны для запуска;
- [ ] синк `sources.json` работает end-to-end (валидный файл → `monitored_chats`, невалидный/дубликат `handle` → остановка на старте с понятной ошибкой) и покрыт тестом;
- [ ] `docker compose up -d` поднимает бота и SearXNG одной командой на чистом окружении.

### Стадия 2 — Фичи слайсами

Каждая задача — один вертикальный слайс, один PR/коммит-серия, с тестами по разделу 12. Порядок учитывает зависимости:

1. **Мониторинг чатов** — реальный хендлер входящих сообщений, `lead_service.process_message`, сохранение `Lead`, уведомление с кнопкой «Написать» (раздел 8). LLM пока фейковый.
2. **Портфолио** — `github_client` реальный, `portfolio/service.py` (sync + summary), периодическая задача синка (раздел 9).
3. **DeepSeek relevance** — заменить фейк на реальный `deepseek_client` + `llm/relevance.py`, парсинг `RelevanceVerdict` с ретраем на невалидный JSON (раздел 7).
4. **Discovery: провайдер Telethon** — `telethon_client/search.py` (`SearchGlobalRequest`), `TelethonGlobalSearchProvider`, маппинг в `DiscoveredSourceCandidate` (раздел 6.2).
5. **Discovery: провайдер SearXNG** — `SearxngProvider`, запросы `site:t.me`, парсинг результатов (раздел 6.2).
6. **Discovery: конвейер** — `query_generator.py` (LLM-генерация запросов на портфолио), `pipeline.py` целиком: сбор от обоих провайдеров, дедуп, проверка БД, обогащение через Telethon, AI-фильтр, персист (раздел 6.3), периодический запуск в `scheduler.py`.
7. **Управление чатами** — `/add_chat` (точечное добавление чата без правки `sources.json`+перезапуска, `origin=command`), `/list_chats`, `/remove_chat`, `/discovered` (просмотр `approved`-кандидатов, кнопка «Добавить в мониторинг» → перенос в `monitored_chats`).
8. **Устойчивость** — обработка `FloodWaitError`/бэкофф на Telethon-вызовах, рейт-лимит на DeepSeek-запросы, `/status`, закрытие пробелов в тестовом покрытии.
