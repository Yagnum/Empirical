"""Sandbox treasury faucet: keep the firm sweep account topped up.

The only bridge from the simulated bank world into the firm pool is a
customer "conduit" account: ACH money in (capped at $50,000 per account per
day — verified empirically 2026-08-24, and the cap is per ACCOUNT, so N
conduits yield N x $50k/day), then journal it up to the sweep account
(customer->firm journals are instant and unlimited).

Run this whenever the pool is low. It does three things per conduit:
  1. journals any cleared cash up to the sweep account
  2. starts a fresh $50k ACH deposit (skipped if today's is already used)
  3. reports balances

SANDBOX ONLY.

Usage (from app/api):
    uv run python scripts/treasury_faucet.py             # dry run
    uv run python scripts/treasury_faucet.py --execute   # do it
    uv run python scripts/treasury_faucet.py --execute --create 3   # add 3 conduits
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import alpaca  # noqa: E402
from config import settings  # noqa: E402

CONDUIT_EMAIL_PREFIX = "yagnum-treasury-conduit"
DAILY_MAX = Decimal("50000")


def find_conduits() -> list[dict]:
    return alpaca._request("GET", f"/v1/accounts?query={CONDUIT_EMAIL_PREFIX}") or []


def main() -> None:
    execute = "--execute" in sys.argv
    create_n = 0
    if "--create" in sys.argv:
        create_n = int(sys.argv[sys.argv.index("--create") + 1])

    firm = settings.alpaca_firm_account_id
    if not firm:
        sys.exit("ALPACA_FIRM_ACCOUNT_ID is not set in .env")

    conduits = find_conduits()
    print(f"{len(conduits)} conduit accounts found; mode: {'EXECUTE' if execute else 'dry run'}\n")

    if create_n and execute:
        start = len(conduits)
        for i in range(create_n):
            email = f"{CONDUIT_EMAIL_PREFIX}-{start + i + 1}@example.com"
            acct = alpaca.create_account(email, "Yagnum", "Treasury")
            print(f"  created conduit {acct['id'][:8]} ({email})")
        conduits = find_conduits()

    moved = Decimal("0")
    for c in conduits:
        cid = c["id"]
        cash = Decimal(alpaca.get_trading_account(cid)["cash"])
        if cash > 0:
            if execute:
                alpaca.create_journal(cid, firm, cash)
            print(f"  {cid[:8]}: {'journaled' if execute else 'would journal'} ${cash} -> sweep")
            moved += cash
        if execute:
            try:
                rel = alpaca.ensure_ach_relationship(cid, "Yagnum Treasury")
                alpaca.create_transfer(cid, rel, DAILY_MAX)
                print(f"  {cid[:8]}: started fresh $50k deposit (clears in ~7 min)")
            except alpaca.AlpacaError as exc:
                print(f"  {cid[:8]}: no new deposit ({exc.message[:60]})")

    print(f"\nmoved to sweep now: ${moved}")
    print("sweep cash:", alpaca.get_trading_account(firm)["cash"])


if __name__ == "__main__":
    main()
