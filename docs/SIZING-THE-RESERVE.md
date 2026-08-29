# Sizing the reserve: why 2.326 was too small, and what we measured instead

This document explains one number in the paper's formula, how we tested it,
and what the data says. It answers three questions:

1. Where did the multiplier 2.326 come from?
2. Why is it too small?
3. Is the multiplier per symbol, or one number for everyone?

The numbers come from `notebooks/gap-volatility.ipynb` (run on 2026-08-28).
Read `docs/YAGNUM-EXPLAINED.md` §4e first if the formula is new to you.

## 1. The formula has two knobs, and they do different jobs

$$\text{ERR}_{\text{initial}} = Q \cdot P_{\text{open}} \cdot \sigma_{\text{gap}} \cdot z_{\alpha} + \text{Fees}$$

`Q · P_open` is the dollars at risk. The two knobs are:

- **`σ_gap` — the size knob.** It says how far this stock typically moves
  across a weekend. It is **measured per symbol**. NVDA moves more than
  McDonald's, so NVDA gets a bigger σ.
- **`z_α` — the shape knob.** It says how many σ you must reserve to cover
  the bad weekends, not just the typical ones. It depends on the *shape* of
  the weekend moves: are the rare bad ones a little worse than typical, or
  much worse?

So the reserve for one order is `(per-symbol size) × (shape multiplier)`. The
question "is the multiplier per symbol?" is really two questions, and the
answers differ. Section 5 returns to it.

## 2. Where 2.326 came from

The paper took `z` from the **bell curve** (the normal distribution). On a
bell curve, 99% of outcomes sit below 2.326 standard deviations. So "reserve
2.326 σ and you are covered 99% of the time" is true **if weekend moves
follow a bell curve**. That assumption was never tested. It is the kind of
assumption a formula makes quietly.

## 3. The test, and why 2.326 fails it

We took two years of real data: 19 shares, every weekend, the Friday close
and the Monday open — **1,864 weekend gaps**. For each gap we computed the
log return `r = ln(open_Monday / close_Friday)`.

Then we asked the bell curve's promise directly. If the reserve is 2.326 σ,
how many weekends broke through it?

| Side | Bell curve promises | Two years of data |
| --- | --- | --- |
| Seller (Monday lower than expected) | 1.00% | **1.93%** |
| Buyer (Monday higher than expected) | 1.00% | **1.50%** |

Almost twice the promised failures for sellers. The reason is visible in one
number: **excess kurtosis**. Kurtosis measures how heavy the tails of a
distribution are. A bell curve scores 0. The pooled weekend gaps score
**27**. Real weekends produce extreme moves far more often than a bell curve
predicts: earnings, Sunday-night news, a macro shock. These are the
weekends a reserve exists for, and they are exactly the ones the bell curve
under-counts.

The shape differs by stock, which matters for section 5:

| Share | σ (weekend) | Excess kurtosis | Worst 1% weekend |
| --- | --- | --- | --- |
| MCD | 0.71% | 2.4 | −1.5% |
| SPY | 0.90% | 6.2 | −3.4% |
| AAPL | 1.70% | 14.3 | −6.1% |
| NVDA | 2.70% | 13.7 | −13.2% |
| TSLA | 2.62% | 4.3 | −6.7% |
| MSTR | 4.79% | 18.7 | −11.7% |

`notebooks/figures/01_market_gap_histogram.png` shows the whole distribution
with a bell curve drawn over it. The tails stick out past the curve on both
sides.

## 4. How we found the multiplier that works

Instead of asking the bell curve, ask the data. Take every weekend gap,
divide it by its stock's σ (so every stock is on the same scale), sort the
results, and read off the value that only 1% of weekends exceed. That is an
**empirical percentile**: no curve assumed, just counting.

Two years of market gaps gave:

- Two-sided (either direction): the 99th percentile of |gap/σ| is **4.10**,
  where the bell curve says 2.58.
- One-sided, which is what one trade needs: **3.50 for a seller, 2.61 for a
  buyer**. The asymmetry is real: weekend crashes are bigger than weekend
  rallies.

Then we ran the formula **as if live**, on the token data — 344 token-weekends
over 180 days. For each weekend, σ was estimated only from the weekends
before it (no look-ahead), the reserve was set two ways, and we counted how
often the actual move broke through:

| Multiplier | Sell-side breaches | Buy-side breaches | Average reserve (% of trade) |
| --- | --- | --- | --- |
| Bell curve, z = 2.326 | **4.65%** | 2.33% | 4.4% |
| Empirical 99th percentile, z ≈ 3.67 on average | **0.87%** | 1.16% | 6.9% |

The empirical multiplier meets the 1% target. It costs more: the trader parks
about 6.9% of the trade's value instead of 4.4%. That trade-off — coverage
versus capital drag — is the paper's Research Question 1, now with a number
on each side. `notebooks/figures/04_backtest_breach_rates.png` is this table
as a chart.

## 5. So, is the multiplier per symbol?

**σ is per symbol. z is pooled — for now, and for a reason.**

In principle `z` differs per symbol too. The kurtosis table above says so:
McDonald's tails are mild (2.4), MSTR's are wild (18.7). Computing the
one-sided seller multiplier per share from the two-year data gives:

| Share | z needed for a true 1% (seller) |
| --- | --- |
| MCD | 2.1 |
| MSTR | 2.4 |
| TSLA | 2.6 |
| HOOD | 3.2 |
| AAPL | 3.6 |
| SPY | 3.7 |
| NVDA | 4.9 |

That spread is real, but each number rests on about 103 weekends, and the
"1% tail" of 103 observations is the single worst weekend. One more bad
Monday changes NVDA's 4.9 to something else entirely. The token data is
thinner still — 25 weekends per token, 7 or 8 for some. The notebook tried
per-token multipliers in the back-test and they failed (5.4% breaches for
*both* methods), because with 8 to 17 prior weekends the "99th percentile"
is just the worst weekend seen so far.

The rule we follow is the statistician's: **estimate the shape from the
pooled sample until each symbol has enough weekends to stand alone.**
Pooling 1,864 weekends gives a stable tail; 25 do not. As the sampler
records more weekends, the per-symbol multipliers become usable, and the
formula does not change — only where `z` comes from.

## 6. What this means for one order

10 NVDA at $226, exposure $2,260:

| Sizing | Reserve |
| --- | --- |
| Paper's illustration (σ = 2%, z = 2.326) | $105 |
| Token σ at 9:30 (1.04%) × bell-curve z | $55 |
| Token σ × empirical z (3.67) | $86 |
| Market σ (2.70%) × seller z (3.50) | $214 |
| Market σ × NVDA's own z (4.9) | $299 |

The honest statement: a reserve of about **$150** covered 99% of weekends in
both samples. Until the token history is long, we size from the larger of
the two σ sources, because the token sample contains no crash yet.

## 7. Decision status

Recorded as a proposal for ADR-018, awaiting the owner's decision:

- The formula in §6d stays exactly as written.
- `z_α` is defined as the empirical one-sided 99th percentile of past
  gap/σ, pooled across symbols, recomputed as data accumulates — not the
  normal-table constant 2.326.
- `σ_gap` stays per symbol, and is taken as the larger of the two-year
  market estimate and the token estimate until the token history spans a
  market shock.

Caveats the notebook states and this document repeats: 25 weekends per
token is thin; the token sample (March to August 2026) contains no crash;
seven tokens have only 7 or 8 weekends; the premarket settlement question
waits for the sampler's own data and a full-market feed.
