"""Walk-forward reserve backtest: does reserve = sigma * z cover the weekend gap
on far more than the 126 settled trades?

Run from app/api:
    uv run --group research python ../../notebooks/analysis/reserve_backtest.py

READ-ONLY: SELECT statements against market_bars, token_candles and
token_prices. Writes one PNG to notebooks/figures/ and prints every number.

Design
------
For every symbol and every weekend:
  * p_open  = the token's price at Saturday 12:00 ET (close of the last hourly
              GeckoTerminal candle, at most 6 h stale), else the share's last
              close before the weekend (Friday close, Thursday on Good Friday).
              A robustness run uses Sunday 20:00 ET instead of Saturday noon.
  * p_close = the share's first open after the weekend (daily bar open;
              Tuesday after a Monday holiday).
  * sigma   = the engine's rule max(sigma_market, sigma_token), each computed
              ONLY from weekends whose Monday open happened before this
              weekend's Friday close (no look-ahead):
                sigma_market = std (ddof=1) of ln(next open / last close) over
                               the trailing 104 weekends, needs >= 26 prior
                sigma_token  = std of ln(next open / token Sun 23:00) over all
                               prior token weekends, needs >= 8, else ignored
  * reserve = notional * sigma * z, z = 3.7742, on a $10,000 notional in
              Decimal, rounded up to the cent (as err.compute does).
  * breach  = the true-up exceeds the reserve: buy when the price rose by more
              than the reserve, sell when it fell by more.

Market daily bars stop at 2026-08-31, so weekends after that are added only
where the sampler caught a usable Friday close and Monday open (see section 1).
z = 3.7742 was fitted on Mar-Aug 2026 token weekends, so the token-era rows are
not fully out of sample for z; the 2024-2026 share-only rows are.
"""

from __future__ import annotations

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
Z = Decimal("3.7742")
NOTIONAL = Decimal("10000")
CENT = Decimal("0.01")
TARGET = 0.01  # one-sided breach rate the design promises
WIN_MKT = 104  # trailing weekends for sigma_market (~2 years)
MIN_MKT = 26
MIN_TOK = 8
MAX_STALE_H = 6

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_rows", 200)


def hr(title: str) -> None:
    print("\n" + "=" * 78 + "\n" + title + "\n" + "=" * 78)


eng = db.engine()

# ---------------------------------------------------------------- load
daily = pd.read_sql(
    text("select symbol, bucket_start, open, close from market_bars where timeframe = '1Day' "
         "order by symbol, bucket_start"), eng)
daily[["open", "close"]] = daily[["open", "close"]].astype(float)
daily["d"] = daily.bucket_start.dt.tz_convert(ET).dt.date

cand = pd.read_sql(
    text("select symbol, bucket_start, close from token_candles where timeframe = 'hour' "
         "order by symbol, bucket_start"), eng)
cand["close"] = cand.close.astype(float)
cand["share"] = cand.symbol.str[:-1]
cand_by = {s: g.set_index("bucket_start").close for s, g in cand.groupby("share")}

tp = pd.read_sql(
    text("select sampled_at, underlying, market_price, market_trade_at, market_open "
         "from token_prices where underlying is not null order by sampled_at"), eng)
tp["market_price"] = tp.market_price.astype(float)
tp["market_open"] = tp.market_open.fillna(False).astype(bool)
tp["trade_et"] = tp.market_trade_at.dt.tz_convert(ET)


def token_at(sym: str, when_et: pd.Timestamp) -> float:
    """Close of the last hourly candle that ENDED at or before `when`, if <= 6 h old."""
    s = cand_by.get(sym)
    if s is None:
        return np.nan
    when = when_et.tz_convert("UTC")
    idx = s.index.searchsorted(when - pd.Timedelta(hours=1), side="right") - 1
    if idx < 0:
        return np.nan
    age = (when - (s.index[idx] + pd.Timedelta(hours=1))).total_seconds() / 3600
    return float(s.iloc[idx]) if age <= MAX_STALE_H else np.nan


