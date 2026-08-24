from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DiscountType, Order, PromoCode, PromoRedemption, User
from app.services.users import credit_balance


class PromoError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def normalize_code(raw: str) -> str:
    return (raw or "").strip().upper().replace(" ", "")


def is_balance_promo(promo: PromoCode) -> bool:
    return promo.discount_type == DiscountType.BALANCE


def is_order_promo(promo: PromoCode) -> bool:
    return promo.discount_type in {DiscountType.PERCENT, DiscountType.FIXED}


def calc_discount(promo: PromoCode, amount: Decimal) -> Decimal:
    amount = Decimal(amount)
    if promo.discount_type == DiscountType.PERCENT:
        discount = (amount * Decimal(promo.discount_value) / Decimal("100")).quantize(
            Decimal("0.01")
        )
    elif promo.discount_type == DiscountType.FIXED:
        discount = Decimal(promo.discount_value).quantize(Decimal("0.01"))
    else:
        return Decimal("0.00")
    if discount > amount:
        discount = amount
    # Keep at least $0.01 payable if original > 0
    if amount > 0 and amount - discount < Decimal("0.01"):
        discount = amount - Decimal("0.01")
    if discount < 0:
        discount = Decimal("0.00")
    return discount


async def get_promo_by_code(session: AsyncSession, code: str) -> PromoCode | None:
    result = await session.execute(
        select(PromoCode).where(PromoCode.code == normalize_code(code))
    )
    return result.scalar_one_or_none()


async def list_promos(session: AsyncSession, *, active_only: bool = False) -> list[PromoCode]:
    stmt = select(PromoCode).order_by(PromoCode.created_at.desc())
    if active_only:
        stmt = stmt.where(PromoCode.is_active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_promo(
    session: AsyncSession,
    *,
    code: str,
    discount_type: str,
    discount_value: Decimal,
    max_uses: int | None = None,
    max_per_user: int = 1,
    min_amount: Decimal = Decimal("0.00"),
    expires_at: datetime | None = None,
) -> PromoCode:
    normalized = normalize_code(code)
    if not normalized or len(normalized) > 64:
        raise PromoError("Некорректный код")
    allowed = {DiscountType.PERCENT, DiscountType.FIXED, DiscountType.BALANCE}
    if discount_type not in allowed:
        raise PromoError("Тип: percent, fixed или balance")
    if discount_value <= 0:
        raise PromoError("Значение должно быть > 0")
    if discount_type == DiscountType.PERCENT and discount_value > 100:
        raise PromoError("Процент не больше 100")

    existing = await get_promo_by_code(session, normalized)
    if existing:
        raise PromoError("Такой промокод уже есть")

    promo = PromoCode(
        code=normalized,
        discount_type=discount_type,
        discount_value=discount_value,
        max_uses=max_uses,
        max_per_user=max_per_user,
        min_amount=min_amount if discount_type != DiscountType.BALANCE else Decimal("0.00"),
        expires_at=expires_at,
        is_active=True,
        used_count=0,
    )
    session.add(promo)
    await session.flush()
    return promo


async def _check_promo_limits(
    session: AsyncSession,
    promo: PromoCode,
    user: User,
) -> None:
    if not promo.is_active:
        raise PromoError("Промокод неактивен")
    if promo.expires_at and promo.expires_at < datetime.now(timezone.utc):
        raise PromoError("Срок действия промокода истёк")
    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        raise PromoError("Лимит использований исчерпан")

    used_by_user = await session.scalar(
        select(func.count())
        .select_from(PromoRedemption)
        .where(PromoRedemption.promo_id == promo.id, PromoRedemption.user_id == user.id)
    )
    if int(used_by_user or 0) >= int(promo.max_per_user):
        raise PromoError("Вы уже использовали этот промокод")


async def validate_promo_for_user(
    session: AsyncSession,
    promo: PromoCode,
    user: User,
    amount: Decimal,
) -> Decimal:
    if is_balance_promo(promo):
        raise PromoError("Этот промокод начисляет баланс — введите его в меню «Промокод»")

    await _check_promo_limits(session, promo, user)

    if Decimal(amount) < Decimal(promo.min_amount):
        raise PromoError(f"Минимальная сумма заказа ${promo.min_amount}")

    discount = calc_discount(promo, Decimal(amount))
    if discount <= 0:
        raise PromoError("Скидка не применяется к этой сумме")
    return discount


async def redeem_balance_promo(
    session: AsyncSession,
    user: User,
    code: str,
) -> tuple[PromoCode, Decimal]:
    """Immediately credit user balance. One-shot per limits."""
    promo = await get_promo_by_code(session, code)
    if not promo:
        raise PromoError("Промокод не найден")
    if not is_balance_promo(promo):
        raise PromoError("not_balance")  # caller handles order-type save

    await _check_promo_limits(session, promo, user)

    amount = Decimal(promo.discount_value).quantize(Decimal("0.01"))
    if amount <= 0:
        raise PromoError("Некорректная сумма промокода")

    await credit_balance(session, user, amount)
    session.add(
        PromoRedemption(
            promo_id=promo.id,
            user_id=user.id,
            order_id=None,
            discount_amount=amount,
        )
    )
    promo.used_count = int(promo.used_count or 0) + 1
    await session.flush()
    return promo, amount


async def apply_promo_to_order(
    session: AsyncSession,
    order: Order,
    user: User,
    code: str,
) -> tuple[Order, Decimal]:
    promo = await get_promo_by_code(session, code)
    if not promo:
        raise PromoError("Промокод не найден")
    if is_balance_promo(promo):
        raise PromoError("Этот промокод начисляет баланс — введите его в меню «Промокод»")

    base = Decimal(order.original_price or order.sale_price) + Decimal(
        order.discount_amount or 0
    )
    # If already discounted, restore base from original
    if order.original_price is not None:
        base = Decimal(order.original_price)

    discount = await validate_promo_for_user(session, promo, user, base)
    order.original_price = base
    order.discount_amount = discount
    order.sale_price = (base - discount).quantize(Decimal("0.01"))
    order.promo_code_id = promo.id
    await session.flush()
    return order, discount


async def finalize_promo_redemption(
    session: AsyncSession,
    order: Order,
    user: User,
) -> None:
    """Call after successful payment. Idempotent per order."""
    if not order.promo_code_id or Decimal(order.discount_amount or 0) <= 0:
        return

    existing = await session.scalar(
        select(PromoRedemption.id).where(PromoRedemption.order_id == order.id)
    )
    if existing:
        return

    promo = await session.get(PromoCode, order.promo_code_id)
    if not promo:
        return

    session.add(
        PromoRedemption(
            promo_id=promo.id,
            user_id=user.id,
            order_id=order.id,
            discount_amount=Decimal(order.discount_amount),
        )
    )
    promo.used_count = int(promo.used_count or 0) + 1
    await session.flush()


def format_promo(promo: PromoCode) -> str:
    if promo.discount_type == DiscountType.PERCENT:
        disc = f"{promo.discount_value}% скидка"
    elif promo.discount_type == DiscountType.BALANCE:
        disc = f"+${promo.discount_value} на баланс"
    else:
        disc = f"${promo.discount_value} скидка"
    uses = f"{promo.used_count}"
    if promo.max_uses is not None:
        uses = f"{promo.used_count}/{promo.max_uses}"
    status = "✅" if promo.is_active else "❌"
    return f"{status} <code>{promo.code}</code> — {disc} · использовано {uses}"
