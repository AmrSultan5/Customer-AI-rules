"""
STEP 6 — LineageService
Extracts lineage metadata from the rules dataframe and YAML pipelines.
Lineage columns are optional — never crashes if absent.
"""

import logging
from functools import lru_cache

log = logging.getLogger(__name__)

LINEAGE_CANDIDATES = [
    "source", "system", "owner", "workflow", "steps", "lineage",
    "datamart_or_reference_table_used", "dependent_on", "rule_responsibility",
    "module", "group",
]


def _detect_lineage_cols(cols: list[str]) -> list[str]:
    found = [c for c in cols if any(cand in c for cand in LINEAGE_CANDIDATES)]
    if found:
        log.info("[INFO] LineageService: lineage columns found: %s", found)
    else:
        log.warning("[WARNING] LineageService: no lineage columns found — returning empty lineage")
    return found


@lru_cache(maxsize=1)
def _build_lineage_index() -> dict[str, dict]:
    from data_loader import get_rules

    rules = get_rules()
    lineage_cols = _detect_lineage_cols(list(rules.columns))
    index: dict[str, dict] = {}

    for _, row in rules.iterrows():
        rid = str(row.get("rule_id", "")).strip()
        if not rid:
            continue

        lin: dict = {}
        for col in lineage_cols:
            val = row.get(col)
            if val is not None and str(val).strip() not in ("", "nan", "None"):
                lin[col] = str(val).strip()

        # Attach YAML pipeline sources if there's a matching YAML
        from data_loader import find_yaml_for_rule
        yaml_match = find_yaml_for_rule(rid)
        if yaml_match:
            from data_loader import get_custom_operations
            custom_ops_index = get_custom_operations()

            lin["yaml_reference"] = yaml_match.get("yaml_file", "")
            lin["pipeline_name"] = yaml_match.get("name", "")
            lin["pipeline_sources"] = yaml_match.get("sources", [])
            sibling_ids = [
                r for r in yaml_match.get("rule_ids_in_yaml", [])
                if r.upper() != rid.upper()
            ]
            if sibling_ids:
                lin["sibling_rules"] = sibling_ids
            lin["workflow_steps"] = [
                op.get("name", op.get("kind", ""))
                for op in yaml_match.get("operations", [])
                if isinstance(op, dict)
            ]
            # Resolve custom operation descriptions for richer lineage context
            custom_op_descs: list[str] = []
            for key in yaml_match.get("custom_ops_used", []):
                meta = custom_ops_index.get(key)
                if meta:
                    label = meta["class_name"]
                    doc = meta.get("docstring", "")
                    custom_op_descs.append(f"{label}: {doc}" if doc else label)
            if custom_op_descs:
                lin["custom_operations"] = custom_op_descs

        index[rid] = lin

    return index



def get_lineage(rule_id: str) -> dict:
    index = _build_lineage_index()
    result = index.get(rule_id.strip(), {})
    if not result:
        log.warning("[WARNING] LineageService: no lineage found for rule_id '%s'", rule_id)
    return result


if __name__ == "__main__":
    from data_loader import get_rules

    rules = get_rules()
    sample_id = rules["rule_id"].iloc[0]
    print(f"Lineage for '{sample_id}':")
    print(get_lineage(sample_id))
