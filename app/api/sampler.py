"""One sampling run: every tokenized stock's Jupiter price beside its real share (ADR-016).

    tokens  = jupiter.list_xstocks()          which xStocks exist right now
            + jupiter.list_ondo()             the verified Ondo twins (fixed list)
    quotes  = jupiter.prices(mints)           what each last swapped at
    spread  = jupiter.spread_quote(...)       executable bid/ask for ~$1,000
                                              (two quote calls per token, ADR-020)
    trades  = alpaca.latest_trades(shares)    what each real share last traded at
    clock   = alpaca.get_clock()              is the real market open

One TokenPrice row per token, all stamped with the same `sampled_at`, so a
run is a snapshot and not a smear. Runs from a GitHub Actions cron
(.github/workflows/sample-prices.yml); `scripts/sample_prices.py` is the
entry point and prints a dry run by default.

THE RESEARCH SERIES (docs/RESEARCH-COLLECTION.md). Around that core, one run
also collects - each best effort, each in its own try, none able to cost
the token rows:

    A  issuer          Ondo tokens sampled exactly like xStocks; `issuer` column
    B  quote_ladder    $10k/$50k quotes each way for a few tokens, <= once an hour
    C  oracle_prices   what Pyth's equity feeds report (needs PYTH_API_KEY)
    D  share_trades    the share's latest trade with its feed and session

BEST EFFORT ON THE ALPACA SIDE. The observation we cannot afford to lose is
the token price - it is the one nobody else keeps. So if Alpaca is slow or
down, the row is still written with the market columns null; a Jupiter
failure on the token list or prices, by contrast, is a failed run (there is
nothing to record).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa

import alpaca
import db
import jupiter
import pyth
import sessions
from config import settings
from models import OraclePrice, QuoteLadder, ShareTrade, TokenPrice

# A breath between tokens (ADR-020). Jupiter's gateway allows roughly one
# request per second on our tier - a burst 429s after a handful (measured
# live, 2026-09-01). With the leg delay in jupiter.spread_quote this paces
# the quote calls to just under that. Tests zero this.
SPREAD_DELAY_SECONDS = 1.2

# The ladder's pause between quote calls, and the pause before it starts
# (the spread loop has just used the rate budget). Tests zero both.
LADDER_DELAY_SECONDS = 1.1
LADDER_START_PAUSE_SECONDS = 2.0

# The feed the share-side series is read from. The only real-time stock
# feed this plan serves (alpaca.latest_trades has the evidence).
SHARE_FEED = "iex"


def _log(message: str) -> None:
    print(f"[sampler] {message}", file=sys.stderr)


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _moment(value) -> datetime | None:
    """Alpaca's RFC-3339 timestamp, nanoseconds truncated to microseconds."""
    text = str(value or "").strip()
    if not text:
        return None
    if "." in text:
        head, _, tail = text.partition(".")
        fraction = "".join(ch for ch in tail if ch.isdigit())
        zone = tail[len(fraction) :]
        text = f"{head}.{fraction[:6]}{zone}" if fraction else f"{head}{zone}"
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _csv(text: str) -> list[str]:
    return [part.strip() for part in str(text or "").split(",") if part.strip()]


def market_side(
    underlyings: list[str], feed: str | None = None
) -> tuple[dict[str, dict], bool | None]:
    """Alpaca's last trades and clock, or empty/None if Alpaca is unreachable.

    The sampler pins `feed` (SHARE_FEED) so the share_trades rows can say
    which feed they came from; the /market route leaves Alpaca's default.
    """
    trades: dict[str, dict] = {}
    market_open: bool | None = None
    try:
        trades = (
            alpaca.latest_trades(underlyings, feed=feed) if feed else alpaca.latest_trades(underlyings)
        )
    except alpaca.AlpacaError as exc:
        _log(f"alpaca trades unavailable: {exc.message}")
    try:
        market_open = bool(alpaca.get_clock().get("is_open"))
    except alpaca.AlpacaError as exc:
        _log(f"alpaca clock unavailable: {exc.message}")
    return trades, market_open


def universe() -> list[dict]:
    """Every token to sample: live xStocks list, then the fixed Ondo list.

    Raises JupiterError if the xStocks list cannot be fetched (a failed run).
    """
    return jupiter.list_xstocks() + jupiter.list_ondo()


@dataclass
class Snapshot:
    """Everything one run observed. Only `prices` is required to be non-empty."""

    sampled_at: datetime
    tokens: list[dict] = field(default_factory=list)
    quotes: dict[str, dict] = field(default_factory=dict)
    trades: dict[str, dict] = field(default_factory=dict)
    market_open: bool | None = None
    prices: list[TokenPrice] = field(default_factory=list)
    ladder: list[QuoteLadder] = field(default_factory=list)
    oracles: list[OraclePrice] = field(default_factory=list)
    share_trades: list[ShareTrade] = field(default_factory=list)


