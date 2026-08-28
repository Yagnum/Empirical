"""Backfill the past for the gap-volatility research (ADR-016, ADR-017).

Usage (from app/api):
    uv run python scripts/backfill_history.py                 # dry run: print the plan
    uv run python scripts/backfill_history.py --write         # fetch and upsert
    uv run python scripts/backfill_history.py --tokens NVDAx,AAPLx
    uv run python scripts/backfill_history.py --skip-minutes  # no Monday minute bars

What --write does, in order, for every xStock Jupiter lists:
    1. GeckoTerminal hourly candles for the token's deepest USDC pool, back to
       the public tier's 180-day wall.
    2. GeckoTerminal daily candles, same pool, same wall.
    3. Alpaca daily bars for the underlying share from 2024-08-01.
    4. Alpaca minute bars for every Monday 04:00-10:30 ET in the last 180 days.

Every write is an upsert on the table's natural key, so re-running is safe
and a run that dies can be restarted. GeckoTerminal is rate-limited to about
30 calls a minute, so a full run takes on the order of half an hour.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import alpaca  # noqa: E402
import backfill  # noqa: E402
import db  # noqa: E402
import geckoterminal  # noqa: E402
import jupiter  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="fetch and upsert (default: dry run)")
    parser.add_argument("--tokens", default="", help="comma-separated symbols to restrict to, e.g. NVDAx,AAPLx")
    parser.add_argument("--skip-minutes", action="store_true", help="skip the Monday minute bars")
    parser.add_argument("--days", type=int, default=geckoterminal.HISTORY_DAYS, help="candle/Monday lookback")
    parser.add_argument("--daily-start", default=backfill.MARKET_DAILY_START, help="Alpaca daily bars from")
    return parser.parse_args(argv)


def log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {message}", flush=True)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    now = datetime.now(timezone.utc)
    started = time.monotonic()

    tokens = jupiter.list_xstocks()
    wanted = {symbol.strip() for symbol in args.tokens.split(",") if symbol.strip()}
    if wanted:
        tokens = [token for token in tokens if token["symbol"] in wanted]
        missing = wanted - {token["symbol"] for token in tokens}
        if missing:
            log(f"not found on Jupiter: {', '.join(sorted(missing))}")
    underlyings = sorted({token["underlying"] for token in tokens if token["underlying"]})
    mondays = backfill.mondays_since(now, args.days)
    hourly_pages = -(-args.days * 24 // geckoterminal.PAGE_LIMIT)  # ceil

    log(f"{len(tokens)} tokens, {len(underlyings)} underlyings")
    log(f"candles: {args.days} days back, ~{hourly_pages} hourly pages + 1 daily page per token")
    log(f"alpaca daily bars from {args.daily_start}; Mondays: {len(mondays)}"
        f" ({mondays[0] if mondays else '-'} .. {mondays[-1] if mondays else '-'})"
        f"{' (skipped)' if args.skip_minutes else ''}")
    gecko_calls = len(tokens) * (1 + hourly_pages + 1 + 2)  # pools + pages + wall hits
    log(f"expected GeckoTerminal calls: ~{gecko_calls} at {geckoterminal.CALL_INTERVAL_SECONDS}s each")
    for token in tokens:
        log(f"  {token['symbol']:<7} mint {token['mint']}  underlying {token['underlying'] or '-'}")

    if not args.write:
        print("\ndry run. Pass --write to fetch and upsert.")
        return
    if not db.is_configured():
        sys.exit("DATABASE_URL is not set; cannot write")

    written = {"hour": 0, "day": 0, "1Day": 0, "1Min": 0}
    failures: list[str] = []

    for token in tokens:
        symbol, mint = token["symbol"], token["mint"]
        try:
            pool = geckoterminal.deepest_usdc_pool(mint)
        except geckoterminal.GeckoTerminalError as exc:
            failures.append(f"{symbol}: pools lookup failed ({exc.status_code}: {exc.message})")
            continue
        if pool is None:
            failures.append(f"{symbol}: no pool on GeckoTerminal")
            continue
        log(f"{symbol}: pool {pool['address']} ({pool['name']}, ${pool['reserve_usd']})")
        for timeframe in geckoterminal.TIMEFRAMES:
            try:
                count = backfill.backfill_token(symbol, mint, timeframe, args.days, now=now, pool=pool["address"])
            except geckoterminal.GeckoTerminalError as exc:
                failures.append(f"{symbol}/{timeframe}: {exc.status_code}: {exc.message}")
                continue
            written[timeframe] += count
            log(f"{symbol}: {timeframe} candles +{count}")

    for underlying in underlyings:
        try:
            count = backfill.backfill_market_daily(underlying, args.daily_start)
        except alpaca.AlpacaError as exc:
            failures.append(f"{underlying}/1Day: {exc.status_code}: {exc.message}")
            continue
        written["1Day"] += count
        log(f"{underlying}: daily bars +{count}")

    if not args.skip_minutes:
        for underlying in underlyings:
            total = 0
            for monday in mondays:
                try:
                    total += backfill.backfill_market_minutes(underlying, monday)
                except alpaca.AlpacaError as exc:
                    failures.append(f"{underlying}/1Min {monday}: {exc.status_code}: {exc.message}")
            written["1Min"] += total
            log(f"{underlying}: Monday minute bars +{total}")

    elapsed = time.monotonic() - started
    log(f"done in {elapsed / 60:.1f} min. written: token_candles hour={written['hour']} day={written['day']};"
        f" market_bars 1Day={written['1Day']} 1Min={written['1Min']}")
    for failure in failures:
        log(f"FAILED {failure}")


if __name__ == "__main__":
    main()
