"""A thin client for Alpaca's Broker API (sandbox).

Only this module knows the Alpaca credentials and URL shapes. Everything
else in the app calls the small functions at the bottom of this file.

Auth is HTTP Basic: username = ALPACA_BROKER_ID, password = ALPACA_BROKER_SECRET.
Base URL (sandbox): https://broker-api.sandbox.alpaca.markets

Docs:
  - Create account:  https://docs.alpaca.markets/reference/createaccount
  - Trading account: https://docs.alpaca.markets/reference/gettradingaccount
  - ACH relationship: https://docs.alpaca.markets/reference/createachrelationshipforaccount
  - Transfers:       https://docs.alpaca.markets/reference/createtransferforaccount

MONEY RULE: every dollar amount Alpaca sends us is a decimal *string*
("1000.25"). We pass those strings straight through to the frontend and never
convert them to float — binary floats cannot represent decimal cents exactly,
so float(x) silently corrupts money (0.1 + 0.2 != 0.3). Where we must do
arithmetic or formatting we use decimal.Decimal.
"""

from __future__ import annotations

import math
import random
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from fastapi import HTTPException

from config import settings

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AlpacaError(Exception):
    """Something went wrong talking to Alpaca.

    Carries the HTTP status Alpaca returned (or None for a network/timeout
    failure) plus a short, non-secret message safe to show a user.
    """

    def __init__(self, message: str, status_code: int | None = None, code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code  # Alpaca's own numeric error code, when present


def http_error(exc: AlpacaError) -> HTTPException:
    """Translate an AlpacaError into the HTTPException we show the client.

    We never leak credentials or raw upstream bodies that might contain them;
    `exc.message` is already the trimmed message Alpaca gave us.
    """
    if exc.status_code is None:
        return HTTPException(status_code=504, detail=f"alpaca_unreachable: {exc.message}")
    if exc.status_code in (401, 403):
        # Our keys are wrong/expired — that is our bug, not the caller's.
        return HTTPException(status_code=502, detail="alpaca_auth_failed")
    if exc.status_code == 404:
        return HTTPException(status_code=404, detail=f"alpaca_not_found: {exc.message}")
    if exc.status_code == 422:
        return HTTPException(status_code=422, detail=f"alpaca_rejected: {exc.message}")
    if 400 <= exc.status_code < 500:
        return HTTPException(status_code=400, detail=f"alpaca_rejected: {exc.message}")
    return HTTPException(status_code=502, detail=f"alpaca_error: {exc.message}")


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
#
# These are plain synchronous functions. FastAPI runs `def` (non-async) route
# handlers in a worker thread, so blocking HTTP here does not stall the event
# loop — and synchronous code is far easier to read and debug.


def _call(
    method: str,
    url: str,
    *,
    path: str,
    json: dict | None = None,
    params: dict | None = None,
    follow_redirects: bool = True,
) -> httpx.Response:
    """One HTTP round trip to Alpaca, with our credentials and timeout."""
    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.request(
                method,
                url,
                json=json,
                params=params,
                auth=(settings.alpaca_broker_id, settings.alpaca_broker_secret),
                headers={"accept": "application/json"},
                follow_redirects=follow_redirects,
            )
    except httpx.TimeoutException as exc:
        raise AlpacaError(f"timed out calling {method} {path}") from exc
    except httpx.HTTPError as exc:
        raise AlpacaError(f"network error calling {method} {path}: {type(exc).__name__}") from exc

    if response.status_code >= 400:
        raise AlpacaError(
            _error_message(response),
            status_code=response.status_code,
            code=_error_code(response),
        )
    return response


def _decode(response: httpx.Response, *, numbers_as_strings: bool = False) -> Any:
    """Parse a JSON body.

    `numbers_as_strings=True` hands `json.loads` a `parse_float` hook so every
    JSON *number* with a decimal point arrives as the exact text Alpaca sent
    ("294.37"), never as a binary float. The Broker API sends money as strings
    already, but the Market Data API and portfolio history send bare JSON
    numbers — this is where those become ADR-010-compliant strings without
    ever passing through `float`.
    """
    if not response.content:
        return None
    if numbers_as_strings:
        return response.json(parse_float=str)
    return response.json()


def _request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    numbers_as_strings: bool = False,
) -> Any:
    url = settings.alpaca_broker_base_url.rstrip("/") + path
    response = _call(method, url, path=path, json=json, params=params)
    return _decode(response, numbers_as_strings=numbers_as_strings)


