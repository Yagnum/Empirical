# Simulated traders

Eight personas, each a language model with a real sandbox brokerage
account, trading through the same engine a person uses. What they are
evidence of, what they are not, and how to run them.

Built 2026-09-04 (ADR-026). Provisioned that afternoon: eight accounts,
$50,000 each, a $25,000 starter basket bought in the after-hours session.

---

## 1. What it is, simply

**ELI5.** Crash-test dummies. They sit in real seats and go through the
real crash, so the car gets tested; nobody pretends the dummy chose the
route. The personas place real orders in the real sandbox and their
weekend trades go through the real ERR engine. The engine is what gets
tested.

**The rule.** *The model never touches money.* It reads a briefing and
answers with one JSON wish: buy, sell, or hold, one symbol, one quantity,
a reason. The wish goes through the same door a person's order would, and
the engine's own checks accept or refuse it.

**The trap.** A persona's choice is not evidence about markets. "Maya
sold 4 NVDA at 2 PM Saturday" tells you nothing about Monday's price;
Monday does not know who ordered. What the population produces is
evidence about the **engine**: many trades at once, real reserves against
real true-ups at real sizes, refusals, lock conflicts, a settlement run
with dozens of open rows, and under ADR-025 the shadow hedge's cost for
each one.

---

## 2. The personas

| Name | Style | Watches |
| --- | --- | --- |
| Maya | Momentum: buys what is moving, cuts losers fast | NVDA, TSLA, COIN, MSTR, HOOD |
| Walter | Patient value: buys dips in big names, almost never sells | AAPL, MSFT, GOOGL, AMZN, MCD |
| Dev | High risk, odd hours, full-cap swings | GME, MSTR, COIN, CRCL, TSLA |
| Priya | Index rebalancer, avoids wide spreads | SPY, QQQ, GLD, AAPL |
| Ken | Contrarian: sells strength, buys weakness | META, NVDA, AVGO, AMZN, MSFT |
| Lena | Execution cost first: trades only tight spreads | MSFT, AAPL, SPY, QQQ, NVDA |
| Omar | Weekend trader: positions ahead of Monday | GOOGL, META, HOOD, TSLA, AVGO |
| Sam | Mean reversion over the weekend | NVDA, TSLA, AAPL, MSTR, GLD |

The persona text is the whole personality. It is stored on the row and
sent as the system prompt before every decision, followed by the rules of
the current session and the answer format.

---

## 3. One decision, step by step

1. **Briefing.** The time in New York and which window it is; cash;
   positions with average cost; open weekend trades; and for each
   watched symbol the token price, the move over one hour, 24 hours, and
   since the last regular-hours print, the executable spread, and that
   symbol's reserve percentage. All of it from the sampler's rows and the
   broker, none of it from the model.
2. **Ask.** One call to Groq in JSON mode. The answer, the model name,
   token counts and latency are stored.
3. **Check.** The JSON is parsed and bounded: action in {buy, sell,
   hold}, symbol on the watchlist, quantity positive, at most 100 shares
   and $10,000. Anything else is stored as an unusable answer and nothing
   happens.
4. **Route.** Weekend: `weekend.open_trade` with `source="sim"`. Regular
   hours: a market day order. Premarket or after hours: a marketable limit
   day order in whole shares with `extended_hours`. Overnight: skipped,
   that window queues at the broker (ADR-024).
5. **Record.** The outcome: `weekend_trade`, `order`, `hold`, `refused`
   (the engine said no and why), `skipped`, or `error`.

Every field of every step lands in `sim_decisions`. The decision process
is part of the dataset.

---

## 4. Pacing

Groq's free plan (checked 2026-09-04) allows the `openai/gpt-oss-120b`
model 30 requests a minute, 1,000 a day, 8,000 tokens a minute and
200,000 tokens a day. A decision costs about 2,000 tokens. So:

- The cron runs hourly, at minute 7.
- Personas take turns in two groups by the hour's parity. Each persona
  decides every two hours.
- Within a tick the calls are 20 seconds apart.
- A 429 from Groq stops the tick; the next hour tries again.

That is about 100 decisions a day, under the cap with room for retries.
Upgrade the plan and the cadence can rise; the code has one constant for
each of those numbers.

---

## 5. Running it

```
uv run python scripts/sim_users.py provision --cash 50000 --seed 25000
uv run python scripts/sim_users.py tick              # dry run: briefings only
uv run python scripts/sim_users.py tick --write      # ask and act (this hour's group)
uv run python scripts/sim_users.py tick --write --everyone
uv run python scripts/sim_users.py status
```

`provision` is idempotent: a persona that exists is left alone. The
GitHub Actions job `sim-users.yml` runs `tick --write` hourly and fails
visibly when `GROQ_API_KEY` is missing, rather than inventing decisions.

Useful queries:

```sql
-- what the population did this weekend
select u.name, d.at, d.session, d.action, d.symbol, d.qty, d.outcome, d.ref, left(d.reason, 80)
from sim_decisions d join sim_users u on u.id = d.sim_user_id
order by d.at desc;

-- sim trades only, with their hedge cost
select t.id, t.side, t.qty, t.symbol, t.p_open, t.state, h.gas_usd, h.version_b_pnl
from weekend_trades t left join hedge_legs h on h.trade_id = t.id and h.leg = 'close'
where t.source = 'sim';
```

---

## 6. Say it back

1. What can a persona never do? *(Move money. It emits a JSON wish; the
   engine decides.)*
2. Why is a sim trade tagged `source = 'sim'`? *(So research queries can
   include or exclude them on purpose. The engine treats both the same.)*
3. What is the population evidence of? *(The engine under load and the
   hedge's cost per trade. Not the market.)*
4. Why every two hours and not every five minutes? *(The free plan's
   200,000 tokens a day at about 2,000 per decision.)*
