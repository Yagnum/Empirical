"""RQ5: what would a firm-price (on-chain hedged) product have cost?

Run from app/api:
    uv run --group research python ../../notebooks/analysis/rq5_hedge_cost.py

Recomputed from first principles; the stored broker_pnl / chain_pnl /
version_b_pnl columns are NOT used (the close leg was sized in USD, so its
token qty differs from the trade qty, and some rows have no gas).

Per market-mode trade with a usable open AND close leg (both have a price):
  notional     = qty * p_open
  share_pnl    = qty * (p_close - p_open)          customer sell
               = qty * (p_open - p_close)          customer buy
  token_pnl    = qty * (open_px - close_px)        sell-first hedge (customer sell)
               = qty * (close_px - open_px)        buy-first hedge  (customer buy)
  gross_hedged = share_pnl + token_pnl             "tracking error" before costs
  gas          = rent (one-time, refundable ATA rent) + fees (base + priority)
  net_hedged   = gross_hedged - gas (both legs)
  unhedged     = share_pnl                          firm price, no hedge
Gas missing on a leg (Jupiter 429 at build) is imputed: rent at that leg's
recorded ata_rent_lamports, fee at the median fee, SOL at the trade's other leg.
Spread: estimated from the live sampler's executable bid/ask ($1,000 quote) in
token_prices nearest the leg time (within 3 h): half-spread per leg.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\Yagnesh\Documents\Yagnum\app\api")
import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

FIG = r"C:\Users\Yagnesh\Documents\Yagnum\notebooks\figures\rq5_hedge_cost.png"
LAMPORTS = 1e9
DUST = 100.0
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)


def q(sql):
    return pd.read_sql(text(sql), db.engine())


def stats(s: pd.Series, label: str):
    s = s.dropna()
    return {"measure": label, "n": len(s), "mean": s.mean(), "median": s.median(), "std": s.std(),
            "worst": s.min(), "best": s.max(), "p05": s.quantile(.05), "%losing": (s < 0).mean() * 100}


def main():
    w = q("""select id, symbol, token_symbol, side, qty, p_open, p_close, state, source, created_at, settled_at
             from weekend_trades where settlement_mode='market' and state in ('settled','breached')""")
    h = q("""select trade_id, leg, side, qty, usd_amount, price, price_impact_pct, priority_fee_lamports,
                    base_fee_lamports, ata_exists, ata_rent_lamports, gas_lamports, sol_usd, gas_usd, error, at
             from hedge_legs""")
    for c in ["qty", "usd_amount", "price", "price_impact_pct", "priority_fee_lamports", "base_fee_lamports",
              "ata_rent_lamports", "gas_lamports", "sol_usd", "gas_usd"]:
        h[c] = h[c].astype(float)
    for c in ["qty", "p_open", "p_close"]:
        w[c] = w[c].astype(float)

    print(f"Market-mode settled/breached trades: {len(w)}; with any hedge leg: {w.id.isin(h.trade_id).sum()}")
    o = h[h.leg == "open"].set_index("trade_id")
    c = h[h.leg == "close"].set_index("trade_id")
    t = w.set_index("id").join(o.add_prefix("o_"), how="inner").join(c.add_prefix("c_"), how="inner")
    t = t[(t.o_price > 0) & (t.c_price > 0)].copy()  # a 429 at quote leaves price 0
    dropped = w[~w.id.isin(t.index)]
    print(f"Usable (both legs with a price > 0): {len(t)}; excluded: {len(dropped)} "
          f"(of which no hedge legs at all: {(~dropped.id.isin(h.trade_id)).sum()}, "
          f"open leg missing/failed: {(dropped.id.isin(h.trade_id)).sum()})")
    print("Excluded trade ids:", sorted(dropped.id.tolist()))

    # ---- gas, split rent from fees, with imputation
    fee_lam = pd.concat([h.base_fee_lamports + h.priority_fee_lamports]).dropna()
    med_fee = fee_lam.median()
    for L in ("o", "c"):
        miss = t[f"{L}_gas_usd"].isna()
        t[f"{L}_imputed"] = miss
        sol = t[f"{L}_sol_usd"].fillna(t["o_sol_usd" if L == "c" else "c_sol_usd"])
        fee = (t[f"{L}_base_fee_lamports"] + t[f"{L}_priority_fee_lamports"]).fillna(med_fee)
        rent = np.where(t[f"{L}_ata_exists"].fillna(False), 0.0, t[f"{L}_ata_rent_lamports"].fillna(0.0))
        t[f"{L}_fee_usd"] = fee * sol / LAMPORTS
        t[f"{L}_rent_usd"] = rent * sol / LAMPORTS
        t[f"{L}_gas_calc"] = t[f"{L}_fee_usd"] + t[f"{L}_rent_usd"]
    chk = (t.o_gas_calc - t.o_gas_usd).abs().max()
    print(f"Gas recompute check (open legs, max |calc-recorded|): ${chk:.6f}; legs imputed: "
          f"{int(t.o_imputed.sum() + t.c_imputed.sum())}")
    t["fees_usd"] = t.o_fee_usd + t.c_fee_usd
    t["rent_usd"] = t.o_rent_usd + t.c_rent_usd
    t["gas_usd"] = t.fees_usd + t.rent_usd

    # ---- P/L
    sgn = np.where(t.side == "sell", 1.0, -1.0)  # +1: Yagnum long the share after a customer sell
    t["notional"] = t.qty * t.p_open
    t["share_pnl"] = sgn * t.qty * (t.p_close - t.p_open)
    t["token_pnl"] = sgn * t.qty * (t.o_price - t.c_price)
    t["gross_hedged"] = t.share_pnl + t.token_pnl
    t["net_hedged"] = t.gross_hedged - t.gas_usd
    t["net_hedged_fees_only"] = t.gross_hedged - t.fees_usd
    t["unhedged"] = t.share_pnl
    for col in ["unhedged", "gross_hedged", "net_hedged", "net_hedged_fees_only", "token_pnl"]:
        t[col + "_pct"] = t[col] / t.notional * 100
    t["gas_pct"] = t.gas_usd / t.notional * 100
    t["fees_pct"] = t.fees_usd / t.notional * 100
    t["rent_pct"] = t.rent_usd / t.notional * 100
    # entry basis: open-leg executable price vs p_open (the customer's quote)
    t["entry_diff_pct"] = (t.o_price / t.p_open - 1) * 100
    # exit basis: close-leg token price vs Monday share fill
    t["exit_basis_pct"] = (t.c_price / t.p_close - 1) * 100
    t["hold_days"] = (t.settled_at - t.created_at).dt.total_seconds() / 86400
    t["close_lag_min"] = (t.c_at - t.settled_at).dt.total_seconds() / 60

    # ---- spread estimate from the live sampler
    tp = q("select sampled_at, symbol, bid_usd, ask_usd from token_prices where bid_usd is not null and ask_usd is not null")
    tp["hs"] = (tp.ask_usd.astype(float) - tp.bid_usd.astype(float)) / (tp.ask_usd.astype(float) + tp.bid_usd.astype(float))
    tp = tp[(tp.hs >= 0) & (tp.hs < 0.05)].sort_values("sampled_at")

    def half_spread(sym, at):
        g = tp[tp.symbol == sym]
        if g.empty:
            return np.nan
        i = (g.sampled_at - at).abs().idxmin()
        return g.loc[i, "hs"] if abs(g.loc[i, "sampled_at"] - at) <= pd.Timedelta(hours=3) else np.nan

    t["hs_open"] = [half_spread(s, a) for s, a in zip(t.token_symbol, t.o_at)]
    t["hs_close"] = [half_spread(s, a) for s, a in zip(t.token_symbol, t.c_at)]
    t["rt_spread_pct"] = (t.hs_open + t.hs_close) * 100
    t["rt_impact_pct"] = t.o_price_impact_pct + t.c_price_impact_pct  # Jupiter reports percent

    # ---- report: % measures on trades >= DUST notional (gas on a $0.77 trade is 41% of it)
    dust = t[t.notional < DUST]
    print(f"Dust trades (< ${DUST} notional) kept in $ totals, dropped from % stats: {len(dust)} ids {sorted(dust.index.tolist())}")
    t_all = t
    t = t[t.notional >= DUST].copy()
    sgn = np.where(t.side == "sell", 1.0, -1.0)
    print(f"\nTrades: {len(t)} across {t.symbol.nunique()} symbols; total notional ${t.notional.sum():,.0f}; "
          f"median ${t.notional.median():,.0f}; sides: {t.side.value_counts().to_dict()}; sources: {t.source.value_counts().to_dict()}")
    hd = t.hold_days
    print(f"Holding period trade->settlement (days): median {hd.median():.1f}, p90 {hd.quantile(.9):.1f}, "
          f"max {hd.max():.1f}; >4 days: {(hd > 4).sum()}")

    tab = pd.DataFrame([stats(t.unhedged_pct, "unhedged firm-price, % notional"),
                        stats(t.gross_hedged_pct, "hedged before gas (tracking err), %"),
                        stats(t.net_hedged_fees_only_pct, "hedged net of fees only (rent refunded), %"),
                        stats(t.net_hedged_pct, "hedged net of all gas, %"),
                        stats(t.unhedged, "unhedged, $"),
                        stats(t.gross_hedged, "hedged before gas, $"),
                        stats(t.net_hedged, "hedged net of all gas, $")])
    print("\n=== Per-trade P/L to Yagnum (positive = Yagnum gains) ===")
    print(tab.round(3).to_string(index=False))
    print("\nTotals ($):", {k: round(t[k].sum(), 2) for k in ["unhedged", "share_pnl", "token_pnl", "gross_hedged",
                                                                "fees_usd", "rent_usd", "gas_usd", "net_hedged"]})
    print(f"Totals as % of total notional: unhedged {t.unhedged.sum()/t.notional.sum()*100:+.3f}%, "
          f"gross hedged {t.gross_hedged.sum()/t.notional.sum()*100:+.3f}%, net hedged {t.net_hedged.sum()/t.notional.sum()*100:+.3f}%")
    vr = t.gross_hedged_pct.var() / t.unhedged_pct.var()
    print(f"Variance ratio hedged/unhedged (% notional): {vr:.4f}  -> variance reduction {100*(1-vr):.1f}%; "
          f"std {t.unhedged_pct.std():.3f}% -> {t.gross_hedged_pct.std():.3f}%")
    print(f"Dollar std: {t.unhedged.std():.2f} -> {t.net_hedged.std():.2f}")

    print("\n=== Cost components (% of notional, per trade) ===")
    comp = pd.DataFrame([stats(t.gas_pct, "gas total"), stats(t.rent_pct, "rent (refundable, one-time)"),
                         stats(t.fees_pct, "fees (base+priority)"), stats(t.rt_spread_pct, "round-trip spread est. ($1k quote)"),
                         stats(t.rt_impact_pct, "round-trip Jupiter price impact"),
                         stats(t.entry_diff_pct, "open-leg px vs p_open"), stats(t.exit_basis_pct, "close-leg token px vs p_close")])
    print(comp.drop(columns=["%losing"]).round(4).to_string(index=False))
    print(f"Gas $ per trade (both legs): mean {t.gas_usd.mean():.4f}, median {t.gas_usd.median():.4f}, max {t.gas_usd.max():.4f}; "
          f"rent share of gas {t.rent_usd.sum()/t.gas_usd.sum()*100:.1f}%; fees $ per trade mean {t.fees_usd.mean():.4f}, "
          f"median {t.fees_usd.median():.5f}, max {t.fees_usd.max():.4f}")
    legs = h.dropna(subset=["gas_usd"])
    legs_fee = (legs.base_fee_lamports + legs.priority_fee_lamports) * legs.sol_usd / LAMPORTS
    legs_rent = legs.ata_rent_lamports * legs.sol_usd / LAMPORTS
    print(f"All {len(legs)} legs with gas: gas mean ${legs.gas_usd.mean():.4f} (range {legs.gas_usd.min():.4f}..{legs.gas_usd.max():.4f}); "
          f"rent mean ${legs_rent.mean():.4f}; fee mean ${legs_fee.mean():.4f}, median ${legs_fee.median():.5f}; "
          f"priority fee >0 on {(legs.priority_fee_lamports>0).mean()*100:.0f}% of legs; rent lamports values {sorted(legs.ata_rent_lamports.unique().astype(int))}")

    # decomposition of tracking error: (share+token) ~= qty*sgn*[(p_close - c_px) - (p_open - o_px)]
    print(f"\nTracking error decomposition (mean % notional): entry term {(-sgn*(t.p_open-t.o_price)*t.qty/t.notional*100).mean():+.4f}, "
          f"exit basis term {(sgn*(t.p_close-t.c_price)*t.qty/t.notional*100).mean():+.4f}")
    print(f"|gross hedged| % notional: mean {t.gross_hedged_pct.abs().mean():.3f}, median {t.gross_hedged_pct.abs().median():.3f}, "
          f"p90 {t.gross_hedged_pct.abs().quantile(.9):.3f}")
    print(f"Close-leg quote time minus settlement time (min): median {t.close_lag_min.median():.2f}, max {t.close_lag_min.max():.2f}")

    # ---- break-even fee
    be_eq = -t.net_hedged_pct.mean() * 100
    be_w = -t.net_hedged.sum() / t.notional.sum() * 1e4
    be_eq_f = -t.net_hedged_fees_only_pct.mean() * 100
    be_w_f = -t.net_hedged_fees_only.sum() / t.notional.sum() * 1e4
    be_un = -t.unhedged.sum() / t.notional.sum() * 1e4
    se = t.net_hedged_pct.std() / np.sqrt(len(t)) * 100
    print(f"\nBreak-even fee, hedged (bps of notional): equal-weight {be_eq:+.1f} (±{1.96*se:.1f} 95% naive), "
          f"notional-weighted {be_w:+.1f}; with rent treated as refundable: {be_eq_f:+.1f} / {be_w_f:+.1f}")
    print(f"Break-even fee, UNHEDGED (notional-weighted, bps): {be_un:+.1f}; equal-weight {-t.unhedged_pct.mean()*100:+.1f}")
    # fee to cover a 99th pct loss
    print(f"Per-trade 5th pct / 1st pct of net hedged P/L, bps: {t.net_hedged_pct.quantile(.05)*100:.1f} / {t.net_hedged_pct.quantile(.01)*100:.1f}; "
          f"unhedged: {t.unhedged_pct.quantile(.05)*100:.1f} / {t.unhedged_pct.quantile(.01)*100:.1f}")

    # ---- adverse selection: did customers end up on the winning side?
    allw = w.copy()
    allw["notional"] = allw.qty * allw.p_open
    allw["cust_pnl_pct"] = -np.where(allw.side == "sell", 1, -1) * (allw.p_close / allw.p_open - 1) * 100
    ce = allw.created_at.dt.tz_convert("America/New_York").dt.tz_localize(None)
    allw["weekend"] = (ce - pd.Timedelta(days=2)).dt.to_period("W").astype(str)  # Fri..Thu buckets -> one weekend each
    from scipy import stats as st
    wins = (allw.cust_pnl_pct > 0).sum()
    n = len(allw)
    print(f"\n=== Adverse selection (all {n} market-mode settled trades, customer view) ===")
    print(f"Customer won on {wins}/{n} = {wins/n*100:.1f}% (binomial p vs 50%: {st.binomtest(wins, n).pvalue:.3f}); "
          f"mean customer P/L {allw.cust_pnl_pct.mean():+.3f}% of notional (t-test p {st.ttest_1samp(allw.cust_pnl_pct, 0).pvalue:.3f}); "
          f"notional-weighted {(allw.cust_pnl_pct*allw.notional).sum()/allw.notional.sum():+.3f}%")
    by = allw.groupby("weekend").agg(n=("id", "size"), mean_cust_pct=("cust_pnl_pct", "mean"),
                                     win_rate=("cust_pnl_pct", lambda s: (s > 0).mean()))
    print(by.round(3).to_string())
    pos = (by.mean_cust_pct > 0).sum()
    print(f"Weekend-level: customers net positive on {pos}/{len(by)} weekends (binomial p {st.binomtest(int(pos), len(by)).pvalue:.3f}); "
          f"t-test of weekend means p {st.ttest_1samp(by.mean_cust_pct, 0).pvalue:.3f}")
    print(allw.groupby("side").cust_pnl_pct.agg(["size", "mean", lambda s: (s > 0).mean()]).round(3).to_string())
    print(allw.groupby("source").cust_pnl_pct.agg(["size", "mean"]).round(3).to_string())

    # sensitivity: trades that settled promptly
    pr = t[t.hold_days <= 4]
    print(f"Median exit basis (token close px / p_close - 1): sells {t[t.side=='sell'].exit_basis_pct.median():+.3f}%, buys {t[t.side=='buy'].exit_basis_pct.median():+.3f}%")
    print(f"\nSensitivity, hold <= 4 days (n={len(pr)}): unhedged std {pr.unhedged_pct.std():.3f}% mean {pr.unhedged_pct.mean():+.3f}%; "
          f"hedged gross std {pr.gross_hedged_pct.std():.3f}% mean {pr.gross_hedged_pct.mean():+.3f}%; net mean {pr.net_hedged_pct.mean():+.3f}%")
    print(f"  net hedged median {pr.net_hedged_pct.median():+.3f}%, %losing {(pr.net_hedged_pct < 0).mean()*100:.0f}%, "
          f"break-even bps equal-weight {-pr.net_hedged_pct.mean()*100:+.1f} (95% naive +-{1.96*pr.net_hedged_pct.std()/np.sqrt(len(pr))*100:.1f}), "
          f"notional-weighted {-pr.net_hedged.sum()/pr.notional.sum()*1e4:+.1f}; variance reduction "
          f"{100*(1-pr.gross_hedged_pct.var()/pr.unhedged_pct.var()):.1f}%; unhedged %losing {(pr.unhedged_pct < 0).mean()*100:.0f}%, worst {pr.unhedged_pct.min():.2f}%")
    lg = t[t.hold_days > 4]
    print(f"  long holds (>4d, n={len(lg)}): gross hedged mean {lg.gross_hedged_pct.mean():+.3f}% std {lg.gross_hedged_pct.std():.3f}%, "
          f"unhedged std {lg.unhedged_pct.std():.3f}%")

    print("\nWorst hedged trades:")
    print(t.sort_values("net_hedged_pct")[["symbol", "side", "qty", "p_open", "o_price", "p_close", "c_price", "notional",
                                           "unhedged_pct", "gross_hedged_pct", "net_hedged_pct", "hold_days"]].head(6).round(3).to_string())

    # ---- figure
    surf, ink, ink2 = "#fcfcfb", "#0b0b0b", "#52514e"
    c1, c2 = "#eb6834", "#2a78d6"
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.8), facecolor=surf, gridspec_kw={"width_ratios": [1.1, 1]})
    for a in ax:
        a.set_facecolor(surf)
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            a.spines[sp].set_color("#c8c7c2")
        a.tick_params(colors=ink2, labelsize=9)
        a.grid(axis="y", color="#e6e5e0", lw=0.8)
    bins = np.arange(-17, 17.5, 0.5)
    ax[0].hist(t.unhedged_pct, bins=bins, color=c1, alpha=0.85, label=f"unhedged firm price (sd {t.unhedged_pct.std():.2f}%)",
               edgecolor=surf, linewidth=1)
    ax[0].hist(t.net_hedged_pct, bins=bins, color=c2, alpha=0.85, label=f"hedged on-chain, net of gas (sd {t.net_hedged_pct.std():.2f}%)",
               edgecolor=surf, linewidth=1)
    ax[0].set_xlabel("Yagnum P/L per trade, % of notional", color=ink2)
    ax[0].set_ylabel("trades", color=ink2)
    ax[0].set_title(f"Firm-price P/L per trade (n={len(t)})", color=ink, fontsize=11, loc="left")
    ax[0].legend(frameon=False, fontsize=8.5, labelcolor=ink2, loc="upper right")
    # zoom on hedged
    hb = np.arange(np.floor(t.net_hedged_pct.min() * 10) / 10, t.net_hedged_pct.max() + 0.2, 0.1)
    ax[1].hist(t.net_hedged_pct, bins=hb, color=c2, alpha=0.9, edgecolor=surf, linewidth=1)
    ax[1].axvline(t.net_hedged_pct.mean(), color=ink2, ls="--", lw=1.2)
    ax[1].text(t.net_hedged_pct.mean(), ax[1].get_ylim()[1] * 0.95, f" mean {t.net_hedged_pct.mean():+.3f}%",
               color=ink2, fontsize=8.5, va="top")
    ax[1].set_xlabel("hedged P/L net of gas, % of notional (zoomed)", color=ink2)
    ax[1].set_title("Hedged: what is left is tracking error, spread and gas", color=ink, fontsize=11, loc="left")
    fig.tight_layout()
    fig.savefig(FIG, dpi=150, facecolor=surf)
    print("\nfigure:", FIG)
    return t


if __name__ == "__main__":
    main()
