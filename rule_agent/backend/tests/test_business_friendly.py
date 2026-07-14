"""Tests for the business-friendly analyst answer layer.

Loads the REAL chat_agent module (conftest replaces sys.modules["chat_agent"]
with a MagicMock for the API tests); its lazy imports resolve to the conftest
mocks, same pattern as test_chat_routing.py.
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


def test_sap_column_answer_uses_business_name(monkeypatch):
    monkeypatch.setattr(
        sys.modules["sap_mapper"], "lookup_sap_field",
        lambda key: {"field": "KNA1-KUNNR", "business_name": "Customer Number"},
    )
    out = chat_agent._format_sap_column_answer("TEST_1", "KNA1", "KUNNR")
    assert "Customer Number" in out
    assert "KUNNR" in out


def test_sap_column_answer_unknown_field_falls_back(monkeypatch):
    monkeypatch.setattr(
        sys.modules["sap_mapper"], "lookup_sap_field",
        lambda key: {"field": "KNA1-KUNNR", "business_name": "Unknown field"},
    )
    out = chat_agent._format_sap_column_answer("TEST_1", "KNA1", "KUNNR")
    assert out == "The SAP column checked by rule **TEST_1** is: `KUNNR`"


def test_sap_column_answer_missing_column():
    out = chat_agent._format_sap_column_answer("TEST_1", "KNA1", "")
    assert "No SAP column information" in out


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


def test_sap_column_answer_lookup_failure_falls_back(monkeypatch):
    monkeypatch.setattr(
        sys.modules["sap_mapper"], "lookup_sap_field",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    out = chat_agent._format_sap_column_answer("TEST_1", "KNA1", "KUNNR")
    assert out == "The SAP column checked by rule **TEST_1** is: `KUNNR`"
