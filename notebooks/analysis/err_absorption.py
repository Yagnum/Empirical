"""How much does the ERR actually have to absorb under the locked design?

Run from app/api:
    uv run --group research python ../../notebooks/analysis/err_absorption.py

Reads the database only. Most trades here ran under pass-through (ADR-029), so
this is a counterfactual built from what was really recorded on each: the
broker's sandbox fill, and the shadow hedge's two Jupiter quotes (ADR-025).

    broker leg  = +qty (p_close - p_open) for a customer sell, negated for a buy
    token leg   = +qty (open_px - close_px) for a customer sell, negated for a buy
    leftover    = broker leg + token leg - gas     the ERR's true-up (ADR-033)

Because open_px is the same quote as p_open, the two entry prices cancel:

    leftover ~= qty (p_close - close_px) - gas      (customer sell)

The weekend drops out. What is left is the basis at the single moment the legs
close. That is why leg timing matters so much below: the close quote must be
taken when the share fills. On sells the sweep journal can fail on unsettled
proceeds, which delays the close quote until a later run, a median of 46 hours.
Those trades measure drift against a stale fill, not the hedge, so they are
reported apart.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\Yagnesh\Documents\Yagnum\app\api")
import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)

Z = 3.7742
HEDGED_SIGMA = 0.0098  # err.HEDGED_SIGMA
FEES_EST = 0.40  # err.LOCKED_FEES_EST
DUST_USD = 100  # flat gas swamps any percentage below this; reported apart
SYNC_HOURS = 1 / 6


def q(sql: str) -> pd.DataFrame:
    return pd.read_sql(text(sql), db.engine())


def load() -> pd.DataFrame:
    w = q(
        """select w.id, w.symbol, w.side, w.qty, w.p_open, w.p_close, w.design, w.created_at,
                  o.price op, c.price cp, o.gas_usd og, c.gas_usd cg, c.at close_at,
                  (select max(at) from weekend_trade_events e
                    where e.trade_id = w.id and e.kind = 'hedge_filled') filled_at
             from weekend_trades w
             left join lateral (select * from hedge_legs h where h.trade_id = w.id and h.leg = 'open'
                                order by id desc limit 1) o on true
             left join lateral (select * from hedge_legs h where h.trade_id = w.id and h.leg = 'close'
                                order by id desc limit 1) c on true
            where w.settlement_mode = 'market' and w.state in ('settled', 'breached') and not w.simulated"""
    )
    for col in ("qty", "p_open", "p_close", "op", "cp", "og", "cg"):
        w[col] = pd.to_numeric(w[col])
    w["notional"] = w.qty * w.p_open
    return w


def derive(w: pd.DataFrame) -> pd.DataFrame:
    h = w[(w.op > 0) & (w.cp > 0)].copy()
    sign = np.where(h.side == "sell", 1, -1)
    h["broker"] = sign * h.qty * (h.p_close - h.p_open)
    h["token"] = sign * h.qty * (h.op - h.cp)
    h["gas"] = h.og.fillna(0) + h.cg.fillna(0)
    h["left"] = h.broker + h.token - h.gas
    h["lp"] = h.left / h.notional * 100
    h["up"] = h.broker / h.notional * 100
    h["err"] = h.notional * HEDGED_SIGMA * Z + FEES_EST
    h["loss_use"] = (-h.left).clip(lower=0) / h.err * 100
    h["abs_use"] = h.left.abs() / h.err * 100
    h["gap_h"] = (pd.to_datetime(h.close_at) - pd.to_datetime(h.filled_at)).dt.total_seconds() / 3600
    h["days"] = (pd.to_datetime(h.filled_at) - pd.to_datetime(h.created_at)).dt.total_seconds() / 86400
    h["week"] = pd.to_datetime(h.created_at).dt.tz_convert("America/New_York").dt.strftime("%G-%V")
    return h


def describe(d: pd.DataFrame, name: str) -> None:
    p = d.lp
    print(f"\n== {name}: n={len(d)}, median trade ${d.notional.median():,.0f}")
    print(f"  leftover % of trade: median {p.median():.3f}, mean {p.mean():.3f}, std {p.std():.3f}, worst {p.min():.3f}, best {p.max():.3f}")
    print(f"  |leftover| %: p50 {p.abs().median():.3f}, p90 {p.abs().quantile(.9):.3f}, p95 {p.abs().quantile(.95):.3f}, max {p.abs().max():.3f}")
    print(f"  unhedged %: std {d.up.std():.3f}, |.| p50 {d.up.abs().median():.3f}, p95 {d.up.abs().quantile(.95):.3f}")
    print(f"  variance removed {100 * (1 - p.var() / d.up.var()):.1f}%")
    print(f"  ERR (3.7%) used by a loss: p50 {d.loss_use.median():.1f}%, p90 {d.loss_use.quantile(.9):.1f}%, p95 {d.loss_use.quantile(.95):.1f}%, max {d.loss_use.max():.1f}%; breaches {(d.loss_use > 100).sum()}")
    print(f"  |leftover| vs ERR: under 10% {(d.abs_use < 10).mean() * 100:.0f}% of trades, under 25% {(d.abs_use < 25).mean() * 100:.0f}%, under 50% {(d.abs_use < 50).mean() * 100:.0f}%")
    print(f"  dollars: median leftover {d.left.median():.2f}, median |leftover| {d.left.abs().median():.2f}, median ERR {d.err.median():.2f}, profit on {(d.left > 0).mean() * 100:.0f}% of trades")


def bootstrap(d: pd.DataFrame, draws: int = 3000) -> None:
    """Weekends, not trades, are the independent units."""
    rng = np.random.default_rng(11)
    weeks = d.week.unique()
    out = []
    for _ in range(draws):
        s = pd.concat([d[d.week == k] for k in rng.choice(weeks, len(weeks))])
        out.append((s.lp.std(), s.lp.abs().quantile(0.95), 100 * (1 - s.lp.var() / s.up.var())))
    out = np.array(out)
    print(f"  bootstrap over {len(weeks)} weekends, {d.groupby(['symbol', 'week']).ngroups} symbol-weekends (95%):")
    print(f"    std {np.percentile(out[:, 0], [2.5, 97.5]).round(3)}, p95 {np.percentile(out[:, 1], [2.5, 97.5]).round(3)}, variance removed {np.percentile(out[:, 2], [2.5, 97.5]).round(1)}")


def main() -> None:
    w = load()
    h = derive(w)
    print(f"market-settled trades {len(w)}; both hedge legs priced {len(h)} ({len(h) / len(w) * 100:.0f}%)")

    dust = h[h.notional < DUST_USD]
    big = h[h.notional >= DUST_USD]
    print(f"under ${DUST_USD}: {len(dust)} trades, {(dust.loss_use > 100).sum()} breaches (flat gas against a tiny ERR)")
    print(dust[dust.loss_use > 100][["id", "symbol", "notional", "gas", "left", "err"]].round(2))
    describe(big, f"all trades >= ${DUST_USD}")
    bootstrap(big)

    sync = big[big.gap_h <= SYNC_HOURS]
    lag = big[big.gap_h > 1]
    describe(sync, "legs closed together (close quote within 10 min of the fill)")
    bootstrap(sync)
    describe(lag, "close quote more than 1h after the fill")
    print(f"  of the delayed trades, sells: {(lag.side == 'sell').sum()} of {len(lag)}; median delay {lag.gap_h.median():.1f}h")

    print("\n== risk against time to fill, legs closed together")
    print("  unhedged grows with time; the leftover does not")
    for lo, hi in ((0, 1.5), (1.5, 4), (4, 10**6)):
        x = sync[(sync.days > lo) & (sync.days <= hi)]
        print(f"  {lo}-{hi} days n={len(x)}: unhedged std {x.up.std():.2f}%, leftover std {x.lp.std():.3f}%")

    print("\n== by side, legs closed together")
    for side in ("buy", "sell"):
        x = sync[sync.side == side]
        print(f"  {side}: n={len(x)}, median {x.lp.median():.3f}, std {x.lp.std():.3f}, worst {x.lp.min():.3f}, best {x.lp.max():.3f}")

    print("\n== how small could the ERR be, legs closed together")
    for sigma in (0.0098, 0.005, 0.004, 0.003):
        err = sync.notional * sigma * Z + FEES_EST
        loss = (-sync.left).clip(lower=0)
        print(f"  sigma {sigma:.4f}: ERR {sigma * Z * 100:.2f}%, breaches {(loss > err).sum()} of {len(sync)}, largest use {(loss / err).max() * 100:.0f}%")

    tokens = np.where(sync.side == "sell", 1, -1) * sync.qty * (sync.cp - sync.op) / sync.notional * 100
    print(f"\ntoken move vs share move: correlation {np.corrcoef(tokens, sync.up)[0, 1]:.3f}, min-variance hedge ratio {np.cov(tokens, sync.up)[0, 1] / tokens.var():.3f}")

    print("\n== live locked-design trades")
    print(
        q(
            """select id, symbol, side, qty, reserve, true_up, escrow_returned, state, created_at::date opened
                 from weekend_trades where design = 'locked' order by id"""
        )
    )
    v1 = q(
        """select count(*) n, sum(case when state = 'breached' then 1 else 0 end) breached
             from weekend_trades
            where design = 'pass_through' and settlement_mode = 'market' and state in ('settled', 'breached')"""
    )
    print(f"\npass-through design, market settled: {v1.n[0]}, breached {v1.breached[0]}")

    ladder = q("""select sampled_at, symbol, issuer, size_usd, side, price_usd from quote_ladder where status = 'ok'""")
    ladder["price_usd"] = pd.to_numeric(ladder.price_usd)
    p = ladder.pivot_table(index=["sampled_at", "symbol", "issuer", "size_usd"], columns="side", values="price_usd").dropna().reset_index()
    p["round_trip"] = (p.buy - p.sell) / ((p.buy + p.sell) / 2) * 100
    print(f"\n== round-trip cost by size, % (ladder since {ladder.sampled_at.min():%Y-%m-%d}, {p.sampled_at.nunique()} samples)")
    print(p.groupby(["issuer", "symbol", "size_usd"]).round_trip.median().unstack().round(3))


if __name__ == "__main__":
    main()
