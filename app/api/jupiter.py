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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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
            "issuer": "xstocks",
        }
        for token in tokens
        if is_xstock(token) and token.get("id")
    ]
    return sorted(found, key=lambda entry: entry["symbol"])


# ---------------------------------------------------------------------------
# Ondo Global Markets tokens (docs/RESEARCH-COLLECTION.md, series A)
# ---------------------------------------------------------------------------
#
# Ondo's tokenized stocks mint and redeem 24/7 against Ondo itself; xStocks
# do not. Sampling both side by side tests whether that primary-market
# access keeps the weekend price closer to fair.
#
# A FIXED, VERIFIED LIST - deliberately not a live search. Jupiter's search
# for "NVDAon" returns one real token and a dozen look-alikes, and an
# unverified mint is worse than no data. Each address below was checked on
# 2026-10-13 against three sources that agree:
#   1. Ondo's own token sheet, linked from docs.ondo.finance/addresses
#      ("Solana Deployed Address" column);
#   2. Jupiter's token API (tags 'ondo' + 'verified', name "(Ondo Tokenized)");
#   3. the mint account on Solana mainnet: Token-2022 program, 9 decimals,
#      on-chain metadata symbol matching, mint authority
#      9foMHsSDq7nMg4WPusSz9eY7tyxyukqborA8GyU5cUxD shared by all eight.
# All are Token-2022 with the scaled-UI-amount extension (see ui_multiplier).
ONDO_TOKENS: tuple[dict, ...] = (
    {"symbol": "AAPLon", "underlying": "AAPL", "mint": "123mYEnRLM2LLYsJW3K6oyYh8uP1fngj732iG638ondo", "name": "Apple (Ondo Tokenized)"},
    {"symbol": "CRCLon", "underlying": "CRCL", "mint": "6xHEyem9hmkGtVq6XGCiQUGpPsHBaoYuYdFNZa5ondo", "name": "Circle Internet Group (Ondo Tokenized)"},
    {"symbol": "GOOGLon", "underlying": "GOOGL", "mint": "bbahNA5vT9WJeYft8tALrH1LXWffjwqVoUbqYa1ondo", "name": "Alphabet Class A (Ondo Tokenized)"},
    {"symbol": "METAon", "underlying": "META", "mint": "fDxs5y12E7x7jBwCKBXGqt71uJmCWsAQ3Srkte6ondo", "name": "Meta Platforms (Ondo Tokenized)"},
    {"symbol": "NVDAon", "underlying": "NVDA", "mint": "gEGtLTPNQ7jcg25zTetkbmF7teoDLcrfTnQfmn2ondo", "name": "NVIDIA (Ondo Tokenized)"},
    {"symbol": "QQQon", "underlying": "QQQ", "mint": "HrYNm6jTQ71LoFphjVKBTdAE4uja7WsmLG8VxB8ondo", "name": "Invesco QQQ (Ondo Tokenized)"},
    {"symbol": "SPYon", "underlying": "SPY", "mint": "k18WJUULWheRkSpSquYGdNNmtuE2Vbw1hpuUi92ondo", "name": "SPDR S&P 500 ETF (Ondo Tokenized)"},
    {"symbol": "TSLAon", "underlying": "TSLA", "mint": "KeGv7bsfR4MheC1CkmnAVceoApjrkvBhHYjWb67ondo", "name": "Tesla (Ondo Tokenized)"},
)
ONDO_DECIMALS = 9


def list_ondo() -> list[dict]:
    """The verified Ondo tokens, in the same shape as `list_xstocks()`. No HTTP."""
    return [{**token, "decimals": ONDO_DECIMALS, "issuer": "ondo"} for token in ONDO_TOKENS]


