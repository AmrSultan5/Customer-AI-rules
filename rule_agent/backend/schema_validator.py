"""
STEP 3 — SchemaValidator
Validates that all required logical fields can be resolved.

Phase 2: required columns can now come from a KB descriptor's field_map
(validate_against_descriptor) instead of only the hardcoded module constants
below. The constants remain the default fallback so existing callers
(data_loader.reload_all with no descriptor, main.py's startup validation,
and anything importing REQUIRED_RULES_COLS/REQUIRED_SAP_COLS directly) are
unaffected, and customer_sap's descriptor declares the exact same required
set (kb/customer_sap.yaml field_map.required_rules/required_sap), so
behavior for the current dataset is unchanged either way.
"""

import logging

import pandas as pd

from kb._schema import KBDescriptor

log = logging.getLogger(__name__)

REQUIRED_RULES_COLS = ["rule_id", "domain", "is_active", "rule_logic"]
REQUIRED_SAP_COLS = ["sap_table", "sap_field", "field_label"]


def validate_rules(df: pd.DataFrame, required: list[str] | None = None) -> None:
    cols = required if required else REQUIRED_RULES_COLS
    missing = [c for c in cols if c not in df.columns]
    if missing:
        for m in missing:
            log.error("[ERROR] Cannot find a column mapping to '%s' in dim_rules_inventory.xlsx", m)
        raise ValueError(f"Missing required columns in rules dataframe: {missing}")
    log.info("[INFO] SchemaValidator: rules dataframe OK — all required columns present.")


def validate_sap(df: pd.DataFrame, required: list[str] | None = None) -> None:
    cols = required if required else REQUIRED_SAP_COLS
    missing = [c for c in cols if c not in df.columns]
    if missing:
        for m in missing:
            log.error("[ERROR] Cannot find a column mapping to '%s' in MDG Official Z1_AI_AGENT.xlsx", m)
        raise ValueError(f"Missing required columns in SAP dataframe: {missing}")
    log.info("[INFO] SchemaValidator: SAP dataframe OK — all required columns present.")


def validate_against_descriptor(
    rules_df: pd.DataFrame, sap_df: pd.DataFrame, descriptor: KBDescriptor
) -> None:
    """Validate both dataframes using the descriptor's field_map-declared
    required columns, falling back to the legacy constants above when the
    descriptor leaves required_rules/required_sap empty."""
    fm = descriptor.field_map
    validate_rules(rules_df, fm.required_rules or None)
    validate_sap(sap_df, fm.required_sap or None)


if __name__ == "__main__":
    from data_loader import get_rules, get_sap_map

    rules = get_rules()
    sap = get_sap_map()
    validate_rules(rules)
    validate_sap(sap)
    print("Validation passed cleanly.")
