"""RQ2: what does weekend liquidity cost, and does the executable spread widen
when the regulated US market is closed?

Run from app/api:
    uv run --group research python ../../notebooks/analysis/rq2_spread.py

READ-ONLY: one SELECT against token_prices. Writes two PNGs to
notebooks/figures/ and prints every number the write-up quotes.

Session windows are computed here from the ET weekday/hour (no Alpaca call),
with Labor Day (Mon 2026-09-07) treated as weekend: the weekend that week runs
Fri 20:00 to Mon 20:00 ET. The Alpaca `market_open` flag is used only as a
cross-check of the regular-hours label.
"""

from __future__ import annotations

import sys
from datetime import date
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
HOLIDAYS = {date(2026, 9, 7)}  # Labor Day: closed all day, behaves like weekend
WINDOWS = ["regular", "premarket", "afterhours", "overnight", "weekend"]
MAX_SPREAD_PCT = 20.0  # above this a $1,000 quote is a broken route, not a spread
MAX_MID_DEV_PCT = 20.0  # mid this far from the last swap = mis-sized / bad quote
MIN_UNITS = 5  # per symbol: minimum day-units in each of weekend and regular

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def hr(title: str) -> None:
    print("\n" + "=" * 78 + "\n" + title + "\n" + "=" * 78)


# ---------------------------------------------------------------- load
q = """
select sampled_at, symbol, underlying, usd_price, liquidity_usd, market_price,
       market_trade_at, market_open, bid_usd, ask_usd, bid_impact_pct,
       ask_impact_pct, quote_size_usd
from token_prices
where sampled_at >= (select min(sampled_at) from token_prices where bid_usd is not null)
"""
raw = pd.read_sql(text(q), db.engine())
num = ["usd_price", "liquidity_usd", "market_price", "bid_usd", "ask_usd",
       "bid_impact_pct", "ask_impact_pct", "quote_size_usd"]
raw[num] = raw[num].astype(float)
raw["et"] = raw["sampled_at"].dt.tz_convert(ET)


# ---------------------------------------------------------------- windows
def window(ts: pd.Timestamp) -> str:
    d, h = ts.date(), ts.hour + ts.minute / 60
    wd = ts.weekday()  # Mon=0
    # weekend: Fri 20:00 -> Sun 20:00, extended over a Monday holiday
    if wd == 5 or (wd == 4 and h >= 20) or (wd == 6 and h < 20):
        return "weekend"
    if wd == 6 and h >= 20:  # Sunday evening: overnight, unless Monday is a holiday
        nxt = (ts + pd.Timedelta(days=1)).date()
        return "weekend" if nxt in HOLIDAYS else "overnight"
    if d in HOLIDAYS:
        return "weekend" if h < 20 else "overnight"
    if h < 4:  # includes Tue 00:00-04:00 after a Monday holiday: overnight, as usual
        return "overnight"
    if h < 9.5:
        return "premarket"
    if h < 16:
        return "regular"
    if h < 20:
        return "afterhours"
    return "overnight"


raw["window"] = raw["et"].map(window)
raw["how"] = raw["et"].dt.weekday * 24 + raw["et"].dt.hour  # hour of week, Mon 00 = 0
raw["date_et"] = raw["et"].dt.date

# ---------------------------------------------------------------- 1. data quality
hr("1. DATA QUALITY")
n_all = len(raw)
runs = raw["sampled_at"].drop_duplicates().sort_values()
gaps = runs.diff().dt.total_seconds() / 60
print(f"rows since first spread run ({raw.sampled_at.min():%Y-%m-%d %H:%M} UTC "
      f"to {raw.sampled_at.max():%Y-%m-%d %H:%M} UTC): {n_all}")
print(f"distinct sampling runs: {len(runs)}; median gap between runs "
      f"{gaps.median():.1f} min, mean {gaps.mean():.1f} min, max {gaps.max():.0f} min")
print("runs per ET date (cron is best-effort; first 4 days dense, then ~4-8/day):")
print(raw.groupby("date_et")["sampled_at"].nunique().describe().round(1).to_string())