def et(d: date, hh: int, mm: int = 0) -> pd.Timestamp:
    return pd.Timestamp(f"{d} {hh:02d}:{mm:02d}", tz=ET)


# ---------------------------------------------------------------- 1. build weekends
hr("1. DATA: SHARE WEEKENDS FROM DAILY BARS, PLUS SAMPLER WEEKENDS AFTER 2026-08-31")
rows = []
for sym, g in daily.groupby("symbol"):
    g = g.sort_values("d").reset_index(drop=True)
    for i in range(len(g) - 1):
        d0, d1 = g.d[i], g.d[i + 1]
        # a weekend lies between them: some Saturday in (d0, d1)
        sat = d0 + timedelta(days=(5 - d0.weekday()) % 7 or 7) if d0.weekday() != 5 else d0
        if not (d0 < sat < d1):
            continue
        rows.append(dict(symbol=sym, last_session=d0, next_session=d1, sat=sat,
                         p_fri=g.close[i], p_mon=g.open[i + 1], src_close="daily_bar"))
wk = pd.DataFrame(rows)
print(f"daily-bar weekends: {len(wk)} symbol-weekends, {wk.symbol.nunique()} symbols, "
      f"{wk.sat.nunique()} distinct weekends, {wk.sat.min()} to {wk.sat.max()}")
print(f"long weekends (next session not a Monday, or last session not a Friday): "
      f"{int(((pd.to_datetime(wk.next_session).dt.weekday != 0) | (pd.to_datetime(wk.last_session).dt.weekday != 4)).sum())}")

# --- sampler extension after the last daily bar
last_bar = daily.d.max()
sess_dates = set(daily.d) | set(tp.loc[tp.market_open, "sampled_at"].dt.tz_convert(ET).dt.date)
sess_sorted = sorted(sess_dates)
ext = []
for sym, g in tp.groupby("underlying"):
    if sym not in set(daily.symbol):
        continue
    for i in range(len(sess_sorted) - 1):
        d0, d1 = sess_sorted[i], sess_sorted[i + 1]
        if d0 < last_bar or (d1 - d0).days < 2:
            continue
        # Friday close: the last regular-session print, 15:55-16:00:59 ET on d0
        c = g[(g.trade_et >= et(d0, 15, 55)) & (g.trade_et < et(d0, 16, 1))]
        # Monday open: a print in 09:30-09:40 ET on d1 while market_open
        o = g[(g.trade_et >= et(d1, 9, 30)) & (g.trade_et < et(d1, 9, 40)) & g.market_open]
        sat = d0 + timedelta(days=(5 - d0.weekday()) % 7 or 7)
        ext.append(dict(symbol=sym, last_session=d0, next_session=d1, sat=sat,
                        p_fri=c.market_price.iloc[-1] if len(c) else np.nan,
                        p_mon=o.market_price.iloc[0] if len(o) else np.nan,
                        src_close="sampler"))
ext = pd.DataFrame(ext)
n_ext_all = len(ext)
ext_ok = ext.dropna(subset=["p_fri", "p_mon"])
print(f"sampler weekends after {last_bar}: {n_ext_all} symbol-weekends possible over "
      f"{ext.sat.nunique() if len(ext) else 0} weekends; usable (Friday 15:55-16:00 print AND "
      f"Monday 09:30-09:40 print both caught): {len(ext_ok)}")
if len(ext):
    print("  usable per weekend:", ext_ok.groupby("sat").size().to_dict())
print("  (the cron samples ~6 times a day after early September, so the exact open is "
      "rarely caught;\n   missing weekends are dropped, not filled)")
wk = pd.concat([wk, ext_ok], ignore_index=True).sort_values(["symbol", "sat"]).reset_index(drop=True)
wk = wk.drop_duplicates(["symbol", "sat"], keep="first")

