"""How do the LLM trader personas behave? Decision mix, weekend vs weekday
appetite, sensitivity to the shown reserve and spread, disposition effect,
herding, refusals and errors.

Run from app/api:
    uv run --group research python ../../notebooks/analysis/persona_behaviour.py

READ-ONLY: SELECT statements against sim_users, sim_decisions and
weekend_trades. Writes one PNG to notebooks/figures/ and prints every number.

THESE ARE NOT PEOPLE. Every "trader" here is the same language model
(openai/gpt-oss-120b on Groq) given a different persona paragraph (app/api/sim.py)
and a JSON briefing. What follows describes how that model follows those
instructions; it is not evidence about how humans trade on weekends. Quoted
text is model output.
"""

from __future__ import annotations

import json
import re
import sys
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

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 120)
TRADABLE_WEEKDAY = {"regular", "premarket", "afterhours"}


def hr(title: str) -> None:
    print("\n" + "=" * 78 + "\n" + title + "\n" + "=" * 78)


eng = db.engine()
users = pd.read_sql(text("select id, slug, watchlist, model from sim_users order by id"), eng)
d = pd.read_sql(text("""
select d.id, d.sim_user_id, u.slug, d.at as ts, d.session, d.model, d.briefing, d.reasoning,
       d.action, d.symbol, d.qty, d.reason, d.confidence, d.outcome, d.ref, d.error,
       d.latency_ms, d.reasoning_tokens
from sim_decisions d join sim_users u on u.id = d.sim_user_id
order by d.at"""), eng)
d["confidence"] = d.confidence.astype(float)
d["intent"] = d.action.isin(["buy", "sell"])  # the model asked to trade (executed or refused)
d["brief"] = d.briefing.map(json.loads)
PERSONAS = list(users.slug)

hr("0. WHAT THIS IS")
print(f"decisions: {len(d)}, from {d.slug.nunique()} personas, {d.ts.min():%Y-%m-%d %H:%M} to "
      f"{d.ts.max():%Y-%m-%d %H:%M} UTC ({(d.ts.max() - d.ts.min()).days} days)")
print(f"models recorded: {d.model.value_counts().to_dict()}")
print(f"decisions with a stored reasoning trace: {d.reasoning.notna().sum()}; "
      f"median reasoning tokens {d.reasoning_tokens.median():.0f}; median latency {d.latency_ms.median():.0f} ms")
print("All eight 'traders' are one LLM with eight persona prompts. Nothing below is human behaviour.")

# ---------------------------------------------------------------- 1. mix
hr("1. DECISION MIX PER PERSONA")
mix = pd.crosstab(d.slug, d.outcome).reindex(PERSONAS)
mix["total"] = mix.sum(axis=1)
print(mix.to_string())
print("\nby session (all personas):")
print(pd.crosstab(d.session, d.outcome, margins=True).to_string())
print("\nintended action (buy/sell/hold, refused and errored included where parsed):")
print(pd.crosstab(d.slug, d.action.fillna("(no parse)")).reindex(PERSONAS).to_string())

hr("1b. WEEKEND VS WEEKDAY: HOW OFTEN DOES THE PERSONA ASK TO TRADE?")
print("Rate = buy/sell intents / decisions with a parsed answer. Weekday = regular + premarket +")
print("afterhours (overnight excluded: the rules force 'hold'). Fisher exact test per persona.")
p = d[d.action.notna()]
rows = []
for s in PERSONAS + ["ALL"]:
    g = p if s == "ALL" else p[p.slug == s]
    w = g[g.session == "weekend"]; k = g[g.session.isin(TRADABLE_WEEKDAY)]
    a, b, c, e = int(w.intent.sum()), int((~w.intent).sum()), int(k.intent.sum()), int((~k.intent).sum())
    odds, pv = stats.fisher_exact([[a, b], [c, e]])
    rows.append(dict(persona=s, wknd_decisions=a + b, wknd_trade_rate=a / max(a + b, 1),
                     wkday_decisions=c + e, wkday_trade_rate=c / max(c + e, 1), odds_ratio=odds, fisher_p=pv))