def _error_body(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error_message(response: httpx.Response) -> str:
    body = _error_body(response)
    message = body.get("message") or body.get("error") or response.text or response.reason_phrase
    return str(message)[:300]


def _error_code(response: httpx.Response) -> int | None:
    code = _error_body(response).get("code")
    return code if isinstance(code, int) else None


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def _fake_ssn() -> str:
    """Sandbox KYC needs a well-formed, unique-looking SSN. Never a real one.

    Avoids the invalid area numbers 000, 666 and 900-999.
    """
    area = random.randint(100, 665)
    group = random.randint(1, 99)
    serial = random.randint(1, 9999)
    return f"{area:03d}-{group:02d}-{serial:04d}"


def build_account_payload(email: str, given_name: str, family_name: str) -> dict:
    """The POST /v1/accounts body.

    Real email + name come from the signed-in Clerk user; everything else is
    plausible fake KYC, which is exactly what the sandbox expects (ADR-004).
    """
    signed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "contact": {
            "email_address": email,
            "phone_number": "+15556667788",
            "street_address": ["20 N San Mateo Dr"],
            "city": "San Mateo",
            "state": "CA",
            "postal_code": "94401",
            "country": "USA",
        },
        "identity": {
            "given_name": given_name,
            "family_name": family_name,
            "date_of_birth": date(1990, 1, 1).isoformat(),
            "tax_id": _fake_ssn(),
            "tax_id_type": "USA_SSN",
            "country_of_citizenship": "USA",
            "country_of_birth": "USA",
            "country_of_tax_residence": "USA",
            "funding_source": ["employment_income"],
        },
        "disclosures": {
            "is_control_person": False,
            "is_affiliated_exchange_or_finra": False,
            "is_politically_exposed": False,
            "immediate_family_exposed": False,
        },
        "agreements": [
            {
                "agreement": "customer_agreement",
                "signed_at": signed_at,
                "ip_address": "127.0.0.1",
            }
        ],
    }


def create_account(email: str, given_name: str, family_name: str) -> dict:
    """POST /v1/accounts — create one brokerage account for one end user."""
    return _request("POST", "/v1/accounts", json=build_account_payload(email, given_name, family_name))


def is_email_conflict(exc: AlpacaError) -> bool:
    """True when Alpaca refused because that email already has an account."""
    if exc.status_code == 409:
        return True
    return exc.status_code == 400 and "email" in exc.message.lower()


def find_account_by_email(email: str) -> dict | None:
    """GET /v1/accounts?query=<email> — adopt an account that already exists.

    Used when Alpaca says the email is taken: usually a concurrent provision
    call won the race, so the right move is to reuse its account, not fail.
    """
    matches = _request("GET", f"/v1/accounts?query={email}") or []
    for account in matches:
        contact = account.get("contact") or {}
        if str(contact.get("email_address", "")).lower() == email.lower():
            return account
    return matches[0] if len(matches) == 1 else None


def get_account(account_id: str) -> dict:
    """GET /v1/accounts/{id} — the brokerage account record (KYC status etc.)."""
    return _request("GET", f"/v1/accounts/{account_id}")


def get_trading_account(account_id: str) -> dict:
    """GET /v1/trading/accounts/{id}/account — balances and buying power.

    All monetary fields come back as decimal strings; we keep them as strings.
    """
    return _request("GET", f"/v1/trading/accounts/{account_id}/account")


# ---------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------
#
# FUNDING METHOD: ACH relationship + Transfer API.
#
# In sandbox the Transfer API "simulates deposits and withdrawals to/from an
# account. The target account is immediately credited or debited upon such a
# request." That makes it a one-call top-up once a relationship exists, and it
# is the same code path a production app would use. The alternative — journaling
# cash (JNLC) out of the firm/sweep account — needs us to discover and manage a
# firm account id, which is more moving parts for no benefit here.
#
# https://docs.alpaca.markets/us/docs/funding-accounts

