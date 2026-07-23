"""
Tests for migrations/m0001_multi_kb.py — the additive, idempotent script that
adds `knowledge_base_id` columns + the `knowledge_bases` table to a
pre-Phase-4 database.

Each test builds its own throwaway SQLite file with the OLD (pre-multi-KB)
table shapes — no `knowledge_base_id` columns, no `knowledge_bases` table —
via raw SQL (not the current ORM models, which already have the new columns),
then runs the migration against an explicit engine (migrations.m0001_multi_kb
.run(engine=...) takes one instead of always using db.sync_engine, precisely
so tests never need to touch the app's real DB or reload db.py's
module-level engine).
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from migrations.m0001_multi_kb import (
    DEFAULT_KB_ID,
    backfill_null_kb_ids,
    run,
)

_OLD_SHAPE_TABLES = {
    "conversations": "CREATE TABLE conversations (id INTEGER PRIMARY KEY, user_id INTEGER, persona VARCHAR(16))",
    "projects": "CREATE TABLE projects (id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(200))",
    "messages": "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER, role VARCHAR(16), content TEXT)",
    "chat_events": "CREATE TABLE chat_events (id INTEGER PRIMARY KEY, rule_id VARCHAR(64), intent VARCHAR(32))",
    "feedback_events": "CREATE TABLE feedback_events (id INTEGER PRIMARY KEY, rating VARCHAR(8), rule_id VARCHAR(64))",
    "token_events": "CREATE TABLE token_events (id INTEGER PRIMARY KEY, total_tokens INTEGER)",
}


def _old_shape_engine(tmp_path: Path, seed_rows: bool = True):
    """A fresh sqlite engine with the pre-Phase-4 table shapes (no
    knowledge_base_id columns, no knowledge_bases table), optionally with one
    pre-existing row per table (to prove backfill leaves data intact)."""
    db_path = tmp_path / "old_shape.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as conn:
        for ddl in _OLD_SHAPE_TABLES.values():
            conn.execute(text(ddl))
        if seed_rows:
            conn.execute(text("INSERT INTO conversations (id, user_id, persona) VALUES (1, 1, 'analyst')"))
            conn.execute(text("INSERT INTO messages (id, conversation_id, role, content) VALUES (1, 1, 'user', 'hi')"))
            conn.execute(text("INSERT INTO chat_events (id, rule_id, intent) VALUES (1, 'RC1', NULL)"))
    return engine


# ── Fresh migration from the old shape ────────────────────────────────────────


def test_migration_adds_columns_and_table(tmp_path):
    engine = _old_shape_engine(tmp_path)

    summary = run(engine=engine)

    assert set(summary["columns_added"]) == set(_OLD_SHAPE_TABLES.keys())
    assert summary["kb_table_created"] is True
    assert summary["kb_seeded"] is True

    inspector = inspect(engine)
    assert "knowledge_bases" in inspector.get_table_names()
    for table in _OLD_SHAPE_TABLES:
        cols = {c["name"] for c in inspector.get_columns(table)}
        assert "knowledge_base_id" in cols, f"{table} missing knowledge_base_id"


def test_migration_seeds_customer_sap_row(tmp_path):
    engine = _old_shape_engine(tmp_path)
    run(engine=engine)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, name FROM knowledge_bases WHERE id = :id"),
            {"id": DEFAULT_KB_ID},
        ).first()
    assert row is not None
    assert row.id == "customer_sap"
    assert row.name


def test_migration_backfills_existing_rows_to_customer_sap(tmp_path):
    engine = _old_shape_engine(tmp_path)
    run(engine=engine)

    with engine.connect() as conn:
        conv = conn.execute(text("SELECT knowledge_base_id FROM conversations WHERE id = 1")).first()
        msg = conn.execute(text("SELECT knowledge_base_id FROM messages WHERE id = 1")).first()
        evt = conn.execute(text("SELECT knowledge_base_id FROM chat_events WHERE id = 1")).first()
    assert conv.knowledge_base_id == DEFAULT_KB_ID
    assert msg.knowledge_base_id == DEFAULT_KB_ID
    assert evt.knowledge_base_id == DEFAULT_KB_ID


def test_migration_is_idempotent_on_rerun(tmp_path):
    engine = _old_shape_engine(tmp_path)

    first = run(engine=engine)
    assert first["columns_added"]  # something happened the first time

    second = run(engine=engine)
    assert second["columns_added"] == []
    assert second["kb_table_created"] is False
    assert second["kb_seeded"] is False
    assert second["backfilled"] == {}


def test_migration_on_already_empty_fresh_db_is_a_noop_for_columns(tmp_path):
    """No conversations/etc. tables exist at all (a genuinely fresh DB that
    hasn't run db.init_db() yet) — add_kb_columns must skip them rather than
    error, while the knowledge_bases table/seed still get created."""
    db_path = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    summary = run(engine=engine)
    assert summary["columns_added"] == []
    assert summary["kb_table_created"] is True
    assert summary["kb_seeded"] is True
    assert summary["backfilled"] == {}


# ── backfill_null_kb_ids in isolation ─────────────────────────────────────────


def test_backfill_null_kb_ids_fixes_explicit_nulls(tmp_path):
    """Simulate a knowledge_base_id column that exists but was populated
    without a DEFAULT (e.g. rows inserted between ADD COLUMN and a server
    restart) — backfill must turn NULLs into 'customer_sap' without touching
    already-set values."""
    db_path = tmp_path / "partial.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE conversations (id INTEGER PRIMARY KEY, knowledge_base_id VARCHAR(64))"))
        conn.execute(text("INSERT INTO conversations (id, knowledge_base_id) VALUES (1, NULL)"))
        conn.execute(text("INSERT INTO conversations (id, knowledge_base_id) VALUES (2, 'other_kb')"))

    with engine.begin() as conn:
        backfilled = backfill_null_kb_ids(conn)

    assert backfilled == {"conversations": 1}
    with engine.connect() as conn:
        rows = {r.id: r.knowledge_base_id for r in conn.execute(text("SELECT id, knowledge_base_id FROM conversations"))}
    assert rows == {1: "customer_sap", 2: "other_kb"}
