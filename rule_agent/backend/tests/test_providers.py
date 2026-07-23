"""
Tests for the Phase 2 provider seam: providers/base.py, providers/structured.py,
and providers/registry.py's build_provider/get_provider.

conftest.py stubs sys.modules["data_loader"] (and chat_agent/explanation_engine/
schema_validator) with a MagicMock backed by a 2-row MOCK_RULES DataFrame
before any test module is collected. providers/structured.py resolves
`import data_loader` lazily inside each method via the shared sys.modules
cache, so normal imports of it here see that same stub — no extra patching
needed, matching how tests/test_chat_routing.py and
tests/test_business_friendly.py already exercise the real chat_agent.py
against the same stub.

The real chat_agent.py is loaded directly from disk (same importlib pattern
as test_kb_descriptor.py) to get its `_RULE_ID_RE` constant and its
`_build_rule_context` back-compat shim — the shim now delegates to a
provider itself (see chat_agent._get_provider), so comparing against it is a
true end-to-end check that chat_agent's call sites get identical output via
the provider seam.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from kb._schema import KBDescriptor, load_descriptor  # noqa: E402
from providers.base import Entity  # noqa: E402
from providers.hybrid import HybridProvider  # noqa: E402
from providers.rag import RagProvider  # noqa: E402
from providers.registry import build_provider  # noqa: E402
from providers.structured import StructuredTabularProvider  # noqa: E402

_KB_DIR = _BACKEND_DIR / "kb"


def _load_real_module(name: str):
    spec = importlib.util.spec_from_file_location(f"_real_{name}", _BACKEND_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def descriptor():
    return load_descriptor(_KB_DIR / "customer_sap.yaml")


# ── build_provider / registry wiring ───────────────────────────────────────────


def test_build_provider_returns_hybrid_provider_for_customer_sap(descriptor):
    """customer_sap's descriptor is adapter: hybrid (Phase 8a) — build_provider
    now returns a HybridProvider, not a bare StructuredTabularProvider."""
    provider = build_provider(descriptor)
    assert isinstance(provider, HybridProvider)
    assert provider.kb is descriptor
    assert isinstance(provider.structured, StructuredTabularProvider)
    # customer_sap.yaml's source.rag is null in this phase — no RagProvider is
    # built, so capabilities/behavior stay byte-identical to the plain
    # structured provider (Phase 8a hard gate: customer_sap unchanged).
    assert provider.rag is None
    assert provider.capabilities() == {"entity", "search", "context"}


def test_build_provider_returns_rag_provider_for_rag_adapter():
    rag_descriptor = KBDescriptor(
        id="docs_only",
        name="Docs KB",
        description="A rag-only KB for testing build_provider's rag path.",
        adapter="rag",
        retrieval_mode="rag",
        source={"kind": "rag", "roots": ["data"]},
        id_pattern=r"\b([A-Z]{2,8}_\d+)\b",
        vocab={"entity_singular": "doc", "entity_plural": "docs"},
        prompts={"repository_label": "Docs"},
    )
    provider = build_provider(rag_descriptor)
    assert isinstance(provider, RagProvider)
    assert provider.kb is rag_descriptor
    assert provider.capabilities() == {"search", "context", "rag"}


# ── HybridProvider parity with StructuredTabularProvider (no rag configured) ──


def test_hybrid_provider_delegates_structured_lookup_methods(descriptor):
    provider = build_provider(descriptor)
    structured = StructuredTabularProvider(descriptor)

    sample = "Can you explain rule RCCOMP_12.1 for me?"
    assert provider.extract_entity_id(sample) == structured.extract_entity_id(sample)

    entity = provider.get_entity("test_1")
    expected = structured.get_entity("test_1")
    assert entity is not None and expected is not None
    assert entity.raw == expected.raw


def test_hybrid_provider_build_context_matches_structured(descriptor):
    import data_loader

    provider = build_provider(descriptor)
    structured = StructuredTabularProvider(descriptor)

    rules = data_loader.get_rules()
    row = rules[rules["rule_id"].str.upper() == "TEST_1"].iloc[0]
    logic = str(row.get("rule_logic", "") or "")

    assert provider.build_context("TEST_1", row, logic, rules) == structured.build_context(
        "TEST_1", row, logic, rules
    )


def test_hybrid_provider_retrieve_context_matches_structured_with_no_rag_source(descriptor):
    provider = build_provider(descriptor)
    structured = StructuredTabularProvider(descriptor)

    hybrid_ctx = asyncio.run(provider.retrieve_context_for_query("q", entity_id="TEST_1"))
    structured_ctx = asyncio.run(structured.retrieve_context_for_query("q", entity_id="TEST_1"))
    assert hybrid_ctx == structured_ctx


def test_hybrid_provider_reload_matches_structured(descriptor, monkeypatch):
    import data_loader

    monkeypatch.setattr(data_loader, "reload_all", lambda descriptor=None: {"rules_loaded": 2})
    provider = build_provider(descriptor)
    assert provider.reload() == {"rules_loaded": 2}


# ── extract_entity_id parity with the old chat_agent._RULE_ID_RE ──────────────


def test_extract_entity_id_matches_old_regex(descriptor):
    provider = StructuredTabularProvider(descriptor)
    real_chat_agent = _load_real_module("chat_agent")
    sample = "Can you explain rule RCCOMP_12.1 for me?"
    old_match = real_chat_agent._RULE_ID_RE.search(sample)
    assert old_match is not None
    assert provider.extract_entity_id(sample) == old_match.group(1).upper()


def test_extract_entity_id_no_match_returns_none(descriptor):
    provider = StructuredTabularProvider(descriptor)
    assert provider.extract_entity_id("no id in this message") is None


# ── get_entity parity with data_loader ─────────────────────────────────────────


def test_get_entity_matches_data_loader_row(descriptor):
    import data_loader  # resolves to conftest's MagicMock stub

    provider = StructuredTabularProvider(descriptor)
    entity = provider.get_entity("test_1")  # lowercase on purpose — id is upper-cased
    assert entity is not None
    assert isinstance(entity, Entity)
    assert entity.id == "TEST_1"

    rules = data_loader.get_rules()
    expected_row = rules[rules["rule_id"].str.upper() == "TEST_1"].iloc[0]
    assert entity.raw == expected_row.to_dict()
    assert entity.title == expected_row["rule_description"]
    assert entity.category == expected_row["quality_category"]
    assert entity.logic == expected_row["rule_logic"]


def test_get_entity_unknown_id_returns_none(descriptor):
    provider = StructuredTabularProvider(descriptor)
    assert provider.get_entity("NOPE_999") is None


# ── search ──────────────────────────────────────────────────────────────────────


def test_search_filters_by_category(descriptor):
    provider = StructuredTabularProvider(descriptor)
    results = provider.search("", category="Completeness")
    assert results
    assert all(e.category == "Completeness" for e in results)
    assert any(e.id == "TEST_1" for e in results)


def test_search_filters_by_keyword(descriptor):
    provider = StructuredTabularProvider(descriptor)
    results = provider.search("Test rule 2")
    assert [e.id for e in results] == ["TEST_2"]


# ── retrieve_context_for_query / build_context parity with the old ────────────
# ── chat_agent._build_rule_context ─────────────────────────────────────────────


def test_retrieve_context_for_query_matches_old_build_rule_context(descriptor):
    """With conftest's mocked data_loader (no yaml/refs), both the provider's
    async context method and the pre-refactor chat_agent._build_rule_context
    (now a shim delegating to its own provider instance) produce the same
    context string for a known rule."""
    import data_loader

    real_chat_agent = _load_real_module("chat_agent")
    provider = StructuredTabularProvider(descriptor)

    rules = data_loader.get_rules()
    row = rules[rules["rule_id"].str.upper() == "TEST_1"].iloc[0]
    logic = str(row.get("rule_logic", "") or "")

    old_ctx, old_refs, old_yaml = real_chat_agent._build_rule_context("TEST_1", row, logic, rules)
    new_ctx = asyncio.run(provider.retrieve_context_for_query("irrelevant", entity_id="TEST_1"))

    assert new_ctx == old_ctx
    # Sanity: MOCK_RULES has no dependent_on/dependency text and the stubbed
    # data_loader returns no yaml/refs, so both should be empty here.
    assert old_ctx == ""
    assert old_refs == []
    assert old_yaml is None


def test_build_context_tuple_matches_old_build_rule_context(descriptor):
    """provider.build_context is the exact function chat_agent._build_rule_context
    now delegates to — same signature, same (ctx, ref_rules, yaml_match) tuple."""
    import data_loader

    real_chat_agent = _load_real_module("chat_agent")
    provider = StructuredTabularProvider(descriptor)

    rules = data_loader.get_rules()
    row = rules[rules["rule_id"].str.upper() == "TEST_1"].iloc[0]
    logic = str(row.get("rule_logic", "") or "")

    old = real_chat_agent._build_rule_context("TEST_1", row, logic, rules)
    new = provider.build_context("TEST_1", row, logic, rules)
    assert new == old


def test_retrieve_context_for_query_unknown_or_missing_entity_returns_empty(descriptor):
    provider = StructuredTabularProvider(descriptor)
    assert asyncio.run(provider.retrieve_context_for_query("q", entity_id=None)) == ""
    assert asyncio.run(provider.retrieve_context_for_query("q", entity_id="NOPE")) == ""


def test_build_context_uses_descriptor_severity_map(descriptor, monkeypatch):
    """Sibling severity labels come from kb.vocab.severity_map (the descriptor),
    which Phase 0 asserted is identical to chat_agent._SEVERITY_MAP."""
    import data_loader

    provider = StructuredTabularProvider(descriptor)
    rules = data_loader.get_rules()

    monkeypatch.setattr(
        data_loader, "get_referenced_rules",
        lambda rid: [{
            "rule_id": "TEST_2", "source": "dependent_on", "active": True,
            "rule_description": "Test rule 2", "rule_logic": "NAME1 > 0",
            "table_name_checked": "KNA1",
        }],
    )
    row = rules[rules["rule_id"].str.upper() == "TEST_1"].iloc[0]
    ctx, ref_rules, _yaml_match = provider.build_context(
        "TEST_1", row, str(row.get("rule_logic", "")), rules
    )
    assert "Severity: High" in ctx  # TEST_2's severity is 2 -> "High"
    assert ref_rules[0]["rule_id"] == "TEST_2"


# ── lifecycle ────────────────────────────────────────────────────────────────────


def test_reload_delegates_to_data_loader_reload_all(descriptor, monkeypatch):
    import data_loader

    called = {}

    def fake_reload_all(descriptor=None):
        called["descriptor"] = descriptor
        return {"rules_loaded": 2}

    monkeypatch.setattr(data_loader, "reload_all", fake_reload_all)
    provider = StructuredTabularProvider(descriptor)
    result = provider.reload()
    assert result == {"rules_loaded": 2}
    assert called["descriptor"] is descriptor
