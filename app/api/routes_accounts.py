"""Account provisioning, balance lookup, and the reset button.

    POST /accounts        lazily create the signed-in user's Alpaca account
    GET  /accounts/me     that account's status and balances
    POST /accounts/reset  sell everything, return the cash, land on $0
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

import alpaca
import audit
import clerk_auth
import db
import offboarding
import weekend
from config import settings

router = APIRouter(tags=["accounts"])


def _money(value) -> str:
    """Pass a monetary field through as a STRING, exactly as Alpaca sent it.

    Never float() these. A float cannot hold decimal cents exactly, so parsing
    and re-printing money silently changes it. Strings in, strings out; if we
    ever need arithmetic, decimal.Decimal is the tool.
    """
    return "" if value is None else str(value)


@router.post("/accounts")
def provision_account(
    request: Request,
    user_id: str = Depends(clerk_auth.require_user_id),
) -> dict:
    """Idempotent: one Alpaca account per Clerk user, created on first call.

    Audited (ADR-014): this is the one request that brings a brokerage account
    into existence, so "who opened this account, and when" is worth a row.
    """
    with audit.audited(request, "account.provision", user_id=user_id) as entry:
        result = _provision(user_id)
        entry.alpaca_account_id = result["alpaca_account_id"]
        entry.detail = f"created={result['created']} status={result['status']}"
        return result


def _provision(user_id: str) -> dict:
    """The provisioning itself, kept separate so the route reads as one line."""
    user = clerk_auth.get_user(user_id)
    existing_metadata = clerk_auth.private_metadata(user)
    existing_id = clerk_auth.get_alpaca_account_id(user)

    if existing_id:
        try:
            account = alpaca.get_account(existing_id)
            return {
                "alpaca_account_id": existing_id,
                "created": False,
                "status": str(account.get("status", "")),
            }
        except alpaca.AlpacaError as exc:
            if exc.status_code != 404:
                raise alpaca.http_error(exc) from exc
            # The stored id points at an account Alpaca no longer knows —
            # e.g. the sandbox was reset. Our metadata and Alpaca's state
            # have diverged; Alpaca is the source of truth for accounts, so
            # self-heal by falling through and provisioning a fresh one.

    email = clerk_auth.primary_email(user)
    if not email:
        raise HTTPException(status_code=400, detail="clerk_user_has_no_email")
    given_name, family_name = clerk_auth.names(user)

    try:
        account = alpaca.create_account(email, given_name, family_name)
    except alpaca.AlpacaError as exc:
        if not alpaca.is_email_conflict(exc):
            raise alpaca.http_error(exc) from exc
        # The email is already registered with Alpaca. Almost always this is
        # a concurrent provision call that won the race a moment ago. Adopt
        # that account instead of failing; only give up if we cannot find it.
        try:
            account = alpaca.find_account_by_email(email)
        except alpaca.AlpacaError as lookup_exc:
            raise alpaca.http_error(lookup_exc) from lookup_exc
        if account is None:
            raise HTTPException(
                status_code=409,
                detail="alpaca_email_already_exists: an Alpaca account already exists for this email",
            ) from exc
        account_id = str(account["id"])
        clerk_auth.set_alpaca_account_id(user_id, account_id, existing_metadata)
        return {
            "alpaca_account_id": account_id,
            "created": False,
            "status": str(account.get("status", "")),
        }

    account_id = str(account["id"])
    # Store the mapping before returning: if this write fails the caller gets an
    # error and can retry, rather than us orphaning a brokerage account.
    clerk_auth.set_alpaca_account_id(user_id, account_id, existing_metadata)

    return {
        "alpaca_account_id": account_id,
        "created": True,
        "status": str(account.get("status", "")),
    }


@router.post("/accounts/reset")
def reset_account(
    request: Request,
    user_id: str = Depends(clerk_auth.require_user_id),
    account_id: str = Depends(clerk_auth.require_account_id),
    session: Session | None = Depends(db.get_session),
) -> dict:
    """Sell everything, return the cash, leave the account at $0 (ADR-015).

    The owner's chosen semantics: a reset liquidates whatever the user still
    holds, then journals every dollar back to the firm sweep — the account
    lands empty and the existing funding form picks the next starting
    amount. Shares its flatten-and-return steps with the offboarding webhook
    (`offboarding.py`); unlike the webhook it never retires the email or
    closes the account.

    Each call advances the flow as far as it can and reports where things
    stand; the frontend polls by re-POSTing. The states:

      {"state": "liquidating", "positions": N, "open_orders": M}
          Closing orders submitted (cancelling open orders with them). With
          the market closed those sells queue until the next open, so this
          state can honestly persist for days — that is the market, not a
          bug, and the UI should say so.
      {"state": "reset", "returned": "<decimal string>"}
          Flat, orders cancelled, cash journalled away. `"0"` when there
          was nothing to return — calling reset twice is harmless.

    Audited (ADR-014): a reset moves money and destroys positions.
    """
    with audit.audited(request, "account.reset", user_id=user_id, account_id=account_id) as entry:
        # A reset sells everything - including shares an open weekend trade
        # has already sold once (ADR-022). Settle those first.
        if session is not None and weekend.open_trade_count(session, account_id) > 0:
            raise HTTPException(
                status_code=409,
                detail="weekend_trades_open: settle your open weekend trades before resetting",
            )
        try:
            # Same guard and shape as POST /funding: journals (and orders)
            # bounce off a not-yet-ACTIVE account with a bare 422, so name
            # the real problem instead.
            status = str(alpaca.get_account(account_id).get("status", "")).upper()
            if status != "ACTIVE":
                raise HTTPException(
                    status_code=409,
                    detail=f"account_not_active: the brokerage account is {status.lower() or 'not active'}",
                )

            begun = offboarding.begin_liquidation(account_id)
            if begun is not None:
                positions, open_orders = begun
                entry.detail = f"liquidating positions={positions} open_orders={open_orders}"
                return {"state": "liquidating", "positions": positions, "open_orders": open_orders}

            cancelled = offboarding.cancel_open_orders(account_id)

            cash = offboarding.account_cash(account_id)
            if cash <= 0:
                entry.detail = f"returned=0 orders_cancelled={cancelled}"
                return {"state": "reset", "returned": "0"}
            if not settings.alpaca_firm_account_id:
                raise HTTPException(
                    status_code=503,
                    detail="reset_unavailable: ALPACA_FIRM_ACCOUNT_ID is not configured",
                )
            offboarding.return_cash_to_firm(account_id, cash)
            returned = format(cash, "f")
            entry.detail = f"returned={returned} orders_cancelled={cancelled}"
            return {"state": "reset", "returned": returned}
        except alpaca.AlpacaError as exc:
            raise alpaca.http_error(exc) from exc


@router.get("/accounts/me")
def my_account(user_id: str = Depends(clerk_auth.require_user_id)) -> dict:
    """Status + balances for the signed-in user's account."""
    user = clerk_auth.get_user(user_id)
    account_id = clerk_auth.get_alpaca_account_id(user)
    if not account_id:
        raise HTTPException(status_code=404, detail="no_account")

    try:
        trading = alpaca.get_trading_account(account_id)
    except alpaca.AlpacaError as exc:
        if exc.status_code == 404:
            # Orphaned id (sandbox reset). Report "no account" so the
            # frontend routes the user back through onboarding, where
            # POST /accounts self-heals the mapping.
            raise HTTPException(status_code=404, detail="no_account") from exc
        raise alpaca.http_error(exc) from exc

    return {
        "alpaca_account_id": account_id,
        "status": str(trading.get("status", "")),
        "currency": str(trading.get("currency") or "USD"),
        "cash": _money(trading.get("cash")),
        "buying_power": _money(trading.get("buying_power")),
        "portfolio_value": _money(trading.get("portfolio_value")),
        "equity": _money(trading.get("equity")),
    }
