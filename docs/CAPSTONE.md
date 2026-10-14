# Project Yagnum: Capstone Reference

Everything needed to write, defend, or extend a capstone on Project Yagnum, in
one document. First compiled 2026-10-13 from the thirteen working documents in
`docs/`. **Revised the same day** with the first full research pass:

- The spread question (RQ2) answered.
- The weekend gap split into its parts.
- Five ways of estimating sigma compared out of sample.
- Recent outside developments verified from their sources.
- A plan for the data to collect over the next weeks.

**Read this first if you are new to the project.** Everything here is either
drawn from the project's own documents, measured from its database, or cited to
a named outside source. Where a claim is a hypothesis rather than a result, it
says so. Where an analysis is still running, it says that too.

---

## 1. What this document is, and what is already true

Project Yagnum is a **working, deployed, continuously running system**, not a
proposal. As of 2026-10-13 it has been collecting data for 47 days and
settling trades automatically for 5 weeks.

The capstone is therefore not "build Yagnum." It is **"use Yagnum to answer a
question nobody has answered."** The system is the instrument; the capstone is
the measurement.

| Already done | What the capstone adds |
| --- | --- |
| The settlement engine, built and running | The analysis of what it recorded |
| 23,260 price observations, still accumulating | The research questions those observations answer |
| 126 weekend trades settled at real market prices | Whether the reserve worked, and *why* it failed where it did |
| A first research pass: spreads, gap decomposition, sigma methods | The argument, the limits, and the next data to collect |

**What changed in this revision.** The first version of this document ended on
a hypothesis: the reserve failed for META because sigma ignored the
token-versus-share basis and the spread. The research pass **rejected that
hypothesis**:

- Basis and spread together explain only about 2 to 3 percent of the gap.
- The real second cause was one nobody had suspected: **the engine settles
  late**. Only about half of the weekend trades filled in the first Monday
  session, and the late part of the fill explains about 46 percent of the
  gap's variance.

That is a better finding than the one predicted, and Section 10 sets it out.

**An important attribution note.** The underlying academic proposal, which
describes the settlement design and its formulas, was written by Yagnesh's
father. The implementation, the measurement infrastructure, the empirical
results, and this document are the student project. Any capstone write-up must
keep that line visible: the theory is cited, the measurement is original.

### Key numbers at a glance

| Number | Meaning |
| --- | --- |
| 48 h | Weekend window with no regulated venue |
| 126 / 124 | Weekend trades settled / covered by the reserve (98.4%, target 99%) |
| 2 | Breaches, both META buys |
| 3.7742 | Measured z; the live trades' 99th percentile to the next open is 3.80 |
| 0.337% vs 0.343% | Weekend vs regular median spread: no widening (p = 0.50) |
| $1.68 | One-way spread cost on a $1,000 weekend trade |
| 52% / 46% / 2–3% | Gap variance from share move / settlement timing / basis + spread |
| 58 of 120 | Trades that filled in the first Monday session |
| 9.8% → 10.5% | Mean reserve, current vs the proposed max(stored, realised) floor |

### What is original here

1. A running settlement engine that reconciles weekend token prices to
   regulated fills, with every cash movement a real brokerage journal.
2. A continuous paired token-and-share record with executable quotes, started
   before the engine was built.
3. A measured null result on weekend spreads, with a tight interval.
4. A decomposition of realised reserve risk into four parts. It found that
   the system's own settlement timing was almost half of the risk.

---

## 2. Abstract and thesis

**Abstract.** United States stock markets are closed for roughly 48 hours every
weekend, but tokenized copies of real shares trade continuously on Solana. A
price therefore exists when the market does not. This project builds and
operates a settlement framework that lets a brokerage customer act on that
weekend price safely:

- The trade executes provisionally against a live token quote.
- A cash reserve sized from measured volatility is held until the market reopens.
- The real shares settle at the first regulated price, and the reserve comes
  back adjusted for the move.

Over 47 days the system recorded 23,260 paired token-and-share price
observations and settled 126 weekend trades automatically. The reserve covered
the realised gap in 124 of them, 98.4 percent against a 99 percent target.

Three analyses explain the result:

1. **Spreads do not widen at the weekend.** Across 22 symbols and 2,660
   symbol-days, the weekend spread is statistically the same as the
   regular-hours spread (−3.6 percent, p = 0.50). The data rule out a weekend
   widening larger than about 7 percent.
2. **Basis and spread are not the cause of the misses.** Decomposing each
   trade's gap shows that the token-versus-share basis and the spread
   together explain about 2 to 3 percent of its variance.
3. **The rest is the share's own weekend move (52 percent) and settlement
   timing (46 percent).** The engine routinely filled Monday orders hours or
   sessions after the open. Measured against the quantity sigma was designed
   for, Friday to the Monday open, the 99th percentile of |gap|/σ is 3.80,
   almost exactly the measured multiplier of 3.7742.

**Thesis in one sentence.** A measured, customer-collateralised cash reserve
can bridge weekend token prices to regulated Monday settlement. Its statistics
hold, and its main weakness is operational: **the reserve is sized for a
settlement at the Monday open, so settlement must actually happen there.**

---

## 3. The problem

**ELI5.** The stock market is a shop that closes Friday evening and opens
Monday morning. A second shop next door sells receipts for the same goods and
never closes. On Saturday you can see what a receipt costs, but you cannot get
the actual good until Monday, and by Monday the price has moved. Someone has to
cover that difference.

**In full.** United States equity markets trade 9:30 to 16:00 Eastern on
weekdays. Alpaca, the brokerage this project uses, extends that to roughly 24
hours over 5 days. The genuinely dead window is the weekend: Friday 20:00 to
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
the project exists to manage. Across 126 real settlements, the gap averaged
2.83 percent of trade value and reached 16.12 percent at its worst.

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
| **Spread** | Ask minus bid, as a percentage of the midpoint. **Half-spread** is the one-way cost of trading at the quote rather than the mid. |
| **Basis** | How far the token's price sits from the real share's last price. |
| **Settlement lag** | How long after the Monday open the real shares actually filled. New in this revision. |
| **Fee floor** | A spread that sits exactly at a pool's fee, because the pool's fee, not market risk, sets the minimum price of trading. |
| **Gas** | The fee paid to a blockchain's validators to include a transaction. |
| **Rent** | A refundable deposit Solana requires to keep a token account open, about 0.002 SOL. |
| **TSV** | Tokenized Securities Venue: the new class of SEC-exempted on-chain venue (Section 5). |

---

## 5. Related work and the competitive landscape

### The three layers

Any tokenized-equity system has three separable layers. Confusing them is the
most common error in discussing this space.

1. **Issuance.** Who mints a token against a custodied share.
2. **Venue.** Where that token, or the share, trades.
3. **Settlement.** How a regulated brokerage customer gets an off-hours price
   reconciled to a regulated one.

Yagnum operates **only at layer 3**. It issues nothing and runs no venue.

