"""Realized profit and loss - the one number Alpaca cannot tell us.

    GET /pnl/realized?after=&until=

This is the first route in the API that reads *our* database instead of
forwarding a broker call. Everything else in Yagnum is a translation of
something Alpaca already knows; realized P/L is something Alpaca deliberately
forgets. A position carries `unrealized_pl` while you hold it, and the moment
you sell, position and cost basis both vanish. The fills stay in the activity
feed, so the number is recoverable - by keeping the fills, matching sells to
buys FIFO, and storing the result (ADR-014, `ledger.py`).

Money leaves here as strings, rounded to the cent (ADR-010). The sum is done
in Decimal over the stored rows, so `total` always equals the parts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

import clerk_auth
import db
import ledger

router = APIRouter(tags=["pnl"])

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


@router.get("/pnl/realized")
def realized(
    after: str | None = Query(None, pattern=DATE_PATTERN, description="YYYY-MM-DD, inclusive"),
    until: str | None = Query(None, pattern=DATE_PATTERN, description="YYYY-MM-DD, inclusive"),
    account_id: str = Depends(clerk_auth.require_account_id),
) -> dict:
    """Realized P/L over a date range: the total and a per-symbol breakdown.

    `trades` counts **sell fills**, not round trips: one sell that consumed
    three lots is one trade here, because that is the event the user performed
    and the row we stored.

    An account that has never sold anything gets `{"total": "0.00",
    "by_symbol": [], "method": "FIFO"}` - not a 404. "Nothing realized yet" is
    a perfectly good answer.
    """
    if not db.is_configured():
        # Honest rather than silently zero: a zero total would look like a
        # real answer and quietly misreport a profitable account.
        raise HTTPException(status_code=503, detail="ledger_unavailable")

    # Same refresh the dashboard routes do, so a direct call to this endpoint
    # is not the one place that shows stale numbers. Best-effort; never raises.
    ledger.refresh(account_id, after=after, until=until)

    with db.session_scope() as session:
        return ledger.realized_summary(session, account_id, after=after, until=until)
