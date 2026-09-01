"""Sample every xStock's Jupiter price beside its real share (ADR-016).

Usage (from app/api):
    uv run python scripts/sample_prices.py            # dry run: print the snapshot
    uv run python scripts/sample_prices.py --write    # append it to token_prices

The GitHub Actions cron runs the --write form every five minutes. Run the
dry form yourself any time to see what a snapshot looks like.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
import sampler  # noqa: E402


def main() -> None:
    write = "--write" in sys.argv
    rows = sampler.sample_once()
    if not rows:
        sys.exit("no xStock prices returned; nothing to record")

    stamp = rows[0].sampled_at.strftime("%Y-%m-%d %H:%M:%SZ")
    state = {True: "open", False: "closed", None: "unknown"}[rows[0].market_open]
    print(f"{stamp}  market {state}  {len(rows)} tokens")
    for row in rows:
        market = f"{row.market_price:>12}" if row.market_price is not None else f"{'-':>12}"
        gap = ""
        if row.market_price:
            gap = f"  gap {(row.usd_price / row.market_price - 1) * 100:+.3f}%"
        spread = ""
        if row.bid_usd and row.ask_usd:
            spread = f"  spread {(row.ask_usd / row.bid_usd - 1) * 100:.3f}%"
        print(f"  {row.symbol:<7} jup {row.usd_price:>20}   mkt {market}{gap}{spread}")

    if not write:
        print("\ndry run. Pass --write to append these rows.")
        return
    if not db.is_configured():
        sys.exit("DATABASE_URL is not set; cannot write")
    print(f"wrote {sampler.record(rows)} rows")


if __name__ == "__main__":
    main()
