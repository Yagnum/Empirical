# Decision Log (ADRs)

Architecture Decision Records: each entry captures a decision, the context it
was made in, and its consequences. Professional teams keep these so that six
months later nobody asks "why on earth did we do it this way?" — the answer is
written down. New decisions get appended; superseded ones stay (marked), so
the history is honest.

---

## ADR-001 — Monorepo: app + notebooks + docs in one repo

**Date**: 2026-08-24 · **Status**: Accepted

**Context**: Yagnum is one project with three kinds of work: the web app, the
empirical research notebooks, and the paper/docs.

**Decision**: Single repo. `app/web` (frontend), `app/api` (backend),
`notebooks/` (research), `docs/` (architecture + decisions).

**Consequences**: One clone tells the whole story for demos and reviewers.
If the pieces ever need separate deploy cadences or teams, we can split later.

---

## ADR-002 — Next.js frontend + FastAPI backend as separate services

**Date**: 2026-08-24 · **Status**: Accepted

**Context**: The MVP could ship as a single Next.js full-stack app (simpler),
but the research roadmap (ERR engine, backtesting, ledger) is Python-shaped,
and we want to learn real service-to-service architecture: API design, CORS,
token verification across languages.

**Decision**: Two services from day one. Next.js 16 (`app/web`, port 3000)
for UI; FastAPI (`app/api`, port 8000) as the only holder of broker secrets
and the only caller of Alpaca.

**Consequences**: Two processes in dev, CORS configuration, and Clerk JWT
verification in Python — more plumbing, but the Phase 5+ quant work lands in
a backend that already exists. Deployment needs two hosts (e.g. Vercel +
Render/Fly).

---

## ADR-003 — No database yet; Alpaca account ID lives in Clerk user metadata

**Date**: 2026-08-24 · **Status**: Accepted · **Partly superseded by ADR-014** (2026-08-27): the database now exists for our own records. The Clerk-metadata mapping stays.

**Context**: The only state Phase 1 needs is the mapping Clerk user →
Alpaca account ID. Orders, positions, and balances already live in Alpaca.

**Decision**: Store `alpaca_account_id` in Clerk's user metadata via its
backend API. Defer Postgres until we build our own ledger/order log — which
the paper requires anyway (double-entry IBOR), so the database arrives when
it has a real job.

**Consequences**: Phase 1 has zero database ops. Revisit the moment we need
to store anything Alpaca doesn't (ERR records, reconciliation state).

---

## ADR-004 — Alpaca Broker API (sandbox), not the single-account Trading API

**Date**: 2026-08-24 · **Status**: Accepted

**Context**: Alpaca has two products: the Trading API (one paper account,
ours) and the Broker API (programmatically create a brokerage account per
end-user; sandbox environment for development).

**Decision**: Broker API sandbox, because Yagnum's model is "every signup
gets their own account", and that is the API real fintechs build on.

**Consequences**: Account creation requires KYC-style fields (fake data is
fine in sandbox). Funding is simulated, but not instant by default: see
ADR-011 and ALPACA-FUNDING.md §7 for the limits we measured and raised.

---

## ADR-005 — Trust-first visual design; persistent paper-trading indicator

**Date**: 2026-08-24 · **Status**: Accepted · **Amended** 2026-08-24: the
first execution leaned "heritage" (serif headlines, micro-caps labels
everywhere) and read one notch too old-world. Calibrated to "modern-trust":
headlines in a modern grotesk, the serif reserved for the wordmark and one
hero money figure per screen, softer card furniture, one load animation.
The specimen-statement card and the paper-trading stamp are keepers.
Lesson recorded: "young vs. old audience" is a proxy — design for the shared
codes of trust (calm, legible, current, honest) rather than for an age group.

**Context**: Crypto-native UIs (dark, dense, ad-laden) read as casino-like to
mainstream users — the opposite of Yagnum's goal of making this feel safe.

**Decision**: Light, white/blue palette in the vein of established brokers
(Schwab, Chase). A persistent but subtle indicator that the account is paper
trading — the same pattern thinkorswim paperMoney and TradingView use.

**Consequences**: Design work optimizes for calm and clarity over spectacle.
The paper-trading indicator is honest UX and doubles as a compliance habit.

---

## ADR-006 — Next.js (React) for the frontend

**Date**: 2026-08-24 · **Status**: Accepted

**Context**: The frontend needs professional UI, routing, and — critically —
a _server side_, because our auth pattern requires attaching the user's
session token to backend calls without exposing token-handling machinery to
the browser.

**Decision**: Next.js 16 (App Router) with React.

**Alternatives considered**:

- _Plain React SPA (Vite)_: simpler mental model, but everything runs in the
  browser — every API call, every token, every redirect decision happens
  client-side. No server to keep things private on, worse first-load, and
  we'd hand-roll routing and auth glue.
- _SvelteKit / Vue (Nuxt)_: genuinely good frameworks, but React has the
  largest ecosystem, the most transferable job-market skill, and the best
  Clerk support.