null = raw["bid_usd"].isna() | raw["ask_usd"].isna()
print(f"\nnull bid/ask (quote leg failed, mostly Jupiter 429 rate limits): "
      f"{null.sum()} ({null.mean():.1%})")
d = raw[~null].copy()
d["mid"] = (d.bid_usd + d.ask_usd) / 2
d["spread_pct"] = (d.ask_usd - d.bid_usd) / d.mid * 100
d["mid_dev_pct"] = (d.mid / d.usd_price - 1) * 100
print(f"rows with a spread: {len(d)}")

neg = d.spread_pct < 0
zero = d.spread_pct == 0
absurd = (d.spread_pct > MAX_SPREAD_PCT) | (d.mid_dev_pct.abs() > MAX_MID_DEV_PCT)
print(f"negative spread (ask < bid): {neg.sum()} ({neg.mean():.2%}); "
      f"median of those {d.spread_pct[neg].median():.3f}%, min {d.spread_pct.min():.3f}%")
print("  cause: the ask and bid legs are two separate quotes ~1-2 s apart, so the pool "
      "can move between them;\n  a negative value is timing noise, not a free arbitrage.")
print("  negative spreads by symbol:", d[neg].symbol.value_counts().head(8).to_dict())
print(f"zero spread: {zero.sum()}")
print(f"absurd (spread > {MAX_SPREAD_PCT}% or |mid/last-1| > {MAX_MID_DEV_PCT}%): {absurd.sum()}")
if absurd.any():
    print(d[absurd][["sampled_at", "symbol", "usd_price", "bid_usd", "ask_usd",
                     "spread_pct", "mid_dev_pct"]].head(10).to_string())

# last swap price relative to the executable quotes
inside = (d.usd_price >= d.bid_usd) & (d.usd_price <= d.ask_usd)
ok_order = d.ask_usd >= d.bid_usd
print(f"\nlast-swap usd_price OUTSIDE [bid, ask] (rows with ask >= bid): "
      f"{(~inside[ok_order]).sum()} of {ok_order.sum()} ({(~inside[ok_order]).mean():.1%})")
above = (d.usd_price > d.ask_usd)[ok_order].mean()
below = (d.usd_price < d.bid_usd)[ok_order].mean()
print(f"  above the ask {above:.1%}, below the bid {below:.1%}; "
      f"median |mid/last - 1| = {d.mid_dev_pct.abs().median():.3f}%, "
      f"p95 = {d.mid_dev_pct.abs().quantile(.95):.3f}%")

dev_bid = ((d.usd_price / d.bid_usd - 1) * 100).groupby(d.symbol).median().sort_values()
print("  median (last/bid - 1) % by symbol, most negative first:",
      dev_bid.head(6).round(3).to_dict())
print("  share of rows with last < bid, by window:",
      (d.usd_price < d.bid_usd).groupby(d.window).mean().round(3).to_dict())

# exclusion rule: drop nulls, negative and absurd; keep negatives for a sensitivity run
d_incl_neg = d[~absurd].copy()
c = d[~neg & ~absurd].copy()
print(f"\nEXCLUSION RULES: drop null quotes, ask < bid, and absurd rows -> {len(c)} rows kept "
      f"({len(c)/n_all:.1%} of all rows). Sensitivity run keeps the negatives.")

# label cross-check against the Alpaca clock
xt = pd.crosstab(c["window"], c["market_open"])
print("\nwindow label vs Alpaca market_open flag:\n" + xt.to_string())

# symbol coverage
cov = c.pivot_table(index="symbol", columns="window", values="spread_pct",
                    aggfunc="size", fill_value=0)[WINDOWS]
print("\nobservations per symbol and window:\n" + cov.to_string())

# ---------------------------------------------------------------- 2. distribution
hr("2. SPREAD_PCT DISTRIBUTION")
q_ = c.spread_pct.quantile([.05, .25, .5, .75, .95, .99])
print("pooled spread_pct (%), all windows:", {f"p{int(k*100)}": round(v, 4) for k, v in q_.items()},
      f"mean {c.spread_pct.mean():.4f}")
