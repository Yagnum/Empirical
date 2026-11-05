# Yagnum, Explained

**The purpose in one sentence.** Yagnum lets a person lock in a price for a real U.S. stock while the market is closed, and it does this without making markets or taking a view on where the stock goes.

Written from the academic proposal (v4, "Cross-Market Hedging Model", August 2026) and from the project's own database as of 2026-11-05. The numbers in Section 5 can be regenerated with `notebooks/analysis/err_absorption.py`. Section 8 says plainly what is simulated and what is not.

---

## 1. The problem: the market closes when people can think

This project began with a practical frustration. My father and I do our research on stocks at the weekend, because that is when we have time. So our most intellectually active hours fell exactly when we could not trade.

The workaround was to place a limit order on Saturday for Monday. That felt wrong in a way that took a while to name. We were doing careful work to arrive at a price, then handing that price to a mechanism that could not honor it. The order might not fill. If it filled, we could not know whether the price was still fair, because Monday's open could be far from Friday's close. Weekend news made this worse: you could read it, understand it, and still do nothing until the next session.

Naming the problem exactly is what made it solvable. A retail trader facing a closed market has only two tools, and each one gives up something:

| Tool | Certain about | Uncertain about |
| --- | --- | --- |
| Monday market order | That it fills | The price |
| Monday limit order | The price, if it fills | Whether it fills |
| **A locked weekend price** | **Both** | Only a small, measured remainder (Section 5) |

So the product is not "more trading hours". It is the missing row in that table: **price certainty and execution certainty together, at a moment when the regulated market cannot offer either.**

This reaches well beyond our family. Regular U.S. trading runs 9:30 to 4:00 Eastern on weekdays, which overlaps almost exactly with a normal working day. The hours when most people are free to think about their investments are close to the hours when they cannot act on them.

A smaller motivation is emergency liquidity. Someone who needs cash on a Saturday cannot sell until the next session, and U.S. settlement then takes one more business day. Yagnum's sale pays out at once. This is a real benefit but a secondary one. It is not why the project exists.

**How big is the risk being managed?** On our settled trades of $100 or more, the move between the weekend token quote and the real share fill had a median size of 2.0% of the trade and a 95th percentile of 10.1%. Those moves include delays in our own settlement (Section 6), but the point stands: a price you cannot lock on Saturday can be far away by the time you can trade.

---

## 2. From the problem to the design

We did not start by building. We started by asking whether a weekend price could exist at all. That question led to tokenization.

**What we found.** A tokenized stock is a digital token backed one-to-one by a real share held in custody. On Solana, Backed Finance issues these as xStocks: `NVDAx` tracks `NVDA`. They trade around the clock in liquidity pools, and Jupiter routes each order to the best available price. So on a Saturday, a live and executable price exists for a share whose own market is shut.

Three roles here are easy to confuse, and the design depends on keeping them apart:

| Role | Who | What it does |
| --- | --- | --- |
| **Issuer** | Backed Finance | Mints tokens against custodied shares |
| **Router** | Jupiter | Finds the best route across pools. It holds no inventory of its own |
| **Liquidity providers** | Solana pools and their LPs | The actual counterparties, carrying inventory and adverse selection |

### The first idea, and why we dropped it

Our first reaction was: this is exactly what we wanted, and we can be the market maker on this platform and offer 24/7 equities ourselves. So before building that, we studied the most famous failure in crypto market structure: FTX and its affiliated trading firm, Alameda Research.

The obvious lesson would be "market making is dangerous, so avoid it". That lesson is too crude, and it is not quite what FTX shows. Most of the FTX collapse was fraud and the misuse of customer money, not a market maker's ordinary risk. Bankman-Fried was sentenced to 25 years in March 2024. What made the case useful to us was **the mechanism by which a market-making role turned into a hole**:

1. **The market-maker role was the justification for special treatment.** FTX co-founder Gary Wang testified that Alameda had an `allow_negative` setting that exempted it from the liquidation other accounts faced, and a line of credit that grew to $65 billion. He testified that market makers typically had lines in the millions. The defense argued the feature was needed for Alameda's market-making role. A liquidity provider really does need room to operate, and that real need became cover for an effectively unlimited loan.
2. **The conflict of interest was structural.** The venue's risk engine was controlled by the people who also owned its biggest trader. No outside party was positioned to say no.
3. **Customer money and trading capital were not separated.** Customers wired billions of dollars to bank accounts controlled by Alameda. Once that happens, a trading loss becomes a customer loss.
4. **The collateral was correlated with the risk.** Alameda's borrowing was backed in large part by FTT, a token FTX itself issued, which lost its value exactly when it was needed.
5. **Risk was not really measured.** John Ray, who took over in bankruptcy, cited a "secret exemption" from the liquidation protocol among the control failures. Bankman-Fried himself later said that an hour a day spent on risk management might have prevented the collapse.

