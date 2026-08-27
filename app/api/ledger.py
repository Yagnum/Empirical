"""The fills ledger and FIFO realized P/L.

WHY THIS EXISTS
    Alpaca tells you the unrealized P/L of a position you still hold. The
    moment you sell it, the position disappears and so does its cost basis —
    the broker has no "you made $12.40 on that NVDA trade" to give us. The
    activity feed still lists both executions, though, so the number is
    *derivable*; it just has to be derived by somebody, and that somebody is
    this module.

HOW
    1. `sync_fills`  copies FILL / PARTIAL_FILL activities into `fills`,
       keyed on Alpaca's activity id. Re-running inserts nothing new.
    2. `match_lots`  walks the unprocessed fills in time order. A buy opens a
       lot. A sell eats open lots oldest-first (FIFO), decrementing
       `qty_open`, and writes one `realized_pnl` row for the whole sell.

    Both are idempotent, because both are called on ordinary page loads
    (`GET /activities`, `GET /positions`) and a page load must be safe to
    repeat. Idempotency is enforced by data, not by flags: a buy is done when
    a lot points at it, a sell is done when a realized_pnl row points at it.

ARITHMETIC
    Decimal end to end (ADR-010). `qty * price` on binary floats would put the
    ledger a fraction of a cent out on the first trade and further out on
    every trade after it. NUMERIC in, Decimal through, string out.

KNOWN LIMIT
    We match against the history we have. If a sell's opening buy is older
    than the window we synced, the sell matches partially or not at all — we
    then record only the part we can price rather than inventing a zero cost
    basis, which would report the entire proceeds as profit. See
    `_match_sell`.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import alpaca
import db
from models import Fill, Lot, RealizedPnl

# Alpaca activity codes that are an execution. Everything else in the feed is
# cash movement and belongs to no lot.
FILL_TYPES = {"FILL", "PARTIAL_FILL"}

METHOD = "FIFO"

ZERO = Decimal("0")
CENTS = Decimal("0.01")

# The dashboard polls. Re-asking Alpaca for the same activity page every few
# seconds would spend our rate limit on data we already have, so one account's
# window is re-synced at most this often *within one process*. Correctness is
# unaffected: a fill that lands inside the window is picked up by the next
# call, and nothing downstream caches the derived numbers.
SYNC_TTL_SECONDS = 15.0
_last_sync: dict[tuple[str, str, str], float] = {}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _moment(value) -> datetime | None:
    """Alpaca's RFC-3339 timestamp as an aware UTC datetime.

    A naive datetime in a ledger sorts wrongly across a DST boundary and
    compares wrongly against a `timestamptz` column, so anything that arrives
    without a zone is declared UTC — which is what Alpaca means.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def is_buy(side: str) -> bool:
    """`buy`, `buy_to_cover` -> True. `sell`, `sell_short` -> False."""
    return str(side or "").lower().startswith("buy")


def money(value: Decimal | None) -> str:
    """A dollar amount as a string, rounded to the cent for presentation.

    Rounded here and only here: the stored NUMERIC keeps full precision, so
    a display choice can never work its way back into the ledger.
    """
    if value is None:
        return ""
    return format(value.quantize(CENTS, rounding=ROUND_HALF_UP), "f")


def _day_bounds(after: str | None, until: str | None) -> tuple[datetime | None, datetime | None]:
    """YYYY-MM-DD strings -> a half-open UTC interval, `until` inclusive."""
    start = _moment(f"{after}T00:00:00Z") if after else None
    end = _moment(f"{until}T00:00:00Z") if until else None
    if end is not None:
        end = end + timedelta(days=1)
    return start, end


# ---------------------------------------------------------------------------
# 1. Sync: Alpaca activities -> fills
# ---------------------------------------------------------------------------


