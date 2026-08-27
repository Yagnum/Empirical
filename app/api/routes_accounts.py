"""Account provisioning and balance lookup.

    POST /accounts     lazily create the signed-in user's Alpaca account
    GET  /accounts/me  that account's status and balances
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

import alpaca
import audit
import clerk_auth

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
