"""
Tests for the Phase 0 KB descriptor layer: kb/_schema.py, kb/customer_sap.yaml,
and providers/registry.py.

These assert the descriptor is a faithful extraction of the values still
hardcoded in chat_agent.py / data_loader.py / schema_validator.py, so a future
phase can delete those hardcodes without silently changing behavior.

conftest.py stubs chat_agent/data_loader/schema_validator in sys.modules for
the main.py test suite (see conftest.py's module-level sys.modules assignments).
This file needs the REAL modules, so it loads them directly from disk instead of
`import`-ing (which would return the stubs). None of the three modules do I/O or
require API keys at import time, so loading them from disk is side-effect free.
"""

import importlib.util
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_real_module(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_real_{name}", _BACKEND_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


real_chat_agent = _load_real_module("chat_agent")
real_data_loader = _load_real_module("data_loader")
real_schema_validator = _load_real_module("schema_validator")

from kb._schema import KBDescriptor, load_descriptor  # noqa: E402
from providers.registry import KnowledgeBaseRegistry  # noqa: E402

_KB_DIR = _BACKEND_DIR / "kb"


def test_customer_sap_descriptor_loads_and_validates():
    descriptor = load_descriptor(_KB_DIR / "customer_sap.yaml")
    assert isinstance(descriptor, KBDescriptor)
    assert descriptor.id == "customer_sap"
    assert descriptor.adapter == "hybrid"
    assert descriptor.source.kind == "hybrid"
    # analyst_system inherited from _defaults.yaml
    assert descriptor.prompts.analyst_system
    assert "{entity_singular}" in descriptor.prompts.analyst_system
    assert "**Why it matters:**" in descriptor.prompts.analyst_system


def test_id_pattern_matches_chat_agent():
    descriptor = load_descriptor(_KB_DIR / "customer_sap.yaml")
    assert descriptor.id_pattern == real_chat_agent._RULE_ID_RE.pattern


def test_vocab_matches_pre_phase3_chat_agent_constants():
    """chat_agent._CATEGORIES/_SEVERITY_MAP/_TABLE_BUSINESS_NAMES were deleted in
    Phase 3 (callers now read provider.kb.vocab.* instead) — see
    tests/test_prompts.py, which keeps a golden literal copy of their values
    and is the source of truth for this parity check going forward."""
    from tests.test_prompts import (
        _OLD_CATEGORIES, _OLD_SEVERITY_MAP, _OLD_TABLE_BUSINESS_NAMES,
    )

    assert not hasattr(real_chat_agent, "_CATEGORIES")
    assert not hasattr(real_chat_agent, "_SEVERITY_MAP")
    assert not hasattr(real_chat_agent, "_TABLE_BUSINESS_NAMES")

    descriptor = load_descriptor(_KB_DIR / "customer_sap.yaml")
    assert descriptor.vocab.categories == _OLD_CATEGORIES
    assert descriptor.vocab.severity_map == _OLD_SEVERITY_MAP
    assert descriptor.vocab.business_names == _OLD_TABLE_BUSINESS_NAMES


def test_structured_source_matches_data_loader_paths():
    descriptor = load_descriptor(_KB_DIR / "customer_sap.yaml")
    files = descriptor.source.structured.files
    dirs = descriptor.source.structured.dirs
    assert files["rules_file"] == real_data_loader.RULES_FILE.relative_to(
        _BACKEND_DIR
    ).as_posix()
    assert files["sap_file"] == real_data_loader.SAP_FILE.relative_to(
        _BACKEND_DIR
    ).as_posix()
    assert files["sap_file_z11"] == real_data_loader.SAP_FILE_Z11.relative_to(
        _BACKEND_DIR
    ).as_posix()
    assert dirs["golden_dir"] == real_data_loader.GOLDEN_DIR.relative_to(
        _BACKEND_DIR
    ).as_posix()
    assert dirs["custom_ops_dir"] == real_data_loader.CUSTOM_OPS_DIR.relative_to(
        _BACKEND_DIR
    ).as_posix()


def test_field_map_covers_required_columns():
    descriptor = load_descriptor(_KB_DIR / "customer_sap.yaml")
    rules_keys = set(descriptor.field_map.rules.keys())
    sap_keys = set(descriptor.field_map.sap.keys())
    assert set(real_schema_validator.REQUIRED_RULES_COLS) <= rules_keys
    assert set(real_schema_validator.REQUIRED_SAP_COLS) <= sap_keys


def test_registry_lists_customer_sap_as_default():
    registry = KnowledgeBaseRegistry(kb_dir=_KB_DIR, active_kb="customer_sap")
    ids = {d.id for d in registry.list_descriptors()}
    assert "customer_sap" in ids  # docs_demo (Phase 8b) may also be registered
    assert registry.default_kb_id == "customer_sap"
    assert registry.get_descriptor("customer_sap") is not None
    assert registry.get_descriptor("nonexistent") is None
