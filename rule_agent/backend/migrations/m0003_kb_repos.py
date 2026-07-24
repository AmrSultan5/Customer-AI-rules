"""
Migration 0003 — kb_repos table (self-service Git-repo KBs, Phase 9).

Additive and idempotent, in the style of ./m0002_rag.py: CREATE TABLE IF NOT
EXISTS kb_repos straight from the ORM definition in models.py (SQLAlchemy's
Table.create(checkfirst=True) generates correct, dialect-appropriate DDL for
both engines, so there is no hand-written SQL to keep in sync with
models.py), safe on both SQLite (dev/CI) and Postgres (prod).

Usage (from backend/, with the target DATABASE_URL / DATABASE_URL_SYNC set in
the environment or .env):

    python -m migrations.m0003_kb_repos
    python migrations/m0003_kb_repos.py

Programmatic use (e.g. tests) can pass an explicit engine to `run()` instead
of relying on the module-level `db.sync_engine`:

    from migrations.m0003_kb_repos import run
    run(engine=my_test_engine)
"""

import sys
from pathlib import Path

# Support `python migrations/m0003_kb_repos.py` (run outside `-m`, where
# sys.path[0] is the migrations/ dir, not backend/) as well as `-m`.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

import db


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def create_kb_repos_table(conn) -> bool:
    """CREATE TABLE IF NOT EXISTS kb_repos from the ORM definition in
    models.py. Returns True if the table did not exist before."""
    import models  # noqa: F401 — registers KbRepo on Base.metadata

    inspector = inspect(conn)
    created = not _has_table(inspector, "kb_repos")
    models.KbRepo.__table__.create(bind=conn, checkfirst=True)
    return created


def run(engine: Engine | None = None) -> dict:
    """Run the full migration in one transaction. Returns a summary dict.

    `engine` defaults to db.sync_engine (bound to the configured
    DATABASE_URL/DATABASE_URL_SYNC) — pass an explicit engine (e.g. a
    throwaway SQLite file) for testing without touching the app's DB.
    """
    engine = engine or db.sync_engine
    summary = {"kb_repos_created": False}
    with engine.begin() as conn:
        summary["kb_repos_created"] = create_kb_repos_table(conn)
    return summary


def main() -> None:
    summary = run()
    print(f"[migration 0003] kb_repos table created: {summary['kb_repos_created']}")
    print("[migration 0003] done - safe to re-run (no-op on an already-migrated DB).")


if __name__ == "__main__":
    main()