**Why it wins**: Server components let us fetch account data on the server
(where the Clerk token and API URL live) and ship the browser finished HTML.
File-based routing, first-class Clerk integration, one-command Vercel
deployment, and it's what real fintech frontends are built on. We chose Next.js because it acts as a secure Backend-for-Frontend (BFF). It gives us built-in routing for a smooth user experience, while its server layer ensures our session tokens are kept strictly on the server—completely hidden from the browser and shielded from client-side security risks.

**Consequences**: We must learn the server/client component split and
Next-specific caching rules (e.g. we already had to mark the health page
`force-dynamic`). Worth it: those concepts _are_ modern web architecture.

---

## ADR-007 — FastAPI (Python) for the backend

**Date**: 2026-08-24 · **Status**: Accepted

**Context**: The backend's MVP job is small (verify identity, call Alpaca),
but the roadmap's job is big: the ERR engine, double-entry ledger, and
gap-volatility research are all Python-shaped work (`notebooks/` already is).

**Decision**: FastAPI on Python 3.13, managed by uv.

**Alternatives considered**:

- _Flask_: the classic, but no built-in request validation, no async-native
  story, no auto-generated docs — we'd bolt all three on.
- _Django_: batteries we don't need (ORM, admin, templates) — ADR-003 says
  no database yet, so most of Django would sit idle.
- _Node/Express or Next API routes_: one language across the stack is
  attractive, but it forfeits the research synergy — the quant work would
  then live in a different language from the product backend forever.

**Why it wins**: Pydantic models validate every request/response shape at
runtime (exactly what you want when payloads carry money), it's async-native
(our workload is I/O: waiting on Alpaca/Clerk/Jupiter), and it auto-generates
interactive API docs at `/docs` — the frontend's contract is always visible
and testable in a browser.

**Consequences**: Two languages in the repo and Clerk JWT verification done
in Python. Deliberate: cross-language token verification is a core
professional skill, and JWTs are designed for exactly this.

---

## ADR-008 — Clerk for authentication

**Date**: 2026-08-24 · **Status**: Accepted

**Context**: Auth is the highest-blast-radius component to get wrong
(password storage, session fixation, token leakage). For a financial app,
"we rolled our own auth" is a red flag, not a flex.

**Decision**: Clerk, on its free tier.

**Alternatives considered**:

- _NextAuth/Auth.js_: free and open source, but UI is DIY and its session
  model is Next-centric — verifying sessions from our separate FastAPI
  service is more manual.
- _Auth0_: enterprise-grade, heavier configuration, tighter free tier.
- _Roll our own_: maximum learning, maximum risk. Might revisit as a
  learning exercise in a branch — never for the demo.

**Why it wins**: Polished prebuilt sign-in/sign-up components (bank-grade
first impression for near-zero effort), sessions issued as standard JWTs any
backend can verify against Clerk's public keys (perfect for our two-service
split), and per-user metadata storage — which is what lets ADR-003 defer the
database.

**Consequences**: A third-party dependency for a core function; acceptable
at MVP. If we ever outgrow it, the JWT-based boundary keeps FastAPI's auth
code swappable.

---

## ADR-009 — Supporting tooling: TypeScript, Tailwind, uv

**Date**: 2026-08-24 · **Status**: Accepted

- **TypeScript** over JavaScript: the compiler catches wrong shapes at build
  time — e.g. treating `cash` (a string, see ADR-010) as a number fails
  before it ships instead of in a demo.
- **Tailwind CSS v4**: styling lives with the markup, design stays consistent
  via one set of tokens, and it's what create-next-app ships. The trade-off
  (long class strings) is worth the iteration speed at MVP scale.
- **uv** for Python: lockfile-based, reproducible environments (`uv.lock` is
  to Python what `package-lock.json` is to Node) and dramatically faster than
  pip. `uv run` guarantees the right interpreter and deps every time.

---

## ADR-010 — Monetary values are strings at the boundaries, never floats

**Date**: 2026-08-24 · **Status**: Accepted

**Context**: Binary floating point cannot represent most decimal amounts
exactly (`0.1 + 0.2 === 0.30000000000000004`). Brokers therefore transmit
money as strings; Alpaca does exactly this.

**Decision**: Money crosses every API boundary as a **string**, passed
through untouched from Alpaca wherever possible. If we ever do arithmetic on
money server-side, we use Python's `Decimal` — never `float`. The frontend
formats for display with `Intl.NumberFormat` but never round-trips a parsed
float back to the server.

**Consequences**: Slightly more ceremony (no accidental `+` on amounts),
zero rounding bugs. This discipline becomes load-bearing in the ERR phase,
where reconciliation math must balance to the cent (Invariant 2 in the
paper).

---

## ADR-011 — Fund accounts by journal from the firm account, not ACH

**Date**: 2026-08-24 · **Status**: Accepted

