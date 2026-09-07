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
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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


class WeekendTrade(Base):
    """One trade through the ERR engine: opened while no market is open,
    settled at the first regulated execution (ADR-017, ADR-019).

    This is the state machine of the paper's §6, one row per trade:

        provisional           opened. Jupiter's quote is `p_open`, the reserve
                              is journaled to escrow, a sell is advanced
                              `qty * p_open` immediately (that advance IS the
                              product: cash now instead of Monday).
        awaiting_settlement   the weekend is over and the hedge order is
                              working at the broker (`hedge_order_id`).
        settled               the hedge filled at `p_close`; the true-up ran;
                              the trader ended at the regulated price and the
                              escrow came back plus or minus the gap.
        breached              the gap ate more than the whole reserve; the
                              excess was debited (escrow is collateral, not a
                              cap - ADR-017).

    `simulated` marks trades opened under the dev weekend override, so a row
    from the simulator can never be mistaken for a real weekend later.
    `settlement_mode` records how it closed: "market" (a real broker fill) or
    "injected" (dev only - a chosen gap, no order; the way to watch the
    reserve absorb a Monday we would otherwise wait months for).

    Money columns are the trade's arithmetic, frozen at the moment it ran;
    the journals themselves live at Alpaca under the ids kept here. The
    per-step story is in `weekend_trade_events`.
    """

    __tablename__ = "weekend_trades"
    __table_args__ = (
        CheckConstraint("side in ('buy','sell')", name="side"),
        CheckConstraint(
            "state in ('provisional','awaiting_settlement','settled','breached')",
            name="state",
        ),
        Index("ix_weekend_trades_account_created", "alpaca_account_id", "created_at"),
        Index("ix_weekend_trades_state", "state"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    clerk_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    alpaca_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)  # NVDA
    token_symbol: Mapped[str] = mapped_column(String(16), nullable=False)  # NVDAx
    mint: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    # The Jupiter executable quote the trade opened at (bid for sells, ask
    # for buys), and the reserve inputs exactly as used (ADR-018).
    p_open: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    sigma: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    z: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    reserve: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fees: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="provisional")
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Who placed it: "user" (a person through the app) or "sim" (a Groq
    # persona, ADR-026). Research queries filter on this; it never changes
    # how the engine treats the trade.
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="user", server_default="user")
    # Alpaca journal ids: the escrow in, the sell-side advance out.
    escrow_journal_id: Mapped[str | None] = mapped_column(String(64))
    advance_journal_id: Mapped[str | None] = mapped_column(String(64))
    # Settlement.
    settlement_mode: Mapped[str | None] = mapped_column(String(16))
    injected_gap: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    hedge_order_id: Mapped[str | None] = mapped_column(String(64))
    p_close: Mapped[Decimal | None] = mapped_column(MONEY)
    # What the true-up moved for the trader: p_close vs p_open, signed from
    # the trader's side. Positive means the trader got money back on top of
    # the escrow; negative means the escrow (then the account) covered it.
    true_up: Mapped[Decimal | None] = mapped_column(MONEY)
    escrow_returned: Mapped[Decimal | None] = mapped_column(MONEY)
    shortfall: Mapped[Decimal | None] = mapped_column(MONEY)
    created_at: Mapped[dt.datetime] = mapped_column(
        TZ, nullable=False, server_default=func.now(), index=True
    )
    settled_at: Mapped[dt.datetime | None] = mapped_column(TZ)


class WeekendTradeEvent(Base):
    """Everything that happened to one weekend trade, in order. Append-only.

    One row per step - opened, escrow_reserved, advance_paid, hedge_placed,
    hedge_filled, escrow_released, shortfall_debited, breached - with the
    amount it moved and the Alpaca id (journal or order) that proves it.
    The double-entry ledger of ADR-019 in its simplest honest form: the
    trade row says where things stand, this table says how they got there.
    """

    __tablename__ = "weekend_trade_events"
    __table_args__ = (
        Index("ix_weekend_trade_events_trade_at", "trade_id", "at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(
        ForeignKey("weekend_trades.id", ondelete="RESTRICT"), nullable=False
    )
    at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    # The Alpaca journal or order id behind this step, when there is one.
    alpaca_ref: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text)


