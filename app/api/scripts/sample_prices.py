"""Sample every tokenized stock's Jupiter price beside its real share (ADR-016).

Usage (from app/api):
    uv run python scripts/sample_prices.py            # dry run: print the snapshot
    uv run python scripts/sample_prices.py --ladder   # dry run, depth ladder too
    uv run python scripts/sample_prices.py --write    # append it to the database

The GitHub Actions cron runs the --write form. With --write the depth
ladder runs when the database says the last one is at least
LADDER_MIN_INTERVAL_MINUTES old; a dry run skips it unless --ladder is
given (it is ~48 slow quote calls). docs/RESEARCH-COLLECTION.md explains
every series a run collects.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
import sampler  # noqa: E402


def main() -> None:
    write = "--write" in sys.argv
    ladder = True if "--ladder" in sys.argv else (None if write else False)
    snap = sampler.sample_all(ladder=ladder)
    rows = snap.prices
    if not rows:
        sys.exit("no token prices returned; nothing to record")

    stamp = snap.sampled_at.strftime("%Y-%m-%d %H:%M:%SZ")
    state = {True: "open", False: "closed", None: "unknown"}[snap.market_open]
    print(f"{stamp}  market {state}  {len(rows)} tokens")
    for row in rows:
        market = f"{row.market_price:>12}" if row.market_price is not None else f"{'-':>12}"
        gap = ""
        if row.market_price:
            gap = f"  gap {(row.usd_price / row.market_price - 1) * 100:+.3f}%"
        spread = ""
        if row.bid_usd and row.ask_usd:
            spread = f"  spread {(row.ask_usd / row.bid_usd - 1) * 100:.3f}%"
        print(f"  {row.symbol:<8}{row.issuer:<8} jup {row.usd_price:>20}   mkt {market}{gap}{spread}")

    print(f"\nshare trades ({len(snap.share_trades)})")
    for trade in snap.share_trades:
        print(f"  {trade.symbol:<6} {trade.feed} {trade.price:>12} at {trade.trade_at:%Y-%m-%d %H:%M:%SZ}"
              f"  {trade.session or '-':<10} [{trade.conditions or ''}]")
    print(f"\noracle ({len(snap.oracles)})")
    for oracle in snap.oracles:
        print(f"  {oracle.symbol:<6} {oracle.feed_kind:<11} {oracle.price_usd:>14}"
              f"  published {oracle.publish_time:%Y-%m-%d %H:%M:%SZ}")
    print(f"\nladder ({len(snap.ladder)})")
    for rung in snap.ladder:
        price = f"{rung.price_usd:.4f}" if rung.price_usd is not None else "-"
        print(f"  {rung.symbol:<8} {rung.side:<4} ${rung.size_usd:>8}  {rung.status:<12} {price:>14}  {rung.route or ''}")

    if not write:
        print("\ndry run. Pass --write to append these rows.")
        return
    if not db.is_configured():
        sys.exit("DATABASE_URL is not set; cannot write")
    written = sampler.record_all(snap)
    print("wrote " + ", ".join(f"{count} {table}" for table, count in written.items()))


if __name__ == "__main__":
    main()
