"""Ops tool: close one sandbox brokerage account correctly (ADR-013).

Steps, in order:
  1. cancel open orders
  2. journal remaining cash back to the firm sweep account
  3. retire the contact email, then close (alpaca.close_account)

Usage (from app/api):
    uv run python scripts/close_account.py <account_id>            # dry run
    uv run python scripts/close_account.py <account_id> --execute  # do it
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import alpaca  # noqa: E402
from config import settings  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    account_id = sys.argv[1]
    execute = "--execute" in sys.argv

    account = alpaca.get_account(account_id)
    trading = alpaca.get_trading_account(account_id)
    orders = alpaca.list_orders(account_id, status="open") if hasattr(alpaca, "list_orders") else []
    positions = alpaca.list_positions(account_id) if hasattr(alpaca, "list_positions") else []
    cash = Decimal(trading["cash"])

    print(f"account {account_id[:8]}  status={account.get('status')}  cash=${cash}")
    print(f"  open orders: {len(orders)}   positions: {len(positions)}")
    if positions:
        sys.exit("  positions must be flat before closing. Sell them first.")

    print(f"  {'will' if execute else 'would'} cancel {len(orders)} open order(s)")
    if cash > 0:
        print(f"  {'will' if execute else 'would'} journal ${cash} back to the sweep account")
    print(f"  {'will' if execute else 'would'} retire the email and close the account")
    if not execute:
        print("
dry run. Pass --execute to proceed.")
        return

    for order in orders:
        alpaca.cancel_order(account_id, order["id"])
    if cash > 0:
        alpaca.create_journal(account_id, settings.alpaca_firm_account_id, cash)
    closed = alpaca.close_account(account_id)
    print("closed. status now:", closed.get("status"))


if __name__ == "__main__":
    main()
