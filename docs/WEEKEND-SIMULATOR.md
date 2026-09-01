# The Weekend Simulator

How to trade a Saturday on a Tuesday — and what actually happens when you do.

Built 2026-08-31 (ADR-019). Everything below ran for real that afternoon;
the numbers are from those trades, not invented.

---

## 1. What it is, simply

**ELI5.** It is a flight simulator. The cockpit is real — the reserve
maths, the escrow, the cash movements, the state machine are the same code
that will run on a real Saturday. Only the window is a screen: one switch
tells the app "it is the weekend now," and the app believes it.

The lucky fact that makes this cheap: **Jupiter trades 24/7.** On a Tuesday
afternoon the "weekend" data source is fully live. We do not fake prices.
We only fake the calendar.

**For real.** A dev-only flag in `sessions.py` forces the effective session
to `weekend`. Every part of the app asks that one module what time it is,
so one flag flips the whole app: the market-status line, the after-hours
token panel, and the order ticket, which becomes the weekend ticket.

**The rule.** The override exists only when `APP_ENV=development`. In
production the switch, and the `/dev/clock` route behind it, do not exist —
a probe gets 404, not 403, so it learns nothing.

**The trap.** Simulation logic leaking into production paths. That is why
every override check funnels through two functions in one module
(`sessions.weekend_override`, `sessions.dev_override_allowed`) and nothing
else ever reads the flag.

---

## 2. The five windows (who executes when)

Every hour of the week has exactly one execution path (ADR-019):

| Window (ET) | Name | Who executes |
| --- | --- | --- |
| Mon–Fri 4:00 AM – 9:30 AM | premarket | Alpaca, limit + `extended_hours` |
| Mon–Fri 9:30 AM – 4:00 PM | regular | Alpaca, anything |
| Mon–Fri 4:00 PM – 8:00 PM | after-hours | Alpaca, limit + `extended_hours` |
| Sun–Thu 8:00 PM – 4:00 AM | overnight | Alpaca 24/5 (Blue Ocean ATS) — pending our sandbox test |
| Fri 8:00 PM – Sun 8:00 PM | **weekend** | **the ERR engine** |

