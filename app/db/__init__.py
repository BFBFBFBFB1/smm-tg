from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

_engine_kwargs: dict = {
    # echo floods Windows consoles with UnicodeEncodeError on emoji service names
    "echo": False,
}
if settings.local_mode:
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    _engine_kwargs["connect_args"] = {"timeout": 30}
else:
    _engine_kwargs.update(
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Create tables + lightweight SQLite column upgrades for local_mode."""
    from sqlalchemy import text

    from app.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.local_mode:
            cols = (
                await conn.execute(text("PRAGMA table_info(users)"))
            ).fetchall()
            names = {row[1] for row in cols}
            if "referrer_id" not in names:
                await conn.execute(text("ALTER TABLE users ADD COLUMN referrer_id INTEGER"))
            if "referral_earned" not in names:
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN referral_earned NUMERIC(12,2) DEFAULT 0")
                )
            if "broadcast_opt_out" not in names:
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN broadcast_opt_out BOOLEAN DEFAULT 0")
                )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
