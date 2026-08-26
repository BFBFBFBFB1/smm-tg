"""user broadcast opt-out and pending promo

Revision ID: 0004_user_flags
Revises: 0003_promos
Create Date: 2026-08-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_user_flags"
down_revision: Union[str, None] = "0003_promos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("broadcast_opt_out", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("users", sa.Column("pending_promo_code", sa.String(64), nullable=True))
    op.add_column(
        "services",
        sa.Column("refill", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "services",
        sa.Column("cancel_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "services",
        sa.Column("dripfeed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "services",
        sa.Column("speed_rank", sa.Integer(), server_default="9", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("services", "speed_rank")
    op.drop_column("services", "dripfeed")
    op.drop_column("services", "cancel_allowed")
    op.drop_column("services", "refill")
    op.drop_column("users", "pending_promo_code")
    op.drop_column("users", "broadcast_opt_out")
