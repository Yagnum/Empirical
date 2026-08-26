"""Clerk authentication + the tiny bit of user state we keep there.

Two jobs:

1. `require_user_id` — a FastAPI dependency. It verifies the Clerk session
   token in the `Authorization: Bearer ...` header and hands the route the
   Clerk user id. Anything unverifiable is a 401.

2. Read/write the user's `alpaca_account_id`. We have no database (ADR-003):
   the one piece of state Phase 1 needs lives in the Clerk user's *private*
   metadata, which only the backend can read or write.

3. `require_account_id` — the same check plus "which Alpaca account is
   this?", so the trading routes do not each repeat the lookup.

The dependency is declared with `fastapi.security.HTTPBearer`, which is what
puts the **Authorize** lock button on /docs: Swagger then attaches
`Authorization: Bearer <token>` to every try-it-out request. The scheme is
created with `auto_error=False` so *we* keep emitting the exact 401 detail
strings below rather than FastAPI's generic "Not authenticated".

Docs: https://github.com/clerk/clerk-sdk-python
      https://fastapi.tiangolo.com/reference/security/#fastapi.security.HTTPBearer
"""

from __future__ import annotations

from typing import Any

from clerk_backend_api import Clerk
from clerk_backend_api.security.types import AuthenticateRequestOptions
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings

ALPACA_ACCOUNT_ID_KEY = "alpaca_account_id"

# One client for the process. `bearer_auth` is the Clerk *secret* key: it is
# only ever used server-side and never appears in a response.
clerk = Clerk(bearer_auth=settings.clerk_secret_key)

# Declaring the scheme (rather than reading the header by hand) is what makes
# OpenAPI advertise bearer auth, which is what /docs turns into the lock icon.
# `auto_error=False`: a missing header returns None here instead of raising, so
# our own 401 message survives.
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="ClerkSessionToken",
    description="Clerk session token. Mint one with `uv run python scripts/dev_token.py`.",
)


def _reason_text(state: Any) -> str:
    """Render Clerk's failure reason as a short string (never a secret)."""
    reason = getattr(state, "reason", None)
    if reason is None:
        return getattr(state, "message", None) or "token could not be verified"
    value = getattr(reason, "value", reason)
    if isinstance(value, (tuple, list)) and value:
        return str(value[0])
    return str(value)


def _check_authorized_party(payload: dict) -> None:
    """Enforce `azp` when the token has one, and only then.

    `azp` ("authorized party") records the origin a session token was minted
    for. Clerk's frontend stamps our web app's origin into it, so checking it
    stops a token issued for some *other* Clerk app from being replayed here.
    We want that check.

    But the SDK's `authorized_parties` option also rejects a token that has no
    `azp` at all, and a token minted through the Backend API - which is what
    `scripts/dev_token.py` does, and the only way to test with curl, Swagger
    or Postman - never has one, because it was not issued to any origin.

    So we check the claim ourselves: present means it must match; absent means
    the token was minted server-side by something already holding
    CLERK_SECRET_KEY, which is a party we trust by definition. Browser tokens
    stay pinned to the frontend origin either way.
    """
    azp = payload.get("azp")
    if azp is None and not settings.allow_tokens_without_azp:
        raise HTTPException(
            status_code=401,
            detail="invalid_session_token: token-missing-authorized-party",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if azp is not None and azp != settings.frontend_origin:
        raise HTTPException(
            status_code=401,
            detail="invalid_session_token: token-invalid-authorized-parties",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """FastAPI dependency: verify the bearer token, return the Clerk user id.

    `credentials` exists so the route is documented as requiring bearer auth;
    the token itself is re-read from the request by the Clerk SDK, which wants
    the whole request object (it also understands Clerk's session cookie).
    """
    if not settings.clerk_secret_key:
        raise HTTPException(status_code=500, detail="clerk_not_configured")

    if credentials is None and not request.headers.get("authorization"):
        raise HTTPException(
            status_code=401,
            detail="missing_authorization_header: send 'Authorization: Bearer <clerk session token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # The SDK only needs an object with `.headers`; a FastAPI Request has one.
    # We do NOT pass `authorized_parties` here and instead check `azp`
    # ourselves below - see _check_authorized_party for why.
    try:
        state = clerk.authenticate_request(request, AuthenticateRequestOptions())
    except Exception as exc:  # network hiccup, malformed token, bad key...
        raise HTTPException(
            status_code=401,
            detail=f"invalid_session_token: {type(exc).__name__}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if not state.is_signed_in:
        raise HTTPException(
            status_code=401,
            detail=f"invalid_session_token: {_reason_text(state)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = state.payload or {}
    _check_authorized_party(payload)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_session_token: no subject claim")
    return str(user_id)


# ---------------------------------------------------------------------------
# Clerk user record helpers
# ---------------------------------------------------------------------------


def _clerk_call(what: str, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"clerk_error: {what} failed ({type(exc).__name__})") from exc


def get_user(user_id: str):
    user = _clerk_call("get user", clerk.users.get, user_id=user_id, timeout_ms=15_000)
    if user is None:
        raise HTTPException(status_code=404, detail="clerk_user_not_found")
    return user


def private_metadata(user) -> dict:
    data = getattr(user, "private_metadata", None)
    return dict(data) if isinstance(data, dict) else {}


def get_alpaca_account_id(user) -> str | None:
    value = private_metadata(user).get(ALPACA_ACCOUNT_ID_KEY)
    return str(value) if value else None


def set_alpaca_account_id(user_id: str, account_id: str, existing: dict | None = None) -> None:
    """Store the mapping Clerk user -> Alpaca account, preserving other keys.

    `update_metadata` merges at the top level, but we pass the existing keys
    back explicitly so this stays obvious rather than clever.
    """
    merged = dict(existing or {})
    merged[ALPACA_ACCOUNT_ID_KEY] = account_id
    _clerk_call(
        "update private metadata",
        clerk.users.update_metadata,
        user_id=user_id,
        private_metadata=merged,
        timeout_ms=15_000,
    )


def primary_email(user) -> str | None:
    """The user's primary email address, falling back to the first one."""
    addresses = getattr(user, "email_addresses", None) or []
    primary_id = getattr(user, "primary_email_address_id", None)
    for address in addresses:
        if primary_id and getattr(address, "id", None) == primary_id:
            return getattr(address, "email_address", None)
    for address in addresses:
        email = getattr(address, "email_address", None)
        if email:
            return email
    return None


def names(user) -> tuple[str, str]:
    """(given_name, family_name), with sensible fallbacks for KYC fields."""
    given = (getattr(user, "first_name", None) or "").strip()
    family = (getattr(user, "last_name", None) or "").strip()
    return given or "Yagnum", family or "Trader"


def require_account_id(user_id: str = Depends(require_user_id)) -> str:
    """FastAPI dependency: the signed-in user's Alpaca account id.

    Every trading, portfolio and statement route needs exactly this, so the
    lookup lives here once. 404 `no_account` means "you have not onboarded
    yet" — the frontend sends the user back through POST /accounts.
    """
    account_id = get_alpaca_account_id(get_user(user_id))
    if not account_id:
        raise HTTPException(status_code=404, detail="no_account")
    return account_id