per_sym = c.groupby("symbol").agg(n=("spread_pct", "size"),
                                 median_spread=("spread_pct", "median"),
                                 p90_spread=("spread_pct", lambda x: x.quantile(.9)),
                                 median_liq_usd=("liquidity_usd", "median"))
print(per_sym.sort_values("median_spread").round(4).to_string())

# ---------------------------------------------------------------- 3. by window
hr("3. SPREAD BY SESSION WINDOW")
by_w = c.groupby("window").spread_pct.agg(["size", "median", "mean"]).loc[WINDOWS]
print("pooled (raw rows):\n" + by_w.round(4).to_string())

# median of per-symbol medians, so busy symbols do not dominate
sym_w = c.pivot_table(index="symbol", columns="window", values="spread_pct",
                      aggfunc="median")[WINDOWS]
print("\nmedian across symbols of per-symbol window medians (%):")
print(sym_w.median().round(4).to_string())

# Autocorrelation: raw samples within one symbol-day are not independent (and the
# first four days were sampled ~20x more densely). Unit of analysis = one
# (symbol, ET date, window) median. A weekend day is one unit, a regular session one unit.
units = (c.groupby(["symbol", "date_et", "window"])
         .agg(spread=("spread_pct", "median"), n=("spread_pct", "size"),
              liq=("liquidity_usd", "median"))
         .reset_index())
units["log_spread"] = np.log(units.spread)
print(f"\naggregated to {len(units)} symbol-day-window units "
      f"(from {len(c)} rows); median rows per unit {units.n.median():.0f}")

rows = []
for sym, g in units.groupby("symbol"):
    wk = g[g.window == "weekend"].spread
    rg = g[g.window == "regular"].spread
    if len(wk) < MIN_UNITS or len(rg) < MIN_UNITS:
        continue
    u, p = stats.mannwhitneyu(wk, rg, alternative="two-sided")
    rows.append(dict(symbol=sym, n_wkd=len(wk), n_reg=len(rg),
                     med_regular=rg.median(), med_weekend=wk.median(),
                     ratio=wk.median() / rg.median(), p_mw=p))
mw = pd.DataFrame(rows).set_index("symbol").sort_values("ratio")
# Holm correction across symbols
order = mw.p_mw.sort_values().index
m = len(order)
holm, running = {}, 0.0
for i, s in enumerate(order):
    running = max(running, min(1.0, (m - i) * mw.p_mw[s]))
    holm[s] = running
mw["p_holm"] = pd.Series(holm)
mw["verdict"] = np.where(mw.p_holm < 0.05,
                         np.where(mw.ratio > 1, "WIDER on weekend", "NARROWER on weekend"),
                         "no sig. difference")
print("\nper-symbol weekend vs regular, Mann-Whitney on daily medians (Holm-adjusted):")
print(mw.round(4).to_string())

# Balanced panel: only symbols tested above, and every summary below is a median
# of DAILY medians, so the dense 1-4 Sep weekday runs and thinly covered symbols
# (AVGOx, INTCx with ~5 weekend obs) cannot drive the window comparison.
CORE = list(mw.index)
cu = units[units.symbol.isin(CORE)]
sym_w = cu.pivot_table(index="symbol", columns="window", values="spread", aggfunc="median")[WINDOWS]
print(f"\nBALANCED PANEL ({len(CORE)} symbols), median across symbols of per-symbol median "
      "daily spread (%):")
print(sym_w.median().round(4).to_string())
print("raw-row version above is NOT comparable: it mixes symbol composition and the dense "
      "first four days.")