def snapshot(now: datetime | None = None) -> Snapshot:
    """The token side: one TokenPrice per token. Raises JupiterError on the token list/prices."""
    sampled_at = now or datetime.now(timezone.utc)
    tokens = universe()
    quotes = jupiter.prices(token["mint"] for token in tokens)
    trades, market_open = market_side(
        sorted({token["underlying"] for token in tokens if token["underlying"]}), feed=SHARE_FEED
    )
    snap = Snapshot(sampled_at, tokens, quotes, trades, market_open)

    for token in tokens:
        quote = quotes.get(token["mint"]) or {}
        usd_price = _decimal(quote.get("usdPrice"))
        if usd_price is None:
            _log(f"no price for {token['symbol']}; skipped")
            continue
        trade = trades.get(token["underlying"]) if token["underlying"] else {}
        trade = trade or {}
        block_id = quote.get("blockId")
        multiplier = jupiter.ui_multiplier(quote, sampled_at)

        # The spread (ADR-020): best effort, like the Alpaca side. A failed
        # quote leg loses the spread columns, never the price observation.
        # spread_quote sizes its sell leg from a per-RAW-token price, which
        # is the per-share price x multiplier.
        spread: dict = {}
        try:
            spread = jupiter.spread_quote(token, usd_price * (multiplier or 1))
        except (jupiter.JupiterError, ValueError, KeyError) as exc:
            _log(f"no spread for {token['symbol']}: {exc}")
        if SPREAD_DELAY_SECONDS:
            time.sleep(SPREAD_DELAY_SECONDS)

        snap.prices.append(
            TokenPrice(
                sampled_at=sampled_at,
                symbol=token["symbol"],
                underlying=token["underlying"],
                mint=token["mint"],
                issuer=token.get("issuer", "xstocks"),
                usd_price=usd_price,
                liquidity_usd=_decimal(quote.get("liquidity")),
                block_id=block_id if isinstance(block_id, int) else None,
                price_change_24h=_decimal(quote.get("priceChange24h")),
                market_price=_decimal(trade.get("p")),
                market_trade_at=_moment(trade.get("t")),
                market_open=market_open,
                bid_usd=spread.get("bid"),
                ask_usd=spread.get("ask"),
                bid_impact_pct=spread.get("bid_impact_pct"),
                ask_impact_pct=spread.get("ask_impact_pct"),
                quote_size_usd=spread.get("quote_size_usd"),
                ui_multiplier=multiplier,
            )
        )
    return snap


def sample_once(now: datetime | None = None) -> list[TokenPrice]:
    """Build (but do not write) the token rows of one snapshot. Raises JupiterError."""
    return snapshot(now).prices


# ---------------------------------------------------------------------------
# B. The depth ladder
# ---------------------------------------------------------------------------


def ladder_due(now: datetime) -> bool:
    """True when no ladder row is younger than LADDER_MIN_INTERVAL_MINUTES.

    The gate lives in the data, not the cron: the cron is best effort (~6
    runs a day observed), so "every 12th run" would mean "twice a day".
    A failed read skips the ladder - better a missing rung than a 429 storm.
    """
    if not db.is_configured():
        return False
    cutoff = now - timedelta(minutes=settings.ladder_min_interval_minutes)
    try:
        with db.session_scope() as session:
            latest = session.scalar(sa.select(sa.func.max(QuoteLadder.sampled_at)))
    except Exception as exc:  # noqa: BLE001 - any DB failure means "skip"
        _log(f"ladder gate unreadable, ladder skipped: {type(exc).__name__}")
        return False
    return latest is None or latest <= cutoff


def _rung_status(exc: Exception) -> str:
    if isinstance(exc, jupiter.JupiterError):
        if exc.status_code == 429:
            return "rate_limited"
        if "route" in exc.message.lower():
            return "no_route"
    return "error"


def ladder_rows(snap: Snapshot) -> list[QuoteLadder]:
    """$10k/$50k buy and sell quotes for the configured tokens.

    Paced at LADDER_DELAY_SECONDS between calls. The first 429 ends the
    ladder for this run (recorded as one 'rate_limited' row); every other
    failure is recorded on its rung and the ladder moves on.
    """
    wanted = _csv(settings.ladder_symbols)
    sizes = [Decimal(size) for size in _csv(settings.ladder_sizes_usd)]
    by_symbol = {token["symbol"]: token for token in snap.tokens}
    rows: list[QuoteLadder] = []
    if LADDER_START_PAUSE_SECONDS:
        time.sleep(LADDER_START_PAUSE_SECONDS)

    first_call = True
    for symbol in wanted:
        token = by_symbol.get(symbol)
        quote = snap.quotes.get(token["mint"]) if token else None
        share_price = _decimal((quote or {}).get("usdPrice"))
        if token is None or share_price is None:
            _log(f"ladder: no token or price for {symbol}; skipped")
            continue
        multiplier = jupiter.ui_multiplier(quote, snap.sampled_at)
        for size in sizes:
            for side in ("buy", "sell"):
                if not first_call and LADDER_DELAY_SECONDS:
                    time.sleep(LADDER_DELAY_SECONDS)
                first_call = False
                row = QuoteLadder(
                    sampled_at=snap.sampled_at,
                    symbol=symbol,
                    issuer=token.get("issuer", "xstocks"),
                    underlying=token.get("underlying"),
                    mint=token["mint"],
                    size_usd=size,
                    side=side,
                    ui_multiplier=multiplier,
                )
                try:
                    rung = jupiter.ladder_quote(token, side, size, share_price, multiplier)
                except (jupiter.JupiterError, ValueError, KeyError) as exc:
                    row.status = _rung_status(exc)
                    row.error = str(exc)[:300]
                    rows.append(row)
                    if row.status == "rate_limited":
                        _log(f"ladder: 429 at {symbol} {side} ${size}; ladder stopped for this run")
                        return rows
                    continue
                row.status = "ok"
                for key, value in rung.items():
                    setattr(row, key, value)
                rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# C. The oracle record
