"""Application settings.

Every secret lives in a single .env at the repo root (git-ignored) and is
loaded here by pydantic-settings. Nothing else in the codebase reads
environment variables directly, so there is exactly one place to look when
you wonder "where does this key come from?".
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/api/config.py -> parents[0]=app/api, [1]=app, [2]=repo root
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # --- Alpaca Broker API (sandbox) ---
    alpaca_broker_id: str = ""
    alpaca_broker_secret: str = ""
    alpaca_broker_base_url: str = "https://broker-api.sandbox.alpaca.markets"
    # The firm/sweep account that journal funding draws from (ADR-011).
    # Found in the Broker dashboard under Accounts -> Firm Accounts; when
    # empty we fall back to ACH transfers (1/day limit, minutes to clear).
    alpaca_firm_account_id: str = ""
    # Market data lives on a different host from the Broker API but takes the
    # same broker credentials (verified in sandbox, 2026-08-26).
    alpaca_data_base_url: str = "https://data.sandbox.alpaca.markets"

    # --- Clerk (test instance) ---
    clerk_secret_key: str = ""
    # Signing secret for the Clerk webhook endpoint (ADR-015). From the Clerk
    # Dashboard -> Webhooks -> (endpoint) -> Signing Secret; starts with
    # `whsec_`. Empty means POST /webhooks/clerk answers 503 rather than ever
    # accepting an unsigned event.
    clerk_webhook_signing_secret: str = ""
    # Accept session tokens that carry no `azp` claim. Only the Backend API
    # mints such tokens (scripts/dev_token.py, for Swagger and Postman), and
    # only a holder of CLERK_SECRET_KEY can call it. Set to false in
    # production so every token must be pinned to the frontend origin.
    allow_tokens_without_azp: bool = True

    # --- Database (ADR-014) ---
    # Two URLs for the same Postgres. Neon hands out a *pooled* endpoint
    # (hostname with `-pooler`, PgBouncer in transaction mode) and a *direct*
    # one. The app uses the pooled URL — many short connection-per-request
    # queries. Alembic uses the direct URL, because DDL and session-level
    # state do not survive a transaction-mode pooler.
    #
    # Both default to "" so the API still boots and serves every non-database
    # route with no database configured: db.py degrades instead of crashing.
    database_url: str = ""
    database_url_unpooled: str = ""

    # --- Misc ---
    jup_api_key: str = ""  # used in later crypto phases
    frontend_origin: str = "http://localhost:3000"
    # Every outbound HTTP call gets a timeout; a hung broker call must never
    # hang one of our request workers forever.
    http_timeout_seconds: float = 30.0


settings = Settings()
