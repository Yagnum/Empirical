# Project Yagnum — the whole thing, explained

A tour of everything that exists, how it works, and why it is built that
way. Written 2026-08-31, the day the ERR engine went live; updated
2026-09-01 with the spread recorder and holiday routing. Each section
links to the deep doc; this one is the map.

**The problem in one sentence.** The US stock market is closed 48 hours
every weekend, but tokenized copies of real shares (xStocks) trade on
Jupiter, a Solana exchange, around the clock — so a price exists when the
market does not, and Yagnum is a settlement framework that lets someone
trade against that price *safely*, with a measured cash reserve absorbing
the gap between the weekend price and Monday's real one.

---

## 1. The map

Three pieces, one repository:

```
app/web    Next.js 16 frontend — the brokerage the user sees
app/api    FastAPI backend — the only holder of every secret; talks to
           Alpaca (real-ish brokerage, sandbox) and Jupiter (read + quote)
notebooks  the research — measures the numbers the engine runs on
```

The browser never talks to Alpaca or Jupiter. It talks to our own origin;
a proxy attaches the user's session token; FastAPI does the rest. One
sentence of security model: every route acts on the signed-in user's own
account, resolved server-side, never taken from a request body.

Data lives in Neon Postgres (branch `development`). Decisions live in
[DECISIONS.md](DECISIONS.md) — twenty-one ADRs, each one a choice you made
with its reasons.

---

## 2. The brokerage (Phases 1–4, done)

What a customer can do today, and the machinery behind each piece:

**Sign in and get a brokerage account.** Clerk handles identity; the first
visit provisions a real account at Alpaca's Broker API sandbox (fake KYC,
by design — ADR-004). A login and a brokerage account are different things
with different lifecycles (ADR-013): deleting the Clerk user fires a
webhook that liquidates and closes the Alpaca account properly
(ADR-015) — sell everything, return the cash, retire the email, close.

**Fund it.** $10,000 of sandbox cash arrives by *journal* from a firm
account — instant and unlimited — because ACH transfers in the sandbox are
capped at one per day and crawl (ADR-011, learned the hard way).

**Trade it.** Market and limit orders, cancel, order history. `POST
/orders` takes an `Idempotency-Key`: the key is recorded *before* the
order goes out, so a retry after a timeout returns the original order
instead of buying twice (ADR-014). As of today it also takes
`extended_hours` for the 4–9:30 AM and 4–8 PM sessions.

**See the truth about money.** Every dollar amount is a **string** on the
wire and `Decimal`/`NUMERIC` in code and database, never a float — binary
floats cannot hold decimal cents (ADR-010). This rule appears in every
module and is the single most load-bearing convention in the project.

**Know what you made.** The moment you sell, Alpaca forgets what the
shares cost you. So we keep our own ledger: every fill is copied into
`fills`, buys open `lots`, sells consume them oldest-first (FIFO), and
`realized_pnl` stores the result — which feeds History, the dashboard, and
the sell ticket's "estimated gain vs. what you paid" line.

**Leave a trail.** Every state-changing request writes one `audit_log`
row, and every response carries an `X-Request-ID` that joins a user's "it
didn't work" to the exact row.

---

## 3. The measurement pipeline (Phase 5, running since Aug 28)

The paper's reserve formula needs one number nobody publishes: how far
weekend token prices land from Monday's real fill. So we measure it
ourselves (ADR-016):

- **The sampler** — a GitHub Actions cron, every 5 minutes, around the
  clock — records each of the ~20 xStocks' Jupiter price beside its real
  share's last Alpaca trade, into `token_prices`. The share price freezes
  at Friday's close all weekend *on purpose*: that staleness IS the gap
  being measured. Since Sep 1 each run also records the executable
  bid/ask spread (§7).
- **The backfill** pulled the past: 180 days of hourly token candles from
  GeckoTerminal (57,861 rows) and 2 years of daily share bars plus Monday
  premarket minutes from Alpaca (38,820 rows).
- **The notebook** (`notebooks/gap-volatility.ipynb`) turns all of it into
  the two numbers the engine runs on — see the next section.

