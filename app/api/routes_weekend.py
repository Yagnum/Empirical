"""The weekend engine's API, plus the dev clock that simulates a weekend.

    GET  /weekend/session            which window is it, and is it simulated
    GET  /weekend/preview            price + reserve for a draft weekend trade
    POST /weekend/orders             open a weekend trade (steps 1-3)
    GET  /weekend/orders             this account's weekend trades
    GET  /weekend/orders/{id}        one trade with its full event trail
    POST /weekend/orders/{id}/settle advance it toward settled (step 4-6)
    POST /dev/clock                  development only: flip the simulator

Weekend orders are accepted only while the effective session is "weekend" -
a real one, or the dev override. During any regulated session the answer is
409 `market_is_open`: the routing rule of ADR-019 is one path per hour, and
Jupiter is never the path while Alpaca is.

The /dev route answers 404 outside development. Not 403: in production the
simulator does not exist, and a probe should learn nothing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

import audit
import clerk_auth
import db
import sessions
import weekend
from models import WeekendTrade, WeekendTradeEvent

router = APIRouter(tags=["weekend"])

MAX_WEEKEND_QTY = Decimal("1000")


def _require_db(session: Session | None) -> Session:
    if session is None:
        raise HTTPException(status_code=503, detail="weekend_engine_unavailable: no database")
    return session


def _fmt(value: Decimal | None) -> str | None:
    # normalize() drops NUMERIC's stored trailing zeros ("190.0000000000");
    # format(..., "f") keeps the result plain digits, never scientific.
    return None if value is None else format(value.normalize(), "f")


def shape_trade(trade: WeekendTrade) -> dict:
    return {
        "id": trade.id,
        "symbol": trade.symbol,
        "token_symbol": trade.token_symbol,
        "side": trade.side,
        "qty": _fmt(trade.qty),
        "p_open": _fmt(trade.p_open),
        "sigma": _fmt(trade.sigma),
        "z": _fmt(trade.z),
        "reserve": _fmt(trade.reserve),
        "fees": _fmt(trade.fees),
        "state": trade.state,
        "simulated": trade.simulated,
        "source": trade.source,
        "settlement_mode": trade.settlement_mode,
        "injected_gap": _fmt(trade.injected_gap),
        "hedge_order_id": trade.hedge_order_id,
        "p_close": _fmt(trade.p_close),
        "true_up": _fmt(trade.true_up),
        "escrow_returned": _fmt(trade.escrow_returned),
        "shortfall": _fmt(trade.shortfall),
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
        "settled_at": trade.settled_at.isoformat() if trade.settled_at else None,
    }


def shape_event(event: WeekendTradeEvent) -> dict:
    return {
        "at": event.at.isoformat() if event.at else None,
        "kind": event.kind,
        "amount": _fmt(event.amount),
        "alpaca_ref": event.alpaca_ref,
        "detail": event.detail,
    }


# ---------------------------------------------------------------------------
# Session and the dev clock
# ---------------------------------------------------------------------------


@router.get("/weekend/session", dependencies=[Depends(clerk_auth.require_user_id)])
def current_session() -> dict:
    """The effective trading window, and whether the simulator can exist.

    `dev_toggle` tells the frontend whether to render the weekday/weekend
    switch at all - true only in development.
    """
    state = sessions.effective_session()
    return {
        **state,
        "weekend_trading": state["session"] == sessions.WEEKEND,
        "dev_toggle": sessions.dev_override_allowed(),
    }


class DevClockRequest(BaseModel):
    simulate_weekend: bool


@router.post("/dev/clock")
def set_dev_clock(
    body: DevClockRequest,
    request: Request,
    user_id: str = Depends(clerk_auth.require_user_id),
) -> dict:
    """Development only: force the app's clock into (or out of) the weekend."""
    if not sessions.dev_override_allowed():
        raise HTTPException(status_code=404, detail="not_found")
    with audit.audited(request, "dev.clock", user_id=user_id) as entry:
        sessions.set_weekend_override(body.simulate_weekend)
        entry.detail = f"simulate_weekend={body.simulate_weekend}"
    return current_session()


# ---------------------------------------------------------------------------
# Preview and orders
# ---------------------------------------------------------------------------


def _check_qty(qty: Decimal) -> Decimal:
    # Whole shares only for now: fractional orders meet extra broker rules in
    # extended sessions, and the hedge must be placeable in any of them.
    if qty != qty.to_integral_value():
        raise HTTPException(status_code=422, detail="whole_shares_only")
    if not (0 < qty <= MAX_WEEKEND_QTY):
        raise HTTPException(status_code=422, detail="qty_out_of_range")
    return qty