Reading that, we asked what any honest market maker on this platform would still have to carry, with the fraud taken out:

- **Adverse selection.** Weekend flow is likely to include people reacting to weekend news. A firm quote to them is a free option, and they exercise it against you. This is the classic result of Glosten and Milgrom (1985) and Kyle (1985).
- **Unhedgeable inventory.** The regulated market you would hedge in is closed.
- **Capital and operational risk.** Thin capital cannot survive one bad gap. Nor is this only a crypto problem: Knight Capital, a mainstream U.S. market maker, lost more than $460 million in about 45 minutes in 2012 from one faulty deployment.
- **Regulatory exposure.** Whether a crypto market maker is an unregistered securities dealer has been actively contested, including in SEC enforcement actions before the agency changed course in 2025.

Market making is a real discipline, done well by specialised firms with capital, technology and licences. We were not going to become one by reading about it. So we made the decision that shaped everything after it: **Yagnum uses existing liquidity and never provides its own.** The liquidity providers on Jupiter already exist, and they already price the risks above. Yagnum's job is the one nobody was doing: connecting that weekend price to a regulated account.

The FTX case also became a list of things the architecture must rule out:

| FTX failure | Yagnum's rule |
| --- | --- |
| Affiliated market maker with special privileges | No affiliated market maker. Every trade prices from a public quote |
| Customer funds used as trading capital | Every cash move is a tagged journal at a regulated broker, so "escrow covers open trades" is a query against the broker's records, not a promise in our code |
| Correlated collateral | The reserve is cash, never a token Yagnum issued. Yagnum issues nothing |
| Unmeasured risk | The reserve is sized from a published calculation and shown to the trader before they confirm |
| Losses landing on people who never agreed to them | The cascade (Section 9) ends in a known state for every trade |

### Why build at all

Building is how I learn most. Conceptual understanding is useful, but a working system forces you into details a paper can skip: what a mint is, who actually pays gas, why a token account needs a refundable deposit, what happens when a broker refuses a journal on Monday morning. So we built a paper-trading platform to test whether the theory held up against real prices.

The platform also addresses a second gap. Tokenized equities are available to anyone comfortable with crypto, but for an ordinary investor the friction is large: a wallet, converting dollars to USDC, gas in SOL, token accounts, and in the U.S. the fact that xStocks are not offered to U.S. persons at all. Yagnum's customer never touches any of this. They see a stock, a price and a brokerage account. **The token is infrastructure, and it stays behind the interface**, the way TCP/IP stays behind a web page.

---

## 3. The mechanism

**ELI5.** You sell your bike to a shop on Saturday for $226, and that price is yours. The shop can't resell the bike until Monday and worries about prices falling. So the same minute, it sells a bike-voucher next door, in a market that never closes, also for $226. If prices fall, the shop loses on your bike and gains on the voucher. You leave a small refundable deposit. On Monday you get it back, plus or minus whatever tiny amount the bike and voucher failed to cancel.

**In full, for a customer sell** (a buy is the mirror image):

| When | The trader | Yagnum |
| --- | --- | --- |
| Weekend | Sells at Jupiter's executable bid, `p_open`. **That price is final.** Receives cash at once. Posts the ERR | Sells the same quantity of the token on Jupiter at the same quote |
| Monday | Nothing to do | Sells the real shares at the broker at `p_close`, and buys the token back at `close_px` |
| After | Receives the ERR plus or minus the leftover | Ends flat |

The **Execution Reconciliation Reserve (ERR)** is the part that makes this honest. It is a deposit that belongs to the trader, not a fee or a premium:

```
ERR_initial = qty × p_open × σ × z + fees_est      (proposal §6d)
leftover    = broker leg + token leg − gas         (proposal §6b, P&L_net)
ERR_final   = ERR_initial + leftover
```

If the leftover is positive, the hedge made money and the trader **receives that profit**. If it is negative, the loss comes out of the deposit. Yagnum keeps nothing either way. The proposal is explicit: the trader "pays ERR escrow (refundable on reconciliation)", a surplus is "automatically refunded", and Yagnum is "not a speculative trading protocol".

So "locked" has a precise meaning: **locked to within the leftover.** Section 5 measures how small that is.

### A real example of each direction

Both use real recorded prices (Jupiter's executable quotes and the broker's sandbox fill), re-run under the locked-price rule.

**Trade 98, a buy that went the trader's way.** On Sunday, 20 NVDA at $225.54.

| | |
| --- | --- |
| Trader pays for the shares | $4,510.79 |
| ERR posted (3.7%) | $166.85 |
| Monday: shares bought at the broker | $229.99 |
| Broker leg, 20 × (225.54 − 229.99) | −$89.01 |
| Token leg, bought at 225.54, sold at 230.25 | +$94.19 |
| Gas, both legs | −$0.36 |
| **Leftover** | **+$4.82** |
| **ERR returned** | **$171.67** |