wv = pd.DataFrame(rows).set_index("persona")
print(wv.round(3).to_string())
hours = d.groupby(d.ts.dt.floor("h")).session.first().value_counts()
print(f"\ndecision ticks by session (hours with >= 1 decision): {hours.to_dict()}")
wt = pd.read_sql(text("select id, source, side, symbol, qty, p_open, p_close, reserve, true_up, state, "
                      "created_at from weekend_trades where source = 'sim'"), eng)
print(f"weekend_trades with source='sim': {len(wt)}; states {wt.state.value_counts().to_dict()}")

# ---------------------------------------------------------------- 2. reserve and spread
hr("2. DO THEY REACT TO THE SHOWN RESERVE % OR SPREAD?")


def ctx_frame(row) -> pd.DataFrame:
    w = pd.DataFrame(row.brief.get("watchlist", []))
    if w.empty:
        return w
    for c in ["spread_pct", "reserve_pct", "change_since_market_pct", "change_24h_pct"]:
        w[c] = pd.to_numeric(w.get(c), errors="coerce")
    return w


# (a) within-decision choice: the chosen symbol's rank among the watchlist
wk = d[(d.session == "weekend") & d.intent].copy()
ranks = {"reserve_pct": [], "spread_pct": [], "abs_move": []}
for r in wk.itertuples():
    w = ctx_frame(r)
    if w.empty or r.symbol not in set(w.symbol):
        continue
    w["abs_move"] = w.change_since_market_pct.abs()
    for col in ranks:
        x = w[[col, "symbol"]].dropna()
        if len(x) < 2 or r.symbol not in set(x.symbol):
            continue
        rk = x[col].rank(pct=False)
        pos = (rk[x.symbol == r.symbol].iloc[0] - 1) / (len(x) - 1)  # 0 = lowest in the list
        ranks[col].append(pos)
print("(a) Weekend trade intents: where does the chosen symbol sit within the persona's watchlist?")
print("    rank 0 = lowest value shown, 1 = highest; random choice averages 0.5 (Wilcoxon vs 0.5).")
for col, v in ranks.items():
    v = np.array(v)
    if len(v) < 10:
        print(f"    {col}: n = {len(v)}, too few"); continue
    w = stats.wilcoxon(v - 0.5)
    print(f"    {col:12s} n = {len(v):3d}  mean rank {v.mean():.3f}  share in lower half {np.mean(v < 0.5):.2f}, "
          f"upper half {np.mean(v > 0.5):.2f}  Wilcoxon p = {w.pvalue:.4f}")

# (b) trade vs hold, against the average reserve / spread shown that tick
rows = []
for r in d[(d.session == "weekend") & d.action.notna()].itertuples():
    w = ctx_frame(r)
    if w.empty:
        continue
    rows.append(dict(slug=r.slug, intent=r.intent, mean_spread=w.spread_pct.mean(),
                     min_spread=w.spread_pct.min(), mean_reserve=w.reserve_pct.mean(),
                     max_abs_move=w.change_since_market_pct.abs().max()))
th = pd.DataFrame(rows)
print("\n(b) Weekend decisions: what was on screen when they traded vs when they held? (Mann-Whitney)")
for col in ["mean_spread", "min_spread", "mean_reserve", "max_abs_move"]:
    a, b = th.loc[th.intent, col].dropna(), th.loc[~th.intent, col].dropna()
    mw = stats.mannwhitneyu(a, b)
    print(f"    {col:13s} traded median {a.median():.3f} (n={len(a)})  held median {b.median():.3f} (n={len(b)})  p = {mw.pvalue:.4f}")
# within persona, so the watchlist mix does not drive it: logistic slope via point-biserial per persona
print("    per persona (Spearman of intent vs mean spread / max |move since Friday|):")
for s, g in th.groupby("slug"):
    if g.intent.nunique() < 2 or len(g) < 10:
        print(f"      {s:7s} n = {len(g)}: too few or no variation"); continue
    r1 = stats.spearmanr(g.intent, g.mean_spread, nan_policy="omit")
    r2 = stats.spearmanr(g.intent, g.max_abs_move, nan_policy="omit")
    r3 = stats.spearmanr(g.intent, g.mean_reserve, nan_policy="omit")
    print(f"      {s:7s} n = {len(g):3d}  trade rate {g.intent.mean():.2f}  rho(spread) {r1.statistic:+.2f} "
          f"(p {r1.pvalue:.3f})  rho(reserve) {r3.statistic:+.2f} (p {r3.pvalue:.3f})  "
          f"rho(|move|) {r2.statistic:+.2f} (p {r2.pvalue:.3f})")
