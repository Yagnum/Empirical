"""Sizing the Execution Reconciliation Reserve (paper §6d, ADR-018).

The formula is the paper's:

    reserve = qty * p_open * sigma_gap * z + fees

with two measured inputs instead of assumed ones:

    sigma_gap   per symbol - how much this share's weekend gaps move
                (research_params.json, the larger of two measurements)
    z           one pooled multiplier - how heavy the tails are across
                all symbols (the empirical 99th percentile, ~3.78, not
                the normal table's 2.326; the gaps are not bell-shaped)

Money is Decimal end to end (ADR-010). The reserve rounds UP to the cent:
a reserve is a promise of cover, and rounding a promise down breaks it by
a fraction of a cent, which is still broken.
"""

from __future__ import annotations

import json
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

PARAMS_PATH = Path(__file__).with_name("research_params.json")

_CENT = Decimal("0.01")

_params_cache: dict | None = None


def params() -> dict:
    """research_params.json, loaded once per process."""
    global _params_cache
    if _params_cache is None:
        _params_cache = json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
    return _params_cache


def sigma_for(symbol: str) -> tuple[Decimal, str]:
    """(sigma_gap, where it came from) for one underlying.

    A symbol we have measured gets its own sigma; one we have not falls back
    to the pooled figure, which is wider than most single names - the
    conservative direction for an unknown.
    """
    entry = params()["sigma"].get(symbol.upper())
    if entry is not None:
        return Decimal(entry["used"]), "measured"
    return Decimal(params()["pooled_sigma"]), "pooled_fallback"


def compute(symbol: str, qty: Decimal, p_open: Decimal) -> dict:
    """The reserve for one weekend trade, with every input it used.

    Returned Decimals are exact; the caller formats them as strings at the
    boundary. `reserve` includes fees; `reserve_pct` is reserve / notional,
    the "capital drag" figure the research reports.
    """
    sigma, sigma_source = sigma_for(symbol)
    z = Decimal(params()["z"])
    fees = Decimal(params()["fees"])
    notional = qty * p_open
    reserve = (notional * sigma * z + fees).quantize(_CENT, rounding=ROUND_CEILING)
    return {
        "design": "pass_through",
        "sigma": sigma,
        "sigma_source": sigma_source,
        "z": z,
        "fees": fees,
        "notional": notional,
        "reserve": reserve,
        "reserve_pct": (reserve / notional * Decimal("100")) if notional else Decimal("0"),
        "params_generated_at": str(params()["generated_at"]),
    }


# ---------------------------------------------------------------------------
# v2, the locked price (ADR-033)
# ---------------------------------------------------------------------------
#
# The trader keeps the weekend price. Yagnum hedges the same moment with the
# token on Jupiter (customer sells -> Yagnum sells the token; Monday it sells
# the real shares and buys the token back), so the weekend move cancels
# between the legs. The ERR is the paper's (§6b): the trader posts it, and on
# Monday it comes back as ERR + the hedge's net P/L - the leftover profit
# refunded, a leftover loss deducted, anything beyond the ERR cascading.
#
# Because only the hedge's leftover is at risk, sigma here is the hedged
# leftover's, measured, not the share's weekend gap (RQ5,
# notebooks/analysis/rq5_hedge_cost.py, 2026-10-31, 108 settled trades with
# both hedge legs recorded): the hedge cut the per-trade standard deviation
# from 4.06% to 0.98% of notional. z stays the pooled measured multiplier.

HEDGED_SIGMA = Decimal("0.0098")

# The proposal's Fees_est. Gas is flat, about $0.34 for the two legs (mostly a
# refundable token-account deposit), and a percentage ERR cannot cover it on a
# very small trade: every breach in the data was a trade of about $10 or less.
LOCKED_FEES_EST = Decimal("0.40")


def compute_locked(symbol: str, qty: Decimal, p_open: Decimal) -> dict:
    """The ERR for a locked-price trade: the paper's formula (§6d) with the
    hedged leftover's sigma in place of the share's weekend gap."""
    base = compute(symbol, qty, p_open)
    notional = base["notional"]
    fees = max(base["fees"], LOCKED_FEES_EST)
    reserve = (notional * HEDGED_SIGMA * base["z"] + fees).quantize(_CENT, rounding=ROUND_CEILING)
    return {
        **base,
        "design": "locked",
        "sigma": HEDGED_SIGMA,
        "sigma_source": "hedged_leftover",
        "fees": fees,
        "reserve": reserve,
        "reserve_pct": (reserve / notional * Decimal("100")) if notional else Decimal("0"),
    }
