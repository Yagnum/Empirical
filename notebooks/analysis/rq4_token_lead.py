"""RQ4: does the token lead the share into the reopening, or merely mirror it?

Run from app/api:
    uv run --group research python ../../notebooks/analysis/rq4_token_lead.py

DATA
  Share  : market_bars (Alpaca IEX). 1Day bars give F (previous session's
           regular close) and O (reopening session's regular open; checked
           equal to the 09:30 one-minute bar's open). 1Min bars give the few
           premarket prints IEX has, used as a benchmark predictor.
  Token  : token_candles (GeckoTerminal hourly, deepest USDC pool).
  Both tables were backfilled once and end on 2026-08-31. With EXTEND_LIVE
  the script also fetches, read-only (HTTP GET, nothing written to the
  database), the same sources for 2026-08-25 .. today, so the live-sampler
  weekends (Labor Day, 09-14 .. 10-12) are included. The fetch is cached in
  the OS temp directory. If the fetch fails the script runs on the DB alone.

  token_prices (the live 5-minute sampler) is NOT used for the token series:
  after 2026-09-04 it sampled only 4-8 times a day, so Monday 08:00 and 09:25
  are rarely covered, and its first market_open sample on a Monday is often
  hours after 09:30. It is used for one cross-check (candle close vs live mid).

DEFINITIONS (per symbol, per weekend = trading day d whose previous trading
day p is >= 3 calendar days earlier)
  F  = regular close on p,  O = regular open on d,  y = ln(O/F)
  T(t) = close of the last complete hourly token candle ending <= t
         (stale if older than MAX_STALE_H; then missing)
  x(t) = ln(T(t)/F)                               (as specified)
  xa(t)= ln(T(t)/T(p 16:00))                      (basis-adjusted: removes the
                                                    token-vs-share level offset)
  Checkpoints (ET): Fri 20:00, Sat 12:00, Sun 20:00 (eve of d), d 04:00,
  d 08:00, d 09:25. Hourly candles mean "09:25" is in practice the 08:00-09:00
  candle's close, i.e. the token price at ~09:00.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

API = r"C:\Users\Yagnesh\Documents\Yagnum\app\api"
sys.path.insert(0, API)
import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ET = ZoneInfo("America/New_York")
FIG = r"C:\Users\Yagnesh\Documents\Yagnum\notebooks\figures\rq4_token_lead.png"
EXTEND_LIVE = True
EXT_START = "2026-08-25"
CACHE = os.path.join(tempfile.gettempdir(), "yagnum_rq4_cache")
MAX_STALE_H = 4.0
TINY = 0.002  # |ln(O/F)| below this: excluded from the ratio, kept in regressions
EXCLUDE = {"SPCXx"}  # no listed underlying share

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def q(sql: str) -> pd.DataFrame:
    return pd.read_sql(text(sql), db.engine())


# ---------------------------------------------------------------- load
def load_db():
    daily = q("select symbol, bucket_start, open, close from market_bars where timeframe='1Day'")
    mins = q("select symbol, bucket_start, open, close, volume from market_bars where timeframe='1Min'")
    cand = q("select symbol, pool, bucket_start, close from token_candles where timeframe='hour'")
    return daily, mins, cand


def fetch_extension(symbols_share, pools):
    """Read-only GETs to Alpaca and GeckoTerminal for EXT_START .. now. Cached."""
    os.makedirs(CACHE, exist_ok=True)
    pd_ = os.path.join(CACHE, "daily.pkl")
    pm_ = os.path.join(CACHE, "mins.pkl")
    pc_ = os.path.join(CACHE, "cand.pkl")
    if all(os.path.exists(p) for p in (pd_, pm_, pc_)):
        return pd.read_pickle(pd_), pd.read_pickle(pm_), pd.read_pickle(pc_)
    import backfill  # app module; only its pure fetch helpers are used

    now = dt.datetime.now(dt.timezone.utc)
    drows, mrows, crows = [], [], []
    for s in symbols_share:
        bars = backfill.fetch_bars(s, {"timeframe": "1Day", "start": EXT_START, "limit": 10000,
                                       "adjustment": "split", "feed": "iex", "sort": "asc"})
        for b in bars:
            drows.append({"symbol": s, "bucket_start": pd.Timestamp(b["t"]), "open": float(b["o"]), "close": float(b["c"])})
    ddf = pd.DataFrame(drows)
    days = sorted({t.tz_convert(ET).date() for t in ddf.bucket_start})
    reopen = [d for p, d in zip(days, days[1:]) if (d - p).days >= 3]
    for s in symbols_share:
        for d in reopen:
            a = dt.datetime.combine(d, dt.time(4, 0), tzinfo=ET).astimezone(dt.timezone.utc)
            b_ = dt.datetime.combine(d, dt.time(9, 31), tzinfo=ET).astimezone(dt.timezone.utc)
            bars = backfill.fetch_bars(s, {"timeframe": "1Min", "start": a.isoformat().replace("+00:00", "Z"),
                                           "end": b_.isoformat().replace("+00:00", "Z"), "limit": 10000,
                                           "feed": "iex", "sort": "asc"})
            for b in bars:
                mrows.append({"symbol": s, "bucket_start": pd.Timestamp(b["t"]), "open": float(b["o"]),
                              "close": float(b["c"]), "volume": float(b["v"])})
    cutoff = dt.datetime.fromisoformat(EXT_START).replace(tzinfo=dt.timezone.utc)
    for tok, pool in pools.items():
        for row in backfill.fetch_candles(pool, "hour", cutoff):
            crows.append({"symbol": tok, "pool": pool,
                          "bucket_start": pd.Timestamp(int(row[0]), unit="s", tz="UTC"), "close": float(row[4])})
    mdf, cdf = pd.DataFrame(mrows), pd.DataFrame(crows)
    ddf.to_pickle(pd_); mdf.to_pickle(pm_); cdf.to_pickle(pc_)
    _ = now
    return ddf, mdf, cdf


def combine(a, b, key):
    out = pd.concat([a, b], ignore_index=True)
    for c in ("open", "close", "volume"):
        if c in out:
            out[c] = out[c].astype(float)
    out["bucket_start"] = pd.to_datetime(out.bucket_start, utc=True)
    return out.drop_duplicates(subset=key, keep="first").sort_values(key).reset_index(drop=True)


# ---------------------------------------------------------------- stats
def ols(x, y, groups):
    """y = a + b x. Returns slope, intercept, R2, n, weekend-clustered SE of slope."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean()))
    meat = np.zeros((2, 2))
    G = pd.unique(groups)
    for g in G:
        m = groups == g
        s = X[m].T @ e[m]
        meat += np.outer(s, s)
    k = len(G)
    adj = k / (k - 1) * (n - 1) / (n - 2) if k > 1 else 1.0
    V = adj * XtX_inv @ meat @ XtX_inv
    return beta[1], beta[0], r2, n, k, float(np.sqrt(V[1, 1])), e


