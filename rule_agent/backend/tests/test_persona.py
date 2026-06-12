"""
Unit tests for persona_agent (Data Engineer / Project Manager modes) and
data_loader.get_custom_op_source.

conftest.py stubs data_loader and explanation_engine as MagicMock modules, so
persona_agent's lazy imports resolve to those stubs — each test configures the
stub functions it needs via monkeypatch.

get_custom_op_source is tested against the REAL data_loader module, loaded under
a private name so the conftest stub stays in place for everything else.
"""
import asyncio
import importlib.util
import json
import pathlib

import pandas as pd
import pytest

import persona_agent

BACKEND_DIR = pathlib.Path(__file__).parent.parent

RULES = pd.DataFrame(
    {
        "rule_id":            ["TEST_1", "TEST_2"],
        "rule_description":   ["Email must not be empty", "Postal code must be valid"],
        "quality_category":   ["Completeness", "Validity"],
        "table_name_checked": ["KNA1", "KNA1"],
        "column_name_checked":["SMTP_ADDR", "PSTLZ"],
        "severity":           ["1", "2"],
        "rule_logic":         ["SMTP_ADDR IS NOT NULL", "PSTLZ matches country format"],
    }
)

YAMLS = {
    "pipe_a": {
        "name": "pipe_a",
        "yaml_file": "customer/v1/pipe_a.yaml",
        "sources": ["dm_customer_general"],
        "rule_ids_in_yaml": ["TEST_1"],
        "custom_ops_used": [],
    },
    "pipe_b": {
        "name": "pipe_b",
        "yaml_file": "customer/v1/pipe_b.yaml",
        "sources": ["dm_customer_address"],
        "rule_ids_in_yaml": ["TEST_2"],
        "custom_ops_used": ["ops.foo"],
    },
}

CUSTOM_OPS = {
    "ops.foo": {
        "class_name": "FooOperation",
        "docstring": "Does foo checks",
        "file": "custom_operations/ops/foo.py",
    },
}


@pytest.fixture
def loader(monkeypatch):
    """Configure the stubbed data_loader module with a small consistent repo."""
    import data_loader

    monkeypatch.setattr(data_loader, "get_rules", lambda: RULES)
    monkeypatch.setattr(data_loader, "get_yaml_rules", lambda: YAMLS)
    monkeypatch.setattr(data_loader, "get_custom_operations", lambda: CUSTOM_OPS)
    monkeypatch.setattr(
        data_loader, "find_yaml_for_rule",
        lambda rid: YAMLS["pipe_a"] if rid.upper() == "TEST_1" else (
            YAMLS["pipe_b"] if rid.upper() == "TEST_2" else None
        ),
    )
    monkeypatch.setattr(data_loader, "get_yaml_raw", lambda f: f"# yaml of {f}\noperations: []")
    monkeypatch.setattr(
        data_loader, "extract_rule_section_from_yaml",
        lambda text, rid: f"# section for {rid}",
    )
    monkeypatch.setattr(
        data_loader, "get_custom_op_source",
        lambda key: "class FooOperation:\n    pass" if key == "ops.foo" else "",
    )
    return data_loader


def _set_selector_response(monkeypatch, payload):
    import explanation_engine

    async def fake_call(system_prompt, user_msg, max_tokens=600, history=None, json_mode=False):
        return payload

    monkeypatch.setattr(explanation_engine, "call_openai_async", fake_call)


# ── Stage 1: _select_targets ──────────────────────────────────────────────────


def test_select_targets_parses_valid_json(loader, monkeypatch):
    _set_selector_response(monkeypatch, json.dumps({
        "rule_ids": ["TEST_1"],
        "pipelines": ["pipe_a"],
        "custom_ops": ["ops.foo"],
        "needs_new_rule": False,
        "rationale": "matches email rule",
    }))
    sel = asyncio.run(persona_agent._select_targets("change the email check"))
    assert sel["rule_ids"] == ["TEST_1"]
    assert sel["pipelines"] == ["pipe_a"]
    assert sel["custom_ops"] == ["ops.foo"]
    assert sel["needs_new_rule"] is False