def sync_fills(
    session: Session,
    account_id: str,
    *,
    after: str | None = None,
    until: str | None = None,
    page_size: int = 100,
) -> int:
    """Copy this account's executions into `fills`. Returns rows inserted.

    The upsert key is `alpaca_activity_id`, and we do the read-then-insert by
    hand rather than with Postgres' `ON CONFLICT`: a plain SELECT of the ids
    we already hold is portable (the test suite can run on SQLite), tells us
    in one query whether there is any work at all, and is not measurably
    slower at statement scale. A concurrent syncer that beats us to a row
    loses the unique constraint instead, which we absorb per row.
    """
    activities = alpaca.list_activities(account_id, after=after, until=until, page_size=page_size)
    executions = [row for row in activities if str(row.get("activity_type") or "").upper() in FILL_TYPES]
    if not executions:
        return 0

    ids = [str(row.get("id") or "") for row in executions if row.get("id")]
    known = set(
        session.scalars(select(Fill.alpaca_activity_id).where(Fill.alpaca_activity_id.in_(ids))).all()
    )
    inserted = 0
    for row in executions:
        activity_id = str(row.get("id") or "")
        if not activity_id or activity_id in known:
            continue
        qty = _decimal(row.get("qty"))
        price = _decimal(row.get("price"))
        occurred_at = _moment(row.get("transaction_time"))
        if qty is None or price is None or occurred_at is None:
            # A fill with no quantity, no price or no time cannot be matched
            # against a lot. Skipping keeps a malformed row out of the ledger
            # instead of poisoning every P/L figure derived from it.
            print(f"[ledger] skipping unusable fill activity {activity_id}", file=sys.stderr)
            continue
        fill = Fill(
            alpaca_activity_id=activity_id,
            alpaca_account_id=account_id,
            alpaca_order_id=str(row.get("order_id") or "") or None,
            symbol=str(row.get("symbol") or "").upper(),
            side=str(row.get("side") or "").lower(),
            qty=qty,
            price=price,
            occurred_at=occurred_at,
        )
        try:
            with session.begin_nested():  # SAVEPOINT: one bad row, not the batch
                session.add(fill)
            inserted += 1
        except IntegrityError:
            # Another worker inserted the same activity between our SELECT and
            # this INSERT. That is the constraint doing its job, not an error.
            continue
    return inserted


# ---------------------------------------------------------------------------
# 2. Match: fills -> lots + realized P/L
# ---------------------------------------------------------------------------


def _unprocessed_fills(session: Session, account_id: str) -> list[Fill]:
    """Fills with no lot (buys) and no realized row (sells), oldest first.

    This is the whole idempotency mechanism. A second call finds nothing left
    to do and returns immediately, so calling `match_lots` on every page load
    costs one indexed query.
    """
    opened = select(Lot.opened_by_fill_id).where(Lot.alpaca_account_id == account_id)
    matched = select(RealizedPnl.sell_fill_id).where(RealizedPnl.alpaca_account_id == account_id)
    statement = (
        select(Fill)
        .where(
            Fill.alpaca_account_id == account_id,
            Fill.id.not_in(opened),
            Fill.id.not_in(matched),
        )
        .order_by(Fill.occurred_at, Fill.id)
    )
    return list(session.scalars(statement).all())


def _open_lots(session: Session, account_id: str, symbol: str) -> list[Lot]:
    """Lots of one symbol that still hold shares, oldest first — the F in FIFO."""
    statement = (
        select(Lot)
        .where(
            Lot.alpaca_account_id == account_id,
            Lot.symbol == symbol,
            Lot.qty_open > ZERO,
        )
        .order_by(Lot.opened_at, Lot.id)
    )
    return list(session.scalars(statement).all())


def _open_buy(session: Session, fill: Fill) -> None:
    session.add(
        Lot(
            alpaca_account_id=fill.alpaca_account_id,
            symbol=fill.symbol,
            opened_by_fill_id=fill.id,
            qty_open=fill.qty,
            qty_initial=fill.qty,
            unit_cost=fill.price,
            opened_at=fill.occurred_at,
        )
    )


