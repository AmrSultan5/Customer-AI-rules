"""
STEP 5 — SAPMapper
Maps SAP TABLE-FIELD strings to business descriptions.
Uses Z11_Transposed sheet of MDG Official Z1_AI_AGENT.xlsx.
"""

import logging
from functools import lru_cache

import pandas as pd

log = logging.getLogger(__name__)


def _build_lookup(df: pd.DataFrame) -> dict[str, dict]:
    """Build a dict keyed by 'TABLE-FIELD' (upper). Falls back to FIELD alone."""
    lookup: dict[str, dict] = {}
    for _, row in df.iterrows():
        table = str(row.get("sap_table", "") or "").strip().upper()
        field = str(row.get("sap_field", "") or "").strip().upper()
        label = str(row.get("field_label", "") or "").strip()
        desc = str(row.get("cchbc_field_usage_comments", "") or "").strip()
        validation = str(row.get("mdg_validation_rules", "") or "").strip()
        required = str(row.get("required_optional", "") or "").strip()
        field_format = str(row.get("sap_field_format", "") or "").strip()
        ref_table = str(row.get("reference_table", "") or "").strip()

        if not field or field in ("NAN", "NONE", ""):
            continue

        def _clean(s: str) -> str:
            return "" if s.upper() in ("NAN", "NONE", "") else s

        entry = {
            "field": f"{table}-{field}" if table else field,
            "business_name": label or field,
            "description": desc[:200] if desc else "",
            "table": table,
            "mdg_validation_rules": _clean(validation)[:300],
            "required": _clean(required),
            "field_format": _clean(field_format),
            "reference_table": _clean(ref_table),
        }

        if table:
            key = f"{table}-{field}"
            lookup[key] = entry
        # Also index by field-only for fuzzy fallback
        if field not in lookup:
            lookup[field] = entry

    log.info("[INFO] SAPMapper: built lookup with %d entries", len(lookup))
    return lookup


@lru_cache(maxsize=1)
def _get_lookup() -> dict[str, dict]:
    from data_loader import get_sap_map
    return _build_lookup(get_sap_map())


@lru_cache(maxsize=1024)
def lookup_sap_field(field_str: str) -> dict:
    """Return field metadata for a given TABLE-FIELD string."""
    if not field_str:
        return {"field": "", "business_name": "Unknown field", "description": "", "table": ""}

    lkp = _get_lookup()
    key = field_str.strip().upper()

    entry = lkp.get(key)

    # Try field-only fallback (after the dash)
    if entry is None and "-" in key:
        field_only = key.split("-", 1)[1]
        entry = lkp.get(field_only)

    if entry is None:
        return {
            "field": field_str,
            "business_name": "Unknown field",
            "description": "",
            "table": key.split("-")[0] if "-" in key else "",
            "mdg_validation_rules": "",
            "required": "",
            "field_format": "",
            "reference_table": "",
            "valid_codes": [],
        }

    # Enrich with reference code list if this field has a ref table
    ref_table = entry.get("reference_table", "")
    valid_codes: list[dict] = []
    if ref_table:
        from data_loader import get_reference_codes
        codes = get_reference_codes().get(ref_table, [])
        valid_codes = codes[:20]  # cap at 20 for context size

    return {**entry, "valid_codes": valid_codes}


if __name__ == "__main__":
    from data_loader import get_sap_map

    sap = get_sap_map()
    # Find a real SAP field from the sheet
    real_rows = sap[(sap["sap_table"].notna()) & (sap["sap_field"].notna())]
    if not real_rows.empty:
        r = real_rows.iloc[0]
        real_key = f"{str(r['sap_table']).strip()}-{str(r['sap_field']).strip()}"
        print(f"Real field lookup '{real_key}':")
        print(f"  {lookup_sap_field(real_key)}")

    print(f"\nFake field lookup 'KNA1-FAKE99':")
    print(f"  {lookup_sap_field('KNA1-FAKE99')}")
