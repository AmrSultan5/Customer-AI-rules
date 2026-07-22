"""Tests for the business-friendly analyst answer layer.

Loads the REAL chat_agent module (conftest replaces sys.modules["chat_agent"]
with a MagicMock for the API tests); its lazy imports resolve to the conftest
mocks, same pattern as test_chat_routing.py.

Phase 1 note: rule_parser.py, sap_mapper.py, lineage_service.py, and
impact_service.py were removed along with the engineer/PM tooling. Tests that
exercised their enrichment (SAP field business names, lineage lookups, the
impact-digest "Why it matters" grounding) were removed or rewritten below to
reflect the graceful fallback behavior chat_agent now uses instead of
importing those modules.
"""

import importlib.util
import inspect
import os
import sys
from unittest.mock import MagicMock

import pytest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "chat_agent_business", os.path.join(_BACKEND_DIR, "chat_agent.py")
)
chat_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_agent)


# ── Task 1: table & column formatters ─────────────────────────────────────────


def test_sap_table_answer_known_table_leads_with_business_name():
    out = chat_agent._format_sap_table_answer("TEST_1", "KNA1")
    assert "customer master" in out
    assert "KNA1" in out


def test_sap_table_answer_unknown_table_falls_back_to_old_format():
    out = chat_agent._format_sap_table_answer("TEST_1", "ZWEIRD99")
    assert out == "The SAP table checked by rule **TEST_1** is: `ZWEIRD99`"


def test_sap_table_answer_missing_table():
    out = chat_agent._format_sap_table_answer("TEST_1", "")
    assert "No SAP table information" in out


def test_sap_column_answer_missing_column():
    out = chat_agent._format_sap_column_answer("TEST_1", "KNA1", "")
    assert "No SAP column information" in out


def test_sap_column_answer_falls_back_without_sap_mapper():
    """sap_mapper.py was removed with the engineer/PM tooling; the business-name
    lookup now always fails (module not found) and _format_sap_column_answer
    gracefully falls back to the raw technical format."""
    out = chat_agent._format_sap_column_answer("TEST_1", "KNA1", "KUNNR")
    assert out == "The SAP column checked by rule **TEST_1** is: `KUNNR`"


def test_handle_message_sap_table_is_business_friendly(monkeypatch):
    monkeypatch.setattr(chat_agent, "_classify_intent_llm", lambda m, r: "sap_table")
    monkeypatch.setattr(chat_agent, "_generate_followups", lambda *a, **k: [])
    result = chat_agent.handle_message("Which table does TEST_1 check?")
    assert "customer master" in result["response"]
    assert "KNA1" in result["response"]


def test_both_paths_use_shared_table_formatter():
    assert "_format_sap_table_answer" in inspect.getsource(chat_agent.handle_message)
    assert "_format_sap_table_answer" in inspect.getsource(chat_agent.stream_message)
    assert "_format_sap_column_answer" in inspect.getsource(chat_agent.handle_message)
    assert "_format_sap_column_answer" in inspect.getsource(chat_agent.stream_message)


def test_stream_message_sap_table_is_business_friendly(monkeypatch):
    import asyncio
    monkeypatch.setattr(chat_agent, "_classify_intent_llm", lambda m, r: "sap_table")
    monkeypatch.setattr(chat_agent, "_generate_followups", lambda *a, **k: [])

    async def collect():
        import json
        text = []
        async for ev in chat_agent.stream_message("Which table does TEST_1 check?"):
            # Each event is an SSE line: "data: {...}\n\n". Reassemble the
            # chunk text the way a client would, so assertions are not broken
            # by chunk boundaries or JSON escaping.
            payload = json.loads(ev[len("data: "):])
            if payload.get("type") == "chunk":
                text.append(payload["text"])
        return "".join(text)

    out = asyncio.run(collect())
    assert "customer master" in out
    assert "KNA1" in out


# ── Task 2: fields formatter (Phase 1: graceful fallback, no rule_parser/sap_mapper) ──


def test_fields_answer_is_graceful_fallback():
    out = chat_agent._format_fields_answer("TEST_1", "KUNNR IS NOT NULL")
    assert "TEST_1" in out
    assert "aren't available" in out


def test_both_paths_use_shared_fields_formatter():
    assert "_format_fields_answer" in inspect.getsource(chat_agent.handle_message)
    assert "_format_fields_answer" in inspect.getsource(chat_agent.stream_message)


def test_handle_message_fields_intent_returns_fallback(monkeypatch):
    monkeypatch.setattr(chat_agent, "_classify_intent_llm", lambda m, r: "fields")
    monkeypatch.setattr(chat_agent, "_generate_followups", lambda *a, **k: [])
    result = chat_agent.handle_message("Which fields does TEST_1 use?")
    assert "aren't available" in result["response"]


def test_stream_message_fields_intent_returns_fallback(monkeypatch):
    import asyncio
    monkeypatch.setattr(chat_agent, "_classify_intent_llm", lambda m, r: "fields")
    monkeypatch.setattr(chat_agent, "_generate_followups", lambda *a, **k: [])

    async def collect():
        import json
        text = []
        async for ev in chat_agent.stream_message("Which fields does TEST_1 use?"):
            payload = json.loads(ev[len("data: "):])
            if payload.get("type") == "chunk":
                text.append(payload["text"])
        return "".join(text)

    out = asyncio.run(collect())
    assert "aren't available" in out


# ── Task 3: lineage formatter (Phase 1: lineage_service removed) ─────────────