### What changed in 2026: the weekend is being attacked from three sides

Between June and October 2026 the 48-hour weekend gap stopped being a niche
problem. Each item below was checked against its source. Where only secondary
coverage was available, that is said.

1. **A regulated weekend venue for real shares.** On 2026-09-30, Bruce Markets
   announced continuous weekend trading of US equities on its alternative
   trading system. It runs on Nasdaq technology with Apex Clearing, and
   Robinhood and PEAK6 made strategic investments. It is subject to regulatory
   review, and the announcement gives no weekend hours, settlement details, or
   price-discovery details.
2. **Round-the-clock issuance.** Since 2026-06-25, Ondo Global Markets mints
   and redeems six tokens over weekends and holidays at "the current
   prevailing price". The six are SPYon, QQQon, NVDAon, TSLAon, GOOGLon and
   CRCLon. The pricing and hedging method is not disclosed. The xStocks this
   project records have no weekend mint or redeem.
3. **SEC-sanctioned on-chain venues.** On 2026-09-17 the SEC issued an
   Innovation Exemption (Release 2026-90) for **Tokenized Securities Venues**.
   These may trade tokenized NMS stock in permissioned AMM pools, including
   24/7.
   - **Tier 1:** up to 75 large-cap symbols, each capped at 0.25 percent of
     prior-month average daily volume.
   - **Tier 2:** 250 symbols at 2.5 percent.
   - **Conditions:** allowlisted wallets only, the same shareholder rights as
     the share, and a halt whenever the primary listing halts.
   - **Public data:** USD transaction data must be published within 10
     minutes.
   - **Expiry:** the exemption expires 2031-09-17.

Alongside these:

- **Nasdaq.** It received SEC approval (2026-03-18, secondary sources) to
  trade tokenized securities in the same order book, with tokenized DTC
  settlement chosen at order entry.
- **DTCC.** Its tokenization service had production trades in July 2026 and a
  commercial launch targeted for October 2026 (secondary sources).
- **Kraken and Backed.** Kraken agreed to acquire Backed, the xStocks issuer,
  in December 2025. Closing is reported only by secondary sources.
  - xStocks passed 100 listings in March 2026.
  - This project records 26 of them.

### What this means for the project

The earlier positioning, "US persons cannot hold tokens, so Yagnum's customer
is untouched", **is weaker than it was**. Permissioned TSVs can serve US
participants. A regulated weekend ATS would give a weekend price for the real
share itself.

What survives, and in fact gets stronger, is the ERR's actual job:
**reconciling an off-hours execution price to a later settlement price, at a
measured risk.** None of the three developments removes that job:

- A Bruce weekend print still settles on business days.
- An Ondo weekend mint at "the prevailing price" still has to be hedged
  against Monday.
- A TSV is capped at a fraction of daily volume and halts with the primary
  market.

The ERR is therefore best described as a **venue-agnostic reconciliation
layer**. The weekend price can come from a Solana pool, a weekend ATS, or a
TSV. The reserve maths does not change. Only the source of `p_open` does.

The project's other durable asset is **its measured dataset**. Every one of
these venues will need a benchmark for weekend spreads, basis and gap risk, and
this project has been measuring them since August.

### Who does what

| Party | Issuance | Venue | Settlement to a regulated account | US persons |
| --- | --- | --- | --- | --- |
| **Backed Finance (xStocks)** | Yes | No, trades on Solana venues | No | Not offered |
| **Ondo Global Markets** | Yes, with weekend mint and redeem | No | No | Not offered |
| **Jupiter** | No | Yes, as an aggregator | No | Permissionless |
| **Robinhood Chain** | Yes | Yes, its own L2 plus DEXs | No, the token is the product | Not offered |
| **Bruce Markets** (announced) | No | Weekend ATS for real shares | Business-day settlement | Yes |
| **TSVs** (exempted, none live yet) | Third-party or issuer | Permissioned on-chain pools | Not specified | Allowlisted participants |
| **Alpaca** | No | Regulated brokerage, 24/5 | Weekdays only | Yes |
| **Yagnum** | No | No | **Yes, this is the contribution** | Yes, by design |

### Robinhood Chain, the closest comparison

In July 2026 Robinhood launched its own Ethereum layer-2 with more than 90
tokenized stocks trading continuously.

**How Robinhood handles the weekend.** It does not solve the gap; it
reallocates it. The token keeps trading, but nobody can create or redeem shares
while the custodian is shut, so Robinhood or its market makers carry the
inventory risk. The customer ends the weekend holding a token whose price may
diverge from Monday's open. The cost is embedded in the spread. Section 10 adds
a measured nuance: on Solana, at $1,000 size, that spread did *not* visibly
widen at the weekend.

Robinhood is also now an investor in Bruce's weekend venue for the real
shares. The largest US retail broker is backing both answers to the weekend at
once: the token and the regulated weekend print.

### Academic and industry context

- **Settlement risk and the cost of immediacy.** Demsetz framed the bid-ask
  spread as the price of immediacy. The market-microstructure literature on
  **adverse selection** adds that the traders most eager to transact are
  disproportionately those acting on information the counterparty lacks. That
  is why the proposal rejects quoting a firm weekend price. These are named
  from domain knowledge; verify and cite the originals.
- **Cong, Landsman, Rabetti, Zhang and Zhao, "Tokenized Stocks"** (SSRN
  5937314, December 2025, revised January 2026). The abstract was read through
  a search listing because the SSRN page refused access. It reports that:
  - tokens absorb weekend news in real time;
  - they track closely in regular hours and deviate modestly when the market
    is closed;
  - weekend moves anticipate Monday's open;
  - off-hours trading *redistributes* the Monday return rather than
    amplifying it.

  This is the closest academic work. RQ4 here should be framed as a
  replication and extension, not a first discovery.
- **Binance Research,** as reported 2026-09-22, using data through 2026-07-28:
  - Weekend on-chain prices captured a median 92 percent of Monday's gap.
  - Direction accuracy rose with the size of the gap: 81 percent below 0.5
    percent, up to 97 percent for 1–3 percent gaps.
  - CoinMarketCap Research separately reported weekend DEX tokenized-equity
    activity down about 70 to 90 percent.
  - Many on-chain oracles hold Friday's close all weekend.

  These are industry claims, not peer-reviewed. They give the project concrete
  numbers to test against its own record.

---

## 6. Research questions

| RQ | Question | Status |
| --- | --- | --- |
| RQ1 | How large is the weekend gap, and is it predictable? | **Answered in part** (Section 10) |
| RQ2 | Does the spread widen when the regulated market is closed? | **Answered: no** (Section 10) |
| RQ3 | Does a reserve sized at zσ cover the realised gap at the claimed confidence? | **Answered, with a cause** (Section 10) |
| RQ4 | Does the token lead the share into the Monday open? | Analysis running; data partly blocked |
| RQ5 | What would a firm-price product have cost? | Analysis running |
| RQ6 | How much of the risk comes from *when* settlement happens? | **New, answered in part** (Section 10) |

