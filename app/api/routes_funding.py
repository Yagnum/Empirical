"""Sandbox funding.

    POST /funding   {"amount": 1000}  ->  deposit virtual cash

In sandbox, Alpaca's Transfer API credits the account immediately, so this is
the onboarding "fund your account" button (ADR-004).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import alpaca
import clerk_auth

router = APIRouter(tags=["funding"])

MIN_AMOUNT = Decimal("1")
# Capped to protect the shared funding pool (the firm sweep account is
# finite — docs/ALPACA-FUNDING.md). Must match MAX_FUNDING in the web app.
MAX_AMOUNT = Decimal("100000")


class FundingRequest(BaseModel):
    # Declared as Decimal, not float: money never touches binary floating
    # point. Out-of-range values fail here and FastAPI returns 422.
    amount: Decimal = Field(..., ge=MIN_AMOUNT, le=MAX_AMOUNT)


@router.post("/funding")
def fund(
    body: FundingRequest,
    user_id: str = Depends(clerk_auth.require_user_id),
) -> dict:
    user = clerk_auth.get_user(user_id)
    account_id = clerk_auth.get_alpaca_account_id(user)
    if not account_id:
        raise HTTPException(status_code=404, detail="no_account")

    given_name, family_name = clerk_auth.names(user)
    amount = body.amount.quantize(Decimal("0.01"))

    # A brand-new account sits in SUBMITTED for a short time before Alpaca
    # activates it, and Alpaca refuses journals until then with a bare 422.
    # Say what is actually happening so the UI can ask the user to wait.
    try:
        status = str(alpaca.get_account(account_id).get("status", "")).upper()
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc
    if status != "ACTIVE":
        raise HTTPException(
            status_code=409,
            detail=f"account_not_active: the brokerage account is {status.lower() or 'not active'} yet",
        )

    try:
        transfer = alpaca.fund_account(account_id, amount, f"{given_name} {family_name}")
    except alpaca.AlpacaError as exc:
        raise alpaca.http_error(exc) from exc

    return {
        "transfer_id": str(transfer.get("id", "")),
        "status": str(transfer.get("status", "")),
        # Alpaca's own decimal string, passed through untouched.
        "amount": str(transfer.get("amount") or format(amount, "f")),
    }
