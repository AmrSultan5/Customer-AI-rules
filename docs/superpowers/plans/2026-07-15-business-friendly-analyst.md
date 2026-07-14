# Business-Friendly Analyst Answer Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every analyst-mode answer lead with plain business language while keeping technical identifiers visible but secondary, and add a grounded "Why it matters" line to rule explanations.

**Architecture:** The deterministic lookup answers (sap_table / sap_column / fields / lineage) are currently duplicated in `handle_message` (sync) and `stream_message` (SSE) inside `backend/chat_agent.py`. We extract shared pure formatter functions and wire both paths to them. A deterministic impact digest (severity + counts from `impact_service.get_rule_impact`) is appended to the explanation LLM prompt so the new "Why it matters" line can't hallucinate. Every new lookup degrades to today's exact output on any failure.

**Tech Stack:** Python 3.12 / FastAPI backend, pandas, pytest. LLM calls go through `explanation_engine.py` (Anthropic SDK). Tests mock heavy modules via `backend/tests/conftest.py` (`sys.modules` stubs).

**Spec:** `docs/superpowers/specs/2026-07-14-business-friendly-analyst-design.md`

---

## Context for workers (read first)

- **Working directory for all commands:** repo root. Backend code: `rule_agent/backend/`. Run tests from `rule_agent/backend/`: `python -m pytest tests/ -v`.
- `rule_agent/backend/tests/conftest.py` replaces `data_loader`, `sap_mapper`, `lineage_service`, `explanation_engine`, `chat_agent` etc. in `sys.modules` with MagicMocks. Test catalog: rules `TEST_1` / `TEST_2` on table `KNA1`, columns `KUNNR` / `NAME1`, severities 1 / 2.
- `rule_agent/backend/tests/test_chat_routing.py` shows the pattern for testing the REAL `chat_agent` module: load it via `importlib.util.spec_from_file_location` under a different name; its lazy (inside-function) imports still resolve to the conftest mocks.
- `impact_service` is NOT stubbed by conftest — tests must inject a fake via `monkeypatch.setitem(sys.modules, "impact_service", fake)`.
- All new tests for this plan go in ONE new file: `rule_agent/backend/tests/test_business_friendly.py` (created in Task 1, extended in later tasks).
- Commit after every task. Commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

### Test file boilerplate (Task 1 creates this file with this exact header)

```python
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
```

---

### Task 1: Table & column business-name formatters

**Files:**
- Modify: `rule_agent/backend/chat_agent.py` (new dict + 2 formatters after `_SEVERITY_MAP` at line 68; replace intent blocks in `handle_message` ~line 973 and `stream_message` ~line 802)
- Test: `rule_agent/backend/tests/test_business_friendly.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `rule_agent/backend/tests/test_business_friendly.py` with the boilerplate header above, then append:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `rule_agent/backend/`): `python -m pytest tests/test_business_friendly.py -v`
Expected: FAIL — `AttributeError: module 'chat_agent_business' has no attribute '_format_sap_table_answer'`

- [ ] **Step 3: Implement the dict and both formatters**

In `rule_agent/backend/chat_agent.py`, directly after `_SEVERITY_MAP = {...}` (line 68), add:

```python
# Business names for SAP tables that appear in the rule inventory. Lookup
# misses fall back to the raw technical answer format, so this list only
# needs the tables business users actually ask about.
_TABLE_BUSINESS_NAMES = {
    "KNA1": "customer master — general data",
    "KNB1": "customer master — company code data",
    "KNB5": "customer master — dunning data",
    "KNVV": "customer master — sales area data",
    "KNVP": "customer master — partner functions",
    "KNVA": "customer master — unloading points",
    "KNVH": "customer hierarchy",
    "KNVI": "customer master — tax indicators",
    "ADRC": "central address data",
    "ADR2": "telephone numbers",
    "ADR3": "fax numbers",
    "ADR6": "email addresses",
    "BUT000": "business partner — general data",
    "BUT050": "business partner relationships",
    "BUT051": "business partner contact persons",
    "BUT0BK": "business partner bank details",
    "BUT0IS": "business partner industry sectors",
    "CVI_CUST_LINK": "customer / business-partner link",
    "DFKKBPTAXNUM": "business partner tax numbers",
    "UKMBP_CMS": "credit management profile",
    "UKMBP_CMS_SGM": "credit management segment",
    "LFA1": "vendor master — general data",
    "LFB1": "vendor master — company code data",
    "LFM1": "vendor master — purchasing data",
    "MARA": "material master — general data",
    "MARC": "material master — plant data",
    "MAKT": "material descriptions",
    "MVKE": "material master — sales data",
    "MBEW": "material valuation",
    "MARM": "material units of measure",
    "MLAN": "material tax classifications",
    "MLGN": "material master — warehouse data",
    "SKA1": "G/L account master — chart of accounts",
    "SKAT": "G/L account descriptions",
    "SKB1": "G/L account master — company code",
    "CSKS": "cost center master",
    "CSKB": "cost element master",
    "CEPC": "profit center master",
    "ANLA": "asset master",
}