# Time trend: were spreads simply tighter later in the window?
cu_w = cu.assign(week=pd.to_datetime(cu.date_et).dt.to_period("W-SUN"))
trend = (cu_w.groupby(["week", "symbol"]).spread.median().groupby("week").median())
print("\nweekly median (across core symbols) of per-symbol median daily spread (%):")
print(trend.round(4).to_string())
dense = cu[cu.date_et <= date(2026, 9, 4)].groupby("symbol").spread.median()
later = cu[(cu.date_et > date(2026, 9, 4)) & (cu.window == "regular")].groupby("symbol").spread.median()
print(f"core symbols, 1-4 Sep median spread {dense.median():.4f}% vs later regular-hours "
      f"{later.median():.4f}%")

# Pooled test 1: across symbols, is log(weekend/regular) centred on 0?
lr = np.log(mw.ratio)
w_stat, w_p = stats.wilcoxon(lr)
n_up = int((mw.ratio > 1.005).sum())  # ties at the fee floor (ratio 1.00) are not "wider"
n_down = int((mw.ratio < 0.995).sum())
b_p = stats.binomtest(n_up, n_up + n_down, 0.5).pvalue  # ties dropped
print(f"\nPOOLED across {len(mw)} symbols: median weekend/regular ratio "
      f"{mw.ratio.median():.3f} (geo-mean {np.exp(lr.mean()):.3f}); "
      f"{n_up} wider, {n_down} narrower, {len(mw) - n_up - n_down} tied (within 0.5%)")
print(f"  Wilcoxon signed-rank on log ratios: W={w_stat:.1f}, p={w_p:.4g}; sign test p={b_p:.4g}")


# Pooled test 2: OLS of log spread on window dummies + symbol FE, on the daily
# units, cluster-robust SEs by ET date (all symbols on a date share a shock).
def ols_cluster(df: pd.DataFrame, cluster: str):
    X = pd.get_dummies(df[["window", "symbol"]], drop_first=False, dtype=float)
    X = X.drop(columns=["window_regular", X.filter(like="symbol_").columns[0]])
    X.insert(0, "const", 1.0)
    y = df["log_spread"].to_numpy()
    Xv = X.to_numpy()
    XtX_inv = np.linalg.pinv(Xv.T @ Xv)
    beta = XtX_inv @ Xv.T @ y
    resid = y - Xv @ beta
    meat = np.zeros((Xv.shape[1], Xv.shape[1]))
    groups = df[cluster].to_numpy()
    G = 0
    for gval in pd.unique(groups):
        idx = groups == gval
        sg = Xv[idx].T @ resid[idx]
        meat += np.outer(sg, sg)
        G += 1
    n, k = Xv.shape
    adj = G / (G - 1) * (n - 1) / (n - k)
    V = adj * XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.diag(V))
    out = pd.DataFrame({"coef": beta, "se": se}, index=X.columns)
    out["t"] = out.coef / out.se
    out["p"] = 2 * stats.t.sf(out.t.abs(), df=G - 1)
    out["pct_vs_regular"] = (np.exp(out.coef) - 1) * 100
    return out.loc[[c_ for c_ in X.columns if c_.startswith("window_")]], G


reg, G = ols_cluster(units, "date_et")
print(f"\nREGRESSION log(spread) ~ window + symbol FE, daily units, "
      f"cluster-robust by ET date ({G} clusters), regular = baseline:")
print(reg.round(4).to_string())

# Sensitivity: same regression on raw rows (clustered by date) and with negatives kept
raw_units = c.assign(log_spread=np.log(c.spread_pct))
reg_raw, Gr = ols_cluster(raw_units, "date_et")
print(f"\nsensitivity A - raw rows, clustered by date ({Gr} clusters):")
print(reg_raw[["coef", "se", "p", "pct_vs_regular"]].round(4).to_string())
neg_units = (d_incl_neg.groupby(["symbol", "date_et", "window"]).spread_pct.median()
             .reset_index(name="spread"))
neg_units = neg_units[neg_units.spread > 0].assign(log_spread=lambda x: np.log(x.spread))
reg_neg, _ = ols_cluster(neg_units, "date_et")
print("sensitivity B - negative-spread rows kept before the daily median:")
print(reg_neg[["coef", "se", "p", "pct_vs_regular"]].round(4).to_string())
# Sensitivity C: drop the dense 2026-09-01..04 start
late = units[units.date_et >= date(2026, 9, 5)]
reg_late, _ = ols_cluster(late, "date_et")
print("sensitivity C - from 2026-09-05 only (uniform cron cadence):")
print(reg_late[["coef", "se", "p", "pct_vs_regular"]].round(4).to_string())

