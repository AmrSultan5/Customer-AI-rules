"""
HybridProvider — composes a StructuredTabularProvider with an optional
RagProvider (Phase 8a).

customer_sap is registered as `adapter: hybrid` but its `source.rag` is
`null` in this phase (no repo has been ingested yet), so `self.rag` is None
and every method here is a pure pass-through to `self.structured` — byte-
identical behavior/capabilities to the plain StructuredTabularProvider that
served it before this phase. This is deliberate, not incidental: RAG is
opt-in per KB via the descriptor's `source.rag`, and chat_agent.py is not
wired to call `retrieve_context_for_query` in this phase at all (it calls
`build_context` directly, delegated below) — 8b is what changes chat
behavior.

`extract_entity_id`, `get_entity`, and `build_context` are delegated
unconditionally because chat_agent.py's analyst flow calls them today via
`_get_provider()` — see chat_agent.py:762 (`_build_rule_context` shim) and
its `_RULE_ID_RE`/entity-lookup call sites. Once a KB's `source.rag` *is*
configured, `retrieve_context_for_query` merges structured context with the
RAG chunks (structured first, RAG appended as a labeled section) and
`capabilities()`/`reload()` become the union of both providers'.
"""

from __future__ import annotations

from typing import Any

from kb._schema import KBDescriptor
from providers.base import Entity, KnowledgeProvider
from providers.structured import StructuredTabularProvider


class HybridProvider(KnowledgeProvider):
    def __init__(self, descriptor: KBDescriptor):
        self.kb = descriptor
        self.structured = StructuredTabularProvider(descriptor)
        self.rag = None
        rag_source = getattr(descriptor.source, "rag", None)
        if rag_source is not None:
            from providers.rag import RagProvider

            self.rag = RagProvider(descriptor)

    # ---- delegate to structured (chat_agent's call sites today) ------------------

    def get_entity(self, entity_id: str) -> Entity | None:
        return self.structured.get_entity(entity_id)

    def search(self, query: str, *, limit: int = 20, category: str | None = None) -> list[Entity]:
        return self.structured.search(query, limit=limit, category=category)

    def extract_entity_id(self, text: str) -> str | None:
        return self.structured.extract_entity_id(text)

    def build_context(self, rule_id: str, row: Any, logic: str, rules: Any):
        """Same (ctx, ref_rules, yaml_match) tuple as
        StructuredTabularProvider.build_context — chat_agent's
        `_build_rule_context` shim delegates straight through to this."""
        return self.structured.build_context(rule_id, row, logic, rules)

    # ---- merged retrieval ----------------------------------------------------------

    async def retrieve_context_for_query(
        self, query: str, *, entity_id: str | None = None, limit: int = 8
    ) -> str:
        """Structured deterministic context, with RAG chunks appended when
        this KB has a configured rag source. With no rag source (or an empty
        vector store) this returns exactly `self.structured`'s output —
        customer_sap today has neither, so this is a no-op passthrough."""
        structured_ctx = await self.structured.retrieve_context_for_query(
            query, entity_id=entity_id, limit=limit
        )
        if self.rag is None:
            return structured_ctx

        rag_ctx = await self.rag.retrieve_context_for_query(query, entity_id=entity_id, limit=limit)
        if not rag_ctx:
            return structured_ctx
        if not structured_ctx:
            return rag_ctx
        return structured_ctx + "\n\n## Related context (semantic search)\n\n" + rag_ctx

    # ---- lifecycle -------------------------------------------------------------------

    def reload(self) -> dict:
        result = self.structured.reload()
        if self.rag is not None:
            result = {**result, "rag": self.rag.reload()}
        return result

    def capabilities(self) -> set[str]:
        caps = self.structured.capabilities()
        if self.rag is not None:
            caps = caps | self.rag.capabilities()
        return caps
