"""
VectorStore — storage/search abstraction over kb_chunks embeddings (Phase 8a).

Two implementations, selected by DB dialect via get_vector_store() so the
provider layer (providers/rag.py) never knows which backend is active:

  - NumpyVectorStore — reads kb_chunks.embedding_json (a JSON list of floats)
    for a KB, does brute-force cosine similarity in numpy. Used for
    dev/CI/SQLite. Fully working and what every test in this repo exercises.
  - PgVectorStore — talks to a pgvector `vector` column (embedding_vector,
    added by migrations/m0002_rag.py) via `<=>` cosine-distance queries plus
    an ivfflat/hnsw index. Used in production on Postgres/Neon. Its
    constructor never imports `pgvector`/`psycopg` at module import time (a
    best-effort adapter registration is wrapped in try/except) so this module
    stays importable in environments — like local dev/CI — where those
    packages aren't installed; the class is not exercised by the test suite,
    which never runs against a real Postgres instance.

Both stores operate on the same `kb_chunks`/`kb_documents` tables (models.py)
and are scoped by `kb_id` so one store instance serves every registered KB.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class StoredChunk:
    """A row from kb_chunks, detached from its ORM session (safe to use after
    the session that loaded it has closed)."""

    id: int
    kb_id: str
    document_id: int
    chunk_index: int
    text: str
    source_ref: str | None


class VectorStore(ABC):
    """Storage/search contract for one KB's embedded chunks."""

    @abstractmethod
    def upsert_chunks(self, kb_id: str, chunks: list[dict]) -> int:
        """Insert chunk rows for `kb_id`.

        Each dict in `chunks` has keys: document_id, chunk_index, text,
        source_ref (optional), embedding (list[float]). Returns the number of
        rows written. Callers (ingestion.py) are responsible for deleting any
        stale chunks of a changed document before calling this — this method
        only inserts.
        """

    @abstractmethod
    def query(self, kb_id: str, embedding: list[float], k: int = 8) -> list[tuple[StoredChunk, float]]:
        """Top-k (chunk, cosine_similarity) for `kb_id`, ordered by
        descending similarity. Returns [] if the KB has no chunks."""

    @abstractmethod
    def delete_kb(self, kb_id: str) -> int:
        """Delete every chunk (and document) row for `kb_id`. Returns the
        number of chunk rows deleted."""

    @abstractmethod
    def count(self, kb_id: str) -> int:
        """Number of chunk rows stored for `kb_id`."""


class NumpyVectorStore(VectorStore):
    """Brute-force cosine similarity over kb_chunks.embedding_json, loaded
    into memory per query. O(n) per query — fine at dev/CI/SQLite scale;
    PgVectorStore is what production Postgres deployments use instead."""

    def __init__(self, engine=None, session_factory=None):
        if session_factory is not None:
            self._session_factory = session_factory
        elif engine is not None:
            from sqlalchemy.orm import sessionmaker

            self._session_factory = sessionmaker(engine, expire_on_commit=False)
        else:
            import db

            self._session_factory = db.SyncSessionLocal

    def upsert_chunks(self, kb_id: str, chunks: list[dict]) -> int:
        from models import KbChunk

        count = 0
        with self._session_factory() as session:
            for c in chunks:
                session.add(
                    KbChunk(
                        kb_id=kb_id,
                        document_id=c["document_id"],
                        chunk_index=c.get("chunk_index", 0),
                        text=c["text"],
                        source_ref=c.get("source_ref"),
                        embedding_json=json.dumps(c["embedding"]),
                    )
                )
                count += 1
            session.commit()
        return count

    def query(self, kb_id: str, embedding: list[float], k: int = 8) -> list[tuple[StoredChunk, float]]:
        import numpy as np
        from sqlalchemy import select

        from models import KbChunk

        with self._session_factory() as session:
            rows = session.execute(select(KbChunk).where(KbChunk.kb_id == kb_id)).scalars().all()
            # Materialize plain values while the session is open — StoredChunk
            # instances must outlive this `with` block.
            data = [
                (r.id, r.kb_id, r.document_id, r.chunk_index, r.text, r.source_ref, r.embedding_json)
                for r in rows
            ]

        if not data:
            return []

        q = np.asarray(embedding, dtype=float)
        qn = float(np.linalg.norm(q))
        if qn == 0:
            return []

        scored: list[tuple[float, StoredChunk]] = []
        for (cid, ckb, doc_id, idx, text, source_ref, emb_json) in data:
            if not emb_json:
                continue
            vec = np.asarray(json.loads(emb_json), dtype=float)
            if vec.shape != q.shape:
                continue
            vn = float(np.linalg.norm(vec))
            if vn == 0:
                continue
            sim = float(np.dot(q, vec) / (qn * vn))
            scored.append(
                (sim, StoredChunk(id=cid, kb_id=ckb, document_id=doc_id, chunk_index=idx, text=text, source_ref=source_ref))
            )

        scored.sort(key=lambda t: t[0], reverse=True)
        return [(chunk, sim) for sim, chunk in scored[:k]]

    def delete_kb(self, kb_id: str) -> int:
        from models import KbChunk, KbDocument

        with self._session_factory() as session:
            n = session.query(KbChunk).filter(KbChunk.kb_id == kb_id).delete()
            session.query(KbDocument).filter(KbDocument.kb_id == kb_id).delete()
            session.commit()
        return n

    def count(self, kb_id: str) -> int:
        from sqlalchemy import func, select

        from models import KbChunk

        with self._session_factory() as session:
            val = session.execute(
                select(func.count()).select_from(KbChunk).where(KbChunk.kb_id == kb_id)
            ).scalar()
        return int(val or 0)