class TokenPrice(Base):
    """One observation: a tokenized stock's Jupiter price beside its real share.

    The raw material for the paper's central number, sigma_gap (ADR-016).
    Sampled every five minutes around the clock, so the weekend - when the
    share cannot trade but the token can - is recorded at the same cadence as
    the trading day. `market_*` is Alpaca's last trade for the underlying at
    the same moment; it goes stale across a weekend on purpose, because that
    staleness *is* the gap being measured.

    Append-only. Nothing ever updates or deletes an observation.
    """

    __tablename__ = "token_prices"
    __table_args__ = (
        Index("ix_token_prices_symbol_sampled", "symbol", "sampled_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # The moment we asked - one value shared by every row of a run.
    sampled_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)  # NVDAx
    # NVDA. Null for a token with no listed share (SpaceX is private).
    underlying: Mapped[str | None] = mapped_column(String(16))
    mint: Mapped[str] = mapped_column(String(64), nullable=False)
    usd_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    # Solana block of the last swap behind `usd_price`; a recency check.
    block_id: Mapped[int | None] = mapped_column(BigInteger)
    price_change_24h: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    # Alpaca's last trade for the underlying. Null when Alpaca has no such
    # symbol - SpaceX has a token but no listed share.
    market_price: Mapped[Decimal | None] = mapped_column(MONEY)
    market_trade_at: Mapped[dt.datetime | None] = mapped_column(TZ)
    # Alpaca's clock at sampling time; null if the clock call failed.
    market_open: Mapped[bool | None] = mapped_column(Boolean)
    # The executable spread for a fixed ~$1,000, both directions (ADR-020,
    # the paper's RQ2): what a seller would receive and a buyer would pay
    # per token, with Jupiter's own price-impact figure for each leg. Null
    # when the quote legs failed - the price row is still worth keeping.
    bid_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    ask_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    bid_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 10))
    ask_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 10))
    quote_size_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="jupiter_price_v3")


class TokenCandle(Base):
    """One GeckoTerminal OHLCV candle for an xStock's deepest pool (ADR-016).

    The sampler (`token_prices`) only began recording on 2026-08-28. The
    paper's sigma_gap needs *past* weekends - many of them - and the only
    free source that keeps a Solana token's history at hourly resolution is
    GeckoTerminal, which serves the last 180 days of candles per pool. This
    table is that history, backfilled once (`backfill.backfill_token`) and
    extendable by re-running: the unique key makes a second pass a no-op.

    A candle belongs to a *pool*, not to the token: the same NVDAx trades in
    several pools with different depth and different prices. We keep the
    deepest USDC pool (the one Jupiter would route most size through) and
    record which, so a later reader can tell one pool's history from another.

    `bucket_start` is the candle's opening moment in UTC; GeckoTerminal sends
    it as a unix timestamp. Prices arrive as JSON numbers and are decoded as
    strings (ADR-010) before becoming NUMERIC.
    """

    __tablename__ = "token_candles"
    __table_args__ = (
        UniqueConstraint("pool", "timeframe", "bucket_start"),
        Index("ix_token_candles_symbol_timeframe_bucket", "symbol", "timeframe", "bucket_start"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)  # NVDAx
    mint: Mapped[str] = mapped_column(String(64), nullable=False)
    # The Solana address of the liquidity pool the candle was built from.
    pool: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)  # 'hour' | 'day'
    bucket_start: Mapped[dt.datetime] = mapped_column(TZ, nullable=False)
    open: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    high: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    low: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    close: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    volume_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="geckoterminal")


class MarketBar(Base):
    """One Alpaca bar for a real share - the regulated side of the gap.

    Two timeframes, two jobs:

    '1Day'  Years of daily closes for every underlying. Friday's close is
            P_MKT at the moment the market shuts and the token keeps trading;
            the daily series is how the notebook lines a weekend's token
            candles up against the last regulated print before them.
    '1Min'  Monday mornings only, 04:00-10:30 ET. ADR-017 closes the Monday
            leg premarket, as early as it is liquid, so the notebook needs
            every minute from the first extended-hours print through the
            9:30 auction and the half hour after it - the candidates for the
            settlement moment. IEX minute bars include extended hours.

    `volume` and `trade_count` are kept because liquidity *is* the question:
    a 4:07 AM bar with three trades is not a price anyone can settle at.
    `vwap` is Alpaca's own volume-weighted price for the bar.
    """

    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "bucket_start"),
        Index("ix_market_bars_symbol_timeframe_bucket", "symbol", "timeframe", "bucket_start"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)  # NVDA
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)  # '1Day' | '1Min'
    bucket_start: Mapped[dt.datetime] = mapped_column(TZ, nullable=False)
    open: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    high: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    low: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    close: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    trade_count: Mapped[int | None] = mapped_column(Integer)
    vwap: Mapped[Decimal | None] = mapped_column(MONEY)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="alpaca_iex")


class SimUser(Base):
    """A simulated trader (ADR-026): a persona, a Groq model, and a real
    sandbox brokerage account of its own.

    The persona text is the whole personality - it is what the model reads
    before every decision. `watchlist` narrows the universe the persona
    thinks about (comma-separated underlying symbols). A sim user is data:
    it can be switched off (`active`) without deleting its history.
    """

    __tablename__ = "sim_users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    persona: Mapped[str] = mapped_column(Text, nullable=False)
    watchlist: Mapped[str] = mapped_column(String(256), nullable=False)
    alpaca_account_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