def test_select_targets_drops_hallucinated_names(loader, monkeypatch):
    _set_selector_response(monkeypatch, json.dumps({
        "rule_ids": ["FAKE_999", "TEST_2"],
        "pipelines": ["nonexistent_pipeline", "pipe_b"],
        "custom_ops": ["ops.invented"],
        "needs_new_rule": False,
        "rationale": "",
    }))
    sel = asyncio.run(persona_agent._select_targets("postal code change"))
    assert sel["rule_ids"] == ["TEST_2"]
    assert sel["pipelines"] == ["pipe_b"]
    assert sel["custom_ops"] == []


def test_select_targets_handles_fenced_json(loader, monkeypatch):
    fenced = "```json\n" + json.dumps({
        "rule_ids": ["TEST_1"], "pipelines": [], "custom_ops": [],
        "needs_new_rule": False, "rationale": "",
    }) + "\n```"
    _set_selector_response(monkeypatch, fenced)
    sel = asyncio.run(persona_agent._select_targets("email check"))
    assert sel["rule_ids"] == ["TEST_1"]


def test_select_targets_garbage_falls_back_to_regex(loader, monkeypatch):
    _set_selector_response(monkeypatch, "I am not JSON at all")
    sel = asyncio.run(persona_agent._select_targets("please update TEST_1 threshold"))
    assert sel["rule_ids"] == ["TEST_1"]
    # Fallback resolves the owning pipeline deterministically
    assert sel["pipelines"] == ["pipe_a"]
    assert sel["custom_ops"] == []


def test_select_targets_always_includes_explicit_rule_ids(loader, monkeypatch):
    _set_selector_response(monkeypatch, json.dumps({
        "rule_ids": ["TEST_1"], "pipelines": [], "custom_ops": [],
        "needs_new_rule": False, "rationale": "",
    }))
    sel = asyncio.run(persona_agent._select_targets("update TEST_2 to be stricter"))
    # Explicitly mentioned ID is pre-seeded first; LLM pick appended after
    assert sel["rule_ids"][0] == "TEST_2"
    assert "TEST_1" in sel["rule_ids"]


# ── Stage 2: _load_persona_context ────────────────────────────────────────────


def test_load_persona_context_includes_all_sources(loader):
    ctx = persona_agent._load_persona_context({
        "rule_ids": ["TEST_1"],
        "pipelines": ["pipe_b"],
        "custom_ops": ["ops.foo"],
        "needs_new_rule": False,
    })
    # Excel fields
    assert "Email must not be empty" in ctx
    assert "SMTP_ADDR" in ctx
    # Owning YAML cited with golden/ path + extracted section
    assert "golden/customer/v1/pipe_a.yaml" in ctx
    assert "# section for TEST_1" in ctx
    # Selected pipeline (not rule-owned) with raw YAML
    assert "golden/customer/v1/pipe_b.yaml" in ctx
    # Custom op path + source
    assert "custom_operations/ops/foo.py" in ctx
    assert "class FooOperation" in ctx
    # Databricks source tables surfaced
    assert "dm_customer_general" in ctx
    assert "dm_customer_address" in ctx
    # Inventory file note
    assert "dim_rules_inventory.xlsx" in ctx


def test_load_persona_context_respects_pipeline_char_cap(loader, monkeypatch):
    import data_loader
    monkeypatch.setattr(data_loader, "get_yaml_raw", lambda f: "Y" * 10_000)
    ctx = persona_agent._load_persona_context({
        "rule_ids": [], "pipelines": ["pipe_b"], "custom_ops": [],
        "needs_new_rule": False,
    })
    assert "Y" * persona_agent._PIPELINE_RAW_CAP in ctx
    assert "Y" * (persona_agent._PIPELINE_RAW_CAP + 1) not in ctx


def test_load_persona_context_empty_selection_asks_for_detail(loader):
    ctx = persona_agent._load_persona_context({
        "rule_ids": [], "pipelines": [], "custom_ops": [], "needs_new_rule": False,
    })
    assert "Ask the user for more detail" in ctx


