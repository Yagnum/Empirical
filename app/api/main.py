"""Yagnum API — Phases 1–3.

A FastAPI service that acts as the secure middleman between the Next.js
frontend and Alpaca's Broker API. The browser never talks to Alpaca directly:
only this server holds the Alpaca credentials.

Layout (deliberately flat — a few small modules, easy to read end to end):

    config.py            settings / secrets loading
    clerk_auth.py        verify the Clerk session token; read+write user metadata
    alpaca.py            thin client for Alpaca (Broker API + market data)
    db.py                the Postgres engine, session factory and dependency
    models.py            the five SQLAlchemy tables of ADR-014
    audit.py             write one audit_log row per state-changing request
    ledger.py            fills -> FIFO lots -> realized P/L
    offboarding.py       flatten positions + return cash (webhook and reset)
    routes_accounts.py   POST /accounts, GET /accounts/me, POST /accounts/reset
    routes_funding.py    POST /funding
    routes_market.py     GET /market/clock, /market/assets, /market/quotes, /market/bars
    routes_orders.py     POST/GET/DELETE /orders
    routes_portfolio.py  GET /positions, GET /portfolio/history
    routes_activity.py   GET /activities, /activities/export.csv, /documents
    routes_pnl.py        GET /pnl/realized
    routes_webhooks.py   POST /webhooks/clerk

Explore it at http://localhost:8000/docs. Everything except /health and
/webhooks/clerk (which authenticates by Svix signature, not session) needs a
Clerk session token: click **Authorize**, paste a token from
`uv run python scripts/dev_token.py`, and the try-it-out buttons work.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import audit
import db
import routes_accounts
import routes_activity
import routes_funding
import routes_market
import routes_orders
import routes_pnl
import routes_portfolio
import routes_webhooks
from config import settings

app = FastAPI(
    title="Yagnum API",
    version="0.3.0",
    description=(
        "Paper-trading backend on Alpaca's Broker API sandbox. "
        "All money and prices cross this boundary as **strings** (ADR-010); "
        "parse them with a decimal-safe type, never a float."
    ),
)

# The frontend runs on a different origin (localhost:3000), so the browser
# enforces CORS: this middleware tells it our frontend is allowed to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this the browser hides Content-Disposition from fetch(), and the
    # CSV export and document download lose their filenames.
    expose_headers=["Content-Disposition", audit.REQUEST_ID_HEADER],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Give every request an id, and tell the caller what it was.

    One id ties a browser network entry, a server log line and an `audit_log`
    row together - which is the difference between "a user says their order
    failed" and "here is the row". A client-supplied `X-Request-ID` is trusted
    and echoed, because it lets the Next.js proxy stitch its own logs to ours;
    it is only ever used as a correlation label, never for a decision, so a
    forged one costs nothing.
    """
    incoming = request.headers.get(audit.REQUEST_ID_HEADER, "")[:64].strip()
    request.state.request_id = incoming or audit.new_request_id()
    response = await call_next(request)
    response.headers[audit.REQUEST_ID_HEADER] = request.state.request_id
    return response


app.include_router(routes_accounts.router)
app.include_router(routes_funding.router)
app.include_router(routes_market.router)
app.include_router(routes_orders.router)
app.include_router(routes_portfolio.router)
app.include_router(routes_activity.router)
app.include_router(routes_pnl.router)
app.include_router(routes_webhooks.router)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "yagnum-api",
        # Report presence only — never echo secret values in a response.
        "alpaca_keys_loaded": bool(
            settings.alpaca_broker_id and settings.alpaca_broker_secret
        ),
        # Same rule for the database: whether a URL is configured, never the
        # URL itself (it carries a password).
        "database_configured": db.is_configured(),
    }