The trader paid $89.01 less than a Monday buyer would have, and received $4.82 more than they deposited.

**Trade 125, a sell where the leftover was negative.** On the weekend, 10 NVDA at $230.80. The shares sold Monday at $226.15 (−$46.52), and the token was bought back at $226.67 (+$41.31). After $0.33 of gas the leftover was **−$5.54**, so $79.83 of the $85.37 ERR came back.

These were chosen to show one profit and one loss. Section 5 gives the distribution.

---

## 4. Four ways to see what this actually does

The mechanism is simple, but it connects to several older ideas. Each view below changes how you read the numbers.

### 4a. It converts price risk into basis risk

This is the oldest move in hedging. A grain elevator owner who hedges with futures does not eliminate risk. They exchange the risk of the price of wheat for the much smaller risk of the gap between their wheat and the futures contract: the **basis**. Yagnum does the same thing with a share and its token.

The standard measure of how well this works is hedging effectiveness, the fraction of variance removed (Ederington, 1979). The figure on our data, when both legs close together, is **99.1%**, with a minimum-variance hedge ratio of **0.997**. The ratio is what you would hope for from an instrument backed one-to-one: one token hedges one share.

### 4b. The weekend disappears from the equation

This is the insight we found most surprising. Write the leftover out, for a customer sell:

```
leftover = qty (p_close − p_open) + qty (open_px − close_px) − gas
```

The trader's price and the hedge's entry are the same quote, so `open_px = p_open` (on our data they differ by an average of 0.002%), and those terms cancel:

```
leftover = qty (p_close − close_px) − gas
```

**Nothing about the weekend is left.** The leftover depends only on the gap between the share and the token at the moment Monday's legs close. Everything that happened in between, however violent, has passed through the hedge.

This makes a prediction we could test. Prices behave roughly like a random walk, so an unhedged position's risk should grow with time. French and Roll (1986) is the classic study of how variance accumulates across trading and non-trading hours. But a share and its one-to-one token are tied together by redemption and arbitrage, so the gap between them should be roughly stable: in the language of Engle and Granger (1987), the two prices should be **cointegrated**. If so, hedged risk should not grow with time at all. It does not:

| Time from trade to fill | Trades | Unhedged std (% of trade) | Hedged leftover std |
| --- | --- | --- | --- |
| Up to 1.5 days | 18 | 2.38% | **0.37%** |
| 1.5 to 4 days | 63 | 3.85% | **0.37%** |
| Over 4 days | 21 | 5.73% | **0.36%** |

As the wait lengthens, the unhedged risk more than doubles and the leftover does not move. This also changes the meaning of an earlier finding. Under the first design, late settlement explained 46% of the risk. **Under the hedge, late settlement is nearly harmless to the reserve**, as long as both legs close together.

Two cautions. The bins are small. And almost all of these closes happened while the regulated market was open, when arbitrage is at work. So this says the gap at the close is small, not that the token tracks the share closely all weekend. The algebra says that weekend gap should not matter to the leftover, and Section 6 shows the token does drift over the weekend.

### 4c. The ERR is initial margin, and the cascade is a default waterfall

Clearing houses solved a version of this problem long ago. Between a trade and its settlement, someone might fail, so a clearing house collects **initial margin**, sized to cover a large move over the time it would take to close the position out. If that is not enough, losses run down a fixed **default waterfall**.

The ERR is initial margin for a one-trade clearing house. `σ × z` plays the role of the margin model. The proposal's four-level shortfall cascade is a waterfall. The interval between the trade and its close is what clearing calls the **margin period of risk**. This view explains why our first design failed where it did: its margin model assumed a period ending at Monday's open, while the engine's real period ran hours or days longer. That is a known type of failure, not an exotic one.

### 4d. Adverse selection is relocated, not ignored

Our earlier reasoning said a firm weekend price would be picked off by informed traders. That remains true of a firm price offered from your own book. It should not be true of this design, and the reason is worth being careful about.

Yagnum does not choose the price. The price is whatever Jupiter's liquidity providers will trade at right now, and Yagnum trades at that same price in the same moment. If an informed trader sells, Yagnum sells too. The informed flow lands on the liquidity providers, who are paid for that risk through their spreads and move their quotes in response. The proposal's actor table says this directly: Jupiter's LPs carry "inventory, price discovery, and adverse-selection risk".

Yagnum therefore behaves less like a market maker and more like a **riskless principal**: it stands between two trades and earns nothing from the difference. What it offers the customer is access to a price, not a guarantee of a fair one. If the token is expensive on Saturday, the trader locks an expensive price, and that is the trader's decision. Our order flow is simulated and uninformed, so this reasoning has **not been tested against real informed traders**.

