# Project Yagnum: Capstone Reference

Everything needed to write, defend, or extend a capstone on Project Yagnum, in
one document. Compiled 2026-10-13 from the thirteen working documents in
`docs/`, plus new material those documents do not contain: the research
questions stated formally, the competitive landscape, the first real empirical
results, the limitations, and a work plan.

**Read this first if you are new to the project.** Everything here is either
drawn from the project's own documents, or measured from its database on
2026-10-13. Where a claim is a hypothesis rather than a result, it says so.

---

## 1. What this document is, and what is already true

Project Yagnum is a **working, deployed, continuously running system**, not a
proposal. As of 2026-10-13 it has been collecting data for 47 days and
settling trades automatically for 5 weeks, with no human intervention between
runs.

The capstone is therefore not "build Yagnum." It is **"use Yagnum to answer a
question nobody has answered."** The system is the instrument; the capstone is
the measurement.

| Already done | What the capstone adds |
| --- | --- |
| The settlement engine, built and running | The analysis of what it recorded |
| 23,260 price observations, still accumulating | The research questions those observations answer |
| 126 trades settled at real market prices | Whether the reserve model actually worked, and where it failed |
| 13 engineering documents | A written argument with a result and its limitations |

**An important attribution note.** The underlying academic proposal, which
describes the settlement design and its formulas, was written by Yagnesh's
father. The implementation, the measurement infrastructure, the empirical
results, and this document are the student project. Any capstone write-up must
keep that line visible: the theory is cited, the measurement is original.

---

## 2. Abstract and thesis

