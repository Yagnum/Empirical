"""The database connection: one engine, one session factory, one dependency.

ADR-014 brought Postgres in for the three things Alpaca cannot hold — an
audit log, order idempotency, and a fills ledger for realized P/L. This module
is the only place that knows how to open a connection.

DEGRADE, DO NOT CRASH
    `DATABASE_URL` unset is a supported state. `is_configured()` is False,
    `get_session` yields nothing, and every database-touching feature skips
    itself. The API still boots and every Alpaca route still works. That keeps
    a missing secret from taking the whole service down, and it keeps the
    contract tests runnable without a database.

POOLED VS DIRECT (Neon)
    Neon publishes two hostnames for the same database. The pooled one
    (`-pooler`, PgBouncer in transaction mode) is what an app should use:
    short connection-per-request queries, many of them. The direct one is for
    migrations, dumps and anything relying on session state — DDL and a
    transaction-mode pooler do not mix. Alembic reads
    `DATABASE_URL_UNPOOLED`; everything here reads `DATABASE_URL`.

pool_pre_ping=True
    Neon computes scale to zero after ~5 minutes idle and drop their
    connections. Without a pre-ping the first query after an idle spell dies
    on a stale socket. The ping costs one round trip and turns that class of
    failure into a transparent reconnect.

SYNC, like the rest of the codebase: FastAPI runs `def` handlers in a worker
thread, so a blocking query never stalls the event loop.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings

# SQLAlchemy needs the driver named in the scheme. Neon (and every other
# provider) hands out a bare `postgresql://` URL, so we add the driver here
# rather than asking every environment to write a SQLAlchemy-flavoured URL.
_DRIVER = "postgresql+psycopg"


def normalize_url(url: str) -> str:
    """`postgres://...` / `postgresql://...` -> `postgresql+psycopg://...`."""
    if not url:
        return ""
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return _DRIVER + "://" + url[len(prefix) :]
    return url  # sqlite:// and friends pass through untouched


def is_configured() -> bool:
    """True when a database URL is set. Everything DB-shaped checks this."""
    return bool(settings.database_url)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def engine() -> Engine:
    """The process-wide engine (and its connection pool), created on first use.

    Lazy rather than module-level so importing `db` never opens a socket —
    that is what lets the app boot with no database and lets tests point the
    engine somewhere else before anything connects.
    """
    global _engine
    if _engine is None:
        if not is_configured():
            raise RuntimeError("database_not_configured: DATABASE_URL is empty")
        _engine = create_engine(
            normalize_url(settings.database_url),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            future=True,
        )
    return _engine


def session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=engine(), expire_on_commit=False, future=True)
    return _session_factory


def configure(bind: Engine) -> None:
    """Point the module at an engine somebody else built (tests do this)."""
    global _engine, _session_factory
    _engine = bind
    _session_factory = sessionmaker(bind=bind, expire_on_commit=False, future=True)


def reset() -> None:
    """Drop the cached engine/factory. Tests use it; the app never needs it."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """A transaction: commit on a clean exit, roll back on any exception.

    Used by the background-ish work (audit writes, ledger sync) that is not a
    FastAPI dependency.
    """
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session | None]:
    """FastAPI dependency: a session per request, or None with no database.

    Yields, then commits if the handler returned and rolls back if it raised —
    so a route never has to remember either. Returning `None` (rather than
    raising) is the degrade path: the route decides whether it can carry on.
    """
    if not is_configured():
        yield None
        return
    with session_scope() as session:
        yield session