---

## 5. What the ERR actually has to absorb

This is the central empirical question: if the hedge works, how much is left for the reserve to do?

**The data.** 175 weekend trades settled against the broker's market. 138 of them (79%) have both token-hedge quotes recorded. Of those, 117 are $100 or larger. The smaller ones are discussed below. The 117 span 9 weekends and 64 symbol-weekends, with a median trade of $3,150.

### The headline

**For a typical trade, the ERR absorbs about 0.2% of the trade's value, or roughly 6% of the deposit.**

Measured on the 102 trades whose two Monday legs closed together:

| Measure | Hedged leftover | Unhedged, for comparison |
| --- | --- | --- |
| Standard deviation | **0.39%** | 4.15% |
| Median size | **0.23%** | 2.01% |
| 90th percentile size | **0.76%** | |
| 95th percentile size | **0.93%** | 10.17% |
| Largest | **1.10%** | |
| Variance removed | **99.1%** | |

The 95% interval from a bootstrap over weekends is 0.30% to 0.44% for the standard deviation, and 97.9% to 99.6% for variance removed.

In dollars, on this group's median trade of $2,820: an ERR of about $104, a leftover of $5.45 in median size, and a median signed leftover of −$1.78.

How much of the 3.7% deposit each trade moved:

| Leftover as a share of the deposit | Trades |
| --- | --- |
| Under 10% | 71% |
| Under 25% | 94% |
| Under 50% | 100% |

The largest share of an ERR used by a loss was **29.7%**. Reserve breaches: **zero**. The leftover was a profit returned to the trader on **35%** of trades.

### The cost is real, and it is mostly the spread

The median leftover is −0.155%, so the typical trader gets back slightly less than they put in. That is the true cost of the product. It is not symmetric:

| Side | Trades | Median leftover | Standard deviation |
| --- | --- | --- | --- |
| Buy | 66 | −0.01% | 0.36% |
| Sell | 36 | −0.24% | 0.34% |

For a customer sell, Yagnum buys the token back on Monday at the ask, and on those trades the ask sat about 0.22% above the share's fill. For a customer buy, Yagnum sells the token at the bid, which sat almost exactly at the share's fill. So token quotes appear to sit with the bid near the share and the ask above it. That fits our separate finding that token spreads are largely set by pool fees (Section 6).

### A flaw the analysis found in our own measurement

Across all 117 trades, the same calculation gives a standard deviation of 0.96%, not 0.39%. That difference traces to 15 trades, every one of them a customer sell.

When a share sale fills, its proceeds are not immediately transferable. Our engine swept the proceeds first and only then quoted the token buy-back, so when the sweep failed, the buy-back was quoted at a later run, a median of 46 hours after the share had filled. A real hedge would close both legs together. These 15 trades measure two days of drift between a fresh token quote and a stale share fill. They are a bookkeeping artefact, not a measure of hedge quality.

The split is defined by an operational event, not by outcome, so it is not cherry-picking. All the same, the honest statement gives all the numbers:

| | Trades | Std | Variance removed | Worst loss |
| --- | --- | --- | --- | --- |
| Legs closed together | 102 | 0.39% | 99.1% | −1.10% |
| Delayed buy-back | 15 | 2.46% | 24.5% | −2.85% |
| All | 117 | 0.96% | 94.3% (interval 90.2% to 97.3%) | −2.85% |

The fix is simple: quote the buy-back the moment the share fills, before any journal runs.

### Sizing the reserve from this

The live ERR uses σ = 0.98%, measured before this artefact was understood. That gives about 3.7% of the trade, against about 10% under the first design. It is larger than these trades needed:

| σ | ERR | Breaches in 102 | Largest use |
| --- | --- | --- | --- |
| 0.98% (live) | 3.70% | 0 | 30% |
| 0.50% | 1.89% | 0 | 58% |
| 0.40% | 1.51% | 0 | 73% |
| 0.30% | 1.13% | 0 | 97% |

We have not lowered it. This is in-sample, nine weekends are not evidence about a crisis, and the cost of being wrong on a reserve is asymmetric. Something near 2% looks plausible if the holiday weekends confirm it.

### Where it breaks: small trades and large ones

**Very small trades.** All 4 breaches among trades with both hedge legs are trades of about $10 or less. Gas is flat, at about $0.34 for the two legs, while the ERR is a percentage. On a $0.77 trade the ERR is 3 cents. The proposal's formula has a `Fees_est` term for exactly this, and our parameter file sets it to zero. That is a real calibration bug, and setting it to about $0.40 addresses it. About 95% of that gas is a refundable token-account deposit, so the true economic cost is smaller still.