**Abstract.** United States stock markets are closed for roughly 48 hours every
weekend, but tokenized copies of real shares trade continuously on Solana. A
price therefore exists when the market does not. This project builds and
operates a settlement framework that lets a brokerage customer act on that
weekend price safely: the trade executes provisionally against a live token
quote, a cash reserve sized from measured volatility is held until the market
reopens, and the real shares settle at the first regulated price with the
reserve returned adjusted for the move. Over 47 days the system recorded 23,260
paired token-and-share price observations and settled 126 weekend trades
automatically. The reserve covered the realised weekend gap in 124 of them, or
98.4 percent, against a design target of 99 percent. The two failures were not
randomly distributed: both were the same symbol, and that symbol's reserve was
sized at approximately its mean weekend gap rather than its tail. The finding
is that **the pooled confidence multiplier is sound and the per-symbol
volatility estimate is the weak link**, because the quantity measured (the
share's Friday-close to Monday-open move) is not the quantity actually at risk
(the token's weekend quote to Monday's fill).

**Thesis in one sentence.** A measured, customer-collateralized cash reserve
can bridge weekend token prices to regulated Monday settlement, and the
limiting factor is not the statistical method but the choice of what to measure.

---

## 3. The problem

**ELI5.** The stock market is a shop that closes Friday evening and opens
Monday morning. A second shop next door sells receipts for the same goods and
never closes. On Saturday you can see what a receipt costs, but you cannot get
the actual good until Monday, and by Monday the price has moved. Someone has to
cover that difference.

**In full.** United States equity markets trade 9:30 to 16:00 Eastern on
weekdays. Alpaca, the brokerage this project uses, extends that to roughly 24
hours over 5 days, so the genuinely dead window is the weekend: Friday 20:00 to
Sunday 20:00 Eastern, about 48 hours. The paper originally assumed 65 hours;
measuring it found 48, which is a smaller and more precisely bounded problem.

Tokenized equities, called xStocks and issued by Backed Finance, are Solana
tokens each backed one-to-one by a real share held in custody. They trade
continuously through Jupiter, a Solana exchange aggregator. So on a Saturday,
`NVDAx` has a live, tradeable price while `NVDA` has none.

This produces two prices for one economic event:

| Symbol | Meaning | Known when |
| --- | --- | --- |
| `p_open` | The token's executable price at the moment of the weekend trade | Immediately |
| `p_close` | The price at which the real share fills at the next regulated session | Only Monday |

The difference between them is the **weekend gap**, and it is the entire risk
the project exists to manage. Measured across 126 real settlements, the gap
averaged 2.83 percent of trade value and reached 16.12 percent at its worst.

**The trap.** It is tempting to treat the token price as simply "the price."
It is not. It is a price at a venue with different liquidity, different
participants, and no mechanism to create or redeem shares while the custodian
is closed. Treating the two as interchangeable is exactly the mistake the
reserve exists to prevent.

---

## 4. Key concepts and vocabulary

Defined once, used consistently throughout the project.

| Term | Meaning |
| --- | --- |
| **Tokenized equity** | A blockchain token backed one-to-one by a real share held by a custodian. |
| **xStock** | Backed Finance's brand of tokenized equity on Solana. `NVDAx` tracks `NVDA`. |
| **Mint** | A token's unique identity on Solana, the equivalent of a ticker symbol. |
| **Jupiter** | A Solana exchange aggregator that routes a trade to the pool offering the best price. It is not itself a pool. |
| **AMM** | Automated market maker. A pool of two assets whose formula sets the price. Jupiter routes to these. |
| **Execution** | The moment a trade's price is agreed. |
| **Settlement** | The moment the real asset and the real money actually change hands. |
| **The core design rule** | Execution and settlement are **separated in time**. Jupiter provides execution immediately; the brokerage provides settlement when it reopens. |
| **ERR** | Execution Reconciliation Reserve. The cash held from the trader between execution and settlement. |
| **σ (sigma)** | Measured standard deviation of a symbol's weekend price gap. Per symbol. |
| **z** | A confidence multiplier. How many sigmas of movement the reserve must cover. Pooled across all symbols. |
| **True-up** | The adjustment applied to the reserve at settlement, equal to the realised gap. |
| **Breach** | The gap exceeded the entire reserve. Escrow is collateral, not a cap, so the excess is debited. |
| **Provisional** | A weekend trade that has executed but not yet settled. |
| **Slippage and price impact** | How much a trade moves the price against itself. Larger orders get worse prices. |
| **Gas** | The fee paid to a blockchain's validators to include a transaction. |
| **Rent** | A refundable deposit Solana requires to keep a token account open, about 0.002 SOL. |

---

## 5. Related work and the competitive landscape

This section exists nowhere else in the project's documents and is essential
for a capstone, which must situate itself against prior work.

### The three layers

Any tokenized-equity system has three separable layers. Confusing them is the
most common error in discussing this space.

1. **Issuance.** Who mints a token against a custodied share.
2. **Venue.** Where that token trades.
3. **Settlement.** How a regulated brokerage customer gets the off-hours price
   without ever holding the token.

Yagnum operates **only at layer 3**. It issues nothing and runs no venue.

### Who does what

| Party | Issuance | Venue | Settlement to a regulated account | US persons |
| --- | --- | --- | --- | --- |
| **Backed Finance (xStocks)** | Yes | No, trades on Solana venues | No | Not offered |
| **Jupiter** | No | Yes, as an aggregator | No | Permissionless |
| **Robinhood Chain** | Yes | Yes, its own L2 plus DEXs | No, the token is the product | Not offered |
| **Dinari** | Yes | Infrastructure for others | No | Limited |
| **Alpaca** | No | Regulated brokerage, 24/5 | Weekdays only | Yes |
| **Yagnum** | No | No | **Yes, this is the contribution** | Yes, by design |

### Robinhood Chain, the closest comparison

In July 2026 Robinhood launched its own Ethereum layer-2 blockchain with more
than 90 tokenized stocks trading continuously, and by September the chain was
posting the highest network revenue of any blockchain on some days. It is the
most serious thing in this space.

**How Robinhood handles the weekend.** It does not solve the gap; it
reallocates it. The token keeps trading, nobody can create or redeem shares
while the custodian is shut, so the spread widens and Robinhood or its market
makers carry the inventory risk. The customer ends the weekend holding a token
whose price may diverge from Monday's open. The cost is embedded in a wider
spread, which is neither measured nor disclosed to the customer.

**What that means for this project.** Robinhood's launch strengthens the
motivation and does not threaten the contribution:

- It is **validation**. The largest US retail broker has conceded, in product
  form, that a weekend price exists and that someone must carry the gap.
- It is **not competition for the same user**. Robinhood's stock tokens are
  explicitly not offered to US persons. Yagnum's customer is a US brokerage
  customer who never touches a token.
- It has **no equivalent of the ERR**. There is no per-trade reserve, no
  measured sizing, and no reconciliation to a regulated price. The customer
  simply keeps the token.
- The **real risk is regulatory**, not competitive. If the SEC approves a
  regime for tokenized equities for US retail, Robinhood could offer this
  natively with issuance, venue, brokerage, and balance sheet under one roof,
  and the reserve would become an invisible internal spread.

**The defensible positioning:** Yagnum is the broker-agnostic, transparent
version. Any brokerage on compatible rails could adopt it, and the cost of the
weekend is published as a number rather than buried in a spread.

### Academic context

The relevant literature is on **settlement risk** and **the cost of immediacy**.
The classical result is Demsetz's framing of the bid-ask spread as the price of
immediacy, and the market-microstructure literature on **adverse selection**:
the traders most eager to transact are disproportionately those acting on
information the counterparty lacks. That result is why the project's proposal
rejects quoting a firm weekend price, and it is worth citing directly, because
it is the reason the pass-through design is correct rather than merely
convenient. Verify and cite these properly; they are named here from domain
knowledge, not from a source consulted while writing.

---

## 6. Research questions

Stated formally. The project's documents reference RQ2 through RQ5 informally;
this is the first place they are written out.

**RQ1. How large is the weekend gap, and is it predictable?**
*Answerable now.* Measure the distribution of `p_close − p_open` across
recorded weekends, per symbol and pooled. Status: **answered in part**, see
Section 10.

**RQ2. What does weekend liquidity cost, and does the spread widen when the
regulated market is closed?**
*Data collecting since 2026-09-01.* Two executable quotes per token every five
minutes, 9,940 observations recorded. Test whether spread as a fraction of
midpoint is significantly wider in the weekend window than in regular hours,
controlling for symbol. Status: **data complete, analysis not yet run.** This
is the single most tractable unanswered question and the recommended capstone
core.

**RQ3. Does a reserve sized at z sigma actually cover the realised gap at the
claimed confidence?**
*Answerable now.* Compare realised |true-up| against the reserve held, per
trade. Status: **answered, and the answer is interesting**, see Section 10.

**RQ4. Does the token lead or lag the share around the Monday open?**
*Partially blocked.* The first recorded weekend showed the token pricing
Monday's 0.77 percent gap by 04:05 Eastern, five and a half hours before the
market confirmed it. If that generalises, the token is a **price-discovery
venue**, not merely a mirror, which is a much stronger claim than the project
currently makes. Blocked by data: the free market-data feed prints no premarket
share trades, so the share side of the comparison is missing. Addressable by
using the token's own early-morning series against the 09:30 open.

**RQ5. What would a firm-price product have cost?**
*Instrumented, not analysed.* Every weekend trade records a shadow on-chain
hedge: what it would have cost in spread and gas to guarantee the weekend price
and offset it on Solana. 232 hedge legs recorded. This is the empirical version
of the adverse-selection argument the proposal makes in prose.

---

## 7. The ERR mechanism, with worked examples

### The design in one paragraph

The trader executes at the token's live weekend price and receives cash (on a
sell) or shares (on a buy) immediately. A reserve is journaled from their
account into escrow. At the next regulated session the real shares trade, and
the reserve is returned **adjusted by the realised gap**. The trader therefore
ends at Monday's price, which is the price a regulated market actually
produced, but they had their cash or their position two days early. Yagnum ends
flat on every trade by design.

