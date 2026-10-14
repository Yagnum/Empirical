# Research collection: four new data series

The price recorder (`app/api/sampler.py`) now collects four more series
next to the token prices. This page explains each one: what it is, a
real example, the rule the code follows, the trap to avoid, and the
research question it serves.

The research questions are in `docs/CAPSTONE.md`, section 6:

- **RQ1.** How large is the weekend gap?
- **RQ2.** What does weekend liquidity cost?
- **RQ3.** Does the reserve cover the gap?
- **RQ4.** Does the token lead or lag the share?
- **RQ5.** What would a firm-price product cost?

Start the series well before the holidays. The market is closed on
2026-11-26 and 2026-12-25, and on 2027-01-01. On 2026-11-27 it closes
early, at 1:00 PM. These days are natural experiments: the token trades
but the share does not. Pyth's own schedule string lists the same dates.

---

## How one run works

The GitHub cron starts `scripts/sample_prices.py --write`. The cron is
"best effort". We see about six runs a day, not one every five minutes.

One run does this, in this order:

1. Get the token list (all xStocks, plus the eight Ondo tokens).
2. Get all prices from Jupiter in one call.
3. Get the last trade of each real share and the market clock from Alpaca.
4. Get a $1,000 buy and sell quote for each token (the spread).
5. Write the share trades (series D). This needs no extra call.
6. Get the Pyth oracle prices (series C). This needs one call, and only
   when `PYTH_API_KEY` is set.
7. If the last ladder is 55 minutes old or older, get the depth ladder
   (series B).

Steps 5, 6 and 7 are each in their own `try`. If one fails, the run logs
one line and continues. The token prices are written first, in their own
transaction. A failure in a new series can never lose a token price.

### Calls and time per run (measured live, 2026-10-13)

| Part | Extra calls per run | Extra time |
|---|---|---|
| A. Ondo tokens (8 tokens x 2 spread quotes) | +16 Jupiter | about +25 s |
| B. Depth ladder (12 tokens x 2 sizes x 2 sides) | +48 Jupiter, at most once an hour | about +78 s |
| C. Pyth oracle | +1 Pyth (0 without a key) | under 1 s |
| D. Share trades | +0 market data, +1 Alpaca calendar | under 1 s |

A full run with the ladder took 157 seconds. There were no 429 errors.
A run without the ladder took 79 seconds. Before this change a run took
about 45 seconds (the figure in `sampler.py`). These times are on a
laptop. The workflow timeout is now 8 minutes (it was 5).

Because the cron is sparse, the ladder runs on almost every real run.
To make runs shorter, set the `LADDER_SYMBOLS` environment variable to a
shorter list.

### Settings

All settings are in `config.py`. You can change them with environment
variables:

| Variable | Default | What it does |
|---|---|---|
| `LADDER_SYMBOLS` | `SPYx,QQQx,NVDAx,TSLAx,AAPLx,METAx,SPYon,QQQon,NVDAon,TSLAon,AAPLon,METAon` | The tokens that get the ladder |
| `LADDER_SIZES_USD` | `10000,50000` | The ladder sizes, in dollars |
| `LADDER_MIN_INTERVAL_MINUTES` | `55` | The minimum time between two ladders |
| `PYTH_API_KEY` | empty | The Pyth key. If it is empty, series C is skipped. |
| `PYTH_HERMES_URL` | `https://pyth.dourolabs.app/hermes` | The Pyth price service |

### Run it yourself

From `app/api`:

```
uv run python scripts/sample_prices.py            # dry run: print, write nothing
uv run python scripts/sample_prices.py --ladder   # dry run, with the ladder
```

A dry run never writes to the database.

---

## The trap that affects every series: the multiplier

Read this first. It changes how you read the `bid_usd` and `ask_usd`
columns.

**ELI5.** Some companies pay a dividend. A token issuer can pass the
dividend to you in two ways: give you more tokens, or make each token
count for a little more. xStocks and Ondo both do the second. Each token
has a hidden number, the *multiplier*. It starts at 1.0 and goes up a
little with each dividend.

