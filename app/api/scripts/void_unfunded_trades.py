"""Mark open weekend trades whose opening cash never moved as `failed` (ADR-034).

Usage (from app/api):
    uv run python scripts/void_unfunded_trades.py            # dry run: list them
    uv run python scripts/void_unfunded_trades.py --write    # mark them failed

Until ADR-034, a refused opening journal left the trade `provisional`, and the
settlement job later traded the shares for it as if it had been funded. The
engine no longer does this. This clears the ones still open, so nothing tries to
settle them. It moves no money: a real order that already filled stays filled.

It deliberately leaves alone the trades that already settled this way. Their
books need a decision about repairing the sandbox cash, not a state change.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_, select  # noqa: E402

import db  # noqa: E402
import weekend  # noqa: E402
from models import WeekendTrade  # noqa: E402


def main() -> None:
    write = "--write" in sys.argv
    if not db.is_configured():
        sys.exit("DATABASE_URL is not set; cannot read weekend trades")

    with db.session_scope() as session:
        rows = session.execute(
            select(WeekendTrade)
            .where(
                WeekendTrade.state.in_(weekend.OPEN_STATES),
                or_(WeekendTrade.escrow_journal_id.is_(None), WeekendTrade.advance_journal_id.is_(None)),
            )
            .order_by(WeekendTrade.id)
        )
        trades = [trade for (trade,) in rows]
        print(f"{len(trades)} open trade(s) with no opening cash:")
        for trade in trades:
            print(f"  #{trade.id} {trade.side} {format(trade.qty, 'f')} {trade.symbol} [{trade.state}]")
        if not write:
            print("\ndry run. Pass --write to mark them failed.")
            return
        for trade in trades:
            weekend._fail_open(session, trade, "voided: the opening journal had failed and no money moved at open")
    print("done")


if __name__ == "__main__":
    main()