### The formulas

Reserve sizing:

```latex
\text{reserve} = q \times p_{\text{open}} \times \sigma_{\text{symbol}} \times z + \text{fees}
```

True-up at settlement, signed from the trader's side:

```latex
\text{true-up} = \begin{cases} q\,(p_{\text{close}} - p_{\text{open}}) & \text{sell} \\ -q\,(p_{\text{close}} - p_{\text{open}}) & \text{buy} \end{cases}
```

Escrow released:

```latex
\text{released} = \text{reserve} + \text{true-up}
```

A negative `released` means the gap exceeded the whole reserve. The trade is
marked breached and the excess is debited, because escrow is collateral, not a
cap.

### Current parameters

Measured 2026-08-31 from 2,089 market weekends and 407 token-weekends.

| Parameter | Value | Source |
| --- | --- | --- |
| `z`, pooled | 3.7742 | Empirical 99th percentile of \|gap\|/σ across all token-weekends |
| `σ`, pooled | 0.0242 | Across all symbols |
| `σ`, per symbol | 0.0086 (MCD) to 0.0477 (MSTR) | max(2-year share gaps, token gaps) |

**Why z is 3.7742 and not 2.326.** A statistics course gives 2.326 for a
one-sided 99 percent interval under a normal distribution. The measured value
is 62 percent larger because real weekend gaps have **fatter tails** than the
normal curve. Using the textbook number would under-reserve every trade. This
difference between a formula and a measurement is one of the better teaching
points in the project.

### Worked example, a real settled trade

Trade 46, a simulated trader's sell, settled 2026-09-08. Arithmetic verified
against the database.

| Step | Value |
| --- | --- |
| Weekend sell, 16 NVDA at the token's executable bid | $232.0101 per share |
| Reserve held (σ 0.0269 × z 3.7742 = 10.15%) | $376.89 |
| Monday fill, real shares at the broker | $226.38 |
| True-up: 16 × (226.38 − 232.0101) | −$90.08 |
| Escrow released: 376.89 − 90.08 | **$286.81** |

The trader's net outcome equals 16 shares at Monday's $226.38. The reserve
absorbed the entire move and $286.81 of $376.89 came back. Yagnum ended flat.

### The mirror case, a buy

Trade 43, 30 AAPL bought at $321.9263, filled Monday at $316.26. The buy's
true-up reverses sign, so the trader receives **more** than their reserve back:
$619.66 + $169.99 = $789.65. The real shares cost less than the weekend price,
and the difference is returned.