def test_load_persona_context_includes_impact_block(loader, monkeypatch):
    import impact_service
    monkeypatch.setattr(
        impact_service, "format_impact_for_context",
        lambda rid: f"IMPACT ANALYSIS: dependents of {rid}",
    )
    ctx = persona_agent._load_persona_context({
        "rule_ids": ["TEST_1"], "pipelines": [], "custom_ops": [], "needs_new_rule": False,
    })
    assert "IMPACT ANALYSIS: dependents of TEST_1" in ctx


# ── _pipeline_excerpt ─────────────────────────────────────────────────────────


def test_pipeline_excerpt_short_file_passes_through(loader):
    assert persona_agent._pipeline_excerpt({"operations": []}, "short yaml", []) == "short yaml"


def test_pipeline_excerpt_long_file_uses_outline_and_sections(loader):
    ops = [
        {"kind": "read_dataio", "params": {"object_name": "dm_x"}},
        {"kind": "add", "params": {"name": "rule_id"}},
    ]
    raw = "# header\n" + ("filler line\n" * 800) + "expression: 'TEST_2'\n"
    excerpt = persona_agent._pipeline_excerpt({"operations": ops}, raw, ["TEST_2"])
    assert len(excerpt) <= persona_agent._PIPELINE_RAW_CAP
    assert "1. read_dataio | dm_x" in excerpt
    assert "2. add | rule_id" in excerpt
    # loader fixture stubs extract_rule_section_from_yaml → "# section for <rid>"
    assert "# section for TEST_2" in excerpt


def test_pipeline_excerpt_long_file_without_structure_falls_back_to_head(loader):
    raw = "Y" * 10_000
    excerpt = persona_agent._pipeline_excerpt({"operations": []}, raw, [])
    assert excerpt == "Y" * persona_agent._PIPELINE_RAW_CAP


# ── Complexity hint (PM sizing signal) ────────────────────────────────────────


def test_complexity_hint_small_change():
    hint = persona_agent._complexity_hint({
        "rule_ids": ["A"], "pipelines": ["p"], "custom_ops": [], "needs_new_rule": False,
    })
    assert "small change" in hint
    assert "1 rule" in hint
    assert "1 pipeline file" in hint


def test_complexity_hint_custom_op_requires_coordination():
    hint = persona_agent._complexity_hint({
        "rule_ids": ["A"], "pipelines": ["p"], "custom_ops": ["x"], "needs_new_rule": False,
    })
    assert "medium change" in hint
    assert "coordinate" in hint


def test_complexity_hint_new_rule_counts_toward_size():
    hint = persona_agent._complexity_hint({
        "rule_ids": [], "pipelines": ["p"], "custom_ops": [], "needs_new_rule": True,
    })
    assert "a new rule" in hint
    assert "medium change" in hint


def test_complexity_hint_empty_selection_is_empty():
    assert persona_agent._complexity_hint({
        "rule_ids": [], "pipelines": [], "custom_ops": [], "needs_new_rule": False,
    }) == ""


def test_pm_context_includes_sizing_signal(loader):
    ctx = persona_agent._load_persona_context({
        "rule_ids": ["TEST_1"], "pipelines": [], "custom_ops": [], "needs_new_rule": False,
    }, mode="pm")
    assert "SIZING SIGNAL" in ctx
    assert "small change" in ctx


def test_engineer_context_has_no_sizing_signal(loader):
    ctx = persona_agent._load_persona_context({
        "rule_ids": ["TEST_1"], "pipelines": [], "custom_ops": [], "needs_new_rule": False,
    }, mode="engineer")
    assert "SIZING SIGNAL" not in ctx


# ── Stage 3: stream_persona_message ───────────────────────────────────────────


def _parse_events(raw_events):
    return [json.loads(e[len("data:"):].strip()) for e in raw_events]


def _collect(agen):
    async def _run():
        return [e async for e in agen]
    return asyncio.run(_run())


