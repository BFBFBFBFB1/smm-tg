import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from app.bot.handlers import setup_routers
from app.bot.middlewares import DbSessionMiddleware, UserMiddleware
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db import async_session_factory, init_db
from app.db.redis import close_redis, get_redis, log_cache_backend
from app.panel.sync import sync_services_from_panel
from app.worker_local import crypto_payments_loop, poll_loop, sync_loop


async def on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    logger.info("Bot started as @{}", me.username)
    try:
        async with async_session_factory() as session:
            stats = await sync_services_from_panel(session)
            await session.commit()
            logger.info("Initial services sync: {}", stats)
    except Exception as exc:
        logger.exception("Initial sync failed: {}", exc)


async def on_shutdown(bot: Bot) -> None:
    logger.info("Shutting down bot...")
    await close_redis()
    await bot.session.close()


async def main() -> None:
    setup_logging()
    settings = get_settings()
    log_cache_backend()

    if settings.local_mode:
        await init_db()
        logger.info("Local mode: SQLite + MemoryStorage + in-process workers")
        storage = MemoryStorage()
    else:
        from aiogram.fsm.storage.redis import RedisStorage

        storage = RedisStorage.from_url(settings.redis_url)
        get_redis()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    dp.pre_checkout_query.middleware(DbSessionMiddleware())
    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(UserMiddleware())

    dp.include_router(setup_routers())
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    stop = asyncio.Event()
    bg_tasks: list[asyncio.Task] = [
        # Always poll Crypto Bot invoices (webhook may be unreachable in local/dev)
        asyncio.create_task(crypto_payments_loop(bot, stop), name="crypto_payments_loop"),
    ]
    if settings.local_mode:
        bg_tasks.extend(
            [
                asyncio.create_task(sync_loop(stop), name="sync_loop"),
                asyncio.create_task(poll_loop(bot, stop), name="poll_loop"),
            ]
        )
    else:
        bg_tasks.append(asyncio.create_task(poll_loop(bot, stop), name="poll_loop"))

    logger.info("Starting polling...")
    try:
        await dp.start_polling(bot)
    finally:
        stop.set()
        for task in bg_tasks:
            task.cancel()
        if bg_tasks:
            await asyncio.gather(*bg_tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