def _format_sap_table_answer(rule_id: str, table: str) -> str:
    """Plain-language answer for the sap_table intent; falls back to the
    technical format for tables without a business name."""
    if not table:
        return f"No SAP table information available for rule {rule_id}."
    biz = _TABLE_BUSINESS_NAMES.get(table.strip().upper())
    if biz:
        return f"Rule **{rule_id}** checks the **{biz}** table (SAP name: `{table}`)."
    return f"The SAP table checked by rule **{rule_id}** is: `{table}`"


def _format_sap_column_answer(rule_id: str, table: str, col: str) -> str:
    """Plain-language answer for the sap_column intent; falls back to the
    technical format when no business name is known."""
    if not col:
        return f"No SAP column information available for rule {rule_id}."
    try:
        from sap_mapper import lookup_sap_field
        key = f"{table}-{col}" if table else col
        biz = lookup_sap_field(key).get("business_name", "")
    except Exception:
        biz = ""
    if biz and biz != "Unknown field" and biz.upper() != col.upper():
        return f"Rule **{rule_id}** checks the **{biz}** field (SAP name: `{col}`)."
    return f"The SAP column checked by rule **{rule_id}** is: `{col}`"
```

- [ ] **Step 4: Wire both call sites**

In `handle_message` (~line 973), replace the `sap_table` and `sap_column` blocks:

```python
    elif intent == "sap_table":
        response = _format_sap_table_answer(rule_id, _safe(row.get("table_name_checked", "")))

    elif intent == "sap_column":
        response = _format_sap_column_answer(
            rule_id,
            _safe(row.get("table_name_checked", "")),
            _safe(row.get("column_name_checked", "")),
        )
```

In `stream_message` (~line 802), replace only the `response = (...)` expression inside the `sap_table` and `sap_column` blocks with the same two calls (keep the surrounding `async for part in _stream_text(response): ...` / `yield _sse(...)` / `return` lines exactly as they are):

```python
    elif intent == "sap_table":
        response = _format_sap_table_answer(rule_id, _safe(row.get("table_name_checked", "")))
        async for part in _stream_text(response):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id,
                    "suggested_followups": _generate_followups(rule_id, message, response[:200], available)})
        return

    elif intent == "sap_column":
        response = _format_sap_column_answer(
            rule_id,
            _safe(row.get("table_name_checked", "")),
            _safe(row.get("column_name_checked", "")),
        )
        async for part in _stream_text(response):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id,
                    "suggested_followups": _generate_followups(rule_id, message, response[:200], available)})
        return
```

- [ ] **Step 5: Run the new tests — expect all PASS**

Run: `python -m pytest tests/test_business_friendly.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full suite — no regressions**

Run: `python -m pytest tests/ -v`
Expected: all PASS (same pass count as before this task, plus the new tests).

- [ ] **Step 7: Commit**

```bash
git add rule_agent/backend/chat_agent.py rule_agent/backend/tests/test_business_friendly.py
git commit -m "feat(analyst): business-friendly table/column lookup answers"
```

---

### Task 2: Fields-intent formatter (business name first)

**Files:**
- Modify: `rule_agent/backend/chat_agent.py` (new formatter next to the Task-1 formatters; wire `fields` intent in both `handle_message` ~line 995 and `stream_message` ~line 833)
- Test: `rule_agent/backend/tests/test_business_friendly.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `test_business_friendly.py`:

```python
# ── Task 2: fields formatter ──────────────────────────────────────────────────


