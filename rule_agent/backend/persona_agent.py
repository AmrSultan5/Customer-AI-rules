"""
Persona agent — Data Engineer & Project Manager chat modes.

Three-stage flow (243 YAML pipelines + 228 rules cannot fit in one prompt):

  Stage 1  _select_targets        one LLM call over compact catalogs (+ rule-ID
                                  regex pre-seed) → which rules / pipelines /
                                  custom ops the story is about
  Stage 2  _load_persona_context  deterministic, char-budgeted context assembly
                                  from disk/cache — no LLM
  Stage 3  stream_persona_message persona system prompt + call_openai_stream

All LLM calls use the async client — never block the event loop.
"""

import json
import logging
import re
from collections.abc import AsyncGenerator

log = logging.getLogger(__name__)

# Mirrors chat_agent._RULE_ID_RE — duplicated so this module has no import-time
# dependency on chat_agent (which lazy-imports this module for dispatch).
_RULE_ID_RE = re.compile(r"\b([A-Z]{2,8}_\d+(?:\.\d+)?)\b", re.IGNORECASE)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# Stage 2 character budgets
_TOTAL_CONTEXT_BUDGET = 28_000
_RULE_YAML_SECTION_CAP = 4_000
_PIPELINE_RAW_CAP = 3_000
_CUSTOM_OP_SOURCE_CAP = 4_000
_EXCEL_FIELD_CAP = 400

_MAX_RULES = 5
_MAX_PIPELINES = 3
_MAX_CUSTOM_OPS = 4

_INVENTORY_NOTE = (
    "Rule inventory file: data/dim_rules_inventory.xlsx (sheet `dim_rules_inventory`). "
    "One row per rule, keyed by `rule_id`. Column names are normalized snake_case "
    "(e.g. rule_description, quality_category, table_name_checked, column_name_checked, "
    "severity, rule_logic, is_active, domain, dependent_on). New or changed rules must "
    "also be reflected in this file."
)

_ENGINEER_FOLLOWUPS = [
    "Show the full YAML after the change",
    "Generate only the PySpark test",
    "Which other rules does this impact?",
]

_PM_FOLLOWUPS = [
    "Make the acceptance criteria more specific",
    "Add edge cases to testing notes",
    "Shorten this story",
]

_STATUS_SELECTING = "Identifying affected rules and pipelines…"
_STATUS_READING = "Reading pipeline definitions…"

# ── System prompts ─────────────────────────────────────────────────────────────

_TARGET_SELECTION_SYSTEM = """\
You are a retrieval router for a data quality rule repository.
The repository contains rule pipelines (YAML files under golden/), custom Python
operations (under custom_operations/), and a rule inventory Excel file.

Given the catalogs and the user's text, select the items most relevant to the change
or issue being described.

Respond with ONLY a JSON object in this exact shape:
{
  "rule_ids": ["..."],      // up to 5 rule IDs, copied VERBATIM from the rule catalog
  "pipelines": ["..."],     // up to 3 pipeline names, copied VERBATIM from the pipeline catalog
  "custom_ops": ["..."],    // up to 4 custom op module keys, copied VERBATIM from the pipeline catalog's custom_ops field
  "needs_new_rule": false,  // true only if NO existing rule covers what the user describes
  "rationale": "one short sentence"
}

Hard rules:
- Never invent names. Every entry must appear verbatim in the catalogs provided.
- If the user explicitly mentions rule IDs, always include them.
- Prefer fewer, more relevant selections over many loose matches.
- If nothing matches, return empty lists and set needs_new_rule accordingly.\
"""

