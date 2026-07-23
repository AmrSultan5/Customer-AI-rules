"""
Tests for Phase 6's prompt-enhance + save endpoints:
POST /kb/{kb_id}/prompt/enhance and PUT /kb/{kb_id}/prompt.

conftest.py replaces sys.modules["explanation_engine"] with a bare MagicMock
(no call_openai_async/model_for_tier configured), so every test that exercises
the enhance route patches those two attributes via monkeypatch — an AsyncMock
for the (async, non-streaming) LLM call and a plain callable for the model-id
lookup. The real Anthropic API is never called.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import prompts
from kb._schema import load_descriptor
from main import app

client = TestClient(app, raise_server_exceptions=False)

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

_BACKEND_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from main import limiter
    limiter._storage.reset()
    yield


@pytest.fixture(autouse=True)
def _clear_customer_sap_prompt_row():
    """Start (and end) every test with no saved prompt for customer_sap, so
    tests don't leak state into each other or into other test modules."""
    import db
    from models import KnowledgeBase

    async def clear():
        async with db.AsyncSessionLocal() as s:
            row = await s.get(KnowledgeBase, "customer_sap")
            if row is not None:
                row.custom_prompt = None
                row.enhanced_prompt = None
                row.prompt_updated_at = None
                await s.commit()

    asyncio.run(clear())
    yield
    asyncio.run(clear())


def _mock_enhance(
    monkeypatch,
    enhanced_text: str = "ENHANCED: Always cite the rule ID in bold.",
    model: str = "claude-sonnet-4-6-test",
) -> AsyncMock:
    import main as main_module

    call_mock = AsyncMock(return_value=enhanced_text)
    monkeypatch.setattr(main_module.explanation_engine, "call_openai_async", call_mock)
    monkeypatch.setattr(
        main_module.explanation_engine, "model_for_tier", lambda tier="standard": model
    )
    return call_mock


# ── POST /kb/{kb_id}/prompt/enhance ───────────────────────────────────────────