def _patch_stream(monkeypatch, chunks=("Hello ", "world"), error=False):
    import explanation_engine

    async def fake_stream(system_prompt, user_msg, max_tokens=800, history=None):
        if error:
            raise RuntimeError("llm down")
        for c in chunks:
            yield c

    monkeypatch.setattr(explanation_engine, "call_openai_stream", fake_stream)


def test_stream_persona_message_event_sequence(loader, monkeypatch):
    async def fake_select(message, history=None, context_rule_id=None):
        return {"rule_ids": ["TEST_1"], "pipelines": [], "custom_ops": [], "needs_new_rule": False}

    monkeypatch.setattr(persona_agent, "_select_targets", fake_select)
    _patch_stream(monkeypatch)

    events = _parse_events(_collect(
        persona_agent.stream_persona_message("story", "engineer")
    ))
    types = [e["type"] for e in events]
    assert types[0] == "status"
    assert "chunk" in types
    assert types[-1] == "done"
    done = events[-1]
    # Single-rule selection → rule_id set, engineer followups attached
    assert done["rule_id"] == "TEST_1"
    assert done["suggested_followups"] == persona_agent._ENGINEER_FOLLOWUPS
    answer = "".join(e["text"] for e in events if e["type"] == "chunk")
    assert answer == "Hello world"


def test_stream_persona_message_multi_rule_has_no_rule_id(loader, monkeypatch):
    async def fake_select(message, history=None, context_rule_id=None):
        return {"rule_ids": ["TEST_1", "TEST_2"], "pipelines": [], "custom_ops": [], "needs_new_rule": False}

    monkeypatch.setattr(persona_agent, "_select_targets", fake_select)
    _patch_stream(monkeypatch)

    events = _parse_events(_collect(
        persona_agent.stream_persona_message("story", "pm")
    ))
    done = events[-1]
    assert done["rule_id"] is None
    assert done["suggested_followups"] == persona_agent._PM_FOLLOWUPS


def test_stream_persona_message_graceful_fallback_on_llm_error(loader, monkeypatch):
    async def fake_select(message, history=None, context_rule_id=None):
        return {"rule_ids": [], "pipelines": [], "custom_ops": [], "needs_new_rule": False}

    monkeypatch.setattr(persona_agent, "_select_targets", fake_select)
    _patch_stream(monkeypatch, error=True)

    events = _parse_events(_collect(
        persona_agent.stream_persona_message("story", "engineer")
    ))
    types = [e["type"] for e in events]
    assert "chunk" in types
    assert types[-1] == "done"
    assert events[-1]["rule_id"] is None
    assert events[-1]["suggested_followups"] == []


# ── data_loader.get_custom_op_source (real module) ─────────────────────────────


def _load_real_data_loader():
    spec = importlib.util.spec_from_file_location(
        "_real_data_loader", BACKEND_DIR / "data_loader.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


real_dl = _load_real_data_loader()


def test_get_custom_op_source_unknown_key_returns_empty(monkeypatch):
    real_dl.get_custom_op_source.cache_clear()
    monkeypatch.setattr(real_dl, "get_custom_operations", lambda: {})
    assert real_dl.get_custom_op_source("does.not.exist") == ""


def test_get_custom_op_source_truncates_long_files(tmp_path, monkeypatch):
    real_dl.get_custom_op_source.cache_clear()
    (tmp_path / "op.py").write_text("x" * 7000, encoding="utf-8")
    monkeypatch.setattr(real_dl, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        real_dl, "get_custom_operations",
        lambda: {"op": {"class_name": "Op", "docstring": "", "file": "op.py"}},
    )
    src = real_dl.get_custom_op_source("op")
    assert src.endswith("# … truncated")
    assert len(src) <= 6000 + len("\n# … truncated")


def test_get_custom_op_source_reads_full_short_file(tmp_path, monkeypatch):
    real_dl.get_custom_op_source.cache_clear()
    (tmp_path / "short.py").write_text("class Op:\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(real_dl, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        real_dl, "get_custom_operations",
        lambda: {"short": {"class_name": "Op", "docstring": "", "file": "short.py"}},
    )
    assert real_dl.get_custom_op_source("short") == "class Op:\n    pass\n"
