"""
Migration 0002 — RAG storage tables (Phase 8a).

Additive and idempotent, in the style of ./m0001_multi_kb.py, safe on both
SQLite (dev/CI) and Postgres (prod):

  1. CREATE TABLE IF NOT EXISTS kb_documents / kb_chunks — created straight
     from the ORM table definitions in models.py (SQLAlchemy's
     Table.create(checkfirst=True) generates correct, dialect-appropriate DDL
     for both engines, including the autoincrement primary key, so there is
     no hand-written SQL to keep in sync with models.py).
  2. On Postgres only, best-effort: `CREATE EXTENSION IF NOT EXISTS vector`,
     then add a native `embedding_vector vector(<dim>)` column to kb_chunks
     (parallel to the portable `embedding_json` column already on the ORM
     model) and an ivfflat cosine index. Every step here is wrapped in its
     own try/except — a database without CREATE EXTENSION privileges (a
     common restriction on managed Postgres) degrades gracefully to
     NumpyVectorStore-only behavior rather than failing the whole migration.
     No-op (skipped entirely) on SQLite.

Every step is guarded by an existence check (or a try/except for the
best-effort Postgres block), so re-running is a no-op.

Usage (from backend/, with the target DATABASE_URL / DATABASE_URL_SYNC set in
the environment or .env):

    python -m migrations.m0002_rag
    python migrations/m0002_rag.py

Programmatic use (e.g. tests) can pass an explicit engine to `run()` instead
of relying on the module-level `db.sync_engine`:

    from migrations.m0002_rag import run
    run(engine=my_test_engine)
"""

import logging
import sys
from pathlib import Path

# Support `python migrations/m0002_rag.py` (run outside `-m`, where
# sys.path[0] is the migrations/ dir, not backend/) as well as `-m`.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

import db

log = logging.getLogger(__name__)

# text-embedding-3-small (config.settings.embeddings_model default) — the
# native pgvector column is sized to match. If a deployment switches
# embeddings models to a different dimensionality, this constant (and the
# already-created column) needs a follow-up migration; embedding_json has no
# such constraint and always works regardless of dimension.
_EMBEDDING_DIM = 1536


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def create_rag_tables(conn) -> dict[str, bool]:
    """CREATE TABLE IF NOT EXISTS kb_documents / kb_chunks from the ORM
    definitions in models.py. Returns {"kb_documents": created?, "kb_chunks":
    created?}."""
    import models  # noqa: F401 — registers KbDocument/KbChunk on Base.metadata

    inspector = inspect(conn)
    created = {
        "kb_documents": not _has_table(inspector, "kb_documents"),
        "kb_chunks": not _has_table(inspector, "kb_chunks"),
    }
    # kb_documents first — kb_chunks.document_id has an FK to it.
    models.KbDocument.__table__.create(bind=conn, checkfirst=True)
    models.KbChunk.__table__.create(bind=conn, checkfirst=True)
    return created


def enable_pgvector_and_column(conn) -> dict:
    """Best-effort Postgres-only: CREATE EXTENSION vector, add the native
    embedding_vector column, and its ivfflat cosine index. No-op on SQLite.
    Every sub-step is independently guarded — a partial failure (e.g. no
    CREATE EXTENSION privilege) leaves whatever succeeded in place and does
    not raise, so the rest of the migration (and the app, which can still run
    on NumpyVectorStore) is unaffected.
    """
    result = {"extension_created": False, "column_added": False, "index_created": False}
    if conn.dialect.name != "postgresql":
        return result

    try:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        result["extension_created"] = True
    except Exception as exc:
        log.warning("[migration 0002] CREATE EXTENSION vector failed (continuing without it): %s", exc)
        return result

    try:
        inspector = inspect(conn)
        if not _has_column(inspector, "kb_chunks", "embedding_vector"):
            conn.execute(text(f"ALTER TABLE kb_chunks ADD COLUMN embedding_vector vector({_EMBEDDING_DIM})"))
        result["column_added"] = True
    except Exception as exc:
        log.warning("[migration 0002] adding embedding_vector column failed: %s", exc)
        return result

    try:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS kb_chunks_embedding_vector_idx ON kb_chunks "
                "USING ivfflat (embedding_vector vector_cosine_ops) WITH (lists = 100)"
            )
        )
        result["index_created"] = True
    except Exception as exc:
        log.warning("[migration 0002] creating ivfflat index failed: %s", exc)

    return result


def run(engine: Engine | None = None) -> dict:
    """Run the full migration in one transaction. Returns a summary dict.

    `engine` defaults to db.sync_engine (bound to the configured
    DATABASE_URL/DATABASE_URL_SYNC) — pass an explicit engine (e.g. a
    throwaway SQLite file) for testing without touching the app's DB.
    """
    engine = engine or db.sync_engine
    summary = {
        "kb_documents_created": False,
        "kb_chunks_created": False,
        "pgvector": {"extension_created": False, "column_added": False, "index_created": False},
    }
    with engine.begin() as conn:
        created = create_rag_tables(conn)
        summary["kb_documents_created"] = created["kb_documents"]
        summary["kb_chunks_created"] = created["kb_chunks"]
        summary["pgvector"] = enable_pgvector_and_column(conn)
    return summary


def main() -> None:
    summary = run()
    print(f"[migration 0002] kb_documents table created: {summary['kb_documents_created']}")
    print(f"[migration 0002] kb_chunks table created: {summary['kb_chunks_created']}")
    print(f"[migration 0002] pgvector: {summary['pgvector']}")
    print("[migration 0002] done - safe to re-run (no-op on an already-migrated DB).")


if __name__ == "__main__":
    main()
