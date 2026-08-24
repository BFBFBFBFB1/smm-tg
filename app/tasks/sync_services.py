import asyncio

from loguru import logger

from app.db import async_session_factory
from app.panel.sync import sync_services_from_panel
from app.tasks import celery_app


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _sync() -> dict:
    async with async_session_factory() as session:
        try:
            stats = await sync_services_from_panel(session)
            await session.commit()
            return stats
        except Exception:
            await session.rollback()
            raise


@celery_app.task(name="app.tasks.sync_services.sync_services_task", bind=True, max_retries=3)
def sync_services_task(self) -> dict:
    try:
        stats = _run(_sync())
        logger.info("Celery sync services: {}", stats)
        return stats
    except Exception as exc:
        logger.exception("Sync services failed: {}", exc)
        raise self.retry(exc=exc, countdown=60)
