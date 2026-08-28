"""Historical backfill for the gap-volatility research (ADR-016, ADR-017).

The sampler records the present. These functions fetch the past, once, from
the two sources that keep it for free:

    backfill_token(symbol, mint, timeframe)   GeckoTerminal candles for the
                                              token's deepest USDC pool, paged
                                              backwards to the 180-day wall
    backfill_market_daily(symbol, start)      Alpaca daily bars for the real
                                              share, years of them
    backfill_market_minutes(symbol, monday)   Alpaca minute bars for one Monday
                                              morning, 04:00-10:30 ET, which is
                                              where ADR-017 says settlement
                                              happens

Every writer upserts with INSERT ... ON CONFLICT DO NOTHING on the table's
natural key, so running the backfill twice writes nothing the second time and
a run that dies halfway can simply be restarted. Each returns the number of
rows actually written.

Pure in the sense that matters: no hidden clock. `mondays_since` and
`backfill_token` take the reference moment as an argument, so a test can pin
"now" and a DST boundary can be exercised on purpose.

Prices stay strings until they become Decimal (ADR-010); GeckoTerminal and
Alpaca both send bare JSON numbers, and both clients decode them with
parse_float=str.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy.dialects.postgresql import insert

import alpaca
import db
import geckoterminal
from models import MarketBar, TokenCandle

ET = ZoneInfo("America/New_York")

# ADR-017: the Monday leg closes premarket, as early as it is liquid.
# Alpaca accepts extended-hours orders from 04:00 ET; 10:30 ET is an hour
# after the auction, long enough to see the open settle down.
MONDAY_WINDOW_START = dt.time(4, 0)
MONDAY_WINDOW_END = dt.time(10, 30)

MARKET_DAILY_START = "2024-08-01"
ALPACA_PAGE_LIMIT = 10000


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _utc(timestamp: int | str) -> dt.datetime:
    return dt.datetime.fromtimestamp(int(timestamp), tz=dt.timezone.utc)


def _moment(value) -> dt.datetime | None:
    """Alpaca's RFC-3339 `t`, nanoseconds and all, as an aware datetime."""
    text = str(value or "").strip()
    if not text:
        return None
    if "." in text:
        head, _, tail = text.partition(".")
        fraction = "".join(ch for ch in tail if ch.isdigit())
        zone = tail[len(fraction) :]
        text = f"{head}.{fraction[:6]}{zone}" if fraction else f"{head}{zone}"
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------------------
# Token candles (GeckoTerminal)
# ---------------------------------------------------------------------------


def candle_rows(symbol: str, mint: str, pool: str, timeframe: str, ohlcv_list: list[list]) -> list[dict]:
    """GeckoTerminal's [[ts, o, h, l, c, volume], ...] -> token_candles rows."""
    rows: list[dict] = []
    for entry in ohlcv_list:
        ts, open_, high, low, close = entry[:5]
        volume = entry[5] if len(entry) > 5 else None
        prices = [_decimal(open_), _decimal(high), _decimal(low), _decimal(close)]
        if any(price is None for price in prices):
            continue
        rows.append(
            {
                "symbol": symbol,
                "mint": mint,
                "pool": pool,
                "timeframe": timeframe,
                "bucket_start": _utc(ts),
                "open": prices[0],
                "high": prices[1],
                "low": prices[2],
                "close": prices[3],
                "volume_usd": _decimal(volume),
                "source": "geckoterminal",
            }
        )
    return rows


def fetch_candles(pool: str, timeframe: str, cutoff: dt.datetime) -> list[list]:
    """Every candle from now back to `cutoff` (or the 180-day wall), newest first.

    Pages backwards: each request's `before_timestamp` is the oldest `ts` of
    the page before it. Stops on the history-limit 401, on an empty or short
    page, or once a page reaches past the cutoff.
    """
    cutoff_ts = int(cutoff.timestamp())
    collected: list[list] = []
    before: int | None = None
    while True:
        try:
            page = geckoterminal.ohlcv(pool, timeframe, before_timestamp=before)
        except geckoterminal.HistoryLimitReached:
            break
        if not page:
            break
        collected.extend(row for row in page if int(row[0]) >= cutoff_ts)
        oldest = min(int(row[0]) for row in page)
        if oldest <= cutoff_ts or len(page) < geckoterminal.PAGE_LIMIT:
            break
        before = oldest
    return collected


def upsert_candles(rows: list[dict]) -> int:
    """INSERT ... ON CONFLICT (pool, timeframe, bucket_start) DO NOTHING."""
    if not rows:
        return 0
    # RETURNING yields only the rows actually inserted, so its length is the
    # exact count; `rowcount` is unreliable for a multi-row VALUES insert.
    statement = (
        insert(TokenCandle)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["pool", "timeframe", "bucket_start"])
        .returning(TokenCandle.id)
    )
    with db.session_scope() as session:
        return len(session.execute(statement).all())