# ---------------------------------------------------------------- 4. hour of week figure
hr("4. HOUR-OF-WEEK FIGURE")
cc = c[c.symbol.isin(CORE)]
hw = (cc.groupby(["symbol", "date_et", "how"]).spread_pct.median()
      .groupby(["symbol", "how"]).median().unstack("symbol"))
hw_med = hw.median(axis=1).reindex(range(168))
hw_n = cc.groupby("how").size().reindex(range(168), fill_value=0)
print(f"hour-of-week bins with data: {hw_med.notna().sum()}/168; "
      f"rows per bin median {hw_n.median():.0f}, min {hw_n.min()}")
# 3-hour centred circular rolling median for the readable line
ext = pd.concat([hw_med.iloc[-2:], hw_med, hw_med.iloc[:2]])
smooth = ext.rolling(5, center=True, min_periods=2).median().iloc[2:-2]
smooth.index = range(168)

INK, MUTED, LINE, SHADE = "#1f2328", "#6b7280", "#2563eb", "#f59e0b"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.edgecolor": "#c7cbd1", "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED})
fig, ax = plt.subplots(figsize=(12, 4.6), dpi=150)
# weekend = Fri 20:00 (4*24+20=116) to Sun 20:00 (6*24+20=164)
ax.axvspan(116, 164, color=SHADE, alpha=0.14, lw=0)
for day in range(5):  # regular sessions, faint
    ax.axvspan(day * 24 + 9.5, day * 24 + 16, color="#9ca3af", alpha=0.10, lw=0)
ax.scatter(hw_med.index + 0.5, hw_med.values, s=9, color=LINE, alpha=0.35, lw=0,
           label="hourly bin (median of per-symbol medians)")
ax.plot(smooth.index + 0.5, smooth.values, color=LINE, lw=2,
        label="5-hour rolling median")
wk_level = sym_w["weekend"].median()
rg_level = sym_w["regular"].median()
ax.axhline(rg_level, xmin=0, xmax=1, color=MUTED, lw=1, ls=":")
ax.text(167.5, rg_level, f" regular-hours level {rg_level:.2f}%", va="bottom",
        ha="right", color=MUTED, fontsize=8.5)
ax.set_xlim(0, 168)
ax.set_ylim(0, max(np.nanpercentile(hw_med, 99) * 1.15, wk_level * 1.4))
ax.set_xticks([i * 24 for i in range(8)])
ax.set_xticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", ""])
ax.set_xticks([i * 24 + 12 for i in range(7)], minor=True)
ax.tick_params(axis="x", which="minor", length=2)
ax.set_xlabel("Hour of week (US Eastern time; tick = midnight)")
ax.set_ylabel("Executable spread, % of mid\n($1,000 round-trip quote)")
wk_p = reg.loc["window_weekend", "p"]
verb = ("do not widen" if wk_p >= 0.05 else ("widen" if wk_level > rg_level else "narrow"))
ax.set_title(f"xStock spreads {verb} when the US market is closed: weekend median "
             f"{wk_level:.2f}% vs {rg_level:.2f}% in regular hours (p = {wk_p:.2f})",
             loc="left", color=INK, fontsize=11.5)
ax.text(140, ax.get_ylim()[1] * 0.96, "weekend\nFri 20:00 to Sun 20:00 ET", ha="center",
        va="top", color="#92400e", fontsize=8.5)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.grid(axis="y", color="#e5e7eb", lw=0.8)
ax.set_axisbelow(True)
from matplotlib.patches import Patch  # noqa: E402
h_, l_ = ax.get_legend_handles_labels()
h_.append(Patch(color="#9ca3af", alpha=0.25, lw=0))
l_.append("regular session 09:30-16:00 ET")
ax.legend(h_, l_, loc="lower left", frameon=True, facecolor="white", edgecolor="none",
          framealpha=0.9, fontsize=8.5, ncol=3)