def token_at(cand_sym: pd.DataFrame, t_utc: pd.Timestamp):
    """Close of last complete hourly candle ending <= t; NaN if stale."""
    ends = cand_sym["end"].values
    i = np.searchsorted(ends, np.datetime64(t_utc.tz_convert("UTC").tz_localize(None)), side="right") - 1
    if i < 0:
        return np.nan, np.nan
    stale_h = (t_utc.tz_convert("UTC").tz_localize(None) - pd.Timestamp(ends[i])).total_seconds() / 3600
    if stale_h > MAX_STALE_H:
        return np.nan, stale_h
    return float(cand_sym["close"].values[i]), stale_h


def share_premarket_at(mins_sym: pd.DataFrame, d: dt.date, t_et: dt.datetime):
    if mins_sym is None or mins_sym.empty:
        return np.nan
    a = pd.Timestamp(dt.datetime.combine(d, dt.time(4, 0), tzinfo=ET))
    m = mins_sym[(mins_sym.et >= a) & (mins_sym.et_end <= pd.Timestamp(t_et))]
    m = m[m.et < pd.Timestamp(dt.datetime.combine(d, dt.time(9, 30), tzinfo=ET))]
    return float(m.close.iloc[-1]) if len(m) else np.nan


# ---------------------------------------------------------------- main
def main():
    daily, mins, cand = load_db()
    source_note = "DB only (backfill to 2026-08-31)"
    if EXTEND_LIVE:
        try:
            pools = cand.groupby("symbol").pool.agg(lambda s: s.mode().iloc[0]).to_dict()
            pools = {k: v for k, v in pools.items() if k not in EXCLUDE}
            shares = sorted({k[:-1] for k in pools})
            d2, m2, c2 = fetch_extension(shares, pools)
            daily = combine(daily, d2, ["symbol", "bucket_start"])
            mins = combine(mins, m2, ["symbol", "bucket_start"])
            cand = combine(cand, c2, ["symbol", "bucket_start"])
            source_note = f"DB backfill + read-only live extension from {EXT_START}"
        except Exception as exc:  # network etc.
            print("live extension failed, DB only:", exc)
    daily["date"] = daily.bucket_start.dt.tz_convert(ET).dt.date
    cand = cand[~cand.symbol.isin(EXCLUDE)].copy()
    cand["end"] = (cand.bucket_start + pd.Timedelta(hours=1)).dt.tz_convert("UTC").dt.tz_localize(None)
    cand = cand.sort_values(["symbol", "end"])
    mins["et"] = mins.bucket_start.dt.tz_convert(ET)
    mins["et_end"] = mins.et + pd.Timedelta(minutes=1)
    print("Data source:", source_note)

    cal = sorted(daily[daily.symbol == "SPY"].date.unique())
    weekends = [(p, d) for p, d in zip(cal, cal[1:]) if (d - p).days >= 3]
    first_tok = cand.bucket_start.min().tz_convert(ET).date()
    weekends = [(p, d) for p, d in weekends if d > first_tok]

    dkey = daily.set_index(["symbol", "date"])
    cand_by = {s: g.reset_index(drop=True) for s, g in cand.groupby("symbol")}
    mins_by = {s: g.reset_index(drop=True) for s, g in mins.groupby("symbol")}

    cps = [("Fri 20:00", None), ("Sat 12:00", None), ("Sun 20:00", None),
           ("Mon 04:00", dt.time(4, 0)), ("Mon 08:00", dt.time(8, 0)), ("Mon 09:25", dt.time(9, 25))]
    rows = []
    for p, d in weekends:
        sat = p + dt.timedelta(days=(5 - p.weekday()) % 7 or 7)
        times = {
            "Fri 16:00": dt.datetime.combine(p, dt.time(16, 0), tzinfo=ET),
            "Fri 20:00": dt.datetime.combine(p, dt.time(20, 0), tzinfo=ET),
            "Sat 12:00": dt.datetime.combine(sat, dt.time(12, 0), tzinfo=ET),
            "Sun 20:00": dt.datetime.combine(d - dt.timedelta(days=1), dt.time(20, 0), tzinfo=ET),
        }
        for name, tm in cps:
            if tm:
                times[name] = dt.datetime.combine(d, tm, tzinfo=ET)
        for tok, cs in cand_by.items():
            sh = tok[:-1]
            if (sh, p) not in dkey.index or (sh, d) not in dkey.index:
                continue
            F = float(dkey.loc[(sh, p), "close"]); O = float(dkey.loc[(sh, d), "open"])
            rec = {"weekend": d, "prev": p, "symbol": sh, "F": F, "O": O, "y": np.log(O / F),
                   "holiday": (d - p).days > 3}
            for name, t_et in times.items():
                T, st = token_at(cs, pd.Timestamp(t_et))
                rec[f"T|{name}"] = T; rec[f"stale|{name}"] = st
            for name in ("Mon 08:00", "Mon 09:25"):
                S = share_premarket_at(mins_by.get(sh), d, times[name])
                rec[f"S|{name}"] = S
            S9 = share_premarket_at(mins_by.get(sh), d, dt.datetime.combine(d, dt.time(9, 0), tzinfo=ET))
            rec["S|Mon 09:00"] = S9
            rows.append(rec)
    df = pd.DataFrame(rows)
    names = [c for c, _ in cps]
    for nme in names:
        df[f"x|{nme}"] = np.log(df[f"T|{nme}"] / df.F)
        df[f"xa|{nme}"] = np.log(df[f"T|{nme}"] / df["T|Fri 16:00"])
    df["basis_fri"] = np.log(df["T|Fri 16:00"] / df.F)

    print(f"\nWeekends: {df.weekend.nunique()}  ({df.weekend.min()} .. {df.weekend.max()}); "
          f"symbols: {df.symbol.nunique()}; pairs: {len(df)}")
    print("Holiday-extended weekends:", sorted({str(w) for w in df[df.holiday].weekend}))
    print(f"Gap y=ln(O/F): mean {df.y.mean():+.4%}, sd {df.y.std():.4%}, "
          f"median |y| {df.y.abs().median():.4%}, |y|<{TINY:.1%}: {(df.y.abs() < TINY).mean():.1%}")
    print(f"Friday-close basis ln(T_fri16/F): mean {df.basis_fri.mean():+.4%}, sd {df.basis_fri.std():.4%}")

    # ---- per-checkpoint pooled results
    out = []
    for nme in names:
        sub = df.dropna(subset=[f"x|{nme}", "y"])
        g = sub.weekend.astype(str).values
        b, a, r2, n, k, se, _ = ols(sub[f"x|{nme}"], sub.y, g)
        sa = sub.dropna(subset=[f"xa|{nme}"])
        ba, aa, r2a, _, _, sea, _ = ols(sa[f"xa|{nme}"], sa.y, sa.weekend.astype(str).values)
        resid_raw = sub.y - sub[f"x|{nme}"]  # ln(O/T): risk left if you reprice at T
        big = sub[sub.y.abs() >= TINY]
        ratio = big[f"x|{nme}"] / big.y
        # weekend-level: average across symbols
        wk = sub.groupby("weekend")[[f"x|{nme}", "y"]].mean()
        bw, aw, r2w, nw, _, _, _ = ols(wk[f"x|{nme}"], wk.y, np.arange(len(wk)))
        # within-weekend (demeaned): idiosyncratic part only
        dm = sub[[f"x|{nme}", "y"]] - sub.groupby("weekend")[[f"x|{nme}", "y"]].transform("mean")
        bd, _, r2d, _, _, sed, _ = ols(dm[f"x|{nme}"], dm.y, g)
        out.append({
            "checkpoint": nme, "n": n, "weekends": k, "slope": b, "slope_se_cl": se, "intercept": a, "R2": r2,
            "R2_basis_adj": r2a, "slope_basis_adj": ba,
            "R2_weekend_mean": r2w, "slope_wk_mean": bw, "R2_within": r2d, "slope_within": bd,
            "ratio_median": ratio.median(), "ratio_IQR": f"{ratio.quantile(.25):.2f}..{ratio.quantile(.75):.2f}",
            "n_ratio": len(ratio), "sign_hit": (np.sign(big[f"x|{nme}"]) == np.sign(big.y)).mean(),
            "sd_y": sub.y.std(), "sd_ln_O_over_T": resid_raw.std(), "rmse_fit": np.sqrt(np.mean((sub.y - a - b * sub[f'x|{nme}'])**2)),
            "p99_abs_y": sub.y.abs().quantile(.99), "p99_abs_ln_O_over_T": resid_raw.abs().quantile(.99),
            "median_stale_h": sub[f"stale|{nme}"].median(),
        })
    res = pd.DataFrame(out)
    show = res.copy()
    for c in ["sd_y", "sd_ln_O_over_T", "rmse_fit", "p99_abs_y", "p99_abs_ln_O_over_T"]:
        show[c] = (show[c] * 100).round(3)
    print("\n=== Pooled, per checkpoint (std/percentile columns in %) ===")
    print(show.round(3).to_string(index=False))

    # ---- same, restricted to a common sample present at every checkpoint
    cols = [f"x|{n}" for n in names]
    common = df.dropna(subset=cols)
    print(f"\nCommon sample (token price present at every checkpoint): n={len(common)}, weekends={common.weekend.nunique()}")
    for nme in names:
        b, a, r2, n, k, se, _ = ols(common[f"x|{nme}"], common.y, common.weekend.astype(str).values)
        print(f"  {nme}: slope {b:.3f} (cl.se {se:.3f})  R2 {r2:.3f}  sd ln(O/T) {(common.y-common[f'x|{nme}']).std():.3%}")

    # ---- token vs the share's own premarket prints (who leads?)
    print("\n=== Token vs share premarket prints (same pairs) ===")
    for tk, sk in [("Mon 08:00", "S|Mon 08:00"), ("Mon 09:25", "S|Mon 09:00"), ("Mon 09:25", "S|Mon 09:25")]:
        sub = df.dropna(subset=[f"x|{tk}", sk]).copy()
        if len(sub) < 10:
            print(f"  {tk} vs {sk}: too few pairs ({len(sub)})"); continue
        sub["xs"] = np.log(sub[sk] / sub.F)
        g = sub.weekend.astype(str).values
        bt, _, r2t, n, k, _, _ = ols(sub[f"x|{tk}"], sub.y, g)
        bs, _, r2s, _, _, _, _ = ols(sub.xs, sub.y, g)
        X = np.column_stack([np.ones(len(sub)), sub[f"x|{tk}"], sub.xs])
        beta, *_ = np.linalg.lstsq(X, sub.y.values, rcond=None)
        e = sub.y.values - X @ beta
        r2b = 1 - e @ e / ((sub.y - sub.y.mean()) ** 2).sum()
        print(f"  token@{tk} vs share-premarket {sk}: n={n} weekends={k}  R2 token {r2t:.3f} (b {bt:.2f}) | "
              f"R2 share-pm {r2s:.3f} (b {bs:.2f}) | both {r2b:.3f} (b_tok {beta[1]:.2f}, b_share {beta[2]:.2f}) | "
              f"sd ln(O/T) {(sub.y-sub[f'x|{tk}']).std():.3%} vs sd ln(O/S) {(sub.y-sub.xs).std():.3%}")

    # ---- leave-one-weekend-out stability at Mon 08:00
    nme = "Mon 08:00"
    sub = df.dropna(subset=[f"x|{nme}"])
    lo = []
    for w in sub.weekend.unique():
        s2 = sub[sub.weekend != w]
        b, _, r2, *_ = ols(s2[f"x|{nme}"], s2.y, s2.weekend.astype(str).values)
        lo.append((w, b, r2))
    lo = pd.DataFrame(lo, columns=["dropped", "slope", "R2"])
    print(f"\nLeave-one-weekend-out at {nme}: slope {lo.slope.min():.3f}..{lo.slope.max():.3f}, R2 {lo.R2.min():.3f}..{lo.R2.max():.3f}")

    # ---- per-weekend table at Mon 08:00
    pw = sub.groupby("weekend").apply(lambda g: pd.Series({
        "n": len(g), "mean_gap_%": g.y.mean() * 100, "mean_x08_%": g[f"x|{nme}"].mean() * 100,
        "corr": g[[f"x|{nme}", "y"]].corr().iloc[0, 1] if len(g) > 2 else np.nan,
        "sd_ln(O/T08)_%": (g.y - g[f"x|{nme}"]).std() * 100}), include_groups=False)
    print("\nPer weekend at Mon 08:00:")
    print(pw.round(3).to_string())

    # ---- per-symbol residual risk at Mon 08:00 vs unconditional
    ps = sub.groupby("symbol").apply(lambda g: pd.Series({
        "n": len(g), "sd_gap_%": g.y.std() * 100, "sd_ln(O/T_sat)_%": (g.y - g["x|Sat 12:00"]).std() * 100,
        "sd_ln(O/T08)_%": (g.y - g[f"x|{nme}"]).std() * 100, "R2": np.corrcoef(g[f"x|{nme}"], g.y)[0, 1] ** 2}),
        include_groups=False)
    print("\nPer symbol (Mon 08:00):")
    print(ps.round(3).sort_values("sd_gap_%", ascending=False).to_string())

    # ---- cross-check: hourly candle close vs live sampler mid (where both exist)
    try:
        tp = q("select sampled_at, symbol, usd_price, bid_usd, ask_usd from token_prices where bid_usd is not null")
        tp["mid"] = (tp.bid_usd.astype(float) + tp.ask_usd.astype(float)) / 2
        tp["t"] = tp.sampled_at.dt.tz_convert("UTC").dt.tz_localize(None)
        diffs = []
        for s, g in tp.groupby("symbol"):
            cs = cand_by.get(s)
            if cs is None:
                continue
            idx = np.searchsorted(cs["end"].values, g.t.values, side="right") - 1
            ok = idx >= 0
            ends = cs["end"].values[idx[ok]]
            age = (g.t.values[ok] - ends) / np.timedelta64(1, "h")
            ok2 = age <= 1
            diffs.extend(np.log(cs["close"].values[idx[ok]][ok2] / g.mid.values[ok][ok2]))
        diffs = np.array(diffs)
        print(f"\nCross-check candle close vs live executable mid (<=1h apart): n={len(diffs)}, "
              f"median {np.median(diffs):+.3%}, MAD-type spread (p75-p25) {np.subtract(*np.percentile(diffs,[75,25])):.3%}")
    except Exception as exc:
        print("cross-check skipped:", exc)

    # ---- figure
    surf, ink, ink2 = "#fcfcfb", "#0b0b0b", "#52514e"
    c1, c2, c3 = "#2a78d6", "#eb6834", "#1baf7a"
    xs = np.arange(len(names))
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.8), facecolor=surf)
    for a in ax:
        a.set_facecolor(surf)
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            a.spines[sp].set_color("#c8c7c2")
        a.tick_params(colors=ink2, labelsize=9)
        a.grid(axis="y", color="#e6e5e0", lw=0.8)
        a.set_xticks(xs, [n.replace("Mon", "Reopen") for n in names], rotation=20)
    ax[0].plot(xs, res.R2, "-o", color=c1, lw=2, ms=7, label="pooled pairs (as specified)")
    ax[0].plot(xs, res.R2_basis_adj, "-s", color=c3, lw=2, ms=7, label="pooled, Friday basis removed")
    ax[0].plot(xs, res.R2_weekend_mean, "-^", color=c2, lw=2, ms=7, label="weekend means (cross-symbol avg)")
    ax[0].set_ylim(0, 1)
    ax[0].set_ylabel("R² of ln(O/F) on ln(T(t)/F)", color=ink2)
    ax[0].set_title("How much of the reopening gap the token has priced", color=ink, fontsize=11, loc="left")
    ax[0].legend(frameon=False, fontsize=8.5, labelcolor=ink2, loc="lower right")
    ax[0].text(0, -0.30, f"n≈{int(res.n.median())} symbol-weekends, {int(res.weekends.max())} weekends; "
               "'09:25' = token at ~09:00 (hourly candles)", transform=ax[0].transAxes, fontsize=8, color=ink2)
    ax[1].plot(xs, res.sd_ln_O_over_T * 100, "-o", color=c1, lw=2, ms=7, label="sd ln(O / T(t)): risk left after repricing at t")
    ax[1].axhline(res.sd_y.iloc[-1] * 100, color=ink2, lw=1.2, ls="--")
    ax[1].text(len(names) - 1, res.sd_y.iloc[-1] * 100, "sd ln(O/F): no repricing", color=ink2, fontsize=8.5,
               ha="right", va="bottom")
    ax[1].set_ylim(0, max(res.sd_y.max(), res.sd_ln_O_over_T.max()) * 100 * 1.25)
    ax[1].set_ylabel("standard deviation, % ", color=ink2)
    ax[1].set_title("Residual gap risk if the reserve is resized at t", color=ink, fontsize=11, loc="left")
    ax[1].legend(frameon=False, fontsize=8.5, labelcolor=ink2, loc="lower left")
    fig.tight_layout()
    fig.savefig(FIG, dpi=150, facecolor=surf)
    print("\nfigure:", FIG)
    return df, res


if __name__ == "__main__":
    main()
