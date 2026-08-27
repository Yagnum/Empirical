"""The audit trail: one row per state-changing request.

ADR-014's first table, and the one with the simplest rule — **an audit write
must never fail a user's request**. A trade that Alpaca accepted is a trade
whether or not we managed to write a log line about it, and turning a
successful order into a 500 because Postgres blinked would be the worst
possible trade-off. So every write here is wrapped, and a failure goes to
stderr and nowhere else.

The same reasoning covers a missing database: with `DATABASE_URL` unset the
recorder does nothing at all and the API behaves exactly as it did before
ADR-014.

WHAT GOES IN `detail`
    A short, non-secret sentence: an error slug, a symbol and side, a
    quantity. Never a token, never a request body, never a URL with
    credentials in it. This table is read by humans during incidents; it must
    be safe to paste into a ticket.

USAGE — as a context manager at the end of the route's work:

    with audit.audited(request, "order.place", user_id=user_id,
                       account_id=account_id) as entry:
        order = alpaca.create_order(...)
        entry.detail = f"{body.side} {body.symbol}"
        return shape_order(order)

The success row is written when the block exits cleanly; an HTTPException
raised inside writes an `error` row with its status and re-raises untouched.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import HTTPException, Request

import db
from models import AuditLog

# Postgres would accept far more, but a log line is a summary, not a payload.
MAX_DETAIL = 500

REQUEST_ID_HEADER = "X-Request-ID"


def new_request_id() -> str:
    """A fresh correlation id. Short enough to read out over a call."""
    return uuid.uuid4().hex[:16]


def request_id(request: Request | None) -> str:
    """The id the middleware stamped on this request, if there is one."""
    if request is None:
        return ""
    return str(getattr(request.state, "request_id", "") or "")


@dataclass
class Entry:
    """The mutable half of an audit row: what only the route body knows."""

    action: str
    clerk_user_id: str
    alpaca_account_id: str | None = None
    detail: str | None = None
    outcome: str = "ok"
    status_code: int = 200


def _short(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:MAX_DETAIL]


def record(
    *,
    action: str,
    clerk_user_id: str,
    method: str,
    path: str,
    outcome: str,
    status_code: int,
    alpaca_account_id: str | None = None,
    detail: str | None = None,
    request_id: str = "",
) -> None:
    """Write one audit row. Never raises — that is the entire contract.

    Uses its own short-lived session rather than the request's, so an audit
    write cannot poison a transaction the route still cares about (and so a
    row still lands when the route is about to return an error).
    """
    if not db.is_configured():
        return
    try:
        with db.session_scope() as session:
            session.add(
                AuditLog(
                    clerk_user_id=clerk_user_id[:64],
                    alpaca_account_id=(alpaca_account_id or None),
                    method=method[:8],
                    path=path[:256],
                    action=action[:64],
                    outcome="ok" if outcome == "ok" else "error",
                    status_code=int(status_code),
                    detail=_short(detail),
                    request_id=(request_id or new_request_id())[:64],
                )
            )
    except Exception as exc:  # noqa: BLE001 - deliberately swallowing everything
        # stderr, not the response. The user's order already happened.
        print(f"[audit] failed to record {action}: {type(exc).__name__}: {exc}", file=sys.stderr)


@contextmanager
def audited(
    request: Request | None,
    action: str,
    *,
    user_id: str,
    account_id: str | None = None,
) -> Iterator[Entry]:
    """Record the outcome of the block, whichever way it ends.

    Success writes `outcome="ok"` with status 200. An `HTTPException` writes
    `outcome="error"` with its real status and detail, then re-raises so the
    client still sees exactly the error the route meant to send. Any other
    exception is logged as a 500 and re-raised.
    """
    entry = Entry(action=action, clerk_user_id=user_id, alpaca_account_id=account_id)
    try:
        yield entry
    except HTTPException as exc:
        entry.outcome = "error"
        entry.status_code = exc.status_code
        entry.detail = _short(exc.detail) or entry.detail
        _flush(request, entry)
        raise
    except Exception as exc:
        entry.outcome = "error"
        entry.status_code = 500
        entry.detail = entry.detail or type(exc).__name__
        _flush(request, entry)
        raise
    else:
        _flush(request, entry)


def _flush(request: Request | None, entry: Entry) -> None:
    record(
        action=entry.action,
        clerk_user_id=entry.clerk_user_id,
        method=(request.method if request else ""),
        path=(request.url.path if request else ""),
        outcome=entry.outcome,
        status_code=entry.status_code,
        alpaca_account_id=entry.alpaca_account_id,
        detail=entry.detail,
        request_id=request_id(request),
    )