class SimDecision(Base):
    """One tick of one simulated trader: what it was told, what it answered,
    and what happened (ADR-026).

    Everything is kept - the briefing, the full prompt, the raw model output,
    token counts and latency - because the decision process is itself part
    of the dataset. `outcome` is what the engine did with the intent:

        weekend_trade   opened through the ERR engine (`ref` = trade id)
        order           a regular Alpaca order (`ref` = order id)
        hold            the persona chose to do nothing
        refused         the engine said no (insufficient shares, cash, ...)
        skipped         no path for this hour (overnight queues at the broker)
        error           the model or a dependency failed; see `error`
    """

    __tablename__ = "sim_decisions"
    __table_args__ = (
        CheckConstraint(
            "outcome in ('weekend_trade','order','hold','refused','skipped','error')",
            name="outcome",
        ),
        Index("ix_sim_decisions_user_at", "sim_user_id", "at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    sim_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sim_users.id", ondelete="CASCADE"), nullable=False
    )
    at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=func.now(), index=True)
    session: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    briefing: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text)
    # The model's own deliberation before the answer, when it reports one.
    reasoning: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(String(8))
    symbol: Mapped[str | None] = mapped_column(String(16))
    qty: Mapped[Decimal | None] = mapped_column(QTY)
    reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    ref: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)


class HedgeLeg(Base):
    """One on-chain leg of a weekend trade's hedge (ADR-025, Version B).

    Two legs per trade. The OPEN leg mirrors the customer on Jupiter at the
    moment the trade opens (customer sells -> the engine sells the token;
    customer buys -> the engine buys it). The CLOSE leg unwinds it when the
    trade settles at the broker. In `mode` "shadow" the transaction is built
    by Jupiter against the engine wallet, signed here when the keypair is
    present, and simulated on mainnet - and never sent. The row records
    what sending it would have cost, in lamports and in dollars at that
    moment's SOL price.

    On the close leg, the three P/L columns answer the Version B question
    for this one trade: had Yagnum guaranteed `p_open` and hedged on-chain,
    what would it have made or lost after spread and gas?

        broker_pnl     the broker leg Yagnum would own: qty x (p_close - p_open)
                       for a customer sell, the reverse for a buy
        chain_pnl      qty x (open price - close price) for a sell-first
                       hedge, the reverse for buy-first: the spread plus the
                       token's own move, per token
        version_b_pnl  broker_pnl + chain_pnl - gas of both legs
    """

    __tablename__ = "hedge_legs"
    __table_args__ = (
        CheckConstraint("leg in ('open','close')", name="leg"),
        CheckConstraint("mode in ('shadow','live')", name="mode"),
        CheckConstraint("side in ('buy','sell')", name="side"),
        Index("ix_hedge_legs_trade", "trade_id", "leg"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("weekend_trades.id", ondelete="CASCADE"), nullable=False
    )
    leg: Mapped[str] = mapped_column(String(8), nullable=False)
    at: Mapped[dt.datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    token_symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    mint: Mapped[str] = mapped_column(String(64), nullable=False)
    token_program: Mapped[str | None] = mapped_column(String(64))
    wallet: Mapped[str] = mapped_column(String(64), nullable=False)
    # The quote: what the swap would have moved.
    qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    usd_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 10))
    slippage_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    route: Mapped[str | None] = mapped_column(String(256))
    # The transaction Jupiter built, and what it would cost to send.
    compute_unit_limit: Mapped[int | None] = mapped_column(Integer)
    priority_fee_lamports: Mapped[int | None] = mapped_column(BigInteger)
    base_fee_lamports: Mapped[int | None] = mapped_column(BigInteger)
    ata_exists: Mapped[bool | None] = mapped_column(Boolean)
    ata_rent_lamports: Mapped[int | None] = mapped_column(BigInteger)
    gas_lamports: Mapped[int | None] = mapped_column(BigInteger)
    sol_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    gas_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    jupiter_sim_error: Mapped[str | None] = mapped_column(Text)
    rpc_sim_error: Mapped[str | None] = mapped_column(Text)
    rpc_units_consumed: Mapped[int | None] = mapped_column(BigInteger)
    signed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    signature: Mapped[str | None] = mapped_column(String(128))
    last_valid_block_height: Mapped[int | None] = mapped_column(BigInteger)
    # Close leg only.
    broker_pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    chain_pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    version_b_pnl: Mapped[Decimal | None] = mapped_column(MONEY)
    error: Mapped[str | None] = mapped_column(Text)

