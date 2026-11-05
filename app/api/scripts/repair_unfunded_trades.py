"""Undo the cash moved by weekend trades that settled without being funded (ADR-034).

Usage (from app/api):
    uv run python scripts/repair_unfunded_trades.py            # dry run: list the corrections
    uv run python scripts/repair_unfunded_trades.py --write    # post them

Until ADR-034, a refused opening journal left a trade alive, and settlement then
ran it as if it had been funded. The real order was real: the shares did trade,
at the broker, for the customer's own account, which is the outcome of an ordinary
order. What should not have happened is any firm <-> trader cash around it. So
each trade's correct net is zero, and the correction is the opposite of what its
journals actually moved, read from its own event trail.

One tagged journal per trade, recorded as a `cash_repaired` event, so a rerun skips
what is done and every correction can be traced to the trade it belongs to. The
trades keep their `settled` state: their prices are real and the research reads
them. Money to traders goes first, so an account owing cash has the best chance of
having it. A refused journal is reported and left for a rerun.
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_, select  # noqa: E402

import alpaca  # noqa: E402
import db  # noqa: E402
import weekend  # noqa: E402
from config import settings  # noqa: E402
from models import WeekendTrade, WeekendTradeEvent  # noqa: E402

# Which way each journal kind moves cash, seen from the trader.
TO_TRADER = {"advance_paid", "escrow_released", "escrow_refunded", "hedge_prefunded"}
FROM_TRADER = {"escrow_reserved", "charge_paid", "shortfall_debited"}


def net_to_trader(trade: WeekendTrade, events: list[WeekendTradeEvent]) -> Decimal:
    """What the trade's recorded journals moved to the trader, net."""
    net = Decimal("0")
    for event in events:
        amount = event.amount or Decimal("0")
        if event.kind in TO_TRADER:
            net += amount
        elif event.kind in FROM_TRADER:
            net -= amount
        elif event.kind == "hedge_swept":
            # A sell's proceeds went to the firm; a buy's fill was reimbursed.
            net += -amount if trade.side == "sell" else amount
    return net


def main() -> None:
    write = "--write" in sys.argv
    if not db.is_configured():
        sys.exit("DATABASE_URL is not set; cannot read weekend trades")
    firm = settings.alpaca_firm_account_id
    if not firm:
        sys.exit("ALPACA_FIRM_ACCOUNT_ID is not set")

    with db.session_scope() as session:
        rows = session.execute(
            select(WeekendTrade)
            .where(
                WeekendTrade.state.in_(("settled", "breached")),
                or_(WeekendTrade.escrow_journal_id.is_(None), WeekendTrade.advance_journal_id.is_(None)),
            )
            .order_by(WeekendTrade.id)
        )
        plan = []
        for (trade,) in rows:
            events = weekend.trade_events(session, trade)
            kinds = {event.kind for event in events}
            filled = "hedge_filled" in kinds
            net = net_to_trader(trade, events)
            plan.append((trade, net, filled, "cash_repaired" in kinds))

        # Trader-owed corrections (net < 0) first.
        plan.sort(key=lambda item: item[1])
        total_in = total_out = Decimal("0")
        posted = refused = 0
        print(f"{len(plan)} unfunded settled trade(s):")
        for trade, net, filled, done in plan:
            correction = -net
            direction = "firm -> trader" if correction > 0 else "trader -> firm"
            note = "already repaired" if done else ("" if filled else "NO FILL RECORDED, skipped")
            print(
                f"  #{trade.id} {trade.side} {format(trade.qty.normalize(), 'f')} {trade.symbol} "
                f"account {trade.alpaca_account_id[:8]}: moved {net:.2f} to trader; "
                f"correct {abs(correction):.2f} {direction} {note}"
            )
            if done or not filled or abs(correction) < Decimal("0.01"):
                continue
            if correction > 0:
                total_in += correction
            else:
                total_out += -correction
            if not write:
                continue
            source, target = (firm, trade.alpaca_account_id) if correction > 0 else (trade.alpaca_account_id, firm)
            amount = abs(correction).quantize(Decimal("0.01"))
            description = f"Repair of unfunded weekend trade {trade.id}"
            try:
                journal = alpaca.create_journal(source, target, amount, description=description)
            except alpaca.AlpacaError as exc:
                refused += 1
                print(f"    REFUSED: {exc.message}")
                continue
            session.add(
                WeekendTradeEvent(
                    trade_id=trade.id,
                    kind="cash_repaired",
                    amount=amount,
                    alpaca_ref=str(journal.get("id", "")) or None,
                    detail=f"{description}: {direction} (ADR-034)",
                )
            )
            session.commit()
            posted += 1
        print(f"\nto traders {total_in:.2f}; to the firm {total_out:.2f}")
        if write:
            print(f"posted {posted}, refused {refused}")
        else:
            print("dry run. Pass --write to post them.")


if __name__ == "__main__":
    main()
