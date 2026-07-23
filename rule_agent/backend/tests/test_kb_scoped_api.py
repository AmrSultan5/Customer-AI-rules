"""
Tests for Phase 5's KB-scoped API surface: GET /kbs, GET /kbs/{id},
POST /kb/{id}/chat[/stream], POST /kb/{id}/feedback, and the KB resolver's
precedence (main.get_provider). Also asserts the unprefixed /chat, /chat/stream,
and /feedback aliases still work unscoped (resolving to the active/default KB).

conftest.py replaces sys.modules["chat_agent"] with a MagicMock
(handle_message.return_value set; stream_message is auto-mocked but unused
here directly — main.py's own `stream_message` name is monkeypatched per-test
where SSE streaming is exercised, same pattern as tests/test_conversations.py).
These tests exercise ROUTING/resolution, not the real LLM.
"""
import json as _json

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app, raise_server_exceptions=False)

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from main import limiter
    limiter._storage.reset()
    yield


# ── GET /kbs ─────────────────────────────────────────────────────────────────


def test_list_kbs_returns_customer_sap_with_capabilities():
    r = client.get("/kbs", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["active_kb"] == "customer_sap"
    assert body["switcher_enabled"] is True

    ids = {kb["id"] for kb in body["knowledge_bases"]}
    assert "customer_sap" in ids
    entry = next(kb for kb in body["knowledge_bases"] if kb["id"] == "customer_sap")
    assert entry["adapter"] == "hybrid"
    assert entry["retrieval_mode"] == "hybrid"
    assert set(entry["capabilities"]) == {"entity", "search", "context"}
    assert entry["name"]
    assert entry["description"]


def test_list_kbs_api_prefix_parity():
    r = client.get("/api/kbs", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["active_kb"] == "customer_sap"


def test_list_kbs_requires_auth():
    r = client.get("/kbs")
    assert r.status_code == 401


# ── GET /kbs/{kb_id} ─────────────────────────────────────────────────────────


def test_get_kb_detail_returns_descriptor_and_prompt_fields():
    r = client.get("/kbs/customer_sap", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "customer_sap"
    assert "custom_prompt" in body
    assert "enhanced_prompt" in body
    # No prompt has been saved yet (Phase 6 feature) — both are None.
    assert body["custom_prompt"] is None
    assert body["enhanced_prompt"] is None


def test_get_kb_detail_reflects_saved_prompt():
    import asyncio
    import db
    from models import KnowledgeBase

    async def seed():
        async with db.AsyncSessionLocal() as s:
            existing = await s.get(KnowledgeBase, "customer_sap")
            if existing is None:
                s.add(KnowledgeBase(id="customer_sap", name="Customer SAP", enhanced_prompt="Be terse."))
            else:
                existing.enhanced_prompt = "Be terse."
            await s.commit()

    asyncio.run(seed())
    try:
        r = client.get("/kbs/customer_sap", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["enhanced_prompt"] == "Be terse."
    finally:
        async def clear():
            async with db.AsyncSessionLocal() as s:
                row = await s.get(KnowledgeBase, "customer_sap")
                if row is not None:
                    row.enhanced_prompt = None
                    await s.commit()
        asyncio.run(clear())


def test_get_kb_detail_unknown_kb_404s():
    r = client.get("/kbs/does_not_exist", headers=AUTH)
    assert r.status_code == 404


# ── POST /kb/{kb_id}/chat (+ /api prefix) ─────────────────────────────────────


def test_kb_scoped_chat_resolves_and_responds():
    r = client.post(
        "/kb/customer_sap/chat", headers=AUTH,
        json={"message": "Hello", "history": []},
    )
    assert r.status_code == 200
    assert "response" in r.json()


def test_kb_scoped_chat_api_prefix_parity():
    r = client.post(
        "/api/kb/customer_sap/chat", headers=AUTH,
        json={"message": "Hello", "history": []},
    )
    assert r.status_code == 200
    assert "response" in r.json()


def test_kb_scoped_chat_unknown_kb_404s():
    r = client.post(
        "/kb/does_not_exist/chat", headers=AUTH,
        json={"message": "Hello", "history": []},
    )
    assert r.status_code == 404


def test_kb_scoped_chat_requires_auth():
    r = client.post("/kb/customer_sap/chat", json={"message": "Hello", "history": []})
    assert r.status_code == 401


# ── POST /kb/{kb_id}/chat/stream ──────────────────────────────────────────────


def test_kb_scoped_chat_stream_resolves(monkeypatch):
    async def fake_stream(message, context_rule_id=None, history=None,
                          allow_general=False, extra_context=None, **kwargs):
        # Assert the resolved provider was threaded through.
        assert kwargs.get("provider") is not None
        assert kwargs["provider"].kb.id == "customer_sap"
        yield f"data: {_json.dumps({'type': 'chunk', 'text': 'hi'})}\n\n"
        yield f"data: {_json.dumps({'type': 'done', 'rule_id': None, 'suggested_followups': []})}\n\n"

    import main as main_module
    monkeypatch.setattr(main_module, "stream_message", fake_stream)

    r = client.post(
        "/kb/customer_sap/chat/stream", headers=AUTH,
        json={"message": "hi", "history": []},
    )
    assert r.status_code == 200
    assert "hi" in r.text


def test_kb_scoped_chat_stream_unknown_kb_404s():
    r = client.post(
        "/kb/does_not_exist/chat/stream", headers=AUTH,
        json={"message": "hi", "history": []},
    )
    assert r.status_code == 404


# ── POST /kb/{kb_id}/feedback ─────────────────────────────────────────────────


def test_kb_scoped_feedback_ok():
    r = client.post(
        "/kb/customer_sap/feedback", headers=AUTH,
        json={"rating": "up", "mode": "analyst"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_kb_scoped_feedback_unknown_kb_404s():
    r = client.post(
        "/kb/does_not_exist/feedback", headers=AUTH,
        json={"rating": "up", "mode": "analyst"},
    )
    assert r.status_code == 404


# ── Unprefixed aliases still resolve to the active/default KB ────────────────


def test_unprefixed_chat_alias_still_works():
    r = client.post("/chat", headers=AUTH, json={"message": "Hello", "history": []})
    assert r.status_code == 200
    assert "response" in r.json()


def test_unprefixed_chat_alias_api_prefix_still_works():
    r = client.post("/api/chat", headers=AUTH, json={"message": "Hello", "history": []})
    assert r.status_code == 200


def test_unprefixed_feedback_alias_still_works():
    r = client.post("/feedback", headers=AUTH, json={"rating": "up", "mode": "analyst"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ── Explicit knowledge_base_id in the request body (alias routes) ────────────


def test_chat_body_knowledge_base_id_unknown_404s():
    r = client.post(
        "/chat", headers=AUTH,
        json={"message": "Hello", "history": [], "knowledge_base_id": "does_not_exist"},
    )
    assert r.status_code == 404


def test_chat_body_knowledge_base_id_known_resolves():
    r = client.post(
        "/chat", headers=AUTH,
        json={"message": "Hello", "history": [], "knowledge_base_id": "customer_sap"},
    )
    assert r.status_code == 200


# ── get_provider resolver precedence (unit-level) ─────────────────────────────


def test_get_provider_resolves_active_kb_by_default():
    import main as main_module
    provider = main_module.get_provider()
    assert provider.kb.id == "customer_sap"


def test_get_provider_conversation_kb_used_when_no_explicit_kb():
    import main as main_module
    provider = main_module.get_provider(None, "customer_sap")
    assert provider.kb.id == "customer_sap"


def test_get_provider_unknown_explicit_kb_raises_404():
    import main as main_module
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        main_module.get_provider("does_not_exist")
    assert exc_info.value.status_code == 404


def test_get_provider_ignores_explicit_kb_when_switcher_disabled(monkeypatch):
    import main as main_module
    from config import settings

    monkeypatch.setattr(settings, "enable_kb_switcher", False)
    # An explicit (even unknown) kb_id is ignored entirely when the switcher
    # is disabled — resolution falls through to conversation_kb / active_kb,
    # so this must NOT 404.
    provider = main_module.get_provider("does_not_exist")
    assert provider.kb.id == settings.active_kb