**Context**: Live sandbox testing contradicted the docs' "transfers credit
immediately" claim twice: (1) Alpaca caps ACH at **one transfer per direction
per trading day**, breaking "fund whenever you want"; (2) sandbox transfers
crawl through a simulated clearing pipeline (QUEUED → SENT_TO_CLEARING →
COMPLETE) over minutes, so onboarding would end on a $0 dashboard.

**Decision**: Fund via `POST /v1/journals` (JNLC) from the firm/sweep
account — instant credit, no daily cap, and the pattern production
broker-API fintechs actually use. Requires `ALPACA_FIRM_ACCOUNT_ID` in
`.env` (Broker dashboard → Accounts → Firm Accounts; not discoverable via
the API — customer-to-customer journals are disabled). ACH remains as the
fallback path when the firm account is unconfigured.

**Consequences**: One more secret to configure per environment. The
pending-transfer display moves to the ERR phase, where "settlement takes
time" is the entire point. Meta-lesson recorded: empirical testing beats
documentation — the funding method survived a spec validation and a mocked
contract test, and was only falsified by hitting the real system.

---

## ADR-012 — Phase 2/3 libraries and scope

**Date**: 2026-08-26 · **Status**: Accepted

**Context**: Phases 2 and 3 add trading, positions, history, and statements.
Each needs a chart, a table, and live data. We compared the options before
writing code (TradingView Lightweight vs. Advanced, Recharts, ECharts,
Highcharts; TanStack Table vs. AG Grid; polling vs. WebSockets).

**Decisions**:

- **Charts**: TradingView Lightweight Charts (Apache 2.0). Finance-native,
  45 KB, canvas. One library for price and portfolio charts. Attribution
  link required and kept.
- **Tables**: TanStack Table (headless). We keep our own design.
- **Live data**: TanStack Query with polling. WebSockets wait for the ERR
  engine, which needs them anyway.
- **Orders**: market and limit, day and GTC.
- **History**: Alpaca account activities (fills, deposits, journals).
- **Statements**: a date-range CSV export that we build, plus Alpaca monthly
  PDF documents when the sandbox provides them. Our own PDF waits for Phase 4.

**Rejected**: TradingView Advanced Charts (proprietary, branded), AG Grid
(heavy, paid tiers), Highcharts (commercial license), WebSockets now (a
relay for no immediate gain).

**Consequences**: Three new frontend dependencies. Market hours now matter
for testing: fills only occur while the market is open.

---

## ADR-013 — Account lifecycle: a login is not a brokerage account

**Date**: 2026-08-26 · **Status**: Accepted

**Context**: A user deleted their Clerk login. The Alpaca account stayed
open. We then closed it, and the same user could not sign up again:
Alpaca keeps a closed account's email reserved, `ACCOUNT_CLOSED` is
terminal, and there is no reopen endpoint. A first fix opened the new
account under a tagged email. That was withdrawn: a false contact email on
a KYC record is not a design.

**Decision**:
- A login deletion does not close the brokerage account at once. It starts
  an offboarding: cancel open orders, flatten positions, return cash to the
  firm account, then close. Phase 4 wires this to a Clerk `user.deleted`
  webhook.
- Closing an account retires its contact email first, then closes it. The
  procedure lives in `alpaca.close_account` and `scripts/close_account.py`.
- A returning customer gets a new account. Closed accounts stay closed and
  keep their history, as at any real broker.
- Provisioning never adopts a closed account by email.

**Consequences**: Sign-up after a deletion works without tricks. One more
ops script. The Phase 4 webhook has a specification.

---

## ADR-014 — The database arrives: Neon Postgres, SQLAlchemy 2, Alembic

**Date**: 2026-08-27 · **Status**: Accepted

**Context**: Three needs now exist that Alpaca cannot hold: an audit log,
order idempotency, and a fills ledger for realized P/L (a sold position's
cost basis vanishes from Alpaca at the moment of sale). Deployment target
is Azure (family decision), so production will use Azure Database for
PostgreSQL.

**Decision**:
- **Engine**: Postgres. Dev on **Neon** (hosted free tier — zero local
  setup; chosen over local Docker), production on Azure Postgres. Same
  engine both places; only `DATABASE_URL` changes.
- **Access layer**: **SQLAlchemy 2** models + **Alembic** migrations —
  the industry standard and the fuller lesson.
- **First tables**:
  - `audit_log` — one row per state-changing API request: who, what,
    when, request id, outcome. Append-only.
  - `order_intents` — client-generated idempotency key per order
    submission; a retried request returns the original order instead of
    placing a second one.
  - `fills` — every fill copied from Alpaca (symbol, side, qty, price,
    time, alpaca ids). Append-only; the raw material of the ledger.
  - `lots` — open tax lots derived from buys; sells consume lots FIFO and
    write realized P/L. This pair is the seed of the ERR-era double-entry
    ledger (paper, Invariant 2).