**Real example.** NVDAx on 2026-10-13:
- multiplier = 1.0017012
- Jupiter's `usdPrice` = 229.61 (this is per share)
- Jupiter's price per raw token = 230.00

The difference is 0.17%. For one xStock the multiplier is 1.0212, so
the difference is 2.1%.

**Rule.**
- shares = raw tokens x multiplier
- price per share = price per raw token / multiplier

When the scheduled `newMultiplier` date has passed, the new multiplier
is in force. Jupiter's own numbers agree with this.

**The trap.** Swap quotes count in *raw* tokens. So since ADR-020,
`token_prices.bid_usd` and `ask_usd` are per raw token, but `usd_price`
is per share. If you compare them directly, you get a false gap of up
to 2%. The spread itself (ask divided by bid) is correct, because both
legs are raw.

**What changed.**
- `token_prices.ui_multiplier` now records the multiplier on each new
  row. To get the per-share bid, calculate `bid_usd / ui_multiplier`.
- Older rows have no multiplier. Treat them with care.
- The new ladder table stores the per-share price directly.
- The $1,000 sell leg is now sized at about $1,000 of raw tokens. Before,
  it was sized up to 2% off. This changes the quoted size, not how the
  price is calculated.

---

## A. Ondo tokens beside xStocks

**Serves:** RQ1 and RQ2 (a second issuer as a control). It also serves
RQ4.

**ELI5.** Two companies sell a "token copy" of NVIDIA stock. Backed
sells NVDAx. Ondo sells NVDAon. You can turn an Ondo token back into
cash with Ondo at any time, even on a Sunday. You cannot do this with an
xStock. If that matters, the Ondo token should stay closer to the fair
price on weekends. We record both, side by side, to find out.

**Real example** (live run, 2026-10-13, 20:58 ET, market closed):

| Token | Jupiter price | Last NVDA trade | Gap | $1,000 spread | Jupiter liquidity |
|---|---|---|---|---|---|
| NVDAx | 229.34 | 229.20 | +0.06% | 0.04% | $1.6M |
| NVDAon | 228.53 | 229.20 | -0.29% | 105.8% | $2.7k |

**Rule.**
- Each Ondo token gets the same row as an xStock in `token_prices`: the
  price, the $1,000 spread and the share's last trade.
- The new column `issuer` is `'xstocks'` or `'ondo'`. Old rows get
  `'xstocks'`.
- Rows are told apart by `symbol` (NVDAx, NVDAon). Both rows have
  `underlying = 'NVDA'`, and nothing collides.
- The Ondo list is fixed in `jupiter.ONDO_TOKENS`. It is not a live
  search. Jupiter's search for "NVDAon" returns one real token and about
  twenty fakes.

**Verified mints.** Checked on 2026-10-13. Three sources agree on each
mint:

1. Ondo's official token sheet, linked from
   <https://docs.ondo.finance/addresses> (the "Solana Deployed Address"
   column).
2. Jupiter's token API (tags `ondo` and `verified`).
3. The mint account on Solana mainnet: the Token-2022 program, 9
   decimals, the same on-chain symbol, and the same mint authority
   `9foMHsSDq7nMg4WPusSz9eY7tyxyukqborA8GyU5cUxD`.

| Symbol | Mint | Decimals | Program |
|---|---|---|---|
| SPYon | `k18WJUULWheRkSpSquYGdNNmtuE2Vbw1hpuUi92ondo` | 9 | Token-2022 |
| QQQon | `HrYNm6jTQ71LoFphjVKBTdAE4uja7WsmLG8VxB8ondo` | 9 | Token-2022 |
| NVDAon | `gEGtLTPNQ7jcg25zTetkbmF7teoDLcrfTnQfmn2ondo` | 9 | Token-2022 |
| TSLAon | `KeGv7bsfR4MheC1CkmnAVceoApjrkvBhHYjWb67ondo` | 9 | Token-2022 |
| GOOGLon | `bbahNA5vT9WJeYft8tALrH1LXWffjwqVoUbqYa1ondo` | 9 | Token-2022 |
| CRCLon | `6xHEyem9hmkGtVq6XGCiQUGpPsHBaoYuYdFNZa5ondo` | 9 | Token-2022 |
| AAPLon | `123mYEnRLM2LLYsJW3K6oyYh8uP1fngj732iG638ondo` | 9 | Token-2022 |
| METAon | `fDxs5y12E7x7jBwCKBXGqt71uJmCWsAQ3Srkte6ondo` | 9 | Token-2022 |

