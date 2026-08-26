"""What the user owns and how it has done - the Phase 3 dashboard data.

    GET /positions            one row per holding, marked to market
    GET /portfolio/history    the equity curve

MONEY RULE (ADR-010): positions come back from Alpaca as decimal strings and
are passed through untouched. Portfolio history is the one Broker API
endpoint that sends JSON *numbers*, so `alpaca.portfolio_history` decodes it
with a `parse_float` hook that keeps the exact text - see the note there.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

import alpaca
import clerk_auth

router = APIRouter(tags=["portfolio"])

# Alpaca's own vocabulary, restated as types so a typo is a 422 instead of a
# confusing upstream error.
Period = Literal["1D", "1W", "1M", "3M", "1A", "all"]
Timeframe = Literal["1Min", "15Min", "1H", "1D"]


def _money(value) -> str:
    """A monetary value as a STRING. Never float() this (ADR-010)."""
    return "" if value is None else str(value)


def _series(values) -> list[str]:
    """One line of the equity chart, as strings.

    A `null` in an intraday series means "market closed, no data point"; it
    becomes an empty string so the array stays the same length as
    `timestamps` and the frontend can draw a gap.
    """
    if not isinstance(values, list):
        return []
    return [_money(value) for value in values]


@router.get("/positions")
def positions(account_id: str = Depends(clerk_auth.require_account_id)) -> list[dict]:
    """Current holdings. An empty list is the normal state of a new account."""
    try:
        rows = alpaca.list_positions(account_id)
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc

    return [
        {
            "symbol": str(row.get("symbol") or ""),
            "qty": _money(row.get("qty")),
            "side": str(row.get("side") or ""),
            "avg_entry_price": _money(row.get("avg_entry_price")),
            "current_price": _money(row.get("current_price")),
            "market_value": _money(row.get("market_value")),
            "cost_basis": _money(row.get("cost_basis")),
            "unrealized_pl": _money(row.get("unrealized_pl")),
            "unrealized_plpc": _money(row.get("unrealized_plpc")),
            "change_today": _money(row.get("change_today")),
        }
        for row in rows
    ]


@router.get("/portfolio/history")
def portfolio_history(
    period: Period = Query("1M"),
    timeframe: Timeframe = Query("1D"),
    account_id: str = Depends(clerk_auth.require_account_id),
) -> dict:
    """The equity curve: four parallel arrays plus the baseline they measure from.

    Parallel arrays rather than a list of objects because that is what Alpaca
    sends and what charting libraries consume, and it keeps the payload small
    for a 1Min/1D series (390 points).

    `timestamps` are epoch **seconds** and are left-labelled: a point marks
    the start of its interval.
    """
    try:
        data = alpaca.portfolio_history(account_id, period, timeframe)
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc

    data = data or {}
    timestamps = data.get("timestamp")
    return {
        "timestamps": [int(value) for value in timestamps] if isinstance(timestamps, list) else [],
        "equity": _series(data.get("equity")),
        "profit_loss": _series(data.get("profit_loss")),
        "profit_loss_pct": _series(data.get("profit_loss_pct")),
        "base_value": _money(data.get("base_value")),
    }