### The design that was rejected, and why

The alternative is to quote a firm weekend price and keep the gap. The proposal
rejects it on **adverse selection** grounds: weekend traders are
disproportionately those reacting to weekend news, their flow pushes the gap
systematically against whoever quotes the firm price, and that party cannot
hedge because the regulated market is shut. A fee cannot fix it, because
informed traders pay the fee only when it is worth it to them.

This is worth knowing because the project briefly implemented the rejected
design by mistake on 2026-09-07 and reverted it the same day. The error and its
correction are recorded as ADR-028 and ADR-029. A capstone that discusses the
design space honestly is stronger than one that presents a single answer as
obvious.

---

## 8. System architecture

### The stack

| Layer | Technology |
| --- | --- |
| Front end | Next.js 16, React 19, TypeScript, Tailwind |
| Back end | FastAPI, Python 3.13 |
| Database | Postgres (Neon), SQLAlchemy 2, Alembic migrations |
| Auth | Clerk |
| Brokerage | Alpaca Broker API, sandbox |
| Token data and quotes | Jupiter, plus GeckoTerminal for history |
| Blockchain reads and signing | Solana JSON-RPC, `solders` |
| Agent decisions | Groq, `openai/gpt-oss-120b` |
| Hosting | Azure App Service, free tier |
| Automation | 4 GitHub Actions cron jobs |

### Session routing: the five windows

Every hour belongs to exactly one execution path. Jupiter is never the path
while a regulated venue is open.

| Window | Eastern time | Execution path |
| --- | --- | --- |
| Premarket | 04:00 to 09:30 | Broker, limit order, extended hours |
| Regular | 09:30 to 16:00 | Broker, market order |
| After hours | 16:00 to 20:00 | Broker, limit order, extended hours |
| Overnight | 20:00 to 04:00 | Queues at the broker until 04:00 |
| **Weekend** | Fri 20:00 to Sun 20:00 | **The ERR engine** |

Market holidays route as weekends, resolved against Alpaca's calendar and
cached daily.

### The trade state machine

```
provisional ──► awaiting_settlement ──► settled
                                   └──► breached
```

- **provisional**: executed against the token quote, reserve escrowed, cash or
  shares delivered.
- **awaiting_settlement**: a real order is working at the broker.
- **settled**: the order filled, the true-up ran, the escrow returned.
- **breached**: the gap exceeded the reserve; the excess was debited.

### Two design choices worth defending in a viva

1. **Every cash movement is a real tagged journal at the brokerage.** The
   invariant "escrow covers every open weekend trade" is therefore a *query
   against the broker's records*, not a promise made by our own code. This is
   the difference between an auditable system and a trusted one.

2. **Money is never a floating-point number.** Every monetary value is a
   decimal string at system boundaries and a `Decimal` internally. IEEE-754
   doubles cannot represent every decimal exactly, and a balance that drifts by
   a fraction of a cent per operation is a real failure mode in financial
   software.

### Unattended automation

| Job | Schedule | What it does |
| --- | --- | --- |
| `sample-prices` | Every 5 minutes, always | Records each token's price and spread beside its real share |
| `sim-users` | Hourly | One group of AI personas decides and trades |
| `settle-weekend` | Every 10 minutes, weekday mornings | Places hedges and reconciles open weekend trades |
| `deploy-azure` | On push to main | Rebuilds and redeploys both apps |

---

## 9. Methodology

### The data pipeline

Every five minutes, for each of 26 tokens, the sampler records: the token's USD
price from Jupiter, its liquidity, the real share's last trade from Alpaca,
whether the market was open, and two executable swap quotes of about $1,000 in
each direction giving the bid, the ask, and the price impact of each.

**Why executable quotes rather than the last traded price.** The last swap
price tells you what somebody else already paid. A quote for *your* size tells
you what you would actually get. For a settlement system the second is the only
honest number, and the difference between them is the spread the project is
measuring in RQ2.

### How sigma is measured

Two independent estimates per symbol, and the engine uses the larger:

1. `sigma_market_2y`: the standard deviation of real Friday-close to
   Monday-open gaps over about two years of daily bars.
2. `sigma_token`: the standard deviation of token Sunday-23:00 to Monday-09:30
   gaps from historical candles.

Taking the maximum is the conservative choice while the token record is thin.
Section 10 shows that this rule is **not conservative enough** for at least one
symbol.

### How z is measured

Pooled across all symbols, not per symbol. For every recorded token-weekend,
compute |gap| / sigma, then take the empirical 99th percentile of that
distribution. This yields 3.7742.

**Why pooled.** Per-symbol z would be fitted to very few observations each and
would overfit. The ratio |gap|/sigma should be approximately symbol-independent
if sigma is doing its job, so pooling is both statistically sound and a
testable assumption. Section 10 tests it.

