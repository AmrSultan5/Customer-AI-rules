"""
Structural validation for pasted pipeline YAML — no LLM involved.

Engineers paste an edited golden/ pipeline file back before committing; this
checks it parses, has the expected transform shape, and that everything it
references (custom operations, rule IDs, source tables) resolves against the
real repository indexes.

Errors  → the file is broken or references something that does not exist.
Warnings → suspicious but possibly intentional (e.g. a new rule ID that still
           needs an inventory row).
"""

import logging
import re

import yaml

log = logging.getLogger(__name__)

# Largest real golden/ pipeline is ~318K chars — cap holds ~2x headroom.
MAX_YAML_CHARS = 600_000

# Mirror data_loader's constants — duplicated so this module works against the
# raw pasted text without import-time coupling (data_loader is consulted lazily
# only for the known-name indexes).
_RULE_EXPR_RE = re.compile(
    r"expression:\s+[\"']?'(RC[A-Z]+_\d+(?:[._]\d+)?)'[\"']?",
    re.IGNORECASE,
)
_CUSTOM_OP_PREFIX = "governance_data_quality_processes.custom_operations."


def _norm_rule_id(rule_id: str) -> str:
    return rule_id.upper().replace(".", "_")


def validate_pipeline_yaml(text: str) -> dict:
    """Validate a pasted pipeline YAML document.

    Returns {"valid": bool, "errors": [str], "warnings": [str], "summary": {...}}.
    valid is False only on errors; warnings alone keep valid True.
    """
    from data_loader import get_rules, get_yaml_rules, get_custom_operations

    errors: list[str] = []
    warnings: list[str] = []
    summary = {
        "transform_name": "",
        "operation_count": 0,
        "rule_ids": [],
        "custom_ops": [],
        "sources": [],
    }

    text = (text or "").strip()
    if not text:
        return {"valid": False, "errors": ["The pasted text is empty."], "warnings": [], "summary": summary}
    if len(text) > MAX_YAML_CHARS:
        return {
            "valid": False,
            "errors": [f"YAML exceeds the maximum size of {MAX_YAML_CHARS} characters."],
            "warnings": [],
            "summary": summary,
        }

    # ── Parse ─────────────────────────────────────────────────────────────────
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        problem = getattr(exc, "problem", None) or "invalid YAML"
        if mark is not None:
            errors.append(f"YAML syntax error at line {mark.line + 1}, column {mark.column + 1}: {problem}")
        else:
            errors.append(f"YAML syntax error: {problem}")
        return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}

    # ── Structure ─────────────────────────────────────────────────────────────
    if not isinstance(data, dict):
        errors.append("Top level must be a YAML mapping (got a "
                      f"{type(data).__name__ if data is not None else 'empty document'}).")
        return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}

    transform = data.get("transform")
    if not isinstance(transform, dict):
        errors.append("Missing required top-level `transform` mapping — every golden/ pipeline file has one.")
        return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}

    name = transform.get("name")
    if not name or not isinstance(name, str):
        warnings.append("`transform.name` is missing — pipelines are indexed by this name.")
    else:
        summary["transform_name"] = name

    operations = transform.get("operations")
    if operations is None:
        errors.append("`transform.operations` is missing.")
        return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}
    if not isinstance(operations, list):
        errors.append("`transform.operations` must be a list of operation mappings.")
        return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}
    if not operations:
        warnings.append("`transform.operations` is empty — the pipeline does nothing.")
    summary["operation_count"] = len(operations)

    sources: list[str] = []
    custom_op_keys: list[str] = []
    for i, op in enumerate(operations, start=1):
        if not isinstance(op, dict):
            errors.append(f"Operation #{i} is not a mapping (got {type(op).__name__}).")
            continue
        kind = op.get("kind")
        if not kind or not isinstance(kind, str):
            errors.append(f"Operation #{i} has no `kind`.")
            continue
        # Real pipelines use both shapes: a mapping (read_dataio, select, …) or
        # a list of mappings (join, add with multiple param sets).
        params = op.get("params")
        if params is not None and not isinstance(params, (dict, list)):
            errors.append(f"Operation #{i} (`{kind}`): `params` must be a mapping or a list of mappings.")
            continue
        if isinstance(params, list) and any(not isinstance(p, dict) for p in params):
            errors.append(f"Operation #{i} (`{kind}`): every entry in the `params` list must be a mapping.")
            continue
        params = params if isinstance(params, dict) else {}
        if kind == "read_dataio":
            src = params.get("object_name")
            if not src:
                warnings.append(f"Operation #{i} (`read_dataio`) has no `params.object_name`.")
            elif src not in sources:
                sources.append(src)
        if _CUSTOM_OP_PREFIX in kind:
            fragment = kind[kind.index(_CUSTOM_OP_PREFIX) + len(_CUSTOM_OP_PREFIX):]
            parts = fragment.rsplit(".", 1)
            module_key = parts[0] if len(parts) == 2 else fragment
            if module_key and module_key not in custom_op_keys:
                custom_op_keys.append(module_key)

    summary["sources"] = sources
    summary["custom_ops"] = custom_op_keys

    # ── Cross-check against the repository indexes ────────────────────────────
    try:
        known_ops = set(get_custom_operations().keys())
        for key in custom_op_keys:
            if key not in known_ops:
                errors.append(
                    f"Custom operation `{key}` does not exist under custom_operations/ — "
                    "check the module path in the `kind` value."
                )
    except Exception as exc:
        log.warning("[yaml-validation] custom op index unavailable: %s", type(exc).__name__)

    rule_ids = list(dict.fromkeys(m.upper() for m in _RULE_EXPR_RE.findall(text)))
    summary["rule_ids"] = rule_ids
    try:
        known_rules = {_norm_rule_id(str(r)) for r in get_rules()["rule_id"]}
        for rid in rule_ids:
            if _norm_rule_id(rid) not in known_rules:
                warnings.append(
                    f"Rule ID {rid} is not in the active inventory — if this is a new rule, "
                    "add its row to data/dim_rules_inventory.xlsx."
                )
    except Exception as exc:
        log.warning("[yaml-validation] rule inventory unavailable: %s", type(exc).__name__)

    try:
        known_sources: set[str] = set()
        for data_entry in get_yaml_rules().values():
            known_sources.update(data_entry.get("sources", []))
        for src in sources:
            if known_sources and src not in known_sources:
                warnings.append(
                    f"Source table `{src}` is not read by any existing pipeline — "
                    "double-check the object name."
                )
    except Exception as exc:
        log.warning("[yaml-validation] pipeline index unavailable: %s", type(exc).__name__)

    return {"valid": not errors, "errors": errors, "warnings": warnings, "summary": summary}
