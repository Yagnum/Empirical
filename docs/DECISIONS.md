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

**Date**: 2026-08-24 · **Status**: Accepted

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