_ENGINEER_SYSTEM = """\
You are a senior data engineer assistant for a data quality rule repository
(YAML pipelines under golden/, custom Python operations under custom_operations/,
rule inventory in data/dim_rules_inventory.xlsx, running on Databricks).

The user usually pastes a user story or change request.

If the message is NOT a user story or change request — a greeting, a general question
about what you can do, or anything else off-topic — do NOT use the structure below.
Reply briefly and conversationally: say hi, explain in 2-3 sentences that you turn
user stories / change requests into concrete file-edit instructions for the rule
repository, and invite the user to paste a story or name a rule ID.

When the message IS a user story or change request, use ONLY the repository context
provided in the message and answer with exactly this structure:

## Summary
One short paragraph: what the change is and which rules it affects.

## Files to change
A bullet list of the exact file paths that need edits.

Then ONE section per file — never mix edits from two files in the same section, and
never repeat a file path in the list or sections. Each file section must follow exactly
this template:

### <exact/file/path>
One or two sentences saying which block(s)/step(s) in THIS file to edit and how
(e.g. "delete this expression and replace it with…", "add this `add` operation
after the step named `<name>`…"). Then:

**Before:**
```yaml
<the actual current content quoted verbatim from the provided context>
```

**After:**
```yaml
<the full edited content>
```

(Use ```python fences instead when the file is Python.) If one file needs edits in
several separate blocks, give a separate labeled Before/After pair per block. The
Before/After pair is mandatory for every code file. For the rule inventory Excel,
identify the exact row by rule_id and show the affected column(s) as
**Before:** <current value> / **After:** <new value> — write out the actual new value,
never "update to reflect the new logic".

## Databricks validation
How to verify the change. Provide BOTH:
1. A `%sql` cell querying the real source tables named in the context.
2. A PySpark cell (python) doing the equivalent check.
Use only table names that appear in the provided context.

Hard rules:
- NEVER invent file paths, table names, column names, or rule IDs that are not in the
  provided context. If something needed is missing from the context, say so explicitly.
- Always write rule IDs in bold like **RCACCU_383.6** (the UI makes them clickable).
- If the story is ambiguous or could map to multiple unrelated changes, ask ONE
  clarifying question instead of guessing.
- If the context indicates no existing rule covers the story, say a new rule is needed,
  propose which pipeline file it belongs in, and show the YAML block to add plus the
  inventory row to insert.\
"""

_PM_SYSTEM = """\
You are an assistant that helps project managers write agile user stories for a data
quality rule repository (YAML pipelines under golden/, custom Python operations under
custom_operations/, rule inventory in data/dim_rules_inventory.xlsx, running on Databricks).

The user usually describes an issue or need in plain language.

If the message is NOT an issue or need description — a greeting, a general question
about what you can do, or anything else off-topic — do NOT use the structure below.
Reply briefly and conversationally: say hi, explain in 2-3 sentences that you turn
plain-language issues into complete agile user stories for the rule repository, and
invite the user to describe the issue or need.

When the message IS an issue or need description, use ONLY the repository context
provided in the message and write a complete user story with exactly this structure:

## Title
Short, action-oriented.

**As a** <role>, **I want** <capability>, **so that** <business value>.

## Description
2-4 sentences of business context: what is wrong or missing today and the desired outcome.
Plain business language — no code.

## Acceptance Criteria
Given/When/Then bullets, each independently verifiable.

## Technical Notes
The affected rule IDs in bold (e.g. **RCACCU_383.6**), the exact file paths to change
(golden/... YAML, custom_operations/... Python, the inventory Excel), and any custom
operations involved. This is the only section where technical detail belongs.

## Testing Notes
How the team should verify the change (which source tables / conditions to check in
Databricks), in plain language.

If the context contains a SIZING SIGNAL line, repeat it verbatim as the last line of
the Technical Notes section.

Hard rules:
- NEVER invent rule IDs or file paths that are not in the provided context. If no
  existing rule covers the issue, state that a new rule is needed and name the most
  plausible pipeline file from the context.
- If the conversation history contains an earlier draft of this story, refine that
  draft according to the user's latest request instead of writing a new one.
- If the issue description is too vague to write acceptance criteria, ask ONE
  clarifying question instead of guessing.\
"""

# ── Catalogs (Stage 1 input) ───────────────────────────────────────────────────