**RQ1.** The distribution of `p_close − p_open` across recorded weekends, per
symbol and pooled.

**RQ2.** Two executable quotes per token, at about $1,000 each side, since
2026-09-01. Is spread as a fraction of midpoint wider at the weekend than in
regular hours, controlling for symbol and time?

**RQ3.** Compare realised |true-up| against the reserve held, per trade. Then
ask *why* it missed where it missed.

**RQ4.** The first recorded weekend showed the token pricing Monday's 0.77
percent gap by 04:05 Eastern, five and a half hours before the market
confirmed it. If that generalises, the token is a **price-discovery venue**,
not merely a mirror. Cong et al. and Binance Research both point the same way.
The share side is partly blocked because the free data feed prints few
premarket trades. Section 16 plans the fix.

**RQ5.** Every weekend trade records a shadow on-chain hedge: what it would
have cost in spread and gas to guarantee the weekend price and offset it on
Solana. 232 legs recorded. This is the empirical version of the
adverse-selection argument.

**RQ6.** Added in this revision because the decomposition found it. The
reserve is sized for a move from Friday to the Monday *open*. The engine's
actual exposure runs to the Monday *fill*. How far apart are those, and what
does the difference cost?

---

## 7. The ERR mechanism, with worked examples

### The design in one paragraph

The trader executes at the weekend price and receives cash (on a sell) or
shares (on a buy) immediately. A reserve is journaled from their account into
escrow. At the next regulated session the real shares trade, and the reserve is
returned **adjusted by the realised gap**. The trader therefore ends at
Monday's price, which is the price a regulated market actually produced, but
they had their cash or their position two days early. Yagnum ends flat on every
trade by design.

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

### Why the mechanism is venue-agnostic

Nothing in the three formulas names Solana. `p_open` is "the best executable
off-hours price"; `p_close` is "the regulated settlement price". The engine
uses a Jupiter quote today. The same reserve and the same true-up work if
`p_open` comes from a weekend ATS print, a TSV pool, or an issuer's weekend
mint price. Only sigma changes, because sigma must be measured on whichever
venue supplies `p_open`.

This is the reason the 2026 developments in Section 5 extend the project
rather than replace it.

### Current parameters

Measured 2026-08-31 from 2,089 market weekends and 407 token-weekends. A
refresh is running at the time of writing; Section 15 records its status.

| Parameter | Value | Source |
| --- | --- | --- |
| `z`, pooled | 3.7742 | Empirical 99th percentile of \|gap\|/σ across all token-weekends |
| `σ`, pooled | 0.0242 | Across all symbols |
| `σ`, per symbol | 0.0086 (MCD) to 0.0477 (MSTR) | max(2-year share gaps, token gaps) |

**Why z is 3.7742 and not 2.326.** A statistics course gives 2.326 for a
one-sided 99 percent interval under a normal distribution. The measured value
is 62 percent larger because real weekend gaps have **fatter tails** than the
normal curve. Using the textbook number would under-reserve every trade.

The research pass gives this an independent check. On the live trades,
measured from the weekend quote to the next open, the 99th percentile of
|gap|/σ came out at **3.80**.

### Worked example, a real settled trade

Trade 46, a simulated trader's sell, settled 2026-09-08. The arithmetic was
checked against the database.

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

Trade 43: 30 AAPL bought at $321.9263, filled Monday at $316.26. The buy's
true-up reverses sign, so the trader receives **more** than their reserve back:
$619.66 + $169.99 = $789.65. The real shares cost less than the weekend price,
and the difference is returned.

A consequence the decomposition makes visible: because the trader always ends
at `p_close`, **the spread they paid at the weekend is effectively refunded**.
A buyer who paid the ask gets the difference back through the true-up. Across
the trades, the spread component averaged −0.19 percent *in the trader's
favour*.

### The design that was rejected, and why

The alternative is to quote a firm weekend price and keep the gap. The proposal
rejects it on **adverse selection** grounds:

- Weekend traders are disproportionately those reacting to weekend news.
- Their flow pushes the gap systematically against whoever quotes the firm
  price.
- That party cannot hedge, because the regulated market is shut.

A fee cannot fix it, because informed traders pay the fee only when it is worth
it to them.

The project briefly implemented the rejected design by mistake on 2026-09-07
and reverted it the same day. The error and its correction are recorded as
ADR-028 and ADR-029.

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
cached daily. Early-close half days, such as 2026-11-27, are a known gap; a fix
is in progress (Section 16).

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
   against the broker's records*, not a promise made by our own code.
2. **Money is never a floating-point number.** Every monetary value is a
   decimal string at system boundaries and a `Decimal` internally.

### Unattended automation, as scheduled and as measured

| Job | Scheduled | What actually happened |
| --- | --- | --- |
| `sample-prices` | Every 5 minutes | **About 6 runs a day** after 2026-09-04. 534 runs in 6 weeks. |
| `sim-users` | Hourly | One group of AI personas decides and trades |
| `settle-weekend` | Every 10 minutes, weekday mornings | **Only 58 of 120 weekend trades filled in the first Monday session** |
| `deploy-azure` | On push to main | Rebuilds and redeploys both apps |

GitHub's scheduled workflows are best-effort. They are delayed or skipped
under load, and the measured cadence is far sparser than the schedule. This is
recorded here because both rows matter to the results: the first limits the
time resolution of every price analysis, and the second turned out to be the
largest single source of reserve risk (Section 10).

---

## 9. Methodology

### The data pipeline

On each run, for each of 26 tokens, the sampler records:

- The token's USD price from Jupiter.
- Its liquidity.
- The real share's last trade from Alpaca.
- Whether the market was open.
- Two executable swap quotes of about $1,000, one in each direction, giving
  the bid, the ask, and the price impact of each.

**Why executable quotes rather than the last traded price.** The last swap
price tells you what somebody else already paid. A quote for *your* size tells
you what you would actually get. The research pass measured how much this
matters:

- The last swap price sat **outside** the executable bid and ask in **61.6
  percent** of observations.
- In 55.1 percent it was below the bid.
- Its median distance from the midpoint was 0.29 percent, and the 95th
  percentile 7.97 percent.

A reserve or a chart built on the last swap price would be built on a price
nobody could trade at.

### Data cleaning for the spread analysis

| Step | Rows |
| --- | --- |
| Rows since the first spread run (2026-09-01) | 10,680 |
| Quote failed, usually a Jupiter rate limit (429) | −740 (6.9%) |
| Ask below bid: the two quotes are 1–2 s apart, so this is timing noise | −17 |
| Broken routes: spread above 20%, or mid more than 20% from the last price | −11 |
| **Kept** | **9,912** (92.8%) |

Session windows were computed from the Eastern clock, with Labor Day treated
as weekend. They agree 100 percent with Alpaca's own `market_open` flag.

### How the spread was tested

Samples taken minutes apart are not independent, and sampling density varied
twentyfold over the period. Testing raw rows therefore gives a misleading
answer: it found the weekend 17 percent narrower, an artefact of over-weighting
a densely sampled first week.

