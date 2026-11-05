"""A weekend trade whose opening cash could not move is `failed` (ADR-034).

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_weekend_trades_state"), "weekend_trades", type_="check")
    op.create_check_constraint(
        "state",
        "weekend_trades",
        "state in ('provisional','awaiting_settlement','settled','breached','failed')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_weekend_trades_state"), "weekend_trades", type_="check")
    op.create_check_constraint(
        "state",
        "weekend_trades",
        "state in ('provisional','awaiting_settlement','settled','breached')",
    )