def _match_sell(session: Session, fill: Fill) -> bool:
    """Consume open lots FIFO for one sell fill. True when a row was written.

    Returns False — writing nothing — when there is no open lot to price the
    sale against. That happens only when the sell's opening buy predates the
    history we synced. Recording a zero cost basis there would tell the user
    the whole sale was profit, so we would rather report `realized_pl: null`
    and let a deeper sync fill it in later.
    """
    remaining = Decimal(fill.qty)
    cost_basis = ZERO
    matched_qty = ZERO

    for lot in _open_lots(session, fill.alpaca_account_id, fill.symbol):
        if remaining <= ZERO:
            break
        take = lot.qty_open if lot.qty_open < remaining else remaining
        cost_basis += take * lot.unit_cost
        matched_qty += take
        remaining -= take
        lot.qty_open = lot.qty_open - take
        if lot.qty_open <= ZERO:
            # The lot is spent. `qty_initial` and `unit_cost` stay put, so the
            # original purchase is still readable years later.
            lot.closed_at = fill.occurred_at

    if matched_qty <= ZERO:
        print(
            f"[ledger] sell fill {fill.alpaca_activity_id} ({fill.symbol}) has no open lot to match; "
            "leaving it unmatched rather than assuming a zero cost basis",
            file=sys.stderr,
        )
        return False
    if remaining > ZERO:
        print(
            f"[ledger] sell fill {fill.alpaca_activity_id} ({fill.symbol}) matched only "
            f"{matched_qty} of {fill.qty} shares; history is shorter than the position",
            file=sys.stderr,
        )

    proceeds = matched_qty * fill.price
    session.add(
        RealizedPnl(
            alpaca_account_id=fill.alpaca_account_id,
            symbol=fill.symbol,
            sell_fill_id=fill.id,
            qty=matched_qty,
            proceeds=proceeds,
            cost_basis=cost_basis,
            realized=proceeds - cost_basis,
            method=METHOD,
            occurred_at=fill.occurred_at,
        )
    )
    return True


def match_lots(session: Session, account_id: str) -> int:
    """Turn unprocessed fills into lots and realized P/L. Returns sells matched.

    Fills are walked in execution order, so a buy always opens its lot before
    a later sell can eat it. Anything already processed is skipped by
    `_unprocessed_fills`, which is what makes this safe on every page load.
    """
    pending = _unprocessed_fills(session, account_id)
    if not pending:
        return 0

    session.flush()  # fills need ids before a lot can point at one
    matched = 0
    for fill in pending:
        if is_buy(fill.side):
            _open_buy(session, fill)
            # Flush so a sell later in this same batch can see the new lot.
            session.flush()
        elif _match_sell(session, fill):
            matched += 1
            session.flush()
    return matched


# ---------------------------------------------------------------------------
# 3. The call routes make
# ---------------------------------------------------------------------------


def refresh(
    account_id: str,
    *,
    after: str | None = None,
    until: str | None = None,
    force: bool = False,
) -> None:
    """Bring the ledger up to date. Best-effort: never raises.

    A read route that shows P/L should still render if Alpaca is slow or the
    database is down — the numbers it derives are a convenience on top of
    Alpaca's own truth, not the truth itself. So this swallows everything and
    complains to stderr, exactly like `audit.record`.
    """
    if not db.is_configured():
        return
    key = (account_id, after or "", until or "")
    now = time.monotonic()
    if not force and now - _last_sync.get(key, 0.0) < SYNC_TTL_SECONDS:
        return
    try:
        with db.session_scope() as session:
            sync_fills(session, account_id, after=after, until=until)
            match_lots(session, account_id)
        _last_sync[key] = now
    except Exception as exc:  # noqa: BLE001 - see the docstring
        print(f"[ledger] refresh failed for {account_id}: {type(exc).__name__}: {exc}", file=sys.stderr)


