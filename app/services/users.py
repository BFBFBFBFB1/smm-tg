from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def get_or_create_user(
    session: AsyncSession,
    tg_id: int,
    username: str | None = None,
    first_name: str | None = None,
    language: str = "ru",
) -> User:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one_or_none()
    if user:
        changed = False
        if username and user.username != username:
            user.username = username
            changed = True
        if first_name and user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if changed:
            await session.flush()
        return user

    user = User(
        tg_id=tg_id,
        username=username,
        first_name=first_name,
        language=language,
        balance=Decimal("0.00"),
    )
    session.add(user)
    await session.flush()
    return user


async def get_user_by_tg_id(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def credit_balance(session: AsyncSession, user: User, amount: Decimal) -> User:
    user.balance = Decimal(user.balance) + amount
    await session.flush()
    return user


async def debit_balance(session: AsyncSession, user: User, amount: Decimal) -> bool:
    if Decimal(user.balance) < amount:
        return False
    user.balance = Decimal(user.balance) - amount
    await session.flush()
    return True
