"""Placing and managing orders - the heart of Phase 2.

    POST   /orders             place a market or limit order
    GET    /orders?status=     order history, newest first
    GET    /orders/{id}        one order
    DELETE /orders/{id}        cancel a working order

Every route acts on the signed-in user's own Alpaca account and no other:
the account id comes from `clerk_auth.require_account_id`, never from the
request body. That is the whole security model in one sentence.

Docs: https://docs.alpaca.markets/reference/createorderforaccount
      https://docs.alpaca.markets/reference/getallordersforaccount
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

import alpaca
import clerk_auth

router = APIRouter(tags=["orders"])

MAX_ORDERS = 500


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class OrderRequest(BaseModel):
    """The buy/sell form, validated before a single byte reaches Alpaca.

    `qty` and `limit_price` are `Decimal`, so a JSON string ("1.5") and a JSON
    number (1.5) are both accepted and neither becomes a binary float
    (ADR-010). Anything that fails here is a 422 from FastAPI with the field
    name attached - the frontend can point at the offending input.
    """

    symbol: str = Field(..., min_length=1, max_length=12)
    qty: Decimal = Field(..., gt=0)
    side: Literal["buy", "sell"]
    type: Literal["market", "limit"]
    limit_price: Decimal | None = Field(default=None, gt=0)
    time_in_force: Literal["day", "gtc"] = "day"

    @field_validator("symbol")
    @classmethod
    def _normalise_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def _limit_needs_a_price(self) -> "OrderRequest":
        if self.type == "limit" and self.limit_price is None:
            raise ValueError("limit_price is required for a limit order")
        if self.type == "market" and self.limit_price is not None:
            raise ValueError("limit_price is only valid for a limit order")
        return self

    def to_alpaca(self) -> dict:
        """The Alpaca request body. Numbers go out as strings, always."""
        payload = {
            "symbol": self.symbol,
            "qty": format(self.qty, "f"),
            "side": self.side,
            "type": self.type,
            "time_in_force": self.time_in_force,
        }
        if self.limit_price is not None:
            payload["limit_price"] = format(self.limit_price, "f")
        return payload


# ---------------------------------------------------------------------------
# Shaping and error mapping
# ---------------------------------------------------------------------------


def _text(value) -> str:
    return "" if value is None else str(value)


def _optional(value) -> str | None:
    """Nullable pass-through: Alpaca's null stays null, never becomes "0"."""
    return None if value is None else str(value)


def shape_order(order: dict) -> dict:
    """The exact order object the frontend is built against.

    Alpaca sends both `type` and `order_type` (identical) plus a dozen fields
    we do not use. Pinning the shape here means an upstream addition can never
    silently change our contract.
    """
    return {
        "id": _text(order.get("id")),
        "client_order_id": _text(order.get("client_order_id")),
        "symbol": _text(order.get("symbol")),
        "qty": _text(order.get("qty")),
        "filled_qty": _text(order.get("filled_qty")),
        "side": _text(order.get("side")),
        "type": _text(order.get("type") or order.get("order_type")),
        "time_in_force": _text(order.get("time_in_force")),
        "status": _text(order.get("status")),
        "limit_price": _optional(order.get("limit_price")),
        "filled_avg_price": _optional(order.get("filled_avg_price")),
        "submitted_at": _text(order.get("submitted_at") or order.get("created_at")),
        "filled_at": _optional(order.get("filled_at")),
        "canceled_at": _optional(order.get("canceled_at")),
    }


def _rejection(exc: alpaca.AlpacaError) -> HTTPException:
    """Turn an order refusal into the 400 the contract promises.

    Alpaca is inconsistent about which 4xx a refusal gets: "insufficient
    buying power" is a **403**, "asset not found" a **422**, others 400. All
    three mean the same thing to a user - the broker said no - so they
    collapse into one status with Alpaca's own wording preserved. We reserve
    422 for *our* validation (a malformed body), so the frontend can tell
    "you typed it wrong" apart from "the broker refused".

    401 (our keys), 404 (the account is gone) and 429 (rate limit) are not
    refusals of *this* order, so they keep their usual meaning.
    """
    status = exc.status_code
    if status is not None and 400 <= status < 500 and status not in (401, 404, 429):
        return HTTPException(status_code=400, detail=f"alpaca_rejected: {exc.message}")
    return alpaca.http_error(exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/orders")
def place_order(
    body: OrderRequest,
    account_id: str = Depends(clerk_auth.require_account_id),
) -> dict:
    """Submit an order and return it in whatever state Alpaca accepted it.

    While the market is closed a `day` order sits in `accepted` until the
    next open; that is normal, not an error.
    """
    try:
        order = alpaca.create_order(account_id, body.to_alpaca())
    except alpaca.AlpacaError as exc:
        raise _rejection(exc) from exc
    return shape_order(order)


@router.get("/orders")
def list_orders(
    status: Literal["open", "closed", "all"] = Query("open"),
    limit: int = Query(50, ge=1, le=MAX_ORDERS),
    account_id: str = Depends(clerk_auth.require_account_id),
) -> list[dict]:
    """Order history, newest first."""
    try:
        orders = alpaca.list_orders(account_id, status, limit)
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc
    return [shape_order(order) for order in orders]


@router.get("/orders/{order_id}")
def get_order(
    order_id: str,
    account_id: str = Depends(clerk_auth.require_account_id),
) -> dict:
    try:
        order = alpaca.get_order(account_id, order_id)
    except alpaca.AlpacaError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="order_not_found") from exc
        raise alpaca.http_error(exc) from exc
    return shape_order(order)


@router.delete("/orders/{order_id}")
def cancel_order(
    order_id: str,
    account_id: str = Depends(clerk_auth.require_account_id),
) -> dict:
    """Cancel a working order.

    Alpaca's DELETE answers 204 with no body, so we read the order back to
    report the real outcome. Cancellation is a *request*: an order that is
    still working goes to `pending_cancel` first and only later to `canceled`.
    An order that already filled cannot be cancelled at all - Alpaca refuses
    with 422, which we surface as 409, the honest "conflicts with current
    state" status.
    """
    try:
        alpaca.cancel_order(account_id, order_id)
    except alpaca.AlpacaError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="order_not_found") from exc
        if exc.status_code in (409, 422):
            raise HTTPException(status_code=409, detail="order_not_cancelable") from exc
        raise alpaca.http_error(exc) from exc

    try:
        order = alpaca.get_order(account_id, order_id)
        status = _text(order.get("status")) or "pending_cancel"
    except alpaca.AlpacaError:
        # The cancel itself succeeded; a failed read-back must not turn a
        # successful cancellation into an error for the user.
        status = "pending_cancel"
    return {"id": order_id, "status": status}
