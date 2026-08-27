"""The tables — what Alpaca forgets (ADR-014, TRADING-FLOW.md §1).

Alpaca stays the system of record for balances, orders and positions. These
five tables hold only what a broker does not keep for us:

    audit_log      who did what, when, and how it ended. Append-only.
    order_intents  one row per idempotency key, so a retry cannot double-buy.
    fills          every fill copied out of Alpaca's activity feed.
    lots           open tax lots, opened by buys and eaten by sells (FIFO).
    realized_pnl   one row per sell fill: proceeds, cost basis, realized P/L.

The last three exist for one reason: the moment you sell a position, Alpaca
stops telling you what it cost you. `unrealized_pl` is on the position; there
is no `realized_pl` anywhere once the position is gone. So we keep the raw
fills and derive the lot maths ourselves.

MONEY RULE (ADR-010): every quantity, price and amount is NUMERIC in Postgres
and `Decimal` in Python. Never Float — a binary float cannot hold decimal
cents, and this is the ledger. Timestamps are all `timestamptz`; a naive
datetime in a trading ledger is a bug waiting for a DST boundary.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint/index names. Without this, Alembic autogenerate
# invents names from whatever the backend happened to assign, and the next
# migration wants to rename things that never changed.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# BIGSERIAL on Postgres; SQLite has no 64-bit autoincrement, and INTEGER there
# is already 64-bit, so the variant keeps the sqlite fallback usable in tests.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")

# Enough digits for any share count or price we will ever see, with room for
# fractional shares (Alpaca quotes them to 9 dp) and for a proceeds figure in
# the billions. NUMERIC is exact at any scale; this only bounds it.
QTY = Numeric(28, 10)
MONEY = Numeric(28, 10)

# `timestamptz`. Postgres stores UTC and hands back an aware datetime.
TZ = DateTime(timezone=True)


class AuditLog(Base):
    """One row per state-changing request. Append-only: never UPDATE, never DELETE.

    Written *after* the request has an outcome, best-effort: an audit write
    that fails must not fail the user's trade (see `audit.record`). That makes
    this log a very good record and not a perfect one, which is the right
    trade for an application audit trail — the broker holds the real ledger.

    `detail` carries a short, non-secret explanation (an error slug, a symbol).
    Never a token, never a body.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint("outcome in ('ok','error')", name="outcome"),
        Index("ix_audit_log_user_at", "clerk_user_id", "at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=func.now(), index=True)
    clerk_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Null when the request never got as far as resolving an account — a
    # provisioning call that failed, for instance.
    alpaca_account_id: Mapped[str | None] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(256), nullable=False)
    # A short stable slug: "order.place", "order.cancel", "funding.deposit",
    # "account.provision". Query by this, not by path — paths carry ids.
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class OrderIntent(Base):
    """A client's promise that two identical POSTs mean one order.

    The key is the primary key, so a concurrent duplicate loses on the unique
    constraint rather than on a read-then-write race. `body_sha256` is what
    lets us tell a genuine retry (same key, same body -> return the original
    order) from a client bug (same key, different body -> 409).

    `alpaca_order_id` is null between recording the intent and Alpaca
    accepting the order. A row stuck in that state means we crashed mid-flight;
    the retry re-places it, which is the safe direction for a paper account.
    """

    __tablename__ = "order_intents"

    idempotency_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    clerk_user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    alpaca_order_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class Fill(Base):
    """One execution, copied out of Alpaca's activity feed. Append-only.

    `alpaca_activity_id` is the upsert key: Alpaca's activity ids are stable
    and unique, so re-syncing the same window inserts nothing new. That single
    unique constraint is what makes `ledger.sync_fills` safe to call on every
    page load.

    A partially filled order produces several activities, hence several rows —
    which is correct: each one moved shares at its own price.
    """

    __tablename__ = "fills"
    __table_args__ = (
        Index("ix_fills_account_occurred", "alpaca_account_id", "occurred_at"),
        Index("ix_fills_account_symbol", "alpaca_account_id", "symbol"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    alpaca_activity_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    alpaca_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    alpaca_order_id: Mapped[str | None] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # When the trade happened (Alpaca's `transaction_time`)...
    occurred_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False)
    # ...as opposed to when we first saw it. The gap is our sync lag.
    recorded_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class Lot(Base):
    """An open tax lot: shares bought at one price, waiting to be sold.

    A buy fill opens exactly one lot. Sells consume lots oldest-first (FIFO),
    decrementing `qty_open`; when it reaches zero the lot is closed and
    `closed_at` is stamped. `qty_initial` and `unit_cost` never change, so the
    original purchase stays readable after the lot is spent.

    This pair (lots + realized_pnl) is the seed of the ERR-era double-entry
    ledger in the paper (Invariant 2).
    """

    __tablename__ = "lots"
    __table_args__ = (
        # The FIFO scan: open lots for one symbol, oldest first.
        Index("ix_lots_account_symbol_opened", "alpaca_account_id", "symbol", "opened_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    alpaca_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_by_fill_id: Mapped[int] = mapped_column(
        ForeignKey("fills.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    qty_open: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    qty_initial: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    opened_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False)
    closed_at: Mapped[dt.datetime | None] = mapped_column(TZ)


class RealizedPnl(Base):
    """The result of one sell fill, after FIFO matching.

    Why a table rather than a column on `fills`: one sell can consume many
    lots at different costs, so "the" cost basis of a sell is a sum, not a
    field of the execution. This row stores that sum once, keyed by the sell
    fill — and the unique constraint on `sell_fill_id` is what makes
    `match_lots` idempotent: a sell that already has a row is skipped.

    `realized` is stored, not computed on read, because it is the number the
    user is shown; recomputing it later against edited lots would let history
    change silently.
    """

    __tablename__ = "realized_pnl"
    __table_args__ = (
        Index("ix_realized_pnl_account_occurred", "alpaca_account_id", "occurred_at"),
        Index("ix_realized_pnl_account_symbol", "alpaca_account_id", "symbol"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    alpaca_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    sell_fill_id: Mapped[int] = mapped_column(
        ForeignKey("fills.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    proceeds: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # proceeds - cost_basis, at the moment of matching.
    realized: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Constant "FIFO" today. A column, not a constant, because the lot-relief
    # method is a real choice (LIFO, specific-id) and a future row must say
    # which one produced it.
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="FIFO")
    occurred_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False)
