"""Thin client for Jupiter's public data APIs (ADR-016).

Two endpoints, both read-only:

    tokens/v2/search?query=xStock   the tokenized equities Jupiter knows, with
                                    their mint addresses (a mint is a token's
                                    identity on Solana, the way a ticker is a
                                    stock's on an exchange)
    price/v3?ids=<mints>            the last-swapped USD price of each token

Prices are the reason this module exists. An xStock (NVDAx, AAPLx, ...) is
one real share held in custody, mirrored as a Solana token that trades on
Jupiter around the clock - including the weekend, when the share itself
cannot trade. The gap between the token's weekend price and Monday's real
open is what the paper's Execution Reconciliation Reserve is sized against,
and this client is how we observe it.

NUMBERS ARRIVE AS STRINGS (ADR-010). Jupiter sends prices as bare JSON
numbers. They are decoded with `parse_float=str`, so "220.23925284547732"
reaches the ledger as exactly those digits and never passes through a
binary float.

NO SWAPS. This client never signs a transaction and never touches a wallet.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

import httpx

from config import settings

PRICE_URL = "https://api.jup.ag/price/v3"
LITE_PRICE_URL = "https://lite-api.jup.ag/price/v3"
SEARCH_URL = "https://lite-api.jup.ag/tokens/v2/search"

# Documented ceiling for one price/v3 call.
MAX_IDS_PER_CALL = 50


class JupiterError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _get(url: str, params: dict) -> Any:
    """One GET, JSON numbers kept as text. The API key rides only to api.jup.ag."""
    headers = {"accept": "application/json"}
    if settings.jup_api_key and url.startswith("https://api.jup.ag"):
        headers["x-api-key"] = settings.jup_api_key
    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.get(url, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise JupiterError(f"timed out calling {url}") from exc
    except httpx.HTTPError as exc:
        raise JupiterError(f"network error calling {url}: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise JupiterError(response.text[:300], status_code=response.status_code)
    return response.json(parse_float=str)


def is_xstock(token: dict) -> bool:
    """Backed's xStocks are named '<Company> xStock' with a trailing-x symbol."""
    name = str(token.get("name", ""))
    symbol = str(token.get("symbol", ""))
    return name.endswith("xStock") and symbol.endswith("x")


# Tokens whose company has no listed share. Stripping the x would hit an
# unrelated ticker (SPCX is an ETF, not SpaceX), so these map to nothing.
NO_UNDERLYING = {"SPCXx"}


def underlying_of(symbol: str) -> str | None:
    """'NVDAx' -> 'NVDA'; None for a token with no listed share behind it."""
    if symbol in NO_UNDERLYING:
        return None
    return symbol[:-1] if symbol.endswith("x") else symbol


def list_xstocks() -> list[dict]:
    """Every xStock Jupiter's search returns, normalised and sorted by symbol.

    Each entry: {symbol, underlying, mint, name, decimals}. Fetched live on
    every call rather than checked in, because the list grows as Backed
    issues new tokens and a stale list would silently stop sampling them.
    """
    body = _get(SEARCH_URL, {"query": "xStock"})
    tokens = body if isinstance(body, list) else []
    found = [
        {
            "symbol": str(token["symbol"]),
            "underlying": underlying_of(str(token["symbol"])),
            "mint": str(token["id"]),
            "name": str(token.get("name", "")),
            "decimals": int(token.get("decimals") or 0),
        }
        for token in tokens
        if is_xstock(token) and token.get("id")
    ]
    return sorted(found, key=lambda entry: entry["symbol"])


# The xStocks list changes on the order of weeks; the trade page asks for it
# on every load. One process-wide copy, refreshed at most every 15 minutes,
# the same pattern as alpaca.active_equity_assets.
_XSTOCKS_TTL_SECONDS = 900
_xstocks_cache: tuple[float, list[dict]] | None = None


def cached_xstocks(*, force_refresh: bool = False) -> list[dict]:
    """`list_xstocks()`, memoised for 15 minutes."""
    global _xstocks_cache
    now = time.monotonic()
    if not force_refresh and _xstocks_cache and now - _xstocks_cache[0] < _XSTOCKS_TTL_SECONDS:
        return _xstocks_cache[1]
    tokens = list_xstocks()
    _xstocks_cache = (now, tokens)
    return tokens


def xstock_for(underlying: str) -> dict | None:
    """The xStock that mirrors this listed share ('NVDA' -> the NVDAx entry), or None."""
    wanted = underlying.upper()
    for token in cached_xstocks():
        if token["underlying"] == wanted:
            return token
    return None


def prices(mints: Iterable[str]) -> dict[str, dict]:
    """{mint -> price/v3 entry} for these mints, chunked to the API's ceiling.

    An entry looks like {"usdPrice": "220.24", "liquidity": "1623912.59",
    "blockId": 442385375, "priceChange24h": "-3.90", ...} - the string fields
    are the parse_float=str decoding at work.
    """
    ids = [mint for mint in dict.fromkeys(mints) if mint]
    url = PRICE_URL if settings.jup_api_key else LITE_PRICE_URL
    result: dict[str, dict] = {}
    for start in range(0, len(ids), MAX_IDS_PER_CALL):
        chunk = ids[start : start + MAX_IDS_PER_CALL]
        body = _get(url, {"ids": ",".join(chunk)})
        if isinstance(body, dict):
            result.update({mint: entry for mint, entry in body.items() if isinstance(entry, dict)})
    return result
