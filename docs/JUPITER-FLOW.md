# The Jupiter flow, from "which token?" to "it is on the chain"

This document explains how a trade on Jupiter works, step by step, with the
real numbers we saw on 2026-08-28. It then explains how Yagnum will use
these steps for a weekend trade, and what Yagnum deliberately never does.

**How to read it.** Each concept follows the same four beats:

1. **Simply** — the idea in everyday terms.
2. **For real** — the same idea with the actual API call and numbers.
3. **The rule** — the precise statement you can rely on.
4. **The trap** — the mistake people make with it.

Read one section at a time. Each one adds one idea. The last section asks
you to say it all back in your own words.

---

## 0. What Jupiter is

**Simply.** Jupiter is a price-comparison site for tokens that also does the
buying. You say "I want to turn 1,000 dollars-tokens into NVDA-tokens", and
it looks across every pool on Solana, finds the cheapest path, and builds
the transaction for you.

**For real.** Jupiter is a *DEX aggregator* on the Solana blockchain. A DEX
(decentralized exchange) is a program on the chain that holds a *pool* of
two tokens and sets a price by a formula. Many pools exist for the same
pair. Jupiter's job is routing: pick the pool, or chain of pools, that gives
the most output for your input. It does not hold your money.

**The rule.** Jupiter quotes and routes. A pool executes. A wallet signs.
Three different parties.

**The trap.** Calling Jupiter "an exchange" and expecting an order book with
bids and asks like NASDAQ. There is no order book. Section 4 explains what
replaces it.

---

## 1. Step one: find the token, and make sure that it is the real one

**Simply.** Anyone can create a token and name it "NVDAx". The name proves
nothing. A token's real identity is its *mint address*, a long string like a
serial number. The real NVDAx has exactly one.

**For real.** We ask Jupiter's token search:

```
GET https://lite-api.jup.ag/tokens/v2/search?query=xStock
```

One entry of the reply, trimmed:

```json
{
  "id": "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh",
  "name": "NVIDIA xStock",
  "symbol": "NVDAx",
  "decimals": 8,
  "mintAuthority": "7pt9tkctJPK7PPNQJ77GKg8ZffSF6QxoMiCFYHxrtaCj",
  "usdPrice": 220.24,
  "liquidity": 1623912.58,
  "holderCount": 65788
}
```

Three fields matter:

- `id` is the mint address. This is the identity we store and pass to every
  later call. Our code stores it in `token_prices.mint`.
- `mintAuthority` is the account allowed to create new tokens. For a real
  xStock this is Backed Finance's issuer account. Every real xStock shares
  the same authority; a fake would not.
- `decimals` is the subject of section 2.

"Verified" in our code means: the name ends in "xStock", the symbol ends in
"x", and — the check that matters — the mint address matches the one Backed
publishes. We cross-check the address against Backed's official list, and
GeckoTerminal shows its main pool holding about $1.6 million, which a fake
would not have.

**The rule.** Identify a token by its mint address, never by its symbol.

**The trap.** Searching "NVDAx" and taking the first result. Scam tokens
copy names on purpose. Our `jupiter.is_xstock` filter plus the address
check is what stands between the app and a fake.

---

## 2. Step two: decimals — how a token counts

**Simply.** A dollar is 100 cents, and a computer that handles money counts
cents, never fractions of a dollar. Every token does the same, but each
token chooses its own "cent". USDC chose a millionth (six decimal places).
NVDAx chose a hundred-millionth (eight). SOL chose a billionth (nine). The
chain only ever sees whole numbers of these tiny units.

**For real.** How do we *know* USDC has 6 and NVDAx has 8? We do not
memorize it. **The token declares it on the chain.** Every token's mint
account carries a `decimals` field, set once by its issuer at creation.
The token search returned `"decimals": 8` for NVDAx; the same field for
USDC returns 6. Our code reads the field and stores it; it never assumes.

Why do they differ? The issuer picks a granularity that fits the asset.
USDC copied the dollar's cents and added four more places for fee math.
Backed chose eight for xStocks so that a fraction of a share can be as small
as 0.00000001. SOL uses nine, a convention from Solana's earliest days.
There is no rule that they match, so a program must carry each token's own
number.

The conversion, in both directions:

```
base units  =  human amount × 10^decimals
human amount =  base units ÷ 10^decimals
```

Real numbers from a quote we ran:

| Token | Human amount | decimals | Base units sent or received |
| --- | --- | --- | --- |
| USDC | 1,000 | 6 | `1000000000` |
| NVDAx | 4.5662917 | 8 | `456629170` |

And the effective price is a ratio of two human amounts:

```
(1000000000 ÷ 10^6) ÷ (456629170 ÷ 10^8)  =  1000 ÷ 4.5662917  =  218.9961 USDC per NVDAx
```