def build_pipeline_catalog() -> str:
    """One line per YAML pipeline: name | path | sources | rules | custom_ops."""
    from data_loader import get_yaml_rules

    lines: list[str] = []
    for name, data in get_yaml_rules().items():
        parts = [name, f"golden/{_posix(data['yaml_file'])}"]
        if data.get("sources"):
            parts.append("sources: " + ",".join(data["sources"][:5]))
        if data.get("rule_ids_in_yaml"):
            parts.append("rules: " + ",".join(data["rule_ids_in_yaml"][:10]))
        if data.get("custom_ops_used"):
            parts.append("custom_ops: " + ",".join(data["custom_ops_used"][:4]))
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def build_rule_catalog() -> str:
    """One line per rule: rule_id | category | table | desc[:100]."""
    from data_loader import get_rules

    lines: list[str] = []
    for _, row in get_rules().iterrows():
        rid = _safe(row.get("rule_id", ""))
        if not rid:
            continue
        cat = _safe(row.get("quality_category", ""))
        tbl = _safe(row.get("table_name_checked", ""))
        desc = _safe(row.get("rule_description", ""))[:100]
        lines.append(f"{rid} | {cat} | {tbl} | {desc}")
    return "\n".join(lines)


def _safe(val) -> str:
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


def _posix(path: str) -> str:
    """Normalize Windows backslashes so cited file paths match the real repo layout."""
    return str(path).replace("\\", "/")


# ── Stage 1: target selection ──────────────────────────────────────────────────


def _regex_rule_ids(message: str, history: list[dict] | None, context_rule_id: str | None) -> list[str]:
    """Rule IDs explicitly mentioned in the message / recent history, validated against the inventory."""
    from data_loader import get_rules

    texts = [message]
    for turn in (history or [])[-2:]:
        texts.append(str(turn.get("content", "")))

    found: list[str] = []
    for text in texts:
        for m in _RULE_ID_RE.finditer(text):
            rid = m.group(1).upper()
            if rid not in found:
                found.append(rid)
    if context_rule_id and context_rule_id.upper() not in found:
        found.append(context_rule_id.upper())

    known = {str(r).upper() for r in get_rules()["rule_id"]}
    return [rid for rid in found if rid in known]


def _fallback_selection(seeded_ids: list[str]) -> dict:
    """Deterministic selection when the LLM selector fails: regex hits + their owning pipelines."""
    from data_loader import find_yaml_for_rule

    pipelines: list[str] = []
    for rid in seeded_ids:
        match = find_yaml_for_rule(rid)
        if match and match["name"] not in pipelines:
            pipelines.append(match["name"])
    return {
        "rule_ids": seeded_ids[:_MAX_RULES],
        "pipelines": pipelines[:_MAX_PIPELINES],
        "custom_ops": [],
        "needs_new_rule": False,
        "rationale": "fallback: explicit rule IDs only",
    }


