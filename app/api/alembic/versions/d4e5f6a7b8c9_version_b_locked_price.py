"""Version B (ADR-028): the design a trade settled under, and Yagnum's gap P/L.

Every row that exists settled under design A (pass-through), and says so;
new rows default to B.

Revision ID: d4e5f6a7b8c9
Revises: c3d9e0f1a2b4
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d9e0f1a2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "weekend_trades",
        sa.Column("design", sa.String(length=1), nullable=False, server_default="B"),
    )
    op.add_column("weekend_trades", sa.Column("yagnum_pnl", sa.Numeric(precision=28, scale=10), nullable=True))
    op.execute("update weekend_trades set design = 'A'")


def downgrade() -> None:
    op.drop_column("weekend_trades", "yagnum_pnl")
    op.drop_column("weekend_trades", "design")
