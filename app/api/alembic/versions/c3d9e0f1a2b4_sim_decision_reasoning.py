"""Keep the model's reasoning and its token count on each sim decision.

Revision ID: c3d9e0f1a2b4
Revises: b7e4c1a9d2f3
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d9e0f1a2b4"
down_revision: str | None = "b7e4c1a9d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sim_decisions", sa.Column("reasoning", sa.Text(), nullable=True))
    op.add_column("sim_decisions", sa.Column("reasoning_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("sim_decisions", "reasoning_tokens")
    op.drop_column("sim_decisions", "reasoning")
