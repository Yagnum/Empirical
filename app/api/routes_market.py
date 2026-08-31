"""Market data: is the market open, what exists, what does it cost.

    GET /market/clock            market open/closed + next open/close
    GET /market/assets?q=        symbol / company search
    GET /market/quotes/{symbol}  latest bid, ask and trade
    GET /market/bars/{symbol}    OHLCV candles for a chart

These are the only routes that read Alpaca's *market data* host rather than
the Broker API. They still require a signed-in user: the data is licensed to
us, not to the internet.

MONEY RULE (ADR-010): every price is a string. The market data API sends
prices as JSON numbers, so `alpaca._data_request` decodes them with a
`parse_float` hook that keeps the original text - no value in this file has
ever been a Python float. Sizes and volumes are counts, so they stay ints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query

import alpaca
import clerk_auth
import sessions

router = APIRouter(tags=["market"], dependencies=[Depends(clerk_auth.require_user_id)])

# A search that scans 14,000 assets should never be asked for all of them.
MAX_ASSET_RESULTS = 50
MAX_BARS = 1000


def _price(value) -> str:
    """A price as a STRING, exactly as Alpaca wrote it. Never float() this."""
    return "" if value is None else str(value)


def _count(value) -> int:
    """A share count / volume. These really are integers, so int() is safe."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@router.get("/market/clock")
def clock() -> dict:
    """Is the market open, and when does that next change?

    The frontend needs this to say "your order will queue until 9:30 AM"
    instead of leaving the user wondering why nothing filled.

    Under the dev weekend override (ADR-019) `is_open` is forced false and
    `simulated` says so: the whole app then behaves as it will on a real
    Saturday. Only this route's answer is faked - everything that records
    data (the sampler) reads Alpaca's clock directly and never sees this.
    """
    try:
        data = alpaca.get_clock()
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc
    simulated = sessions.weekend_override()
    return {
        "is_open": False if simulated else bool(data.get("is_open")),
        "next_open": str(data.get("next_open") or ""),
        "next_close": str(data.get("next_close") or ""),
        "timestamp": str(data.get("timestamp") or ""),
        "simulated": simulated,
    }


def _rank(asset: dict, needle: str) -> tuple | None:
    """Sort key for one asset against the query, or None if it does not match.

    Bands, best first:
      0  the symbol *is* the query          AAPL for "AAPL"
      1  the symbol starts with it          AAPU for "AAP"
      2  the company name starts a word with it   Apple Inc. for "apple"
      3  the name merely contains it        Maui Land & Pineapple for "apple"

    Band 3 exists because "pineapple" contains "apple": without it a search
    for "apple" put a pineapple farm above Apple Inc. (seen live). Tradable
    assets outrank untradable ones inside each band, because an untradable row
    is a dead end for the user; ties then break on the shorter symbol.
    """
    symbol = str(asset.get("symbol") or "").upper()
    name = str(asset.get("name") or "").upper()
    tradable = 0 if asset.get("tradable") else 1

    if symbol == needle:
        band = 0
    elif symbol.startswith(needle):
        band = 1
    elif name.startswith(needle) or f" {needle}" in name:
        band = 2
    elif needle in name:
        band = 3
    else:
        return None
    return (band, tradable, len(symbol), symbol)


@router.get("/market/assets")
def search_assets(
    q: str = Query("", description="Symbol prefix or part of a company name"),
    limit: int = Query(10, ge=1, le=MAX_ASSET_RESULTS),
) -> list[dict]:
    """Symbol lookup for the ticker search box.

    Alpaca's assets endpoint has no search parameter, so the match happens
    here over a cached copy of the active US equity list (see
    `alpaca.active_equity_assets`). An empty query returns an empty list
    rather than the first ten of fourteen thousand arbitrary tickers.
    """
    needle = q.strip().upper()
    if not needle:
        return []

    try:
        assets = alpaca.active_equity_assets()
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc

    scored = []
    for asset in assets:
        key = _rank(asset, needle)
        if key is not None:
            scored.append((key, asset))
    scored.sort(key=lambda pair: pair[0])

    return [
        {
            "symbol": str(asset.get("symbol") or ""),
            "name": str(asset.get("name") or ""),
            "exchange": str(asset.get("exchange") or ""),
            "tradable": bool(asset.get("tradable")),
            "fractionable": bool(asset.get("fractionable")),
        }
        for _, asset in scored[:limit]
    ]


