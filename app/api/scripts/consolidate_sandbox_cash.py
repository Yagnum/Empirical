"""One-off sandbox ops tool: sweep idle test-account cash into the firm account.

Journals (JNLC) the full cash balance of every client account into the firm
sweep account configured as ALPACA_FIRM_ACCOUNT_ID. Customer->firm journals
are permitted and execute instantly (verified 2026-08-24); customer->customer
journals are not.

SANDBOX ONLY. In production this would be moving real customer money.

Usage (from app/api):
    uv run python scripts/consolidate_sandbox_cash.py            # dry run
    uv run python scripts/consolidate_sandbox_cash.py --execute  # do it
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import alpaca  # noqa: E402
from config import settings  # noqa: E402


def main() -> None:
    execute = "--execute" in sys.argv
    firm = settings.alpaca_firm_account_id
    if not firm:
        sys.exit("ALPACA_FIRM_ACCOUNT_ID is not set in .env")

    accounts = alpaca._request("GET", "/v1/accounts")
    print(f"{len(accounts)} client accounts; firm target {firm[:8]}...")
    print(f"mode: {'EXECUTE' if execute else 'dry run (pass --execute to move cash)'}\n")

    total = Decimal("0")
    swept = 0
    for account in accounts:
        account_id = account["id"]
        if account_id == firm:
            continue
        try:
            cash = Decimal(alpaca.get_trading_account(account_id)["cash"])
        except alpaca.AlpacaError as exc:
            print(f"  skip {account_id[:8]}: cannot read balance ({exc.message[:50]})")
            continue
        if cash <= 0:
            continue
        if execute:
            try:
                alpaca.create_journal(account_id, firm, cash)
            except alpaca.AlpacaError as exc:
                print(f"  skip {account_id[:8]}: journal refused ({exc.message[:50]})")
                continue
        print(f"  {'swept' if execute else 'would sweep'} {account_id[:8]}  ${cash}")
        total += cash
        swept += 1

    print(f"\n{swept} accounts, ${total} total")
    if execute:
        print("firm cash now:", alpaca.get_trading_account(firm)["cash"])


if __name__ == "__main__":
    main()
