"""
One-off migration: copy historical analytics from the legacy SQLite file
(data/analytics.db) into the configured SQLAlchemy database (Postgres in prod).

Usage:
    python migrate_analytics_to_pg.py            # skips tables that already have rows
    python migrate_analytics_to_pg.py --force    # insert regardless of existing rows

Run with the target DATABASE_URL set in the environment (or .env). Safe to run
once; by default it refuses to duplicate data into a non-empty target table.
"""

import argparse
import asyncio
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select

import db
from models import ChatEvent, FeedbackEvent, TokenEvent

LEGACY_DB = Path(__file__).parent / "data" / "analytics.db"


def _parse_ts(raw) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _read_legacy(table: str) -> list[dict]:
    with sqlite3.connect(LEGACY_DB) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(r) for r in rows]


async def _count(session, model) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def migrate(force: bool) -> None:
    if not LEGACY_DB.exists():
        print(f"No legacy analytics DB at {LEGACY_DB} — nothing to migrate.")
        return

    await db.init_db()

    # rule_views is intentionally omitted — RuleView (and rule-view tracking)
    # was removed in Phase 4; the legacy rule_views table in analytics.db, if
    # any, is no longer migrated.
    plan = [
        ("chat_events", ChatEvent, lambda r: ChatEvent(rule_id=r.get("rule_id"), intent=r.get("intent"), occurred_at=_parse_ts(r["occurred_at"]))),
        ("feedback_events", FeedbackEvent, lambda r: FeedbackEvent(rating=r["rating"], mode=r.get("mode"), rule_id=r.get("rule_id"), occurred_at=_parse_ts(r["occurred_at"]))),
        ("token_events", TokenEvent, lambda r: TokenEvent(
            prompt_tokens=r.get("prompt_tokens", 0) or 0,
            completion_tokens=r.get("completion_tokens", 0) or 0,
            total_tokens=r.get("total_tokens", 0) or 0,
            model=r.get("model"), call_type=r.get("call_type"),
            occurred_at=_parse_ts(r["occurred_at"]),
        )),
    ]

    async with db.AsyncSessionLocal() as session:
        for table, model, build in plan:
            existing = await _count(session, model)
            if existing and not force:
                print(f"[skip] {table}: target already has {existing} rows (use --force to insert anyway)")
                continue
            legacy_rows = _read_legacy(table)
            if not legacy_rows:
                print(f"[----] {table}: no legacy rows")
                continue
            session.add_all([build(r) for r in legacy_rows])
            await session.commit()
            print(f"[ok  ] {table}: migrated {len(legacy_rows)} rows")

    print("Migration complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="insert even if target tables are non-empty")
    args = parser.parse_args()
    asyncio.run(migrate(args.force))
    sys.exit(0)