**The rule.** Read `decimals` from the token, convert with exact decimal
arithmetic (Python's `Decimal`, our ADR-010), and keep amounts as integers
until the moment a person needs to read them.

**The trap.** Two traps. First, mixing up the exponents: dividing NVDAx's
base units by 10⁶ instead of 10⁸ reports 100 times too many tokens. Second,
using floating-point numbers: `456629170 / 1e8` in a float is
4.566291699999999..., and a ledger that is off in the last digit is a
ledger that does not balance. There is a third, subtle one: xStocks carry a
*scaled UI amount* multiplier (about 1.0001 for NVDAx today) that adjusts
displayed balances for dividends. Jupiter's prices already include it; a
program that reads raw wallet balances must apply it.

---

## 3. Step three: price versus quote

**Simply.** A price is what the last person paid. A quote is what *you*
would pay, right now, for *your* amount. They differ, because your trade
moves the pool a little, and because a quote is a promise for a few seconds
while a price is a memory.

**For real.** Two endpoints:

```
GET https://api.jup.ag/price/v3?ids=<mint>            → usdPrice 220.24 (last swap, any size)
GET https://lite-api.jup.ag/swap/v1/quote?...&amount=… → outAmount for this exact size and direction
```

The price feeds our panel and our sampler, because they only need to
*observe*. The quote is what a trade uses, because a trade needs a number it
can execute.

**The rule.** Observe with the price. Trade with the quote.

**The trap.** Computing a trade's value from `usdPrice`. It is the middle of
the market, and nobody trades at the middle (section 4).

---

## 4. Step four: bid and ask — and which one you trade at

**Simply.** A pawn shop buys your watch for $80 and sells the same watch
for $100. The $80 is its *bid* (what it pays), the $100 is its *ask* (what
it charges), and the $20 gap is how it earns a living. You never choose
which number you get. **If you are selling, you get the bid. If you are
buying, you pay the ask.** The direction of your trade chooses for you.

**For real.** A pool has no bid and ask written down. The two numbers are
the two *directions of the quote*, for a size. We ran both on 2026-08-28:

| Direction | Call | Result | Effective price |
| --- | --- | --- | --- |
| Buying NVDAx (the ask) | `inputMint=USDC, outputMint=NVDAx, amount=1000000000` | `outAmount 456629170` | **$218.996** per token |
| Selling NVDAx (the bid) | `inputMint=NVDAx, outputMint=USDC, amount=450000000` | `outAmount 984561747` | **$218.792** per token |

The spread was $0.20, about 0.09%: the pool's fee plus a sliver of *price
impact* (0.0013%), which is how much our own $1,000 moved the pool's price.
Three more fields in the quote matter:

- `slippageBps`: the tolerance we set (50 = 0.50%). If the price moves more
  than this between the quote and the moment the transaction lands, the
  chain rejects the transaction instead of filling it worse.
- `otherAmountThreshold`: the guaranteed minimum you receive. This is the
  slippage rule turned into one number.
- `routePlan`: which pool or pools the trade goes through (ours said
  "Riptide").

The paper's formulas use exactly this. Its direction variable δ is +1 for a
buy and −1 for a sell, and it defines `P_open` as the ask for a buy and the
bid for a sell. In code: a sell quotes `NVDAx → USDC`; a buy quotes
`USDC → NVDAx`. One rule, no judgment call.

**The rule.** Quote in the direction of the trade, for the trade's size. The
result is the price. There is nothing to decide.

**The trap.** Using the mid price or the other direction's quote. Both
flatter the trade by half the spread, and the flattery becomes a ledger
error at settlement.

---

## 5. Step five: build the transaction, and who signs it

**Simply.** The quote is a promise. To make it happen, someone must sign a
form that says "move my tokens". On Solana that signature comes from a
*wallet*, and only the wallet's private key can produce it. Yagnum has no
wallet, so this step is the one it never takes.

**For real.** The swap endpoint turns a quote into an unsigned transaction:

```
POST https://lite-api.jup.ag/swap/v1/swap
{ "quoteResponse": <the quote>, "userPublicKey": "<the wallet's address>" }
```

We ran it once with a placeholder address to see the shape of the reply:

```
swapTransaction: <548 characters of base64 — the unsigned transaction>
lastValidBlockHeight: 420712103     (the offer expires after this block, about a minute)
prioritizationFeeLamports: 0        (the tip to validators; 0 on a quiet network)
simulationError: null               (Jupiter dry-ran it: it would succeed)
```

A wallet would decode this, sign it with its private key, and send it to a
Solana RPC node. The node forwards it to validators, and about a second
later it is confirmed or rejected.

**The rule.** A quote and a swap build are read-only and safe. A signature
is the point of no return. Yagnum's code stops before it.

**The trap.** Believing a "swap" API call trades anything. It does not. It
formats a request that only a private key can turn into a trade.

---

> **Update 2026-09-04 (ADR-025).** Yagnum now does this step for real, in
> shadow: `jupiter.build_swap` asks Jupiter for the transaction against the
> engine wallet, `solana.sign` signs it locally, `solana.simulate` runs it on
> mainnet, and nothing is sent. See [SHADOW-HEDGE.md](SHADOW-HEDGE.md).

## 6. Step six: the on-chain record

**Simply.** Every completed swap is written into a public ledger that
anyone can read forever. That is the audit trail the paper's Research
Question 3 wants to use as proof.

**For real.** Ask a Solana node for the latest transactions on the NVDAx
pool:

```
POST https://api.mainnet-beta.solana.com
{"method": "getSignaturesForAddress", "params": ["49iMatQ…", {"limit": 2}]}
```

The reply on 2026-08-29 listed two signatures at slot 442,664,095, and both
carried `err: InstructionError [2, Custom 6000]`. That is a *failed* swap:
the pool's program rejected it, and code 6000 in the swap program is the
slippage guard from section 4 — the price moved past the sender's
`otherAmountThreshold` between quote and landing, so the chain refused to
fill it worse. A real, public example of the safety rule doing its job.

**The rule.** Every attempt, successful or not, leaves a signed record with
a time and a block. A reconciliation can point at it.

**The trap.** Assuming that a signature means a fill. Read the `err` field.

---

## 7. How Yagnum will use these steps (the engine, paper money only)

The owner's decisions on 2026-08-29: the reserve multiplier `z` is the
measured 99th percentile (ADR-018); the Monday leg is a premarket limit
order at 8:00 ET that rolls into the 9:30 auction if unfilled; the escrow
moves by real journals; a scheduled job settles.

A Saturday sale of 10 NVDA, step by step:

1. **Find** the token for NVDA (section 1; cached).
2. **Quote the sell direction** for 10 × 10⁸ base units (section 4). The
   effective price is `P_open` — the bid.
3. **Size the reserve**: `10 × P_open × σ_NVDA × z`, about $150 today.
4. **Escrow**: journal the reserve out of the user's cash (section 8 says
   where it goes). Record the trade as `provisional`, with the quote saved
   as evidence: route, impact, block.