# token prices at the simulated trade moment and at Sunday 23:00 (for sigma_token)
wk["p_tok_sat12"] = [token_at(s, et(sat, 12)) for s, sat in zip(wk.symbol, wk.sat)]
wk["p_tok_sun20"] = [token_at(s, et(sat + timedelta(days=1), 20)) for s, sat in zip(wk.symbol, wk.sat)]
wk["p_tok_sun23"] = [token_at(s, et(sat + timedelta(days=1), 23)) for s, sat in zip(wk.symbol, wk.sat)]
wk["r_mkt"] = np.log(wk.p_mon / wk.p_fri)
wk["r_tok"] = np.log(wk.p_mon / wk.p_tok_sun23)
print(f"\nsymbol-weekends total: {len(wk)}; with a fresh token price at Sat 12:00 ET: "
      f"{wk.p_tok_sat12.notna().sum()}; at Sun 20:00 ET: {wk.p_tok_sun20.notna().sum()}; "
      f"at Sun 23:00 ET (sigma_token input): {wk.p_tok_sun23.notna().sum()}")


# ---------------------------------------------------------------- 2. walk-forward sigma
def walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("sat").reset_index(drop=True)
        for i, r in g.iterrows():
            prior = g[g.next_session <= r.last_session]  # Monday open already happened
            pm = prior.r_mkt.dropna().tail(WIN_MKT)
            pt = prior.r_tok.dropna()
            s_m = pm.std(ddof=1) if len(pm) >= MIN_MKT else np.nan
            s_t = pt.std(ddof=1) if len(pt) >= MIN_TOK else np.nan
            out.append(dict(symbol=sym, sat=r.sat, sigma_mkt=s_m,
                            sigma_tok=s_t, n_prior_mkt=len(pm), n_prior_tok=len(pt)))
    return pd.DataFrame(out)


sig = walk_forward(wk)
wk = wk.merge(sig, on=["symbol", "sat"])
wk["sigma"] = wk[["sigma_mkt", "sigma_tok"]].max(axis=1)  # NaN token side is ignored
wk = wk[wk.sigma_mkt.notna()].copy()  # need a share history before testing


def to_dec(x: float) -> Decimal:
    return Decimal(repr(float(x)))


def simulate(df: pd.DataFrame, ref_col: str) -> pd.DataFrame:
    d = df.copy()
    d["p_open"] = d[ref_col].where(d[ref_col].notna(), d.p_fri)
    d["ref"] = np.where(d[ref_col].notna(), "token", "friday_close")
    buys, sells, res = [], [], []
    for p_open, p_close, s in zip(d.p_open, d.p_mon, d.sigma):
        po, pc = to_dec(p_open), to_dec(p_close)
        qty = NOTIONAL / po
        reserve = (NOTIONAL * to_dec(s) * Z).quantize(CENT, rounding=ROUND_CEILING)
        tu_sell = qty * (pc - po)  # trader's true-up, err.py sign convention
        tu_buy = -qty * (pc - po)
        res.append(reserve)
        sells.append(reserve + tu_sell < 0)
        buys.append(reserve + tu_buy < 0)
    d["reserve"] = res
    d["reserve_pct"] = [float(r / NOTIONAL) for r in res]
    d["buy_breach"] = buys
    d["sell_breach"] = sells
    d["gap"] = d.p_mon / d.p_open - 1
    d["util"] = d.gap.abs() / d.reserve_pct
    return d


def kupiec(x: int, n: int, p: float = TARGET) -> tuple[float, float]:
    """Kupiec (1995) proportion-of-failures LR test; returns (LR, p-value), chi2(1)."""
    if n == 0:
        return np.nan, np.nan
    ph = x / n
    ll0 = (n - x) * np.log(1 - p) + x * np.log(p)
    ll1 = ((n - x) * np.log(1 - ph) if ph < 1 else 0) + (x * np.log(ph) if x > 0 else 0)
    lr = -2 * (ll0 - ll1)
    return lr, 1 - stats.chi2.cdf(lr, 1)