def test_fields_answer_business_name_first(monkeypatch):
    monkeypatch.setattr(
        sys.modules["rule_parser"], "extract_sap_fields", lambda logic: ["KNA1-KUNNR"],
    )
    monkeypatch.setattr(
        sys.modules["sap_mapper"], "lookup_sap_field",
        lambda f: {"field": "KNA1-KUNNR", "business_name": "Customer Number"},
    )
    out = chat_agent._format_fields_answer("TEST_1", "KUNNR IS NOT NULL")
    assert "**Customer Number**" in out
    assert "KNA1-KUNNR" in out
    # business name comes before the SAP identifier
    assert out.index("Customer Number") < out.index("KNA1-KUNNR")


def test_fields_answer_unknown_field_shows_raw(monkeypatch):
    monkeypatch.setattr(
        sys.modules["rule_parser"], "extract_sap_fields", lambda logic: ["KNA1-XYZ99"],
    )
    monkeypatch.setattr(
        sys.modules["sap_mapper"], "lookup_sap_field",
        lambda f: {"field": "KNA1-XYZ99", "business_name": "Unknown field"},
    )
    out = chat_agent._format_fields_answer("TEST_1", "XYZ99 > 0")
    assert "`KNA1-XYZ99`" in out


def test_fields_answer_none_detected(monkeypatch):
    monkeypatch.setattr(
        sys.modules["rule_parser"], "extract_sap_fields", lambda logic: [],
    )
    out = chat_agent._format_fields_answer("TEST_1", "")
    assert "none detected" in out


def test_both_paths_use_shared_fields_formatter():
    assert "_format_fields_answer" in inspect.getsource(chat_agent.handle_message)
    assert "_format_fields_answer" in inspect.getsource(chat_agent.stream_message)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_business_friendly.py -v -k fields`
Expected: FAIL — no attribute `_format_fields_answer`.

- [ ] **Step 3: Implement** — add after `_format_sap_column_answer` in `chat_agent.py`:

```python
def _format_fields_answer(rule_id: str, logic: str) -> str:
    """Plain-language answer for the fields intent — business names first,
    SAP identifiers in parentheses."""
    from rule_parser import extract_sap_fields
    from sap_mapper import lookup_sap_field
    raw_fields = extract_sap_fields(logic)
    names: list[str] = []
    for f in (lookup_sap_field(rf) for rf in raw_fields):
        bn = f.get("business_name", "")
        if bn and bn != "Unknown field":
            names.append(f"**{bn}** (SAP field: {f['field']})")
        else:
            names.append(f"`{f['field']}`")
    if not names:
        return f"Rule {rule_id} references these fields: none detected."
    return f"Rule **{rule_id}** looks at these fields: " + ", ".join(names) + "."
```

- [ ] **Step 4: Wire both call sites**

`handle_message` `fields` block (~line 995) becomes:

```python
    elif intent == "fields":
        response = _format_fields_answer(rule_id, logic)
```

Then delete the two now-unused lazy imports at the top of `handle_message` (lines ~947-948): `from rule_parser import extract_sap_fields` and `from sap_mapper import lookup_sap_field`. (Verified: nothing else in `handle_message` uses them — the explain branch does its own imports via `_build_rule_context`.)

`stream_message` `fields` block (~line 833): replace the three lines computing `raw_fields` / `mapped` / `names` and the `response = (...)` with:

```python
    elif intent == "fields":
        response = _format_fields_answer(rule_id, logic)
        async for part in _stream_text(response):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id,
                    "suggested_followups": _generate_followups(rule_id, message, response[:200], available)})
        return