5. **Simulate the token leg** at the quoted price. No transaction is built
   or signed. The ledger records it as if Yagnum bought 10 NVDAx.
6. **Monday 8:00 ET**: place a limit sell for 10 NVDA at Alpaca with
   extended hours enabled. If it does not fill by 9:30, it rolls into the
   auction. The fill is `P_MKT`.
7. **Reconcile**: `P&L = −δ · (P_MKT − P_open) · Q`, fees off, add to the
   reserve, refund the surplus or debit the shortfall (ADR-017). Mark the
   trade `settled`. Every step is a double-entry row.

Yagnum ends flat. The user ends at Monday's price. The reserve is the pipe.

---

## 8. Where the escrow lives (the account question)

Alpaca's dashboard cannot create a second firm account, and its API cannot
either: firm accounts are created by Alpaca itself. A separate *customer*
account for Yagnum would not work as an escrow, because the sandbox does not
allow journals between two customer accounts (we found this in ADR-011).

So the escrow lives in the **existing sweep account**, which journals to and
from every customer already. Each reserve journal carries a description
("ERR escrow, trade 42"), and our ledger keeps a separate escrow balance per
trade. The paper's Invariant 1 (every reserve is backed) becomes a query:
the sum of open escrow rows must be less than or equal to the sweep's cash.
No new account. One more column of meaning on journals we already use.

---

## 9. Say it back

Answer these in your own words. If one is hard, reread its section.

1. Two tokens are both named "NVDAx". How do you tell which is real?
2. USDC has 6 decimals and NVDAx has 8. Where did those numbers come from,
   and what happens if you swap them?
3. You are selling 10 NVDAx. Which quote direction do you call, and which
   number is `P_open`?
4. Why can a transaction fail *after* a good quote, and which field
   protects you?
5. Which single step turns "reading" into "trading", and why does Yagnum
   never take it?

---

## Glossary

- **Aggregator** — a service that finds the best route across many pools.
- **Ask** — the price a buyer pays. On a pool: the quote in the buy direction.
- **Base units** — a token's smallest whole unit; the chain counts these.
- **Bid** — the price a seller receives. On a pool: the quote in the sell direction.
- **Decimals** — how many decimal places a token's base unit represents; declared by the token.
- **DEX** — decentralized exchange: a program on the chain that holds a pool and sets a price by formula.
- **Mint address** — a token's identity on Solana.
- **Pool** — a pair of token balances a DEX trades against.
- **Price impact** — how much your own trade moves the pool's price.
- **Quote** — an executable answer: this input, this output, this route, right now.
- **Slippage** — the price change you tolerate between quote and fill.
- **Signature** — a wallet's proof that it authorized a transaction.
- **Slot** — Solana's clock tick; each confirmed block has one.
