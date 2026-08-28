"""One sampling run: every xStock's Jupiter price beside its real share (ADR-016).

    tokens  = jupiter.list_xstocks()          which tokens exist right now
    quotes  = jupiter.prices(mints)           what each last swapped at
    trades  = alpaca.latest_trades(shares)    what each real share last traded at
    clock   = alpaca.get_clock()              is the real market open

One TokenPrice row per token, all stamped with the same `sampled_at`, so a
run is a snapshot and not a smear. Runs every five minutes from a GitHub
Actions cron (.github/workflows/sample-prices.yml); `scripts/sample_prices.py`
is the entry point and prints a dry run by default.

BEST EFFORT ON THE ALPACA SIDE. The observation we cannot afford to lose is
the token price - it is the one nobody else keeps. So if Alpaca is slow or
down, the row is still written with the market columns null; a Jupiter
failure, by contrast, is a failed run (there is nothing to record).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import alpaca
import db
import jupiter
from models import TokenPrice


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


def market_side(underlyings: list[str]) -> tuple[dict[str, dict], bool | None]:
    """Alpaca's last trades and clock, or empty/None if Alpaca is unreachable."""
    trades: dict[str, dict] = {}
    market_open: bool | None = None
    try:
        trades = alpaca.latest_trades(underlyings)
    except alpaca.AlpacaError as exc:
        print(f"[sampler] alpaca trades unavailable: {exc.message}", file=sys.stderr)
    try:
        market_open = bool(alpaca.get_clock().get("is_open"))
    except alpaca.AlpacaError as exc:
        print(f"[sampler] alpaca clock unavailable: {exc.message}", file=sys.stderr)
    return trades, market_open


def sample_once(now: datetime | None = None) -> list[TokenPrice]:
    """Build (but do not write) one snapshot. Raises JupiterError on the token side."""
    sampled_at = now or datetime.now(timezone.utc)
    tokens = jupiter.list_xstocks()
    quotes = jupiter.prices(token["mint"] for token in tokens)
    trades, market_open = market_side(
        sorted({token["underlying"] for token in tokens if token["underlying"]})
    )

    rows: list[TokenPrice] = []
    for token in tokens:
        quote = quotes.get(token["mint"]) or {}
        usd_price = _decimal(quote.get("usdPrice"))
        if usd_price is None:
            print(f"[sampler] no price for {token['symbol']}; skipped", file=sys.stderr)
            continue
        trade = trades.get(token["underlying"]) if token["underlying"] else {}
        trade = trade or {}
        block_id = quote.get("blockId")
        rows.append(
            TokenPrice(
                sampled_at=sampled_at,
                symbol=token["symbol"],
                underlying=token["underlying"],
                mint=token["mint"],
                usd_price=usd_price,
                liquidity_usd=_decimal(quote.get("liquidity")),
                block_id=block_id if isinstance(block_id, int) else None,
                price_change_24h=_decimal(quote.get("priceChange24h")),
                market_price=_decimal(trade.get("p")),
                market_trade_at=_moment(trade.get("t")),
                market_open=market_open,
            )
        )
    return rows


def record(rows: list[TokenPrice]) -> int:
    """Append the snapshot. Returns rows written."""
    if not rows:
        return 0
    with db.session_scope() as session:
        session.add_all(rows)
    return len(rows)
