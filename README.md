# SMM Telegram Bot

Telegram-бот для продажи SMM-услуг: каталог, оплата, автоматический запуск заказов и уведомления о статусах.

## Стек

- Python 3.11+, aiogram 3
- PostgreSQL + SQLAlchemy 2 + asyncpg + Alembic (или SQLite в `LOCAL_MODE`)
- Redis (кэш каталога + FSM) / in-memory в local mode
- Celery или in-process workers
- ЮKassa / Telegram Stars / Crypto Bot
- Docker Compose

## Быстрый старт (local)

```bash
cp .env.example .env
# BOT_TOKEN, PANEL_API_KEY, ADMIN_IDS, CRYPTOBOT_TOKEN
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
```

`LOCAL_MODE=true` — SQLite без Docker/Postgres/Redis.

## Docker

```bash
docker compose up -d --build
```

## Админ-команды

Только `ADMIN_IDS`:

| Команда | Описание |
|---------|----------|
| `/admin` | Справка |
| `/sync` | Обновить каталог |
| `/panel_balance` | Баланс поставщика |
| `/stats` | Users / orders / profit |
