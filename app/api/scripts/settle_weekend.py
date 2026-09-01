"""Settle every open weekend trade into the first regulated session (ADR-023).

Usage (from app/api):
    uv run python scripts/settle_weekend.py            # dry run: list what would settle
    uv run python scripts/settle_weekend.py --write    # place the hedges and reconcile

The GitHub Actions cron (.github/workflows/settle-weekend.yml) runs the
--write form every ten minutes from 8:00 AM ET on weekday mornings. Each
run is idempotent: a trade that is still `awaiting_settlement` gets its
order checked again; a settled one is left alone; a run during a weekend
or holiday does nothing at all, because there is no session to settle
into.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
import sessions  # noqa: E402
import weekend  # noqa: E402


def main() -> None:
    write = "--write" in sys.argv
    if not db.is_configured():
        sys.exit("DATABASE_URL is not set; cannot read weekend trades")

    live = sessions.scheduled_session()
    print(f"session now: {live}")
    if live == sessions.WEEKEND:
        print("no regulated session is open; nothing to settle into")
        return

    with db.session_scope() as session:
        open_trades = weekend.list_open_trades(session)
        if not open_trades:
            print("no open weekend trades")
            return
        print(f"{len(open_trades)} open weekend trade(s):")
        for trade in open_trades:
            print(
                f"  #{trade.id} {trade.side} {format(trade.qty, 'f')} {trade.symbol} "
                f"at {format(trade.p_open, '.2f')} [{trade.state}] account {trade.alpaca_account_id[:8]}"
            )
        if not write:
            print("\ndry run. Pass --write to settle them.")
            return

        summary = weekend.settle_all_open(session)
    print(
        f"settled {summary['settled']}, breached {summary['breached']}, "
        f"still awaiting {summary['awaiting']}, failed {summary['failed']}"
    )
    for line in summary["log"]:
        print("  " + line)
    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
