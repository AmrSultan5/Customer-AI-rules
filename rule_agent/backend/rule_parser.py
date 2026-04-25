"""
STEP 4 — RuleParser
Extracts SAP field references from rule logic expressions.
"""

import re
import logging
from functools import lru_cache

log = logging.getLogger(__name__)

# Matches TABLE-FIELD patterns like KNA1-KUNNR, VBAK-VBELN, etc.
_SAP_FIELD_RE = re.compile(r"\b([A-Z][A-Z0-9]{0,9}-[A-Z][A-Z0-9_]{0,19})\b")


@lru_cache(maxsize=512)
def extract_sap_fields(rule_logic: str) -> list[str]:
    """Return deduplicated SAP field strings found in rule_logic."""
    if not rule_logic or not isinstance(rule_logic, str):
        return []
    matches = _SAP_FIELD_RE.findall(rule_logic)
    seen: dict[str, None] = {}
    for m in matches:
        seen[m] = None
    return list(seen.keys())


if __name__ == "__main__":
    from data_loader import get_rules

    rules = get_rules()
    sample_logic = rules["rule_logic"].dropna().iloc[0]
    print(f"Sample logic:\n  {sample_logic[:200]}")
    fields = extract_sap_fields(str(sample_logic))
    print(f"Extracted SAP fields: {fields}")
