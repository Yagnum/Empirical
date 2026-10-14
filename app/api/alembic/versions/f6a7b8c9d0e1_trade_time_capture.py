"""Trade-time capture: the price context each weekend trade opened in.

Every column is nullable. Old rows stay null; new rows fill them best
effort (a failed capture stores null and never blocks the trade).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY = sa.Numeric(precision=28, scale=10)


def upgrade() -> None:
    op.add_column("weekend_trades", sa.Column("sigma_source", sa.String(length=16), nullable=True))
    op.add_column("weekend_trades", sa.Column("params_generated_at", sa.String(length=40), nullable=True))
    op.add_column("weekend_trades", sa.Column("open_bid", _MONEY, nullable=True))
    op.add_column("weekend_trades", sa.Column("open_ask", _MONEY, nullable=True))
    op.add_column("weekend_trades", sa.Column("open_mid", _MONEY, nullable=True))
    op.add_column("weekend_trades", sa.Column("share_ref_price", _MONEY, nullable=True))
    op.add_column("weekend_trades", sa.Column("share_ref_source", sa.String(length=24), nullable=True))
    op.add_column("weekend_trades", sa.Column("share_ref_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("weekend_trades", sa.Column("open_basis", sa.Numeric(precision=20, scale=10), nullable=True))


def downgrade() -> None:
    for column in (
        "open_basis",
        "share_ref_at",
        "share_ref_source",
        "share_ref_price",
        "open_mid",
        "open_ask",
        "open_bid",
        "params_generated_at",
        "sigma_source",
    ):
        op.drop_column("weekend_trades", column)