### The refresh ritual

After each recorded weekend: top up the history tables, re-execute the
volatility notebook, and regenerate `research_params.json`. The file carries a
`generated_at` date so staleness is always visible.

**This ritual has not run since 2026-08-31.** The parameters in production are
six weeks old. That is a finding, and it is the first item in the work plan.

---

## 10. Results to date

All figures measured from the project database on 2026-10-13.

### The dataset

| Measure | Value |
| --- | --- |
| Price observations | 23,260 |
| Distinct tokens tracked | 26 |
| Collection window | 2026-08-28 to 2026-10-14, continuous |
| Observations including executable spread | 9,940 |
| Weekend trades settled at real market prices | 126 |
| Agent decisions recorded | 824, from 8 personas, over 40 days |
| On-chain hedge legs modelled | 232 |

### RQ1: how large is the weekend gap?

Across 126 market-settled trades, the realised gap as a fraction of trade value:

| Statistic | Value |
| --- | --- |
| Mean \|gap\| | 2.83% of notional |
| Maximum \|gap\| | 16.12% of notional |

Per symbol, the dispersion is wide and clearly structured by asset type:

| Symbol | Trades | Mean \|gap\| | Max \|gap\| |
| --- | --- | --- | --- |
| MSTR | 14 | 5.66% | 16.12% |
| META | 11 | 6.02% | 10.99% |
| COIN | 6 | 6.01% | 10.18% |
| HOOD | 7 | 4.16% | 8.92% |
| TSLA | 14 | 3.10% | 5.45% |
| NVDA | 27 | 1.81% | 3.72% |

Crypto-correlated equities (MSTR, COIN) and high-beta names gap hardest, which
is the expected direction and a useful sanity check on the measurement.

### RQ3: did the reserve hold? The headline result

| Measure | Value |
| --- | --- |
| Market-mode settlements | 126 |
| Reserve covered the gap | 124 |
| **Empirical coverage** | **98.4%** |
| Design target | 99% |
| Mean reserve utilisation | 31.5% |
| Maximum reserve utilisation | 181.9% |

Coverage of 98.4 percent against a 99 percent target is close, and with 126
observations the difference is not statistically strong on its own. **The
interesting part is that the failures are not random.**

### The finding: the failures concentrate in one symbol

Reserve utilisation, meaning realised gap as a percentage of the reserve held:

| Symbol | Trades | Mean utilisation | Max utilisation |
| --- | --- | --- | --- |
| **META** | 11 | **99.7%** | **181.9%** |
| MSTR | 14 | 31.5% | 89.5% |
| COIN | 6 | 42.7% | 72.3% |
| SPY | 18 | 20.8% | 68.2% |
| TSLA | 14 | 31.5% | 55.3% |
| NVDA | 27 | 17.9% | 36.7% |

Both real breaches were META buys, on 2026-09-16 and 2026-09-22.

META's reserve is 1.60 percent sigma times 3.7742, or **6.04 percent of
notional**. META's *mean* realised weekend gap was **6.02 percent**. The reserve
is sized at roughly the average outcome, when it is supposed to be sized at the
99th percentile. By contrast NVDA's reserve covers its worst observed weekend
roughly three times over.

### Interpretation, stated as a hypothesis

The pooled z is doing its job; the per-symbol sigma is not. For META both
estimates were low (`market_2y` 0.0160, `token` 0.0097), so taking the maximum
did not help. The likely cause is that **the quantity measured is not the
quantity at risk**:

- `sigma_market_2y` measures the *share* from Friday's close to Monday's open.
- The engine's actual exposure runs from *the token's executable quote at an
  arbitrary weekend moment* to Monday's fill.

Those differ by the token-versus-share basis, by the timing within the weekend,
and by the spread embedded in an executable quote. A sigma estimated on
share-only Friday-to-Monday moves systematically omits the basis component. If
that is right, the fix is to measure sigma on the **realised quantity the
engine actually experiences**, which the project now has 126 direct
observations of.

This is a testable hypothesis, not a demonstrated result, and testing it is the
strongest available capstone contribution.

### Secondary results

- **Gas cost of a modelled on-chain hedge**: mean $0.1887, range $0.1449 to
  $0.3063 per leg, across 232 legs. The dominant component is the one-time
  refundable token-account rent, not the transaction fee.
- **Token as early price discovery**: on the first fully recorded weekend, the
  token had priced Monday's +0.77 percent open by 04:05 Eastern, five and a
  half hours before the regulated market confirmed it. One observation, not a
  result, but it motivates RQ4.
- **Engine correctness**: settlement arithmetic was verified by hand against
  the database for both a sell and a buy, exact to the cent.

---

## 11. Experiment: the simulated-trader population

### Design

