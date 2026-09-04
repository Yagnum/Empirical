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

NO SENDS. `build_swap` (ADR-025) asks Jupiter to assemble a swap transaction
for the engine wallet; signing and simulating it is solana.py's job, and
sending it is nobody's - shadow mode stops there.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from decimal import Decimal
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


# ---------------------------------------------------------------------------
# Executable prices: the swap quote (docs/JUPITER-FLOW.md §3-4, ADR-019)
# ---------------------------------------------------------------------------
#
# price/v3 reports the LAST swap - what somebody else already paid. A trade
# needs the price offered to *you*, *now*, for *your size*: that is the quote.
# Direction is the bid/ask rule: quoting token->USDC prices a SELL (the bid),
# USDC->token prices a BUY (the ask). Amounts travel in base units - integers
# scaled by the token's declared decimals (USDC 6, most xStocks 8) - and the
# quote never places a trade: building or signing a transaction is a different
# endpoint this codebase does not call.

QUOTE_URL = "https://api.jup.ag/swap/v1/quote"
LITE_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6

_TEN = Decimal(10)


def to_base_units(amount: Decimal, decimals: int) -> int:
    """3.5 tokens with 8 decimals -> 350_000_000. Exact or ValueError."""
    scaled = amount * (_TEN**decimals)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{amount} does not fit in {decimals} decimals")
    return int(scaled)


def from_base_units(base_units: int | str, decimals: int) -> Decimal:
    """350_000_000 base units with 8 decimals -> Decimal('3.5')."""
    return Decimal(int(base_units)) / (_TEN**decimals)


def swap_quote(input_mint: str, output_mint: str, amount_base_units: int) -> dict:
    """GET swap/v1/quote - what `amount_base_units` of the input buys right now.

    Returns Jupiter's body: `outAmount` (base units of the output, a string),
    `priceImpactPct`, `routePlan`, and more. Read-only.
    """
    url = QUOTE_URL if settings.jup_api_key else LITE_QUOTE_URL
    return _get(
        url,
        {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_base_units),
            "slippageBps": "50",
        },
    )


def executable_price(token: dict, side: str, qty: Decimal) -> dict:
    """The effective USD price for trading `qty` of this xStock now.

    side "sell": quote qty tokens -> USDC. The USDC out per token is the bid.
    side "buy":  quote USDC -> tokens for roughly the right notional (sized
    from the last-swap price) and read USDC in per token out - the ask. The
    buy leg prices the trade; it does not promise that exact token amount.

    Returns {"price", "usd_amount", "token_amount", "price_impact_pct"};
    price = usd_amount / token_amount, all Decimal.
    """
    decimals = int(token["decimals"])
    mint = str(token["mint"])

    if side == "sell":
        body = swap_quote(mint, USDC_MINT, to_base_units(qty, decimals))
        usd = from_base_units(str(body["outAmount"]), USDC_DECIMALS)
        tokens = qty
    else:
        last = prices([mint]).get(mint) or {}
        approx = Decimal(str(last.get("usdPrice") or "0"))
        if approx <= 0:
            raise JupiterError("no last-swap price to size the buy quote from")
        notional = (qty * approx).quantize(Decimal("0.000001"))
        body = swap_quote(USDC_MINT, mint, to_base_units(notional, USDC_DECIMALS))
        usd = notional
        tokens = from_base_units(str(body["outAmount"]), decimals)

    if tokens <= 0 or usd <= 0:
        raise JupiterError("quote came back with a zero amount")
    return {
        "price": usd / tokens,
        "usd_amount": usd,
        "token_amount": tokens,
        "price_impact_pct": str(body.get("priceImpactPct") or "0"),
    }


SWAP_URL = "https://api.jup.ag/swap/v1/swap"
LITE_SWAP_URL = "https://lite-api.jup.ag/swap/v1/swap"


