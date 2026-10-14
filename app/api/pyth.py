"""Thin client for Pyth's Hermes price service (docs/RESEARCH-COLLECTION.md, series C).

One endpoint, read-only:

    v2/updates/price/latest?ids[]=<feed>&ids[]=...&parsed=true
        the latest price Pyth publishes for each feed: an integer `price`,
        an integer `conf` (Pyth's uncertainty band), an exponent `expo`
        (dollars = price x 10^expo) and `publish_time` (unix seconds).

WHY AN ORACLE AT ALL. A lending market or a perp that holds a tokenized
stock must value it, and it asks an oracle. Pyth's regular US-equity feeds
follow the exchange schedule ("0930-1600" Mon-Fri, holidays closed): from
Friday 4 PM to Monday 9:30 AM the last published price simply stays. The
token keeps trading on Jupiter. Recording both, side by side, measures how
far the frozen oracle drifts from the live token - the risk an oracle-marked
protocol carries all weekend.

THE KEY (verified 2026-10-13). Since the Pyth Core upgrade of 2026-08-26
every Hermes price endpoint - hermes.pyth.network and the new
pyth.dourolabs.app/hermes alike - answers 401 "unauthorized" without an
API key, sent as `Authorization: Bearer <key>`. A key comes from Pyth
Terminal (pythdata.app; free trial, paid plans after). The feed *list*
(v2/price_feeds) is still public, which is how the ids below were found.
No key configured = `latest()` raises PythUnavailable and the sampler logs
one line and moves on.

Also checked and rejected: Pyth's on-chain "sponsored" price accounts on
Solana (readable with no key through any RPC) - the equity ones stopped
updating at 2026-08-26 15:54 UTC, the upgrade moment, while BTC's still
moves. They are a record of the cut-over, not a live source.

NUMBERS ARRIVE AS STRINGS (ADR-010): `parse_float=str`, as in jupiter.py.
Pyth already sends price and conf as decimal strings; expo is an int.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from config import settings

# Feed ids, checked 2026-10-13 against two Pyth sources that agree:
#   hermes.pyth.network/v2/price_feeds?query=<SYM>&asset_type=equity
#   benchmarks.pyth.network/v1/price_feeds/?query=<SYM>&asset_type=equity
# For SPY and NVDA a third: the Pyth receiver account on Solana derived from
# the id holds that same id and a plausible last price (SPY 765.48, NVDA
# 211.02 at 2026-08-26).
#
# 'regular'     Equity.US.<SYM>/USD - Pyth's description "<COMPANY> / US DOLLAR".
# 'index_24_7'  Equity.Index.<SYM>/USD - Pyth's description "PYTH PRICE IN USD
#               FOR <SYM> 24/7". Its published schedule string still reads
#               0930-1600; whether it really moves on a Saturday is exactly
#               what the recorded publish_time will show.
FEEDS: tuple[dict, ...] = (
    {"symbol": "AAPL", "kind": "regular", "feed_symbol": "Equity.US.AAPL/USD", "id": "49f6b65cb1de6b10eaf75e7c03ca029c306d0357e91b5311b175084a5ad55688"},
    {"symbol": "AAPL", "kind": "index_24_7", "feed_symbol": "Equity.Index.AAPL/USD", "id": "aaba35e6f33fb973bb2201d48a79ae24795affa6ba8bd50a93dcaf7da0030f36"},
    {"symbol": "CRCL", "kind": "regular", "feed_symbol": "Equity.US.CRCL/USD", "id": "92b8527aabe59ea2b12230f7b532769b133ffb118dfbd48ff676f14b273f1365"},
    {"symbol": "CRCL", "kind": "index_24_7", "feed_symbol": "Equity.Index.CRCL/USD", "id": "59751961c9aa1943ece2d3e9060070d8d665a99a28642e4b10fcae972c10b833"},
    {"symbol": "GOOGL", "kind": "regular", "feed_symbol": "Equity.US.GOOGL/USD", "id": "5a48c03e9b9cb337801073ed9d166817473697efff0d138874e0f6a33d6d5aa6"},
    {"symbol": "GOOGL", "kind": "index_24_7", "feed_symbol": "Equity.Index.GOOGL/USD", "id": "ad519718d387de4f0d7d29ea16a3730ce42e49c59fef6fba6fc9bac477645f6f"},
    {"symbol": "META", "kind": "regular", "feed_symbol": "Equity.US.META/USD", "id": "78a3e3b8e676a8f73c439f5d749737034b139bbbe899ba5775216fba596607fe"},
    {"symbol": "META", "kind": "index_24_7", "feed_symbol": "Equity.Index.META/USD", "id": "2cc0c022f7f37920485a5947f3cea8633783b6cb7fff6d94ee52f48687b7783d"},
    {"symbol": "NVDA", "kind": "regular", "feed_symbol": "Equity.US.NVDA/USD", "id": "b1073854ed24cbc755dc527418f52b7d271f6cc967bbf8d8129112b18860a593"},
    {"symbol": "NVDA", "kind": "index_24_7", "feed_symbol": "Equity.Index.NVDA/USD", "id": "a470c4ac46f44b547b2cba52338f311fb642b79375ce5f0cfd5cb5b99227b852"},
    {"symbol": "QQQ", "kind": "regular", "feed_symbol": "Equity.US.QQQ/USD", "id": "9695e2b96ea7b3859da9ed25b7a46a920a776e2fdae19a7bcfdf2b219230452d"},
    {"symbol": "QQQ", "kind": "index_24_7", "feed_symbol": "Equity.Index.QQQ/USD", "id": "6d595efb30db0e0139f254eb40985c8695e7ed7e5856287cb5084d2d7794b7eb"},
    {"symbol": "SPY", "kind": "regular", "feed_symbol": "Equity.US.SPY/USD", "id": "19e09bb805456ada3979a7d1cbb4b6d63babc3a0f8e8a9509f68afa5c4c11cd5"},
    {"symbol": "SPY", "kind": "index_24_7", "feed_symbol": "Equity.Index.SPY/USD", "id": "f32c3fbdd20b846bb53395bf175c42955e00b1bffb5a778bb624982b318f5461"},
    {"symbol": "TSLA", "kind": "regular", "feed_symbol": "Equity.US.TSLA/USD", "id": "16dad506d7db8da01c87581c87ca897a012a153557d4d578c3b9c9e1bc0632f1"},
    {"symbol": "TSLA", "kind": "index_24_7", "feed_symbol": "Equity.Index.TSLA/USD", "id": "e6da44bff5b8b06897a3739dd331b440d6662595bb862e37046892c568ae3fc0"},
)


class PythError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class PythUnavailable(PythError):
    """No API key configured: the oracle record is skipped, not failed."""


def _normalise(feed_id: str) -> str:
    return feed_id.lower().removeprefix("0x")


def latest(feed_ids: list[str]) -> dict[str, dict]:
    """{feed id -> {price, conf, expo, publish_time}} for these feeds, one call.

    `price` and `conf` are the raw integers as Decimal, `expo` an int,
    `publish_time` an aware UTC datetime. Feeds Pyth did not return are absent.
    """
    if not settings.pyth_api_key:
        raise PythUnavailable("PYTH_API_KEY is not set; Hermes needs a key since 2026-08-26")
    ids = [_normalise(feed_id) for feed_id in dict.fromkeys(feed_ids) if feed_id]
    if not ids:
        return {}
    url = settings.pyth_hermes_url.rstrip("/") + "/v2/updates/price/latest"
    params: list[tuple[str, str]] = [("ids[]", feed_id) for feed_id in ids]
    params += [("parsed", "true"), ("encoding", "hex")]
    headers = {"accept": "application/json", "authorization": f"Bearer {settings.pyth_api_key}"}
    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.get(url, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise PythError("timed out calling Hermes") from exc
    except httpx.HTTPError as exc:
        raise PythError(f"network error calling Hermes: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise PythError(response.text[:300], status_code=response.status_code)
    body: Any = response.json(parse_float=str)
    result: dict[str, dict] = {}
    for entry in (body or {}).get("parsed") or []:
        parsed = _parse(entry)
        if parsed is not None:
            result[parsed["id"]] = parsed
    return result


def _parse(entry: Any) -> dict | None:
    if not isinstance(entry, dict):
        return None
    quote = entry.get("price") or {}
    try:
        price = Decimal(str(quote["price"]))
        expo = int(quote["expo"])
        published = datetime.fromtimestamp(int(quote["publish_time"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None
    try:
        conf = Decimal(str(quote.get("conf"))) if quote.get("conf") not in (None, "") else None
    except InvalidOperation:
        conf = None
    return {
        "id": _normalise(str(entry.get("id", ""))),
        "price": price,
        "conf": conf,
        "expo": expo,
        "publish_time": published,
    }


def to_usd(raw: Decimal, expo: int) -> Decimal:
    """Pyth integer x 10^expo, exactly: 21101503 with expo -5 -> 211.01503."""
    return raw.scaleb(expo)
