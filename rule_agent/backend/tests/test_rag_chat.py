"""
Phase 8b — RAG chat routing tests.

A rag-only KB (no "entity" capability) must answer from retrieved chunks via
provider.retrieve_context_for_query + the LLM, NOT via the structured
rule-lookup flow (data_loader.get_rules / _extract_rule_id). A structured/
hybrid KB (customer_sap) must still take the structured path unchanged.

The real chat_agent is loaded from disk (conftest stubs it with a MagicMock in
sys.modules for the API suite); the LLM + provider are faked — no network.
"""

import asyncio
import importlib.util
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_real_module(name: str):
    spec = importlib.util.spec_from_file_location(f"_real_{name}", _BACKEND_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


real_chat_agent = _load_real_module("chat_agent")


class _FakeRagProvider:
    """RAG-only: no 'entity' capability, returns canned context."""

    def __init__(self, ctx="Source: faq.md#0\nMedium is the default size."):
        self._ctx = ctx
        self.kb = type("KB", (), {"id": "docs_demo"})()
        self.retrieve_calls = []

    def capabilities(self):
        return {"search", "context", "rag"}

    async def retrieve_context_for_query(self, query, *, entity_id=None, limit=8):
        self.retrieve_calls.append(query)
        return self._ctx


def _collect_done(events):
    for e in events:
        if '"type": "done"' in e or '"type":"done"' in e:
            return e
    return ""


def test_stream_message_rag_path_uses_retrieval_not_rules(monkeypatch):
    prov = _FakeRagProvider()

    # Fake the LLM stream + system prompt; explode if the structured path
    # (data_loader.get_rules) is ever reached.
    async def fake_stream(system, user, max_tokens=1000, **kw):
        assert "Context from the knowledge base:" in user
        assert "faq.md" in user
        for tok in ["Medium ", "is ", "the ", "default."]:
            yield tok

    import explanation_engine
    monkeypatch.setattr(explanation_engine, "call_openai_stream", fake_stream, raising=False)
    monkeypatch.setattr(real_chat_agent, "_get_system_prompt", lambda: "SYS")

    def _boom():  # data_loader.get_rules must not be called on the RAG path
        raise AssertionError("structured rule lookup must not run for a rag-only KB")

    import data_loader
    monkeypatch.setattr(data_loader, "get_rules", _boom, raising=False)

    async def _collect():
        return [e async for e in real_chat_agent.stream_message("what size is default?", provider=prov)]

    events = asyncio.run(_collect())

    assert prov.retrieve_calls == ["what size is default?"]
    body = "".join(events)
    assert "Medium" in body and "default." in body
    done = _collect_done(events)
    assert '"rule_id": null' in done or '"rule_id":null' in done


def test_handle_message_rag_path(monkeypatch):
    prov = _FakeRagProvider()

    async def fake_async(system, user, max_tokens=1000, **kw):
        assert "faq.md" in user
        return "Medium is the default size."

    monkeypatch.setattr("explanation_engine.call_openai_async", fake_async, raising=False)
    monkeypatch.setattr(real_chat_agent, "_get_system_prompt", lambda: "SYS")

    result = real_chat_agent.handle_message("what size is default?", provider=prov)

    assert result["rule_id"] is None
    assert "Medium" in result["response"]
    assert prov.retrieve_calls == ["what size is default?"]


def test_customer_sap_provider_keeps_entity_capability():
    """Regression guard: the capability branch only diverts rag-only KBs.
    customer_sap (hybrid) must keep 'entity', so it stays on the structured
    path and is unaffected by Phase 8b."""
    from providers.registry import KnowledgeBaseRegistry

    reg = KnowledgeBaseRegistry()
    cust = reg.get_provider("customer_sap")
    assert "entity" in cust.capabilities()
    docs = reg.get_provider("docs_demo")
    assert "entity" not in docs.capabilities()