fig.text(0.01, 0.012, f"Source: Yagnum token_prices, Jupiter $1,000 quotes, {len(CORE)} xStocks, "
         f"{c.sampled_at.min():%d %b} to {c.sampled_at.max():%d %b %Y}, n={len(cc):,} quotes. "
         "Per bin: median over symbols of each symbol's median daily spread.\nEmpty bins = no runs "
         "(best-effort cron). Labor Day plotted at its Monday hours. p: window dummy, symbol FE, "
         "date-clustered.",
         fontsize=7.5, color=MUTED)
fig.tight_layout(rect=(0, 0.06, 1, 1))
FIG.mkdir(parents=True, exist_ok=True)
fig.savefig(FIG / "rq2_spread_hour_of_week.png")
plt.close(fig)
print("saved", FIG / "rq2_spread_hour_of_week.png")

# ---------------------------------------------------------------- 5. ratio figure
fig, ax = plt.subplots(figsize=(8, 0.32 * len(mw) + 1.6), dpi=150)
mws = mw.sort_values("ratio")
colors = np.where(mws.verdict == "WIDER on weekend", LINE,
                  np.where(mws.verdict == "NARROWER on weekend", "#dc2626", "#9ca3af"))
ax.barh(mws.index.str.removesuffix("x"), mws.ratio - 1, left=1, color=colors, height=0.7)
ax.axvline(1, color=INK, lw=1)
for i, (s, r) in enumerate(mws.iterrows()):
    ax.text(max(r.ratio, 1) + 0.03, i, f"{r.ratio:.2f}x  ({r.med_regular:.2f}% -> "
            f"{r.med_weekend:.2f}%)", va="center", fontsize=7.5, color=MUTED)
ax.set_xlim(min(0.8, mws.ratio.min() - 0.05), mws.ratio.max() * 1.45)
ax.set_xlabel("Weekend median spread / regular-hours median spread (1 = no change)")
n_sig = int((mw.p_holm < 0.05).sum())
ax.set_title(f"Weekend vs regular-hours spread: {n_up} of {len(mw)} xStocks wider, {n_down} narrower,\n"
             f"{n_sig} significant after Holm correction", loc="left", fontsize=11.5, color=INK)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
present = {"WIDER on weekend": (LINE, "wider, Holm p < 0.05"),
           "no sig. difference": ("#9ca3af", "not significant (Holm p >= 0.05)"),
           "NARROWER on weekend": ("#dc2626", "narrower, Holm p < 0.05")}
ax.legend(handles=[Patch(color=col, label=lab) for k, (col, lab) in present.items()
                   if (mws.verdict == k).any()], loc="lower right", frameon=False, fontsize=8)
fig.text(0.01, 0.005, "Mann-Whitney on per-day medians, Holm-adjusted across symbols. "
         "Ratio of medians of daily-median spreads.", fontsize=7, color=MUTED)
fig.tight_layout(rect=(0, 0.02, 1, 1))
fig.savefig(FIG / "rq2_spread_ratio_by_symbol.png")
plt.close(fig)
print("saved", FIG / "rq2_spread_ratio_by_symbol.png")

# ---------------------------------------------------------------- 6. basis, liquidity
hr("6. TOKEN-VS-SHARE BASIS AND LIQUIDITY")
b = c[c.market_price.notna() & (c.market_price > 0)].copy()
b["stale_s"] = (b.sampled_at - b.market_trade_at).dt.total_seconds()
reg_b = b[(b.window == "regular") & b.market_open & (b.stale_s.between(-60, 300))].copy()
reg_b["basis_pct"] = (reg_b.mid / reg_b.market_price - 1) * 100
print(f"regular hours, share print <= 5 min old: n={len(reg_b)}; "
      f"median basis {reg_b.basis_pct.median():.3f}%, median |basis| "
      f"{reg_b.basis_pct.abs().median():.3f}%, p95 |basis| {reg_b.basis_pct.abs().quantile(.95):.3f}%")
