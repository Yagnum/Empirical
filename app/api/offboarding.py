"""Flatten an account and return its cash — the shared middle of ADR-015.

Two routes need the same sequence: liquidate positions, cancel open orders,
journal every dollar back to the firm sweep account.

    POST /webhooks/clerk   offboarding after a Clerk user deletion (ADR-013):
                           it then retires the email and closes the account.
    POST /accounts/reset   the "reset my balance" button: the account stays
                           open at $0 and the funding form takes over.

Only those endings differ, so the flatten-and-return steps live here once.
Everything raises `alpaca.AlpacaError` on a broker failure; the routes
translate with `alpaca.http_error` so each keeps its own audit context.

CHUNKED JOURNALS: the sandbox refuses a JNLC over $100,000 in a single
transaction, so a large balance travels as several journals of at most
$100,000 each. All arithmetic is Decimal (ADR-010) — the chunks always sum
to exactly the balance, which a float split could not promise.
"""

from __future__ import annotations

from decimal import Decimal

import alpaca
from config import settings

# The sandbox JNLC per-transaction limit (docs/ALPACA-FUNDING.md, ADR-015).
JOURNAL_CHUNK_MAX = Decimal("100000")

# More open orders than this on a paper account would be a bug elsewhere;
# the cap just bounds one webhook delivery's work.
_OPEN_ORDERS_LIMIT = 500


def begin_liquidation(account_id: str) -> tuple[int, int] | None:
    """Submit close-all if any positions are open; None when already flat.

    Returns `(positions, open_orders)` counts as they stood at submission —
    what the caller reports while the closing orders work. With the market
    shut those orders queue until the next open, so "submitted" can be days
    from "flat"; callers poll `list_positions` (or wait for a Svix retry)
    rather than pretend this call finished the job.
    """
    positions = alpaca.list_positions(account_id)
    if not positions:
        return None
    open_orders = alpaca.list_orders(account_id, status="open", limit=_OPEN_ORDERS_LIMIT)
    alpaca.close_all_positions(account_id)
    return len(positions), len(open_orders)


def cancel_open_orders(account_id: str) -> int:
    """Cancel every open order, one DELETE each; returns how many.

    Reached only when the account is already flat — close-all cancels orders
    itself — so this covers the leftover case: no positions, but a working
    buy that would spend the cash we are about to journal away.
    """
    orders = alpaca.list_orders(account_id, status="open", limit=_OPEN_ORDERS_LIMIT)
    for order in orders:
        alpaca.cancel_order(account_id, str(order["id"]))
    return len(orders)


def account_cash(account_id: str) -> Decimal:
    """The account's cash balance, as the Decimal of Alpaca's own string."""
    return Decimal(str(alpaca.get_trading_account(account_id).get("cash") or "0"))


def journal_chunks(amount: Decimal) -> list[Decimal]:
    """Split an amount into journal-sized pieces, each at most $100,000.

    `$250,000 -> [100000, 100000, 50000]`. The pieces sum to exactly the
    input; Decimal subtraction is exact, so no cent is created or lost at a
    chunk boundary.
    """
    chunks: list[Decimal] = []
    remaining = amount
    while remaining > 0:
        chunk = min(remaining, JOURNAL_CHUNK_MAX)
        chunks.append(chunk)
        remaining -= chunk
    return chunks


def return_cash_to_firm(account_id: str, cash: Decimal) -> None:
    """Journal `cash` back to the firm sweep account, in ≤$100k chunks.

    Direction: FROM the user's account TO the firm account — the mirror of
    funding (ADR-011). Callers verify `settings.alpaca_firm_account_id` is
    configured first, because each owes its own error slug when it is not.
    """
    for chunk in journal_chunks(cash):
        alpaca.create_journal(account_id, settings.alpaca_firm_account_id, chunk)
