from decimal import Decimal

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Order, Payment, PaymentStatus, ReferralEarning, User
from app.services.users import credit_balance, get_user_by_tg_id


def referral_link(bot_username: str, tg_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref{tg_id}"


def parse_referrer_tg_id(start_arg: str | None) -> int | None:
    if not start_arg:
        return None
    raw = start_arg.strip()
    if raw.startswith("ref"):
        raw = raw[3:]
    if raw.startswith("_"):
        raw = raw[1:]
    if not raw.isdigit():
        return None
    return int(raw)


async def attach_referrer(
    session: AsyncSession,
    user: User,
    referrer_tg_id: int | None,
) -> bool:
    """Bind referrer once. Returns True if attached."""
    if not referrer_tg_id or user.referrer_id is not None:
        return False
    if referrer_tg_id == user.tg_id:
        return False

    referrer = await get_user_by_tg_id(session, referrer_tg_id)
    if not referrer or referrer.is_banned:
        return False

    # Don't allow attaching after the user already spent money
    paid = await session.scalar(
        select(func.count())
        .select_from(Payment)
        .where(Payment.user_id == user.id, Payment.status == PaymentStatus.PAID)
    )
    if paid and paid > 0:
        return False

    user.referrer_id = referrer.id
    await session.flush()
    logger.info("User {} attached to referrer {}", user.tg_id, referrer.tg_id)
    return True


async def award_referral_for_order(
    session: AsyncSession,
    *,
    buyer: User,
    order: Order,
    payment_id: int | None = None,
) -> ReferralEarning | None:
    """Credit referrer with % of order sale price."""
    if not buyer.referrer_id:
        return None

    settings = get_settings()
    percent = Decimal(str(settings.referral_percent))
    if percent <= 0:
        return None

    source = Decimal(order.sale_price)
    if source <= 0:
        return None

    # Idempotency: one reward per order
    existing = await session.scalar(
        select(ReferralEarning.id).where(ReferralEarning.order_id == order.id)
    )
    if existing:
        return None

    amount = (source * percent / Decimal("100")).quantize(Decimal("0.01"))
    if amount < Decimal("0.01"):
        return None

    referrer = await session.get(User, buyer.referrer_id)
    if not referrer or referrer.is_banned:
        return None

    await credit_balance(session, referrer, amount)
    referrer.referral_earned = Decimal(referrer.referral_earned or 0) + amount

    earning = ReferralEarning(
        referrer_id=referrer.id,
        referred_id=buyer.id,
        order_id=order.id,
        payment_id=payment_id,
        source_amount=source,
        percent=percent,
        amount=amount,
    )
    session.add(earning)
    await session.flush()
    logger.info(
        "Referral reward ${} -> user {} from order {}",
        amount,
        referrer.tg_id,
        order.id,
    )
    return earning


async def get_referral_stats(session: AsyncSession, user: User) -> dict:
    invited = await session.scalar(
        select(func.count()).select_from(User).where(User.referrer_id == user.id)
    )
    rewards_count = await session.scalar(
        select(func.count())
        .select_from(ReferralEarning)
        .where(ReferralEarning.referrer_id == user.id)
    )
    return {
        "invited": int(invited or 0),
        "rewards_count": int(rewards_count or 0),
        "earned": Decimal(user.referral_earned or 0),
        "percent": Decimal(str(get_settings().referral_percent)),
    }


async def notify_referrer(
    bot,
    session: AsyncSession,
    earning: ReferralEarning,
) -> None:
    referrer = await session.get(User, earning.referrer_id)
    if not referrer:
        return
    try:
        await bot.send_message(
            referrer.tg_id,
            f"👥 Реферальный бонус: <b>+${earning.amount:.2f}</b>\n"
            f"({earning.percent:g}% с заказа друга)\n"
            f"Баланс: <b>${Decimal(referrer.balance):.2f}</b>",
        )
    except Exception as exc:
        logger.warning("Referral notify failed: {}", exc)