**Large trades.** Those results come from quotes at the trade's own size, with a median near $3,000. Since 2026-11-01 we also record quotes at $10,000 and $50,000:

| Token | Round trip at $10,000 | Round trip at $50,000 | Pool liquidity |
| --- | --- | --- | --- |
| SPYx | 0.11% | 0.40% | $3.6M |
| NVDAx | 0.10% | 0.45% | $2.3M |
| TSLAx | 0.26% | 0.92% | $1.8M |
| QQQx | 0.37% | 1.08% | $1.7M |
| METAx | 0.37% | 1.39% | $0.6M |
| AAPLx | 0.39% | 1.99% | $0.7M |

These come from 17 samples over five days, so they are preliminary. The message is still clear: **capacity is the binding constraint.** This is a retail-sized product on today's pools.

---

## 6. How the experiments work

No real customers use Yagnum and no real money moves. So the question is how to learn something true from a simulation. The answer is to keep each part as real as it can be, and to be strict about what each part can and cannot show.

### The measurement instruments

**The price recorder (since 2026-08-28).** It records each token's price beside its real share, with executable quotes for a real size rather than the last trade. This mattered: the last traded price sat outside the executable bid and ask in 61.6% of observations. There are 25,861 observations so far across 37 tokens, of which 12,340 include a spread. Since November it also records Ondo's tokens, the $10,000 and $50,000 ladder, and extended-hours share prints. The schedule says every 5 minutes, but GitHub's cron delivers about 6 runs a day, which limits the time resolution of every price analysis.

**The shadow hedge.** For every weekend trade, the system asks Jupiter for a real quote at the trade's size, has Jupiter build a real swap transaction against the project's wallet, signs it where the key is available, simulates it against Solana mainnet, and computes the gas. **It stops one step short of sending.** There is deliberately no function that sends. This gives real prices and real fee arithmetic with no real exposure.

**The broker leg.** At settlement, a real order goes to Alpaca's Broker API sandbox and its fill price is recorded. All cash moves as tagged journals in that sandbox.

### The traders: language models with brokerage accounts

To test an engine you need many traders, placing trades at awkward times, in sizes nobody planned for. Eight language-model personas supply that. Each has a real sandbox account and a distinct style: Maya chases momentum, Walter buys value, Dev takes high risk at odd hours, Priya rebalances indexes, Ken is contrarian, Lena cares only about execution cost, Omar is a weekend specialist, and Sam trades mean reversion.

