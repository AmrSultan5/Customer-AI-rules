"""
Knowledge-base registry — Phase 2.

Loads and exposes KB descriptors, and builds + caches one KnowledgeProvider
per descriptor (build_provider / KnowledgeBaseRegistry.get_provider).
"""

from pathlib import Path

from config import settings
from kb._schema import KBDescriptor, load_all_descriptors
from providers.base import KnowledgeProvider


def build_provider(descriptor: KBDescriptor) -> KnowledgeProvider:
    """Construct the KnowledgeProvider for one descriptor.

    structured/hybrid KBs are served by StructuredTabularProvider (the
    deterministic lookup wrapping the existing data_loader). rag-only KBs
    have no provider yet — RagProvider/HybridProvider land in Phase 8.
    """
    if descriptor.adapter in ("structured", "hybrid"):
        from providers.structured import StructuredTabularProvider

        return StructuredTabularProvider(descriptor)
    raise NotImplementedError(
        f"KBDescriptor {descriptor.id!r}: adapter={descriptor.adapter!r} has no "
        "provider yet — RAG-only KBs are implemented in Phase 8."
    )


class KnowledgeBaseRegistry:
    def __init__(
        self,
        kb_dir: str | Path | None = None,
        active_kb: str | None = None,
    ):
        self._descriptors: dict[str, KBDescriptor] = load_all_descriptors(
            kb_dir if kb_dir is not None else settings.kb_dir
        )
        requested = active_kb if active_kb is not None else settings.active_kb
        if requested in self._descriptors:
            self._default_kb_id = requested
        elif len(self._descriptors) == 1:
            self._default_kb_id = next(iter(self._descriptors))
        else:
            # Unresolved default — later phases 404 on this.
            self._default_kb_id = requested
        self._providers: dict[str, KnowledgeProvider] = {}

    def list_descriptors(self) -> list[KBDescriptor]:
        return list(self._descriptors.values())

    def get_descriptor(self, kb_id: str) -> KBDescriptor | None:
        return self._descriptors.get(kb_id)

    def get_provider(self, kb_id: str) -> KnowledgeProvider | None:
        """Return the (cached) provider for kb_id, building it on first use."""
        if kb_id in self._providers:
            return self._providers[kb_id]
        descriptor = self._descriptors.get(kb_id)
        if descriptor is None:
            return None
        provider = build_provider(descriptor)
        self._providers[kb_id] = provider
        return provider

    @property
    def default_kb_id(self) -> str:
        return self._default_kb_id
