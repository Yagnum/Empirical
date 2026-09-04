"""Shared test fixtures.

The app is a flat set of modules at `app/api/`, so tests import them the same
way the app does (`import alpaca`) once that directory is on the path.

THE DATABASE (ADR-014)
    Two rules, both deliberate.

    1. **Off by default.** Every test starts with `DATABASE_URL` blanked, so
       the pre-ADR-014 contract tests exercise exactly the degraded path the
       API must support with no database configured — and so a test can never
       write to a real database by accident. (It nearly did: the first run
       after wiring `ledger.refresh` into `GET /activities` pushed mock
       fixtures into the development branch.)

    2. **Real Postgres when we do test the database.** The `database` fixture
       creates a throwaway *schema* in the same Neon development branch and
       points the app at it, then drops it. Not a second Neon branch (nothing
       to clean up if a run dies), and deliberately not SQLite: SQLAlchemy's
       NUMERIC on SQLite round-trips through a binary float, which is the one
       thing ADR-010 exists to prevent. A FIFO test that passes on floats and
       fails on Postgres would be worse than no test. Where no database is
       configured at all, those tests skip and say so.

    The schema is built over the **unpooled** URL: DDL and PgBouncer's
    transaction mode do not mix (see the neon-postgres skill).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import clerk_auth  # noqa: E402
import db  # noqa: E402
import ledger  # noqa: E402
from config import settings  # noqa: E402
from main import app  # noqa: E402
from models import Base  # noqa: E402

TEST_USER_ID = "user_test"
TEST_ACCOUNT_ID = "acct-test-0001"

# Per-process so two pytest runs (or an -n auto worker) never share tables.
TEST_SCHEMA = f"yagnum_test_{os.getpid()}"

# Truncated between tests. Children first: the FKs point at `fills` and
# `weekend_trades`.
_TABLES = [
    "audit_log",
    "order_intents",
    "realized_pnl",
    "lots",
    "fills",
    "token_prices",
    "token_candles",
    "market_bars",
    "hedge_legs",
    "weekend_trade_events",
    "weekend_trades",
    "sim_decisions",
    "sim_users",
]


@pytest.fixture(autouse=True)
def database_off(monkeypatch):
    """No database unless a test explicitly asks for one.

    Autouse, so this is the default for the whole suite and the `database`
    fixture below simply overrides it.
    """
    monkeypatch.setattr(settings, "database_url", "")
    # Nothing in the suite may reach the chain or the model by accident: the
    # shadow hedge (ADR-025) and the Groq client (ADR-026) are off unless a
    # test switches them on against a fake.
    monkeypatch.setattr(settings, "hedge_mode", "off")
    monkeypatch.setattr(settings, "solana_engine_keypair", "")
    monkeypatch.setattr(settings, "solana_engine_pubkey", "")
    monkeypatch.setattr(settings, "groq_api_key", "")
    ledger._last_sync.clear()
    yield


@pytest.fixture(scope="session")
def test_engine():
    """A private schema in the development branch, dropped when the run ends."""
    url = settings.database_url_unpooled or settings.database_url
    if not url:
        pytest.skip("no DATABASE_URL_UNPOOLED configured; database tests need real Postgres")

    admin = sa.create_engine(db.normalize_url(url))
    with admin.begin() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{TEST_SCHEMA}"'))
    admin.dispose()

    # `-c search_path=` is applied when the connection opens, so every
    # statement lands in our schema without any model needing a schema name.
    engine = sa.create_engine(
        db.normalize_url(url),
        connect_args={"options": f"-csearch_path={TEST_SCHEMA}"},
        pool_pre_ping=True,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()

    admin = sa.create_engine(db.normalize_url(url))
    with admin.begin() as connection:
        connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE'))
    admin.dispose()


@pytest.fixture
def database(test_engine, monkeypatch):
    """Point the app at the test schema, empty, for one test."""
    monkeypatch.setattr(settings, "database_url", settings.database_url_unpooled or settings.database_url)
    db.configure(test_engine)
    ledger._last_sync.clear()
    with test_engine.begin() as connection:
        connection.execute(
            sa.text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
        )
    yield test_engine


@pytest.fixture
def session(database):
    """A plain SQLAlchemy session on the test schema, for asserting on rows."""
    with db.session_scope() as opened:
        yield opened


@pytest.fixture
def client():
    """A client whose requests are already "signed in".

    `dependency_overrides` replaces the Clerk dependencies with constants, so
    the tests exercise the *real* routers, validation and serialisation while
    skipping the one part that needs a live third party. Nothing else is
    faked at the framework level.
    """
    app.dependency_overrides[clerk_auth.require_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[clerk_auth.require_account_id] = lambda: TEST_ACCOUNT_ID
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def db_client(database, client):
    """The signed-in client, with the test schema wired up behind it."""
    return client


@pytest.fixture
def anon_client():
    """A client with no auth override, for checking the 401 path."""
    app.dependency_overrides.clear()
    with TestClient(app) as test_client:
        yield test_client
