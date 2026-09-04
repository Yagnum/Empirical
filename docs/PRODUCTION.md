# Production checklist

This document lists what must change before Yagnum serves anyone but its
developer. Most items are Clerk dashboard actions only a human can do; the
rest are environment variables. The Azure deployment guide will reference
this list.

Two Clerk instances exist for one application: **Development** (the keys in
use today, `pk_test_`/`sk_test_`) and **Production** (`pk_live_`/`sk_live_`,
created in the Clerk dashboard when you add a production domain). Test-mode
conveniences — `+clerk_test` emails, OTP `424242`, tokens without `azp` —
exist only in Development. That is why this list exists: production removes
the safety nets, so each removal must be deliberate.

## 1. Clerk dashboard (do these in both instances)

- [ ] **Rename the application to "Project Yagnum"** (Dashboard → Settings).
      The name appears on the sign-in card, in emails, and in SSO consent
      screens. Users must see the product's name, not a workspace default.
- [ ] **Disable Apple sign-in** (User & Authentication → Social connections).
      Clerk enables it by default. We never configured an Apple developer
      account, so the button is a dead end; a button that fails erodes the
      trust the design works to build. Keep Google and email.

## 2. Clerk dashboard (production instance only)

- [ ] **Create the production instance** by adding the real domain. Clerk
      issues `pk_live_` / `sk_live_` keys. Set the DNS records Clerk asks
      for (it proxies the auth frontend through your domain).
- [ ] **Register the offboarding webhook** (Configure → Webhooks → Add
      endpoint): URL `https://<api-domain>/webhooks/clerk`, subscribed to
      the `user.deleted` event only. Copy the signing secret (`whsec_…`)
      into the API's `CLERK_WEBHOOK_SIGNING_SECRET`. Without it the API
      refuses webhook events (ADR-015). This cannot be done before the API
      has a public URL, so it lands with the Azure deployment.
- [ ] **Send a test `user.deleted` event** from the Clerk webhook page and
      confirm a 204 (a test event carries a user id we never provisioned,
      so "nothing to do" is the correct answer).

## 3. Environment variables (production values)

| Variable | Dev value | Production value | Why it changes |
| --- | --- | --- | --- |
| `ALLOW_TOKENS_WITHOUT_AZP` | `true` | **`false`** | Dev tokens minted by `scripts/dev_token.py` carry no `azp` claim. In production every token must be pinned to the frontend origin, or a token minted for any other app on the same Clerk instance would be accepted. |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | `https://<web-domain>` | CORS allowlist and the `azp` check both compare against this. |
| `CLERK_SECRET_KEY` | `sk_test_…` | `sk_live_…` | Production instance key. |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_test_…` | `pk_live_…` | Same, for the frontend. |
| `CLERK_WEBHOOK_SIGNING_SECRET` | empty | `whsec_…` | See §2. Empty means the webhook route refuses all events. |
| `DATABASE_URL` / `DATABASE_URL_UNPOOLED` | Neon `development` branch | Azure Database for PostgreSQL | ADR-014: same engine, different host. Run `alembic upgrade head` against the unpooled URL at deploy time. |
| `ALPACA_*` | sandbox keys | sandbox keys (unchanged) | Yagnum stays a paper-trading app. There is no plan to hold real broker keys. |

## 4. Before the first outside user

- [ ] Confirm `/health` reports `alpaca_keys_loaded: true` and
      `database_configured: true` in the deployed API.
- [ ] Sign up with a real personal email end to end: provision, fund,
      trade one share, sell it, check realized P/L, reset the balance,
      delete the account, and confirm Alpaca shows the account closed
      within a day (the webhook may wait for market open — ADR-015).
- [ ] Check that the paper-trading banner and the "not a broker-dealer"
      footer render on every page. They are the honesty layer; the app
      must never look like it handles real money.

## Weekend engine (ADR-022)

- **Ask Alpaca to enable securities journals (JNLS) customer ↔ firm** for
  the correspondent. Until then the engine protects weekend-sold shares
  with a ledger lock inside the app; with JNLS enabled, custody moves to
  the engine account (`ALPACA_ENGINE_ACCOUNT_ID`, created 2026-09-01) and
  the lock becomes physical.

## Simulated traders and the shadow hedge (ADR-025, ADR-026)

- **Repository secrets** (Settings → Secrets and variables → Actions):
  `GROQ_API_KEY` for `sim-users.yml`; `ALPACA_FIRM_ACCOUNT_ID` for both
  `sim-users.yml` and `settle-weekend.yml` (they move sandbox cash).
  `JUP_API_KEY` is shared with the sampler.
- **The engine wallet's secret key never leaves the local `.env`.** The
  workflows carry only `SOLANA_ENGINE_PUBKEY`; they build and simulate
  unsigned. Rotate the keypair before any live send (a separate ADR).
- **In production, switch the sim off or give it its own correspondent.**
  Eight model-driven accounts trading beside real customers would
  confuse every report. `update sim_users set active = false` stops them;
  the history stays.
- **RPC**: the public mainnet endpoint is rate-limited. A Helius (or
  similar) key in `SOLANA_RPC_URL` is the upgrade once volume grows.