The analysis instead takes **one median per symbol, per Eastern date, per
window**. That gives 2,660 units. It then uses three tests:

1. A per-symbol Mann-Whitney test, weekend days against regular days, with a
   Holm correction for 22 symbols.
2. A Wilcoxon signed-rank test and a sign test on the 22 weekend-to-regular
   ratios.
3. A regression of log spread on window dummies, with symbol fixed effects
   and standard errors clustered by date (43 clusters).

### How the gap was decomposed

For each of the 121 weekend trades, the log gap from the trade price to the
fill splits **exactly** into four parts. The identity holds to within 3 × 10⁻¹⁶.

| Part | From | To |
| --- | --- | --- |
| Spread | Trade price | Token midpoint |
| Basis | Token midpoint | Share's last Friday print |
| Share weekend move | Share's last Friday print | Next regular open |
| Settlement timing | Next regular open | Actual fill |

Each part's contribution is reported as its share of E[gap²].

The 121 trades are the 126 market settlements minus five weekday test trades.
They contain both breaches.

### How the sigma methods were compared

Out of sample, with an expanding window: train on weekends 1 to *k*, test on
weekend *k*+1. That gives 82 test trades over weekends 2 to 6. A
leave-one-weekend-out version was run as a check.

Five sigma rules were compared, all at z = 3.7742:

- The stored value.
- Realised sigma per symbol.
- Stored shrunk toward the realised value.
- max(stored, realised).
- Pooled realised.

Each was tested against two targets: the gap **as settled**, and the gap **to
the next open**.

In-sample results are not quoted. Fitting and testing on the same trades makes
every adaptive method look perfect.

### The statistics used, one line each

| Tool | What it answers, simply |
| --- | --- |
| Median of daily medians | One vote per symbol per day, so a busy sampling day cannot shout louder |
| Mann-Whitney | Are weekend days' spreads generally larger than weekday ones, without assuming a bell curve? |
| Holm correction | With 22 tests, some look "significant" by luck. Holm raises the bar to stop that. |
| Wilcoxon and sign tests | Across the 22 symbols, do the weekend/weekday ratios lean one way? |
| Fixed effects | Compare each symbol with itself, so SPY's tight spread never hides in an average with INTC's wide one |
| Clustered standard errors | Samples on the same day move together. This stops them being counted as independent evidence. |
| Out-of-sample, expanding window | Fit only on past weekends, test on the next. This is the only honest way to judge a forecast. |
| Kupiec POF test | Is the number of misses consistent with a 1% target, or too many to be luck? |
| Share of E[gap²] | How much of the gap's total size each part explains. The four shares add to 100%. |

### How sigma and z are measured in production

Two independent sigma estimates per symbol; the engine uses the larger:

1. `sigma_market_2y`: the standard deviation of real Friday-close to
   Monday-open gaps over about two years of daily bars.
2. `sigma_token`: the standard deviation of token Sunday-23:00 to Monday-09:30
   gaps from historical candles.

z is pooled across all symbols. For every recorded token-weekend, compute
|gap|/σ, then take the empirical 99th percentile, which is 3.7742. Pooling
avoids fitting z to a handful of observations per symbol. It is testable,
because |gap|/σ should be roughly the same for every symbol if sigma is doing
its job.

### The refresh ritual

After each recorded weekend:

1. Top up the history tables.
2. Re-execute the volatility notebook.
3. Regenerate `research_params.json`.

The file carries a `generated_at` date so staleness is always visible. The
ritual had not run between 2026-08-31 and this revision.

---

## 10. Results

All figures measured from the project database on 2026-10-13. Scripts are in
`notebooks/analysis/`, figures in `notebooks/figures/`.

### The dataset

| Measure | Value |
| --- | --- |
| Price observations | 23,260 |
| Distinct tokens tracked | 26 |
| Collection window | 2026-08-28 to 2026-10-14 |
| Observations with a clean executable spread | 9,912 |
| Weekend trades settled at real market prices | 126 (121 weekend-opened) |
| Weekends with settled trades | 6 |
| Agent decisions recorded | 824, from 8 personas, over 40 days |
| On-chain hedge legs modelled | 232 |

### RQ1: how large is the weekend gap?

Across 126 market-settled trades, the realised gap was a mean 2.83 percent of
notional, and at most 16.12 percent.

| Symbol | Trades | Mean \|gap\| | Max \|gap\| |
| --- | --- | --- | --- |
| MSTR | 14 | 5.66% | 16.12% |
| META | 11 | 6.02% | 10.99% |
| COIN | 6 | 6.01% | 10.18% |
| HOOD | 7 | 4.16% | 8.92% |
| TSLA | 14 | 3.10% | 5.45% |
| NVDA | 27 | 1.81% | 3.72% |

Crypto-correlated equities (MSTR, COIN) and high-beta names gap hardest.
The decomposition later in this section shows that part of these figures is
settlement timing, not weekend movement.

### RQ2: spreads do not widen at the weekend

**The hypothesis was that spreads widen while the regulated market is shut.
The data reject it for every symbol tested.**

Median of the 22 symbols' median daily spreads, by window:

| Window | Median spread |
| --- | --- |
| Regular | 0.343% |
| Premarket | 0.346% |
| After hours | 0.349% |
| Overnight | 0.332% |
| **Weekend** | **0.337%** |

The tests agree:

- **Per symbol:** 0 of 22 symbols are significantly different after Holm
  correction. Six are wider at the weekend, three tied, thirteen narrower. The
  median weekend-to-regular ratio is 0.977.
- **Across symbols:** Wilcoxon p = 0.12; sign test p = 0.17.
- **Regression:** the weekend coefficient is −3.6 percent versus regular hours
  (SE 0.054, p = 0.50). The 95 percent confidence interval is about −13 to +7
  percent. The other off-hours windows sit within ±2.2 percent.
- **Robustness:**
  - Keeping the negative spreads: −3.8 percent, p = 0.48.
  - Restricting to the even-cadence period from 2026-09-05: −0.7 percent, p = 0.89.

**What a trader pays.** Half the spread, the one-way cost from the midpoint, is
about **$1.68 on a $1,000 weekend trade** and $1.71 in regular hours. That is
small beside a mean weekend gap of 2.83 percent. For the most liquid names
(SPY, QQQ, NVDA, TSLA, MSTR) the weekend half-spread is under 2 percent of even
a 3 percent reserve.

Per-symbol median spreads range from SPYx at 0.025 percent to INTCx at 2.60
percent. Across symbols, spread and liquidity are strongly negatively
correlated (Spearman ρ = −0.87). Weekend liquidity was not lower than weekday
liquidity: the median within-symbol ratio is 0.98.

**Why the spread does not move.** Three observations explain it:

