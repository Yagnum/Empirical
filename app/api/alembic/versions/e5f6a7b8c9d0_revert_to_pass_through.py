"""Revert ADR-028 (ADR-029): the paper is pass-through; drop the columns the
locked-price design added. No row ever settled under it.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("weekend_trades", "yagnum_pnl")
    op.drop_column("weekend_trades", "design")


def downgrade() -> None:
    op.add_column("weekend_trades", sa.Column("design", sa.String(length=1), nullable=False, server_default="A"))
    op.add_column("weekend_trades", sa.Column("yagnum_pnl", sa.Numeric(precision=28, scale=10), nullable=True))
