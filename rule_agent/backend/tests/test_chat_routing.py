"""Routing tests for the analyst chat flow (general vs. rule questions).

conftest.py replaces sys.modules["chat_agent"] with a MagicMock for the API
tests, so the real module is loaded here directly from its file under a
different name. Its lazy imports (explanation_engine, data_loader) still
resolve to the conftest mocks, which is what these tests rely on.
"""

import importlib.util
import os
import sys

import pytest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "chat_agent_real", os.path.join(_BACKEND_DIR, "chat_agent.py")
)
chat_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_agent)


def _is_general_router(system_prompt: str) -> bool:
    return "RULES or GENERAL" in system_prompt


def _is_active_rule_router(system_prompt: str) -> bool:
    return "FOLLOWUP, SEARCH, or GENERAL" in system_prompt


@pytest.fixture
def llm(monkeypatch):
    """Patch explanation_engine.call_openai with a scriptable fake.

    Set fake.routes/fake.answer before calling; fake.systems records every
    system prompt seen so tests can assert which routers ran.
    """
    class Fake:
        route_no_rule = "RULES"
        route_active = "FOLLOWUP"
        answer = "General answer."
        systems: list[str] = []
        fail_all = False

    fake = Fake()

    def call_openai(system_prompt, user_msg, max_tokens=600, history=None, tier="standard"):
        fake.systems.append(system_prompt)
        if fake.fail_all:
            raise RuntimeError("LLM down")
        if _is_general_router(system_prompt):
            return fake.route_no_rule
        if _is_active_rule_router(system_prompt):
            return fake.route_active
        return fake.answer

    monkeypatch.setattr(sys.modules["explanation_engine"], "call_openai", call_openai)
    return fake


# ── General mode ON (allow_general=True) ──────────────────────────────────────


def test_general_question_gets_direct_answer(llm):
    llm.route_no_rule = "GENERAL"
    llm.answer = "I don't have access to your team's wiki, but here is how git flow works…"
    result = chat_agent._handle_no_rule_id(
        "Is there a wiki page that explains the git flow?", allow_general=True
    )
    assert result["rule_id"] is None
    assert "git flow" in result["response"]
    # The general route never produces the rule-search refusal
    assert "couldn't find a rule" not in result["response"]


def test_rule_question_still_goes_to_search(llm):
    llm.route_no_rule = "RULES"
    llm.answer = "Found **TEST_1** — Test rule 1. It checks customer numbers."
    result = chat_agent._handle_no_rule_id(
        "is there a rule for customer number completeness?", allow_general=True
    )
    assert result["rule_id"] == "TEST_1"
    assert any(_is_general_router(s) for s in llm.systems)


def test_router_failure_falls_back_to_search(llm):
    llm.fail_all = True
    result = chat_agent._handle_no_rule_id(
        "Is there a wiki page that explains the git flow?", allow_general=True
    )
    # Search path's own failure fallback — behavior preserved end to end
    assert "Giving a rule ID" in result["response"]
    assert result["rule_id"] is None


def test_conversational_message_skips_router(llm):
    llm.answer = "You're welcome!"
    result = chat_agent._handle_no_rule_id("thanks", allow_general=True)
    assert result["response"] == "You're welcome!"
    assert not any(_is_general_router(s) for s in llm.systems)


def test_active_rule_general_question_gets_general_answer(llm):
    llm.route_active = "GENERAL"
    llm.answer = "I can't see your wiki, but the usual git flow is…"
    result = chat_agent._handle_no_rule_id(
        "Is there a wiki page that explains the git flow?",
        context_rule_id="TEST_1", allow_general=True,
    )
    assert result["rule_id"] is None
    assert "git flow" in result["response"]
    assert any(_is_active_rule_router(s) for s in llm.systems)


def test_general_answer_failure_returns_graceful_message(llm, monkeypatch):
    llm.route_no_rule = "GENERAL"

    real = sys.modules["explanation_engine"].call_openai

    def flaky(system_prompt, user_msg, max_tokens=600, history=None, tier="standard"):
        if _is_general_router(system_prompt):
            return real(system_prompt, user_msg, max_tokens, history, tier)
        raise RuntimeError("LLM down")

    monkeypatch.setattr(sys.modules["explanation_engine"], "call_openai", flaky)
    result = chat_agent._handle_no_rule_id("what is a golden record?", allow_general=True)
    assert "try again" in result["response"].lower()
    assert result["suggested_followups"] == []


# ── General mode OFF (default) — strict rules-only behavior ───────────────────


def test_default_general_question_goes_to_search(llm):
    """With the flag off, off-catalog questions take the original search path."""
    llm.answer = "I couldn't find a rule matching that description. Try naming a rule ID."
    result = chat_agent._handle_no_rule_id("Is there a wiki page that explains the git flow?")
    assert "couldn't find a rule" in result["response"]
    # Neither router runs — the message goes straight to description search
    assert not any(_is_general_router(s) for s in llm.systems)


def test_default_conversational_goes_to_search(llm):
    """With the flag off, even 'thanks' follows the original search path."""
    llm.answer = "I couldn't find a rule matching that description."
    result = chat_agent._handle_no_rule_id("thanks")
    assert not any(_is_general_router(s) for s in llm.systems)


def test_default_active_rule_general_falls_back_to_followup(llm):
    """With the flag off, a GENERAL classification behaves like FOLLOWUP."""
    llm.route_active = "GENERAL"
    llm.answer = "Answer using the rule context."
    result = chat_agent._handle_no_rule_id(
        "Is there a wiki page that explains the git flow?", context_rule_id="TEST_1"
    )
    # Answered as a rule follow-up — the active rule stays loaded
    assert result["rule_id"] == "TEST_1"
