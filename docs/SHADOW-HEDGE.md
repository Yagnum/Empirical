# The shadow hedge (Version B, step one)

What Yagnum now does on Solana for every weekend trade, why it stops one
step short of sending, and what the rows it writes will decide.

Built 2026-09-04 (ADR-025). The numbers are from the first trade that ran
through it that afternoon: a simulated-weekend sell of 2 NVDA from a sim
account.

---

## 1. What it is, simply

**ELI5.** A pilot flies the whole approach in the simulator, hands on the
controls, instruments live, and stops just before the wheels touch. The
shadow hedge does that on the blockchain: it prices the hedge, builds the
real transaction, signs it with Yagnum's real wallet, and asks the network
"what would happen if I sent this?" Then it writes down the answer and
does not send.

**Why.** The paper's design (Version B) guarantees the customer a
weekend price and covers Yagnum by mirroring the trade in the token. That
costs a spread and gas on every leg. Whether it is worth it is a number,
not an opinion, and the only way to get the number is to run the hedge on
real trades. Shadow mode gets the number with no money at risk.

---

## 2. The two legs

| Customer does | Open leg (weekend) | Close leg (settlement) |
| --- | --- | --- |
| Sells 2 NVDA | Engine sells 2 NVDAx for USDC | Engine buys 2 NVDAx back |
| Buys 2 NVDA | Engine buys 2 NVDAx with USDC | Engine sells them |

**The trap.** A sell needs inventory. A decentralized exchange cannot
short, so to hedge a customer sell Yagnum must already hold NVDAx. Version
B live means a wallet holding a basket of xStocks plus USDC plus SOL.
Shadow mode records that honestly: the simulation fails on the empty
wallet, and the row says so.

---

## 3. One leg, step by step, with the real numbers

Trade 7, Friday 2026-09-04 at 3:58 PM ET, under the dev weekend override:
sell 2 NVDA.

1. **Quote.** Jupiter, 2 NVDAx to USDC: 461.598121 USDC, price 230.799 per
   token, price impact 0.00017%, route Raydium CLMM.
2. **Build.** The swap builder returns an unsigned transaction: one
   signature required, three instructions, one address-lookup table.
   Compute limit 1,400,000; priority fee 0 (its own simulation failed on
   the empty wallet); Jupiter's error: "attempt to debit an account but
   found no record of a prior credit".
3. **Sign.** The engine keypair signs the message locally. Signature
   recorded (`4NjH6oEo…`). The GitHub Actions hosts hold only the public
   key, so legs built there are recorded unsigned; the simulation does not
   check signatures.
4. **Simulate.** Mainnet RPC `simulateTransaction`: error `AccountNotFound`
   (the fee payer has no SOL). Compute units consumed: 0.
5. **Rent.** NVDAx is on the Token-2022 program. The wallet's associated
   token account for it does not exist, so rent applies: 1,855,569
   lamports.
6. **Gas.** 5,000 base + 0 priority + 1,855,569 rent = 1,860,569 lamports,
   which at SOL $101.78 is $0.19.

Settlement with an injected +1% gap then ran the close leg: buy back at
230.834 per token, another $0.19 of gas.

The event trail on the trade shows both legs in one line each:

```
hedge_shadow_open   sell 2 NVDAx at 230.80 - gas 1860569 lamports ($0.1894) - simulation: AccountNotFound
hedge_shadow_close  buy 2.01969435 NVDAx at 230.83 - gas 1860569 lamports ($0.1893) - simulation: AccountNotFound - Version B P/L ...
```

---

## 4. The Version B number

On the close leg three columns answer "had Yagnum guaranteed the weekend
price and hedged on-chain, what would this trade have made?"

```
broker_pnl     = qty × (p_close − p_open)          customer sell
               = qty × (p_open − p_close)          customer buy
chain_pnl      = qty × (open price − close price)  sell-first hedge
               = qty × (close price − open price)  buy-first hedge
version_b_pnl  = broker_pnl + chain_pnl − gas of both legs
```

In words: the share leg gains what the token leg loses, minus the spread
crossed twice, minus gas. If the token tracks the share perfectly the two
big terms cancel and Version B costs exactly the spread plus gas per trade.
Where they do not cancel is the tracking error, and that is what the rows
will measure.

Note on the injected settlement above: its `p_close` is invented (p_open ×
1.01) while the token prices are real, so its Version B figure mixes a
fake share move with a real token move. Only market-mode settlements
produce a meaningful figure. The first ones land Tuesday 2026-09-08.

---

## 5. What is recorded

One row per leg in `hedge_legs`: the quote (amount, price, impact, route,
slippage), the transaction (compute limit, priority fee, block height,
signature when signed), the simulation (Jupiter's error, the RPC's error,
units consumed), the rent check (token program, whether the account
exists, rent), gas in lamports and dollars with the SOL price used, and on
the close leg the three P/L columns. A failure in any step goes into
`error` and the rest of the row still fills in. The trade itself is never
touched: the hedge runs after the journals and swallows every exception.

---

## 6. Switching it

| Setting | Meaning |
| --- | --- |
| `HEDGE_MODE=shadow` | Build, sign, simulate, record. The default. |
| `HEDGE_MODE=off` | Skip the hedge entirely. The test suite runs this way. |
| `SOLANA_ENGINE_KEYPAIR` | The wallet's secret, base58. Local only. Never in GitHub. |
| `SOLANA_ENGINE_PUBKEY` | The wallet's address. Enough to build and simulate. In the workflows. |
| `SOLANA_RPC_URL` | Mainnet RPC. The public endpoint is rate-limited; a Helius key is the upgrade. |

There is no `live`. Sending a transaction is a separate decision with its
own ADR, and two questions come first: funding the wallet, and Backed's
terms, which say xStocks are not offered to US persons.

---

## 7. Say it back

1. What is the one step shadow mode skips? *(`sendTransaction`. Everything
   before it, including the signature, is real.)*
2. Why does the simulation fail, and is that a bug? *(The wallet holds no
   SOL and no tokens. It is the honest result; funding the wallet turns
   the same code path into real compute-unit numbers.)*
3. Why can a customer buy be hedged without inventory but a sell cannot?
   *(Buying tokens needs USDC. Selling tokens needs tokens, and a DEX
   cannot short.)*
4. Which settlement's Version B figure should you trust: injected or
   market? *(Market. Injected invents the share price.)*