The surprise from the research: Alpaca now covers 24/5, so the true dead
zone is 48 hours, not 65. Yagnum's engine exists for exactly those 48 hours
(plus market holidays, which route like weekends via Alpaca's calendar — ADR-021).

---

## 3. What happens when you place a weekend trade

The story of the first real run (Monday 2026-08-31, 1:19 PM ET, simulated
weekend, account `0ac3…`):

**Open — you click "Place weekend sell" for 2 NVDA.**

1. Jupiter is asked for an *executable* quote: what does selling exactly
   2 NVDAx pay right now? Answer: **$219.98 a share** (the bid; the
   last-swap price v3 showed was different — a quote for your size is the
   honest number). That becomes `p_open`.
2. The reserve is computed from measured inputs (ADR-018):
   `2 × $219.98 × 0.027 (NVDA's σ) × 3.7759 (pooled z) = $44.86` — about
   10.2% of the trade.
3. Two real journals move real sandbox cash, tagged so the escrow position
   is a query at the broker:
   - **escrow**: $44.86 from you to the firm account
   - **advance**: $439.97 from the firm to you — *you sold now, you are
     paid now*. This immediacy is the product.

   State: `provisional`. Net cash to you at this moment: $395.11.

**Settle — the market reopens (in the simulator: it never closed).**

4. The engine sells your 2 real shares at the broker. Fill: **$219.76** —
   the first regulated price, `p_close`.
5. The fill's $439.52 is swept to the firm (it repays the advance), and the
   escrow comes back **with the true-up**:
   `$44.86 + 2 × (219.76 − 219.98) = $44.41`.
6. Add it up: you ended with exactly `2 × $219.76` — the regulated price,
   per ADR-017. Yagnum ended flat. Every step is a row in
   `weekend_trade_events` carrying the Alpaca journal or order id.

**The rule.** `released = reserve + qty × (p_close − p_open)` for a sell
(sign flipped for a buy). Price moved your way → you get the move on top of
the whole reserve. Price moved against you → the move comes out of the
reserve.

**The trap.** Thinking the reserve is a fee. It is not — it is your own
money, held as collateral, and in the run above $44.41 of $44.86 came back.
What it costs you is *the weekend's price move*, which is the honest price
of selling before the market can.

---

## 4. The two ways a trade settles in dev

**Real resolution (`mode=market`, the default button).** The engine places
a real order — market in regular hours, marketable limit with
`extended_hours` in premarket/after-hours, the same shape overnight — waits
briefly for the fill, reconciles. On a dev weekday this takes seconds, so
you watch the entire lifecycle live. This is the strongest test: nothing is
mocked.

**Injected gap (`mode=injected`, the % box).** The weakness of real
resolution in dev: seconds pass between open and settle, so the gap is
nearly zero and the reserve barely moves. You would wait months for a real
4σ Monday. The gap box fixes that: `p_close = p_open × (1 + gap)`, no order
placed, only the escrow half of the books runs.

The crash test from today: a weekend **buy** of 1 NVDA at $220.06 (the ask
— note the live $0.08 spread against the bid), reserve $22.44, injected
gap **+12%**:

- pretend Monday price: $246.47
- true-up: −$26.41 — *more than the whole reserve*
- result: state `breached`, $0 returned, **$3.97 debited beyond the
  escrow** — collateral, not a cap (ADR-017), demonstrated in one click.

**The trap (known artifact).** Injected mode never trades the real shares —
a "sold" position is still in the account afterwards, and the books do not
fully balance on purpose. It demonstrates the gap arithmetic, nothing else.
Use small quantities; reset-balance cleans up.

---

## 5. Using it

1. Run the API with no `APP_ENV` set (development is the default) and open
   any xStock's trade page (NVDA, AAPL, TSLA…).
2. The amber **Dev clock** pill sits next to the market status. Click
   **Weekend**. The page flips: "Simulated weekend", the after-hours token
   panel appears, the ticket becomes **Weekend trade**.
3. Sell needs shares (buy some in Real time first); buy needs cash for
   notional + reserve. Whole shares only, 1–1,000.
4. The ticket shows the arithmetic before you confirm: the executable
   Jupiter price for your size, the notional, the reserve and its %, and
   "cash to you now". Place it.
5. It appears under **Weekend trades** as `Open (weekend)` with two
   buttons: **Settle at the real market** and **inject a gap of __%**.
6. Everything the trade did is auditable: `GET /weekend/orders/{id}`
   returns the event trail with Alpaca journal ids; the journals themselves
   are visible in History (they are real JNLC entries tagged
   "ERR escrow - weekend trade N").

Note: the override lives in process memory. Restarting the API (or its
`--reload` picking up a code change) resets the clock to real time —
by design, a simulator should never survive into a session nobody asked
it to be in.

---

## 6. Tonight's two experiments (2026-08-31)

The simulator is built; two facts about the *real* extended sessions still
need measuring, and only the clock can run these:

**5:00 PM ET — after-hours.** Place an extended-hours limit order (the new
checkbox on the regular ticket), and settle a weekend trade with
`mode=market` so the hedge goes out as a marketable limit with
`extended_hours=true`. Question: does the sandbox actually fill in the
4–8 PM window, and how fast?

**8:05 PM ET — overnight (the ADR-019 blocker).** Place a 1-share limit
order after 8 PM. Alpaca's 24/5 session needs enablement by their team on
real accounts; the sandbox may (a) fill it via Blue Ocean, (b) queue it to
tomorrow 4 AM, or (c) reject it. Whichever happens decides the routing
table's overnight row: Alpaca if it works, otherwise the weekend engine's
window grows by those hours until it does.

---

## 7. Say it back

1. Only one thing is faked in the simulator. What is it, and what stays
   real? *(The calendar. Prices, quotes, journals, orders, the state
   machine — all real.)*
2. Your weekend sell settles Monday at a price 1% below your `p_open`.
   Who absorbs that 1%? *(You do — out of your reserve. You always end at
   the first regulated price; the reserve exists so that ending there is
   guaranteed to be payable.)*
3. Why does the injected-gap mode exist when real resolution is more
   honest? *(Because in dev the real gap is seconds wide. Only an injected
   gap can show the reserve absorbing — or failing to absorb — a monster
   Monday.)*
4. Why does the reserve for 1 NVDA (~$22) differ from 1 MCD (~$1.35 at the
   same price)? *(σ is per symbol — NVDA's measured weekend swing is about
   four times MCD's. The z multiplier is shared.)*
