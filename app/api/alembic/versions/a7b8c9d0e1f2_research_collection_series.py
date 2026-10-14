"""Research collection: Ondo issuer, depth ladder, oracle record, share trades.

docs/RESEARCH-COLLECTION.md, series A-D:

    A  token_prices.issuer ('xstocks' | 'ondo', existing rows 'xstocks')
       token_prices.ui_multiplier (Token-2022 scaled-UI multiplier)
    B  quote_ladder    $10k/$50k Jupiter quotes each way, <= once an hour
    C  oracle_prices   Pyth's equity feeds, each run
    D  share_trades    the share's latest trade with feed and session

Additive only: two nullable/defaulted columns and three new tables. No
existing row changes meaning.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
_TZ = sa.DateTime(timezone=True)
_MONEY = sa.Numeric(precision=28, scale=10)


def upgrade() -> None:
    # --- A: issuer and multiplier on the existing price rows -------------
    op.add_column(
        "token_prices",
        sa.Column("issuer", sa.String(length=16), nullable=False, server_default="xstocks"),
    )
    op.add_column(
        "token_prices",
        sa.Column("ui_multiplier", sa.Numeric(precision=28, scale=18), nullable=True),
    )

    # --- B: the depth ladder ---------------------------------------------
    op.create_table(
        "quote_ladder",
        sa.Column("id", _ID, autoincrement=True, nullable=False),
        sa.Column("sampled_at", _TZ, nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("issuer", sa.String(length=16), nullable=False),
        sa.Column("underlying", sa.String(length=16), nullable=True),
        sa.Column("mint", sa.String(length=64), nullable=False),
        sa.Column("size_usd", _MONEY, nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("in_amount", sa.Numeric(precision=38, scale=0), nullable=True),
        sa.Column("out_amount", sa.Numeric(precision=38, scale=0), nullable=True),
        sa.Column("share_amount", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("usd_amount", _MONEY, nullable=True),
        sa.Column("price_usd", _MONEY, nullable=True),
        sa.Column("price_impact_pct", sa.Numeric(precision=18, scale=10), nullable=True),
        sa.Column("ui_multiplier", sa.Numeric(precision=28, scale=18), nullable=True),
        sa.Column("route", sa.String(length=200), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_ladder")),
    )
    op.create_index(op.f("ix_quote_ladder_sampled_at"), "quote_ladder", ["sampled_at"], unique=False)
    op.create_index("ix_quote_ladder_symbol_sampled", "quote_ladder", ["symbol", "sampled_at"], unique=False)

    # --- C: the oracle record --------------------------------------------
    op.create_table(
        "oracle_prices",
        sa.Column("id", _ID, autoincrement=True, nullable=False),
        sa.Column("sampled_at", _TZ, nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("feed_kind", sa.String(length=16), nullable=False),
        sa.Column("feed_id", sa.String(length=80), nullable=False),
        sa.Column("feed_symbol", sa.String(length=64), nullable=True),
        sa.Column("price", sa.Numeric(precision=38, scale=0), nullable=False),
        sa.Column("conf", sa.Numeric(precision=38, scale=0), nullable=True),
        sa.Column("expo", sa.Integer(), nullable=False),
        sa.Column("price_usd", _MONEY, nullable=False),
        sa.Column("conf_usd", _MONEY, nullable=True),
        sa.Column("publish_time", _TZ, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oracle_prices")),
    )
    op.create_index(op.f("ix_oracle_prices_sampled_at"), "oracle_prices", ["sampled_at"], unique=False)
    op.create_index("ix_oracle_prices_symbol_sampled", "oracle_prices", ["symbol", "sampled_at"], unique=False)

    # --- D: the share's own prints ---------------------------------------
    op.create_table(
        "share_trades",
        sa.Column("id", _ID, autoincrement=True, nullable=False),
        sa.Column("sampled_at", _TZ, nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("feed", sa.String(length=16), nullable=False),
        sa.Column("price", _MONEY, nullable=False),
        sa.Column("size", sa.Numeric(precision=28, scale=10), nullable=True),
        sa.Column("trade_at", _TZ, nullable=False),
        sa.Column("exchange", sa.String(length=8), nullable=True),
        sa.Column("conditions", sa.String(length=64), nullable=True),
        sa.Column("session", sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_trades")),
    )
    op.create_index(op.f("ix_share_trades_sampled_at"), "share_trades", ["sampled_at"], unique=False)
    op.create_index("ix_share_trades_symbol_sampled", "share_trades", ["symbol", "sampled_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_share_trades_symbol_sampled", table_name="share_trades")
    op.drop_index(op.f("ix_share_trades_sampled_at"), table_name="share_trades")
    op.drop_table("share_trades")
    op.drop_index("ix_oracle_prices_symbol_sampled", table_name="oracle_prices")
    op.drop_index(op.f("ix_oracle_prices_sampled_at"), table_name="oracle_prices")
    op.drop_table("oracle_prices")
    op.drop_index("ix_quote_ladder_symbol_sampled", table_name="quote_ladder")
    op.drop_index(op.f("ix_quote_ladder_sampled_at"), table_name="quote_ladder")
    op.drop_table("quote_ladder")
    op.drop_column("token_prices", "ui_multiplier")
    op.drop_column("token_prices", "issuer")