_ACH_NICKNAME = "Yagnum Sandbox Bank"
# Reusable ACH relationship statuses. A brand-new sandbox relationship is
# QUEUED and becomes APPROVED shortly after; transfers work from either.
_USABLE_ACH_STATUSES = {"QUEUED", "PENDING", "APPROVED", "ACTIVE"}


def list_ach_relationships(account_id: str) -> list[dict]:
    result = _request("GET", f"/v1/accounts/{account_id}/ach_relationships")
    return result if isinstance(result, list) else []


def create_ach_relationship(account_id: str, account_owner_name: str) -> dict:
    """POST /v1/accounts/{id}/ach_relationships — link a (fake) bank account.

    Sandbox still validates the *format* of the routing/account numbers, so we
    use a real bank routing number with a made-up account number.
    """
    return _request(
        "POST",
        f"/v1/accounts/{account_id}/ach_relationships",
        json={
            "account_owner_name": account_owner_name,
            "bank_account_type": "CHECKING",
            "bank_account_number": "32131231abc",
            "bank_routing_number": "121000358",
            "nickname": _ACH_NICKNAME,
        },
    )


def ensure_ach_relationship(account_id: str, account_owner_name: str) -> str:
    """Return a usable ACH relationship id, creating one only if needed."""
    for relationship in list_ach_relationships(account_id):
        if str(relationship.get("status", "")).upper() in _USABLE_ACH_STATUSES:
            return str(relationship["id"])
    return str(create_ach_relationship(account_id, account_owner_name)["id"])


def create_transfer(account_id: str, relationship_id: str, amount: Decimal) -> dict:
    """POST /v1/accounts/{id}/transfers — deposit cash.

    `amount` is sent as a decimal string, never a JSON float, so no cent is
    ever lost to binary floating point on the way out.
    """
    return _request(
        "POST",
        f"/v1/accounts/{account_id}/transfers",
        json={
            "transfer_type": "ach",
            "relationship_id": relationship_id,
            "amount": format(amount, "f"),
            "direction": "INCOMING",
            "timing": "immediate",
        },
    )


def create_journal(from_account: str, to_account: str, amount: Decimal) -> dict:
    """POST /v1/journals — move cash between two accounts (entry type JNLC).

    Funding via a journal from the firm account credits instantly and has no
    daily limit. ACH transfers, by contrast, are capped at 1 per direction per
    trading day and crawl through a simulated clearing pipeline in sandbox —
    we learned both the hard way (ADR-011).
    """
    return _request(
        "POST",
        "/v1/journals",
        json={
            "from_account": from_account,
            "to_account": to_account,
            "entry_type": "JNLC",
            "amount": format(amount, "f"),
        },
    )


def fund_account(account_id: str, amount: Decimal, account_owner_name: str) -> dict:
    """Top up a sandbox account.

    Preferred path: journal from the firm account (instant, unlimited).
    Fallback when no firm account is configured: ACH relationship + transfer.
    Both paths return the same shape: {id, status, amount}.
    """
    if settings.alpaca_firm_account_id:
        journal = create_journal(settings.alpaca_firm_account_id, account_id, amount)
        return {
            "id": str(journal.get("id", "")),
            "status": str(journal.get("status", "")),
            "amount": str(journal.get("net_amount") or journal.get("amount") or format(amount, "f")),
        }
    relationship_id = ensure_ach_relationship(account_id, account_owner_name)
    return create_transfer(account_id, relationship_id, amount)