```

- [ ] **Step 5: Run new tests — PASS**: `python -m pytest tests/test_business_friendly.py -v`
- [ ] **Step 6: Full suite — no regressions**: `python -m pytest tests/ -v`
- [ ] **Step 7: Commit**

```bash
git add rule_agent/backend/chat_agent.py rule_agent/backend/tests/test_business_friendly.py
git commit -m "feat(analyst): business-name-first fields answers"
```

---

### Task 3: Lineage/workflow markdown formatter

**Files:**
- Modify: `rule_agent/backend/chat_agent.py` (new formatter; wire `lineage`/`workflow` intent in `handle_message` ~line 1004 and `stream_message` ~line 845)
- Test: `rule_agent/backend/tests/test_business_friendly.py` (append)

- [ ] **Step 1: Write the failing tests** — append:

```python
# ── Task 3: lineage formatter ─────────────────────────────────────────────────

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
```

- [ ] **Step 2: Run to verify FAIL**: `python -m pytest tests/test_business_friendly.py -v -k lineage`

- [ ] **Step 3: Implement** — add after `_format_fields_answer`:

```python
def _format_lineage_answer(rule_id: str, lin: dict) -> str:
    """Markdown-bulleted lineage answer — business labels first, technical
    identifiers kept but secondary."""
    lines: list[str] = []
    responsibility = lin.get("rule_responsibility", "")
    module = lin.get("module", "")
    grp = lin.get("group", "")
    datamarts = lin.get("datamart_or_reference_table_used", "")
    sources = lin.get("pipeline_sources", [])
    steps = lin.get("workflow_steps", [])
    custom_ops = lin.get("custom_operations", [])
    siblings = lin.get("sibling_rules", [])

    if responsibility:
        lines.append(f"- **Owned by:** {responsibility}")
    if module or grp:
        area = " / ".join(p for p in (module, grp) if p)
        lines.append(f"- **Business area:** {area}")
    if datamarts:
        dm_list = [d.strip() for d in datamarts.replace("\n", ",").split(",") if d.strip()]
        lines.append(f"- **Data comes from:** {', '.join(dm_list[:5])}")
    if sources:
        lines.append(f"- **Technical sources:** {', '.join(sources[:5])}")
    if steps:
        lines.append(f"- **How it runs:** {' → '.join(steps[:6])}")
    if custom_ops:
        lines.append(f"- **Custom checks involved:** {'; '.join(custom_ops[:5])}")
    if siblings:
        shown = ", ".join(siblings[:10])
        more = f" (+{len(siblings) - 10} more)" if len(siblings) > 10 else ""
        plural = "rule" if len(siblings) == 1 else "rules"
        pipeline = lin.get("pipeline_name", "")
        via = f" in `{pipeline}`" if pipeline else ""
        lines.append(f"- **Runs alongside {len(siblings)} related {plural}{via}:** {shown}{more}")

    if not lines:
        return f"No lineage information found for rule {rule_id}."
    return (f"**Where rule {rule_id}'s data comes from and how it runs:**\n\n"
            + "\n".join(lines))
```

- [ ] **Step 4: Wire both call sites**

`handle_message` (~line 1004): replace the whole `elif intent in ("lineage", "workflow"):` block body with:

```python
    elif intent in ("lineage", "workflow"):
        response = _format_lineage_answer(rule_id, get_lineage(rule_id))
```

`stream_message` (~line 845): replace the block body the same way, keeping the stream/yield/return tail:

```python
    elif intent in ("lineage", "workflow"):
        response = _format_lineage_answer(rule_id, get_lineage(rule_id))
        async for part in _stream_text(response):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id,
                    "suggested_followups": _generate_followups(rule_id, message, response[:200], available)})
        return
```

(`get_lineage` is already lazily imported in both functions — keep those imports.)

- [ ] **Step 5: Run new tests — PASS**: `python -m pytest tests/test_business_friendly.py -v`
- [ ] **Step 6: Full suite — no regressions**: `python -m pytest tests/ -v`
- [ ] **Step 7: Commit**

```bash
git add rule_agent/backend/chat_agent.py rule_agent/backend/tests/test_business_friendly.py
git commit -m "feat(analyst): readable markdown lineage answers"
```

---

### Task 4: "Why it matters" — impact digest + explanation prompt

**Files:**
- Modify: `rule_agent/backend/chat_agent.py` (new `_impact_digest` helper; wire into `handle_message` explain branch ~line 1041 and `stream_message` explain path ~line 889)
- Modify: `rule_agent/backend/explanation_engine.py` (`_SYSTEM_PROMPT` line 34; `explain_rule` line 148)
- Test: `rule_agent/backend/tests/test_business_friendly.py` (append)

- [ ] **Step 1: Write the failing tests** — append:

```python
# ── Task 4: impact digest + Why-it-matters prompt ─────────────────────────────


def test_impact_digest_includes_severity_and_counts(monkeypatch):
    fake = MagicMock()
    fake.get_rule_impact.return_value = {
        "dependent_rules": [{"rule_id": "A"}, {"rule_id": "B"}],
        "pipelines": [{"name": "p1"}],
        "same_target_rules": [],
    }
    monkeypatch.setitem(sys.modules, "impact_service", fake)
    out = chat_agent._impact_digest("TEST_1", {"severity": "2"})
    assert "High" in out
    assert "2 other rule(s) depend" in out
    assert "1 pipeline(s)" in out