1. **Many spreads sit exactly on a pool's fee.**
   - 53 percent of QQQx quotes are exactly 0.060 percent.
   - 38 percent of MSTRx quotes are exactly 0.100 percent.

   A spread fixed by the fee cannot reprice weekend risk. The risk has to show
   up somewhere else, and it does: in *where* the price sits.
2. **The token drifts away from the share at the weekend.**
   - The median weekend drift from the share's last print is 0.55 percent, with
     a 95th percentile of 8.6 percent.
   - In regular hours the basis is a median 0.24 percent.
   - Weekend drift exceeds regular-hours basis for 21 of 24 symbols.
3. **Liquidity is growing faster than any weekend effect.** The weekly median
   spread fell steadily from 0.48 percent (week of 2026-08-31) to 0.19 percent
   (week of 2026-10-12).

**How this relates to outside claims.** CoinMarketCap Research reports weekend
DEX activity down 70 to 90 percent. That is consistent with this result:
activity can fall while a fee-floored quote at $1,000 does not move. The test
says nothing about depth at $10,000 or more; Section 16 adds that measurement.

**For the write-up.** A null result with a tight confidence interval is a real
finding. It means the weekend cost is not *paid* in the spread. It is carried
as price risk, which is exactly what a reserve exists to absorb. It also
corrects the earlier description of Robinhood's model, which assumed the cost
was in a widening spread.

Figures:

- `rq2_spread_hour_of_week.png`: flat through the weekend, no step at Friday
  20:00.
- `rq2_spread_ratio_by_symbol.png`: the 22 ratios, none significant.

### RQ3: did the reserve hold?

| Measure | Value |
| --- | --- |
| Market-mode settlements | 126 |
| Reserve covered the gap | 124 |
| **Empirical coverage** | **98.4%** |
| Design target | 99% |
| Mean reserve utilisation | 31.5% |
| Maximum reserve utilisation | 181.9% |

Both breaches were META buys, on 2026-09-16 and 2026-09-22. META's reserve was
1.60 percent sigma times 3.7742, or **6.04 percent of notional**. Its *mean*
realised gap was 6.02 percent. By contrast NVDA's reserve covers its worst
observed weekend about three times over.

| Symbol | Trades | Mean utilisation | Max utilisation |
| --- | --- | --- | --- |
| **META** | 11 | **99.7%** | **181.9%** |
| MSTR | 14 | 31.5% | 89.5% |
| COIN | 6 | 42.7% | 72.3% |
| SPY | 18 | 20.8% | 68.2% |
| TSLA | 14 | 31.5% | 55.3% |
| NVDA | 27 | 17.9% | 36.7% |

### Why it missed: the gap decomposed

The first version of this document guessed that sigma missed the basis and the
spread. **The decomposition rejects that guess.**

| Part | Mean | Std | Mean \|·\| | Share of E[gap²] |
| --- | --- | --- | --- | --- |
| Spread | −0.01% | 0.34% | 0.21% | **0.7%** |
| Basis | −0.49% | 0.80% | 0.68% | **1.7%** |
| Share weekend move | +0.81% | 2.75% | 2.01% | **52.0%** |
| **Settlement timing** | +0.68% | 2.49% | 1.36% | **45.6%** |
| Total (n = 120) | +0.99% | 3.95% | 2.90% | 100% |

At the level of (symbol, weekend) clusters, n = 51, the order is the same but
sharper:

| Part | Share |
| --- | --- |
| Settlement timing | 57.8% |
| Share weekend move | 38.5% |
| Basis | 3.4% |
| Spread | 0.4% |

**Settlement timing is the surprise.** The engine is meant to settle at the
Monday open. Measured:

- **Only 58 of 120 trades filled in the first session.**
- The mean lag was **2.5 sessions**, and the longest 25.
- Even same-day fills happened at roughly 11:50 to 14:50 Eastern, not 09:30.

Every hour of delay exposes the trade to price movement the reserve was never
sized for. The cause of the delay is not yet diagnosed. Two plausible
contributors:

- The settlement cron's best-effort timing (Section 8).
- Orders that wait on conditions in the settlement job.

**The basis is systematic, but small.** The token traded on average about 0.5
percent *above* the share's last Friday print at the weekend. SPY is the
cleanest case, with a mean of −0.65 percent and a standard deviation of only
0.17 percent. It is real and worth reporting, but it is too small to matter
for the reserve.

Figure: `gap_decomposition.png`.

### The META story, trade by trade

**The weekend of 2026-09-19** covers trades 67, 68, 72 and 83, with a total
gap of about +10.4 percent:

| Part | Contribution |
| --- | --- |
| The share's own weekend move | **+6.45%** (666.74 → 711.17 at the open), a 4.0σ event on META's stored σ |
| Late fills, at 13:45 Eastern or later | **+4.4 to +5.1%** |
| Basis, which *helped* | −0.84% |
| Spread | about ±0.3% |

**Trade 20, the weekend of 2026-09-05.** Total gap +8.85 percent. The share's
weekend move was −0.22 percent. The settlement-timing part was **+9.60
percent**, from a fill six sessions late.

**So META's failures came from two things:** one genuine tail event in the
share, and late fills on top of it. META's stored sigma of 1.60 percent also
looks low for its recent regime: its realised share-only RMS over these 5
weekends is about 3.7 to 4.4 percent.

### Does z hold? The statistic measured against what it was built for

| Gap measured | Where z = 3.7742 falls | 99th pct of \|gap\|/σ | RMS of \|gap\|/σ |
| --- | --- | --- | --- |
| As settled (quote → actual fill) | 95.9th percentile | 6.82 | 1.79 |
| **Next open (quote → Monday open)** | 97.5th percentile | **3.80** | **1.19** |
| Share only (Friday → Monday open) | 96.7th percentile | 4.16 | 1.19 |

Against the next open, the quantity the reserve is designed for, the 99th
percentile is 3.80, a near match for the measured 3.7742. **The statistics hold;
the settlement timing does not.**

### Comparing sigma methods, out of sample

Gap to the **next open**, which is what the reserve is meant to cover:

| Method | Coverage | Breaches | Mean reserve, % of notional |
| --- | --- | --- | --- |
| Stored (current) | 96.3% (3 misses, all META 09-19, by about 0.1 pp) | 0 | 9.8% |
| Realised per symbol | 98.8% | 0 | 9.5% |
| Shrunk toward realised | 100% | 0 | 10.2% |
| **max(stored, realised)** | **100%** | **0** | **10.5%** |
| Pooled realised | 96.3% | 1 | 10.2% |

Gap **as settled**, including the late fills:

| Method | Coverage | Breaches | Mean reserve, % of notional |
| --- | --- | --- | --- |
| Stored (current) | 95.1% (p = 0.009 against 1%) | 1 | 9.8% |
| Realised per symbol | 100% | 0 | 14.7% |
| max(stored, realised) | 100% | 0 | 15.2% |
| Pooled realised | 98.8% | 1 | 17.8% |

These tables give three conclusions:

1. **If settlement happened at the open,** the current reserve would already
   be close to target. A modest floor from recent data, max(stored, realised),
   reaches full coverage. The mean reserve goes from 9.8 to 10.5 percent of
   notional.
2. **Covering the late fills with sigma** would push reserves to 15 to 18
   percent of notional. That would make every trader pay for an operational
   defect.
3. **The comparison rests on one weekend.** Every miss by the stored method
   comes from META on 2026-09-19, and with 82 test trades no coverage figure
   except one is statistically distinguishable from 99 percent. "Realised per
   symbol" covered that weekend only because its training data happened to
   include trade 20's late fill. That is luck, not evidence that the method is
   better.

Figure: `sigma_methods_coverage.png`.

### What the results recommend, in order

1. **Fix settlement timing first.** Fill at or near 09:30 on the next session.
   This is an engineering fix to a measured problem, and it is the project
   owner's decision how to do it. If prompt fills are not possible, the honest
   alternative is to size for the actual horizon, roughly σ·√(1 + expected lag
   in sessions).
2. **Keep sigma on the share's weekend move, refresh it, and add a recent-data
   floor:** max(stored, realised next-open RMS).
3. **Do not move sigma onto the as-settled gap.** That bakes an operational
   defect into every customer's reserve.

### RQ4 and RQ5

The token-lead analysis and the hedge-cost analysis are running at the time of
this revision. Their results will be added here once they are checked. Two
earlier observations stand:

- **Token as early price discovery.** On the first fully recorded weekend, the
  token had priced Monday's +0.77 percent open by 04:05 Eastern. That is one
  observation, not a result.
- **Gas for a modelled on-chain hedge.** Mean $0.1887 per leg, range $0.1449
  to $0.3063, across 232 legs. The largest part is the one-time refundable
  token-account rent, not the transaction fee.

### Engine correctness

Settlement arithmetic was checked by hand against the database for both a sell
and a buy. It matched to the cent.

---

## 11. Experiment: the simulated-trader population

### Design

Eight language-model personas, each with a distinct trading style, its own
funded brokerage sandbox account, and a watchlist. Every hour one of two groups
takes a turn.

Each persona receives a briefing containing:

- The time and session window.
- Its cash and positions, and its open weekend trades.
- For each watched symbol: the token price, recent moves, the executable
  spread, and that symbol's reserve percentage.

It replies with a single JSON intent: buy, sell, or hold. The intent passes
through **exactly the same code path a human order takes**.

| Persona | Style |
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

The 77 refusals are a useful result: the engine's own limits correctly rejected
requests that exceeded position caps, available shares, or notional limits,
without a human present. A behavioural analysis of the decisions is running
(Section 16).

### What this is and is not evidence of

**It is evidence about the engine.** The population produced 126 settlements,
exercised the lock and refusal paths 77 times, and ran settlement against
dozens of simultaneously open trades.

**It is not evidence about markets.** A persona deciding to sell NVDA at 14:00
Saturday tells you nothing about Monday's price.

**Personas are not people.** The sim traders choose buy or sell roughly at
random relative to the coming move. That is why one-sided breach counts are
about half the two-sided counts. Real weekend traders, if the adverse-selection
argument is right, would not be random. Their breaches would cluster on the
side the market moves.

---

## 12. Experiment: the on-chain shadow hedge

For every weekend trade the system builds the on-chain hedge that a
firm-price product would require:

1. Request a Jupiter quote for the exact size.
2. Have Jupiter assemble a real swap transaction against the project's own
   Solana wallet.
3. Sign it locally with the real key.
4. Simulate it against Solana mainnet.
5. Compute the full fee, and record everything.

**It never sends the transaction.** There is deliberately no function to do so.

This prices the design the proposal rejects. If Yagnum had guaranteed the
weekend price, it would have needed to offset the position on Solana. That
means paying the spread twice plus gas, and carrying tracking error between the
token and the share.

**Why the simulations report failure.** The wallet holds no SOL and no tokens,
so mainnet simulation returns "account not found." That is the honest result
for an empty wallet. The fee arithmetic is still computed correctly from the
assembled transaction.

**A structural point worth making in a write-up.** Hedging a pass-through
design would *create* risk rather than remove it. The pass-through already
leaves Yagnum exactly flat, so adding an on-chain leg would manufacture a loss
equal to the spread plus gas.

The RQ2 result sharpens this. Because weekend spreads do not widen, a
firm-price operator's cost is not the spread. **It is the weekend move the
operator cannot hedge.** That is exactly the 52 percent "share weekend move"
part of the decomposition.

---

## 13. Limitations and threats to validity

### Construct validity

- **Sandbox fills.** Every account is simulated through Alpaca's sandbox. The
  settlement *logic* is exercised honestly. The *fill quality and timing* may
  not be representative, and the settlement-timing result in particular should
  be re-measured on a live venue before it is generalised.
- **Simulated traders are not traders.** Order flow comes from language models,
  so arrival times, sizes, direction and symbol choice do not reflect real
  demand.
- **$1,000 quotes only.** RQ2 says nothing about depth at institutional size.

### Internal validity

- **Effective sample size is small.**
  - There are 6 weekends and 51 (symbol, weekend) clusters.
  - Every stored-method miss is one event, META on 2026-09-19, counted several
    times.
  - Per-symbol tests have about 19 weekend days each.
- **Sparse, uneven sampling.** The recorder ran about 6 times a day, not every
  5 minutes. Weekend token samples are a median 3.3 hours apart, so the token
  price at a trade's exact time is linearly interpolated. The spread and basis
  parts of the decomposition may absorb some token drift.
- **Seven trades lacked a bid and ask** at the nearest sample, so they used the
  last swap price (ids 10, 24, 40, 46, 70, 105, 123).
- **The Friday reference print** falls between 15:59 and 16:56 Eastern, so it
  includes some after-hours prints.
- **Parameters were stale** at the time the trades ran (generated 2026-08-31).
- **Two tokens look mis-mapped or mispriced.** STRCx and VIDAx carry a
  persistent 8 to 10 percent basis against their share. They should be
  investigated before being used in any basis result.

### External validity

- **47 days, one market regime,** with liquidity steadily improving. The tail
  behaviour a reserve exists for is precisely what a short calm window fails to
  observe.
- **26 symbols, all large-cap US.** That is 26 of more than 100 xStocks.
- **One issuer, one chain, one aggregator.** Ondo tokens with weekend mint and
  redeem may behave differently. Section 16 adds them.

### Known gaps in the system

- Securities journals are not enabled in the sandbox, so weekend-sold shares
  are protected by an application-level ledger lock.
- Settlement fills are late (Section 10).
- Early-close half days are not yet routed correctly; a fix is in progress.
- The on-chain hedge is modelled, never executed.

---

## 14. Ethics, regulation, and the project's honesty constraints

### Regulatory position

The project does not offer securities, custody assets, or handle real money. It
runs entirely on a brokerage sandbox with simulated cash, and the interface
says so on every page.

Three regulatory facts a capstone must state accurately, as of 2026-10-13:

1. **xStocks and Robinhood's stock tokens are not offered to US persons.**
   Yagnum's design works because the customer never holds a token; they hold
   shares in a regulated brokerage account.
2. **The SEC's Innovation Exemption (2026-09-17) changes the picture, but not
   for retail yet.** It allows permissioned, allowlisted participants to trade
   tokenized NMS stock on qualifying venues, with tier caps. It does not
   specify retail access. Any claim that this system could operate
   commercially for US retail today would still be wrong.
3. **A regulated weekend venue for real shares has been announced** (Bruce
   Markets) but is subject to regulatory review and is not yet live.

### Self-imposed constraints

- The brokerage is never deceived.
- The interface never implies real money.
- The on-chain wallet signs but never sends. Sending is gated behind a
  separate, unmade family decision.
- Mistakes are recorded rather than quietly fixed. ADR-028 and ADR-029 document
  a design error and its reversal within one day.
- Hypotheses that fail are reported as failed. This revision replaces its own
  earlier hypothesis.

### Use of AI, stated plainly

The implementation and the analysis scripts were produced by AI coding agents
under the student's direction. The student:

- set every architectural decision;
- caught substantive errors, including one conceptual error in the financial
  design;
- set the quality constraints;
- chose which questions to ask.

The research pass in this revision ran several agents in parallel, each
writing a reproducible script. Any capstone submission must represent this
accurately. Directing, checking and correcting agents in an unfamiliar domain
is a demonstrable skill, and the error-catching is evidence of genuine
understanding.

---

## 15. Capstone work plan

### Status of the original plan

| Item | Status |
| --- | --- |
| 1. Refresh the parameters | **Running.** Results to be added. |
| 2. Re-estimate sigma on the realised quantity | **Done.** The answer changed the question. Section 10. |
| 3. Answer RQ2 | **Done.** Null result, tight interval. Section 10. |
| 4. Decompose the gap | **Done.** Basis and spread are small; timing is large. Section 10. |
| 5a. RQ4, token lead | **Running.** |
| 5b. RQ5, hedge cost | **Running.** |
| 5c. Stress test on worst historical weekends | Folded into the walk-forward backtest, running (Section 16). |

### The plan from here

Ordered by value per unit of effort.

1. **Diagnose and fix late settlement.** Find why fills land hours or sessions
   after the open. Candidates are the cron's timing, the order type, and
   conditions in the settlement job. Then make fills land at the open, and
   re-measure. *The project owner decides how.* This is the highest-value item
   because it removes about half of the measured risk.
2. **Refresh the parameters** and recompute coverage under them. This
   separates "stale parameters" from "method".
3. **Adopt and test a recent-data floor for sigma,** max(stored, realised), as
   a proposal backed by Section 10's out-of-sample table. Present it as weak
   evidence from one event, which is what it is.
4. **Re-run every analysis after Thanksgiving, Christmas and New Year.** These
   three weekends roughly double the cluster count and include the three-day
   weekends (Section 16).
5. **Write up RQ4 as a replication** of Cong et al. and Binance Research on
   this project's own record.

### What not to do

Do not size the reserve to cover an operational defect. Do not report
in-sample coverage. Do not claim a weekend spread premium; the data say there
is none at this size.

---

## 16. Research to collect next

The research pass showed what the current record cannot answer. These are the
measurements that would answer it. They need data that must **accumulate over
the coming weeks**, so they need to start before the holiday weekends.

### New data series

| # | Collect | Why | Serves |
| --- | --- | --- | --- |
| 1 | **The price context at trade time.** For each weekend trade, store the token bid, ask and mid; the share reference price with its time; the basis; and the σ and z used. | The decomposition had to rebuild these from samples hours away. Storing them removes the interpolation error. | RQ3, RQ6 |
| 2 | **Ondo tokens beside xStocks:** SPYon, QQQon, NVDAon, TSLAon, GOOGLon and CRCLon. | A natural experiment: the same share, one issuer with weekend mint and redeem and one without. Does the weekend basis tighten? | RQ2, RQ4 |
| 3 | **A depth ladder:** quotes at $1k, $10k and $50k, hourly, for the main symbols. | RQ2 tested only $1,000. Activity falls at the weekend even if the small quote does not move; depth is where that should show. | RQ2, RQ5 |
| 4 | **Extended-hours share prints.** | The share side of the token-lead test. | RQ4 |
| 5 | **Oracle prices.** Pyth equity feeds on each run. | Many oracles hold Friday's close all weekend. Any on-chain product that reads an oracle inherits that blindness. | Context for Section 5 |
| 6 | **Settlement timing.** Order placed, accepted and filled, each with a timestamp. | RQ6 needs the lag's cause, not just its size. | RQ6 |
| 7 | **Half-day routing fix** before Friday 2026-11-27, which closes at 13:00. | Without it, that afternoon routes wrongly. | Correctness |

Items 1 to 5 and 7 are being built at the time of this revision. Item 6 waits
on the owner's decision about the settlement fix.

### Calendar natural experiments

| Date | Event | What it tests |
| --- | --- | --- |
| Thu 2026-11-26 – Fri 11-27 | Thanksgiving closure, then a 13:00 early close | Half-day routing; a four-day gap from Wednesday |
| Fri 2026-12-25 | Christmas, a three-day weekend | Does the gap scale with √time? |
| Fri 2027-01-01 | New Year, a three-day weekend | A second three-day observation |

A three-day weekend is the cleanest test available of whether σ should scale
with the length of the closure. The current engine uses one sigma for every
weekend.

### Analyses that need no new data

These are running at the time of this revision:

- **A. Time-of-weekend risk.** Pair every weekend token sample with the Monday
  open and ask whether the error shrinks as Monday approaches. If it does, a
  reserve could scale with √(hours remaining) and be cheaper for a Sunday
  evening trade than a Friday night one.
- **B. Walk-forward reserve backtest.** Simulate a trade for every symbol and
  every weekend over two years, with sigma computed only from data before that
  weekend. This turns 126 trades into thousands, and gives a Kupiec test with
  real power.
- **C. Persona behaviour.** For the 824 logged decisions, measure decision mix,
  reaction to the shown reserve and spread, disposition effect, and herding.
  These are LLM agents, so this is about the agents, not about people.

Further out:

- **D. Settlement execution quality.** Compare the fill with the official open,
  time to fill, and premarket versus the opening auction.
- **E. A small, consented human study,** compared against the personas.

### Watch list

| Event | Why it matters |
| --- | --- |
| Bruce Markets' weekend session going live | Weekend prints for the real share: the cleanest possible RQ4 test, and a second source of `p_open` |
| The first TSV launch | Its public 10-minute transaction data is a free, regulated on-chain dataset |
| Nasdaq tokenized trades going live | Tokenized and ordinary shares in one order book |
| Kraken's acquisition of Backed closing | The xStocks issuer changes hands |
| xStocks universe growth | 26 of 100+ tracked today |

---