# ---------------------------------------------------------------------------
# Market data (a different host, the same credentials)
# ---------------------------------------------------------------------------
#
# Broker API keys authenticate against data.sandbox.alpaca.markets too, so the
# app needs no second credential. Verified live 2026-08-26.
#
# Docs:
#   - Latest quote: https://docs.alpaca.markets/reference/stocklatestquotesingle-1
#   - Latest trade: https://docs.alpaca.markets/reference/stocklatesttradesingle-1
#   - Bars:         https://docs.alpaca.markets/reference/stockbarsingle-1
#
# FEED: we send no `feed` parameter, which lets Alpaca pick the best feed our
# subscription allows (SIP in this sandbox). If a feed we are not entitled to
# is refused - 403, or the 400 "subscription does not permit" family - we retry
# once on IEX, which every account can read.

_IEX_FALLBACK_STATUSES = {400, 401, 403}


def _data_request(path: str, params: dict | None = None) -> Any:
    url = settings.alpaca_data_base_url.rstrip("/") + path
    params = dict(params or {})
    try:
        response = _call("GET", url, path=path, params=params)
    except AlpacaError as exc:
        entitlement_problem = (
            exc.status_code in _IEX_FALLBACK_STATUSES
            and "feed" not in params
            and "subscription" in exc.message.lower()
        )
        if not entitlement_problem:
            raise
        response = _call("GET", url, path=path, params={**params, "feed": "iex"})
    # Prices arrive as JSON numbers here; keep their exact text (ADR-010).
    return _decode(response, numbers_as_strings=True)


def latest_quote(symbol: str) -> dict:
    """GET /v2/stocks/{symbol}/quotes/latest -> the quote object (bp/ap/bs/as/t)."""
    body = _data_request(f"/v2/stocks/{symbol}/quotes/latest")
    return (body or {}).get("quote") or {}


def latest_trade(symbol: str) -> dict:
    """GET /v2/stocks/{symbol}/trades/latest -> the trade object (p/s/t)."""
    body = _data_request(f"/v2/stocks/{symbol}/trades/latest")
    return (body or {}).get("trade") or {}


# How many bars one timeframe produces in a single regular session. Used only
# to guess how far back to ask; asking for too much is free, asking for too
# little silently truncates the chart.
_BARS_PER_SESSION = {"1Day": 1, "1Hour": 7, "15Min": 26, "5Min": 78, "1Min": 390}
BAR_TIMEFRAMES = tuple(_BARS_PER_SESSION)


def _bars_start(timeframe: str, limit: int) -> str:
    """A `start` date far enough back to contain `limit` bars.

    Alpaca defaults `start` to the beginning of today, so without this a
    request for 200 daily bars returns exactly one (verified live). We double
    the ideal span and add a week to absorb weekends and holidays.
    """
    sessions = math.ceil(limit / _BARS_PER_SESSION[timeframe])
    return (datetime.now(timezone.utc) - timedelta(days=sessions * 2 + 7)).date().isoformat()


def bars(symbol: str, timeframe: str, limit: int) -> list[dict]:
    """The most recent `limit` bars, oldest first.

    We ask newest-first (`sort=desc`) so the cut falls on the *old* end, then
    reverse - asking oldest-first would hand back the oldest `limit` bars in
    the window, which is the wrong end of the chart.
    """
    body = _data_request(
        f"/v2/stocks/{symbol}/bars",
        {
            "timeframe": timeframe,
            "limit": limit,
            "sort": "desc",
            "start": _bars_start(timeframe, limit),
        },
    )
    rows = (body or {}).get("bars") or []
    return list(reversed(rows))


# ---------------------------------------------------------------------------
# Clock and assets
# ---------------------------------------------------------------------------


def get_clock() -> dict:
    """GET /v1/clock - market open/closed plus the next open and close."""
    return _request("GET", "/v1/clock")


# Alpaca's assets endpoint has no search parameter, so symbol lookup means
# holding the list ourselves. It is ~14,000 rows / 6 MB of JSON and takes well
# under a second to fetch, but doing that per keystroke would be absurd - so
# one process-wide copy, refreshed at most every 15 minutes. The listing
# changes on the order of days.
_ASSETS_TTL_SECONDS = 900
_assets_cache: tuple[float, list[dict]] | None = None