@router.get("/weekend/preview", dependencies=[Depends(clerk_auth.require_user_id)])
def preview(
    symbol: str = Query(..., min_length=1, max_length=12),
    side: Literal["buy", "sell"] = Query(...),
    qty: Decimal = Query(...),
) -> dict:
    """What this weekend trade would cost, before anyone commits to it.

    Everything the confirmation screen shows: the executable Jupiter price
    for this exact size and direction, the measured inputs, the reserve.
    """
    qty = _check_qty(qty)
    priced = weekend.price_trade(symbol, side, qty)
    sizing = priced["sizing"]
    p_open = priced["p_open"]
    cent = Decimal("0.01")
    return {
        "symbol": symbol.upper(),
        "token_symbol": priced["token"]["symbol"],
        "side": side,
        "qty": _fmt(qty),
        "p_open": _fmt(p_open.quantize(cent)),
        "notional": _fmt((qty * p_open).quantize(cent)),
        "price_impact_pct": priced["quote"]["price_impact_pct"],
        "sigma": _fmt(sizing["sigma"]),
        "sigma_source": sizing["sigma_source"],
        "z": _fmt(sizing["z"]),
        "fees": _fmt(sizing["fees"]),
        "reserve": _fmt(sizing["reserve"]),
        "reserve_pct": _fmt(sizing["reserve_pct"].quantize(cent)),
        "params_generated_at": sizing["params_generated_at"],
        "session": sessions.effective_session(),
    }


class WeekendOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=12)
    side: Literal["buy", "sell"]
    qty: Decimal = Field(..., gt=0)

    @field_validator("symbol")
    @classmethod
    def _normalise_symbol(cls, value: str) -> str:
        return value.strip().upper()


@router.post("/weekend/orders")
def place_weekend_order(
    body: WeekendOrderRequest,
    request: Request,
    user_id: str = Depends(clerk_auth.require_user_id),
    account_id: str = Depends(clerk_auth.require_account_id),
    session: Session | None = Depends(db.get_session),
) -> dict:
    """Open a weekend trade: Jupiter quote, reserve to escrow, cash moved."""
    store = _require_db(session)
    qty = _check_qty(body.qty)
    if not sessions.weekend_trading_active():
        raise HTTPException(
            status_code=409,
            detail="market_is_open: weekend trades exist only while no regulated session does",
        )
    with audit.audited(request, "weekend.open", user_id=user_id, account_id=account_id) as entry:
        entry.detail = f"{body.side} {_fmt(qty)} {body.symbol}"
        trade = weekend.open_trade(
            store,
            user_id=user_id,
            account_id=account_id,
            symbol=body.symbol,
            side=body.side,
            qty=qty,
        )
        entry.detail = f"{entry.detail} -> trade {trade.id} at {_fmt(trade.p_open)}"
    return shape_trade(trade)


@router.get("/weekend/orders")
def list_weekend_orders(
    account_id: str = Depends(clerk_auth.require_account_id),
    session: Session | None = Depends(db.get_session),
) -> list[dict]:
    store = _require_db(session)
    return [shape_trade(trade) for trade in weekend.list_trades(store, account_id)]


@router.get("/weekend/orders/{trade_id}")
def get_weekend_order(
    trade_id: int,
    account_id: str = Depends(clerk_auth.require_account_id),
    session: Session | None = Depends(db.get_session),
) -> dict:
    store = _require_db(session)
    trade = weekend.get_trade(store, account_id, trade_id)
    return {
        **shape_trade(trade),
        "events": [shape_event(event) for event in weekend.trade_events(store, trade)],
    }


class SettleRequest(BaseModel):
    mode: Literal["market", "injected"] = "market"
    # As a fraction: -0.05 is "the price fell five percent over the weekend".
    gap: Decimal | None = Field(default=None, ge=Decimal("-0.9"), le=Decimal("0.9"))


@router.post("/weekend/orders/{trade_id}/settle")
def settle_weekend_order(
    trade_id: int,
    body: SettleRequest,
    request: Request,
    user_id: str = Depends(clerk_auth.require_user_id),
    account_id: str = Depends(clerk_auth.require_account_id),
    session: Session | None = Depends(db.get_session),
) -> dict:
    """Advance one trade toward settled. Safe to call repeatedly."""
    store = _require_db(session)
    trade = weekend.get_trade(store, account_id, trade_id)
    with audit.audited(request, "weekend.settle", user_id=user_id, account_id=account_id) as entry:
        entry.detail = f"trade {trade.id} mode={body.mode}"
        trade = weekend.settle(store, trade, mode=body.mode, gap=body.gap)
        entry.detail = f"{entry.detail} -> {trade.state}"
    return {
        **shape_trade(trade),
        "events": [shape_event(event) for event in weekend.trade_events(store, trade)],
    }
