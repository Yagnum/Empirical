"""Alembic's entry point: where a migration gets its database.

TWO THINGS THIS FILE DOES DIFFERENTLY FROM THE TEMPLATE

1. The URL comes from `config.settings`, not from `alembic.ini`. Every secret
   in this repo lives in one repo-root `.env` (see config.py); a second copy
   in a checked-in ini file is exactly the mistake that leaks credentials.

2. It uses **DATABASE_URL_UNPOOLED** — Neon's direct endpoint. The pooled URL
   the app runs on is PgBouncer in transaction mode, which does not carry
   session state; DDL and pooler do not mix, and the failures are obscure
   (a `SET search_path` that evaporates, a stale prepared statement). The
   direct URL is the documented choice for migrations.

The URL is never written into the Alembic config object, so it cannot end up
in an error message or a log line — and a `%` in a password cannot collide
with configparser interpolation.

Usage (from app/api):
    uv run alembic revision --autogenerate -m "..."
    uv run alembic upgrade head
    uv run alembic current
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool

from alembic import context

# app/api/alembic/env.py -> app/api, so `import config` works the same way it
# does for the app itself (flat modules, no package).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
from config import settings  # noqa: E402
from models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# What `--autogenerate` compares the live database against.
target_metadata = Base.metadata


def database_url() -> str:
    """The direct (unpooled) URL, driver prefix included."""
    url = settings.database_url_unpooled or settings.database_url
    if not url:
        raise SystemExit(
            "DATABASE_URL_UNPOOLED is not set. Add it to the repo-root .env "
            "(Neon: the connection string whose host has no '-pooler')."
        )
    return db.normalize_url(url)


def run_migrations_offline() -> None:
    """`alembic upgrade --sql`: print the DDL instead of running it."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # NullPool: a migration opens one connection, uses it, and exits. Pooling
    # a connection nobody will reuse just delays the process shutdown.
    connectable = create_engine(database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Without this, autogenerate sees VARCHAR(64) -> VARCHAR(128) as
            # "no change" and quietly skips the alter.
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