AAPLon and METAon are added because they are the Ondo twins in the
depth ladder. All eight use the multiplier.

**The trap.** Ondo's 24/7 mint and redeem happens in Ondo's own app. It
does not happen on Jupiter. On Jupiter, the Ondo tokens are almost
empty: TSLAon had $0.95 of liquidity, and METAon's "last price" was
$1,908 for a $762 share. So this series measures *Ondo's secondary
market on Solana DEXes*. It does not measure Ondo's redemption price.
Write that in the paper.

Two more things:
- Queries that use `where underlying is not null` (for example in
  `notebooks/gap-volatility.ipynb`) now also return Ondo rows. Add
  `and issuer = 'xstocks'` to keep the old meaning.
- Ondo's own price API (`api.gm.ondo.finance`) answers 403 without a
  key. It is future work.

---

## B. The depth ladder

**Serves:** RQ2 (does the weekend cost more at size?) and RQ5 (what a
firm price costs at size).

**ELI5.** You buy one apple at the market price. You try to buy a
thousand apples, and the seller runs out of cheap apples, so each one
costs more. The ladder asks Jupiter: "What price would I get for
$10,000? And for $50,000?" The larger the step up from the $1,000 price,
the thinner the market.

**Real example** (2026-10-13, per share):

| Token | $10k buy | $10k sell | $50k buy | $50k sell |
|---|---|---|---|---|
| NVDAx | 229.42 | 229.27 | 229.61 | 229.15 |
| AAPLx | 342.21 | 339.86 | 344.14 | 337.70 |
| NVDAon | 3,163.52 | 176.18 | 10,351.15 | 41.54 |

NVDAx barely moves at $50,000. AAPLx moves about 1% each way. NVDAon
has no real depth.

**Rule.**
- The ladder runs for `LADDER_SYMBOLS` and `LADDER_SIZES_USD`, a buy
  and a sell for each.
- It runs only when the newest `quote_ladder` row is 55 minutes old or
  older. The gate is in the data, not in the cron schedule, because the
  cron is sparse.
- There is a 2-second pause before the ladder and 1.1 seconds between
  calls.
- At the first HTTP 429, the ladder stops for this run and writes one
  `rate_limited` row.
- Each rung is a row, also when it fails. `status` is `ok`, `no_route`,
  `rate_limited` or `error`. A `no_route` at $50k is itself a depth
  observation.
- `price_usd` is per share (the multiplier is applied). `in_amount` and
  `out_amount` are the raw base units, exactly as Jupiter sent them.
- Table `quote_ladder` has these columns: `sampled_at`, `symbol`,
  `issuer`, `underlying`, `mint`, `size_usd`, `side`, `status`,
  `in_amount`, `out_amount`, `share_amount`, `usd_amount`, `price_usd`,
  `price_impact_pct`, `ui_multiplier`, `route`, `error`.

**The trap.**
- A `rate_limited` row means "we do not know". It does not mean "no
  depth". Leave it out of the impact analysis.
- The ladder's `sampled_at` is the run's start time. The quotes
  themselves come one to two minutes later.
- A dry run does not run the ladder unless you pass `--ladder`.

---

## C. The oracle record

**Serves:** RQ1 and RQ3. It shows that "the price everyone else uses"
freezes while the token moves. It also adds context to RQ5.

**ELI5.** A lending app on Solana must know what your NVDA token is
worth. It asks an *oracle*, a service that posts prices on-chain. Pyth's
normal stock oracle only updates while the stock exchange is open. From
Friday at 4 PM to Monday at 9:30 AM it keeps showing Friday's price,
while the token moves. We record what the oracle says each run, to show
how far it drifts.