async def _select_targets(
    message: str,
    history: list[dict] | None = None,
    context_rule_id: str | None = None,
) -> dict:
    """Stage 1 — one LLM call over compact catalogs; post-validated against real indexes."""
    from data_loader import get_rules, get_yaml_rules, get_custom_operations
    from explanation_engine import call_openai_async

    seeded_ids = _regex_rule_ids(message, history, context_rule_id)

    history_block = ""
    if history:
        recent = history[-4:]
        history_block = "\n\nRECENT CONVERSATION:\n" + "\n".join(
            f"{t.get('role', '?')}: {str(t.get('content', ''))[:300]}" for t in recent
        )

    user_msg = (
        f"RULE CATALOG:\n{build_rule_catalog()}\n\n"
        f"PIPELINE CATALOG:\n{build_pipeline_catalog()}\n\n"
        f"Rule IDs explicitly mentioned by the user (always include): {seeded_ids or 'none'}\n"
        f"Active rule open in the user's panel: {context_rule_id or 'none'}"
        f"{history_block}\n\n"
        f"USER TEXT:\n{message}"
    )

    try:
        raw = await call_openai_async(
            _TARGET_SELECTION_SYSTEM, user_msg, max_tokens=400, json_mode=True,
        )
        parsed = json.loads(_FENCE_RE.sub("", raw).strip())
        if not isinstance(parsed, dict):
            raise ValueError("selector did not return a JSON object")
    except Exception as exc:
        log.warning("[PERSONA] Target selection failed (%s) — using regex fallback", type(exc).__name__)
        return _fallback_selection(seeded_ids)

    # Post-validate: drop anything not present in the real indexes (grounding step).
    known_rules = {str(r).upper() for r in get_rules()["rule_id"]}
    known_pipelines = set(get_yaml_rules().keys())
    known_ops = set(get_custom_operations().keys())

    rule_ids = list(seeded_ids)
    for rid in parsed.get("rule_ids") or []:
        rid_up = str(rid).upper()
        if rid_up in known_rules and rid_up not in rule_ids:
            rule_ids.append(rid_up)

    pipelines = [
        str(p) for p in (parsed.get("pipelines") or [])
        if str(p) in known_pipelines
    ]
    custom_ops = [
        str(c) for c in (parsed.get("custom_ops") or [])
        if str(c) in known_ops
    ]

    selection = {
        "rule_ids": rule_ids[:_MAX_RULES],
        "pipelines": list(dict.fromkeys(pipelines))[:_MAX_PIPELINES],
        "custom_ops": list(dict.fromkeys(custom_ops))[:_MAX_CUSTOM_OPS],
        "needs_new_rule": bool(parsed.get("needs_new_rule", False)),
        "rationale": str(parsed.get("rationale", ""))[:300],
    }
    log.info("[PERSONA] Target selection: %s", selection)
    return selection


# ── Stage 2: deterministic context assembly ────────────────────────────────────


def _step_outline(operations: list) -> str:
    """One line per pipeline operation: index, kind, and its name/object if any."""
    lines: list[str] = []
    for i, op in enumerate(operations, start=1):
        if not isinstance(op, dict):
            continue
        kind = str(op.get("kind", "?"))
        params = op.get("params") if isinstance(op.get("params"), dict) else {}
        label = params.get("name") or params.get("object_name") or ""
        lines.append(f"{i}. {kind}" + (f" | {label}" if label else ""))
    return "\n".join(lines[:60])


def _pipeline_excerpt(data: dict, raw: str, selected_rule_ids: list[str]) -> str:
    """Targeted excerpt of a pipeline YAML, within _PIPELINE_RAW_CAP chars.

    Short files pass through whole. For long files, head-truncation loses the
    later steps, so instead build: a full step outline (every operation, one
    line) + the extracted sections for any selected rules present in the file +
    whatever head content still fits.
    """
    if len(raw) <= _PIPELINE_RAW_CAP:
        return raw
    from data_loader import extract_rule_section_from_yaml

    parts: list[str] = []
    outline = _step_outline(data.get("operations") or [])
    if outline:
        parts.append(f"Step outline ({len(data.get('operations') or [])} operations):\n{outline}")

    raw_upper = raw.upper()
    for rid in selected_rule_ids:
        rid_up = rid.upper()
        if rid_up in raw_upper or rid_up.replace(".", "_") in raw_upper:
            section = extract_rule_section_from_yaml(raw, rid)
            parts.append(f"Section for {rid_up}:\n{section}")

    body = "\n\n".join(parts)[:_PIPELINE_RAW_CAP]
    if not body:
        return raw[:_PIPELINE_RAW_CAP]
    remaining = _PIPELINE_RAW_CAP - len(body)
    if remaining > 400:
        body += "\n\nFile head:\n" + raw[:remaining]
    return body[:_PIPELINE_RAW_CAP]