def ui_multiplier(entry: dict, now: datetime | None = None) -> Decimal | None:
    """The scaled-UI multiplier in force, from a price/v3 entry; None if absent.

    Token-2022's scaled-UI-amount extension lets an issuer pay a dividend by
    raising a multiplier instead of minting: shares = raw tokens x
    multiplier. Both xStocks and Ondo use it. price/v3 reports
    `scaledUiConfig` with the current `multiplier` and a scheduled
    `newMultiplier` that takes over at `newMultiplierEffectiveAt`; once that
    moment has passed, the new one is in force (checked live: Jupiter's
    usdPricePrescaled / usdPrice equals newMultiplier after the date).
    """
    config = entry.get("scaledUiConfig") if isinstance(entry, dict) else None
    if not isinstance(config, dict):
        return None
    current = config.get("multiplier")
    upcoming = config.get("newMultiplier")
    effective_at = str(config.get("newMultiplierEffectiveAt") or "")
    chosen = current
    if upcoming not in (None, "") and effective_at:
        try:
            moment = datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
        except ValueError:
            moment = None
        if moment is not None and moment <= (now or datetime.now(timezone.utc)):
            chosen = upcoming
    try:
        value = Decimal(str(chosen))
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


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


def executable_price(
    token: dict, side: str, qty: Decimal, *, size_price: Decimal | None = None
) -> dict:
    """The effective USD price for trading `qty` of this xStock now.

    side "sell": quote qty tokens -> USDC. The USDC out per token is the bid.
    side "buy":  quote USDC -> tokens for roughly the right notional (sized
    from the last-swap price) and read USDC in per token out - the ask. The
    buy leg prices the trade; it does not promise that exact token amount.
    `size_price`, when given, sizes the buy leg instead of the last-swap
    price, which saves the price/v3 call (the open's second quote uses the
    first quote's price - see weekend._capture_open_context).

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
        if size_price is not None:
            approx = size_price
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


def _route_labels(body: dict) -> str | None:
    labels = [
        str((step.get("swapInfo") or {}).get("label") or "?")
        for step in body.get("routePlan") or []
        if isinstance(step, dict)
    ]
    return ">".join(labels)[:200] or None


def ladder_quote(
    token: dict,
    side: str,
    size_usd: Decimal,
    share_price: Decimal,
    multiplier: Decimal | None,
) -> dict:
    """One rung of the depth ladder: buy or sell ~`size_usd` of this token now.

    side "buy"  USDC -> token. `size_usd` of USDC in; price = USDC / shares out.
    side "sell" token -> USDC. ~`size_usd` worth of tokens in (sized from
                `share_price`, the last swap per share); price = USDC out / shares in.

    Shares are raw tokens x `multiplier` (the scaled-UI amount, None = 1), so
    `price_usd` is per share and an xStock compares straight to its Ondo twin.
    Returns {in_amount, out_amount (base units, Decimal), share_amount,
    usd_amount, price_usd, price_impact_pct, route}. Raises JupiterError
    (status_code 429 when rate-limited) or ValueError.
    """
    decimals = int(token["decimals"])
    mint = str(token["mint"])
    scale = multiplier if multiplier and multiplier > 0 else Decimal(1)

    if side == "buy":
        usd_in = size_usd.quantize(Decimal("0.000001"))
        in_amount = to_base_units(usd_in, USDC_DECIMALS)
        body = swap_quote(USDC_MINT, mint, in_amount)
        out_amount = int(str(body["outAmount"]))
        shares = from_base_units(out_amount, decimals) * scale
        usd = usd_in
    elif side == "sell":
        if share_price <= 0:
            raise JupiterError("no last price to size the sell rung from")
        raw_qty = (size_usd / (share_price * scale)).quantize(Decimal(1).scaleb(-decimals))
        if raw_qty <= 0:
            raise JupiterError("sell rung rounds to zero tokens")
        in_amount = to_base_units(raw_qty, decimals)
        body = swap_quote(mint, USDC_MINT, in_amount)
        out_amount = int(str(body["outAmount"]))
        shares = raw_qty * scale
        usd = from_base_units(out_amount, USDC_DECIMALS)
    else:
        raise ValueError(f"side must be 'buy' or 'sell', not {side!r}")

    if shares <= 0 or usd <= 0:
        raise JupiterError("quote came back with a zero amount")
    return {
        "in_amount": Decimal(in_amount),
        "out_amount": Decimal(out_amount),
        "share_amount": shares,
        "usd_amount": usd,
        "price_usd": usd / shares,
        "price_impact_pct": Decimal(str(body.get("priceImpactPct") or "0")),
        "route": _route_labels(body),
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
