"""Work plan item 4: decompose the realised weekend gap into components.

Run from app/api:
    uv run --group research python ../../notebooks/analysis/gap_decomposition.py

For each market-settled weekend trade, in log terms (exact identity):

    ln(p_close / p_open) = spread + basis + share_weekend + settle_lag

    spread         ln(mid / p_open)        executable quote vs token mid at trade time
    basis          ln(s_pre / mid)         token mid vs the share's last print before the trade
                                           (minus the token's premium over the share)
    share_weekend  ln(s_next / s_pre)      share: last print before the trade -> next regular open
    settle_lag     ln(p_close / s_next)    share: next open -> the actual fill (settlement ran late)

share_weekend + settle_lag is the "share's own move" (s_pre -> p_close) of the brief.
Sign convention: components of the SIGNED gap (p_close - p_open). Multiplying by
dir (+1 buy, -1 sell) gives the trader-adverse contribution.

Outputs: printed tables, notebooks/figures/gap_decomposition.png, and
notebooks/analysis/out/decomposition_trades.csv.
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

import weekend_data as wd

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "..", "figures", "gap_decomposition.png")
OUT = os.path.join(HERE, "out")
COMP = ["spread", "basis", "share_weekend", "settle_lag"]
LABEL = {
    "spread": "Execution spread (quote vs mid)",
    "basis": "Token-share basis at execution",
    "share_weekend": "Share weekend move (last print to next open)",
    "settle_lag": "Settlement timing (next open to actual fill: intraday + skipped sessions)",
}
# Validated default categorical palette, fixed order (dataviz skill palette.md)
COLOR = {"spread": "#2a78d6", "basis": "#eb6834", "share_weekend": "#1baf7a", "settle_lag": "#eda100"}
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)


def build() -> pd.DataFrame:
    d = wd.load()
    d["total"] = np.log(d.p_close / d.p_open)
    d["spread"] = np.log(d.mid / d.p_open)
    d["basis"] = np.log(d.s_pre / d.mid)
    d["share_weekend"] = np.log(d.s_next / d.s_pre)
    d["settle_lag"] = np.log(d.p_close / d.s_next)
    d["share_move"] = np.log(d.p_close / d.s_pre)
    d["resid"] = d.total - d[["spread", "basis", "share_move"]].sum(axis=1)
    # token -> next open: what the engine would face if it always settled promptly
    d["token_to_open"] = d.spread + d.basis + d.share_weekend
    d["half_spread_quote"] = np.nan  # filled below from the bracketing quote, cross-check only
    return d


def share_table(x: pd.DataFrame, comps: list[str], total: str = "total") -> pd.DataFrame:
    """mean, std, rms of each component; variance share var(c)/var(T); covariance
    share cov(c,T)/var(T) (sums to 1); second-moment share E[cT]/E[T^2] (sums to 1,
    and is the right one for a reserve, which cares about distance from zero)."""
    T = x[total]
    rows = {}
    for c in comps + [total]:
        v = x[c]
        rows[c] = dict(
            mean_pct=100 * v.mean(),
            std_pct=100 * v.std(),
            rms_pct=100 * np.sqrt((v**2).mean()),
            mean_abs_pct=100 * v.abs().mean(),
            var_share=v.var() / T.var(),
            cov_share=np.cov(v, T)[0, 1] / T.var(),
            m2_share=(v * T).mean() / (T**2).mean(),
        )
    return pd.DataFrame(rows).T.round(3)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    d = build()
    print(f"Weekend market-settled trades: {len(d)} (5 weekday test trades by the user excluded)")
    print(f"Weekends: {d.wknd.nunique()}, (symbol, weekend) clusters: {d.groupby(['symbol','wknd']).ngroups}")
    print(f"Token mid from bid/ask: {d.mid_has_ba.sum()} of {len(d)}; usd_price fallback: {(~d.mid_has_ba).sum()} (ids {list(d.loc[~d.mid_has_ba,'id'])})")
    print(f"Bracketing token samples around the trade: median {d.mid_bracket_min.median():.0f} min apart (mid is interpolated)")
    print(f"s_pre = last Alpaca print known before the trade; its timestamp is Friday 15:59-16:56 ET for every trade")
    miss = d.s_next.isna()
    print(f"No next-open sample (lag split impossible): {miss.sum()} trades, ids {list(d.loc[miss,'id'])}")
    print(f"Identity residual max |total - (spread+basis+share_move)| = {d.resid.abs().max():.2e}")
    print("Settlement lag (regular sessions between next open and fill):")
    print(d.lag_sessions.describe().round(2).to_string())
    print(f"  settled at the first session: {(d.lag_sessions==0).sum()} / {d.lag_sessions.notna().sum()}")

    full = d.dropna(subset=["s_next"]).copy()
    print("\n=== Pooled, trade level (n=%d), 4-way, log %% of p_open ===" % len(full))
    print(share_table(full, COMP).to_string())
    print("\n=== Pooled, trade level, 3-way as briefed (spread, basis, share_move) n=%d ===" % len(d))
    print(share_table(d, ["spread", "basis", "share_move"]).to_string())

    cl = full.groupby(["symbol", "wknd"])[COMP + ["total", "token_to_open"]].mean().reset_index()
    print("\n=== Pooled, (symbol, weekend) cluster means (n=%d) ===" % len(cl))
    print(share_table(cl, COMP).to_string())

    # trader-adverse direction: mean contribution against the trader
    adv = full[COMP + ["total"]].mul(full.dir, axis=0)
    print("\n=== Mean trader-ADVERSE contribution, %% (positive = against trader) ===")
    print((100 * adv.mean()).round(3).to_string())

    print("\n=== Per symbol: mean |component| %%, and RMS of total, token_to_open, share_weekend vs stored sigma ===")
    g = full.groupby("symbol")
    per = pd.DataFrame(
        {
            "trades": g.size(),
            "clusters": g.wknd.nunique(),
            **{f"|{c}|": 100 * g[c].apply(lambda s: s.abs().mean()) for c in COMP},
            "rms_total": 100 * g.total.apply(lambda s: np.sqrt((s**2).mean())),
            "rms_token_to_open": 100 * g.token_to_open.apply(lambda s: np.sqrt((s**2).mean())),
            "rms_share_wknd": 100 * g.share_weekend.apply(lambda s: np.sqrt((s**2).mean())),
            "sigma_stored": 100 * g.sigma.mean(),
        }
    ).round(2)
    per = per.sort_values("rms_total", ascending=False)
    print(per.to_string())

    print("\n=== Per symbol mean / std of each component (%%) ===")
    ms = full.groupby("symbol")[COMP].agg(["mean", "std"]).mul(100).round(2)
    print(ms.to_string())

    print("\n=== META in detail ===")
    m = d[d.symbol == "META"][["id", "side", "wknd", "lag_sessions", "breached", "reserve_pct"] + COMP + ["total"]].copy()
    for c in COMP + ["total", "reserve_pct"]:
        m[c] = (100 * m[c]).round(2)
    print(m.to_string(index=False))
    mf = full[full.symbol == "META"]
    print("META second-moment shares:")
    print(share_table(mf, COMP)[["rms_pct", "m2_share", "cov_share"]].to_string())

    d.to_csv(os.path.join(OUT, "decomposition_trades.csv"), index=False)

    # ---------- figure ----------
    order = per.index.tolist()
    fig, (ax, ax2) = plt.subplots(
        1, 2, figsize=(14, 6.2), gridspec_kw={"width_ratios": [4.2, 1]}, facecolor="#fcfcfb"
    )
    x = np.arange(len(order))
    wbar = 0.2
    for k, c in enumerate(COMP):
        vals = [per.loc[s, f"|{c}|"] for s in order]
        ax.bar(x + (k - 1.5) * wbar, vals, width=wbar * 0.9, color=COLOR[c], label=LABEL[c], zorder=3)
    ax.plot(x, [per.loc[s, "sigma_stored"] * wd.Z_POOLED for s in order], ls="none", marker="_",
            ms=22, mew=2, color="#0b0b0b", label="Reserve held (stored sigma x z), % of notional", zorder=4)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{s}\n{per.loc[s,'trades']}t/{per.loc[s,'clusters']}w" for s in order], fontsize=8.5)
    ax.set_ylabel("Mean |contribution|, % of p_open (log)", color="#52514e")
    ax.set_title("Where the weekend gap comes from, per symbol (t = trades, w = weekends)", loc="left", fontsize=11.5)
    ax.grid(axis="y", color="#e4e3df", zorder=0)
    for sp in ["top", "right"]:
        ax.spines[sp].set_visible(False)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    ax.set_facecolor("#fcfcfb")

    sh = share_table(full, COMP)["m2_share"]
    bottom_pos, bottom_neg = 0.0, 0.0
    for c in COMP:
        v = sh[c] * 100
        if v >= 0:
            ax2.bar(0, v, bottom=bottom_pos, color=COLOR[c], width=0.55, edgecolor="#fcfcfb", lw=2, zorder=3)
            if v >= 5:
                ax2.text(0.33, bottom_pos + v / 2, f"{v:.0f}%", va="center", fontsize=9, color="#0b0b0b")
            bottom_pos += v
        else:
            ax2.bar(0, v, bottom=bottom_neg, color=COLOR[c], width=0.55, edgecolor="#fcfcfb", lw=2, zorder=3)
            ax2.text(0.33, bottom_neg + v / 2, f"{v:.0f}%", va="center", fontsize=9, color="#0b0b0b")
            bottom_neg += v
    small = ", ".join(f"{c.replace('_', ' ')} {sh[c]*100:.0f}%" for c in COMP if abs(sh[c]) * 100 < 5)
    ax2.text(-0.45, -6, small, fontsize=8.5, color="#52514e", va="top")
    ax2.axhline(0, color="#52514e", lw=1)
    ax2.set_xlim(-0.5, 0.8)
    ax2.set_xticks([])
    ax2.set_title("Share of E[gap²], pooled\n(n=%d trades)" % len(full), fontsize=10.5, loc="left")
    ax2.set_ylabel("% of second moment", color="#52514e")
    for sp in ["top", "right", "bottom"]:
        ax2.spines[sp].set_visible(False)
    ax2.set_facecolor("#fcfcfb")
    fig.tight_layout()
    fig.savefig(FIG, dpi=150, facecolor=fig.get_facecolor())
    print("\nfigure:", os.path.abspath(FIG))


if __name__ == "__main__":
    main()