def backfill_token(
    symbol: str,
    mint: str,
    timeframe: str = "hour",
    days: int = geckoterminal.HISTORY_DAYS,
    *,
    now: dt.datetime | None = None,
    pool: str | None = None,
) -> int:
    """Fetch and store this token's candles. Returns rows written (0 if no pool)."""
    if pool is None:
        chosen = geckoterminal.deepest_usdc_pool(mint)
        if chosen is None:
            return 0
        pool = chosen["address"]
    reference = now or dt.datetime.now(dt.timezone.utc)
    cutoff = reference - dt.timedelta(days=days)
    ohlcv_list = fetch_candles(pool, timeframe, cutoff)
    return upsert_candles(candle_rows(symbol, mint, pool, timeframe, ohlcv_list))


# ---------------------------------------------------------------------------
# Market bars (Alpaca)
# ---------------------------------------------------------------------------


def bar_rows(symbol: str, timeframe: str, bars: list[dict]) -> list[dict]:
    """Alpaca's {t,o,h,l,c,v,n,vw} bars -> market_bars rows."""
    rows: list[dict] = []
    for bar in bars:
        bucket_start = _moment(bar.get("t"))
        prices = [_decimal(bar.get(key)) for key in ("o", "h", "l", "c")]
        if bucket_start is None or any(price is None for price in prices):
            continue
        count = bar.get("n")
        rows.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "bucket_start": bucket_start,
                "open": prices[0],
                "high": prices[1],
                "low": prices[2],
                "close": prices[3],
                "volume": _decimal(bar.get("v")),
                "trade_count": int(count) if isinstance(count, int) or str(count).isdigit() else None,
                "vwap": _decimal(bar.get("vw")),
                "source": "alpaca_iex",
            }
        )
    return rows


def fetch_bars(symbol: str, params: dict) -> list[dict]:
    """All pages of GET /v2/stocks/{symbol}/bars, following next_page_token."""
    collected: list[dict] = []
    token: str | None = None
    while True:
        query = dict(params)
        if token:
            query["page_token"] = token
        body = alpaca._data_request(f"/v2/stocks/{symbol}/bars", query) or {}
        collected.extend(bar for bar in (body.get("bars") or []) if isinstance(bar, dict))
        token = body.get("next_page_token")
        if not token:
            break
    return collected


def upsert_bars(rows: list[dict]) -> int:
    """INSERT ... ON CONFLICT (symbol, timeframe, bucket_start) DO NOTHING."""
    if not rows:
        return 0
    # RETURNING yields only the rows actually inserted, so its length is the
    # exact count; `rowcount` is unreliable for a multi-row VALUES insert.
    statement = (
        insert(MarketBar)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["symbol", "timeframe", "bucket_start"])
        .returning(MarketBar.id)
    )
    with db.session_scope() as session:
        return len(session.execute(statement).all())


def backfill_market_daily(symbol: str, start: str = MARKET_DAILY_START) -> int:
    """Split-adjusted daily bars from `start` (YYYY-MM-DD) to today. Rows written."""
    bars = fetch_bars(
        symbol,
        {
            "timeframe": "1Day",
            "start": start,
            "limit": ALPACA_PAGE_LIMIT,
            "adjustment": "split",
            "feed": "iex",
            "sort": "asc",
        },
    )
    return upsert_bars(bar_rows(symbol, "1Day", bars))


def monday_window_utc(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """04:00-10:30 ET on `day`, as aware UTC datetimes. DST-aware via zoneinfo."""
    start = dt.datetime.combine(day, MONDAY_WINDOW_START, tzinfo=ET)
    end = dt.datetime.combine(day, MONDAY_WINDOW_END, tzinfo=ET)
    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def backfill_market_minutes(symbol: str, day: dt.date) -> int:
    """Minute bars for one morning's 04:00-10:30 ET window. Rows written."""
    start, end = monday_window_utc(day)
    bars = fetch_bars(
        symbol,
        {
            "timeframe": "1Min",
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
            "limit": ALPACA_PAGE_LIMIT,
            "feed": "iex",
            "sort": "asc",
        },
    )
    return upsert_bars(bar_rows(symbol, "1Min", bars))


def mondays_since(now: dt.datetime, days: int = geckoterminal.HISTORY_DAYS) -> list[dt.date]:
    """Every Monday from `days` before `now` up to and including `now`'s ET date.

    Judged in ET, because "Monday" means the exchange's Monday: at 01:00 UTC
    on a Tuesday it is still Monday evening in New York.
    """
    today = now.astimezone(ET).date()
    first = today - dt.timedelta(days=days)
    first += dt.timedelta(days=(7 - first.weekday()) % 7)  # roll forward to Monday
    found: list[dt.date] = []
    day = first
    while day <= today:
        found.append(day)
        day += dt.timedelta(days=7)
    return found