def realized_by_activity_id(
    session: Session, account_id: str, activity_ids: Iterable[str]
) -> dict[str, Decimal]:
    """{alpaca_activity_id -> realized} for the sells among these activities.

    Keyed by the activity id because that is what `GET /activities` calls a
    row's `id`; the frontend can then line the two up without a second call.
    """
    ids = [value for value in activity_ids if value]
    if not ids:
        return {}
    statement = (
        select(Fill.alpaca_activity_id, RealizedPnl.realized)
        .join(RealizedPnl, RealizedPnl.sell_fill_id == Fill.id)
        .where(Fill.alpaca_account_id == account_id, Fill.alpaca_activity_id.in_(ids))
    )
    return {row[0]: row[1] for row in session.execute(statement)}


def realized_summary(
    session: Session,
    account_id: str,
    *,
    after: str | None = None,
    until: str | None = None,
) -> dict:
    """Realized P/L for a date range: one total plus a per-symbol breakdown.

    Summed in Python over the matched rows rather than with SUM() in SQL, so
    the arithmetic is the same Decimal arithmetic that produced the rows and
    the total is guaranteed to equal the parts. A paper-trading account has
    tens of rows, not millions.
    """
    start, end = _day_bounds(after, until)
    statement = select(RealizedPnl).where(RealizedPnl.alpaca_account_id == account_id)
    if start is not None:
        statement = statement.where(RealizedPnl.occurred_at >= start)
    if end is not None:
        statement = statement.where(RealizedPnl.occurred_at < end)

    total = ZERO
    per_symbol: dict[str, list] = {}
    for row in session.scalars(statement.order_by(RealizedPnl.occurred_at)):
        total += row.realized
        bucket = per_symbol.setdefault(row.symbol, [ZERO, 0])
        bucket[0] += row.realized
        bucket[1] += 1

    by_symbol = [
        {"symbol": symbol, "realized": money(amount), "trades": trades}
        for symbol, (amount, trades) in sorted(per_symbol.items())
    ]
    return {"total": money(total), "by_symbol": by_symbol, "method": METHOD}


def preview_cost_basis(session: Session, account_id: str, symbol: str, qty: Decimal) -> dict:
    """What selling `qty` shares now would cost-base against, before it happens.

    The read-only twin of `_match_sell`: it walks the same open lots in the
    same order and does the same take-from-each arithmetic, but writes
    nothing — the order ticket asks this on every quantity change, and a
    preview must never move the ledger it is previewing. Because both walk
    identically, the estimate the ticket shows is the figure `match_lots`
    will record when the sell actually fills (at whatever price it fills).

    `matched_qty` can come back smaller than `qty`: the open lots hold fewer
    shares than the caller wants to sell, either because our synced history
    is shorter than the position (see KNOWN LIMIT above) or because they are
    simply selling more than they hold. `cost_basis` and `avg_unit_cost` are
    null in the nothing-matched case — a null beats a fabricated zero, which
    would present the entire sale as profit.
    """
    remaining = qty
    cost_basis = ZERO
    matched = ZERO
    for lot in _open_lots(session, account_id, symbol):
        if remaining <= ZERO:
            break
        take = lot.qty_open if lot.qty_open < remaining else remaining
        cost_basis += take * lot.unit_cost
        matched += take
        remaining -= take

    # NUMERIC(28,10) comes back as "3.0000000000"; normalize() drops the
    # trailing zeros and format(..., "f") keeps 1E+2 from leaking out as
    # exponent notation.
    return {
        "symbol": symbol,
        "qty": format(qty.normalize(), "f"),
        "matched_qty": format(matched.normalize(), "f"),
        "cost_basis": money(cost_basis) if matched > ZERO else None,
        "avg_unit_cost": money(cost_basis / matched) if matched > ZERO else None,
        "method": METHOD,
    }
