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
            if "pending_promo_code" not in names:
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN pending_promo_code VARCHAR(64)")
                )

            order_cols = (
                await conn.execute(text("PRAGMA table_info(orders)"))
            ).fetchall()
            order_names = {row[1] for row in order_cols}
            if "original_price" not in order_names:
                await conn.execute(
                    text("ALTER TABLE orders ADD COLUMN original_price NUMERIC(12,4)")
                )
            if "discount_amount" not in order_names:
                await conn.execute(
                    text(
                        "ALTER TABLE orders ADD COLUMN discount_amount "
                        "NUMERIC(12,4) DEFAULT 0"
                    )
                )
            if "promo_code_id" not in order_names:
                await conn.execute(
                    text("ALTER TABLE orders ADD COLUMN promo_code_id INTEGER")
                )

            svc_cols = (
                await conn.execute(text("PRAGMA table_info(services)"))
            ).fetchall()
            svc_names = {row[1] for row in svc_cols}
            if "refill" not in svc_names:
                await conn.execute(
                    text("ALTER TABLE services ADD COLUMN refill BOOLEAN DEFAULT 0")
                )
            if "cancel_allowed" not in svc_names:
                await conn.execute(
                    text(
                        "ALTER TABLE services ADD COLUMN cancel_allowed BOOLEAN DEFAULT 0"
                    )
                )
            if "dripfeed" not in svc_names:
                await conn.execute(
                    text("ALTER TABLE services ADD COLUMN dripfeed BOOLEAN DEFAULT 0")
                )
            if "speed_rank" not in svc_names:
                await conn.execute(
                    text("ALTER TABLE services ADD COLUMN speed_rank INTEGER DEFAULT 9")
                )

            # Ensure promo_redemptions.order_id can be NULL (balance promos)
            red_info = (
                await conn.execute(text("PRAGMA table_info(promo_redemptions)"))
            ).fetchall()
            if red_info:
                order_col = next((r for r in red_info if r[1] == "order_id"), None)
                if order_col is not None and order_col[3] == 1:  # notnull
                    await conn.execute(text("ALTER TABLE promo_redemptions RENAME TO promo_redemptions_old"))
                    await conn.execute(
                        text(
                            """
                            CREATE TABLE promo_redemptions (
                                id INTEGER PRIMARY KEY,
                                promo_id INTEGER NOT NULL REFERENCES promo_codes(id),
                                user_id INTEGER NOT NULL REFERENCES users(id),
                                order_id INTEGER REFERENCES orders(id),
                                discount_amount NUMERIC(12,2) NOT NULL,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                UNIQUE (promo_id, order_id)
                            )
                            """
                        )
                    )
                    await conn.execute(
                        text(
                            """
                            INSERT INTO promo_redemptions
                            (id, promo_id, user_id, order_id, discount_amount, created_at)
                            SELECT id, promo_id, user_id, order_id, discount_amount, created_at
                            FROM promo_redemptions_old
                            """
                        )
                    )
                    await conn.execute(text("DROP TABLE promo_redemptions_old"))
                    await conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_promo_redemptions_promo_id "
                            "ON promo_redemptions (promo_id)"
                        )
                    )
                    await conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_promo_redemptions_user_id "
                            "ON promo_redemptions (user_id)"
                        )
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
