"""
Provider seam — base types and the KnowledgeProvider contract (Phase 2).

This is the thin seam between the analyst/chat layer (chat_agent.py, kept)
and the underlying data. Every concrete adapter implements KnowledgeProvider;
StructuredTabularProvider (providers/structured.py) is the first one, wrapping
the existing data_loader.py retrieval so analyst behavior does not change.

Deliberately slim: no impact/graph/tree/related surface — those views were
removed in Phase 1 along with the engineer/PM personas.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from kb._schema import KBDescriptor


class Entity(BaseModel):
    """A single addressable knowledge-base record (e.g. one rule)."""

    id: str
    title: str | None = None
    domain: str | None = None
    category: str | None = None
    logic: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    source_ref: str | None = None


class RetrievalChunk(BaseModel):
    """One retrieved unit of grounding context, deterministic or RAG-sourced."""

    text: str
    source_ref: str | None = None
    score: float = 1.0
    entity_id: str | None = None


class KnowledgeProvider(ABC):
    """Slim analyst-chat contract every KB adapter implements.

    `kb` is the KBDescriptor the provider was built from (see
    providers/registry.py:build_provider).
    """

    kb: KBDescriptor

    @abstractmethod
    def get_entity(self, entity_id: str) -> Entity | None:
        """Look up a single entity by id. Returns None if not found."""

    @abstractmethod
    def search(
        self, query: str, *, limit: int = 20, category: str | None = None
    ) -> list[Entity]:
        """Keyword/category search over the KB's entities."""

    @abstractmethod
    def extract_entity_id(self, text: str) -> str | None:
        """Extract an entity id embedded in free text (e.g. a chat message)."""

    @abstractmethod
    async def retrieve_context_for_query(
        self, query: str, *, entity_id: str | None = None, limit: int = 8
    ) -> str:
        """Return the deterministic context block used to ground the analyst
        answer for `query` (optionally scoped to a known `entity_id`)."""

    @abstractmethod
    def reload(self) -> dict:
        """Reload the provider's underlying data from disk. Returns counts."""

    @abstractmethod
    def capabilities(self) -> set[str]:
        """Set of feature tags this provider supports, e.g. {'entity','search','context'}."""
