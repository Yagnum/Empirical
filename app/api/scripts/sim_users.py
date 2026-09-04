"""The simulated-trader population (ADR-026).

Usage (from app/api):
    uv run python scripts/sim_users.py provision --cash 50000 --seed 25000
        create the missing personas' sandbox accounts, fund each, and buy a
        starter basket so they have shares to sell
    uv run python scripts/sim_users.py tick            # dry run: build briefings only
    uv run python scripts/sim_users.py tick --write    # ask Groq and act
    uv run python scripts/sim_users.py status          # who exists, last decisions

The GitHub Actions cron (.github/workflows/sim-users.yml) runs `tick
--write` every hour; each hour one of two persona groups takes its turn. It needs GROQ_API_KEY and the same broker
secrets the settlement job uses.
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
import sim  # noqa: E402
from models import SimDecision, SimUser  # noqa: E402
from sqlalchemy import select  # noqa: E402


def cmd_provision(args: argparse.Namespace) -> None:
    with db.session_scope() as session:
        created = sim.provision(session, cash=Decimal(args.cash), model=args.model)
        print(f"created {len(created)} persona(s)")
        if args.seed and Decimal(args.seed) > 0:
            for user in created:
                placed = sim.seed_positions(session, user, Decimal(args.seed))
                for order in placed:
                    print(f"  {user.name}: buy {order['qty']} {order['symbol']} -> {order['status']} {order['order_id']}")
                if not placed:
                    print(f"  {user.name}: no starter orders (market window does not allow it now)")


def cmd_tick(args: argparse.Namespace) -> None:
    with db.session_scope() as session:
        summary = sim.tick(session, write=args.write, everyone=args.everyone)
    print(f"session {summary['session']}; {summary['users']} persona(s); outcomes {summary['outcomes']}")
    for line in summary["log"]:
        print("  " + line)
    if not args.write:
        print("\ndry run. Pass --write to ask the model and act.")
    elif summary["users"] == 0 or any("GROQ_API_KEY" in line for line in summary["log"]):
        # Nothing decided: make the job fail visibly instead of quietly succeeding.
        sys.exit(1)


def cmd_status(_: argparse.Namespace) -> None:
    with db.session_scope() as session:
        users = list(session.execute(select(SimUser).order_by(SimUser.id)).scalars())
        if not users:
            print("no personas yet; run provision")
            return
        for user in users:
            last = session.execute(
                select(SimDecision).where(SimDecision.sim_user_id == user.id).order_by(SimDecision.id.desc()).limit(1)
            ).scalar_one_or_none()
            tail = "no decisions yet"
            if last is not None:
                tail = f"last {last.at:%Y-%m-%d %H:%M}Z {last.action or '-'} {last.symbol or ''} -> {last.outcome}"
            print(f"{user.name:8} {user.alpaca_account_id[:8]} {'active' if user.active else 'off':6} {tail}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("provision")
    p.add_argument("--cash", default="50000")
    p.add_argument("--seed", default="0", help="starter basket notional per persona")
    p.add_argument("--model", default=None)
    p.set_defaults(func=cmd_provision)
    p = sub.add_parser("tick")
    p.add_argument("--write", action="store_true")
    p.add_argument("--everyone", action="store_true", help="all personas, not just this hour's group")
    p.set_defaults(func=cmd_tick)
    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)
    args = parser.parse_args()
    if not db.is_configured():
        sys.exit("DATABASE_URL is not set")
    args.func(args)


if __name__ == "__main__":
    main()
