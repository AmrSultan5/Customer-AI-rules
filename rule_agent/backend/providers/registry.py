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

    structured -> StructuredTabularProvider (deterministic lookup wrapping
    the existing data_loader). hybrid -> HybridProvider (composes structured
    + an optional RagProvider, per the descriptor's source.rag — see
    providers/hybrid.py). rag -> RagProvider (Phase 8a).
    """
    if descriptor.adapter == "structured":
        from providers.structured import StructuredTabularProvider

        return StructuredTabularProvider(descriptor)
    if descriptor.adapter == "hybrid":
        from providers.hybrid import HybridProvider

        return HybridProvider(descriptor)
    if descriptor.adapter == "rag":
        from providers.rag import RagProvider

        return RagProvider(descriptor)
    raise NotImplementedError(
        f"KBDescriptor {descriptor.id!r}: adapter={descriptor.adapter!r} has no provider implementation."
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
