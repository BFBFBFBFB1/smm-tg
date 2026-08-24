"""referral earnings

Revision ID: 0002_referral
Revises: 0001_initial
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_referral"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("referrer_id", sa.Integer(), nullable=True))
    op.add_column(
        "users",
        sa.Column("referral_earned", sa.Numeric(12, 2), server_default="0"),
    )
    op.create_foreign_key(
        "fk_users_referrer_id",
        "users",
        "users",
        ["referrer_id"],
        ["id"],
    )
    op.create_index("ix_users_referrer_id", "users", ["referrer_id"])

    op.create_table(
        "referral_earnings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("referrer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("referred_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id")),
        sa.Column("source_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_referral_earnings_referrer_id", "referral_earnings", ["referrer_id"])
    op.create_index("ix_referral_earnings_referred_id", "referral_earnings", ["referred_id"])


def downgrade() -> None:
    op.drop_index("ix_referral_earnings_referred_id", table_name="referral_earnings")
    op.drop_index("ix_referral_earnings_referrer_id", table_name="referral_earnings")
    op.drop_table("referral_earnings")
    op.drop_index("ix_users_referrer_id", table_name="users")
    op.drop_constraint("fk_users_referrer_id", "users", type_="foreignkey")
    op.drop_column("users", "referral_earned")
    op.drop_column("users", "referrer_id")