Eight language-model personas, each with a distinct trading style, its own
funded brokerage sandbox account, and a watchlist. Every hour one of two groups
takes a turn. Each persona receives a briefing containing the time and session
window, its cash and positions, its open weekend trades, and for each watched
symbol the token price, recent moves, the executable spread, and that symbol's
reserve percentage. It replies with a single JSON intent: buy, sell, or hold.

The intent passes through **exactly the same code path a human order takes**.
The engine's own guards accept or refuse it.

| Personas | Style |
| --- | --- |
| Maya | Momentum |
| Walter | Patient value |
| Dev | High risk, odd hours |
| Priya | Index rebalancer |
| Ken | Contrarian |
| Lena | Execution-cost sensitive |
| Omar | Weekend specialist |
| Sam | Mean reversion |

### Results over 40 days

| Outcome | Count |
| --- | --- |
| Hold | 438 |
| Regular order placed | 177 |
| Weekend trade opened | 109 |
| Refused by the engine's guards | 77 |
| Error | 23 |
| **Total decisions** | **824** |

The 77 refusals are a useful result in themselves: the engine's own limits
correctly rejected requests that exceeded position caps, available shares, or
notional limits, without a human present.

### What this is and is not evidence of

**It is evidence about the engine.** It produced 126 concurrent settlements,
exercised the lock and refusal paths 77 times, and ran a settlement job against
dozens of simultaneously open trades. No human-driven test would have produced
that volume.

**It is not evidence about markets.** A persona deciding to sell NVDA at 14:00
Saturday tells you nothing about Monday's price. Monday does not know who
ordered. Any write-up must state this plainly; it is the single most likely
point of attack in a defence, and the honest answer fully disarms it.

---

## 12. Experiment: the on-chain shadow hedge

For every weekend trade the system builds the on-chain hedge that a
firm-price product would require: it requests a Jupiter quote for the exact
size, has Jupiter assemble a real swap transaction against the project's own
Solana wallet, signs it locally with the real key, simulates it against Solana
mainnet, computes the full fee, and records everything.

**It never sends the transaction.** There is deliberately no function to do so.

This prices the design the proposal rejects. If Yagnum had guaranteed the
weekend price, it would have needed to offset the position on Solana, paying
the spread twice plus gas, and carrying tracking error between token and share.
232 legs have been recorded.

**Why the simulations report failure.** The wallet holds no SOL and no tokens,
so mainnet simulation returns "account not found." That is the honest result
for an empty wallet, not a bug, and the fee arithmetic is still computed
correctly from the assembled transaction.

**A structural point worth making in a write-up.** Hedging a pass-through
design would *create* risk rather than remove it. Because the pass-through
already leaves Yagnum exactly flat, adding an on-chain leg would manufacture a
loss equal to the spread plus gas. The hedge only makes sense under the
firm-price design, which is precisely why its cost is the right way to price
that alternative.

---

## 13. Limitations and threats to validity

A capstone is judged substantially on this section. Be generous with it.

### Construct validity

- **Sandbox money.** Every account is simulated through Alpaca's sandbox. Fills
  may be more generous than a real venue, especially in extended hours. The
  settlement *logic* is exercised honestly; the *fill quality* is not
  representative.
- **The measured sigma may not measure the risk.** This is the central finding
  of Section 10 and is also a limitation of the original method.
- **Simulated traders are not traders.** Order flow is generated by language
  models, so arrival times, sizes, and symbol selection do not reflect real
  demand. The engine load is real; the demand pattern is synthetic.

### Internal validity

- **Parameters are stale.** `research_params.json` was generated 2026-08-31 and
  the results in Section 10 were produced under those six-week-old parameters.
  Some of META's under-reservation may be a regime change rather than a method
  flaw, and refreshing is required to separate the two.
- **Small n per symbol.** META's finding rests on 11 trades and 2 breaches. It
  is suggestive, not conclusive.
- **Survivorship in the token universe.** The token list is fetched live, so
  symbols enter the dataset when Backed lists them. Newly listed tokens have
  null token-sigma and fall back to share-only estimates.

### External validity

- **47 days, one market regime.** Autumn 2026 was not a crisis period. The tail
  behaviour that a reserve exists for is precisely what a short calm window
  fails to observe.
- **26 symbols, all large-cap US.** No small caps, no international.
- **One brokerage, one chain, one aggregator.** Results may not transfer to
  other venues.

### Known gaps in the system

- Securities journals are not enabled in the sandbox, so weekend-sold shares
  are protected by an application-level ledger lock rather than physical
  custody transfer. Production would require the brokerage to enable it.
- No premarket share data on the free feed, which blocks the share side of RQ4.
- The on-chain hedge is modelled, never executed, so its tracking error is
  inferred rather than observed.

---

## 14. Ethics, regulation, and the project's honesty constraints

### Regulatory position

