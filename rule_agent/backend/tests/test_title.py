"""Tests for conversation title sanitization (openai_client).

The sidebar renders titles as plain text, so markdown from the title model
(or from the user's first message via the fallback) must be stripped.
"""

import openai_client


def test_clean_title_strips_markdown():
    assert openai_client._clean_title("**Postal Code Rules**") == "Postal Code Rules"
    assert openai_client._clean_title("`KNA1` completeness # check") == "KNA1 completeness check"
    assert openai_client._clean_title('  "Quoted title"  ') == "Quoted title"


def test_clean_title_collapses_whitespace():
    assert openai_client._clean_title("Too   many\n spaces") == "Too many spaces"


def test_fallback_title_strips_markdown():
    title = openai_client._fallback_title("**Explain rule** RCCOMP_1")
    assert "*" not in title
    assert "Explain rule RCCOMP_1" in title


def test_fallback_title_empty_message():
    assert openai_client._fallback_title("") == "New chat"


def test_generate_title_failure_uses_clean_fallback(monkeypatch):
    def boom():
        raise RuntimeError("no api")
    monkeypatch.setattr(openai_client, "_get_client", boom)
    title = openai_client.generate_title("**bold question** about `KNA1`")
    assert title
    assert "*" not in title
    assert "`" not in title
