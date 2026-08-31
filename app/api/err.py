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
        "sigma": sigma,
        "sigma_source": sigma_source,
        "z": z,
        "fees": fees,
        "notional": notional,
        "reserve": reserve,
        "reserve_pct": (reserve / notional * Decimal("100")) if notional else Decimal("0"),
        "params_generated_at": str(params()["generated_at"]),
    }
