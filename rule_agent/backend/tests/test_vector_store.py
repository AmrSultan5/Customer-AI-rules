"""
Tests for vector_store.py's NumpyVectorStore — brute-force cosine
similarity over hand-made vectors (no real embeddings involved). PgVectorStore
is not exercised here (no Postgres in this test environment); it is covered
by an import-safety check only.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import Base
from models import KbChunk, KbDocument
from vector_store import NumpyVectorStore, PgVectorStore, get_vector_store


@pytest.fixture
def store(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'vectors.db').as_posix()}")
    Base.metadata.create_all(engine, tables=[KbDocument.__table__, KbChunk.__table__])
    session_factory = sessionmaker(engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(KbDocument(kb_id="kb1", path="a.md", sha256="x"))
        session.commit()
    return NumpyVectorStore(session_factory=session_factory)


def test_query_empty_store_returns_empty_list(store):
    assert store.query("kb1", [1.0, 0.0, 0.0], k=5) == []


def test_count_starts_at_zero(store):
    assert store.count("kb1") == 0


def test_upsert_then_query_orders_by_cosine_similarity(store):
    n = store.upsert_chunks(
        "kb1",
        [
            {"document_id": 1, "chunk_index": 0, "text": "exact match", "source_ref": "a.md#0", "embedding": [1.0, 0.0, 0.0]},
            {"document_id": 1, "chunk_index": 1, "text": "orthogonal", "source_ref": "a.md#1", "embedding": [0.0, 1.0, 0.0]},
            {"document_id": 1, "chunk_index": 2, "text": "near match", "source_ref": "a.md#2", "embedding": [0.9, 0.1, 0.0]},
        ],
    )
    assert n == 3
    assert store.count("kb1") == 3

    results = store.query("kb1", [1.0, 0.0, 0.0], k=2)
    assert [c.text for c, _score in results] == ["exact match", "near match"]
    assert results[0][1] == pytest.approx(1.0)
    assert results[1][1] < results[0][1]
    assert 0.0 < results[1][1] < 1.0


def test_query_is_scoped_by_kb_id(store):
    store.upsert_chunks("kb1", [
        {"document_id": 1, "chunk_index": 0, "text": "kb1 chunk", "source_ref": None, "embedding": [1.0, 0.0]},
    ])
    store.upsert_chunks("kb2", [
        {"document_id": 1, "chunk_index": 0, "text": "kb2 chunk", "source_ref": None, "embedding": [1.0, 0.0]},
    ])
    assert store.count("kb1") == 1
    assert store.count("kb2") == 1
    results = store.query("kb1", [1.0, 0.0], k=10)
    assert [c.text for c, _ in results] == ["kb1 chunk"]


def test_delete_kb_removes_only_that_kbs_chunks(store):
    store.upsert_chunks("kb1", [
        {"document_id": 1, "chunk_index": 0, "text": "a", "source_ref": None, "embedding": [1.0, 0.0]},
        {"document_id": 1, "chunk_index": 1, "text": "b", "source_ref": None, "embedding": [0.0, 1.0]},
    ])
    store.upsert_chunks("kb2", [
        {"document_id": 1, "chunk_index": 0, "text": "c", "source_ref": None, "embedding": [1.0, 0.0]},
    ])

    deleted = store.delete_kb("kb1")
    assert deleted == 2
    assert store.count("kb1") == 0
    assert store.count("kb2") == 1


def test_query_skips_zero_vectors_and_mismatched_dims(store):
    store.upsert_chunks("kb1", [
        {"document_id": 1, "chunk_index": 0, "text": "zero", "source_ref": None, "embedding": [0.0, 0.0, 0.0]},
        {"document_id": 1, "chunk_index": 1, "text": "wrong dims", "source_ref": None, "embedding": [1.0, 0.0]},
        {"document_id": 1, "chunk_index": 2, "text": "valid", "source_ref": None, "embedding": [1.0, 0.0, 0.0]},
    ])
    results = store.query("kb1", [1.0, 0.0, 0.0], k=10)
    assert [c.text for c, _ in results] == ["valid"]


# ── Factory / import-safety ──────────────────────────────────────────────────


def test_get_vector_store_picks_numpy_for_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'factory.db').as_posix()}")
    assert isinstance(get_vector_store(engine=engine), NumpyVectorStore)


def test_pgvector_store_is_importable_without_pgvector_or_psycopg_installed():
    """PgVectorStore's constructor must not hard-require the `pgvector` or
    `psycopg` packages — this test's own environment has neither installed,
    which is exactly the dev/CI condition the class needs to tolerate."""
    store = PgVectorStore(session_factory=lambda: None)
    assert isinstance(store, PgVectorStore)