def christoffersen_ind(seqs: list[np.ndarray]) -> tuple[float, float, dict]:
    """Christoffersen independence LR, transition counts pooled over sequences."""
    n00 = n01 = n10 = n11 = 0
    for s in seqs:
        s = s.astype(int)
        a, b = s[:-1], s[1:]
        n00 += int(((a == 0) & (b == 0)).sum()); n01 += int(((a == 0) & (b == 1)).sum())
        n10 += int(((a == 1) & (b == 0)).sum()); n11 += int(((a == 1) & (b == 1)).sum())
    pi0 = n01 / max(n00 + n01, 1); pi1 = n11 / max(n10 + n11, 1)
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)

    def ll(k0, k1, p):  # k0 non-events, k1 events
        return (k0 * np.log(1 - p) if p < 1 and k0 else 0) + (k1 * np.log(p) if p > 0 and k1 else 0)

    lr = -2 * (ll(n00 + n10, n01 + n11, pi) - ll(n00, n01, pi0) - ll(n10, n11, pi1))
    return lr, 1 - stats.chi2.cdf(lr, 1), dict(n00=n00, n01=n01, n10=n10, n11=n11, pi0=pi0, pi1=pi1)


def report(d: pd.DataFrame, label: str) -> None:
    hr(f"RESULTS - trade moment {label}")
    n = len(d)
    print(f"symbol-weekends tested: {n} ({d.symbol.nunique()} symbols, {d.sat.nunique()} weekends, "
          f"{d.sat.min()} to {d.sat.max()})")
    print(f"p_open from token: {(d.ref == 'token').sum()}, from Friday close: {(d.ref == 'friday_close').sum()}")
    print(f"sigma source: token side binding (sigma_tok > sigma_mkt) on "
          f"{int((d.sigma_tok > d.sigma_mkt).sum())} rows; token side available on {int(d.sigma_tok.notna().sum())}")
    print(f"mean reserve {d.reserve_pct.mean():.2%} of notional; median {d.reserve_pct.median():.2%}")
    print(f"mean |gap| {d.gap.abs().mean():.2%}; max |gap| {d.gap.abs().max():.2%}; "
          f"mean utilisation {d.util.mean():.1%}; max {d.util.max():.1%}")

    xb, xs = int(d.buy_breach.sum()), int(d.sell_breach.sum())
    print("\nPOOLED COVERAGE (each symbol-weekend is one buy and one sell; at most one can breach)")
    for name, x, nn in [("buy", xb, n), ("sell", xs, n), ("both sides", xb + xs, 2 * n)]:
        lr, p = kupiec(x, nn)
        print(f"  {name:10s} breaches {x:4d} / {nn:5d} = {x / nn:.3%}  coverage {1 - x / nn:.3%}  "
              f"Kupiec LR {lr:.3f}, p = {p:.4f}")
    lo, hi = stats.binomtest(xb + xs, 2 * n).proportion_ci(0.95, method="exact")
    print(f"  95% exact CI for the two-sided breach rate: {lo:.3%} to {hi:.3%}")

    by = d.groupby("symbol").agg(
        n=("sat", "size"), first=("sat", "min"), mean_sigma=("sigma", "mean"),
        mean_reserve=("reserve_pct", "mean"), mean_abs_gap=("gap", lambda s: s.abs().mean()),
        max_abs_gap=("gap", lambda s: s.abs().max()), buy_br=("buy_breach", "sum"),
        sell_br=("sell_breach", "sum"), max_util=("util", "max"))
    by["coverage"] = 1 - (by.buy_br + by.sell_br) / (2 * by.n)
    by["kupiec_p"] = [kupiec(int(b + s), int(2 * k))[1] for b, s, k in zip(by.buy_br, by.sell_br, by.n)]
    by["P(>=x | 1%)"] = [stats.binom.sf(int(b + s) - 1, int(2 * k), TARGET) for b, s, k in zip(by.buy_br, by.sell_br, by.n)]
    print("\nCOVERAGE BY SYMBOL (coverage over 2n trade-sides; per-symbol n is ~40-110 weekends, so")
    print("expected breaches at 1% are ~0.8-2.2: a per-symbol Kupiec test has little power)")
    fmt = by.copy()
    for c in ["mean_sigma", "mean_reserve", "mean_abs_gap", "max_abs_gap", "coverage"]:
        fmt[c] = fmt[c].map(lambda v: f"{v:.2%}")
    fmt["max_util"] = fmt.max_util.map(lambda v: f"{v:.0%}")
    fmt["kupiec_p"] = fmt.kupiec_p.map(lambda v: f"{v:.3f}")
    fmt["P(>=x | 1%)"] = fmt["P(>=x | 1%)"].map(lambda v: f"{v:.3f}")
    print(fmt.sort_values("coverage").to_string())

    tok = d[d.ref == "token"]
    if len(tok):
        xb_t, xs_t = int(tok.buy_breach.sum()), int(tok.sell_breach.sum())
        lr, p = kupiec(xb_t + xs_t, 2 * len(tok))
        print(f"\nTOKEN-PRICED SUBSET (the engine's real situation): {len(tok)} symbol-weekends, "
              f"{tok.sat.nunique()} weekends; breaches buy {xb_t}, sell {xs_t}; "
              f"rate {(xb_t + xs_t) / (2 * len(tok)):.3%}; Kupiec p = {p:.4f}")
        sh = d[d.ref == "friday_close"]
        xb_s, xs_s = int(sh.buy_breach.sum()), int(sh.sell_breach.sum())
        lr, p = kupiec(xb_s + xs_s, 2 * len(sh))
        print(f"FRIDAY-CLOSE SUBSET (share-only history): {len(sh)} symbol-weekends; breaches buy {xb_s}, "
              f"sell {xs_s}; rate {(xb_s + xs_s) / (2 * len(sh)):.3%}; Kupiec p = {p:.4f}")

    m = d[d.symbol == "META"].sort_values("sat")
    print("\nMETA")
    print(f"  weekends {len(m)}; breaches buy {int(m.buy_breach.sum())}, sell {int(m.sell_breach.sum())}; "
          f"mean reserve {m.reserve_pct.mean():.2%}, mean |gap| {m.gap.abs().mean():.2%}, "
          f"p95 |gap| {m.gap.abs().quantile(0.95):.2%}, max |gap| {m.gap.abs().max():.2%}")
    mt = m[m.ref == "token"]
    if len(mt):
        print(f"  token-priced META weekends {len(mt)}: breaches buy {int(mt.buy_breach.sum())}, "
              f"sell {int(mt.sell_breach.sum())}; mean reserve {mt.reserve_pct.mean():.2%}, "
              f"mean |gap| {mt.gap.abs().mean():.2%}, max util {mt.util.max():.0%}")
    print("  META's five largest utilisations:")
    print(m.nlargest(5, "util")[["sat", "ref", "p_open", "p_mon", "gap", "reserve_pct", "util",
                                  "buy_breach", "sell_breach"]].to_string(index=False))

    # ------------------------------------------------ clustering
    d = d.copy()
    d["any_breach"] = d.buy_breach | d.sell_breach
    per = d.groupby("sat").agg(n=("symbol", "size"), breaches=("any_breach", "sum"))
    p_hat = d.any_breach.mean()
    exp_var = (per.n * p_hat * (1 - p_hat)).sum()
    obs_var = ((per.breaches - per.n * p_hat) ** 2).sum()
    print("\nBREACH CLUSTERING IN TIME")
    print(f"  weekends with >= 1 breach: {(per.breaches > 0).sum()} of {len(per)}; "
          f"breaches: {int(per.breaches.sum())}")
    print(f"  dispersion ratio (observed / binomial variance of breaches per weekend): "
          f"{obs_var / exp_var:.2f}  (1 = independent; >1 = clustered)")
    # permutation: shuffle weekend labels within symbol, recount max breaches in one weekend
    rng = np.random.default_rng(7)
    obs_max = per.breaches.max()
    obs_top = per.breaches.sort_values(ascending=False).head(3).sum()
    sims_max, sims_top = [], []
    for _ in range(2000):
        sh = d.groupby("symbol").any_breach.transform(lambda s: rng.permutation(s.values))
        c = sh.groupby(d.sat).sum()
        sims_max.append(c.max()); sims_top.append(c.sort_values(ascending=False).head(3).sum())
    print(f"  most breaches in one weekend: {obs_max}; permutation p (>= that, shuffling weeks "
          f"within symbol, 2000 draws) = {np.mean(np.array(sims_max) >= obs_max):.4f}")
    print(f"  breaches in the top 3 weekends: {obs_top}; permutation p = "
          f"{np.mean(np.array(sims_top) >= obs_top):.4f}")
    lr, p, tc = christoffersen_ind([g.sort_values('sat').any_breach.values for _, g in d.groupby("symbol")])
    print(f"  Christoffersen independence (per-symbol weekend sequences, pooled): LR {lr:.3f}, "
          f"p = {p:.4f}; P(breach | breach last weekend) {tc['pi1']:.3f} vs P(breach | none) {tc['pi0']:.3f} "
          f"(n11 = {tc['n11']})")
    top = per[per.breaches > 0].sort_values("breaches", ascending=False).head(10)
    print("  weekends with the most breaches (Saturday date: symbols):")
    for sat, r in top.iterrows():
        syms = d[(d.sat == sat) & d.any_breach]
        lab = ", ".join(f"{s}({'buy' if b else 'sell'} {g:+.1%})"
                        for s, b, g in zip(syms.symbol, syms.buy_breach, syms.gap))
        print(f"    {sat}: {int(r.breaches)} of {int(r.n)}  {lab}")
    return per


