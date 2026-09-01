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

## 2. Where 2.326 came from: the bell curve, from the ground up

### The five-year-old version

Measure the height of everyone in a school and draw a bar chart. Most
people are near the middle. A few are very short or very tall. The chart
looks like a bell. Nobody is three metres tall. The bell curve is a rule
that says *how many* people you find at each distance from the middle, and
it says "extremely far from the middle" almost never happens.

Weekend stock moves are not like heights. They are like earthquakes. Most
weekends the ground barely moves. Once in a while, it moves a lot — far
more than "almost never". So a rule built for heights under-counts the big
weekends.

### What the bell curve actually is

The bell curve is the **normal distribution**. It is a formula that gives
the probability of each outcome, and it has exactly two inputs:

- **μ (mu), the mean** — where the middle of the bell sits.
- **σ (sigma), the standard deviation** — how wide the bell is.

Its shape is fixed by a single equation:

$$f(x) = \frac{1}{\sigma\sqrt{2\pi}} \; e^{-\frac{(x-\mu)^2}{2\sigma^2}}$$

You do not need the equation to use it. You need one consequence: **once
you know μ and σ, the curve tells you the share of outcomes in any range.**
About 68% sit within 1 σ of the mean, 95% within 2 σ, 99.7% within 3 σ.
These fractions are the same for heights, for test scores, for anything
that is truly bell-shaped — that is the whole appeal.

### What "measured from" means

Two different things are measured, and it helps to keep them apart.

**The curve's numbers, 2.326 included, are not measured from any data.**
They are pure mathematics. Take a bell curve with μ = 0 and σ = 1 (the
"standard normal"). Ask: below what value does 99% of the area sit? The
answer is 2.326. This function — "give me a probability, I give you the
cut-off" — is written Φ⁻¹ (the inverse of the cumulative distribution
function), and 2.326 = Φ⁻¹(0.99). In code, `scipy.stats.norm.ppf(0.99)`.
Other rows of the same table: 1.645 for 95%, 3.090 for 99.9%, and 2.576 if
you want 99% *two-sided* (both tails together).

**What is measured from data is whether our weekends fit that curve.** The
procedure has three steps:

1. Standardize every gap: `z_i = (r_i − μ) / σ`, where μ and σ come from
   the 1,864 observed gaps themselves (μ is about 0, σ is 2.51%). This puts
   every weekend on the "how many σ from the middle" scale. NVDA's −13.2%
   weekend is 4.9 σ on its own scale.
2. If the gaps were bell-shaped, then by the curve's rule exactly 1% of
   these `z_i` values would lie below −2.326. Count how many actually do.
3. Compare. We found 1.93%, not 1%.

That count is the test. A bell curve fitted to our data — same μ, same σ —
predicts a number of extreme weekends; the data contains almost twice as
many. **Kurtosis** is the summary statistic for this: it is the average of
`z_i⁴` minus 3, so it is dominated by the largest |z| values, and a bell
curve scores exactly 0. Our 27 says the fourth power of the extremes is
enormous relative to what the curve allows.

### Why people assume a bell curve, and why it fails here

There is a theorem (the central limit theorem) that says: add up many small,
independent random effects and the total is bell-shaped, no matter what the
individual effects look like. Heights are like that — thousands of genes
and meals, each a small nudge. Many finance formulas lean on this theorem.

A weekend gap is not the sum of many small nudges. It is usually nothing,
plus occasionally one large lump: an earnings report, a tariff announced on
Sunday night, a war. One lump is not "many independent small effects", so
the theorem does not apply, and the tails come out fat. The paper inherited
the bell-curve multiplier from that tradition. The data says the tradition
does not hold for weekend gaps, which is exactly the kind of finding an
empirical section exists to make.

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

## 8. Where the research data lives

### The five-year-old version

There is a spreadsheet in the cloud that never sleeps. A robot adds one row
to it every five minutes, day and night, with the price of each token and
each share. Another robot, run once, copied six months of old prices into
it. The notebook is a report that reads the spreadsheet and draws the
charts. The spreadsheet stays; the report can be re-run any time.

### The actual layout

**The database.** One Postgres database hosted by Neon (project
`winter-surf-22863956`, branch `development`, region AWS us-east-2). It is
the same database the app uses for its audit log and fills ledger; the
research tables sit beside them. The connection string is `DATABASE_URL`
in the repo-root `.env` (never committed) and, for the robot, a GitHub
Actions secret of the same name. Postgres stores every price as `NUMERIC`,
exact decimal digits — never a floating-point number (ADR-010).

**Three tables, three writers.**

| Table | One row is | Rows (2026-08-29) | Written by | Source |
| --- | --- | --- | --- | --- |
| `token_prices` | one token, one 5-minute moment: Jupiter price, Alpaca last trade, market open? — and since 2026-09-01 the executable bid/ask for ~$1,000 each way (`bid_usd`, `ask_usd`, impact columns; ADR-020) | 4,960 and growing by 5,760 a day | `scripts/sample_prices.py`, run every 5 minutes by the GitHub Actions cron `.github/workflows/sample-prices.yml` | Jupiter Price API v3; Alpaca latest trades |
| `token_candles` | one token, one hour (or day): open, high, low, close, volume | 57,861 | `scripts/backfill_history.py`, run once | GeckoTerminal OHLCV (free tier: last 180 days) |
| `market_bars` | one share, one day or one minute: open, high, low, close, volume, trade count | 38,820 | same script, run once | Alpaca market data, IEX feed (2 years daily; Monday 04:00–10:30 ET minutes) |

Each table is **append-only**: rows are added, never edited or deleted. The
backfill uses `INSERT … ON CONFLICT DO NOTHING` on a natural key (symbol +
timeframe + timestamp), so running it twice adds nothing — a property that
saved the dataset when a run was interrupted.

**The code that fills them** lives in `app/api/`: `jupiter.py` and
`geckoterminal.py` (thin API clients that decode numbers as text),
`alpaca.py` (`latest_trades`, `bars`), `sampler.py` (one snapshot),
`backfill.py` (paging and upserts), and `models.py` (the table
definitions; `alembic/versions/` holds the migrations that created them).

**The notebook** is `notebooks/gap-volatility.ipynb`. It connects with the
same `DATABASE_URL`, loads each table into a pandas DataFrame with
`read_sql`, and does every calculation in memory. It writes nothing back.
Its charts are saved to `notebooks/figures/*.png`, and the notebook file
itself is committed *with its outputs*, so the numbers in this document can
be checked on GitHub without running anything. To re-run it after new
weekends arrive:

```
cd app/api
uv run --group research jupyter nbconvert --to notebook --execute --inplace ../../notebooks/gap-volatility.ipynb
```

**The external sources and their limits**, because they shape what the
notebook can and cannot say:

- Jupiter's Price API is current-price only — no history. That is why the
  sampler exists: nobody else keeps a five-minute weekend record.
- GeckoTerminal's public tier serves the last 180 days of candles and about
  30 calls a minute. Older token history costs money.
- Alpaca's sandbox serves the IEX feed, which prints nothing before 08:00
  ET. Earlier premarket needs a full-market (SIP) feed.
- A pool only prints an hourly candle in hours with a trade, so thin tokens
  have gaps; the notebook drops a weekend if the token's reference price is
  more than 6 hours stale.

**What is *not* stored anywhere**: no wallet, no private key, no swap. Every
byte here is a price somebody else published, copied so it cannot vanish.