**Real example.** Pyth's own schedule for NVDA is
`America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;…1126/C,1127/0930-1300,…1225/C,0101/C`.
That is weekdays 9:30 to 16:00, closed on weekends, closed on 11-26,
closing early on 11-27, and closed on 12-25 and 01-01. On a Saturday,
`publish_time` will still show Friday afternoon.

**Rule.**
- There is one Hermes call per run for 16 feeds: the regular feed and
  the "24/7" index feed for SPY, QQQ, NVDA, TSLA, AAPL, META, GOOGL and
  CRCL.
- Table `oracle_prices` stores: `provider`, `symbol`, `feed_kind`
  (`regular` or `index_24_7`), `feed_id`, `feed_symbol`, the raw
  integers `price`, `conf` and `expo`, the exact dollar values
  `price_usd = price x 10^expo` and `conf_usd`, and `publish_time`.
- A feed that Pyth does not return is left out. It is never stored as
  zero.

**Feed ids.** Checked on 2026-10-13. Two Pyth sources agree on each id:
`hermes.pyth.network/v2/price_feeds` and
`benchmarks.pyth.network/v1/price_feeds`. For SPY and NVDA there is a
third source: the Pyth account on Solana derived from the id holds the
same id.

| Symbol | Regular (`Equity.US.X/USD`) | 24/7 (`Equity.Index.X/USD`) |
|---|---|---|
| SPY | `19e09bb805456ada3979a7d1cbb4b6d63babc3a0f8e8a9509f68afa5c4c11cd5` | `f32c3fbdd20b846bb53395bf175c42955e00b1bffb5a778bb624982b318f5461` |
| QQQ | `9695e2b96ea7b3859da9ed25b7a46a920a776e2fdae19a7bcfdf2b219230452d` | `6d595efb30db0e0139f254eb40985c8695e7ed7e5856287cb5084d2d7794b7eb` |
| NVDA | `b1073854ed24cbc755dc527418f52b7d271f6cc967bbf8d8129112b18860a593` | `a470c4ac46f44b547b2cba52338f311fb642b79375ce5f0cfd5cb5b99227b852` |
| TSLA | `16dad506d7db8da01c87581c87ca897a012a153557d4d578c3b9c9e1bc0632f1` | `e6da44bff5b8b06897a3739dd331b440d6662595bb862e37046892c568ae3fc0` |
| AAPL | `49f6b65cb1de6b10eaf75e7c03ca029c306d0357e91b5311b175084a5ad55688` | `aaba35e6f33fb973bb2201d48a79ae24795affa6ba8bd50a93dcaf7da0030f36` |
| META | `78a3e3b8e676a8f73c439f5d749737034b139bbbe899ba5775216fba596607fe` | `2cc0c022f7f37920485a5947f3cea8633783b6cb7fff6d94ee52f48687b7783d` |
| GOOGL | `5a48c03e9b9cb337801073ed9d166817473697efff0d138874e0f6a33d6d5aa6` | `ad519718d387de4f0d7d29ea16a3730ce42e49c59fef6fba6fc9bac477645f6f` |
| CRCL | `92b8527aabe59ea2b12230f7b532769b133ffb118dfbd48ff676f14b273f1365` | `59751961c9aa1943ece2d3e9060070d8d665a99a28642e4b10fcae972c10b833` |

**The trap: Pyth needs a key now.** Since the Pyth Core upgrade on
2026-08-26, every Hermes price endpoint answers `401 unauthorized`
without a key. This is true for `hermes.pyth.network` and for the new
`pyth.dourolabs.app/hermes`. We tested it on 2026-10-13. Only the feed
list is still public.

