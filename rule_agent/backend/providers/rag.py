"""
RagProvider — semantic search + context retrieval over a KB's ingested
chunks (Phase 8a).

Embeds the query via embeddings.embed_texts and does a top-k cosine search
against the configured VectorStore (vector_store.get_vector_store), scoped by
kb_id. Used standalone for rag-only KBs (registry.build_provider) and
composed inside HybridProvider (providers/hybrid.py) for hybrid ones.

Entities aren't addressable for a rag-only KB (a "chunk" isn't a stable id
the way a rule row is), so get_entity/extract_entity_id are deliberately
inert — that's what capabilities() = {"search", "context", "rag"} (no
"entity") signals to callers.
"""

from __future__ import annotations

import logging

from kb._schema import KBDescriptor
from providers.base import Entity, KnowledgeProvider, RetrievalChunk

log = logging.getLogger(__name__)

_DEFAULT_LIMIT = 8


class RagProvider(KnowledgeProvider):
    def __init__(self, descriptor: KBDescriptor):
        self.kb = descriptor

    # ---- entity lookup (not addressable for RAG chunks) ------------------------

    def get_entity(self, entity_id: str) -> Entity | None:
        return None

    def extract_entity_id(self, text: str) -> str | None:
        return None

    # ---- search -------------------------------------------------------------------

    def search(self, query: str, *, limit: int = 20, category: str | None = None) -> list[Entity]:
        chunks = self._search_chunks(query, limit=limit)
        return [
            Entity(
                id=c.source_ref or f"chunk:{i}",
                title=(c.text[:80] + "…") if len(c.text) > 80 else c.text,
                source_ref=c.source_ref,
                raw={"text": c.text, "score": c.score},
            )
            for i, c in enumerate(chunks)
        ]

    # ---- context ------------------------------------------------------------------

    async def retrieve_context_for_query(
        self, query: str, *, entity_id: str | None = None, limit: int = 8
    ) -> str:
        """Top-k semantic chunks for `query`, formatted as a context block.
        Returns "" if the KB has no ingested chunks (or the query embed
        fails) — never raises, so callers can always append this safely."""
        chunks = self._search_chunks(query, limit=limit)
        if not chunks:
            return ""
        blocks = [
            f"Source: {c.source_ref or '(unknown)'}\n{c.text}" for c in chunks
        ]
        return "\n\n---\n\n".join(blocks)

    def _search_chunks(self, query: str, *, limit: int) -> list[RetrievalChunk]:
        from vector_store import get_vector_store

        store = get_vector_store()
        if store.count(self.kb.id) == 0:
            return []  # nothing ingested yet — skip the embedding call entirely

        try:
            import embeddings

            [query_embedding] = embeddings.embed_texts([query])
        except Exception as exc:
            log.warning("[rag] embedding query failed for kb=%s: %s", self.kb.id, type(exc).__name__)
            return []

        results = store.query(self.kb.id, query_embedding, k=limit)
        return [
            RetrievalChunk(text=chunk.text, source_ref=chunk.source_ref, score=score)
            for chunk, score in results
        ]

    # ---- lifecycle -------------------------------------------------------------------

    def reload(self) -> dict:
        from ingestion import ingest_kb

        return ingest_kb(self.kb)

    def capabilities(self) -> set[str]:
        return {"search", "context", "rag"}