def active_equity_assets(*, force_refresh: bool = False) -> list[dict]:
    """GET /v1/assets?status=active&asset_class=us_equity, memoised."""
    global _assets_cache
    now = time.monotonic()
    if not force_refresh and _assets_cache and now - _assets_cache[0] < _ASSETS_TTL_SECONDS:
        return _assets_cache[1]
    result = _request("GET", "/v1/assets", params={"status": "active", "asset_class": "us_equity"})
    assets = result if isinstance(result, list) else []
    _assets_cache = (now, assets)
    return assets


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
#
# Docs: https://docs.alpaca.markets/reference/createorderforaccount
#       https://docs.alpaca.markets/reference/getallordersforaccount


def create_order(account_id: str, payload: dict) -> dict:
    """POST /v1/trading/accounts/{id}/orders."""
    return _request("POST", f"/v1/trading/accounts/{account_id}/orders", json=payload)


def list_orders(account_id: str, status: str, limit: int) -> list[dict]:
    """GET .../orders - `direction=desc` is Alpaca's default, i.e. newest first."""
    result = _request(
        "GET",
        f"/v1/trading/accounts/{account_id}/orders",
        params={"status": status, "limit": limit, "direction": "desc"},
    )
    return result if isinstance(result, list) else []


def get_order(account_id: str, order_id: str) -> dict:
    """GET .../orders/{id} - 404 when the id belongs to nobody we can see."""
    return _request("GET", f"/v1/trading/accounts/{account_id}/orders/{order_id}")


def cancel_order(account_id: str, order_id: str) -> None:
    """DELETE .../orders/{id} - 204 on success, so there is nothing to return."""
    _request("DELETE", f"/v1/trading/accounts/{account_id}/orders/{order_id}")


# ---------------------------------------------------------------------------
# Positions and portfolio history
# ---------------------------------------------------------------------------


def list_positions(account_id: str) -> list[dict]:
    """GET /v1/trading/accounts/{id}/positions."""
    result = _request("GET", f"/v1/trading/accounts/{account_id}/positions")
    return result if isinstance(result, list) else []


def portfolio_history(account_id: str, period: str, timeframe: str) -> dict:
    """GET /v1/trading/accounts/{id}/account/portfolio/history.

    Unlike the rest of the Broker API this endpoint sends equity and P/L as
    JSON *numbers*, so we decode with the string hook to keep the cents exact.
    """
    return _request(
        "GET",
        f"/v1/trading/accounts/{account_id}/account/portfolio/history",
        params={"period": period, "timeframe": timeframe},
        numbers_as_strings=True,
    )


# ---------------------------------------------------------------------------
# Activities and documents
# ---------------------------------------------------------------------------
#
# Docs: https://docs.alpaca.markets/reference/getaccountactivities
#       https://docs.alpaca.markets/reference/getdocsforaccount


def list_activities(
    account_id: str,
    *,
    after: str | None = None,
    until: str | None = None,
    page_size: int = 100,
) -> list[dict]:
    """GET /v1/accounts/activities?account_id=... - newest first."""
    params: dict[str, Any] = {
        "account_id": account_id,
        "page_size": page_size,
        "direction": "desc",
    }
    if after:
        params["after"] = after
    if until:
        params["until"] = until
    result = _request("GET", "/v1/accounts/activities", params=params)
    return result if isinstance(result, list) else []


def list_documents(account_id: str) -> list[dict]:
    """GET /v1/accounts/{id}/documents."""
    result = _request("GET", f"/v1/accounts/{account_id}/documents")
    return result if isinstance(result, list) else []


def document_download_url(account_id: str, document_id: str) -> str:
    """The short-lived signed URL Alpaca redirects a document download to.

    The endpoint answers `301 Moved Permanently` with a presigned S3 link
    (~15 minutes, no auth of its own). We stop the redirect here so our own
    Basic credentials are never sent to S3, and so the caller can decide
    whether to stream the bytes or hand the link to the browser.
    """
    path = f"/v1/accounts/{account_id}/documents/{document_id}/download"
    url = settings.alpaca_broker_base_url.rstrip("/") + path
    response = _call("GET", url, path=path, follow_redirects=False)
    location = response.headers.get("location")
    if not location:
        raise AlpacaError("document download returned no location", status_code=502)
    return location
