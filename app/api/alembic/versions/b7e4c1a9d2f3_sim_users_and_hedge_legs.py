"""Simulated users (ADR-026) and shadow hedge legs (ADR-025).

Three new tables and one column:

    sim_users        a persona with its own sandbox account
    sim_decisions    every tick: briefing, prompt, raw output, outcome
    hedge_legs       the on-chain leg of each weekend trade, shadow-built
    weekend_trades.source   "user" | "sim"

Revision ID: b7e4c1a9d2f3
Revises: 047e70d67c1e
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e4c1a9d2f3"
down_revision: str | None = "047e70d67c1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "weekend_trades",
        sa.Column("source", sa.String(length=8), nullable=False, server_default="user"),
    )

    op.create_table(
        "sim_users",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("persona", sa.Text(), nullable=False),
        sa.Column("watchlist", sa.String(length=256), nullable=False),
        sa.Column("alpaca_account_id", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sim_users")),
        sa.UniqueConstraint("alpaca_account_id", name=op.f("uq_sim_users_alpaca_account_id")),
        sa.UniqueConstraint("slug", name=op.f("uq_sim_users_slug")),
    )

    op.create_table(
        "sim_decisions",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("sim_user_id", sa.BigInteger(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("session", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("briefing", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("action", sa.String(length=8), nullable=True),
        sa.Column("symbol", sa.String(length=16), nullable=True),
        sa.Column("qty", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("ref", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "outcome in ('weekend_trade','order','hold','refused','skipped','error')",
            name=op.f("ck_sim_decisions_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["sim_user_id"], ["sim_users.id"], name=op.f("fk_sim_decisions_sim_user_id_sim_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sim_decisions")),
    )
    op.create_index(op.f("ix_sim_decisions_at"), "sim_decisions", ["at"], unique=False)
    op.create_index("ix_sim_decisions_user_at", "sim_decisions", ["sim_user_id", "at"], unique=False)

    op.create_table(
        "hedge_legs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("trade_id", sa.BigInteger(), nullable=False),
        sa.Column("leg", sa.String(length=8), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("token_symbol", sa.String(length=16), nullable=False),
        sa.Column("mint", sa.String(length=64), nullable=False),
        sa.Column("token_program", sa.String(length=64), nullable=True),
        sa.Column("wallet", sa.String(length=64), nullable=False),
        sa.Column("qty", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("usd_amount", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("price", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("price_impact_pct", sa.Numeric(precision=18, scale=10), nullable=True),
        sa.Column("slippage_bps", sa.Integer(), nullable=False),
        sa.Column("route", sa.String(length=256), nullable=True),
        sa.Column("compute_unit_limit", sa.Integer(), nullable=True),
        sa.Column("priority_fee_lamports", sa.BigInteger(), nullable=True),
        sa.Column("base_fee_lamports", sa.BigInteger(), nullable=True),
        sa.Column("ata_exists", sa.Boolean(), nullable=True),
        sa.Column("ata_rent_lamports", sa.BigInteger(), nullable=True),
        sa.Column("gas_lamports", sa.BigInteger(), nullable=True),
        sa.Column("sol_usd", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("gas_usd", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("jupiter_sim_error", sa.Text(), nullable=True),
        sa.Column("rpc_sim_error", sa.Text(), nullable=True),
        sa.Column("rpc_units_consumed", sa.BigInteger(), nullable=True),
        sa.Column("signed", sa.Boolean(), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=True),
        sa.Column("last_valid_block_height", sa.BigInteger(), nullable=True),
        sa.Column("broker_pnl", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("chain_pnl", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("version_b_pnl", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("leg in ('open','close')", name=op.f("ck_hedge_legs_leg")),
        sa.CheckConstraint("mode in ('shadow','live')", name=op.f("ck_hedge_legs_mode")),
        sa.CheckConstraint("side in ('buy','sell')", name=op.f("ck_hedge_legs_side")),
        sa.ForeignKeyConstraint(
            ["trade_id"], ["weekend_trades.id"], name=op.f("fk_hedge_legs_trade_id_weekend_trades"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hedge_legs")),
    )
    op.create_index("ix_hedge_legs_trade", "hedge_legs", ["trade_id", "leg"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_hedge_legs_trade", table_name="hedge_legs")
    op.drop_table("hedge_legs")
    op.drop_index("ix_sim_decisions_user_at", table_name="sim_decisions")
    op.drop_index(op.f("ix_sim_decisions_at"), table_name="sim_decisions")
    op.drop_table("sim_decisions")
    op.drop_table("sim_users")
    op.drop_column("weekend_trades", "source")