def test_enhance_returns_draft_enhanced_and_model(monkeypatch):
    call_mock = _mock_enhance(monkeypatch)

    r = client.post(
        "/kb/customer_sap/prompt/enhance", headers=AUTH,
        json={"draft": "always mention rule ids"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["draft"] == "always mention rule ids"
    assert body["enhanced"] == "ENHANCED: Always cite the rule ID in bold."
    assert body["model"] == "claude-sonnet-4-6-test"

    # Standard tier, non-streaming, tagged for analytics with call_type + KB id.
    call_mock.assert_awaited_once()
    args, kwargs = call_mock.call_args
    assert args[1] == "always mention rule ids"  # user_msg == draft
    assert kwargs["tier"] == "standard"
    assert kwargs["call_type"] == "prompt_enhance"
    assert kwargs["knowledge_base_id"] == "customer_sap"


def test_enhance_system_prompt_is_kb_aware(monkeypatch):
    call_mock = _mock_enhance(monkeypatch)
    client.post(
        "/kb/customer_sap/prompt/enhance", headers=AUTH,
        json={"draft": "be concise"},
    )
    system_prompt_arg = call_mock.call_args[0][0]
    descriptor = load_descriptor(_BACKEND_DIR / "kb" / "customer_sap.yaml")
    assert descriptor.name in system_prompt_arg
    assert descriptor.description in system_prompt_arg


def test_enhance_blank_draft_400s(monkeypatch):
    _mock_enhance(monkeypatch)
    r = client.post(
        "/kb/customer_sap/prompt/enhance", headers=AUTH,
        json={"draft": "   "},
    )
    assert r.status_code == 400


def test_enhance_unknown_kb_404s(monkeypatch):
    _mock_enhance(monkeypatch)
    r = client.post(
        "/kb/does_not_exist/prompt/enhance", headers=AUTH,
        json={"draft": "be concise"},
    )
    assert r.status_code == 404


def test_enhance_api_prefix_parity(monkeypatch):
    _mock_enhance(monkeypatch)
    r = client.post(
        "/api/kb/customer_sap/prompt/enhance", headers=AUTH,
        json={"draft": "be concise"},
    )
    assert r.status_code == 200
    assert r.json()["enhanced"]


def test_enhance_requires_auth(monkeypatch):
    _mock_enhance(monkeypatch)
    r = client.post("/kb/customer_sap/prompt/enhance", json={"draft": "be concise"})
    assert r.status_code == 401


def test_enhance_llm_failure_returns_502_family_error(monkeypatch):
    import main as main_module

    async def boom(*args, **kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(main_module.explanation_engine, "call_openai_async", boom)
    r = client.post(
        "/kb/customer_sap/prompt/enhance", headers=AUTH,
        json={"draft": "be concise"},
    )
    assert r.status_code == 500


# ── PUT /kb/{kb_id}/prompt ────────────────────────────────────────────────────


def test_save_prompt_persists_and_get_kb_reflects_it():
    r = client.put(
        "/kb/customer_sap/prompt", headers=AUTH,
        json={
            "custom_prompt": "always mention rule ids",
            "enhanced_prompt": "Always cite the rule ID in bold.",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["custom_prompt"] == "always mention rule ids"
    assert body["enhanced_prompt"] == "Always cite the rule ID in bold."
    assert body["prompt_updated_at"]

    detail = client.get("/kbs/customer_sap", headers=AUTH)
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["custom_prompt"] == "always mention rule ids"
    assert detail_body["enhanced_prompt"] == "Always cite the rule ID in bold."


def test_save_prompt_unknown_kb_404s():
    r = client.put(
        "/kb/does_not_exist/prompt", headers=AUTH,
        json={"custom_prompt": "x", "enhanced_prompt": "y"},
    )
    assert r.status_code == 404


def test_save_prompt_requires_auth():
    r = client.put(
        "/kb/customer_sap/prompt",
        json={"custom_prompt": "x", "enhanced_prompt": "y"},
    )
    assert r.status_code == 401


def test_save_prompt_allows_clearing_with_nulls():
    client.put(
        "/kb/customer_sap/prompt", headers=AUTH,
        json={"custom_prompt": "temp", "enhanced_prompt": "temp enhanced"},
    )
    r = client.put(
        "/kb/customer_sap/prompt", headers=AUTH,
        json={"custom_prompt": None, "enhanced_prompt": None},
    )
    assert r.status_code == 200
    assert r.json()["custom_prompt"] is None
    assert r.json()["enhanced_prompt"] is None


# ── Integration: saved enhanced_prompt reaches build_system_prompt ───────────


def test_saved_enhanced_prompt_is_injected_before_contract_line():
    saved_text = "Always cite the rule ID in bold at the start of the answer."
    r = client.put(
        "/kb/customer_sap/prompt", headers=AUTH,
        json={"custom_prompt": "always mention rule ids", "enhanced_prompt": saved_text},
    )
    assert r.status_code == 200

    descriptor = load_descriptor(_BACKEND_DIR / "kb" / "customer_sap.yaml")
    assembled = prompts.build_system_prompt(descriptor, custom_prompt=saved_text)

    assert "## Knowledge base instructions" in assembled
    assert saved_text in assembled

    kb_idx = assembled.index("## Knowledge base instructions")
    contract_idx = assembled.index("**Why it matters:**")
    assert kb_idx < contract_idx, "contract line must render after injected instructions"

    # The contract line (and everything after it) must be exactly the same
    # tail as the no-custom-prompt assembly — nothing renders after it, so an
    # injected prompt can never push/override the mandatory closing rule.
    base_no_custom = prompts.build_system_prompt(descriptor)
    marker_idx = base_no_custom.index(prompts._CONTRACT_MARKER)
    base_tail = base_no_custom[marker_idx:]
    assert assembled.endswith(base_tail)