Deep dives: [SIZING-THE-RESERVE.md](SIZING-THE-RESERVE.md) (the statistics,
from ELI5 up) and [JUPITER-FLOW.md](JUPITER-FLOW.md) (how a token trade
works, mints, decimals, bid/ask).

---

## 4. The reserve science (ADR-018)

The reserve is `qty × price × σ × z`. Two measured inputs:

- **σ (per symbol)** — how much *this* share's weekend gaps typically move.
  NVDA 2.7%, MCD 0.7%, MSTR 4.8%. Each symbol gets the larger of two
  independent measurements (2 years of real market weekends; the token
  record), the conservative choice while the token record is thin.
- **z (one pooled number, ≈3.77 — 3.7742 as of Aug 31)** — how heavy the
  tails are. The paper
  assumed a bell curve and took 2.326 from the normal table; the measured
  gaps have excess kurtosis of 27 (a bell curve has 0), and back-testing
  showed 2.326 gets breached ~5× more often than promised. The empirical
  99th percentile, pooled across all symbols' worst Mondays, fixes it.

These live in `app/api/research_params.json` with their measurement date,
re-derived from the notebook after each recorded weekend — parameters are
*outputs of research*, never constants typed into code.

---

## 5. ★ Aug 31: the ERR engine and the weekend simulator (ADR-019)

This is the heart of the paper, now running. Built and verified live
2026-08-31. Walkthrough with screenshots of the math:
[WEEKEND-SIMULATOR.md](WEEKEND-SIMULATOR.md).

**The routing rule.** A new module, `sessions.py`, answers one question —
*which of the five trading windows is it?* — premarket, regular,
after-hours, overnight (Alpaca's 24/5, pending the sandbox test), or the
**weekend**: Friday 8 PM to Sunday 8 PM ET, the 48 hours no regulated
venue serves. Every hour has exactly one execution path, and Jupiter is
never the path while Alpaca is. (A finding along the way: Alpaca now
covers 24/5, so the dead zone is 48 hours, not the 65 the paper assumed —
a smaller problem, precisely bounded.)

**The engine** (`weekend.py`). A weekend trade is a row in
`weekend_trades` walking a state machine:

```
provisional ──► awaiting_settlement ──► settled
                                   └──► breached
```

Opening a sell: Jupiter's *executable* quote for your exact size (the bid,
not the last-swap price) becomes `p_open`; the reserve is journaled out of
your account into the firm account; your notional is journaled *to* you —
**you sold now, you are paid now**; that immediacy is the product.
Settling: your real shares sell at the broker; the fill is `p_close`, the
first regulated price; the proceeds repay the advance; and the escrow
returns as `reserve + qty × (p_close − p_open)` — so you always end at the
regulated price (ADR-017) and Yagnum always ends flat. If the gap eats
more than the whole reserve, the trade is `breached` and the excess is
debited: escrow is collateral, not a cap.

Three technical choices worth understanding:

1. **Every cash move is a real Alpaca journal with a tag** ("ERR escrow -
   weekend trade 3"). The paper's Invariant 1 — escrow covers every open
   trade — is therefore a *query at the broker*, not a promise in our code.
2. **Every step appends a `weekend_trade_events` row** carrying the Alpaca
   journal or order id that proves it. The trade row says where things
   stand; the events say how they got there. This is the double-entry
   discipline in its simplest honest form, and it makes retries safe: a
   settlement that dies mid-way resumes by checking which events exist.
3. **The engine has exactly two injectable seams** — the clock and the
   settlement price — and the simulator is nothing but those two seams.
   No throwaway code: the simulator IS the engine.

**The simulator.** Jupiter trades 24/7, so on a Tuesday the weekend's data
source is live; we only fake the calendar. A dev-only switch (the amber
**Dev clock** pill; `POST /dev/clock`, 404 in production) forces the
session to "weekend" and the whole app follows — token panel, market
status, and the ticket, which becomes the weekend ticket showing the full
reserve arithmetic before you confirm. Settlement in dev is both honest
ways: **real** (a real order minutes later — today's run: sold 2 NVDA at
Jupiter's bid $219.98, settled at a real $219.76 fill, escrow back $44.41
of $44.86, the whole lifecycle in ten seconds) and **injected** (choose
the gap: a +12% injected Monday breached a buy's $22.44 reserve and
debited $3.97 beyond it — the crash test a real calendar would take months
to run).

37 new tests cover the session calendar, the reserve math, both settlement
modes, the breach path, and the production guards; 178 pass in total.

**Is the real flow live?** Yes — on a real weekend the same code runs with
no toggle: the calendar alone activates the weekend ticket and the engine.
One piece is still manual: settlement fires when you (or an API call)
press settle, not yet by itself at Monday 8:00 AM. The scheduled
settlement job is the next build item; until then, Monday-morning
settlement is one click.

---

## 6. The first fully recorded weekend (Aug 28–31)

The sampler just lived through its first complete weekend — 9,960
observations, Friday 4 PM to Monday, no gaps. NVDAx, from our own tables:

| Moment | Token (Jupiter) | Share (Alpaca) | What it means |
| --- | --- | --- | --- |
| Fri 3:56 PM | $217.94 | $217.98 | tracking tightly in-hours |
| Sat noon | $218.65 | $217.55 (frozen) | weekend opinion forms: +0.5% |
| Sun 11 PM | $217.72 | frozen | opinion cools to +0.1% |
| Mon 4:05 AM | $219.06 | frozen | premarket news lands in the token first |
| Mon 9:33 AM | $219.07 | **$219.21** | the market opens +0.77% above Friday |

Read the story: the token wandered a half percent all weekend, then by
4 AM Monday had already priced the +0.8% open — five and a half hours
before the market confirmed it. A seller who locked Sunday 11 PM's price
would have been trued up +0.68% at settlement; the move was a tenth of
what the reserve is sized for. This is the engine's risk, watched live at
5-minute resolution for the first time.

**What we do with this data:** top up the history tables
(`backfill_history.py --write --days 4`), re-execute the notebook so
weekend #1 joins the record, refresh `research_params.json` from its
output; repeat after every weekend. Done today: token-weekends 355 → 407,
pooled z 3.7759 → 3.7742 (stability is the finding — the multiplier is
signal, not noise), and two brand-new xStocks (BRK.Bx, GMEx) entered the
record automatically because the token list is fetched live. Each weekend sharpens σ, z, and the
settlement-moment answer — the premarket table now has real 5-minute
observations instead of backfilled minute bars alone. (One instrument
note: Alpaca's free IEX feed printed no premarket share trades this
morning — the share column stayed frozen until 9:33 — so the token is
currently our *only* premarket witness at 5-minute resolution.)

---

## 7. ★ Sep 1: the spread recorder and holiday routing (ADR-020, ADR-021)

Two builds, both racing the calendar: Labor Day weekend starts Friday
night, and both had to be live before it.

**The spread recorder — RQ2 starts collecting.** Everything recorded so
far was the *midpoint* — the last price somebody swapped at. But nobody
trades at the midpoint: a seller receives the bid, a buyer pays the ask,
and the distance between them is how liquidity providers charge for risk.
That distance is the paper's Research Question 2, and no one publishes it
historically — so, exactly like the gap itself (ADR-016), the only way to
have the data is to start recording before it is needed.

How it works, technically: every 5-minute sampler run now asks Jupiter
two extra questions per token — a real swap quote for ~$1,000 of USDC →
token (the ask) and ~$1,000 of token → USDC (the bid). One fixed size for
every token and every run, so the series is comparable across both. Five
new columns on `token_prices`: `bid_usd`, `ask_usd`, the price impact of
each leg, and the quote size. A failed quote loses the spread columns,
never the price row — the same best-effort rule the Alpaca side follows.

Two findings on day one:

1. **Jupiter's gateway rate-limits a burst** — the first live run got
   429s after eight quick calls. The fix is pacing: ~1 request per
   second, spread inside and between quotes, so a run takes ~45 seconds —
   invisible at a 5-minute cadence. (A lesson in reading an API's limits
   from its behaviour, not its docs.)
2. **The spread varies ~70× across tokens**: SPYx and QQQx quote at
   0.03–0.06%, NVDAx at 0.10%, while PLTRx and INTCx cost ~2.7%. The
   reserve model currently prices the *gap* per symbol but not the *exit
   cost* — this series is what a future model needs to fix that.

The cron picked the new code up on its own and wrote its first spread
rows at 2:11 PM — verified unattended, which matters because it must run
alone all weekend.

**Holiday routing — the calendar gets honest.** ADR-019 knew weekdays
from weekends but treated every Monday alike; Labor Day (Monday Sep 7)
would have been routed "regular" while every venue was closed. Now
`sessions.py` learns the real trading days from Alpaca's calendar
endpoint, cached once per day. A non-trading weekday routes exactly like
a weekend — including the subtle case: the overnight session that starts
Sunday 8 PM trades *into* Monday, so the night before a holiday Monday is
closed too. If the calendar cannot be fetched at all, the router falls
back to plain weekday arithmetic, in which a holiday order harmlessly
queues at the broker — a failure mode chosen because it is the old
behaviour, not a new one.

Net effect: **Labor Day weekend runs Friday 8 PM → Tuesday 4 AM as one
continuous 72-hour engine window** — correct routing, and the richest
data-collection event the project has had, with the spread recorder
running through all of it.

Also on Sep 1: the weekend-trades panel dropped its engine jargon — each
trade now ends in one plain sentence ("The $0.16 the price moved against
you came out of the reserve: $22.27 of $22.43 came back") — and the
engine tests were rewired so the weekly parameter refresh can never break
the hand-checked cash figures.

---

## 8. What is not built yet

- **The scheduled settlement job** — settle every open weekend trade
  automatically at Monday 8:00 AM ET premarket, rolling to the 9:30
  auction. The engine's settle function is the job's body; the trigger is
  the missing piece.
- **The overnight verdict** — tonight's 8:05 PM sandbox test decides
  whether Alpaca's 24/5 session works for us, or those hours join the
  engine's window.
- **Research questions 3–5** — simulate the paper's cascade on the
  recorded weekends, off-hours tracking, engine-ledger reconciliation.
  (RQ2's data collection is running — §7.)
- **Azure deployment** — deliberately last (owner's call): ship when the
  app is essentially done. The checklist is in
  [PRODUCTION.md](PRODUCTION.md).

---

## 9. The reading map

| Doc | What it teaches |
| --- | --- |
| [YAGNUM-EXPLAINED.md](YAGNUM-EXPLAINED.md) | The concept: the problem, the hedge, the formulas, the cascade |
| [SIZING-THE-RESERVE.md](SIZING-THE-RESERVE.md) | The statistics: σ, z, the bell curve from the ground up, where the data lives |
| [JUPITER-FLOW.md](JUPITER-FLOW.md) | The token side: mints, decimals, quotes vs prices, the on-chain record |
| [WEEKEND-SIMULATOR.md](WEEKEND-SIMULATOR.md) | ★ The engine's lifecycle with real numbers, and how to drive the simulator |
| [DECISIONS.md](DECISIONS.md) | Every choice, numbered, with reasons — ADR-001 through ADR-021 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | The structural reference: routes, tables, phases |
| `docs/postman/` | Every API call, sendable by hand |

---

## 10. Say it back

1. What is the only thing the weekend simulator fakes? *(The calendar.)*
2. A customer weekend-sells and the price falls 1% by Monday. Walk the
   cash: who pays what, when? *(They are advanced Saturday's price
   immediately; Monday the real sale fills 1% lower; the 1% comes out of
   their reserve at release. They end at Monday's price — same as ADR-017
   promises — but they had the cash two days early.)*
3. Why is Invariant 1 "a query, not a promise"? *(Escrow moves are real
   tagged journals at the broker; summing them proves coverage without
   trusting our own bookkeeping.)*
4. Why does `research_params.json` carry a date? *(Because σ and z are
   measurements that go stale; the date says how stale, and each recorded
   weekend refreshes them.)*
