"""
Migration 0001 — multi-KB columns + knowledge_bases table (Phase 4).

Additive and idempotent, in the style of ../migrate_analytics_to_pg.py, and
safe on both SQLite (dev/CI) and Postgres (prod) via the SQLAlchemy
inspector:

  1. ADD COLUMN knowledge_base_id VARCHAR(64) DEFAULT 'customer_sap' to
     conversations / projects / messages / chat_events / feedback_events /
     token_events — only for tables that exist and don't already have the
     column (a fresh DB created via Base.metadata.create_all already has it
     and every step below is a no-op).
  2. CREATE TABLE IF NOT EXISTS knowledge_bases (id, name, custom_prompt,
     enhanced_prompt, prompt_updated_at, created_at).
  3. Seed the `customer_sap` row if the table doesn't already have one.
  4. Backfill any NULL knowledge_base_id (rows written before step 1's
     DEFAULT existed) to 'customer_sap'.

Every step is guarded by an existence/value check, so re-running is a no-op.

Usage (from backend/, with the target DATABASE_URL / DATABASE_URL_SYNC set in
the environment or .env — same convention as migrate_analytics_to_pg.py):

    python -m migrations.m0001_multi_kb
    python migrations/m0001_multi_kb.py

Programmatic use (e.g. tests) can pass an explicit engine to `run()` instead
of relying on the module-level `db.sync_engine`:

    from migrations.m0001_multi_kb import run
    run(engine=my_test_engine)
"""

import sys
from pathlib import Path

# Support `python migrations/m0001_multi_kb.py` (run outside `-m`, where
# sys.path[0] is the migrations/ dir, not backend/) as well as `-m`.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

import db

DEFAULT_KB_ID = "customer_sap"
DEFAULT_KB_NAME = "Customer / SAP Data Quality Rules"

# Every existing table that needs a knowledge_base_id column. Order doesn't
# matter — each ALTER is independent.
_TABLES_NEEDING_KB_COLUMN = [
    "conversations",
    "projects",
    "messages",
    "chat_events",
    "feedback_events",
    "token_events",
]


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def add_kb_columns(conn) -> list[str]:
    """ALTER TABLE ... ADD COLUMN knowledge_base_id on every table that
    exists and is missing it. Returns the list of tables actually altered."""
    inspector = inspect(conn)
    altered: list[str] = []
    for table in _TABLES_NEEDING_KB_COLUMN:
        if not _has_table(inspector, table):
            continue  # table doesn't exist in this DB yet — nothing to alter
        if _has_column(inspector, table, "knowledge_base_id"):
            continue  # already migrated (or created fresh with the new model)
        conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN knowledge_base_id "
            f"VARCHAR(64) DEFAULT '{DEFAULT_KB_ID}'"
        ))
        altered.append(table)
    return altered


def create_knowledge_bases_table(conn) -> bool:
    """CREATE TABLE IF NOT EXISTS knowledge_bases. Returns True if the table
    did not exist before (works on both SQLite and Postgres)."""
    inspector = inspect(conn)
    if _has_table(inspector, "knowledge_bases"):
        return False
    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS knowledge_bases (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            custom_prompt TEXT,
            enhanced_prompt TEXT,
            prompt_updated_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE
        )
        """
    ))
    return True


def seed_default_kb(conn) -> bool:
    """Insert the customer_sap row if absent. Returns True if inserted."""
    existing = conn.execute(
        text("SELECT id FROM knowledge_bases WHERE id = :id"),
        {"id": DEFAULT_KB_ID},
    ).first()
    if existing is not None:
        return False
    conn.execute(
        text(
            "INSERT INTO knowledge_bases (id, name, created_at) "
            "VALUES (:id, :name, CURRENT_TIMESTAMP)"
        ),
        {"id": DEFAULT_KB_ID, "name": DEFAULT_KB_NAME},
    )
    return True


def backfill_null_kb_ids(conn) -> dict[str, int]:
    """UPDATE any row with a NULL knowledge_base_id to 'customer_sap'.

    Only NULLs written before the column had a DEFAULT (e.g. rows present
    before this migration ran) need this; new rows get the DEFAULT/ORM
    default automatically. Returns {table: rows_updated} for tables that had
    at least one row backfilled.
    """
    inspector = inspect(conn)
    backfilled: dict[str, int] = {}
    for table in _TABLES_NEEDING_KB_COLUMN:
        if not _has_table(inspector, table) or not _has_column(inspector, table, "knowledge_base_id"):
            continue
        result = conn.execute(
            text(f"UPDATE {table} SET knowledge_base_id = :kb WHERE knowledge_base_id IS NULL"),
            {"kb": DEFAULT_KB_ID},
        )
        if result.rowcount:
            backfilled[table] = result.rowcount
    return backfilled


def run(engine: Engine | None = None) -> dict:
    """Run the full migration in one transaction. Returns a summary dict.

    `engine` defaults to db.sync_engine (bound to the configured
    DATABASE_URL/DATABASE_URL_SYNC) — pass an explicit engine (e.g. a
    throwaway SQLite file) for testing without touching the app's DB.
    """
    engine = engine or db.sync_engine
    summary = {
        "columns_added": [],
        "kb_table_created": False,
        "kb_seeded": False,
        "backfilled": {},
    }
    with engine.begin() as conn:
        summary["columns_added"] = add_kb_columns(conn)
        summary["kb_table_created"] = create_knowledge_bases_table(conn)
        summary["kb_seeded"] = seed_default_kb(conn)
        summary["backfilled"] = backfill_null_kb_ids(conn)
    return summary


def main() -> None:
    summary = run()
    print(f"[migration 0001] columns added: {summary['columns_added'] or 'none (already present)'}")
    print(f"[migration 0001] knowledge_bases table created: {summary['kb_table_created']}")
    print(f"[migration 0001] {DEFAULT_KB_ID!r} seeded: {summary['kb_seeded']}")
    print(f"[migration 0001] backfilled rows: {summary['backfilled'] or 'none'}")
    print("[migration 0001] done - safe to re-run (no-op on an already-migrated DB).")


if __name__ == "__main__":
    main()
