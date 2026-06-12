"""
Deterministic impact analysis for rules — no LLM involved.

Walks the real indexes (rule inventory, YAML pipelines, custom operations) to
answer "what does changing this rule touch?":
  - rules that depend on it (reverse of dependent_on / rule_logic references)
  - rules it references
  - pipelines that evaluate it, and the rules co-located in those pipelines
  - custom operations those pipelines use, and which other pipelines share them
  - rules checking the same table/column
  - the concrete file paths a change would touch

Used by the /rules/impact/{rule_id} endpoint and fed into the persona-mode
context (persona_agent Stage 2) so engineer answers list downstream effects.
"""

import logging
import re

log = logging.getLogger(__name__)

_MAX_SAME_TARGET = 10
_MAX_CO_LOCATED = 10

# Mirrors data_loader._RULE_REF_RE — rule IDs as they appear in dependent_on / logic text.
_RULE_REF_RE = re.compile(r"\b(RC[A-Z]+_\d+(?:[._]\d+)?)\b", re.IGNORECASE)


def _safe(val) -> str:
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


def _norm(rule_id: str) -> str:
    """RCCOMP_12.1 and RCCOMP_12_1 compare equal."""
    return rule_id.upper().replace(".", "_")


def _posix(path: str) -> str:
    return str(path).replace("\\", "/")


def get_rule_impact(rule_id: str) -> dict | None:
    """Return the full impact graph for a rule, or None if the rule is unknown."""
    from data_loader import get_rules, get_yaml_rules, get_custom_operations, get_referenced_rules

    rules = get_rules()
    match = rules[rules["rule_id"].str.upper() == rule_id.upper()]
    if match.empty:
        return None

    row = match.iloc[0]
    rid = str(row["rule_id"]).upper()
    rid_norm = _norm(rid)
    table = _safe(row.get("table_name_checked", ""))
    column = _safe(row.get("column_name_checked", ""))

    # ── Rules this rule references (forward) ─────────────────────────────────
    referenced = [
        {
            "rule_id": ref["rule_id"],
            "source": ref["source"],
            "active": ref.get("active", False),
            "description": _safe(ref.get("rule_description", ""))[:120],
        }
        for ref in get_referenced_rules(rid)
    ]

    # ── Rules that reference this rule (reverse) ─────────────────────────────
    dependents: list[dict] = []
    scan_cols = [c for c in ("dependent_on", "rule_logic") if c in rules.columns]
    for _, other in rules.iterrows():
        other_id = str(other.get("rule_id", "")).upper()
        if not other_id or other_id == rid:
            continue
        for col in scan_cols:
            text = _safe(other.get(col, ""))
            if not text:
                continue
            if any(_norm(m.group(1)) == rid_norm for m in _RULE_REF_RE.finditer(text)):
                dependents.append({
                    "rule_id": other_id,
                    "via": col,
                    "description": _safe(other.get("rule_description", ""))[:120],
                })
                break

    # ── Pipelines that evaluate this rule ────────────────────────────────────
    yamls = get_yaml_rules()
    pipelines: list[dict] = []
    for name, data in yamls.items():
        ids_in_yaml = data.get("rule_ids_in_yaml", [])
        if not any(_norm(eid) == rid_norm for eid in ids_in_yaml):
            continue
        co_located = [eid for eid in ids_in_yaml if _norm(eid) != rid_norm]
        pipelines.append({
            "name": name,
            "yaml_file": f"golden/{_posix(data['yaml_file'])}",
            "sources": data.get("sources", []),
            "custom_ops_used": data.get("custom_ops_used", []),
            "co_located_rules": co_located[:_MAX_CO_LOCATED],
        })

    # ── Custom operations used by those pipelines (+ who else uses them) ─────
    ops_index = get_custom_operations()
    op_keys: list[str] = []
    for p in pipelines:
        for key in p["custom_ops_used"]:
            if key not in op_keys:
                op_keys.append(key)

    custom_ops: list[dict] = []
    for key in op_keys:
        meta = ops_index.get(key)
        if not meta:
            continue
        used_by = [
            name for name, data in yamls.items()
            if key in data.get("custom_ops_used", [])
            and name not in {p["name"] for p in pipelines}
        ]
        custom_ops.append({
            "module_key": key,
            "class_name": meta["class_name"],
            "file": f"data/{_posix(meta['file'])}",
            "also_used_by_pipelines": used_by,
        })

    # ── Rules checking the same table/column ─────────────────────────────────
    same_target: list[dict] = []
    if table and "table_name_checked" in rules.columns:
        for _, other in rules.iterrows():
            other_id = str(other.get("rule_id", "")).upper()
            if not other_id or other_id == rid:
                continue
            if _safe(other.get("table_name_checked", "")).lower() != table.lower():
                continue
            other_col = _safe(other.get("column_name_checked", ""))
            if column and other_col.lower() != column.lower():
                continue
            same_target.append({
                "rule_id": other_id,
                "column": other_col,
                "description": _safe(other.get("rule_description", ""))[:120],
            })
            if len(same_target) >= _MAX_SAME_TARGET:
                break

    # ── Files a change would touch ────────────────────────────────────────────
    files = ["data/dim_rules_inventory.xlsx"]
    files += [p["yaml_file"] for p in pipelines]
    files += [op["file"] for op in custom_ops]

    return {
        "rule": {
            "rule_id": rid,
            "description": _safe(row.get("rule_description", ""))[:200],
            "table_checked": table,
            "column_checked": column,
        },
        "referenced_rules": referenced,
        "dependent_rules": dependents,
        "pipelines": pipelines,
        "custom_ops": custom_ops,
        "same_target_rules": same_target,
        "files_to_touch": list(dict.fromkeys(files)),
    }


def format_impact_for_context(rule_id: str, max_chars: int = 700) -> str:
    """Compact one-block impact summary for inclusion in persona LLM context.

    Returns "" when the rule is unknown or nothing beyond the rule itself is
    affected, so callers can append unconditionally.
    """
    try:
        impact = get_rule_impact(rule_id)
    except Exception as exc:
        log.warning("[impact] format_impact_for_context failed for %s: %s", rule_id, type(exc).__name__)
        return ""
    if not impact:
        return ""

    lines: list[str] = []
    if impact["dependent_rules"]:
        ids = ", ".join(d["rule_id"] for d in impact["dependent_rules"][:8])
        lines.append(f"Rules depending on {rule_id.upper()} (must be re-checked if it changes): {ids}")
    if impact["referenced_rules"]:
        ids = ", ".join(r["rule_id"] for r in impact["referenced_rules"][:8])
        lines.append(f"Rules referenced by {rule_id.upper()}: {ids}")
    for p in impact["pipelines"]:
        if p["co_located_rules"]:
            ids = ", ".join(p["co_located_rules"][:8])
            lines.append(f"Other rules evaluated in {p['yaml_file']}: {ids}")
    if impact["custom_ops"]:
        for op in impact["custom_ops"]:
            extra = ""
            if op["also_used_by_pipelines"]:
                extra = f" (also used by pipelines: {', '.join(op['also_used_by_pipelines'][:5])})"
            lines.append(f"Custom operation involved: {op['file']}{extra}")
    if impact["same_target_rules"]:
        ids = ", ".join(s["rule_id"] for s in impact["same_target_rules"][:8])
        lines.append(f"Rules checking the same table/column: {ids}")

    if not lines:
        return ""
    return ("IMPACT ANALYSIS (deterministic, from the repository indexes):\n" + "\n".join(lines))[:max_chars]
