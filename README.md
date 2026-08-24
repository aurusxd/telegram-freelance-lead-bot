# telegram-freelance-lead-bot

Телеграм-бот для поиска фриланс-заказов внутри Telegram. Ядро проекта — `tech.md`, любые изменения контрактов идут туда.

## Локальный запуск

```
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run python -m app.bot.main
```

## Запуск на VPS

```
cp .env.example .env
docker compose -f docker/docker-compose.yml up -d
```

## Проверки

```
uv run ruff check .
uv run pyright
uv run pytest
```

## Мониторимые чаты

Дефолтный список — `sources.json` в корне (раздел 8.1 `tech.md`), синкается на старте бота.