# ---------------------------------------------------------------- 3. run
main = simulate(wk, "p_tok_sat12")
per = report(main, "Saturday 12:00 ET (Friday close where no token)")

hr("STRC AND THE CLUSTERING CHECK WITHOUT IT")
st = main[main.symbol == "STRC"].sort_values("sat")
print("STRC (a Strategy preferred share; token history from 2026-05-06):")
print(st[["sat", "ref", "p_open", "p_fri", "p_mon", "gap", "sigma_mkt", "sigma_tok", "reserve_pct",
          "buy_breach", "sell_breach"]].tail(16).to_string(index=False))
stt = st[st.ref == "token"]
print(f"STRC token-priced weekends {len(stt)}: mean (token Sat noon / Friday close - 1) "
      f"{(stt.p_open / stt.p_fri - 1).mean():+.2%}; mean gap to Monday open {stt.gap.mean():+.2%}")
nx = main[main.symbol != "STRC"].assign(any_breach=lambda d: d.buy_breach | d.sell_breach)
x = int(nx.any_breach.sum()); lr, p = kupiec(x, 2 * len(nx))
print(f"pooled without STRC: {x} breaches / {2 * len(nx)} trade-sides = {x / (2 * len(nx)):.3%}; Kupiec p = {p:.4f}")
nt = nx[nx.ref == "token"]; x = int(nt.any_breach.sum()); lr, p = kupiec(x, 2 * len(nt))
print(f"token-priced without STRC: {x} / {2 * len(nt)} = {x / (2 * len(nt)):.3%}; Kupiec p = {p:.4f}")
lr, p, tc = christoffersen_ind([g.sort_values("sat").any_breach.values for _, g in nx.groupby("symbol")])
print(f"Christoffersen without STRC: LR {lr:.3f}, p = {p:.4f}; n11 = {tc['n11']}, n01 = {tc['n01']}")