**Consequences**: A `DATABASE_URL` secret per environment. Migrations run
at deploy time. The API grows a small persistence layer; Alpaca remains
the system of record for balances and positions — our tables record what
Alpaca forgets, never a second copy of what it remembers.

---

## ADR-015 — Offboarding webhook and reset-balance: liquidate, return cash

**Date**: 2026-08-27 · **Status**: Accepted

**Context**: ADR-013 specified *what* closure means (cancel orders,
flatten positions, return cash, retire email, close) but left two
mechanisms open. First: when Clerk sends `user.deleted`, the user is
already gone from Clerk — and their private metadata, which held the
Alpaca account id, is gone with them. Second: onboarding promises "reset
the balance whenever you want a clean run", and the copy never said what
happens to shares the user still holds.

**Decision**:
- **The audit log is the memory that outlives the user.** The webhook
  finds the Alpaca account by reading our own `audit_log`: the latest row
  for that Clerk user id with an account id on it. This is the first
  feature that *depends* on ADR-014's database rather than merely
  benefiting from it.
- **The webhook authenticates with a Svix signature, not a Clerk token.**
  There is no session behind a webhook. Clerk signs each delivery
  (HMAC-SHA256 over `id.timestamp.body`); we verify with a constant-time
  compare and reject stale timestamps. An unconfigured signing secret
  means the route refuses events rather than trusting them.
- **Svix retries are the completion mechanism.** Liquidation is
  asynchronous: with the market closed, sell orders queue until the next
  open. Instead of building our own scheduler, the webhook answers 503
  while positions remain, and Svix redelivers on its backoff schedule
  (spanning about a day). Each retry advances the closure as far as the
  market allows. Ops fallback for the pathological case (retries
  exhausted over a long weekend): `scripts/close_account.py`.
