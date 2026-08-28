"""Thin client for GeckoTerminal's public API (ADR-016): the token's past.

Jupiter tells us what a token trades at *now*. For sigma_gap we need what it
traded at on every weekend we did not sample, and GeckoTerminal is the one
free source that keeps that: OHLCV candles per liquidity pool, hourly, for
the last 180 days. Two endpoints, both read-only, no key:

    networks/solana/tokens/{mint}/pools          the pools a token trades in,
                                                 with their USD depth
    networks/solana/pools/{pool}/ohlcv/{tf}      candles, newest first, paged
                                                 backwards with before_timestamp

THE 180-DAY WALL. The public tier refuses any page that would reach past
180 days with HTTP 401 and a message saying so. That is the *end of history*,
not an error, and it is raised as `HistoryLimitReached` (a subclass of
`GeckoTerminalError`) so a pager can stop cleanly while every other 4xx/5xx
still fails loudly.

RATE LIMIT. About 30 calls a minute. Every call sleeps `CALL_INTERVAL_SECONDS`
first (2.1 s keeps us just under), and a 429 is retried once after a longer
pause. A full backfill is a few hundred calls; slow and polite beats banned.

NUMBERS ARRIVE AS STRINGS (ADR-010): `parse_float=str`, as in jupiter.py.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from config import settings

BASE_URL = "https://api.geckoterminal.com/api/v2"
NETWORK = "solana"

# Candles per page the public tier serves; ~42 days of hourly candles.
PAGE_LIMIT = 1000
# How far back the public tier will go, in days.
HISTORY_DAYS = 180

CALL_INTERVAL_SECONDS = 2.1
RATE_LIMIT_RETRY_SECONDS = 15.0

TIMEFRAMES = ("hour", "day")


class GeckoTerminalError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class HistoryLimitReached(GeckoTerminalError):
    """The page asked for lies beyond the 180 days the public tier serves."""


# Set to time.sleep in production; tests replace it so they run instantly.
_sleep = time.sleep


def _is_history_limit(response: httpx.Response) -> bool:
    if response.status_code != 401:
        return False
    text = response.text.lower()
    return "180 days" in text or "past 180" in text


def _get(path: str, params: dict | None = None) -> Any:
    """One GET with the rate-limit pause, one retry on 429, numbers as text."""
    url = BASE_URL + path
    headers = {"accept": "application/json"}
    for attempt in (1, 2):
        _sleep(CALL_INTERVAL_SECONDS)
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds) as client:
                response = client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise GeckoTerminalError(f"timed out calling {path}") from exc
        except httpx.HTTPError as exc:
            raise GeckoTerminalError(f"network error calling {path}: {type(exc).__name__}") from exc
        if response.status_code == 429 and attempt == 1:
            _sleep(RATE_LIMIT_RETRY_SECONDS)
            continue
        break
    if _is_history_limit(response):
        raise HistoryLimitReached(response.text[:300], status_code=401)
    if response.status_code >= 400:
        raise GeckoTerminalError(response.text[:300], status_code=response.status_code)
    return response.json(parse_float=str)


def _pool_address(pool_id: str) -> str:
    """'solana_49iMatQ...' -> '49iMatQ...'."""
    prefix = f"{NETWORK}_"
    return pool_id[len(prefix) :] if pool_id.startswith(prefix) else pool_id


def pools(mint: str) -> list[dict]:
    """Every pool for a token, normalised: {address, name, reserve_usd, created_at}."""
    body = _get(f"/networks/{NETWORK}/tokens/{mint}/pools", {"page": 1})
    found: list[dict] = []
    for entry in (body or {}).get("data") or []:
        attributes = entry.get("attributes") or {}
        found.append(
            {
                "address": _pool_address(str(entry.get("id", ""))),
                "name": str(attributes.get("name", "")),
                "reserve_usd": str(attributes.get("reserve_in_usd") or "0"),
                "created_at": attributes.get("pool_created_at"),
            }
        )
    return found


def _reserve(pool: dict) -> float:
    # Ranking only - never stored, never money we account for. A float is
    # fine to sort by depth; it is the candle prices that must stay exact.
    try:
        return float(pool["reserve_usd"])
    except (TypeError, ValueError):
        return 0.0


def choose_pool(candidates: list[dict]) -> dict | None:
    """The deepest USDC pool, else the deepest pool of any kind, else None."""
    if not candidates:
        return None
    usdc = [pool for pool in candidates if "USDC" in pool["name"].upper()]
    return max(usdc or candidates, key=_reserve)


def deepest_usdc_pool(mint: str) -> dict | None:
    """The pool whose candles should stand for this token's price."""
    return choose_pool(pools(mint))


def ohlcv(pool: str, timeframe: str, before_timestamp: int | None = None) -> list[list]:
    """One page of candles, newest first: [[ts, o, h, l, c, volume_usd], ...].

    `before_timestamp` (unix seconds) pages backwards: pass the oldest `ts`
    of the previous page to get the page before it. Raises HistoryLimitReached
    at the 180-day wall.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {TIMEFRAMES}, not {timeframe!r}")
    params: dict[str, Any] = {"limit": PAGE_LIMIT}
    if before_timestamp is not None:
        params["before_timestamp"] = int(before_timestamp)
    body = _get(f"/networks/{NETWORK}/pools/{pool}/ohlcv/{timeframe}", params)
    attributes = ((body or {}).get("data") or {}).get("attributes") or {}
    rows = attributes.get("ohlcv_list") or []
    return [row for row in rows if isinstance(row, list) and len(row) >= 5]