def test_impact_digest_failure_returns_empty(monkeypatch):
    fake = MagicMock()
    fake.get_rule_impact.side_effect = RuntimeError("boom")
    monkeypatch.setitem(sys.modules, "impact_service", fake)
    assert chat_agent._impact_digest("TEST_1", {"severity": "1"}) == ""


def test_handle_message_explain_passes_digest(monkeypatch):
    monkeypatch.setattr(chat_agent, "_classify_intent_llm", lambda m, r: "explain")
    monkeypatch.setattr(chat_agent, "_generate_followups", lambda *a, **k: [])
    monkeypatch.setattr(chat_agent, "_impact_digest",
                        lambda rid, row: "severity: High; 2 other rule(s) depend on it")
    fake_explain = MagicMock(return_value="Explanation.")
    monkeypatch.setattr(sys.modules["explanation_engine"], "explain_rule", fake_explain)
    result = chat_agent.handle_message("Explain TEST_1")
    assert result["response"].startswith("Explanation.")
    kwargs = fake_explain.call_args.kwargs
    assert kwargs.get("impact_digest") == "severity: High; 2 other rule(s) depend on it"


def test_system_prompt_requires_why_it_matters():
    sys.modules.setdefault("analytics", MagicMock())
    spec = importlib.util.spec_from_file_location(
        "explanation_engine_real", os.path.join(_BACKEND_DIR, "explanation_engine.py")
    )
    ee = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ee)
    assert "Why it matters" in ee._SYSTEM_PROMPT
    # explain_rule accepts the new parameter
    import inspect as _inspect
    assert "impact_digest" in _inspect.signature(ee.explain_rule).parameters
```

NOTE for the worker: `test_system_prompt_requires_why_it_matters` loads the real `explanation_engine` (its `anthropic` / `httpx` imports are installed; `analytics` may already be mocked or importable — the `setdefault` covers both). If this test errors for an unrelated import reason, report it — do not silently weaken the test.

- [ ] **Step 2: Run to verify FAIL**: `python -m pytest tests/test_business_friendly.py -v -k "impact or why"`
Expected: FAIL — no attribute `_impact_digest`; "Why it matters" not in prompt.

- [ ] **Step 3: Implement `_impact_digest`** — add after `_format_lineage_answer` in `chat_agent.py`:

```python
def _impact_digest(rule_id: str, row) -> str:
    """One-line deterministic impact summary fed to the explanation prompt so
    the 'Why it matters' line is grounded in real data. '' on any failure —
    the explanation then behaves exactly as before."""
    try:
        parts: list[str] = []
        sev = _safe(row.get("severity", ""))
        if sev:
            parts.append(f"severity: {_SEVERITY_MAP.get(str(sev), sev)}")
        from impact_service import get_rule_impact
        impact = get_rule_impact(rule_id) or {}
        dependents = impact.get("dependent_rules", [])
        if dependents:
            parts.append(f"{len(dependents)} other rule(s) depend on this one")
        pipelines = impact.get("pipelines", [])
        if pipelines:
            parts.append(f"runs in {len(pipelines)} pipeline(s)")
        same_target = impact.get("same_target_rules", [])
        if same_target:
            parts.append(f"{len(same_target)} other rule(s) check the same table/column")
        return "; ".join(parts)
    except Exception as exc:
        log.warning("[IMPACT] digest failed for %s: %s", rule_id, exc)
        return ""
```

- [ ] **Step 4: Extend `_SYSTEM_PROMPT`** in `explanation_engine.py` (line 34) — replace the whole assignment with:

```python
_SYSTEM_PROMPT = (
    "You are a business analyst. Explain the following data rule in plain "
    "English for a non-technical business user. Use business terminology. "
    "No code. No SAP field names. No jargon. "
    "Tailor depth to complexity — use 2-3 sentences for simple rules, "
    "and a fuller explanation for rules with multiple conditions, dependencies, or pipeline steps. "
    "If the rule logic is unclear or the question is ambiguous, ask the user to clarify. "
    "If specific information is not available in the rule provided, say so and suggest "
    "what related details the user could ask about instead (e.g. description, severity, SAP table, lineage). "
    "End every explanation with a final line starting with '**Why it matters:**' — "
    "one or two sentences on the business consequence if this rule is violated, "
    "grounded ONLY in the rule logic and any impact data provided. If impact data "
    "is provided, reflect its severity and dependency counts; never invent "
    "consequences the provided context does not support."
)
```

- [ ] **Step 5: Extend `explain_rule`** in `explanation_engine.py` (line 148) — new signature and user_msg:

```python
def explain_rule(rule_logic: str, sap_context: str = "", tier: str = "standard",
                 impact_digest: str = "") -> str:
    """Translate rule_logic into plain English via Claude."""
    if not rule_logic or rule_logic.strip() in ("", "nan", "None"):
        return "No technical rule definition available for this rule."

    user_msg = f"Rule logic:\n{rule_logic}"
    if sap_context:
        user_msg += f"\n\nField reference (do not use these names in the explanation):\n{sap_context}"
    if impact_digest:
        user_msg += f"\n\nImpact data (deterministic — use only this for the 'Why it matters' line):\n{impact_digest}"