class PgVectorStore(VectorStore):
    """pgvector-backed store: kb_chunks.embedding_vector (vector(N)) queried
    via the `<=>` cosine-distance operator, with an ivfflat/hnsw index
    (created best-effort by migrations/m0002_rag.py). Talks to Postgres
    through a plain SQLAlchemy engine/session using raw SQL + vector string
    literals ("[0.1,0.2,...]") — this deliberately avoids a hard dependency
    on the `pgvector` Python package for correctness; that package (if
    installed) only gets a best-effort adapter-registration attempt, wrapped
    in try/except, purely as a future optimization hook.

    Not exercised by the test suite (no Postgres available locally/in CI);
    reviewers should sanity-check this path against a real pgvector-enabled
    Postgres/Neon database before relying on it in production.
    """

    def __init__(self, engine=None, session_factory=None):
        if session_factory is not None:
            self._session_factory = session_factory
        elif engine is not None:
            from sqlalchemy.orm import sessionmaker

            self._session_factory = sessionmaker(engine, expire_on_commit=False)
        else:
            import db

            self._session_factory = db.SyncSessionLocal
        self._try_register_pgvector_adapter()

    @staticmethod
    def _try_register_pgvector_adapter() -> None:
        try:
            import pgvector.psycopg  # noqa: F401 — presence check only.
        except ImportError:
            log.debug("[vector_store] pgvector package not installed — using raw SQL vector literals only")

    @staticmethod
    def _to_vector_literal(embedding: list[float]) -> str:
        return "[" + ",".join(repr(float(x)) for x in embedding) + "]"

    def upsert_chunks(self, kb_id: str, chunks: list[dict]) -> int:
        from sqlalchemy import text

        count = 0
        with self._session_factory() as session:
            for c in chunks:
                session.execute(
                    text(
                        "INSERT INTO kb_chunks "
                        "(kb_id, document_id, chunk_index, text, source_ref, embedding_json, embedding_vector) "
                        "VALUES (:kb_id, :document_id, :chunk_index, :text, :source_ref, "
                        ":embedding_json, CAST(:embedding_vector AS vector))"
                    ),
                    {
                        "kb_id": kb_id,
                        "document_id": c["document_id"],
                        "chunk_index": c.get("chunk_index", 0),
                        "text": c["text"],
                        "source_ref": c.get("source_ref"),
                        "embedding_json": json.dumps(c["embedding"]),
                        "embedding_vector": self._to_vector_literal(c["embedding"]),
                    },
                )
                count += 1
            session.commit()
        return count

    def query(self, kb_id: str, embedding: list[float], k: int = 8) -> list[tuple[StoredChunk, float]]:
        from sqlalchemy import text

        vec_literal = self._to_vector_literal(embedding)
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT id, kb_id, document_id, chunk_index, text, source_ref, "
                    "1 - (embedding_vector <=> CAST(:embedding AS vector)) AS score "
                    "FROM kb_chunks WHERE kb_id = :kb_id AND embedding_vector IS NOT NULL "
                    "ORDER BY embedding_vector <=> CAST(:embedding AS vector) "
                    "LIMIT :k"
                ),
                {"embedding": vec_literal, "kb_id": kb_id, "k": k},
            ).all()
        return [
            (
                StoredChunk(
                    id=r.id, kb_id=r.kb_id, document_id=r.document_id,
                    chunk_index=r.chunk_index, text=r.text, source_ref=r.source_ref,
                ),
                float(r.score),
            )
            for r in rows
        ]

    def delete_kb(self, kb_id: str) -> int:
        from sqlalchemy import text

        with self._session_factory() as session:
            result = session.execute(text("DELETE FROM kb_chunks WHERE kb_id = :kb_id"), {"kb_id": kb_id})
            session.execute(text("DELETE FROM kb_documents WHERE kb_id = :kb_id"), {"kb_id": kb_id})
            session.commit()
        return result.rowcount or 0

    def count(self, kb_id: str) -> int:
        from sqlalchemy import text

        with self._session_factory() as session:
            val = session.execute(
                text("SELECT COUNT(*) FROM kb_chunks WHERE kb_id = :kb_id"), {"kb_id": kb_id}
            ).scalar()
        return int(val or 0)


def get_vector_store(engine=None) -> VectorStore:
    """Factory: pick NumpyVectorStore or PgVectorStore by DB dialect.

    `engine` defaults to db.sync_engine (the app's configured DATABASE_URL) —
    SQLite/dev/CI gets NumpyVectorStore, Postgres gets PgVectorStore. Pass an
    explicit engine (e.g. a throwaway SQLite file) in tests to avoid touching
    the app's real DB.
    """
    if engine is None:
        import db

        engine = db.sync_engine
    if engine.dialect.name == "postgresql":
        return PgVectorStore(engine=engine)
    return NumpyVectorStore(engine=engine)