alt = simulate(wk, "p_tok_sun20")
hr("ROBUSTNESS - trade moment Sunday 20:00 ET")
xb, xs = int(alt.buy_breach.sum()), int(alt.sell_breach.sum())
lr, p = kupiec(xb + xs, 2 * len(alt))
print(f"rows {len(alt)}; token-priced {(alt.ref == 'token').sum()}; breaches buy {xb}, sell {xs}; "
      f"rate {(xb + xs) / (2 * len(alt)):.3%}; Kupiec p = {p:.4f}")
ma = alt[alt.symbol == "META"]
print(f"META: breaches buy {int(ma.buy_breach.sum())}, sell {int(ma.sell_breach.sum())} of {len(ma)} weekends")

hr("ROBUSTNESS - sigma_market only (ignore the token side of the max)")
mk = wk.copy(); mk["sigma"] = mk.sigma_mkt
mko = simulate(mk, "p_tok_sat12")
xb, xs = int(mko.buy_breach.sum()), int(mko.sell_breach.sum())
lr, p = kupiec(xb + xs, 2 * len(mko))
print(f"breaches buy {xb}, sell {xs}; rate {(xb + xs) / (2 * len(mko)):.3%}; Kupiec p = {p:.4f}; "
      f"mean reserve {mko.reserve_pct.mean():.2%}")