```

(The rest of the function body is unchanged.)

- [ ] **Step 6: Wire both explain call sites in `chat_agent.py`**

`handle_message` explain/show branch (~line 1045): change

```python
        response = explain_rule(logic, (instr + ctx) if instr else ctx)
```

to

```python
        response = explain_rule(logic, (instr + ctx) if instr else ctx,
                                impact_digest=_impact_digest(rule_id, row))
```

`stream_message` explain path (~line 889): after the existing `user_msg` construction (`user_msg = f"{_instructions_block(extra_context)}Rule logic:\n{logic}"` and the `if ctx:` append), add:

```python
    digest = _impact_digest(rule_id, row)
    if digest:
        user_msg += ("\n\nImpact data (deterministic — use only this for the "
                     f"'Why it matters' line):\n{digest}")
```

- [ ] **Step 7: Run new tests — PASS**: `python -m pytest tests/test_business_friendly.py -v`
- [ ] **Step 8: Full suite — no regressions**: `python -m pytest tests/ -v`
- [ ] **Step 9: Commit**

```bash
git add rule_agent/backend/chat_agent.py rule_agent/backend/explanation_engine.py rule_agent/backend/tests/test_business_friendly.py
git commit -m "feat(analyst): grounded 'Why it matters' line in rule explanations"
```

---

### Task 5: Business-first follow-ups + friendlier fallback copy

**Files:**
- Modify: `rule_agent/backend/chat_agent.py` (`_FOLLOWUPS_SYSTEM` line 516; `_find_rule_by_description` fallback ~line 282)
- Test: `rule_agent/backend/tests/test_business_friendly.py` (append)

- [ ] **Step 1: Write the failing tests** — append:

```python
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
```

- [ ] **Step 2: Run to verify FAIL**: `python -m pytest tests/test_business_friendly.py -v -k "followups_prompt or fallback"`

- [ ] **Step 3: Replace `_FOLLOWUPS_SYSTEM`** (line 516) with:

```python
_FOLLOWUPS_SYSTEM = """\
You are a follow-up question generator for a data quality rule assistant whose
users are mostly business people, not engineers.

Given the user's question and the answer they just received, suggest 2-3 short
follow-up questions they are likely to ask next.

Rules:
- Each suggestion must directly build on the current question or the answer — do not suggest generic questions that could apply to any rule
- Do not repeat the user's current question in any form
- Prefer business-oriented follow-ups: how critical the rule is, what happens if it fails, which business data or process it protects, which related checks exist
- Only suggest technical follow-ups (SAP tables, fields, pipelines) when the user's own question was technical
- Keep each question short (under 12 words) and phrased as a natural follow-up
- Return only a JSON array of 2-3 strings. No other text.\
"""
```

- [ ] **Step 4: Replace the fallback copy** in `_find_rule_by_description` (~line 282):

```python
        return {
            "response": (
                "I couldn't search for that rule right now. You can try again by:\n\n"
                "- **Describing what the rule should check** — e.g. `the rule that makes sure every customer has a postal code`\n"
                "- **Naming the quality area** — e.g. `list all completeness rules`\n"
                "- **Giving a rule ID if you know it** — e.g. `Explain rule RCCOMP_103.1`"
            ),
            "rule_id": None,
            "suggested_followups": [],
        }
```

- [ ] **Step 5: Run new tests — PASS**: `python -m pytest tests/test_business_friendly.py -v`
- [ ] **Step 6: Full suite — no regressions**: `python -m pytest tests/ -v`
- [ ] **Step 7: Commit**

```bash
git add rule_agent/backend/chat_agent.py rule_agent/backend/tests/test_business_friendly.py
git commit -m "feat(analyst): business-first followups and friendlier fallback copy"
```