To get a key, sign up at Pyth Terminal (<https://pythdata.app/signup>).
It has a free trial, then paid plans. Then add the key as the GitHub
secret `PYTH_API_KEY`. Until you do, series C is skipped. The log says
so on each run, and everything else still records.

**Also checked, not used:**
- Pyth's on-chain price accounts on Solana can be read with no key. But
  the equity accounts stopped updating at 2026-08-26 15:54 UTC (the
  upgrade), while BTC's account still updates. They are a frozen record,
  not a live source.
- The "24/7" index feeds have a schedule string that still says
  0930-1600. Whether they really move on a Saturday is what
  `publish_time` will tell us. Do not assume it before you see the data.

**Chainlink: future work.** We found no free HTTP endpoint that needs no
key for Chainlink equity prices. Chainlink Data Streams needs
credentials. Reading Chainlink feeds on-chain needs a feed address for
each chain, and we did not check them.

---

## D. Extended-hours share prints

**Serves:** RQ4 (does the token lead the share?).

**ELI5.** To know if the token "moves first", we need the share's
prices at the same moments, including early morning (premarket, 4:00 to
9:30 AM ET) and evening (after hours, 4:00 to 8:00 PM ET). We now save
the share's latest trade on each run. Each row says when the trade
happened, which data feed it came from, and which session it fell in.

**Real example** (run at 20:58 ET on 2026-10-13):

| Share | Price | Trade time (UTC) | Session | Conditions |
|---|---|---|---|---|
| NVDA | 229.20 | 20:13:50 | afterhours | `@,T` |
| QQQ | 743.50 | 20:51:41 | afterhours | `@,T` |
| AAPL | 341.33 | 19:59:59 | regular | `@` |

`T` is the extended-hours condition code.

**What Alpaca gives us (tested live on 2026-10-13):**

| Request | Result |
|---|---|
| Latest trade, `feed=iex` | Works, includes extended-hours prints. This is the default answer too. |
| Latest trade, `feed=sip` / `overnight` / `boats` | 403: "subscription does not permit" |
| 1-minute bars, `feed=sip`, older than 15 minutes | Work, and they are dense. |
| 1-minute bars, `feed=iex` | Work, but are thin. |

How dense are the 1-minute bars before the open (04:00 to 09:30 ET,
2026-10-13)?

| Share | SIP bars | IEX bars | First IEX bar (ET) |
|---|---|---|---|
| NVDA | 320 | 4 | 08:42 |
| SPY | 299 | 3 | 08:53 |
| TSLA | 291 | 4 | 08:35 |

**Rule.**
- Table `share_trades` has one row per share per run: `symbol`,
  `feed = 'iex'`, `price`, `size`, `trade_at`, `exchange`, `conditions`
  and `session`.
- `session` uses the names from `sessions.py`: premarket, regular,
  afterhours, overnight, weekend. A market holiday is labelled
  "weekend".
- The sampler already fetched these trades for `token_prices`, so this
  costs no extra market-data call. The feed is now pinned to IEX, so
  each row can say where it came from. On this plan the values are the
  same as before.

**The trap.**
- IEX is a single small exchange. After hours and before the open it
  prints rarely. A "latest trade" can be an hour old. Always use
  `trade_at`, not `sampled_at`.
- With about six runs a day, this series is sparse anyway.

**The better source for RQ4.** The dense share data for RQ4 is the SIP
1-minute bars, and they are not perishable. Alpaca keeps them, so we
can backfill them at any time after the fact. `backfill.py` currently
asks for `feed=iex`. Switching the Monday-morning backfill to
`feed=sip`, with its own `source` value, will unblock the share side of
RQ4. `docs/CAPSTONE.md` section 13 says "No premarket share data on the
free feed". That is true for IEX only. Do this soon, before the
November holidays. It needs a key change on `market_bars`, which
currently has a unique key on (symbol, timeframe, bucket_start) with no
feed.

---

## Tables at a glance

| Table | New? | One row per | Written |
|---|---|---|---|
| `token_prices` | 2 new columns: `issuer`, `ui_multiplier` | token per run | every run |
| `quote_ladder` | new | token x size x side per ladder | at most once per 55 min |
| `oracle_prices` | new | Pyth feed per run | every run with a key |
| `share_trades` | new | share per run | every run Alpaca answers |

Migration: `alembic/versions/a7b8c9d0e1f2_research_collection_series.py`.
It only adds columns and tables, so no existing row changes meaning.