hr("ROBUSTNESS - the production research_params.json sigma (fixed, has look-ahead)")
import json  # noqa: E402
prm = json.loads((API / "research_params.json").read_text(encoding="utf-8"))
fx = wk.copy(); fx["sigma"] = fx.symbol.map({k: float(v["used"]) for k, v in prm["sigma"].items()})
fxo = simulate(fx[fx.sigma.notna()], "p_tok_sat12")
xb, xs = int(fxo.buy_breach.sum()), int(fxo.sell_breach.sum())
lr, p = kupiec(xb + xs, 2 * len(fxo))
print(f"rows {len(fxo)}; breaches buy {xb}, sell {xs}; rate {(xb + xs) / (2 * len(fxo)):.3%}; "
      f"Kupiec p = {p:.4f}; META breaches {int(fxo[fxo.symbol == 'META'][['buy_breach', 'sell_breach']].values.sum())}")

# ---------------------------------------------------------------- 4. figure
by = main.groupby("symbol").agg(n=("sat", "size"), b=("buy_breach", "sum"), s=("sell_breach", "sum"))
by["rate"] = (by.b + by.s) / (2 * by.n)
by = by.sort_values("rate")
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [1, 1.4]})
y = np.arange(len(by))
a1.barh(y, by.b / (2 * by.n) * 100, color="#d1495b", label="buy breaches")
a1.barh(y, by.s / (2 * by.n) * 100, left=by.b / (2 * by.n) * 100, color="#2e86ab", label="sell breaches")
a1.axvline(TARGET * 100, color="black", ls="--", lw=1, label="1% target")
a1.set_yticks(y, [f"{s} (n={n})" for s, n in zip(by.index, by.n)], fontsize=8)
a1.set_xlabel("breach rate, % of trade-sides")
a1.set_title("Walk-forward breach rate by symbol")
a1.legend(fontsize=8, loc="lower right")
per = per.reset_index()
a2.bar(pd.to_datetime(per.sat), per.breaches, width=5, color="#444")
a2.plot(pd.to_datetime(per.sat), per.n * main.assign(a=main.buy_breach | main.sell_breach).a.mean(),
        color="#d1495b", lw=1, label="expected if independent")
a2.set_ylabel("symbol-weekends breached")
a2.set_title("Breaches per weekend (Sat 12:00 ET trade moment)")
a2.legend(fontsize=8)
fig.suptitle(f"Reserve backtest: {len(main)} symbol-weekends, sigma from prior data only, z = 3.7742",
             fontsize=11)
fig.tight_layout()
out = FIG / "reserve_backtest.png"
fig.savefig(out, dpi=150)
print(f"\nfigure: {out}")
