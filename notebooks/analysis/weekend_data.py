"""Shared loader for the capstone gap analyses (work plan items 2 and 4).

Read-only: SELECT statements only. Imported by sigma_realised.py and
gap_decomposition.py, which live in the same folder.

One row per market-settled weekend trade, with:
  g         signed relative gap (p_close - p_open) / p_open
  adverse   trader-adverse gap -true_up / (qty * p_open), positive = against trader
  wknd      the Saturday date of the weekend the trade was opened in
  mid       token mid (bid+ask)/2 interpolated to created_at between the two
            bracketing token_prices samples (usd_price where bid/ask is null; flagged)
  s_pre     share's last Alpaca print known at trade time (Friday's last print on a weekend)
  s_next    share price at the first market_open sample after created_at (the next regular open)
  lag_sessions  regular sessions that passed between that open and the actual fill
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"C:\Users\Yagnesh\Documents\Yagnum\app\api")

import numpy as np
import pandas as pd
from sqlalchemy import text

import db  # noqa: E402

ET = "America/New_York"
Z_POOLED = 3.7742

TRADES_SQL = """
select id, source, side, qty, symbol, token_symbol, p_open, p_close, sigma, z,
       reserve, true_up, state, created_at, settled_at
from weekend_trades
where settlement_mode = 'market' and state in ('settled', 'breached') and reserve > 0
order by created_at
"""


def _weekend_key(ts_et: pd.Timestamp, session_dates: set):
    """Saturday date of the weekend a trade belongs to, or None for a weekday trade.
    Weekend = Friday 16:00 ET to the next session's 09:30 ET open; a Monday that
    is a market holiday (Labor Day 2026-09-07) counts as part of the weekend."""
    d = ts_et.date()
    if ts_et.weekday() == 0 and d not in session_dates:
        return d - pd.Timedelta(days=2)
    wd = ts_et.weekday()
    if wd == 4 and ts_et.hour >= 16:
        return d + pd.Timedelta(days=1)
    if wd == 5:
        return d
    if wd == 6:
        return d - pd.Timedelta(days=1)
    if wd == 0 and (ts_et.hour, ts_et.minute) < (9, 30):
        return d - pd.Timedelta(days=2)
    return None


def load(weekend_only: bool = True) -> pd.DataFrame:
    eng = db.engine()
    df = pd.read_sql(text(TRADES_SQL), eng)
    for c in ["qty", "p_open", "p_close", "sigma", "z", "reserve", "true_up"]:
        df[c] = df[c].astype(float)
    df["notional"] = df.qty * df.p_open
    df["g"] = (df.p_close - df.p_open) / df.p_open
    df["adverse"] = -df.true_up / df.notional
    df["reserve_pct"] = df.reserve / df.notional  # stored sigma*z, after cent rounding
    df["util"] = df.true_up.abs() / df.reserve
    df["breached"] = (df.reserve + df.true_up) < 0
    syms = tuple(sorted(df.symbol.unique()))
    tp = pd.read_sql(
        text(
            "select sampled_at, underlying, usd_price, bid_usd, ask_usd, market_price, "
            "market_trade_at, market_open from token_prices where underlying = any(:syms) "
            "order by sampled_at"
        ),
        eng,
        params={"syms": list(syms)},
    )
    for c in ["usd_price", "bid_usd", "ask_usd", "market_price"]:
        tp[c] = tp[c].astype(float)
    tp["market_open"] = tp.market_open.fillna(False).astype(bool)
    tp["has_ba"] = tp.bid_usd.notna() & tp.ask_usd.notna()
    tp["mid"] = np.where(tp.has_ba, (tp.bid_usd + tp.ask_usd) / 2, tp.usd_price)
    session_dates = sorted(set(tp.loc[tp.market_open, "sampled_at"].dt.tz_convert(ET).dt.date))
    c_et = df.created_at.dt.tz_convert(ET)
    df["wknd"] = [_weekend_key(t, set(session_dates)) for t in c_et]
    df["is_weekend"] = df.wknd.notna()

    rows = []
    for r in df.itertuples():
        t = tp[tp.underlying == r.symbol]
        # (i) token mid at trade time: linear interpolation between the samples
        # bracketing created_at (weekend sampling is sparser than 5 minutes)
        prev = t[t.sampled_at <= r.created_at].tail(1)
        nxt = t[t.sampled_at > r.created_at].head(1)
        if len(prev) and len(nxt):
            t0, t1 = prev.sampled_at.iloc[0], nxt.sampled_at.iloc[0]
            w = (r.created_at - t0) / (t1 - t0)
            mid = (1 - w) * prev.mid.iloc[0] + w * nxt.mid.iloc[0]
            has_ba = bool(prev.has_ba.iloc[0] and nxt.has_ba.iloc[0])
            bracket = (t1 - t0).total_seconds() / 60
        else:
            near = t.loc[(t.sampled_at - r.created_at).abs().idxmin()]
            mid, has_ba, bracket = near.mid, bool(near.has_ba), np.nan
        # (ii) last share print known before the trade
        before = t[t.sampled_at <= r.created_at]
        s_pre = before.market_price.iloc[-1] if len(before) else np.nan
        s_pre_at = before.market_trade_at.iloc[-1] if len(before) else pd.NaT
        # next regular-session price: first market_open sample after the trade
        after = t[
            (t.sampled_at > r.created_at)
            & t.market_open
            & (t.sampled_at < r.created_at + pd.Timedelta(days=5))  # guard: symbol dropped from sampler
        ]
        s_next = after.market_price.iloc[0] if len(after) else np.nan
        next_date = after.sampled_at.iloc[0].tz_convert(ET).date() if len(after) else None
        settle_date = r.settled_at.tz_convert(ET).date()
        lag = (
            sum(1 for d in session_dates if next_date < d <= settle_date)
            if next_date is not None
            else np.nan
        )
        rows.append(
            dict(
                id=r.id,
                mid=mid,
                mid_has_ba=has_ba,
                mid_bracket_min=bracket,
                s_pre=s_pre,
                s_pre_at=s_pre_at,
                s_next=s_next,
                next_session=next_date,
                lag_sessions=lag,
            )
        )
    out = df.merge(pd.DataFrame(rows), on="id")
    # adverse direction multiplier: buy hurt by a rise, sell hurt by a fall
    out["dir"] = np.where(out.side == "buy", 1.0, -1.0)
    out["g_next"] = (out.s_next - out.p_open) / out.p_open  # gap had it settled at the next open
    out["adverse_next"] = out.dir * out.g_next
    if weekend_only:
        out = out[out.is_weekend].copy()
    out["wknd"] = pd.to_datetime(out.wknd)
    return out.reset_index(drop=True)


def clusters(df: pd.DataFrame, gap_col: str = "g") -> pd.DataFrame:
    """Collapse to one observation per (symbol, weekend): mean signed gap,
    the stored sigma, and the trade count. Trades in a cluster share the same
    weekend news and mostly the same fill, so they are not independent."""
    return (
        df.groupby(["symbol", "wknd"])
        .agg(gap=(gap_col, "mean"), sigma=("sigma", "mean"), n=("id", "size"))
        .reset_index()
    )
