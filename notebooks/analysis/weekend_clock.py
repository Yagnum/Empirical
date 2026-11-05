"""Time-of-weekend risk: how fast does the token -> Monday-open error shrink as
the open approaches, and should the reserve scale with sqrt(hours left)?

Run from app/api:
    uv run --group research python ../../notebooks/analysis/weekend_clock.py

READ-ONLY: SELECT statements against token_prices, token_candles, market_bars
and weekend_trades. Writes one PNG to notebooks/figures/ and prints every number.

Two samples of "the token's price at hour h before the open":
  FIT   hourly GeckoTerminal candle closes, Mar-Aug 2026, every hour inside the
        weekend window, paired with the share's daily-bar open after the
        weekend. Many points, but only ~400 independent symbol-weekends.
  LIVE  every token_prices sampler row inside the weekend window (Aug 28 -
        Oct 13). The share's open is known exactly only for the weekend ending
        2026-08-31 (daily bars stop there); for later weekends the first
        regular-hours share print the sampler caught within 30 minutes of
        09:30 is used as a proxy, and weekends without one are dropped.
The rule is fitted on FIT and tested on LIVE and on the real weekend_trades,
so the trade test is out of sample.

Weekend window = 20:00 ET on the last session day (Friday, or Thursday before a
Friday holiday) to 09:30 ET on the next session day; a Monday holiday (Labor
Day 2026-09-07) extends it. Error e = ln(open / token price); it is divided by
the symbol's production sigma (research_params.json) to pool symbols.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

API = Path(r"C:\Users\Yagnesh\Documents\Yagnum\app\api")
FIG = Path(r"C:\Users\Yagnesh\Documents\Yagnum\notebooks\figures")
sys.path.insert(0, str(API))
import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

ET = "America/New_York"
Z = 3.7742
CENT = Decimal("0.01")
HOLIDAYS = {date(2026, 9, 7)}
PROXY_MAX_MIN = 30
BIN_H = 6
H_FULL = 61.5  # Fri 20:00 -> Mon 09:30

PARAMS = json.loads((API / "research_params.json").read_text(encoding="utf-8"))
SIGMA = {k: float(v["used"]) for k, v in PARAMS["sigma"].items()}

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)


def hr(title: str) -> None:
    print("\n" + "=" * 78 + "\n" + title + "\n" + "=" * 78)


def et(d: date, hh: int, mm: int = 0) -> pd.Timestamp:
    return pd.Timestamp(f"{d} {hh:02d}:{mm:02d}", tz=ET)


eng = db.engine()
daily = pd.read_sql(text("select symbol, bucket_start, open from market_bars where timeframe = '1Day'"), eng)
daily["open"] = daily.open.astype(float)
daily["d"] = daily.bucket_start.dt.tz_convert(ET).dt.date
open_of = {(s, d): o for s, d, o in zip(daily.symbol, daily.d, daily.open)}

tp = pd.read_sql(text(
    "select sampled_at, underlying, usd_price, market_price, market_trade_at, market_open "
    "from token_prices where underlying is not null order by sampled_at"), eng)
tp[["usd_price", "market_price"]] = tp[["usd_price", "market_price"]].astype(float)
tp["market_open"] = tp.market_open.fillna(False).astype(bool)
tp["trade_et"] = tp.market_trade_at.dt.tz_convert(ET)

sess = (set(daily.d) | set(tp.loc[tp.market_open, "sampled_at"].dt.tz_convert(ET).dt.date)) - HOLIDAYS
sess = sorted(d for d in sess if d.weekday() < 5)
windows = []  # (start_et, open_et, open_date)
for d0, d1 in zip(sess[:-1], sess[1:]):
    sat = d0 + timedelta(days=(5 - d0.weekday()) % 7 or 7)
    if d0 < sat < d1:
        windows.append((et(d0, 20), et(d1, 9, 30), d1))
win = pd.DataFrame(windows, columns=["start", "open_at", "open_date"])


def assign_window(ts_utc: pd.Series) -> pd.DataFrame:
    """For each timestamp: the weekend window it falls in (or NaN) and hours to the open."""
    idx = win.open_at.searchsorted(ts_utc.dt.tz_convert(ET), side="right")
    out = pd.DataFrame({"w": idx}, index=ts_utc.index)
    ok = idx < len(win)
    st = np.where(ok, win.start.reindex(np.minimum(idx, len(win) - 1)).values, None)
    out["in"] = ok & (ts_utc.dt.tz_convert(ET).values >= pd.to_datetime(pd.Series(st)).values)
    out["open_at"] = win.open_at.reindex(np.minimum(idx, len(win) - 1)).values
    out["open_date"] = win.open_date.reindex(np.minimum(idx, len(win) - 1)).values
    out["h_left"] = (pd.to_datetime(out.open_at, utc=True) - ts_utc).dt.total_seconds() / 3600
    return out


# ---------------------------------------------------------------- FIT sample: candles
hr("1. DATA")
cand = pd.read_sql(text("select symbol, bucket_start, close from token_candles where timeframe = 'hour'"), eng)
cand["close"] = cand.close.astype(float)
cand["share"] = cand.symbol.str[:-1]
cand["t"] = cand.bucket_start + pd.Timedelta(hours=1)  # the close is known at the end of the hour
a = assign_window(cand.t)
cand = cand.join(a)
fit = cand[cand["in"]].copy()
fit["p_open"] = [open_of.get((s, d), np.nan) for s, d in zip(fit.share, fit.open_date)]
fit["sigma"] = fit.share.map(SIGMA)
fit = fit.dropna(subset=["p_open", "sigma"])
fit["e"] = np.log(fit.p_open / fit.close)
fit["u"] = fit.e / fit.sigma
fit["key"] = fit.share + "|" + fit.open_date.astype(str)
# drop obviously broken candle prints: |e| > 25% is a bad pool print, not a weekend move
bad = fit.e.abs() > 0.25
print(f"FIT (hourly candles): {len(fit) + 0} points before cleaning; dropped |error| > 25% as bad prints: {int(bad.sum())}")
fit = fit[~bad]
print(f"FIT points {len(fit)}, symbols {fit.share.nunique()}, weekends {fit.open_date.nunique()} "
      f"({min(fit.open_date)} to {max(fit.open_date)}), independent symbol-weekends {fit.key.nunique()}")
print(f"  points per symbol-weekend: median {fit.groupby('key').size().median():.0f} "
      f"(max ~62 on a normal weekend, ~86 on a long one); hourly candles are missing when the pool did not trade")

# ---------------------------------------------------------------- LIVE sample: sampler rows
a = assign_window(tp.sampled_at)
live = tp.join(a)
live = live[live["in"]].copy()
print(f"\nLIVE (token_prices rows inside a weekend window): {len(live)} rows, "
      f"{live.sampled_at.nunique()} sampling runs, {live.open_date.nunique()} weekends")
runs = live.groupby("open_date").agg(runs=("sampled_at", "nunique"), rows=("sampled_at", "size"))
runs["runs_per_day"] = runs.runs / ((win.set_index("open_date").open_at - win.set_index("open_date").start)
                                    .dt.total_seconds() / 86400).reindex(runs.index)
print(runs.round(1).to_string())
# share open: exact for daily-bar Mondays, else the first regular-hours print within 30 min of 09:30
opens = {}
for (s, d), g in tp[tp.market_open].groupby(["underlying", tp.loc[tp.market_open, "trade_et"].dt.date]):
    g = g[g.trade_et >= et(d, 9, 30)].sort_values("trade_et")
    if len(g):
        lag = (g.trade_et.iloc[0] - et(d, 9, 30)).total_seconds() / 60
        opens[(s, d)] = (g.market_price.iloc[0], lag)
src, po, lagm = [], [], []
for s, d in zip(live.underlying, live.open_date):
    if (s, d) in open_of:
        src.append("daily_bar"); po.append(open_of[(s, d)]); lagm.append(0.0)
    elif (s, d) in opens and opens[(s, d)][1] <= PROXY_MAX_MIN:
        src.append("proxy"); po.append(opens[(s, d)][0]); lagm.append(opens[(s, d)][1])
    else:
        src.append(None); po.append(np.nan); lagm.append(np.nan)
live["open_src"], live["p_open"], live["open_lag_min"] = src, po, lagm
live["sigma"] = live.underlying.map(SIGMA)
print("\nLIVE rows by how the share's open is known:")
print(live.open_src.fillna("none (dropped)").value_counts().to_string())
proxy_lags = live.loc[live.open_src == "proxy"].groupby(["underlying", "open_date"]).open_lag_min.first()
if len(proxy_lags):
    print(f"proxy opens: {len(proxy_lags)} symbol-weekends, lag after 09:30 median "
          f"{proxy_lags.median():.1f} min, max {proxy_lags.max():.1f} min")
live = live.dropna(subset=["p_open", "sigma"])
live["e"] = np.log(live.p_open / live.usd_price)
live["u"] = live.e / live.sigma
live["key"] = live.underlying + "|" + live.open_date.astype(str)
print(f"LIVE usable: {len(live)} rows, {live.key.nunique()} symbol-weekends, weekends "
      f"{sorted(map(str, live.open_date.unique()))}")


# ---------------------------------------------------------------- 2. shape
def table(df: pd.DataFrame) -> pd.DataFrame:
    b = (df.h_left // BIN_H * BIN_H).clip(upper=84)
    t = df.groupby(b).agg(points=("u", "size"), sym_weekends=("key", "nunique"),
                          rms_e=("e", lambda x: np.sqrt((x ** 2).mean())),
                          rms_u=("u", lambda x: np.sqrt((x ** 2).mean())),
                          mean_u=("u", "mean"), p99_abs_u=("u", lambda x: x.abs().quantile(0.99)))
    t.index.name = f"h_left bin ({BIN_H} h)"
    return t


hr("2. ERROR VS HOURS LEFT (u = ln(open / token) / sigma_symbol)")
tf = table(fit)
print("FIT (candles):")
print(tf.round(4).to_string())
tl = table(live)
print("\nLIVE (sampler):")
print(tl.round(4).to_string())


def ols(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    X = np.column_stack([np.ones_like(x), x])
    return np.linalg.lstsq(X, y, rcond=None)[0]


def boot(df: pd.DataFrame, fn, n=1000, seed=1) -> np.ndarray:
    """Cluster bootstrap over weekends: all symbols of a weekend share one open."""
    rng = np.random.default_rng(seed)
    groups = {k: g for k, g in df.groupby("open_date")}
    keys = list(groups)
    out = []
    for _ in range(n):
        pick = rng.choice(len(keys), len(keys), replace=True)
        out.append(fn(pd.concat([groups[keys[i]] for i in pick])))
    return np.array(out)


hr("3. FITS ON THE FIT SAMPLE (95% CIs: cluster bootstrap over weekends, 1000 draws)")
f_sqrt = lambda d: ols(np.sqrt(d.h_left.values), d.u.abs().values)  # noqa: E731
f_var = lambda d: ols(d.h_left.values, (d.u ** 2).values)  # noqa: E731
c_sqrt = f_sqrt(fit); b_sqrt = boot(fit, f_sqrt)
c_var = f_var(fit); b_var = boot(fit, f_var, seed=2)
ci = lambda b, j: f"[{np.percentile(b[:, j], 2.5):.4f}, {np.percentile(b[:, j], 97.5):.4f}]"  # noqa: E731
print(f"|u| = a + b*sqrt(h):   a = {c_sqrt[0]:.4f} {ci(b_sqrt, 0)},  b = {c_sqrt[1]:.4f} {ci(b_sqrt, 1)}")
print(f"  share of b draws > 0: {(b_sqrt[:, 1] > 0).mean():.3f}")
print(f"u^2 = alpha + beta*h:  alpha = {c_var[0]:.4f} {ci(b_var, 0)},  beta = {c_var[1]:.5f} {ci(b_var, 1)}")
print(f"  share of beta draws > 0: {(b_var[:, 1] > 0).mean():.3f}")
alpha, beta = max(c_var[0], 1e-6), max(c_var[1], 0.0)
s = lambda h: np.sqrt(alpha + beta * np.asarray(h, dtype=float))  # noqa: E731
print(f"implied RMS error in sigmas: at the open (h=0) {s(0):.3f}, at h=12 {s(12):.3f}, "
      f"at h=36 {s(36):.3f}, at Fri 20:00 (h={H_FULL}) {s(H_FULL):.3f}")
print(f"  ratio open / Friday night: {s(0) / s(H_FULL):.2f}  (pure sqrt-time diffusion would give 0)")
print(f"  share of Friday-night variance still present at the open: {alpha / (alpha + beta * H_FULL):.1%}")
sp = stats.spearmanr(fit.h_left, fit.u.abs())
print(f"Spearman(|u|, h_left) point-level: rho = {sp.statistic:.3f} (p = {sp.pvalue:.2g}, "
      f"p ignores within-weekend dependence)")
# the same check on LIVE
c_var_l = f_var(live)
print(f"LIVE, same variance fit: alpha = {c_var_l[0]:.4f}, beta = {c_var_l[1]:.5f} "
      f"({live.key.nunique()} symbol-weekends; too few for a CI worth quoting)")

# time-scaled multiplier, calibrated on FIT the same way z was: 99th pct of |u| / s(h)
z_t = float(np.quantile(fit.u.abs() / s(fit.h_left), 0.99))
print(f"\ntime-scaled multiplier z_t = 99th pct of |u| / s(h) on FIT: {z_t:.4f}")
print("  time-scaled reserve % = sigma_symbol * z_t * s(h)")
for h in (0, 6, 12, 24, 36, 48, H_FULL, 85.5):
    print(f"    h = {h:5.1f}: {z_t * s(h):.3f} sigma   (fixed rule: {Z:.3f} sigma)")
fixed_cov_fit = (fit.u.abs() <= Z).mean()
ts_cov_fit = (fit.u.abs() <= z_t * s(fit.h_left)).mean()
print(f"FIT point coverage, two-sided |u| <= k: fixed {fixed_cov_fit:.3%}; time-scaled {ts_cov_fit:.3%} (in sample)")
fixed_cov_l = (live.u.abs() <= Z).mean()
ts_cov_l = (live.u.abs() <= z_t * s(live.h_left)).mean()
print(f"LIVE point coverage (out of sample): fixed {fixed_cov_l:.3%}; time-scaled {ts_cov_l:.3%}; "
      f"misses fixed {int((live.u.abs() > Z).sum())}, time-scaled {int((live.u.abs() > z_t * s(live.h_left)).sum())} "
      f"of {len(live)} rows in {live.key.nunique()} symbol-weekends")

# ---------------------------------------------------------------- 4. real trades
hr("4. THE REAL WEEKEND TRADES UNDER A TIME-SCALED RESERVE")
tr = pd.read_sql(text("""
select id, source, side, qty, symbol, p_open, p_close, sigma, reserve, true_up, state, created_at, settled_at
from weekend_trades
where settlement_mode = 'market' and state in ('settled', 'breached') and reserve > 0
order by created_at"""), eng)
a = assign_window(tr.created_at)
tr = tr.join(a)
print(f"market-settled trades: {len(tr)}; inside a weekend window by this definition: {int(tr['in'].sum())}")
out_of = tr[~tr["in"]]
if len(out_of):
    print(f"  outside the window (placed on a weekday or Sunday-night overnight etc.): {len(out_of)}; "
          f"they keep h measured to the next open")
nxt = []
for t in tr.created_at.dt.tz_convert(ET):
    d = t.date()
    cand_days = [x for x in sess if et(x, 9, 30) > t]
    nxt.append(et(cand_days[0], 9, 30) if cand_days else pd.NaT)
tr["h_left"] = [(n - c.tz_convert(ET)).total_seconds() / 3600 for n, c in zip(nxt, tr.created_at)]
print(f"the engine's weekend window closes Sun 20:00 ET, so no ERR trade is ever closer than 13.5 h "
      f"to a Monday open; over 13.5-61.5 h the fitted shape moves only from {s(13.5):.3f} to {s(H_FULL):.3f} "
      f"(ratio {s(13.5) / s(H_FULL):.3f})")
print(f"hours from trade to the next 09:30 open: median {tr.h_left.median():.1f}, "
      f"min {tr.h_left.min():.1f}, max {tr.h_left.max():.1f}")
print(tr.h_left.describe().round(1).to_string())
print(f"settled at: median {(tr.settled_at - tr.created_at).dt.total_seconds().median() / 3600:.1f} h after creation")

rows = []
for r in tr.itertuples():
    qty, po = Decimal(str(r.qty)), Decimal(str(r.p_open))
    notional = qty * po
    sig = Decimal(str(r.sigma))
    k_ts = Decimal(repr(float(z_t * s(r.h_left))))
    k_naive = Decimal(repr(float(Z * np.sqrt(max(r.h_left, 0) / H_FULL))))
    k_anch = Decimal(repr(float(Z * s(r.h_left) / s(H_FULL))))
    res_ts = (notional * sig * k_ts).quantize(CENT, rounding=ROUND_CEILING)
    res_nv = (notional * sig * k_naive).quantize(CENT, rounding=ROUND_CEILING)
    res_an = (notional * sig * k_anch).quantize(CENT, rounding=ROUND_CEILING)
    tu = Decimal(str(r.true_up))
    rows.append(dict(id=r.id, symbol=r.symbol, side=r.side, h=r.h_left, notional=notional,
                     reserve=Decimal(str(r.reserve)), res_ts=res_ts, res_naive=res_nv, res_anch=res_an, true_up=tu,
                     br_fixed=Decimal(str(r.reserve)) + tu < 0, br_ts=res_ts + tu < 0, br_naive=res_nv + tu < 0, br_anch=res_an + tu < 0))
T = pd.DataFrame(rows)
n = len(T)
for lab, rc, bc in [("fixed (production)", "reserve", "br_fixed"),
                    ("anchored: z*s(h)/s(61.5), same z", "res_anch", "br_anch"),
                    ("time-scaled sqrt(alpha+beta*h), z_t", "res_ts", "br_ts"),
                    ("naive sigma*z*sqrt(h/61.5), no floor", "res_naive", "br_naive")]:
    held = sum(T[rc], Decimal("0"))
    x = int(T[bc].sum())
    lo, hi = stats.binomtest(n - x, n).proportion_ci(0.95, method="exact")
    syms = ", ".join(f"{a}/{b}" for a, b in T.loc[T[bc], ["symbol", "side"]].values)
    print(f"{lab:40s} reserve held ${held:,.2f}  ({float(held / sum(T.notional)):.2%} of notional)  "
          f"covered {n - x}/{n} = {(n - x) / n:.1%}  [95% CI {lo:.1%}-{hi:.1%}]  breaches: {syms or '-'}")
print(f"total notional ${sum(T.notional):,.2f}")
d_ts = sum(T.res_ts) - sum(T.reserve)
print(f"capital released by time-scaling vs fixed: ${-d_ts:,.2f}" if d_ts < 0 else
      f"time-scaling would hold ${d_ts:,.2f} MORE than fixed")
print(f"capital released by the anchored rule (time-scaling alone, same z): ${sum(T.reserve) - sum(T.res_anch):,.2f}")
print("\nby hours-left band:")
T["band"] = pd.cut(T.h, [-1, 12, 24, 36, 48, 100], labels=["0-12", "12-24", "24-36", "36-48", "48+"])
print(T.groupby("band", observed=True).apply(lambda g: pd.Series({
    "trades": len(g), "fixed_pct": float(sum(g.reserve) / sum(g.notional)),
    "ts_pct": float(sum(g.res_ts) / sum(g.notional)), "mean_abs_trueup_pct": float(sum(abs(x) for x in g.true_up) / sum(g.notional)),
    "anch_pct": float(sum(g.res_anch) / sum(g.notional)),
    "br_fixed": int(g.br_fixed.sum()), "br_anch": int(g.br_anch.sum()), "br_ts": int(g.br_ts.sum()), "br_naive": int(g.br_naive.sum())}),
    include_groups=False).round(4).to_string())

# ---------------------------------------------------------------- 5. figure
fig, ax = plt.subplots(figsize=(9, 5))
hh = np.linspace(0, 86, 200)
ax.plot(tf.index + BIN_H / 2, tf.rms_u, "o-", color="#2e86ab", label=f"RMS error, candles Mar-Aug ({fit.key.nunique()} sym-weekends)")
ax.plot(tf.index + BIN_H / 2, tf.p99_abs_u, "s--", color="#2e86ab", alpha=0.6, label="99th pct |error|, candles")
if len(tl):
    ax.plot(tl.index + BIN_H / 2, tl.rms_u, "o", color="#d1495b", label=f"RMS error, sampler Aug-Oct ({live.key.nunique()} sym-weekends)")
ax.plot(hh, s(hh), color="black", lw=1, label=r"fit $\sqrt{\alpha+\beta h}$")
ax.plot(hh, z_t * s(hh), color="#e09f3e", lw=2, label=f"time-scaled reserve z_t*s(h), z_t={z_t:.2f}")
ax.axhline(Z, color="#e09f3e", ls=":", lw=2, label="fixed reserve z = 3.7742")
ax.set_xlabel("hours left until the regular open")
ax.set_ylabel("error in units of the symbol's sigma")
ax.invert_xaxis()
ax.set_title("Token -> share-open error vs hours left in the weekend")
ax.legend(fontsize=8, loc="center")
fig.tight_layout()
out = FIG / "weekend_clock.png"
fig.savefig(out, dpi=150)
print(f"\nfigure: {out}")
