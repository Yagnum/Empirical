"""Work plan item 2: re-estimate sigma on the realised quantity, test out of sample.

Run from app/api:
    uv run --group research python ../../notebooks/analysis/sigma_realised.py

Realised quantity: g = (p_close - p_open) / p_open per market-settled weekend
trade (token executable quote -> actual Alpaca fill). A counterfactual
g_next = (s_next - p_open) / p_open (token quote -> share price at the next
regular open) is evaluated alongside, to separate the reserve model from late
settlement.

Rigor:
  * sigma is estimated on (symbol, weekend) CLUSTER means, not trades: trades in
    the same symbol and weekend share the same news and usually the same fill.
  * Out of sample by weekend: expanding window (train on weekends 1..k, test on
    k+1, k = 1..5) and leave-one-weekend-out (LOWO, not time-ordered).
  * z is held at the pooled 3.7742 for every method so that only sigma differs.

Methods (sigma per trade):
  stored        sigma in the trade row (research_params.json, 2026-08-31)
  realised      RMS of the symbol's training cluster gaps; stored if < 2 clusters
  shrunk        (n*rms_sym^2 + K*(lam*stored)^2)/(n+K), K = 3 pseudo-weekends, where
                lam = RMS(cluster gap / stored sigma) over all training clusters
  max           max(stored, realised)
  pooled        RMS of all training cluster gaps, same for every symbol
  stored_x_lam  stored * lam (one pooled recalibration factor, keeps relative scale)

Outputs: printed tables, notebooks/figures/sigma_methods_coverage.png,
notebooks/analysis/out/sigma_methods_*.csv
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

import weekend_data as wd

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "..", "figures", "sigma_methods_coverage.png")
OUT = os.path.join(HERE, "out")
Z = wd.Z_POOLED
K_SHRINK = 3.0
METHODS = ["stored", "realised", "shrunk", "max", "pooled", "stored_x_lam"]
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)


def rms(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.sqrt(np.mean(x**2))) if len(x) else np.nan


def fit(train: pd.DataFrame, gcol: str) -> dict:
    cl = wd.clusters(train, gcol)
    lam = rms(cl.gap / cl.sigma)
    per = cl.groupby("symbol").gap.agg(rms_sym=rms, n="size")
    return dict(lam=lam, pooled=rms(cl.gap), per=per)


def sigmas(test: pd.DataFrame, f: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=test.index)
    st = test.sigma
    per = f["per"].reindex(test.symbol)
    n = per.n.fillna(0).to_numpy()
    r = per.rms_sym.to_numpy()
    out["stored"] = st
    out["realised"] = np.where(n >= 2, r, st)
    prior = f["lam"] * st.to_numpy()
    out["shrunk"] = np.sqrt((n * np.nan_to_num(r) ** 2 + K_SHRINK * prior**2) / (n + K_SHRINK))
    out["max"] = np.maximum(st, out["realised"])
    out["pooled"] = f["pooled"]
    out["stored_x_lam"] = prior
    return out


def evaluate(d: pd.DataFrame, sig: pd.DataFrame, gcol: str, acol: str) -> pd.DataFrame:
    rows = []
    for m in METHODS:
        res = sig[m] * Z  # reserve as a fraction of notional
        absg = d[gcol].abs()
        exceed2 = absg > res
        breach = d[acol] > res
        x = d.assign(exceed=exceed2.astype(float), res=res)
        clx = x.groupby(["symbol", "wknd"]).agg(gap=(gcol, "mean"), res=("res", "mean"))
        cl_exceed = clx.gap.abs() > clx.res
        k, n = int(exceed2.sum()), len(d)
        rows.append(
            dict(
                method=m,
                n_trades=n,
                n_clusters=len(clx),
                cov_2sided=1 - exceed2.mean(),
                exceed=k,
                p_binom=stats.binom.sf(k - 1, n, 0.01) if k else 1.0,
                breaches=int(breach.sum()),
                breach_rate=breach.mean(),
                cl_cov=1 - cl_exceed.mean(),
                cl_exceed=int(cl_exceed.sum()),
                mean_util=(absg / res).mean(),
                max_util=(absg / res).max(),
                mean_reserve_pct=100 * res.mean(),
            )
        )
    return pd.DataFrame(rows).set_index("method")


def run(d: pd.DataFrame, gcol: str, acol: str, label: str) -> dict:
    d = d.dropna(subset=[gcol]).copy()
    weeks = sorted(d.wknd.unique())
    res = {}
    # in sample: fit and test on everything
    res["in_sample"] = evaluate(d, sigmas(d, fit(d, gcol)), gcol, acol)
    # expanding window
    parts, sig_parts = [], []
    for k in range(1, len(weeks)):
        tr, te = d[d.wknd.isin(weeks[:k])], d[d.wknd == weeks[k]]
        parts.append(te)
        sig_parts.append(sigmas(te, fit(tr, gcol)))
    te_all, sig_all = pd.concat(parts), pd.concat(sig_parts)
    res["expanding"] = evaluate(te_all, sig_all, gcol, acol)
    res["expanding_sigmas"] = te_all.join(sig_all, rsuffix="_m")
    # leave one weekend out
    parts, sig_parts = [], []
    for w in weeks:
        tr, te = d[d.wknd != w], d[d.wknd == w]
        parts.append(te)
        sig_parts.append(sigmas(te, fit(tr, gcol)))
    res["lowo"] = evaluate(pd.concat(parts), pd.concat(sig_parts), gcol, acol)
    for k in ["in_sample", "expanding", "lowo"]:
        print(f"\n=== {label}: {k} ===")
        t = res[k].copy()
        for c in ["cov_2sided", "breach_rate", "cl_cov", "mean_util", "max_util"]:
            t[c] = (100 * t[c]).round(1)
        t["p_binom"] = t.p_binom.round(4)
        t["mean_reserve_pct"] = t.mean_reserve_pct.round(2)
        print(t.to_string())
    return res


def z_check(d: pd.DataFrame) -> None:
    print("\n=== Does z = 3.7742 hold?  |gap| / sigma_stored ===")
    dec = pd.read_csv(os.path.join(OUT, "decomposition_trades.csv")) if os.path.exists(
        os.path.join(OUT, "decomposition_trades.csv")) else None
    qs = {
        "as-settled g (token quote -> actual fill)": d.g,
        "next-open g (token quote -> next open)": d.g_next,
        "share only (Fri last print -> next open)": (d.s_next - d.s_pre) / d.s_pre,
    }
    for name, g in qs.items():
        ok = g.notna()
        r = (g[ok].abs() / d.sigma[ok]).to_numpy()
        cl = d[ok].assign(r=g[ok]).groupby(["symbol", "wknd"]).agg(g=("r", "mean"), s=("sigma", "mean"))
        rc = (cl.g.abs() / cl.s).to_numpy()
        print(
            f"{name:44s} trades n={len(r):3d}: z=3.7742 is the {stats.percentileofscore(r, Z, kind='weak'):.1f}th pct, "
            f"empirical 99th={np.quantile(r, .99):.2f}, 95th={np.quantile(r, .95):.2f}, RMS(|g|/sigma)={rms(r):.2f}, max={r.max():.2f} | "
            f"clusters n={len(rc)}: {stats.percentileofscore(rc, Z, kind='weak'):.1f}th pct, RMS={rms(rc):.2f}, n>z={int((rc > Z).sum())}"
        )
    print("(If sigma were the right scale, RMS(|g|/sigma) would be ~1 and z the 99th pct.)")


def figure(results: dict) -> None:
    labels = {
        "stored": "Stored (2y share gaps)",
        "realised": "Realised, per symbol",
        "shrunk": "Realised, shrunk to prior",
        "max": "max(stored, realised)",
        "pooled": "Realised, pooled",
        "stored_x_lam": "Stored x pooled factor",
    }
    qcol = {"as-settled": "#2a78d6", "next-open": "#eb6834"}
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.6), sharey=True, facecolor="#fcfcfb")
    y = np.arange(len(METHODS))[::-1]
    h = 0.36
    panels = [
        ("cov_2sided", "Out-of-sample coverage, % of trades\n(|gap| within reserve)", 100),
        ("mean_reserve_pct", "Mean reserve, % of notional\n(capital the trader posts)", 1),
        ("mean_util", "Mean utilisation, %\n(|true-up| / reserve)", 100),
    ]
    for ax, (col, title, mult) in zip(axes, panels):
        for j, (q, res) in enumerate(results.items()):
            t = res["expanding"]
            v = [t.loc[m, col] * mult for m in METHODS]
            ax.barh(y + (0.5 - j) * h, v, height=h * 0.9, color=qcol[q], label=f"{q} gap", zorder=3)
            for yy, vv in zip(y + (0.5 - j) * h, v):
                ax.text(vv, yy, f" {vv:.1f}", va="center", fontsize=8, color="#0b0b0b")
        ax.set_title(title, loc="left", fontsize=10.5)
        ax.grid(axis="x", color="#e4e3df", zorder=0)
        for sp in ["top", "right"]:
            ax.spines[sp].set_visible(False)
        ax.set_facecolor("#fcfcfb")
    axes[0].axvline(99, color="#0b0b0b", lw=1, ls="--", zorder=4)
    axes[0].text(99, y[0] + 0.62, "99% target ", ha="right", fontsize=8, color="#52514e")
    lo = min(r["expanding"].cov_2sided.min() for r in results.values()) * 100
    axes[0].set_xlim(max(0, lo - 6), 102.5)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([labels[m] for m in METHODS])
    n1 = results["as-settled"]["expanding"].n_trades.iloc[0]
    nc = results["as-settled"]["expanding"].n_clusters.iloc[0]
    hnd, lab = axes[0].get_legend_handles_labels()
    fig.legend(hnd, lab, frameon=False, fontsize=9, loc="lower left", ncol=2, bbox_to_anchor=(0.01, 0.0))
    fig.text(0.99, 0.012, "Each 'stored' miss is the same META weekend (2026-09-19): 4 trades, 1 event. "
             "Differences of one or two trades are not statistically meaningful.",
             ha="right", fontsize=8.5, color="#52514e")
    fig.suptitle(
        f"Sigma methods, expanding-window out of sample (test = weekends 2-6: {n1} trades, {nc} symbol-weekends), z = 3.7742 for all",
        x=0.01, ha="left", fontsize=11.5,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(FIG, dpi=150, facecolor=fig.get_facecolor())
    print("\nfigure:", os.path.abspath(FIG))


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    d = wd.load()
    cl = wd.clusters(d)
    print(f"Weekend market-settled trades: {len(d)} | weekends: {d.wknd.nunique()} | (symbol, weekend) clusters: {len(cl)}")
    print("Trades per weekend:", d.groupby("wknd").size().to_dict())
    print(f"Breaches as stored: {int(d.breached.sum())} (ids {list(d.loc[d.breached,'id'])})")
    print("Clusters per symbol:", cl.groupby("symbol").size().to_dict())
    z_check(d)
    results = {
        "as-settled": run(d, "g", "adverse", "AS-SETTLED gap (token quote -> actual fill)"),
        "next-open": run(d, "g_next", "adverse_next", "NEXT-OPEN gap (token quote -> next regular open)"),
    }
    # what the expanding fit says per symbol at the end (all 6 weekends) -- the proposal
    f = fit(d, "g")
    fn = fit(d.dropna(subset=["g_next"]), "g_next")
    print(f"\nFull-sample fit: lam(as-settled) = {f['lam']:.2f}, lam(next-open) = {fn['lam']:.2f}; "
          f"pooled RMS as-settled {100*f['pooled']:.2f}%, next-open {100*fn['pooled']:.2f}%")
    tab = pd.concat(
        [d.groupby("symbol").sigma.mean().rename("stored"),
         f["per"].rms_sym.rename("rms_settled"), fn["per"].rms_sym.rename("rms_next_open"),
         f["per"].n.rename("clusters")], axis=1)
    tab["ratio_next_open/stored"] = tab.rms_next_open / tab.stored
    print((tab * [100, 100, 100, 1, 1]).round(2).sort_values("ratio_next_open/stored", ascending=False).to_string())
    for q, r in results.items():
        for k in ["in_sample", "expanding", "lowo"]:
            r[k].to_csv(os.path.join(OUT, f"sigma_methods_{q}_{k}.csv"))
    # which trades break under each method out of sample (as-settled)
    es = results["as-settled"]["expanding_sigmas"]
    print("\nExpanding-window exceedances (as-settled), by method:")
    for m in METHODS:
        bad = es[es.g.abs() > es[m] * Z]
        print(f"  {m:13s}: " + ", ".join(f"{r.symbol}#{r.id}(lag {int(r.lag_sessions) if r.lag_sessions==r.lag_sessions else '?'})" for r in bad.itertuples()))
    figure(results)


if __name__ == "__main__":
    main()