wkb = b[b.window == "weekend"].copy()
# the share's last print during a weekend is Friday's (or the holiday-eve) last trade
wkb["drift_pct"] = (wkb.mid / wkb.market_price - 1) * 100
wkb["print_age_h"] = wkb.stale_s / 3600
print(f"weekend, token mid vs the share's last (Friday) print: n={len(wkb)}; "
      f"median |drift| {wkb.drift_pct.abs().median():.3f}%, p95 {wkb.drift_pct.abs().quantile(.95):.3f}%; "
      f"median print age {wkb.print_age_h.median():.1f} h")
basis_tbl = pd.DataFrame({
    "reg_med_abs_basis": reg_b.groupby("symbol").basis_pct.apply(lambda x: x.abs().median()),
    "wkd_med_abs_drift": wkb.groupby("symbol").drift_pct.apply(lambda x: x.abs().median()),
    "wkd_med_spread": sym_w["weekend"],
}).dropna()
basis_tbl["half_spread_share_of_drift"] = basis_tbl.wkd_med_spread / 2 / basis_tbl.wkd_med_abs_drift
print(basis_tbl.sort_values("wkd_med_abs_drift").round(3).to_string())

liq = c.groupby("symbol").agg(spread=("spread_pct", "median"), liq=("liquidity_usd", "median"))
rho_x, p_x = stats.spearmanr(liq.liq, liq.spread)
print(f"\ncross-section (per-symbol medians): Spearman rho(liquidity, spread) = {rho_x:.3f}, p={p_x:.3g}, n={len(liq)}")
within = []
for sym, g in units.groupby("symbol"):
    if len(g) >= 20 and g.liq.nunique() > 5:
        within.append(stats.spearmanr(g.liq, g.spread)[0])
within = np.array(within)
print(f"within-symbol over time (daily units): median rho {np.median(within):.3f} across "
      f"{len(within)} symbols, {np.sum(within < 0)} negative")
lw = cu.pivot_table(index="symbol", columns="window", values="liq", aggfunc="median")
lr_ = (lw["weekend"] / lw["regular"]).dropna()
print(f"within-symbol weekend/regular liquidity_usd ratio: median {lr_.median():.3f}, "
      f"{(lr_ > 1).sum()}/{len(lr_)} symbols higher on the weekend")

# ---------------------------------------------------------------- 7. dollars
hr("7. WHAT THE SPREAD COSTS A TRADER")
print("Crossing cost vs mid = half the spread (one way); a round trip pays the full spread.")
for w in WINDOWS:
    s_ = sym_w[w].median()
    print(f"  {w:<11} median spread {s_:.3f}%  ->  one-way on $1,000 ${s_/2*10:.2f}, "
          f"on $10,000 ${s_/2*100:.2f} (lower bound); round trip $1,000 ${s_*10:.2f}")
wk_p90 = c[c.window == "weekend"].groupby("symbol").spread_pct.quantile(.9).median()
print(f"weekend p90 spread (median across symbols): {wk_p90:.3f}%")
print("Per-symbol weekend one-way cost as a share of a 3% / 10% reserve:")
cost = pd.DataFrame({"wkd_spread": sym_w["weekend"], "reg_spread": sym_w["regular"]}).dropna()
cost["wkd_half_spread_$1k"] = cost.wkd_spread / 2 * 10
cost["extra_vs_regular_$1k"] = (cost.wkd_spread - cost.reg_spread) / 2 * 10
cost["half_spread_pct_of_3pct_reserve"] = cost.wkd_spread / 2 / 3 * 100
cost["half_spread_pct_of_10pct_reserve"] = cost.wkd_spread / 2 / 10 * 100
print(cost.sort_values("wkd_spread").round(3).to_string())
print("\nNOTE: quotes are for $1,000 only; a $10,000 trade incurs at least 10x the dollar "
      "cost and likely more (price impact grows with size). Not measured here.")