## 17. Deliverables and how to present it

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
| Results | Section 10 |
| Discussion and limitations | Sections 10 and 13 |
| Ethics and regulatory position | Section 14 |
| Conclusion and future work | Sections 15 and 16 |

### The charts to build, in order

1. **The gap decomposition** (`gap_decomposition.png`). This is the headline
   chart: one bar per part, with settlement timing visibly as large as the
   market itself.
2. **Spread by hour of week** (`rq2_spread_hour_of_week.png`). A flat line
   through a shaded weekend. It shows the null result at a glance.
3. **Sigma methods coverage** (`sigma_methods_coverage.png`). This shows the
   trade-off between coverage and reserve size.

### The demo, five minutes

1. Open the live site and show the weekend trade ticket with its reserve
   arithmetic visible before confirming.
2. Show the weekend trades panel with a settled trade: weekend price, Monday
   price, what came back.
3. Open the database and show the same trade's journal trail.
4. Show a GitHub Actions run of the settlement job firing with nobody present.
5. Put up the decomposition chart and say what it found.

### The thirty-second version

"The stock market closes for 48 hours a week, but tokenized versions of the
same shares keep trading. I built a system that lets someone trade on a
Saturday at that live price and settle at Monday's real price, with a cash
reserve covering the gap. It has settled 126 trades automatically, and the
reserve held 98.4 percent of the time. When I took the misses apart, the
statistics were fine. Almost half the risk came from my own system settling
hours late on Monday. The research found a bug that no unit test would have
found."

### Anticipated questions

| Question | Answer |
| --- | --- |
| Is this real money? | No. Brokerage sandbox throughout, stated on every page. |
| Didn't Robinhood just do this? | They tokenized stocks. They did not reconcile to a regulated account, and their tokens are unavailable to US persons. Section 5. |
| Doesn't the SEC exemption or Bruce make this obsolete? | They supply new weekend prices. Every one of them still settles on business days and needs a measured reconciliation. Section 5. |
| Who wrote the paper? | My father. The implementation, measurement, and results are mine. |
| How much did the AI write? | Nearly all the code and analysis scripts, under my direction. I made the design decisions and caught the errors. |
| Why not just hedge on-chain? | Under pass-through, Yagnum is already flat. Hedging would create a loss. Section 12. |
| Is 126 trades enough? | For the pooled figure, marginally. For the per-symbol finding, no: it rests on one META weekend. The walk-forward backtest addresses this. |
| Spreads didn't widen. Isn't that a failed hypothesis? | Yes, and a useful one. It shows the weekend cost is price risk, not trading cost, which is the case for a reserve. |

---

## 18. Reproducibility

From a clean machine, in order:

```
git clone https://github.com/Yagnum/Empirical
cd Empirical/app/api
uv sync
uv run alembic upgrade head
uv run pytest -q            # 226 tests should pass
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

To reproduce Section 10, run each script from `app/api`. Every script reads the
database only and prints every number it reports.

```
uv run --group research python ../../notebooks/analysis/rq2_spread.py
uv run --group research python ../../notebooks/analysis/gap_decomposition.py
uv run --group research python ../../notebooks/analysis/sigma_realised.py
```

`gap_decomposition.py` and `sigma_realised.py` share the loader
`notebooks/analysis/weekend_data.py`. They write per-trade CSVs to
`notebooks/analysis/out/`.

Live system: `https://yagnum-web.azurewebsites.net`. The free hosting tier
sleeps after 20 idle minutes, so the first page load may take 30 seconds.

---

## 19. Appendix

### The decision record

Twenty-nine numbered architecture decisions are recorded in
`docs/DECISIONS.md`. The ones that matter most for a capstone:

| ADR | Decision |
| --- | --- |
| 010 | Money is decimal strings, never floats |
| 014 | Postgres arrives: audit log, idempotency, fills ledger |
| 016 | Measure before building: start the price record first |
| 017 | The ERR is a pass-through; the Monday leg closes premarket |
| 018 | z is measured, not looked up; sigma per symbol, pooled multiplier |
| 019 | The engine: session routing, state machine, dev simulator |
| 020 | Record the spread: two executable quotes per token |
| 022 | Ledger lock for custody, because the sandbox cannot journal securities |
| 023 | Settlement runs as an idempotent weekday-morning cron |
| 024 | Overnight orders queue at the broker |
| 025 | On-chain hedge built, signed, simulated, never sent |
| 026 | Simulated traders decide through the real engine |
| 028 | A firm weekend price. **Reverted the same day.** |
| 029 | The paper is pass-through; ADR-028 was a misreading, corrected |

ADR-016 deserves a mention in a write-up: the decision to start recording data
before building anything is why there is a 47-day dataset at all. ADR-017
deserves a second look in light of Section 10. It intends the Monday leg to
close premarket, and the measured fills did not.

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

### Sources for Section 5

- SEC press release 2026-90, Innovation Exemption for tokenized NMS stock:
  <https://www.sec.gov/newsroom/press-releases/2026-90-sec-issues-innovation-exemption-facilitate-trading-tokenized-nms-stock-request-comment>
- Morgan Lewis summary of the exemption:
  <https://www.morganlewis.com/pubs/2026/09/sec-grants-temporary-innovation-exemption-for-trading-tokenized-nms-stocks-on-distributed-ledger-venues>
- Bruce Markets weekend trading announcement, 2026-09-30:
  <https://www.prnewswire.com/apac/news-releases/markets-to-be-open-seven-days-a-week-bruce-markets-to-launch-first-continuous-weekend-us-equities-trading-with-strategic-investments-led-by-peak6-and-robinhood-302892011.html>
- Ondo, 24/7 minting and redemption, 2026-06-25:
  <https://ondo.finance/blog/real-24-7-trading-for-tokenized-stocks>
- Nasdaq tokenized securities approval, 2026-03-18 (secondary):
  <https://www.coindesk.com/policy/2026/03/18/sec-approves-nasdaq-s-move-to-allow-tokenized-securities-trading>
- DTC no-action letter, 2025-12-11:
  <https://www.sec.gov/files/tm/no-action/dtc-nal-121125.pdf>
- Kraken's acquisition of Backed: <https://blog.kraken.com/news/backed-acquisition>
- Cong et al., "Tokenized Stocks", SSRN 5937314:
  <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5937314>
- Weekend on-chain prices and Monday, citing Binance and CoinMarketCap
  Research, 2026-09-22:
  <https://www.insidermonkey.com/news/what-weekend-on-chain-prices-say-about-monday-and-what-they-dont-1842401/>

### Open questions as of 2026-10-13

- **Why settlement fills late, and how to fix it.** This is the owner's
  decision.
- Whether to adopt the max(stored, realised) sigma floor.
- The parameter refresh, RQ4 and RQ5 results are pending.
- Whether to fund the Solana wallet and send real swaps. This is a family
  decision, not a technical one.
- STRCx and VIDAx: mis-mapping or a real basis?
- No custom domain, so Clerk authentication runs in development mode.
