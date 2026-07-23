"""
Tests for providers/rag.py — RagProvider.retrieve_context_for_query /
search / capabilities, against the real NumpyVectorStore with a mocked
embedder (embeddings._embed_batch_fn). No real OpenAI/network calls.
"""

import asyncio

import pytest

import db
import embeddings
from kb._schema import KBDescriptor
from models import KbDocument
from providers.rag import RagProvider
from vector_store import get_vector_store


def _descriptor(kb_id: str) -> KBDescriptor:
    return KBDescriptor(
        id=kb_id,
        name="Docs",
        description="A rag-only test KB.",
        adapter="rag",
        retrieval_mode="rag",
        source={"kind": "rag", "roots": []},
        id_pattern=r"\b([A-Z]{2,8}_\d+)\b",
        vocab={"entity_singular": "doc", "entity_plural": "docs"},
        prompts={"repository_label": "Docs"},
    )


@pytest.fixture(autouse=True)
def _mock_embedder(monkeypatch):
    # The query always embeds to [1, 0, 0]; chunk embeddings are supplied
    # directly when seeding the store below, so cosine ordering is explicit
    # and doesn't depend on the fake embedder's behavior for chunk text.
    monkeypatch.setattr(embeddings, "_embed_batch_fn", lambda texts: [[1.0, 0.0, 0.0] for _ in texts])


def _seed_chunks(kb_id: str, chunks: list[dict]) -> None:
    with db.SyncSessionLocal() as session:
        doc = KbDocument(kb_id=kb_id, path="a.md", sha256="x")
        session.add(doc)
        session.commit()
        doc_id = doc.id
    for c in chunks:
        c["document_id"] = doc_id
    get_vector_store().upsert_chunks(kb_id, chunks)


# ── Empty KB ─────────────────────────────────────────────────────────────────


def test_retrieve_context_for_query_empty_kb_returns_empty_string():
    provider = RagProvider(_descriptor("test_rag_empty"))
    assert asyncio.run(provider.retrieve_context_for_query("anything")) == ""


def test_search_empty_kb_returns_empty_list():
    provider = RagProvider(_descriptor("test_rag_empty_search"))
    assert provider.search("anything") == []


# ── Top-k context ────────────────────────────────────────────────────────────


def test_retrieve_context_for_query_returns_top_k_context():
    kb_id = "test_rag_topk"
    _seed_chunks(kb_id, [
        {"chunk_index": 0, "text": "Best match chunk.", "source_ref": "a.md#0", "embedding": [1.0, 0.0, 0.0]},
        {"chunk_index": 1, "text": "Worse match chunk.", "source_ref": "a.md#1", "embedding": [0.0, 1.0, 0.0]},
    ])

    provider = RagProvider(_descriptor(kb_id))
    ctx = asyncio.run(provider.retrieve_context_for_query("query", limit=1))

    assert "Best match chunk." in ctx
    assert "Worse match chunk." not in ctx
    assert "a.md#0" in ctx


def test_retrieve_context_for_query_formats_multiple_chunks_with_source_labels():
    kb_id = "test_rag_multi"
    _seed_chunks(kb_id, [
        {"chunk_index": 0, "text": "Chunk A.", "source_ref": "a.md#0", "embedding": [1.0, 0.0, 0.0]},
        {"chunk_index": 1, "text": "Chunk B.", "source_ref": "a.md#1", "embedding": [0.9, 0.1, 0.0]},
    ])

    provider = RagProvider(_descriptor(kb_id))
    ctx = asyncio.run(provider.retrieve_context_for_query("query", limit=5))

    assert "Source: a.md#0" in ctx
    assert "Source: a.md#1" in ctx
    assert "Chunk A." in ctx
    assert "Chunk B." in ctx


# ── search() ─────────────────────────────────────────────────────────────────


def test_search_returns_entities_from_chunks():
    kb_id = "test_rag_search"
    _seed_chunks(kb_id, [
        {"chunk_index": 0, "text": "Findable chunk.", "source_ref": "a.md#0", "embedding": [1.0, 0.0, 0.0]},
    ])
    provider = RagProvider(_descriptor(kb_id))
    results = provider.search("query")
    assert len(results) == 1
    assert results[0].source_ref == "a.md#0"
    assert results[0].raw["text"] == "Findable chunk."


# ── capabilities / inert entity methods ─────────────────────────────────────


def test_capabilities_and_inert_entity_methods():
    provider = RagProvider(_descriptor("test_rag_caps"))
    assert provider.capabilities() == {"search", "context", "rag"}
    assert provider.get_entity("anything") is None
    assert provider.extract_entity_id("some text mentioning RC1") is None