The project does not offer securities, custody assets, or handle real money. It
runs entirely on a brokerage sandbox with simulated cash, and the user interface
says so on every page. That is a deliberate design constraint, not an
incidental limitation.

Two regulatory facts a capstone must state accurately:

1. **xStocks are not offered to US persons** under Backed Finance's terms, and
   Robinhood's stock tokens are likewise unavailable to US persons. Yagnum's
   design works precisely because the customer never holds a token; they hold
   shares in a regulated brokerage account.
2. **Tokenized equities for US retail would require SEC action** that has not
   occurred. Any claim that this system could operate commercially in the US
   today would be wrong.

### Self-imposed constraints

The project holds itself to rules that are recorded as decisions and are worth
stating because they shaped the engineering:

- The brokerage is never deceived. No workaround procedures, no misrepresented
  account data.
- The interface never implies real money.
- The on-chain wallet signs but never sends. Sending is gated behind a separate,
  unmade decision.
- Mistakes are recorded rather than quietly fixed. ADR-028 and ADR-029 document
  a design error and its reversal within one day.

### Use of AI, stated plainly

The implementation was produced by an AI coding agent under the student's
direction. The student set every architectural decision, caught substantive
errors including one conceptual error in the financial design, and set the
quality constraints. Any capstone submission must represent this accurately.
Institutions increasingly ask; the honest account is also the more interesting
one, because directing and correcting an agent in an unfamiliar domain is a
demonstrable skill and the error-catching is evidence of genuine understanding.

---

## 15. Capstone work plan

Ordered by value per unit effort. Items 1 and 2 together constitute a complete
capstone.

### 1. Refresh the parameters and re-run the analysis — half a day

Run the refresh ritual that has not run since 2026-08-31. Then re-compute
Section 10's coverage table under current parameters. This separates "the
method is flawed" from "the parameters were stale," which is the first question
any examiner will ask.

### 2. Re-estimate sigma on the realised quantity — two to three days, the core contribution

Currently sigma is measured on share Friday-to-Monday gaps. The project now has
126 direct observations of the quantity actually at risk: token executable
quote to Monday fill. Re-estimate sigma from those, recompute the reserve each
trade *would* have had, and report coverage under both methods.

**Deliverable:** a table comparing empirical coverage and mean utilisation under
the current method versus the realised-quantity method. If coverage improves
toward 99 percent without a large rise in mean utilisation, that is a genuine
finding and the capstone's result.

### 3. Answer RQ2 properly — one to two days

9,940 spread observations are sitting unanalysed. Test whether spread as a
fraction of midpoint widens in the weekend window, controlling for symbol and
time of day. Plot spread by hour-of-week. This is the most visually compelling
result available and is almost certainly a clean, publishable-looking chart.

### 4. Decompose the gap — two days

Split the realised gap into token-share basis at execution, the share's own
weekend move, and the spread paid. This directly tests the Section 10
hypothesis about why META under-reserves.

### 5. Optional extensions

- **RQ4** using token-only premarket series against the 09:30 open.
- **RQ5** analysis of the 232 recorded hedge legs to price the rejected design.
- **A stress test**: replay the engine against the worst historical weekends in
  the two-year share record and report what the reserve would have done.

### What not to do

Do not build new features. The system is sufficient. A capstone that adds a
sixth cron job and no analysis is weaker than one that adds nothing and answers
a question.

---

## 16. Deliverables and how to present it

### Suggested paper structure

| Section | Source in this document |
| --- | --- |
| Abstract | Section 2 |
| Introduction and problem | Section 3 |
| Related work | Section 5 |
| Research questions | Section 6 |
| Design and mechanism | Section 7 |
| Implementation | Section 8 |
| Methodology | Section 9 |
| Results | Section 10, after the work plan's items 1 to 3 |
| Discussion and limitations | Sections 10 and 13 |
| Ethics and regulatory position | Section 14 |
| Conclusion and future work | Section 15 |

### The one chart to build

Spread as a fraction of midpoint, plotted by hour of week, averaged across
symbols, with the weekend window shaded. If the weekend widening is real it
will be visible at a glance, and it is the single image that makes the project's
premise legible to a non-specialist.

### The demo, five minutes

1. Open the live site and show the weekend trade ticket with its reserve
   arithmetic visible before confirming.
2. Show the weekend trades panel with a settled trade: weekend price, Monday
   price, what came back.
3. Open the database and show the same trade's journal trail, each step
   carrying its brokerage reference.
4. Show a GitHub Actions run of the settlement job firing with nobody present.

The fourth item is the one that lands. A system that runs itself over a weekend
is categorically different from a demo.

### The thirty-second version

