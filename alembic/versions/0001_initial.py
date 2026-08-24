"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("icon", sa.String(16)),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(255)),
        sa.Column("first_name", sa.String(255)),
        sa.Column("balance", sa.Numeric(12, 2), server_default="0"),
        sa.Column("language", sa.String(5), server_default="ru"),
        sa.Column("is_banned", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("panel_service_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False, server_default="other"),
        sa.Column("panel_rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("resale_rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("min_order", sa.Integer(), nullable=False),
        sa.Column("max_order", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id"), nullable=False),
        sa.Column("panel_order_id", sa.Integer()),
        sa.Column("link", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("purchase_price", sa.Numeric(12, 4)),
        sa.Column("sale_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("profit", sa.Numeric(12, 4)),
        sa.Column("status", sa.String(50), server_default="awaiting_payment"),
        sa.Column("panel_status", sa.String(50)),
        sa.Column("start_count", sa.Integer()),
        sa.Column("remains", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_orders_panel_order_id", "orders", ["panel_order_id"])
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("payment_method", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("external_id", sa.String(255)),
        sa.Column("payload", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("external_id", name="uq_payments_external_id"),
    )


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_panel_order_id", table_name="orders")
    op.drop_table("orders")
    op.drop_table("services")
    op.drop_table("users")
    op.drop_table("categories")