def _complexity_hint(selection: dict) -> str:
    """Deterministic sizing line for PM stories, derived from the Stage 1 selection."""
    n_rules = len(selection.get("rule_ids", []))
    n_pipes = len(selection.get("pipelines", []))
    n_ops = len(selection.get("custom_ops", []))
    needs_new = bool(selection.get("needs_new_rule"))

    if n_rules + n_pipes + n_ops == 0 and not needs_new:
        return ""

    score = n_rules + n_pipes + 2 * n_ops + (2 if needs_new else 0)
    size = "small" if score <= 2 else ("medium" if score <= 5 else "large")

    touches: list[str] = []
    if n_rules:
        touches.append(f"{n_rules} rule{'s' if n_rules != 1 else ''}")
    if n_pipes:
        touches.append(f"{n_pipes} pipeline file{'s' if n_pipes != 1 else ''}")
    if n_ops:
        touches.append(f"{n_ops} custom Python operation{'s' if n_ops != 1 else ''}")
    if needs_new:
        touches.append("a new rule (pipeline YAML + inventory row)")

    hint = f"Sizing signal: touches {', '.join(touches)} — {size} change."
    if n_ops:
        hint += " Custom Python operations are shared across pipelines — coordinate before changing them."
    return hint


def _load_persona_context(selection: dict, mode: str = "engineer") -> str:
    """Assemble grounded repository context for the selected targets. No LLM calls."""
    from data_loader import (
        get_rules, get_yaml_rules, get_yaml_raw, get_custom_operations,
        get_custom_op_source, find_yaml_for_rule, extract_rule_section_from_yaml,
    )
    from impact_service import format_impact_for_context

    rules = get_rules()
    yamls = get_yaml_rules()
    ops_index = get_custom_operations()

    parts: list[str] = [_INVENTORY_NOTE]
    used = len(_INVENTORY_NOTE)
    source_tables: list[str] = []
    rule_owned_pipelines: set[str] = set()

    def _add(block: str) -> bool:
        nonlocal used
        if not block or used + len(block) > _TOTAL_CONTEXT_BUDGET:
            return False
        parts.append(block)
        used += len(block)
        return True

    # ── Selected rules: Excel row + owning YAML section ──────────────────────
    for rid in selection.get("rule_ids", []):
        match = rules[rules["rule_id"].str.upper() == rid.upper()]
        if match.empty:
            continue
        row = match.iloc[0]
        field_lines = []
        for col in rules.columns:
            val = _safe(row.get(col, ""))
            if val:
                field_lines.append(f"  {col}: {val[:_EXCEL_FIELD_CAP]}")
        block = f"=== RULE {rid} (inventory row) ===\n" + "\n".join(field_lines)

        yaml_match = find_yaml_for_rule(rid)
        if yaml_match:
            rule_owned_pipelines.add(yaml_match["name"])
            for src in yaml_match.get("sources", []):
                if src not in source_tables:
                    source_tables.append(src)
            yaml_text = get_yaml_raw(yaml_match["yaml_file"])
            if yaml_text:
                section = extract_rule_section_from_yaml(yaml_text, rid)[:_RULE_YAML_SECTION_CAP]
                block += (
                    f"\nOwning pipeline file: golden/{_posix(yaml_match['yaml_file'])}"
                    f"\nYAML section for {rid}:\n{section}"
                )
        impact = format_impact_for_context(rid)
        if impact:
            block += "\n" + impact
        _add(block)

    # ── Selected pipelines (deduped against rule-owned) ──────────────────────
    for name in selection.get("pipelines", []):
        if name in rule_owned_pipelines:
            continue
        data = yamls.get(name)
        if not data:
            continue
        for src in data.get("sources", []):
            if src not in source_tables:
                source_tables.append(src)
        raw = _pipeline_excerpt(
            data, get_yaml_raw(data["yaml_file"]), selection.get("rule_ids", []),
        )
        block = (
            f"=== PIPELINE {name} ===\n"
            f"File: golden/{_posix(data['yaml_file'])}\n"
            f"Rules evaluated: {', '.join(data.get('rule_ids_in_yaml', [])[:10]) or 'none detected'}\n"
            f"Custom ops used: {', '.join(data.get('custom_ops_used', [])) or 'none'}\n"
            f"YAML content (excerpt):\n{raw}"
        )
        _add(block)

    # ── Selected custom operations ────────────────────────────────────────────
    for key in selection.get("custom_ops", []):
        meta = ops_index.get(key)
        if not meta:
            continue
        source = get_custom_op_source(key)[:_CUSTOM_OP_SOURCE_CAP]
        block = (
            f"=== CUSTOM OPERATION {meta['class_name']} ===\n"
            f"File: {_posix(meta['file'])}\n"
            f"Docstring: {meta.get('docstring', '') or 'none'}\n"
            f"Source:\n{source}"
        )
        _add(block)

    # ── Databricks source tables (grounds SQL/PySpark snippets) ──────────────
    if source_tables:
        _add(
            "Databricks source tables available for validation queries: "
            + ", ".join(source_tables[:10])
        )

    if selection.get("needs_new_rule"):
        _add(
            "NOTE: No existing rule fully covers this request — a NEW rule is likely "
            "needed. Propose it inside the most relevant pipeline file above and "
            "include the inventory row to add."
        )

    if len(parts) == 1:
        _add(
            "NOTE: No specific rules, pipelines, or custom operations were matched to "
            "this request. If the message is a greeting or general question, respond "
            "conversationally and explain what you can help with. If it is a real "
            "change request, ask the user for more detail (a rule ID, pipeline name, "
            "or the specific check involved) before proposing concrete file changes."
        )
    elif mode == "pm":
        hint = _complexity_hint(selection)
        if hint:
            _add(f"SIZING SIGNAL (repeat verbatim at the end of Technical Notes): {hint}")

    return "\n\n".join(parts)