- **Reset sells everything** (owner's choice, 2026-08-27): cancel orders,
  liquidate all positions, then journal every dollar back to the firm
  sweep in ≤$100,000 chunks (the sandbox JNLC transaction limit). The
  account ends at **$0 and the existing funding form takes over**, so the
  user picks the next starting amount. With the market closed the reset
  honestly reports "liquidating" until the sells can fill. Reset shares
  the flatten-and-return-cash code with the webhook; only the webhook
  retires the email and closes the account.

**Consequences**: One new secret (`CLERK_WEBHOOK_SIGNING_SECRET`). The
webhook cannot be registered until the API has a public URL, so it goes
live with the Azure deployment; the code and tests land now. A reset
started on a weekend stays "liquidating" until Monday's open — the UI
must say so plainly rather than pretend it is instant.

---

## ADR-016 — Measure before building: the xStock price record

**Date**: 2026-08-28 · **Status**: Accepted

**Context**: The paper sizes the Execution Reconciliation Reserve as
`ERR_initial = Q · P_open · σ_gap · z_α + Fees` (§6d). Everything in that
formula is known at trade time except `σ_gap` — the historical deviation
between a token's weekend price on Jupiter and Monday's real fill. Nobody
publishes that number. Jupiter's Price API is current-price only;
GeckoTerminal keeps 180 days of hourly candles for free; Alpaca keeps
years of daily bars for the real share. Owner's decision: research first,
Jupiter trading later, Azure after the app is done.

**Decision**:
- **Record our own dataset, starting now.** Every five minutes, around the
  clock, store each xStock's Jupiter price beside its real share's last
  trade on Alpaca (`token_prices`, append-only). The weekend is the
  interesting part, and no free source keeps it at this resolution.
- **Run the sampler on GitHub Actions cron**, not on a laptop that sleeps
  and not on infrastructure we have not deployed yet. Secrets live in the
  repository's Actions secrets; the job places no orders and signs no
  transactions.
- **Numbers stay strings until Decimal** (ADR-010): Jupiter's JSON numbers
  are decoded with `parse_float=str`; the column is `NUMERIC(28,10)`.
- **Suffix-stripping needs an override list.** `SPCXx` is SpaceX, a
  private company; `SPCX` on Alpaca is an unrelated ETF. Tokens with no
  listed share map to a null `underlying`, never to a look-alike ticker.
- **Backfill the past from GeckoTerminal (180 days, hourly) and Alpaca
  (2 years, daily)**, then measure `σ_gap` both ways in
  `notebooks/gap-volatility.ipynb` — the paper's Research Question 1 —
  before any reserve figure is shown in the app.

**Consequences**: A dataset that grows by about 5,700 rows a day and is
worth more every weekend it survives. GitHub's schedule is best-effort
(runs can start late; idle repositories pause after 60 days). The first
in-hours observation, 2026-08-28 12:58 PM ET: NVDA $219.955 on Alpaca,
NVDAx $220.24 on Jupiter — a 0.13% gap. The token tracks the share
tightly in hours; the risk lives off-hours, which is what we now record.

---

## ADR-017 — The ERR is a pass-through, and the Monday leg closes premarket

**Date**: 2026-08-28 · **Status**: Accepted

**Context**: Working the paper's reconciliation with real numbers
(docs/YAGNUM-EXPLAINED.md §3e) showed what the formulas imply but never
state: surplus refunded, shortfall taken from escrow, so **the weekend
trader always ends at the first regulated-market price**. A Saturday sale
at $226 that settles Monday at $223 nets the trader $223 a share. The
trader gains immediacy and guaranteed settlement into regulated custody,
not a locked price. The alternative — Yagnum quoting a firm weekend price
and bearing the gap for a fee — is a market-making business exposed to
informed weekend flow it cannot hedge, because the hedging market is
closed. The paper also fixed settlement at the 9:30 open, the most
volatile moment of the session.

**Decision**:
- **Version A, said out loud.** Yagnum is a neutral bridge. Weekend
  execution is provisional; final settlement is the first regulated
  execution. The paper's language must stop implying that weekend prices
  are locked. Yagnum ends flat on every trade by design.
- **The escrow is collateral, not a liability cap** (proposed amendment
  to §6c for the paper). A shortfall beyond the escrow is debited from
  the trader's brokerage account, as any broker treats margin. Cascade
  Levels 2–4 exist for a customer who cannot pay, not as a free downside
  cap. `σ_gap · z_α` then answers "how much collateral makes debits rare".
- **Close the Monday leg premarket, as early as liquid.** Alpaca accepts
  extended-hours limit orders from 4:00 AM ET (limit only, `extended_hours`
  set, day time-in-force). Unfilled premarket orders roll into the 9:30
  auction. "Liquid enough" is an empirical threshold: the notebook
  measures the gap from the weekend token price to each Monday moment
  (premarket hours, the auction, minutes after) and to the spread at that
  moment, using the sampler's own five-minute record.

**Consequences**: The paper needs a wording pass (abstract, §1, §6) and
one mechanism amendment (§6c). The notebook gains a second question
beside `σ_gap`: the settlement moment. The engine, when built, places
premarket limit orders first and never a market order in extended hours.

---

## ADR-018 — z is measured, not looked up: σ per symbol, one pooled multiplier

**Date**: 2026-08-29 · **Status**: Accepted

**Context**: The paper takes `z_α` from the normal table: `Φ⁻¹(0.99) =
2.326`. That number is only correct if weekend gaps follow a bell curve.
The measured gaps do not: pooled market gaps show excess kurtosis of 27
(a normal curve has 0), which means extreme Mondays happen far more
often than the bell curve predicts. Back-tested on 20 tokens over the
recorded weekends, a reserve sized at z = 2.326 was breached on 4.65% of
seller weekends — almost five times the 1% the paper promises. Full
work-through with figures: `docs/SIZING-THE-RESERVE.md` and
`notebooks/gap-volatility.ipynb`.

**Decision**:
- **Take z from the data, not the table.** z is the pooled empirical
  99th percentile of standardized gaps, measured in the notebook. First
  cut: **z ≈ 3.7**. Back-tested, that brings seller breaches to 0.87% —
  under the promised 1% — at the cost of a larger reserve (drag rises
  from 4.4% to 6.9% of trade value).
- **σ_gap stays per symbol; z is one pooled number.** Volatility differs
  honestly between symbols (each has enough data to measure its own σ).
  Tail shape does not: per-symbol z estimates ranged from 2.1 (MCD) to
  4.9 (NVDA) on so few weekends that the spread is mostly noise. Pooling
  borrows every symbol's worst Mondays to estimate a shape none has
  enough data to show alone.
- **Re-measure as weekends accrue.** z is a notebook output, re-run
  after each recorded weekend, not a constant in code. The engine reads
  it from configuration with the measurement date beside it.

**Consequences**: Reserves are about 60% larger than the paper's formula
gives, and honest. The 10-NVDA worked example moves from ~$95 to ~$150.
The paper's §6d needs an amendment: the formula stands, the source of
`z_α` changes from the normal table to the empirical distribution.

---

## ADR-019 — The ERR engine: session routing, the weekend state machine, and a dev simulator

**Date**: 2026-08-31 · **Status**: Accepted

**Context**: The measurement phase answered how big the reserve must be
(ADR-018) and when the hedge closes (ADR-017). What remained was the
engine itself, plus two questions the owner raised: how to develop and
test weekend behavior on a weekday, and what happens to orders placed
after 4:00 PM. Research on the second changed the map: Alpaca's Broker
API now offers 24/5 trading on the Blue Ocean ATS — an overnight session
from 8:00 PM to 4:00 AM ET, Sunday night through Friday morning, limit
orders only. A regulated venue is therefore open from Sunday 8:00 PM to
Friday 8:00 PM. The true dead zone is 48 hours, not 65.

**Decision**:
- **Every hour of the week has exactly one execution path.** Regular
  session: normal Alpaca orders. Premarket (4:00–9:30 AM) and
  after-hours (4:00–8:00 PM): Alpaca limit orders with
  `extended_hours`. Overnight weeknights (8:00 PM–4:00 AM): Alpaca
  24/5 limit orders — adopted after one sandbox test order at 8:05 PM
  confirms the sandbox supports the session. Weekend (Friday 8:00 PM to
  Sunday 8:00 PM) and market holidays: the ERR engine. Jupiter is never
  used for execution while any regulated session is open.
- **The weekend trade is a state machine in its own table**:
  `provisional` (Jupiter quote taken as `P_open` — bid for sells, ask
  for buys; ERR computed per ADR-018; escrow journaled) →
  `awaiting_settlement` (weekend over, hedge order placed) → `settled`
  (real fill reconciled; surplus refunded or shortfall debited per
  ADR-017; escrow released). A `breached` branch records shortfalls
  beyond escrow. Every money movement is a double-entry ledger row.
- **Escrow is real journals in the existing sweep account**, tagged in
  the journal description, so Invariant 1 ("escrow covers every open
  provisional trade") is a query, not a promise.
- **The hedge closes at Monday 8:00 AM ET premarket** (limit, rolling to
  the 9:30 auction), per the owner's earlier decision. Open follow-up:
  the 24/5 session means the earliest possible close is now Sunday
  8:00 PM. Whether that session is liquid enough is an empirical
  question for the sampler and notebook before any change.
- **A scheduled job settles trades.** No settlement runs inside a web
  request.
- **Dev weekend mode: fake the clock, nothing else.** Jupiter trades
  24/7, so its quotes are live on a Tuesday. A dev-only toggle forces
  `market_open = false`; the full engine then runs for real — quotes,
  reserve, escrow journals, state machine. Two resolution modes:
  **real** (default — the settlement job places a real sandbox order at
  the actual next open, minutes away, and reconciles a real fill) and
  **injected gap** (settle at `open × (1 + g)`, with `g` typed or drawn
  from the measured distribution — the only way to watch the reserve
  absorb, or fail to absorb, a 4σ Monday without waiting months for
  one). All overrides live in one module that refuses to import outside
  development.

**Consequences**: The simulator is not throwaway — it is the engine with
two injected seams (the clock, the settlement price source), which is
also what makes the engine testable at all. The 48-hour dead zone
shortens the exposure window `σ_gap` describes; the notebook should
measure Friday-8PM-to-settlement rather than Friday-close-to-settlement,
which will shrink σ somewhat. The paper gains a finding: the weekend
problem is smaller than stated, and precisely bounded. One task blocks
the overnight path: the 8:05 PM sandbox test.

---

## ADR-020 — Record the spread: two executable quotes per token, every five minutes

**Date**: 2026-09-01 · **Status**: Accepted

**Context**: The paper's Research Question 2 asks how liquidity providers
price weekend risk. The answer is the spread — the distance between what a
seller receives and a buyer pays — and `token_prices` recorded only the
last-swap midpoint. Nobody publishes token spreads historically; like the
gap itself (ADR-016), the only way to have the data is to start recording
before it is needed. Labor Day weekend (a 72-hour closure) was four days
away at the time of the decision.

**Decision**:
- **Each sampler run quotes each token both ways at a fixed ~$1,000**:
  USDC→token (the ask) and token→USDC (the bid), via Jupiter's swap-quote
  API. One size for every token and every run, so the series is comparable
  across both. Five new nullable columns on `token_prices`: `bid_usd`,
  `ask_usd`, `bid_impact_pct`, `ask_impact_pct`, `quote_size_usd`.
- **Best effort, like the Alpaca side**: a failed quote leg loses the
  spread columns, never the price observation.
- **Paced to Jupiter's gateway**: a burst of quote calls 429s after a
  handful (measured live). Delays inside and between quotes hold the run
  to ~1 request/second — ~45 seconds per run, invisible at a five-minute
  cadence.

**Consequences**: The first live snapshot already answers RQ2's opening
question — the spread varies ~70× across tokens (SPYx 0.04%, NVDAx 0.10%,
PLTRx 2.7%) — and every run from now on records how it breathes across
weekends. A future reserve model can price the exit cost per symbol
instead of ignoring it.

---

## ADR-021 — Market holidays belong to the weekend engine

**Date**: 2026-09-01 · **Status**: Accepted

**Context**: ADR-019 routed sessions by weekday arithmetic and listed
holidays as a known limit: on a holiday the router said "regular" while
every venue was closed. Labor Day (Monday 2026-09-07) made the limit
concrete — a 72-hour dead zone the engine would have misrouted.

**Decision**:
- **A non-trading weekday routes exactly like a weekend**, for every
  window it owns. The overnight session that would trade *into* a holiday
  is closed too: Sunday 8 PM before a holiday Monday stays "weekend",
  because the 24/5 session only opens when the next day trades.
- **Trading days come from Alpaca's calendar endpoint**, fetched once per
  day and cached; a stale copy survives an outage. If the calendar has
  never been fetchable, the router falls back to weekday arithmetic — the
  pre-ADR-021 behaviour, in which a holiday order harmlessly queues.
- **Early-close days stay a known limit**: the 1 PM closes around
  Thanksgiving and Christmas are still routed as full days; an afternoon
  order queues instead of reaching the engine.

**Consequences**: Labor Day weekend runs Friday 8 PM → Tuesday 4 AM as one
continuous engine window, and the first scheduled-settlement run lands
Tuesday 2026-09-08 — with real 72-hour gap data behind it.

---

## ADR-022 — Custody of weekend-sold shares: a ledger lock, because the sandbox cannot journal securities

**Date**: 2026-09-01 · **Status**: Accepted

**Context**: Between a Saturday sell and Monday's settlement, the trader
holds both the advance *and* the shares the engine will sell. Nothing
stopped them selling those shares themselves first, leaving Yagnum with
cash advanced against a share that was gone. The clean fix is Alpaca's
securities journal (JNLS): move the share into a Yagnum account on
Saturday, the way the cash moves to the trader. Tested live 2026-09-01:
`customer-to-customer JNLS not enabled`, `customer-to-firm JNLS not
enabled` — a correspondent entitlement Alpaca must switch on, in both
directions, and not one a sandbox can grant itself. A dedicated engine
trading account was created for the purpose (`weekend-engine@yagnum.app`,
`6cbc0608…`, ACTIVE, empty) and stands ready for the day JNLS is enabled.

**Decision**:
- **The engine keeps a ledger lock.** `committed_shares(account, symbol)`
  = the quantity in open (`provisional`, `awaiting_settlement`) weekend
  sells. Every path that could sell those shares subtracts it first: a
  second weekend sell, the regular order ticket (`400 shares_committed`),
  and reset-balance (`409 weekend_trades_open`). Since Yagnum's app is the
  trader's only route to the broker, the lock is complete in practice.
- **Settlement still sells from the trader's account**, as today.
- **Residual risk, named**: a trader who reaches the broker outside the
  app could still sell committed shares; the engine's settlement would
  then fail with an event, and the advance becomes a debit owed. Accepted
  for a sandbox; **production must request JNLS enablement from Alpaca**
  and switch to true custody (the seam is `_check_sell_shares` and
  `_place_hedge`; the engine account already exists).

**Consequences**: The Saturday trade now behaves like a sale even though
the share has not physically moved. The production checklist gains one
line. A future ADR moves custody to the engine account once Alpaca allows
it; nothing in the trade's arithmetic changes when that happens.

---

## ADR-023 — The settlement job: a weekday-morning cron, idempotent, from 8:00 AM ET

**Date**: 2026-09-01 · **Status**: Accepted

**Context**: ADR-019 decided that a scheduled job settles weekend trades
and that the hedge closes at Monday 8:00 AM ET premarket, rolling into the
9:30 auction. Until now settlement was a button. The first real run will
be Tuesday 2026-09-08, after Labor Day.

**Decision**:
- **`weekend.settle_all_open`** is the job's body: every open trade, any
  account, `mode=market`, oldest first. One trade's refusal is recorded on
  its event trail and counted; the loop continues.
- **A GitHub Actions cron runs it every ten minutes, 12:00–15:50 UTC,
  Monday–Friday** (8:00–11:50 AM EDT; 7:00–10:50 AM EST — both inside
  premarket or the regular session). Same infrastructure and secrets as
  the sampler (ADR-016); the job places sandbox orders and moves sandbox
  cash, so it is pinned to the `Yagnum` repository owner and never runs
  from a fork.
- **Idempotent by construction**: a trade still `awaiting_settlement`
  has its order checked again; a settled one is skipped; a weekend or
  holiday run finds no session (ADR-021) and exits. Running it by hand
  (`scripts/settle_weekend.py --write`) or from the button is the same
  code path.
- **Rolling to the auction is the day order itself**: an extended-hours
  day limit works through premarket, the open, and the regular session.
  Known limit: the limit price is set from the last trade at placement,
  so a price that gaps below it by 9:30 leaves the order unfilled until
  it expires at the close; the trade then returns to `provisional` and
  the next morning's run re-prices it.

**Consequences**: A weekend trade now completes with zero clicks. The
job's log is the first record of real premarket execution quality —
fill times and prices from our own orders, which no free feed gives us.

---

## ADR-024 — Overnight hours queue at the broker

**Date**: 2026-09-02 · **Status**: Accepted

**Context**: ADR-019 left the 8 PM–4 AM row of the routing table open
pending one sandbox test of Alpaca's 24/5 session. The test ran Tuesday
2026-09-01 at 8:05 PM ET: two 1-share limit buys just above the last
trade — one with `extended_hours`, one plain — were accepted and then sat
unfilled for 90 seconds before being cancelled. The sandbox has no
overnight execution: Alpaca's docs say the session needs enablement by
their team, and the free data feed carries no overnight prints to fill
against.

**Decision**: **An order placed between 8 PM and 4 AM on a weeknight
queues at the broker** and executes at 4:00 AM premarket (with
`extended_hours`) or the 9:30 open. The routing table is unchanged in
code — this was already the behaviour — and the weekend engine stays a
weekend-and-holiday product. The alternative, extending the engine over
those hours, was declined: it would take gap risk over a window that a
regulated venue serves in production, for a benefit (a few hours of
immediacy) the paper does not claim.

**Consequences**: The five-window table is final. If 24/5 is ever
enabled for the correspondent, `sessions.py` already names the window
and `_place_hedge` already shapes an overnight order; adopting it is a
one-line change plus a re-run of this test.

---

## ADR-025 — Version B adopted, shadow hedge first; Yagnum signs but does not send

**Date**: 2026-09-04 · **Status**: Accepted

**Context**: ADR-017/019 built Version A: pass-through settlement, no
on-chain hedge, Yagnum never touches Solana. It works and it is honest,
but the owner's purpose for this project is to learn the crypto
ecosystem in detail — who pays gas, how a swap is built and signed, what
a token account costs, how Jupiter earns — and Version A hides all of
it. The paper's own design (Version B) guarantees the customer the
weekend price and mirrors the trade in the token. Whether B is worth its
cost (spread crossed twice, gas, inventory, tracking error) is a number
nobody has measured.

**Decision**: **Build toward Version B in two steps.** Step one, done
today: every weekend trade gets a **shadow hedge** — the on-chain mirror
is quoted, built by Jupiter against a real engine wallet, signed with the
engine keypair where it is held, simulated on mainnet, and recorded in
`hedge_legs` with its fees in lamports and dollars; at settlement the
close leg records `broker_pnl`, `chain_pnl` and `version_b_pnl` for that
trade. **Nothing is sent.** Step two, a later ADR: fund the wallet and
send, behind a flag, after two questions are answered — the capital
(SOL, USDC and xStock inventory, because a DEX cannot short) and Backed's
terms, which state xStocks are not offered to US persons. Version A
remains the live settlement meanwhile.

The rule "Yagnum never signs an on-chain transaction" (ADR-017) is
replaced by: **Yagnum signs, never sends, until ADR-0xx says otherwise.**
The secret key lives only in the local `.env`; the GitHub Actions hosts
hold the public key and build unsigned (simulation does not verify
signatures).

**Consequences**: The first hedge legs ran the same afternoon (trade 7:
$0.19 of gas per leg, 99.7% of it token-account rent; simulation fails
`AccountNotFound` on the empty wallet, which is the honest result). Every
sim and user trade from tonight on carries the Version B figure. The
trader-facing behaviour is unchanged. New settings: `HEDGE_MODE`,
`SOLANA_RPC_URL`, `SOLANA_ENGINE_KEYPAIR`, `SOLANA_ENGINE_PUBKEY`. New
docs: `SHADOW-HEDGE.md`, `SOLANA-GAS-AND-JUPITER.md`.

---

## ADR-026 — Simulated traders: language-model personas through the real engine

**Date**: 2026-09-04 · **Status**: Accepted

**Context**: One person clicking a button produces one weekend trade a
day. The engine has never been exercised by many trades at once, and the
hedge (ADR-025) needs trades to price. The owner asked for free
language-model agents (Groq) to simulate realistic users over the
weekend and record everything.

**Decision**: **Eight personas, each with its own funded sandbox account,
each deciding by itself** — when, what and how much — from a briefing of
its own account and the sampler's prices, answering one JSON intent per
turn. Three rules:

1. **The model never touches money.** The intent goes through the same
   code path as a person's order (`weekend.open_trade`, or an Alpaca
   order) and the engine's own checks accept or refuse it.
2. **Everything is recorded.** Briefing, prompt, raw answer, model, token
   counts, latency, the parsed intent and the outcome, in
   `sim_decisions`. Sim trades carry `weekend_trades.source = 'sim'`.
3. **What it is evidence of is stated in the code and the doc.** The
   population tests the engine and prices the hedge. It says nothing
   about markets.

Cadence follows Groq's free plan (200K tokens/day at ~2K per decision):
hourly cron, two alternating groups, each persona every two hours, 20 s
between calls, stop on 429. The job fails visibly without a key rather
than substituting scripted decisions — the owner chose agents, so agents
or nothing.

**Consequences**: Provisioned 2026-09-04: eight accounts, $50,000 each,
$25,000 starter baskets bought in the after-hours session. First
unattended turn at 8:07 PM ET tonight once `GROQ_API_KEY` is set. About
100 decisions a day; Tuesday's settlement run will be the first with
dozens of open trades. New tables `sim_users`, `sim_decisions`; script
`scripts/sim_users.py`; workflow `sim-users.yml`; doc `SIM-USERS.md`.

