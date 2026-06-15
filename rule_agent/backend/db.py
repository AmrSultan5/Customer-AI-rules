"""
Database layer — SQLAlchemy engines, sessions, and the declarative Base.

The app persists users, projects, conversations, messages, and analytics in a
single relational database. Two engines are exposed because the codebase has
both async request-path callers and one synchronous caller
(`analytics.track_token_usage_sync`, invoked from sync code in
`explanation_engine`):

  • async_engine / AsyncSessionLocal  — asyncpg (Postgres) or aiosqlite (dev/tests)
  • sync_engine  / SyncSessionLocal   — psycopg (Postgres) or sqlite (dev/tests)

The same ORM models therefore run on Postgres in production and on SQLite in
local dev and tests. Configure with DATABASE_URL; it defaults to a local SQLite
file so the app runs with zero configuration.

NullPool is used for the async engine so connections are never cached across
event loops — the analytics tests drive it with repeated `asyncio.run(...)`
calls, each on a fresh loop, which a pooled connection would break.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

_DATA_DIR = Path(__file__).parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Default to a local SQLite file (async driver). Set DATABASE_URL to a Postgres
# DSN in production, e.g. postgresql+asyncpg://user:pass@host:5432/rule_agent
_DEFAULT_ASYNC_URL = f"sqlite+aiosqlite:///{(_DATA_DIR / 'rule_agent.db').as_posix()}"

DATABASE_URL = os.environ.get("DATABASE_URL", _DEFAULT_ASYNC_URL)


def _to_sync_url(async_url: str) -> str:
    """Derive the synchronous DSN from the async one (asyncpg→psycopg, drop aiosqlite)."""
    return async_url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


SYNC_DATABASE_URL = os.environ.get("DATABASE_URL_SYNC", _to_sync_url(DATABASE_URL))

_is_sqlite = SYNC_DATABASE_URL.startswith("sqlite")
_sync_connect_args = {"check_same_thread": False} if _is_sqlite else {}


class Base(DeclarativeBase):
    pass


async_engine = create_async_engine(DATABASE_URL, future=True, poolclass=NullPool)
AsyncSessionLocal = async_sessionmaker(
    async_engine, expire_on_commit=False, class_=AsyncSession
)

sync_engine = create_engine(
    SYNC_DATABASE_URL, future=True, connect_args=_sync_connect_args
)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables if they do not exist. Called once on startup."""
    import models  # noqa: F401 — registers models on Base.metadata

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def reset_db() -> None:
    """Drop and recreate all tables. Test-only helper for a clean slate."""
    import models  # noqa: F401

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """FastAPI dependency yielding a request-scoped async session."""
    async with AsyncSessionLocal() as session:
        yield session
