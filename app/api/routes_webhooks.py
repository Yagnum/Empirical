"""The Clerk offboarding webhook (ADR-013, ADR-015).

    POST /webhooks/clerk   Clerk `user.deleted` -> close the Alpaca account

When a user deletes their Clerk login, Clerk delivers a `user.deleted` event
here (via Svix, its webhook carrier). We then run the ADR-013 closure: cancel
orders, liquidate positions, journal the cash back to the firm sweep account,
retire the contact email, close the account.

NO SESSION TOKEN — THE SIGNATURE IS THE AUTH
    There is no user behind a webhook, so this is the one route besides
    /health outside the Clerk dependency chain. Instead every delivery is
    signed (HMAC-SHA256 over `id.timestamp.body`, Svix's scheme) and we
    verify it ourselves — the scheme is four lines of stdlib, not worth a
    dependency. A missing or wrong signature is a 401; a timestamp more than
    five minutes off is a 401 (replay protection); an unconfigured signing
    secret is a 503, because silently accepting unsigned events would turn
    "forgot a secret" into "anyone can close any account".

THE USER IS ALREADY GONE FROM CLERK
    By the time this event arrives, the Clerk user record — and the private
    metadata that held the Alpaca account id — has been deleted. The audit
    log is the memory that outlives the user (ADR-015): we look up the
    latest `audit_log` row for that Clerk user id that carries an account
    id. No row means the user never had an account, and the honest answer
    is 204. No database means we cannot even look, so 503 — Svix retries,
    and the ops fallback is `scripts/close_account.py`.

SVIX RETRIES ARE THE COMPLETION MECHANISM — deliberately.
    Liquidation is asynchronous: with the market closed, the closing orders
    queue until the next open. Rather than run our own scheduler, this route
    answers 503 `liquidation_pending` while positions remain, and Svix
    redelivers on its backoff schedule (spanning about a day). Each retry
    finds the account flatter and advances the closure; the delivery that
    finds it flat journals the cash and closes. The offboarding audit rows
    written along the way carry the account id themselves, so the lookup
    above keeps working across retries.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

import alpaca
import audit
import db
import offboarding
from config import settings
from models import AuditLog

router = APIRouter(tags=["webhooks"])

# Svix's own default tolerance. Any wider invites replays; any narrower
# punishes ordinary clock skew.
_TIMESTAMP_TOLERANCE_SECONDS = 5 * 60

# What Alpaca calls a closed account has varied across API surfaces; treat
# any of them as "nothing left to do" (same set as `find_account_by_email`).
_CLOSED_STATUSES = {"ACCOUNT_CLOSED", "CLOSED"}


def signature_valid(headers: Headers, raw_body: bytes) -> bool:
    """Verify a Svix delivery signature against our signing secret.

    The signed content is `{svix-id}.{svix-timestamp}.` + the raw body
    *bytes* — not the parsed-and-reserialized JSON, which is why the route
    reads the body before anything else touches it. The key is the base64
    decode of the secret after its `whsec_` prefix; the expected signature
    is base64(HMAC-SHA256). `svix-signature` may hold several space-
    separated `v1,<base64>` entries (Svix rotates keys); any one matching
    accepts. Comparisons use `hmac.compare_digest` so a mismatch takes the
    same time however early the bytes diverge.
    """
    svix_id = headers.get("svix-id", "")
    svix_timestamp = headers.get("svix-timestamp", "")
    svix_signature = headers.get("svix-signature", "")
    if not (svix_id and svix_timestamp and svix_signature):
        return False

    try:
        timestamp = int(svix_timestamp)
    except ValueError:
        return False
    if abs(time.time() - timestamp) > _TIMESTAMP_TOLERANCE_SECONDS:
        return False

    secret = settings.clerk_webhook_signing_secret
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except ValueError:
        return False  # a malformed secret can never verify anything

    signed_content = f"{svix_id}.{svix_timestamp}.".encode() + raw_body
    expected = base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest()).decode()
    return any(
        version == "v1" and hmac.compare_digest(signature, expected)
        for version, _, signature in (entry.partition(",") for entry in svix_signature.split())
    )


@router.post("/webhooks/clerk")
async def clerk_webhook(request: Request) -> Response:
    """Verify the Svix signature, then act on `user.deleted`.

    `async` only to read the raw body (the exact bytes are what is signed);
    the blocking work then runs in a worker thread via `run_in_threadpool`,
    same as every `def` route in this codebase.
    """
    raw_body = await request.body()
    return await run_in_threadpool(_handle, request, raw_body)


def _handle(request: Request, raw_body: bytes) -> Response:
    if not settings.clerk_webhook_signing_secret:
        raise HTTPException(
            status_code=503,
            detail="webhook_not_configured: CLERK_WEBHOOK_SIGNING_SECRET is not set",
        )
    if not signature_valid(request.headers, raw_body):
        raise HTTPException(status_code=401, detail="invalid_webhook_signature")

    try:
        event = json.loads(raw_body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_webhook_payload") from exc

    # Clerk sends every event type the endpoint is subscribed to; anything
    # but a user deletion is acknowledged and dropped.
    if not isinstance(event, dict) or event.get("type") != "user.deleted":
        return Response(status_code=204)
    clerk_user_id = str((event.get("data") or {}).get("id") or "")
    if not clerk_user_id:
        return Response(status_code=204)

    if not db.is_configured():
        # We cannot map the user to an account without the audit log. Svix
        # will retry; the ops fallback is scripts/close_account.py.
        raise HTTPException(
            status_code=503,
            detail="offboarding_unavailable: no database to map the user to an account",
        )
    account_id = _latest_account_id(clerk_user_id)
    if not account_id:
        return Response(status_code=204)  # never onboarded; nothing to close

    with audit.audited(request, "account.offboard", user_id=clerk_user_id, account_id=account_id) as entry:
        try:
            return JSONResponse(_offboard(account_id, entry))
        except alpaca.AlpacaError as exc:
            raise alpaca.http_error(exc) from exc


def _latest_account_id(clerk_user_id: str) -> str | None:
    """The deleted user's Alpaca account, recovered from our own audit log.

    The newest row wins: a user who was re-provisioned after a sandbox reset
    has several account ids in the log, and only the latest is theirs.
    Walks `ix_audit_log_user_at`.
    """
    with db.session_scope() as session:
        return session.scalars(
            sa.select(AuditLog.alpaca_account_id)
            .where(
                AuditLog.clerk_user_id == clerk_user_id,
                AuditLog.alpaca_account_id.is_not(None),
            )
            .order_by(AuditLog.at.desc(), AuditLog.id.desc())
            .limit(1)
        ).first()


def _offboard(account_id: str, entry: audit.Entry) -> dict:
    """One delivery's worth of progress through the ADR-013 closure."""
    status = str(alpaca.get_account(account_id).get("status", "")).upper()
    if status in _CLOSED_STATUSES:
        # A retry after the delivery that closed it (or an ops closure).
        entry.detail = "already closed"
        return {"state": "already_closed", "alpaca_account_id": account_id}

    begun = offboarding.begin_liquidation(account_id)
    if begun is not None:
        positions, _open_orders = begun
        raise HTTPException(
            status_code=503,
            detail=f"liquidation_pending: {positions} position(s) still open; the retry will find the account flatter",
        )

    offboarding.cancel_open_orders(account_id)

    cash = offboarding.account_cash(account_id)
    if cash > 0:
        if not settings.alpaca_firm_account_id:
            raise HTTPException(
                status_code=503,
                detail="offboarding_unavailable: ALPACA_FIRM_ACCOUNT_ID is not configured",
            )
        offboarding.return_cash_to_firm(account_id, cash)

    alpaca.close_account(account_id)
    returned = format(cash, "f") if cash > 0 else "0"
    entry.detail = f"closed; returned={returned}"
    return {"state": "closed", "alpaca_account_id": account_id, "returned": returned}
