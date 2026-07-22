"""
Pydantic schema + loader for per-KB descriptors (backend/kb/*.yaml).

A KBDescriptor is the single source of truth for everything that used to be
hardcoded per-dataset: file paths, column names, the entity-id regex, and
chat/prompt vocabulary. This module only defines the schema and a loader —
nothing in the running app consumes it yet (Phase 2+).
"""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class ColumnMap(BaseModel):
    """Logical→physical column mapping for one field, with fuzzy fallbacks."""

    physical: str
    aliases: list[str] = Field(default_factory=list)


class FieldMap(BaseModel):
    """Per-table logical→physical column maps."""

    rules: dict[str, ColumnMap] = Field(default_factory=dict)
    sap: dict[str, ColumnMap] = Field(default_factory=dict)
    # Logical keys (subset of `rules` / `sap` above) that schema_validator
    # treats as required. Empty means "caller falls back to its own legacy
    # defaults" — see schema_validator.validate_against_descriptor.
    required_rules: list[str] = Field(default_factory=list)
    required_sap: list[str] = Field(default_factory=list)


class StructuredSource(BaseModel):
    kind: Literal["structured"] = "structured"
    # logical name -> path, relative to backend/
    files: dict[str, str] = Field(default_factory=dict)
    # logical name -> dir path, relative to backend/
    dirs: dict[str, str] = Field(default_factory=dict)


class RagSource(BaseModel):
    kind: Literal["rag"] = "rag"
    roots: list[str] = Field(default_factory=list)
    include_globs: list[str] = Field(default_factory=lambda: ["**/*"])
    exclude_globs: list[str] = Field(default_factory=list)
    git_url: str | None = None          # Azure DevOps Repos URL
    git_ref: str | None = None          # branch / tag / sha
    # name of the env var holding the PAT (never the token itself)
    auth_token_env: str | None = None


class HybridSource(BaseModel):
    kind: Literal["hybrid"] = "hybrid"
    structured: StructuredSource
    rag: RagSource | None = None


Source = Annotated[
    StructuredSource | RagSource | HybridSource,
    Field(discriminator="kind"),
]


class Vocab(BaseModel):
    entity_singular: str
    entity_plural: str
    domain_noun: str = ""
    categories: list[str] = Field(default_factory=list)
    severity_map: dict[str, str] = Field(default_factory=dict)
    business_names: dict[str, str] = Field(default_factory=dict)
    platform_terms: list[str] = Field(default_factory=list)


class Prompts(BaseModel):
    analyst_system: str | None = None   # None => inherit kb/_defaults.yaml
    repository_label: str


class KBDescriptor(BaseModel):
    id: str
    name: str
    description: str
    adapter: Literal["structured", "rag", "hybrid"]
    retrieval_mode: Literal["structured", "rag", "hybrid"]
    source: Source
    field_map: FieldMap = Field(default_factory=FieldMap)
    id_pattern: str
    vocab: Vocab
    prompts: Prompts

    @model_validator(mode="after")
    def _adapter_matches_source(self) -> "KBDescriptor":
        if self.adapter != self.source.kind:
            raise ValueError(
                f"KBDescriptor {self.id!r}: adapter={self.adapter!r} but "
                f"source.kind={self.source.kind!r}"
            )
        return self


_KB_DIR = Path(__file__).resolve().parent


def _load_defaults() -> dict:
    defaults_path = _KB_DIR / "_defaults.yaml"
    if not defaults_path.exists():
        return {}
    return yaml.safe_load(defaults_path.read_text(encoding="utf-8")) or {}


def load_descriptor(path: str | Path) -> KBDescriptor:
    """Load and validate a single KB descriptor YAML file.

    If the descriptor omits prompts.analyst_system, it inherits the shared
    default template from kb/_defaults.yaml.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    prompts = raw.get("prompts") or {}
    if not prompts.get("analyst_system"):
        defaults = _load_defaults()
        if defaults.get("analyst_system"):
            prompts["analyst_system"] = defaults["analyst_system"]
        raw["prompts"] = prompts

    return KBDescriptor(**raw)


def load_all_descriptors(kb_dir: str | Path) -> dict[str, KBDescriptor]:
    """Load every *.yaml in kb_dir except files starting with '_'.

    Returns a dict keyed by KBDescriptor.id (not filename).
    """
    kb_dir = Path(kb_dir)
    result: dict[str, KBDescriptor] = {}
    for yaml_path in sorted(kb_dir.glob("*.yaml")):
        if yaml_path.name.startswith("_"):
            continue
        descriptor = load_descriptor(yaml_path)
        result[descriptor.id] = descriptor
    return result