# ── Stage 3: orchestrator ──────────────────────────────────────────────────────


async def stream_persona_message(
    message: str,
    mode: str,
    context_rule_id: str | None = None,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """Stream an engineer/pm persona response as SSE events.

    Event types (same shapes as chat_agent.stream_message, plus `status`):
      {"type":"status","text":"..."}  — transient progress while retrieval runs
      {"type":"chunk","text":"..."}   — answer text chunks
      {"type":"done","rule_id":...,"suggested_followups":[...]}
    """
    from explanation_engine import call_openai_stream

    def _sse(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    message = message.strip()
    is_engineer = mode == "engineer"
    system = _ENGINEER_SYSTEM if is_engineer else _PM_SYSTEM
    max_tokens = 2500 if is_engineer else 1500
    followups = _ENGINEER_FOLLOWUPS if is_engineer else _PM_FOLLOWUPS

    yield _sse({"type": "status", "text": _STATUS_SELECTING})

    try:
        selection = await _select_targets(message, history=history, context_rule_id=context_rule_id)
        yield _sse({"type": "status", "text": _STATUS_READING})
        context = _load_persona_context(selection, mode=mode)

        label = "USER STORY" if is_engineer else "USER REQUEST"
        user_msg = f"REPOSITORY CONTEXT:\n{context}\n\n{label}:\n{message}"

        async for chunk_text in call_openai_stream(
            system, user_msg, max_tokens=max_tokens, history=history,
        ):
            yield _sse({"type": "chunk", "text": chunk_text})

        rule_ids = selection.get("rule_ids", [])
        rule_id = rule_ids[0] if len(rule_ids) == 1 else None
        yield _sse({"type": "done", "rule_id": rule_id, "suggested_followups": followups})
    except Exception as e:
        log.error("[ERROR] stream_persona_message failed: %s", type(e).__name__)
        yield _sse({
            "type": "chunk",
            "text": "I couldn't process that request right now. Please try again.",
        })
        yield _sse({"type": "done", "rule_id": None, "suggested_followups": []})
