"""Settle every open weekend trade into the first regulated session (ADR-023).

Usage (from app/api):
    uv run python scripts/settle_weekend.py            # dry run: list what would settle
    uv run python scripts/settle_weekend.py --write    # place the hedges and reconcile
    uv run python scripts/settle_weekend.py --watch    # wait for the open, then settle

Each run is idempotent: a trade that is still `awaiting_settlement` gets its
order checked again; a settled one is left alone; a run during a weekend or
holiday does nothing at all, because there is no session to settle into.

WHY --watch (ADR-034). GitHub's cron is best effort. This job was scheduled every
ten minutes through the morning and in practice started once a day, hours after
the open. A job that starts late cannot settle at the open, but a job that starts
EARLY can simply wait. So the workflow fires well before the open, and this stays
alive until regular hours, settles, and keeps checking until nothing is left or
its time runs out.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
import sessions  # noqa: E402
import weekend  # noqa: E402


# How long --watch sleeps between looks, and how long it keeps settling after
# the open. The workflow's own timeout is the hard stop.
WATCH_POLL_SECONDS = 60
WATCH_SETTLE_PASSES = 30
WATCH_SETTLE_PAUSE_SECONDS = 300


def open_trade_count() -> int:
    with db.session_scope() as session:
        return len(weekend.list_open_trades(session))


def settle_once() -> dict:
    with db.session_scope() as session:
        return weekend.settle_all_open(session)


def report(summary: dict) -> None:
    print(
        f"settled {summary['settled']}, breached {summary['breached']}, "
        f"still awaiting {summary['awaiting']}, failed {summary['failed']}",
        flush=True,
    )
    for line in summary["log"]:
        print("  " + line, flush=True)


def watch(*, sleep=time.sleep, session_now=sessions.scheduled_session) -> dict | None:
    """Wait for regular hours, then settle until nothing is left. Returns the
    last pass's summary, or None when there was nothing to do."""
    if open_trade_count() == 0:
        print("no open weekend trades", flush=True)
        return None
    # Only a session that opens today is worth waiting for. Holidays and
    # weekends route as WEEKEND, and the next scheduled run picks those up.
    while session_now() in (sessions.OVERNIGHT, sessions.PREMARKET):
        sleep(WATCH_POLL_SECONDS)
    if session_now() != sessions.REGULAR:
        print(f"session is {session_now()}; settling as usual", flush=True)
    summary = None
    for attempt in range(WATCH_SETTLE_PASSES):
        if session_now() == sessions.WEEKEND:
            break
        summary = settle_once()
        report(summary)
        if open_trade_count() == 0:
            break
        if attempt + 1 < WATCH_SETTLE_PASSES:
            sleep(WATCH_SETTLE_PAUSE_SECONDS)
    return summary


def main() -> None:
    write = "--write" in sys.argv
    if not db.is_configured():
        sys.exit("DATABASE_URL is not set; cannot read weekend trades")

    if "--watch" in sys.argv:
        watch()
        return

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
    report(summary)
    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
