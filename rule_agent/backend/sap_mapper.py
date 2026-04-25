"""
STEP 5 — SAPMapper
Maps SAP TABLE-FIELD strings to business descriptions.
Uses Sheet1 of MDG Official Z11.xlsx.
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

        if not field or field in ("NAN", "NONE", ""):
            continue

        entry = {
            "field": f"{table}-{field}" if table else field,
            "business_name": label or field,
            "description": desc[:200] if desc else "",
            "table": table,
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

    if key in lkp:
        return lkp[key]

    # Try field-only fallback (after the dash)
    if "-" in key:
        field_only = key.split("-", 1)[1]
        if field_only in lkp:
            return lkp[field_only]

    return {
        "field": field_str,
        "business_name": "Unknown field",
        "description": "",
        "table": key.split("-")[0] if "-" in key else "",
    }


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
