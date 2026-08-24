from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class OrderStatus(StrEnum):
    AWAITING_PAYMENT = "awaiting_payment"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELED = "canceled"
    REFUNDED = "refunded"
    FAILED = "failed"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    WAITING = "waiting"
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"
    EXPIRED = "expired"


class PaymentMethod(StrEnum):
    BALANCE = "balance"
    YOOKASSA = "yookassa"
    STARS = "stars"
    CRYPTO = "crypto"


class DiscountType(StrEnum):
    PERCENT = "percent"
    FIXED = "fixed"
    BALANCE = "balance"  # credits user balance on redeem


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    icon: Mapped[str | None] = mapped_column(String(16))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    services: Mapped[list["Service"]] = relationship(back_populates="category")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    panel_service_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    panel_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    resale_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    min_order: Mapped[int] = mapped_column(Integer, nullable=False)
    max_order: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    refill: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    dripfeed: Mapped[bool] = mapped_column(Boolean, default=False)
    speed_rank: Mapped[int] = mapped_column(Integer, default=9)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    category: Mapped[Category | None] = relationship(back_populates="services")
    orders: Mapped[list["Order"]] = relationship(back_populates="service")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    language: Mapped[str] = mapped_column(String(5), default="ru")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    referrer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    referral_earned: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
    )
    broadcast_opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_promo_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    payments: Mapped[list["Payment"]] = relationship(back_populates="user")
    referrer: Mapped["User | None"] = relationship(
        remote_side="User.id",
        foreign_keys=[referrer_id],
    )
    referral_earnings: Mapped[list["ReferralEarning"]] = relationship(
        back_populates="referrer",
        foreign_keys="ReferralEarning.referrer_id",
    )


class ReferralEarning(Base):
    __tablename__ = "referral_earnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    referred_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"))
    source_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    referrer: Mapped[User] = relationship(
        back_populates="referral_earnings",
        foreign_keys=[referrer_id],
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), nullable=False)
    panel_order_id: Mapped[int | None] = mapped_column(Integer, index=True)
    link: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    sale_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        default=Decimal("0.00"),
    )
    promo_code_id: Mapped[int | None] = mapped_column(ForeignKey("promo_codes.id"))
    profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    status: Mapped[str] = mapped_column(
        String(50),
        default=OrderStatus.AWAITING_PAYMENT,
        index=True,
    )
    panel_status: Mapped[str | None] = mapped_column(String(50))
    start_count: Mapped[int | None] = mapped_column(Integer)
    remains: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="orders")
    service: Mapped[Service] = relationship(back_populates="orders")
    payment: Mapped["Payment | None"] = relationship(back_populates="order")
    promo_code: Mapped["PromoCode | None"] = relationship(back_populates="orders")


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    max_per_user: Mapped[int] = mapped_column(Integer, default=1)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    orders: Mapped[list["Order"]] = relationship(back_populates="promo_code")
    redemptions: Mapped[list["PromoRedemption"]] = relationship(back_populates="promo")


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        UniqueConstraint("promo_id", "order_id", name="uq_promo_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    promo: Mapped[PromoCode] = relationship(back_populates="redemptions")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("external_id", name="uq_payments_external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=PaymentStatus.PENDING)
    external_id: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="payments")
    order: Mapped[Order | None] = relationship(back_populates="payment")
