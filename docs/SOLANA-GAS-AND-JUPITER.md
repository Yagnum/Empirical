# Solana gas, and how Jupiter makes money

Who pays for a swap, what it costs, and where each part of the money goes.
Written 2026-09-04, the day Yagnum first built a real Solana transaction
(ADR-025). Every number below came from that transaction or from a live
call that afternoon.

---

## 1. Gas, simply

**ELI5.** A blockchain is a shared notebook that thousands of computers
copy. To write one line in it, you pay the copiers a small tip. That tip
is "gas". On Solana the tip is tiny, but it is never zero, and it always
comes out of the wallet that signs the line.

**The rule.** *The wallet that signs pays.* Jupiter builds the transaction
and even suggests a tip, but the SOL leaves the signer's wallet, not
Jupiter's. Today Yagnum signs nothing that is sent, so it pays nothing.
If Version B ever goes live, the engine wallet pays for every hedge leg.

**The trap.** "Gas" on Solana is three different things, and the one
people forget is the largest:

| Part | What it is | Size, from our first transaction | Who receives it |
| --- | --- | --- | --- |
| Base fee | Fixed, per signature | 5,000 lamports (0.000005 SOL) | Validators |
| Priority fee | Compute units × a price you choose | 0 in our build (see §3) | Validators |
| Rent | A deposit that keeps a new token account alive | 1,855,569 lamports (about 0.0019 SOL) | Held by the network; refunded when the account closes |

Total for one NVDAx swap from an empty wallet: 1,860,569 lamports, which
was **$0.19** at that afternoon's SOL price of $101.78. Rent was 99.7% of
it. A lamport is one billionth of a SOL.

---

## 2. Rent: the surprise cost

Every token you hold needs its own small account in your wallet, called an
associated token account (ATA). Creating one costs a rent deposit of about
0.002 SOL. You pay it once per token per wallet. Close the account later and
the deposit comes back.

Yagnum's engine wallet holds no tokens yet, so every shadow hedge leg
reports `ata_exists = false` and adds the rent. Once a real NVDAx account
exists, the next NVDAx leg costs about 5,000 lamports plus the priority
fee: under a tenth of a cent.

A detail worth knowing: xStocks live on the **Token-2022** program, not the
older SPL Token program. That changes which address the account has and
makes the account slightly larger than the classic 165 bytes, so the rent
we record is a floor.

---

## 3. The priority fee, and why ours reads zero

Solana processes a transaction in "compute units". You can offer a price
per unit to get ahead of the queue. Jupiter's builder estimates a fee by
simulating the swap first. On our empty wallet that simulation fails
("attempt to debit an account but found no record of a prior credit"),
so Jupiter falls back to a compute limit of 1,400,000 and a priority fee of
zero. That zero is a symptom of the empty wallet, not a market fact. When
the wallet is funded the field becomes real, typically a few thousand to a
few hundred thousand lamports depending on how busy the network is.

---

## 4. The swap's other cost: the spread

Gas is not the expensive part of a swap. The expensive part is the pool.
When Yagnum sells 2 NVDAx, the route goes through a liquidity pool (that
afternoon: Raydium CLMM), and the pool charges a fee plus moves its price
against the trade. That is the bid-ask spread the sampler records every
five minutes (ADR-020). For NVDAx it was about 0.46% on Friday afternoon,
which on a $461 sale is about $2.10, more than ten times the gas.

Who gets that money: the **liquidity providers** who put tokens and USDC
into the pool. Not Jupiter.

---

## 5. How Jupiter makes money

Jupiter is a router. It finds the best path across many pools and
assembles the transaction. On the plain swap API Yagnum uses it charges
nothing. Its income comes from other places:

| Source | What it is |
| --- | --- |
| Ultra API fee | Its newer, hosted swap flow charges a small percentage of the swap (documented as roughly 0.05% to 0.1%). Ultra can also pay gas for a user who has no SOL and take it back out of the swap. |
| Perpetuals exchange | Trading fees on leveraged positions. Historically its largest revenue line. |
| Limit orders and DCA | A small fee on those order types. |
| Integrator fees | An app that builds on the swap API can add its own fee, collected to its own account. Jupiter takes a share on some products. |

Please check the exact percentages on Jupiter's docs before you quote them;
they change. The shape does not: Jupiter earns from hosted products and
volume, the pools earn the spread, and the validators earn the gas.

---

## 6. What Yagnum pays today, and would pay under Version B

| Today (Version A, shadow hedge) | Version B live |
| --- | --- |
| Quotes: free, off-chain | Same |
| Swap builder: free | Same |
| Gas: none. Nothing is sent | Base + priority + rent per leg, from the engine wallet |
| Spread: none. The customer's price is Jupiter's quote, but no swap happens | The spread on both legs, paid to the pools |
| SOL held: none | SOL for gas, USDC for buys, and xStock inventory for sells |

The shadow hedge (ADR-025) records the right-hand column for every weekend
trade without spending it. That table is the evidence for the Version A /
Version B decision.

---

## 7. Say it back

1. Who pays gas when a user swaps on Jupiter's website? *(The user's
   wallet: it signs.)*
2. Why was rent 99.7% of our first transaction's cost? *(The engine wallet
   has no NVDAx account yet; creating one takes a refundable 0.0019 SOL
   deposit. The base fee is only 5,000 lamports.)*
3. Where does the bid-ask spread go? *(To the liquidity providers in the
   pool the route used, not to Jupiter.)*
4. Why does our priority fee read zero? *(Jupiter's own simulation fails
   on an empty wallet and falls back to zero. It is an artifact, not a
   price.)*