# ---------------------------------------------------------------------------


def oracle_rows(sampled_at: datetime) -> list[OraclePrice]:
    """What Pyth reports for each feed in pyth.FEEDS. One HTTP call."""
    found = pyth.latest([feed["id"] for feed in pyth.FEEDS])
    rows: list[OraclePrice] = []
    for feed in pyth.FEEDS:
        quote = found.get(feed["id"])
        if quote is None:
            _log(f"pyth: no update for {feed['feed_symbol']}")
            continue
        conf = quote["conf"]
        rows.append(
            OraclePrice(
                sampled_at=sampled_at,
                provider="pyth",
                symbol=feed["symbol"],
                feed_kind=feed["kind"],
                feed_id=feed["id"],
                feed_symbol=feed["feed_symbol"],
                price=quote["price"],
                conf=conf,
                expo=quote["expo"],
                price_usd=pyth.to_usd(quote["price"], quote["expo"]),
                conf_usd=pyth.to_usd(conf, quote["expo"]) if conf is not None else None,
                publish_time=quote["publish_time"],
            )
        )
    return rows


# ---------------------------------------------------------------------------
# D. The share's own prints
# ---------------------------------------------------------------------------


def _trading_days():
    try:
        return sessions._trading_days()
    except Exception:  # noqa: BLE001 - the label is optional
        return None


def share_trade_rows(snap: Snapshot) -> list[ShareTrade]:
    """One row per share from the trades this run already fetched. No extra market-data call."""
    if not snap.trades:
        return []
    days = _trading_days()
    rows: list[ShareTrade] = []
    for symbol in sorted(snap.trades):
        trade = snap.trades[symbol] or {}
        price = _decimal(trade.get("p"))
        trade_at = _moment(trade.get("t"))
        if price is None or trade_at is None:
            continue
        conditions = trade.get("c")
        if isinstance(conditions, list):
            conditions = ",".join(str(c).strip() or "_" for c in conditions)
        rows.append(
            ShareTrade(
                sampled_at=snap.sampled_at,
                symbol=symbol,
                feed=SHARE_FEED,
                price=price,
                size=_decimal(trade.get("s")),
                trade_at=trade_at,
                exchange=str(trade.get("x"))[:8] if trade.get("x") else None,
                conditions=str(conditions)[:64] if conditions else None,
                session=sessions.scheduled_session(trade_at, trading_days=days),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# The whole run
# ---------------------------------------------------------------------------


def sample_all(now: datetime | None = None, *, ladder: bool | None = None) -> Snapshot:
    """The token snapshot plus series B-D, each best effort.

    `ladder`: True forces the ladder, False skips it, None asks `ladder_due`.
    Raises JupiterError only for the token side, as `snapshot` does.
    """
    snap = snapshot(now)

    try:
        snap.share_trades = share_trade_rows(snap)
    except Exception as exc:  # noqa: BLE001 - one series never sinks the run
        _log(f"share trades failed: {type(exc).__name__}: {exc}")

    try:
        snap.oracles = oracle_rows(snap.sampled_at)
    except pyth.PythUnavailable as exc:
        _log(f"oracle record skipped: {exc.message}")
    except Exception as exc:  # noqa: BLE001
        _log(f"oracle record failed: {type(exc).__name__}: {exc}")

    run_ladder = ladder_due(snap.sampled_at) if ladder is None else ladder
    if run_ladder:
        try:
            snap.ladder = ladder_rows(snap)
        except Exception as exc:  # noqa: BLE001
            _log(f"ladder failed: {type(exc).__name__}: {exc}")
    return snap


def record(rows: list) -> int:
    """Append rows in one transaction. Returns rows written."""
    if not rows:
        return 0
    with db.session_scope() as session:
        session.add_all(rows)
    return len(rows)


def record_all(snap: Snapshot) -> dict[str, int]:
    """Write each series in its own transaction, token prices first.

    A failure writing one series is logged and costs only that series; a
    failure writing the token prices is raised, since that is the run.
    """
    written = {"token_prices": record(snap.prices)}
    for name, rows in (
        ("share_trades", snap.share_trades),
        ("oracle_prices", snap.oracles),
        ("quote_ladder", snap.ladder),
    ):
        try:
            written[name] = record(rows)
        except Exception as exc:  # noqa: BLE001
            _log(f"writing {name} failed: {type(exc).__name__}: {exc}")
            written[name] = 0
    return written