They run through Groq on `openai/gpt-oss-120b`, on an hourly schedule, in two groups, within a free tier of 200,000 tokens a day. Each persona gets a briefing built from recorded data (the time, its cash and positions, each watched token's price and moves, the spread, and the reserve) and replies with a single JSON intent: buy, sell or hold.

**The model never touches money.** Its reply is only a wish. The wish passes through the same engine a human order uses, and that engine can refuse it. Over two months this produced 1,268 decisions: 689 holds, 291 ordinary orders, 155 weekend trades, 107 refusals and 26 errors. The refusals are a useful result in themselves, since they show the guards working with no human present.

**What this evidence is and is not.** The personas are crash-test dummies. They test the engine under load: many open trades, refused orders, lock conflicts. They say nothing about markets, because Monday's price does not know who ordered. Their flow is also not informed, so **this dataset cannot test adverse selection**. There is even a measured difference from people: the personas show no disposition effect, the human tendency to sell winners and keep losers (Odean, 1998). Their ratio of the two selling rates was 0.96 (p = 0.75). Whatever these agents are, they are not a stand-in for human psychology.

### How the statistics are done

- **Weekends are the independent unit, not trades.** Twenty trades on one weekend are closer to one observation than to twenty. Confidence intervals use a bootstrap over weekends.
- **Out of sample where it matters.** When comparing methods for sizing the reserve, each is fitted on past weekends and tested on the next. In-sample, every adaptive method looks perfect.
- **Failed hypotheses are reported as failed.**

### What the research has found so far

**Does the weekend token price predict Monday's open? Early on, barely.** This matters, because it limits what a lock can claim. Using hourly token prices over 27 weekends and 21 symbols (March to August 2026), we regressed the Monday gap on the token's move from Friday's close:

| Token price taken at | Variance of Monday's gap explained | Direction correct |
| --- | --- | --- |
| Saturday 12:00 ET | 3% | 58% |
| Sunday 20:00 ET | 10% | 68% |
| Monday 04:00 ET | 27% | 76% |
| Monday 08:00 ET | 46% | 83% |
| Monday 09:25 ET | 55% | 86% |

So price discovery happens mostly late, and in the hours before the open. **A Saturday lock buys certainty, not a forecast.** The trader is choosing a known price over an unknown one. They are not getting a good estimate of Monday. This is weaker than the industry figure we had seen (a median 92% of the gap captured), which is measured differently and which we have not reproduced. One hypothesis, not yet tested, is that information arrives once equity index futures reopen on Sunday evening, so that tokens follow rather than lead. These figures use hourly closing trades from each token's deepest pool, and they cover a calm stretch of market history.

**Spreads do not widen at the weekend.** This was our own expectation, and it was wrong. Across 22 symbols and 2,660 symbol-days to mid-October, the weekend spread was 3.6% narrower than in regular hours (p = 0.50), with a 95% interval of about −13% to +7%. Many quotes sit exactly at a pool's fee, such as 53% of QQQx quotes at 0.060%. A spread set by a fixed fee cannot reprice risk, so weekend risk shows up in where the price sits, not in the width of the spread.

**The reserve held under the first design, and the misses had an unexpected cause.** It covered 174 of 176 settlements (98.9%, against a 99% target). We assumed the two META misses came from basis and spread. Breaking the gap into parts rejected that: those two explain about 2% to 3%. The share's own move explained 52%, and **late settlement in our own system explained 46%**.

**The cause of the delay is now known.** The settlement job is scheduled every 10 minutes through the morning. In its 12 most recent runs it actually ran about once a day, between 12:15 and 4:18 p.m. Eastern. GitHub's scheduled workflows are best-effort. That one operational fact is what the 46% was measuring.

**A two-year backtest of the first design's sizing.** A walk-forward test with no look-ahead, over 1,645 symbol-weekends, 21 symbols and 83 weekends, found 15 breaches in 3,290 trade-sides: a rate of 0.46%, against the 1% target. The formula was more conservative than its 1% target (Kupiec p = 0.0004). Eight of those 15 breaches are one symbol, STRC, whose token persistently sat about 6% above the share. The reserve's z of 3.77, measured from history, compares with a 99th percentile of 3.80 on the live trades measured to the next open. Both are well above the textbook 2.326, because real gaps have fat tails.

**Scaling the reserve to the hours left in the weekend barely helps.** Across the real trades, scaling with time alone freed only about 0.2% of notional in held capital, because the engine's weekend window closes on Sunday evening, so no trade is ever very close to the open.

---

## 7. What is wrong, or not yet known

This section matters as much as the results.

**The locked-price design is only days old.** It went live on 2026-11-01. For two months the engine ran the earlier design, where the trader ended at Monday's price, because that is how we first read the proposal. Its author then clarified the intent. So nearly every number in Section 5 is a **counterfactual**, recomputed from real recorded quotes and fills, rather than the record of a live locked trade.

**The live record is small, and it has already exposed defects.** Six locked trades have opened:

| Trade | ERR | Result |
| --- | --- | --- |
| COIN sell | $81.30 | Worked. Leftover −$6.26, $75.04 returned |
| QQQ buy | $11.38 | Worked. Leftover +$0.63, $12.01 returned |
| NVDA sell | $227.97 | **No opening hedge leg was recorded**, so the whole −$84.81 move passed through |
| SPY sell | $7.92 | **The closing quote hit a rate limit**, so the whole −$3.02 move passed through |
| META buy | $3.20 | **Stuck.** The broker refuses the purchase for lack of buying power |
| NVDA buy | $355.35 | **Stuck**, for the same reason |

So only two of six behaved as designed. For the other two settled trades **the price was not actually locked**, because the system fell back to passing the move through. Across the whole dataset, 21% of settled trades lack a usable pair of hedge quotes. These defects are fixable, but they are real:

1. A failed hedge quote must retry or block the trade, not fall through silently.
2. On a buy, the firm must fund the purchase before the order, not reimburse it after.
3. Settlement must run on a reliable scheduler rather than a best-effort cron.
4. The close quote must be taken at the fill (Section 5).
5. The ERR needs its flat fee term (Section 5).

Fourteen trades across both designs are currently unsettled, the oldest since September.

**A DEX cannot short.** This is the largest open design problem. To hedge a customer sell, Yagnum must sell a token it already holds. So a real version must carry inventory, and that inventory has price risk unless it is hedged in turn. Offsetting customer flow would help: in our simulated flow, netting buys against sells within each symbol and weekend would cut hedge volume by 37%, though simulated flow proves little about real flow. Customer buys have no such problem. Today's simulation hides this, because an empty wallet can still get a quote.

**The hedge has never been executed.** It is priced from real quotes and built as a real transaction. But a real one would face slippage between quote and landing, failed transactions, and the time between the two Monday legs. Sending real transactions is a separate decision we have not made.

**The fills are a sandbox's.** The share prices are real-market prices, but sandbox fills may be kinder than a real venue's. Since the leftover is the gap between a sandbox fill and a token quote at nearly one instant, this directly affects Section 5.

**It could not launch for U.S. retail today.** xStocks are not offered to U.S. persons. The SEC's Innovation Exemption of September 2026 opens a path for permissioned on-chain venues, but does not settle retail access. This is a research prototype, and its value is the measurement.

**Nine weekends, one regime.** Reserves exist for the weekends this sample has not seen. Thanksgiving, Christmas and New Year's will give the first multi-day closures. `research_params.json` also has not been refreshed since 2026-08-31.

**Demand is unproven.** There are no real users. One report puts weekends at about 0.55% of volume on a large tokenized-stock platform. That may mean little demand exists, or that the product has not yet been usable by the people who would want it. We do not know which.

### Others are converging on this problem

The market is moving toward this fast, and that shapes what is worth claiming:

- **Bruce Markets** (announced 2026-09-30, backed by Robinhood and PEAK6) plans a regulated weekend session for real U.S. shares. We could not confirm as of this writing that it has launched.
- **The SEC's Innovation Exemption** (2026-09-17) allows permissioned on-chain trading of tokenized stocks, including 24/7, with volume caps and public transaction data.
- **Ondo** offers weekend mint and redemption in its own app. On Jupiter its tokens are nearly untradeable, with round trips of 160% to 200% at $10,000, so its weekend liquidity lives somewhere other than the DEX.
- **Academic work** is developing. Cong, Landsman, Rabetti, Zhang and Zhao ("Tokenized Stocks", SSRN 5937314) report that tokens absorb weekend news in real time and that weekend moves anticipate Monday's open. Our Saturday numbers are weaker than that framing suggests, which is worth examining rather than assuming either is wrong.

If a regulated weekend venue succeeds, the token hedge may become unnecessary. What should survive is the general pattern: when an off-hours execution price and a later settlement price differ, a measured and refundable reserve can reconcile them. A price from a weekend ATS would still settle on business days, and the formulas in Section 9 do not name Solana anywhere.

---

## 8. What is real and what is simulated

| Component | Status |
| --- | --- |
| Token prices and swap quotes | **Real**, from Jupiter's live market |
| Share prices | **Real** market data |
| Weekend trade decisions | **Simulated**, by language models |
| Money and accounts | **Simulated**, in Alpaca's Broker API sandbox |
| Broker fills | **Sandbox** fills |
| Token hedge transactions | **Built, signed and simulated on mainnet. Never sent** |
| Gas figures | **Real** arithmetic from assembled transactions |
| Settlement arithmetic | **Real**, and checked by hand to the cent |
| The website and automation | **Real and running**, at `yagnum-web.azurewebsites.net` |

**Who did what.** The proposal and its formulas were written by my father. The research questions and engineering decisions are mine, recorded in 33 architecture decision records. The code and the analysis scripts were written by an AI coding agent under my direction, and I am responsible for checking them. That is why this document names the cases where the numbers were wrong.

---

## 9. Formula reference

**Direction.** δ = +1 when the trader buys, −1 when the trader sells.

**Prices.** `P_open` is Jupiter's ask for a buy and bid for a sell. `P_close` is the broker's actual fill, not the opening print and not a midpoint.

**The reserve** (proposal §6d, with σ measured on the hedged leftover):

```
ERR_initial = Q × P_open × σ × z + Fees_est
σ = 0.0098    z = 3.7742    Fees_est = 0 (see Section 5)
```

**The hedge's net P&L**, which the proposal calls the cross-market hedge:

```
broker leg = −δ × Q × (P_close − P_open)
token leg  =  δ × Q × (close_px − open_px)
P&L_net    = broker leg + token leg − Fees_actual
```

**Reconciliation** (proposal §6b):

```
ERR_final = ERR_initial + P&L_net
```

| ERR_final | Meaning | What happens |
| --- | --- | --- |
| Above ERR_initial | The hedge made money | All of it goes to the trader |
| Between zero and ERR_initial | The hedge lost a little | The balance is returned |
| Below zero | Shortfall | The trade is marked breached and the excess is debited from the trader's account |

**The shortfall cascade** (proposal §6c), if the trader cannot cover it: absorb from the ERR; then cap exposure and raise the ERR for that ticker; then draw on an emergency reserve; finally reverse the transaction. The proposal's aim is that every trade ends in a known state. Only the first step and the debit are built today.

**The four invariants** (proposal §5):

| Invariant | Rule | Meaning |
| --- | --- | --- |
| Backing | Token supply ≤ custodied shares | The issuer enforces this. Yagnum does not control it |
| Double entry | Σ debits = Σ credits | Money cannot appear or vanish |
| Eventual settlement | Every trade ends Completed, Failed or Reversed | No trade stays open forever |
| Reconciliation conservation | Q on-chain = Q at broker + Q reversed | No silent unhedged exposure |

The live system currently falls short of the third and fourth: Section 7 lists trades that are stuck, and trades whose hedge was not recorded.

**One departure from the proposal's wording.** The proposal's example has Yagnum *buy* the token when Alice sells, because in that example Alice herself sells a token on Jupiter. In the product, the customer sells a share in a brokerage account and never touches a token. That leaves Yagnum long the share until Monday, so the offsetting hedge is to *sell* the token. The proposal's direction wording is worth revising in its next version, along with its §2 sentence saying Yagnum does not guarantee execution prices.

**Design history.** ADR-017 and ADR-029 record the earlier design, in which the trader ended at Monday's price. ADR-028 records a one-day attempt at a locked price with no hedge, reverted because nothing covered the gap. ADR-033 records the current design. Older trades still settle under the design they opened with. Reading them in order shows how the idea developed.

---

## 10. Glossary

| Term | Meaning |
| --- | --- |
| **Adverse selection** | The traders most eager to trade with you tend to know something you do not |
| **AMM** | Automated market maker: a pool of tokens that sets prices by formula |
| **Basis** | The gap between two prices that should move together, here a token and its share |
| **Bid / ask** | The best price you can sell at / buy at right now |
| **Cointegration** | Two prices that can each wander freely, but whose gap keeps returning to a stable level |
| **ERR** | Execution Reconciliation Reserve: the trader's refundable deposit, adjusted by the hedge's result |
| **Gas** | The fee paid to include a transaction on a blockchain. Most of what we measure on Solana is a refundable account deposit |
| **Hedge** | A second trade that offsets the risk of a first |
| **Initial margin** | Collateral a clearing house collects to cover a move while a position is closed out |
| **Leftover** | What remains after the broker leg and token leg offset, less gas: what the ERR actually absorbs |
| **Margin period of risk** | The time between a trade and when its risk can actually be closed |
| **Riskless principal** | A firm that buys and sells in matching trades, carrying no lasting position |
| **Settlement** | The moment real shares and real dollars actually move |
| **xStock** | Backed Finance's tokenized share on Solana |

---

## 11. Sources

**Academic.** Cited from memory, so confirm details before quoting.
- Ederington (1979), "The Hedging Performance of the New Futures Markets", *Journal of Finance*.
- Glosten and Milgrom (1985), *Journal of Financial Economics*. Kyle (1985), *Econometrica*.
- French and Roll (1986), "Stock Return Variances", *Journal of Financial Economics*.
- Engle and Granger (1987), "Co-integration and Error Correction", *Econometrica*.
- Odean (1998), "Are Investors Reluctant to Realize Their Losses?", *Journal of Finance*.
- Cong, Landsman, Rabetti, Zhang and Zhao, ["Tokenized Stocks"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5937314), SSRN 5937314 (abstract only).

**FTX and market-making risk.**
- [Alameda's secret exemption, per John Ray's declaration](https://hotfix.coindesk.com/business/2022/11/17/alameda-had-secret-exemption-from-ftx-liquidation-protocols-new-ceo-says)
- [Gary Wang's testimony on allow_negative and the credit line](https://unchainedcrypto.com/sbf-trial-day-4-gary-wang-reveals-alamedas-special-privileges-extend-to-early-ftx/), and [on unlimited withdrawals](https://decrypt.co/200344/ftx-insider-gary-wang-sam-bankman-fried-allowed-alameda-to-withdraw-unlimited-funds)
- [How client money reached Alameda (Reuters)](https://www.thedailystar.net/business/news/exclusive-how-secret-software-change-allowed-ftx-use-client-money-3196136)
- [Sentencing](https://blockworks.co/news/sam-bankman-fried-sentenced), and [the risk-management remark](https://news.yahoo.com/sam-bankman-fried-said-hed-131733118.html)
- [SEC press release on Knight Capital](https://www.sec.gov/news/press-release/2013-222)

**The current landscape.**
- [SEC Innovation Exemption](https://www.sec.gov/newsroom/press-releases/2026-90-sec-issues-innovation-exemption-facilitate-trading-tokenized-nms-stock-request-comment)
- [Bruce Markets' weekend plans](https://www.thetradenews.com/bruce-markets-to-launch-industry-first-24-7-us-equity-trading-ecosystem/)
- [Ondo's 24/7 minting and redemption](https://ondo.finance/blog/real-24-7-trading-for-tokenized-stocks)
- [Weekend share of tokenized-stock volume](https://coincub.com/blog/24-7-tokenized-asset-trading/) (a secondary source, not verified further)

**This project.** `docs/CAPSTONE.md` holds the research write-up as of mid-October, `docs/DECISIONS.md` the decisions, `docs/SHADOW-HEDGE.md` and `docs/SIM-USERS.md` the experiments, and `docs/SOLANA-GAS-AND-JUPITER.md` and `docs/SIZING-THE-RESERVE.md` the mechanics. The analysis scripts are in `notebooks/analysis/`.