_FULL_LINEAGE = {
    "module": "Customer",
    "group": "Completeness",
    "rule_responsibility": "MDM Team",
    "datamart_or_reference_table_used": "dm_customer, ref_country",
    "pipeline_sources": ["src_kna1"],
    "workflow_steps": ["load", "validate", "report"],
    "custom_operations": ["dedupe_customers"],
    "sibling_rules": ["TEST_2"],
    "pipeline_name": "golden/completeness.yaml",
}


def test_lineage_answer_is_markdown_bullets():
    """_format_lineage_answer itself is a pure formatter (no lineage_service
    dependency) — still exercised directly with a hand-built dict."""
    out = chat_agent._format_lineage_answer("TEST_1", _FULL_LINEAGE)
    assert "- **Owned by:** MDM Team" in out
    assert "- **Data comes from:** dm_customer, ref_country" in out
    assert "- **Runs alongside 1 related rule" in out
    assert ";" not in out.split("\n")[0]  # headline is not the old semicolon dump


def test_lineage_answer_empty_falls_back():
    out = chat_agent._format_lineage_answer("TEST_1", {})
    assert out == "No lineage information found for rule TEST_1."


def test_both_paths_use_shared_lineage_formatter():
    assert "_format_lineage_answer" in inspect.getsource(chat_agent.handle_message)
    assert "_format_lineage_answer" in inspect.getsource(chat_agent.stream_message)


def test_handle_message_lineage_intent_returns_no_data_fallback(monkeypatch):
    """lineage_service.py was removed; the lineage/workflow intent now always
    calls _format_lineage_answer with an empty dict, i.e. the "no lineage
    information" fallback."""
    monkeypatch.setattr(chat_agent, "_classify_intent_llm", lambda m, r: "lineage")
    monkeypatch.setattr(chat_agent, "_generate_followups", lambda *a, **k: [])
    result = chat_agent.handle_message("Where does TEST_1 data come from?")
    assert result["response"] == "No lineage information found for rule TEST_1."


def test_stream_message_lineage_intent_returns_no_data_fallback(monkeypatch):
    import asyncio
    monkeypatch.setattr(chat_agent, "_classify_intent_llm", lambda m, r: "lineage")
    monkeypatch.setattr(chat_agent, "_generate_followups", lambda *a, **k: [])

    async def collect():
        import json
        text = []
        async for ev in chat_agent.stream_message("Where does TEST_1 data come from?"):
            payload = json.loads(ev[len("data: "):])
            if payload.get("type") == "chunk":
                text.append(payload["text"])
        return "".join(text)

    out = asyncio.run(collect())
    assert out == "No lineage information found for rule TEST_1."


# ── Task 4: "Why it matters" prompt contract (impact_digest dropped in Phase 1) ──


def test_impact_digest_removed_from_chat_agent():
    """impact_service.py was removed; chat_agent no longer builds a deterministic
    impact digest for the 'Why it matters' line."""
    assert not hasattr(chat_agent, "_impact_digest")


def test_system_prompt_requires_why_it_matters():
    sys.modules.setdefault("analytics", MagicMock())
    spec = importlib.util.spec_from_file_location(
        "explanation_engine_real", os.path.join(_BACKEND_DIR, "explanation_engine.py")
    )
    ee = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ee)
    assert "Why it matters" in ee._SYSTEM_PROMPT
    # explain_rule still accepts impact_digest (unused by chat_agent now, but
    # the parameter itself is explanation_engine's concern, untouched in Phase 1)
    import inspect as _inspect
    assert "impact_digest" in _inspect.signature(ee.explain_rule).parameters


# ── Task 5: follow-up steering + fallback copy ────────────────────────────────


def test_followups_prompt_steers_business_first():
    prompt = chat_agent._FOLLOWUPS_SYSTEM.lower()
    assert "business" in prompt
    assert "what happens if" in prompt
    assert "only suggest technical" in prompt


def test_search_fallback_copy_is_natural(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(sys.modules["explanation_engine"], "call_openai", boom)
    result = chat_agent._find_rule_by_description("something about postcodes")
    assert "makes sure every customer" in result["response"]
    assert "RCCOMP_103.1" in result["response"]  # one rule-ID example kept


# ── Follow-up JSON parsing robustness (prod: model wraps JSON in fences) ──────


def test_generate_followups_handles_fenced_json(monkeypatch):
    monkeypatch.setattr(
        sys.modules["explanation_engine"], "call_openai",
        lambda *a, **k: '```json\n["How critical is this rule?", "What happens if it fails?"]\n```',
    )
    out = chat_agent._generate_followups("TEST_1", "which table?", "answer", {})
    assert out == ["How critical is this rule?", "What happens if it fails?"]


def test_generate_followups_handles_prose_preamble(monkeypatch):
    monkeypatch.setattr(
        sys.modules["explanation_engine"], "call_openai",
        lambda *a, **k: 'Here are the suggestions: ["What data does it protect?"]',
    )
    out = chat_agent._generate_followups("TEST_1", "which table?", "answer", {})
    assert out == ["What data does it protect?"]


def test_generate_followups_bare_json_still_works(monkeypatch):
    monkeypatch.setattr(
        sys.modules["explanation_engine"], "call_openai",
        lambda *a, **k: '["A?", "B?", "C?", "D?"]',
    )
    out = chat_agent._generate_followups("TEST_1", "which table?", "answer", {})
    assert out == ["A?", "B?", "C?"]  # capped at 3


def test_generate_followups_garbage_returns_empty(monkeypatch):
    monkeypatch.setattr(
        sys.modules["explanation_engine"], "call_openai",
        lambda *a, **k: "Sorry, I cannot produce suggestions right now.",
    )
    assert chat_agent._generate_followups("TEST_1", "which table?", "answer", {}) == []
