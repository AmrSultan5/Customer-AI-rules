"""
Knowledge-base registry — Phase 0 skeleton.

Loads and exposes KB descriptors only. Building actual KnowledgeProvider
instances per descriptor is Phase 2; this module intentionally stops at
"descriptors are discoverable and one is the default."
"""

from pathlib import Path

from config import settings
from kb._schema import KBDescriptor, load_all_descriptors


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

    def list_descriptors(self) -> list[KBDescriptor]:
        return list(self._descriptors.values())

    def get_descriptor(self, kb_id: str) -> KBDescriptor | None:
        return self._descriptors.get(kb_id)

    @property
    def default_kb_id(self) -> str:
        return self._default_kb_id