print("    note: the pooled reserve gap is a persona effect (high-reserve watchlists belong to the")
print("    personas told to trade often); the per-persona rows are the fair comparison. With ~26-41")
print("    weekend decisions each and ~20 tests, one or two p < 0.05 are expected by chance.")

# (c) what they say
txt = d.reason.fillna("").str.lower()
for word in ["spread", "reserve", "monday", "friday", "weekend"]:
    m = txt.str.contains(word)
    print(f"    reasons mentioning '{word}': {m.sum()} of {txt.ne('').sum()} "
          f"({m.sum() / txt.ne('').sum():.1%}); by persona {d[m].slug.value_counts().to_dict()}")
lena = d[(d.slug == "lena") & (d.session == "weekend") & d.action.notna()]
print(f"    Lena (told to trade only on tight spreads and small reserves): weekend decisions {len(lena)}, "
      f"trade intents {int(lena.intent.sum())}, holds mentioning spread/reserve "
      f"{int((~lena.intent & lena.reason.fillna('').str.lower().str.contains('spread|reserve')).sum())}")

# ---------------------------------------------------------------- 3. disposition
hr("3. DISPOSITION EFFECT (Odean 1998: PGR vs PLR)")
print("Each decision where the persona held positions and could sell is a sell opportunity.")
print("A position is a winner if unrealized_pl_pct > 0, a loser if < 0 (exact zero dropped).")
print("Selling it = realised; holding it = paper. PGR = RG/(RG+PG), PLR = RL/(RL+PL).")
cnt = {"RG": 0, "PG": 0, "RL": 0, "PL": 0}
per_p = {s: dict(RG=0, PG=0, RL=0, PL=0) for s in PERSONAS}
sold_pl = []
for r in d[(d.session != "overnight") & d.action.notna()].itertuples():
    pos = r.brief.get("positions", [])
    sold = r.symbol if r.action == "sell" else None
    for q in pos:
        try:
            pl = float(q.get("unrealized_pl_pct"))
            avail = float(q.get("available_qty") or 0)
        except (TypeError, ValueError):
            continue
        if avail <= 0 or pl == 0:
            continue
        win = pl > 0
        is_sold = q.get("symbol") == sold
        key = ("R" if is_sold else "P") + ("G" if win else "L")
        cnt[key] += 1; per_p[r.slug][key] += 1
        if is_sold:
            sold_pl.append(pl)
pgr = cnt["RG"] / (cnt["RG"] + cnt["PG"]); plr = cnt["RL"] / (cnt["RL"] + cnt["PL"])
se = np.sqrt(pgr * (1 - pgr) / (cnt["RG"] + cnt["PG"]) + plr * (1 - plr) / (cnt["RL"] + cnt["PL"]))
zst = (pgr - plr) / se
print(f"counts {cnt}")
print(f"PGR {pgr:.4f}  PLR {plr:.4f}  PGR/PLR {pgr / plr:.2f}  difference {pgr - plr:+.4f}  z = {zst:.2f}, "
      f"p (two-sided) = {2 * stats.norm.sf(abs(zst)):.4f}")
print(f"sells with a known P&L: {len(sold_pl)}; median unrealized P&L at sale {np.median(sold_pl):+.2%}"
      if sold_pl else "no sells with a known P&L")
print("per persona:")
for s, c in per_p.items():
    g = c["RG"] + c["PG"]; l = c["RL"] + c["PL"]
    if c["RG"] + c["RL"] < 3:
        print(f"  {s:7s} {c}  fewer than 3 sells with known P&L: not tested"); continue
    a, b = c["RG"] / g if g else np.nan, c["RL"] / l if l else np.nan
    print(f"  {s:7s} {c}  PGR {a:.3f}  PLR {b:.3f}")

# ---------------------------------------------------------------- 4. herding
hr("4. HERDING: SAME SYMBOL, SAME HOUR, DIFFERENT PERSONAS")
it = d[d.intent].copy()
it["hour"] = it.ts.dt.floor("h")