"The stock market closes for 48 hours a week, but tokenized versions of the
same shares keep trading. I built a settlement system that lets someone trade
on a Saturday at that live price and get settled at Monday's real price, with a
cash reserve sized from measured volatility covering the gap. It has settled 126
trades automatically. The reserve held 98.4 percent of the time, and the
failures were all one stock, which told me the way we measure volatility is
measuring the wrong thing."

### Anticipated questions

| Question | Answer |
| --- | --- |
| Is this real money? | No. Brokerage sandbox throughout, stated on every page. |
| Didn't Robinhood just do this? | They tokenized stocks. They did not solve settlement to a regulated account, and their product is unavailable to US persons. Section 5. |
| Who wrote the paper? | My father. The implementation, measurement, and results are mine. |
| How much did the AI write? | Nearly all the code, under my direction. I made every design decision and caught the agent's errors, including a conceptual one about the settlement design. |
| Why not just hedge on-chain? | Under pass-through, Yagnum is already flat. Hedging would create a loss, not remove one. Section 12. |
| Is 126 trades enough? | For the pooled coverage figure, marginally. For the per-symbol finding, no, and the write-up says so. |

---

## 17. Reproducibility

From a clean machine, in order:

```
git clone https://github.com/Yagnum/Empirical
cd Empirical/app/api
uv sync
uv run alembic upgrade head
uv run pytest -q            # 172 tests should pass
```

Required environment variables live in a single root `.env`: Alpaca broker
credentials and firm account, Clerk keys, two Neon database URLs, an optional
Jupiter key, a Groq key for the agents, and the Solana wallet public key.

To reproduce the research parameters:

```
uv run python scripts/backfill_history.py --write --days 4
# then execute notebooks/gap-volatility.ipynb
# then refresh app/api/research_params.json from its output
```

To reproduce Section 10's results, query `weekend_trades` for rows where
`settlement_mode = 'market'` and `state` is `settled` or `breached`, and compute
`abs(true_up) / reserve` for utilisation and `abs(true_up) / (qty * p_open)` for
the gap as a fraction of notional.

Live system: `https://yagnum-web.azurewebsites.net`. The free hosting tier
sleeps after 20 idle minutes, so the first page load may take 30 seconds.

---

## 18. Appendix

### The decision record

Twenty-nine numbered architecture decisions are recorded in
`docs/DECISIONS.md`, each with context, the decision, and consequences. The ones
that matter most for a capstone:

| ADR | Decision |
| --- | --- |
| 010 | Money is decimal strings, never floats |
| 014 | Postgres arrives: audit log, idempotency, fills ledger |
| 016 | Measure before building: start the price record first |
| 017 | The ERR is a pass-through; the Monday leg closes premarket |
| 018 | z is measured, not looked up; sigma per symbol, pooled multiplier |
| 019 | The engine: session routing, state machine, dev simulator |
| 020 | Record the spread: two executable quotes per token, every 5 minutes |
| 022 | Ledger lock for custody, because the sandbox cannot journal securities |
| 023 | Settlement runs as an idempotent weekday-morning cron |
| 024 | Overnight orders queue at the broker |
| 025 | On-chain hedge built, signed, simulated, never sent |
| 026 | Simulated traders decide through the real engine |
| 028 | A firm weekend price. **Reverted the same day.** |
| 029 | The paper is pass-through; ADR-028 was a misreading, corrected |

ADR-016 is worth highlighting in a write-up: the decision to start recording
data before building anything is why there is a 47-day dataset at all.

### Documents in the repository

| Document | Covers |
| --- | --- |
| `YAGNUM-EXPLAINED.md` | The concept, the hedge, the formulas, every case worked |
| `SIZING-THE-RESERVE.md` | The statistics, from the bell curve up |
| `JUPITER-FLOW.md` | Mints, decimals, quotes versus prices, the on-chain record |
| `WEEKEND-SIMULATOR.md` | The engine lifecycle with real numbers |
| `SOLANA-GAS-AND-JUPITER.md` | Who pays gas, rent, spread, how Jupiter earns |
| `SHADOW-HEDGE.md` | The on-chain hedge experiment |
| `SIM-USERS.md` | The eight personas and what they evidence |
| `TRADING-FLOW.md`, `ALPACA-FUNDING.md` | Brokerage mechanics |
| `ARCHITECTURE.md`, `PRODUCTION.md`, `AZURE-DEPLOY.md` | Structure, deployment |
| `PROJECT-TOUR.md` | The whole project, narrated in order |
| `DECISIONS.md` | All 29 decisions |

### Open questions as of 2026-10-13

- The parameter refresh has not run since 2026-08-31.
- Whether to fund the Solana wallet and send real swaps is undecided, and is a
  family decision rather than a technical one.
- No custom domain, so the Clerk authentication runs in development mode and
  shows a development badge.
- RQ2 data is complete and unanalysed. RQ4 is blocked on premarket data.