@router.get("/market/quotes/{symbol}")
def quote(symbol: str = Path(..., description="Ticker, e.g. AAPL")) -> dict:
    """Latest bid/ask plus the last trade, in one call.

    Alpaca splits these across two endpoints because they are two different
    facts: the quote is what someone will trade at *now*, the trade is what
    someone actually paid. A buy preview needs both.

    Outside market hours the ask side is often 0 - there is nobody offering.
    """
    ticker = symbol.strip().upper()
    try:
        quote_data = alpaca.latest_quote(ticker)
    except alpaca.AlpacaError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="unknown_symbol") from exc
        raise alpaca.http_error(exc) from exc

    # A halted or thinly traded symbol can have a quote but no trade today;
    # that is missing data, not a missing symbol, so it must not 404.
    try:
        trade_data = alpaca.latest_trade(ticker)
    except alpaca.AlpacaError as exc:
        if exc.status_code != 404:
            raise alpaca.http_error(exc) from exc
        trade_data = {}

    return {
        "symbol": ticker,
        "bid": _price(quote_data.get("bp")),
        "ask": _price(quote_data.get("ap")),
        "bid_size": _count(quote_data.get("bs")),
        "ask_size": _count(quote_data.get("as")),
        "last": _price(trade_data.get("p")),
        "last_size": _count(trade_data.get("s")),
        "timestamp": str(quote_data.get("t") or trade_data.get("t") or ""),
    }


@router.get("/market/bars/{symbol}")
def bars(
    symbol: str = Path(..., description="Ticker, e.g. AAPL"),
    timeframe: str = Query("1Day", description="One of " + ", ".join(alpaca.BAR_TIMEFRAMES)),
    limit: int = Query(200, ge=1, le=MAX_BARS),
) -> list[dict]:
    """OHLCV candles, oldest first - the order every charting library wants."""
    if timeframe not in alpaca.BAR_TIMEFRAMES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid_timeframe: expected one of {', '.join(alpaca.BAR_TIMEFRAMES)}",
        )

    ticker = symbol.strip().upper()
    try:
        rows = alpaca.bars(ticker, timeframe, limit)
    except alpaca.AlpacaError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="unknown_symbol") from exc
        raise alpaca.http_error(exc) from exc

    return [
        {
            "t": str(bar.get("t") or ""),
            "o": _price(bar.get("o")),
            "h": _price(bar.get("h")),
            "l": _price(bar.get("l")),
            "c": _price(bar.get("c")),
            "v": _count(bar.get("v")),
        }
        for bar in rows
    ]


# ---------------------------------------------------------------------------
# The token that trades when the market does not (ADR-016, ADR-017)
# ---------------------------------------------------------------------------

import jupiter  # noqa: E402
import sampler  # noqa: E402
from decimal import Decimal, ROUND_HALF_UP  # noqa: E402

_GAP_PLACES = Decimal("0.001")


def gap_percent(token_price: Decimal, market_price: Decimal | None) -> str | None:
    """(token / share - 1) x 100 as a signed string to three places, or None.

    Decimal all the way (ADR-010). Signed on purpose: "+0.143" says the token
    trades *above* the share, and that direction is the whole story.
    """
    if market_price is None or market_price <= 0:
        return None
    gap = (token_price / market_price - Decimal("1")) * Decimal("100")
    return format(gap.quantize(_GAP_PLACES, rounding=ROUND_HALF_UP), "+f")


@router.get("/market/token/{symbol}")
def token_price(symbol: str = Path(..., min_length=1, max_length=16)) -> dict:
    """The tokenized twin of a listed share, priced right now on Jupiter.

    An xStock (NVDAx for NVDA) is one real share held in custody, mirrored as
    a Solana token that trades around the clock. While the market is open the
    two prices track closely; on a weekend the token is the only live price
    there is, and the distance between them at Monday's first execution is
    what the paper's reserve is sized against. This route shows that distance
    live, as `gap_pct`, beside both prices.

    404 `no_token` when no xStock mirrors this symbol (most stocks). The
    Alpaca side is best-effort - the token price is the point of the call, so
    a slow broker feed leaves `market_*` null rather than failing it.
    """
    underlying = symbol.upper()
    try:
        token = jupiter.xstock_for(underlying)
        quote = jupiter.prices([token["mint"]]).get(token["mint"]) if token else None
    except jupiter.JupiterError as exc:
        raise HTTPException(status_code=502, detail=f"jupiter_unreachable: {exc.message}") from exc
    if token is None:
        raise HTTPException(status_code=404, detail="no_token")
    usd_price = sampler._decimal((quote or {}).get("usdPrice"))
    if usd_price is None:
        raise HTTPException(status_code=502, detail="jupiter_unreachable: no price for the token")

    trades, market_open = sampler.market_side([underlying])
    trade = trades.get(underlying) or {}
    market_price = sampler._decimal(trade.get("p"))
    traded_at = sampler._moment(trade.get("t"))
    block_id = (quote or {}).get("blockId")

    return {
        "symbol": underlying,
        "token": token["symbol"],
        "name": token["name"],
        "mint": token["mint"],
        "usd_price": format(usd_price, "f"),
        "liquidity_usd": _price((quote or {}).get("liquidity")) or None,
        "price_change_24h": _price((quote or {}).get("priceChange24h")) or None,
        "block_id": block_id if isinstance(block_id, int) else None,
        "market_price": format(market_price, "f") if market_price is not None else None,
        "market_trade_at": traded_at.isoformat().replace("+00:00", "Z") if traded_at else None,
        "market_open": market_open,
        "gap_pct": gap_percent(usd_price, market_price),
    }