def pairs(df: pd.DataFrame, same_side: bool = False) -> int:
    n = 0
    for _, g in df.groupby("hour"):
        if len(g) < 2:
            continue
        rec = list(zip(g.slug, g.symbol, g.action))
        for i in range(len(rec)):
            for j in range(i + 1, len(rec)):
                if rec[i][0] != rec[j][0] and rec[i][1] == rec[j][1] and (not same_side or rec[i][2] == rec[j][2]):
                    n += 1
    return n


obs, obs_s = pairs(it), pairs(it, True)
co = it.groupby("hour").slug.nunique()
print(f"trade intents {len(it)} in {it.hour.nunique()} hours; hours with >= 2 personas trading: {(co >= 2).sum()}")
print("Null: shuffle each persona's (symbol, side) across its own intents, keeping when it traded and")
print("its watchlist mix; 5000 draws. Watchlists overlap (NVDA on 5 lists), which the null keeps.")
rng = np.random.default_rng(11)
sims, sims_s = [], []
for _ in range(5000):
    sh = it.copy()
    for s, idx in sh.groupby("slug").groups.items():
        perm = rng.permutation(len(idx))
        sh.loc[idx, ["symbol", "action"]] = sh.loc[idx, ["symbol", "action"]].values[perm]
    sims.append(pairs(sh)); sims_s.append(pairs(sh, True))
sims, sims_s = np.array(sims), np.array(sims_s)
print(f"same-symbol pairs: observed {obs}, null mean {sims.mean():.2f}, p(>= observed) = {np.mean(sims >= obs):.4f}")
print(f"same-symbol same-side pairs: observed {obs_s}, null mean {sims_s.mean():.2f}, "
      f"p(>= observed) = {np.mean(sims_s >= obs_s):.4f}")
ex = []
for h, g in it.groupby("hour"):
    for sym, gg in g.groupby("symbol"):
        if gg.slug.nunique() >= 2:
            ex.append(f"{h:%Y-%m-%d %H:00} UTC {sym}: " + ", ".join(f"{a} {b}" for a, b in zip(gg.slug, gg.action)))
print(f"hours where >= 2 personas picked the same symbol: {len(ex)}")
for line in ex[:12]:
    print("   ", line)

# direction vs Monday: are the personas 'informed'?
st = wt[wt.state.isin(["settled", "breached"]) & wt.p_close.notna()].copy()
st["up"] = st.p_close.astype(float) > st.p_open.astype(float)
st["right"] = np.where(st.side == "buy", st.up, ~st.up)
bt = stats.binomtest(int(st.right.sum()), len(st), 0.5)
print(f"\nsettled sim weekend trades {len(st)}: Monday moved the persona's way in {int(st.right.sum())} "
      f"({st.right.mean():.1%}); binomial p vs 50% = {bt.pvalue:.3f}. Weekends are few and moves are "
      f"shared across symbols, so this is not independent evidence either way.")

# ---------------------------------------------------------------- 5. refusals and errors
hr("5. REFUSALS AND ERRORS")
n = len(d)
print(f"error (no usable decision): {(d.outcome == 'error').sum()} ({(d.outcome == 'error').mean():.1%}); "
      f"refused by the engine/broker: {(d.outcome == 'refused').sum()} ({(d.outcome == 'refused').mean():.1%}) of {n}")
intents = d[d.intent]
print(f"refused as a share of trade intents: {(intents.outcome == 'refused').mean():.1%} "
      f"({(intents.outcome == 'refused').sum()} of {len(intents)}); weekend "
      f"{(intents[intents.session == 'weekend'].outcome == 'refused').mean():.1%}, weekday "
      f"{(intents[intents.session != 'weekend'].outcome == 'refused').mean():.1%}")


def kind(e: str | None) -> str:
    if not isinstance(e, str) or not e:
        return "-"
    if "json_validate_failed" in e:
        return "groq: JSON validation failed"
    if e.startswith("groq"):
        return "groq: other " + re.sub(r"\d{3}.*", "", e[5:])[:20]
    if e.startswith("unusable answer"):
        return "unusable answer: " + re.sub(r"[\d.]+", "N", e.split(":", 1)[1].strip())[:40]
    return e.split(":")[0]


