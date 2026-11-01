"""v2, the locked price (ADR-033): the design a trade opened under.

Every existing row opened under the pass-through design and says so. Unlike
ADR-028's attempt, the trader's price is locked AND Yagnum hedges it with
the token; the ERR passes the hedge's leftover P/L back (paper §6b), so
every other column keeps its meaning.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "weekend_trades",
        sa.Column("design", sa.String(length=16), nullable=False, server_default="pass_through"),
    )


def downgrade() -> None:
    op.drop_column("weekend_trades", "design")
