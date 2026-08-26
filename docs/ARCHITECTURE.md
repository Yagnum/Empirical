# Yagnum — MVP Architecture

This describes the **Phase 0–4 MVP**: a paper-trading web app on Alpaca's
Broker API sandbox. The crypto/Jupiter/ERR layers from the research paper
come later and will extend — not replace — this foundation.

We use the [C4 model](https://c4model.com) vocabulary: a **context diagram**
shows our system vs. the outside world; a **container diagram** shows the
separately-runnable pieces inside it. Diagrams are Mermaid (GitHub renders
them inline); exported SVGs live in `docs/diagrams/` for the paper.

For *why* each technology was chosen, see [DECISIONS.md](DECISIONS.md).
For the trade loop, the Alpaca calls, and the no-database design, see
[TRADING-FLOW.md](TRADING-FLOW.md). For funding, see [ALPACA-FUNDING.md](ALPACA-FUNDING.md).

## Level 1 — System context

```mermaid
graph LR
    U["User (trader)"] -->|uses| Y["Yagnum"]
    Y -->|trades via| A["Alpaca (sandbox)"]
    Y -->|authenticates via| C["Clerk"]
```

## Level 2 — Containers

```mermaid
graph TB
    Browser["User's browser"]

    subgraph Yagnum["Yagnum (this repo)"]
        Web["Next.js — app/web · port 3000
UI, routing, session handling"]
        Api["FastAPI — app/api · port 8000
sole holder of broker secrets"]
    end

    subgraph External["External services"]
        Clerk["Clerk
users, sessions, user metadata"]
        Alpaca["Alpaca Broker API (sandbox)
one brokerage account per user
+ market data"]
    end

    Browser -->|pages, forms| Web
    Browser -.->|sign-in UI components| Clerk
    Web -->|HTTP + Clerk session JWT| Api
    Api -->|verify JWT · read/write metadata| Clerk
    Api -->|REST: accounts, funding, orders| Alpaca

    style Web fill:#eff6ff,stroke:#3b82f6,stroke-width:1.5px
    style Api fill:#dbeafe,stroke:#1d4ed8,stroke-width:1.5px
    style Clerk fill:#f8fafc,stroke:#94a3b8
    style Alpaca fill:#f8fafc,stroke:#94a3b8
    style Browser fill:#ffffff,stroke:#64748b
```

## The security pattern that shapes everything

**The browser never talks to Alpaca.** Only FastAPI holds the Alpaca keys.
Each request from the frontend carries the user's Clerk session token (a JWT);
FastAPI verifies it against Clerk's public keys, looks up that user's Alpaca
account ID (stored in Clerk user metadata — see ADR-003), and acts on exactly
that account. A user can therefore never touch another user's account, and the
secrets never reach client-side code.

## Request walk-through: "Buy 2 AAPL"

```mermaid
sequenceDiagram
    autonumber
    actor U as User (signed in)
    participant W as Next.js (app/web)
    participant F as FastAPI (app/api)
    participant C as Clerk
    participant A as Alpaca (sandbox)

    U->>W: Submit buy form (2 × AAPL)
    W->>F: POST /orders — with Clerk session JWT
    F->>C: Verify JWT against Clerk public keys
    C-->>F: Valid — Clerk user id
    F->>C: Read user metadata
    C-->>F: alpaca_account_id
    F->>A: Create order: buy 2 AAPL on that account
    A-->>F: Order accepted (id, status, fill price)
    F-->>W: 200 — order details
    W-->>U: Confirmation + refreshed positions

    Note over F,A: Alpaca credentials only ever appear on this hop
```

## API contract (Phase 1)

All endpoints except `/health` require `Authorization: Bearer <Clerk JWT>`.
Monetary values are **strings**, never floats (see ADR-010).

| Endpoint | Purpose | Response |
| --- | --- | --- |
| `GET /health` | Liveness + config check (public) | `{status, service, alpaca_keys_loaded}` |
| `POST /accounts` | Idempotent Alpaca account provisioning | `{alpaca_account_id, created, status}` |
| `GET /accounts/me` | Account summary | `{alpaca_account_id, status, currency, cash, buying_power, portfolio_value, equity}` · `404 no_account` |
| `POST /funding` | Fund the paper account (sandbox) | `{transfer_id, status, amount}` |

## API contract (Phases 2–3)

Same auth rule. Full request and response schemas live in Swagger at
`http://localhost:8000/docs` and in `docs/postman/`.

| Endpoint | Purpose |
| --- | --- |
| `GET /market/clock` | Market open/closed, next open and close |
| `GET /market/assets?q=` | Symbol and name search (cached asset list) |
| `GET /market/quotes/{symbol}` | Latest bid, ask, and last trade |
| `GET /market/bars/{symbol}?timeframe=&limit=` | OHLCV bars for charts |
| `POST /orders` · `GET /orders` · `GET /orders/{id}` · `DELETE /orders/{id}` | Place, list, inspect, cancel orders |
| `GET /positions` | Open positions with unrealized P/L |
| `GET /portfolio/history?period=&timeframe=` | Equity over time |
| `GET /activities` · `GET /activities/export.csv` | Transaction history and CSV statement |
| `GET /documents` · `GET /documents/{id}/download` | Alpaca-issued documents |

Developer tools: `scripts/dev_token.py` mints a one-hour Clerk token for
Swagger and Postman. `scripts/make_postman.py` regenerates the collection.

## Phases

- **Phase 0 — Foundations** ✅: scaffold, docs, health-check plumbing.
- **Phase 1 — Identity & onboarding** ✅ verified live in a browser (2026-08-24): Clerk sign-in → Alpaca account created → $10,000 deposit accepted → dashboard renders. Journal deposits settle after the sandbox journal limits were raised (ALPACA-FUNDING.md §7).
- **Phase 2 — Trading core**: symbol lookup + quotes, buy/sell by quantity, order status.
- **Phase 3 — Dashboard**: positions, cash/buying power, portfolio value, order history.
- **Phase 4 — Production polish**: error/loading states, tests, deployment.
- **Phase 5+ — Paper territory**: market-hours awareness, Jupiter integration, ERR engine, gap-volatility research (`notebooks/`).

## Running locally

```
# Terminal 1 — API
cd app/api && uv run uvicorn main:app --reload

# Terminal 2 — Web
cd app/web && npm run dev
```

Then open http://localhost:3000.