def build_swap(quote: dict, user_pubkey: str) -> dict:
    """POST swap/v1/swap - turn a quote into an unsigned transaction.

    Jupiter assembles the instructions (create the token account if the
    wallet lacks one, wrap SOL if needed, the swap itself), sets a compute
    budget, proposes a priority fee, and runs its own simulation - the
    result rides back as `simulationError` when it fails, which on an empty
    wallet it does. Returns the body: `swapTransaction` (base64),
    `computeUnitLimit`, `prioritizationFeeLamports`, `lastValidBlockHeight`,
    `simulationError`. Nothing is sent.

    The quote was decoded with numbers as text (ADR-010); the one float
    Jupiter insists on getting back as a float is restored here.
    """
    payload = dict(quote)
    if isinstance(payload.get("timeTaken"), str):
        try:
            payload["timeTaken"] = float(payload["timeTaken"])
        except ValueError:
            payload.pop("timeTaken", None)
    body = {
        "quoteResponse": payload,
        "userPublicKey": user_pubkey,
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": {
            "priorityLevelWithMaxLamports": {"maxLamports": 1_000_000, "priorityLevel": "medium"}
        },
    }
    url = SWAP_URL if settings.jup_api_key else LITE_SWAP_URL
    headers = {"accept": "application/json", "content-type": "application/json"}
    if settings.jup_api_key and url.startswith("https://api.jup.ag"):
        headers["x-api-key"] = settings.jup_api_key
    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.post(url, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise JupiterError("jupiter swap builder timed out") from exc
    except httpx.HTTPError as exc:
        raise JupiterError(f"jupiter swap builder unreachable: {exc}") from exc
    if response.status_code != 200:
        raise JupiterError(f"jupiter swap builder HTTP {response.status_code}: {response.text[:200]}", response.status_code)
    result = response.json()
    if not isinstance(result, dict) or not result.get("swapTransaction"):
        raise JupiterError("jupiter swap builder returned no transaction")
    return result


# The fixed notional the sampler prices the spread at (ADR-020). One size
# for every token and every run, so the series is comparable across both.
SPREAD_QUOTE_USD = Decimal("1000")

# Pause between a spread's two legs, for the same rate limit the sampler's
# per-token delay respects: together they keep the calls near 1/second.
SPREAD_LEG_DELAY_SECONDS = 0.6


def spread_quote(token: dict, last_price: Decimal) -> dict:
    """The executable bid and ask for ~$1,000 of this xStock, right now (RQ2).

    Two quotes, one in each direction:
      ask  $1,000 of USDC -> tokens: what a buyer pays per token
      bid  ~$1,000 of tokens -> USDC: what a seller receives per token
    (`last_price` sizes the bid leg's token amount; the *result* never
    depends on it - the quoted amounts do the pricing.)

    Returns {"bid", "ask", "bid_impact_pct", "ask_impact_pct",
    "quote_size_usd"}, Decimals throughout. The ask-minus-bid distance is
    how the liquidity providers charge for weekend risk - the paper's RQ2.
    """
    decimals = int(token["decimals"])
    mint = str(token["mint"])
    if last_price <= 0:
        raise JupiterError("no last price to size the spread quote from")

    ask_body = swap_quote(USDC_MINT, mint, to_base_units(SPREAD_QUOTE_USD, USDC_DECIMALS))
    tokens_out = from_base_units(str(ask_body["outAmount"]), decimals)
    if tokens_out <= 0:
        raise JupiterError("ask quote returned zero tokens")

    if SPREAD_LEG_DELAY_SECONDS:
        time.sleep(SPREAD_LEG_DELAY_SECONDS)

    qty = (SPREAD_QUOTE_USD / last_price).quantize(Decimal(1).scaleb(-decimals))
    if qty <= 0:
        raise JupiterError("bid quote size rounds to zero tokens")
    bid_body = swap_quote(mint, USDC_MINT, to_base_units(qty, decimals))
    usd_out = from_base_units(str(bid_body["outAmount"]), USDC_DECIMALS)
    if usd_out <= 0:
        raise JupiterError("bid quote returned zero USDC")

    return {
        "bid": usd_out / qty,
        "ask": SPREAD_QUOTE_USD / tokens_out,
        "bid_impact_pct": Decimal(str(bid_body.get("priceImpactPct") or "0")),
        "ask_impact_pct": Decimal(str(ask_body.get("priceImpactPct") or "0")),
        "quote_size_usd": SPREAD_QUOTE_USD,
    }


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
