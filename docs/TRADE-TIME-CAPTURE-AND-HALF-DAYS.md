# Trade-time capture and half days

Two small changes, built 2026-10-13. The first one records more facts when a
weekend trade opens. The second one makes the session router know about
markets that close at 1:00 PM.

Code: `app/api/weekend.py` (`_capture_open_context`), `app/api/sessions.py`
(`scheduled_session`), migration `f6a7b8c9d0e1`.

The trade examples below use the numbers from the test suite
(`tests/test_weekend.py`), not a recorded trade. The dates in part 2 are the
real 2026 NYSE half days.

---

## 1. Trade-time capture

### 1.1 Bid, ask and mid at open

**ELI5.** A market stall has two prices for the same apple. It buys from you
at one price (the bid) and sells to you at a higher price (the ask). The
middle of the two is the mid. Before this change, we wrote down only the
price that the trader got. Now we write down both prices and the middle.

**Real example.** A trader sells 2 NVDA on a Saturday. Jupiter quotes a sell
of 2 NVDAx at $199.00. That is the bid and `p_open`. The engine then asks
Jupiter for a buy of the same size and gets $201.00. That is the ask. The mid
is $200.00. The row stores `open_bid = 199`, `open_ask = 201` and
`open_mid = 200`.

**The rule.** The trade's own quote is one side. The engine makes one more
quote, in the other direction, for the same size. It sizes the buy quote from
the first price, so it does not call the price API. The two quotes are 0.6
seconds apart, the same pause as the sampler's spread quotes.

**The trap.** The mid is not a price that anyone can trade at. Use it only to
measure. Also, the two quotes are not from the same instant. On a fast
market the mid can be a little wrong.

### 1.2 The share reference price

**ELI5.** The token copies a real share. To know if the token is cheap or
expensive, you look at the real share's last price.

**Real example.** On Saturday the last NVDA trade at Alpaca was $196.50 at
19:59:58 ET on Friday. The row stores `share_ref_price = 196.50`,
`share_ref_source = "alpaca_latest_trade"` and `share_ref_at` with that
time.

**The rule.** The engine does not use the Friday close anywhere. So the
reference is Alpaca's latest trade, and the source column says so.

**The trap.** On a weekend the latest trade is the last after-hours print,
not the 4:00 PM close. These two can be different. Always read
`share_ref_at` before you compare.

### 1.3 The basis

**ELI5.** The basis is how far the token's price is from the share's price,
as a fraction.

**Real example.** `open_basis = 200 / 196.50 - 1 = 0.0178`. The token was
1.78% above the share when the trade opened.

**The rule.** `open_basis = open_mid / share_ref_price - 1`. A positive
number is a premium. A negative number is a discount.

**The trap.** The basis uses the mid, not `p_open`. If you use `p_open`, you
mix half of the spread into the basis. The decomposition must keep the
basis and the spread apart.

### 1.4 The reserve inputs

**ELI5.** We already wrote down the numbers that made the reserve. Now we
also write down where they came from.

**Real example.** `sigma = 0.0270`, `sigma_source = "measured"`,
`params_generated_at = "2026-09-07T..."`.

**The rule.** `sigma`, `z` and `fees` were already stored. The two new
columns tell you whether sigma was measured for this symbol or was the
pooled fallback, and which version of `research_params.json` was used.

**The trap.** `research_params.json` changes after every weekend. Without
`params_generated_at` you cannot tell which version sized an old trade.

### 1.5 Failure never blocks the trade

**ELI5.** The extra facts are a diary. If the pen runs out, the trade still
happens.

**Real example.** Jupiter answers the second quote with a 429. The trade
opens normally, with the same escrow and the same advance. `open_ask`,
`open_mid` and `open_basis` are null, and the event trail has a
`context_partial` line with the reason.

**The rule.** Each part fails alone and stores null. The reason goes to the
log and to the trade's events. Nothing in the capture can raise.

**The trap.** Trades from before this change have null in all these columns.
The analysis must still use the sampler rows for those trades.

---

## 2. Half days

### 2.1 What a half day is

**ELI5.** Some days the stock market goes home early, at 1:00 PM instead of
4:00 PM. Examples are the day after Thanksgiving and Christmas Eve.

**Real example.** Friday 2026-11-27. Alpaca's calendar row for that day says
`"close": "13:00"`.

**The rule.** The router already reads Alpaca's calendar to find holidays.
Now it also reads each day's close time from the same rows.

**The trap.** Before this change the router thought regular hours were open
until 4:00 PM on a half day. An order at 2:00 PM went to the broker as a
regular order and only queued.

### 2.2 How the afternoon moves

**ELI5.** On a half day, the whole afternoon moves three hours earlier.

**Real example.** Friday 2026-11-27:

| Time (ET) | Session |
| --- | --- |
| 12:59 PM | regular |
| 1:01 PM | afterhours |
| 4:00 PM | afterhours |
| 5:00 PM | weekend |
| 8:00 PM | weekend |

**The rule.** Regular hours end at the close. After-hours lasts four hours
past the close: 4:00 to 8:00 PM on a full day, 1:00 to 5:00 PM on a half
day. On a Friday the weekend starts when after-hours ends. On a half day from
Monday to Thursday, the time after 5:00 PM is overnight, or weekend if
tomorrow is a holiday.

**The trap.** Christmas Eve 2026 is a Thursday, and Christmas Day is a
holiday. So from 5:00 PM on Christmas Eve the session is weekend, not
overnight. The overnight session would trade into a closed day.

### 2.3 When the calendar is missing

**ELI5.** If we cannot read the calendar, we guess that every weekday is a
normal full day.

**Real example.** Alpaca is down on 2026-11-27 and there is no cached copy.
At 2:00 PM the router says regular, as it did before this change.

**The rule.** The calendar is cached for a day, and yesterday's copy is kept
through an outage. Only a process with no copy at all falls back.

**The trap.** In that fallback, a half-day afternoon order queues at the
broker instead of going to the weekend engine. This is safe, but it is not
the best route.
