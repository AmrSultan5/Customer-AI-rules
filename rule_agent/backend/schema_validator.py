"""
STEP 3 — SchemaValidator
Validates that all required logical fields can be resolved.
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)

REQUIRED_RULES_COLS = ["rule_id", "domain", "is_active", "rule_logic"]
REQUIRED_SAP_COLS = ["sap_table", "sap_field", "field_label"]


def validate_rules(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_RULES_COLS if c not in df.columns]
    if missing:
        for m in missing:
            log.error("[ERROR] Cannot find a column mapping to '%s' in dim_rules_inventory.xlsx", m)
        raise ValueError(f"Missing required columns in rules dataframe: {missing}")
    log.info("[INFO] SchemaValidator: rules dataframe OK — all required columns present.")


def validate_sap(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_SAP_COLS if c not in df.columns]
    if missing:
        for m in missing:
            log.error("[ERROR] Cannot find a column mapping to '%s' in MDG Official Z11.xlsx", m)
        raise ValueError(f"Missing required columns in SAP dataframe: {missing}")
    log.info("[INFO] SchemaValidator: SAP dataframe OK — all required columns present.")


if __name__ == "__main__":
    from data_loader import get_rules, get_sap_map

    rules = get_rules()
    sap = get_sap_map()
    validate_rules(rules)
    validate_sap(sap)
    print("Validation passed cleanly.")