d["err_kind"] = d.error.map(kind)
print("\nerror kinds (outcome = error):")
print(d[d.outcome == "error"].err_kind.value_counts().to_string())
print("\nrefusal kinds (outcome = refused):")
print(d[d.outcome == "refused"].err_kind.value_counts().to_string())
print("\nrefusal kinds by persona:")
print(pd.crosstab(d[d.outcome == "refused"].slug, d[d.outcome == "refused"].err_kind).to_string())
oc = d[d.outcome == "refused"].err_kind.eq("over_cap").sum()
ic = d[d.outcome == "refused"].err_kind.eq("insufficient_cash").sum()
print(f"\nmodel-caused refusals (over_cap {oc} + insufficient_cash {ic} + insufficient_shares "
      f"{d[d.outcome == 'refused'].err_kind.eq('insufficient_shares').sum()}): the model was shown the cap "
      f"('max_qty_under_cap'), its cash and committed shares, and still asked past them")
print(f"infrastructure refusals: alpaca_auth_failed {d.err_kind.eq('alpaca_auth_failed').sum()}, "
      f"jupiter_unreachable {d.err_kind.eq('jupiter_unreachable').sum()}, no_token {d.err_kind.eq('no_token').sum()}")
print("\nmean stated confidence by outcome:")
print(d.groupby("outcome").confidence.agg(["count", "mean", "median"]).round(3).to_string())

# ---------------------------------------------------------------- 6. quotes
hr("6. SHORT REASONING SNIPPETS (LLM OUTPUT, NOT PEOPLE)")


def short(s: str, n_words: int = 28) -> str:
    w = str(s).split()
    return " ".join(w[:n_words]) + (" ..." if len(w) > n_words else "")


pick = d[d.reason.notna() & (d.session == "weekend")]
for s in PERSONAS:
    g = pick[pick.slug == s]
    if g.empty:
        continue
    r = g.sample(1, random_state=3).iloc[0]
    print(f"- {s} ({r.ts:%a %Y-%m-%d %H:%M} UTC, {r.action} {r.symbol or ''} -> {r.outcome}): \"{short(r.reason)}\"")
m = d[d.reason.fillna("").str.lower().str.contains("reserve") & d.intent]
if len(m):
    r = m.sample(1, random_state=5).iloc[0]
    print(f"- on the reserve, {r.slug}: \"{short(r.reason)}\"")
m = d[d.reasoning.notna() & d.reasoning.str.contains("reserve", case=False)]
if len(m):
    r = m.sample(1, random_state=8).iloc[0]
    i = r.reasoning.lower().find("reserve")
    print(f"- from a hidden reasoning trace, {r.slug}: \"...{short(r.reasoning[max(0, i - 120):i + 200], 45)}\"")

# ---------------------------------------------------------------- 7. figure
fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5))
cols = ["hold", "order", "weekend_trade", "refused", "error"]
colors = ["#bbbbbb", "#2e86ab", "#e09f3e", "#d1495b", "#333333"]
share = mix[[c for c in cols if c in mix]].div(mix.total, axis=0)
left = np.zeros(len(share))
for c, col in zip(share.columns, colors):
    a1.barh(share.index, share[c], left=left, color=col, label=c)
    left += share[c].values
a1.set_xlabel("share of decisions")
a1.set_title("Decision outcome mix per persona")
a1.legend(fontsize=8, ncol=5, loc="lower center", bbox_to_anchor=(0.5, -0.25))
a1.invert_yaxis()
x = np.arange(len(PERSONAS))
a2.bar(x - 0.2, wv.loc[PERSONAS, "wknd_trade_rate"], 0.4, color="#e09f3e", label="weekend")
a2.bar(x + 0.2, wv.loc[PERSONAS, "wkday_trade_rate"], 0.4, color="#2e86ab", label="weekday (reg/pre/after)")
for i, s in enumerate(PERSONAS):
    if wv.loc[s, "fisher_p"] < 0.05:
        a2.text(i, max(wv.loc[s, "wknd_trade_rate"], wv.loc[s, "wkday_trade_rate"]) + 0.02, "*", ha="center")
a2.set_xticks(x, PERSONAS)
a2.set_ylabel("share of decisions that asked to trade")
a2.set_title("Trade appetite: weekend vs weekday (* Fisher p < 0.05)")
a2.legend(fontsize=8)
fig.suptitle("LLM personas (one model, eight prompts) - not human traders", fontsize=11)
fig.tight_layout()
out = FIG / "persona_behaviour.png"
fig.savefig(out, dpi=150)
print(f"\nfigure: {out}")
