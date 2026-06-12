"""
STEP 1 — Schema Discovery
Run: python discover_schema.py
Must be run before any other module is written.
"""

import os
import sys
import pandas as pd
import yaml
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def discover_excel(path: Path) -> None:
    print(f"\n{'='*70}")
    print(f"[SCHEMA] {path.name}")
    print(f"{'='*70}")

    xl = pd.ExcelFile(path)
    print(f"  Sheets: {xl.sheet_names}")

    for sheet in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet, nrows=5)
        print(f"\n  --- Sheet: '{sheet}' ---")
        print(f"  Shape (full): checking full sheet...")
        df_full = pd.read_excel(path, sheet_name=sheet)
        print(f"  Shape: {df_full.shape[0]} rows × {df_full.shape[1]} cols")
        print(f"\n  [SCHEMA] {path.name} [{sheet}] columns ({len(df_full.columns)}):")
        for i, col in enumerate(df_full.columns):
            print(f"    [{i:03d}] {repr(col)}")
        print(f"\n  [SCHEMA] {path.name} [{sheet}] sample (first 3 rows):")
        print(df_full.head(3).to_string(max_colwidth=60))


def discover_yaml(golden_dir: Path) -> None:
    print(f"\n{'='*70}")
    print(f"[SCHEMA] golden/ YAML files")
    print(f"{'='*70}")

    yaml_files = sorted(golden_dir.glob("*.yaml"))
    print(f"  Found {len(yaml_files)} YAML files\n")

    for yf in yaml_files[:10]:  # print first 10 in detail
        with open(yf, "r", encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError as e:
                print(f"  [ERROR] {yf.name}: {e}")
                continue

        if data is None:
            print(f"  [SCHEMA] {yf.name}: EMPTY FILE")
            continue

        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        print(f"  [SCHEMA] {yf.name} top-level keys: {keys}")

        # Drill into nested structure
        if isinstance(data, dict):
            for k, v in list(data.items())[:5]:
                if isinstance(v, dict):
                    print(f"    '{k}' sub-keys: {list(v.keys())}")
                elif isinstance(v, list) and v and isinstance(v[0], dict):
                    print(f"    '{k}' (list[0]) keys: {list(v[0].keys())}")
                else:
                    preview = str(v)[:120]
                    print(f"    '{k}': {preview}")

    if len(yaml_files) > 10:
        print(f"\n  ... and {len(yaml_files) - 10} more YAML files (keys summary below):")
        all_keys: set = set()
        for yf in yaml_files[10:]:
            with open(yf, "r", encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        all_keys.update(data.keys())
                except Exception:
                    pass
        print(f"  All unique top-level keys across remaining files: {sorted(all_keys)}")


def main() -> None:
    print("=" * 70)
    print("SCHEMA DISCOVERY — Step 1")
    print("=" * 70)

    rules_path = DATA_DIR / "dim_rules_inventory.xlsx"
    sap_path = DATA_DIR / "MDG Official Z1_AI_AGENT.xlsx"
    golden_dir = DATA_DIR / "golden"

    if not rules_path.exists():
        print(f"[ERROR] Missing: {rules_path}")
        sys.exit(1)
    if not sap_path.exists():
        print(f"[ERROR] Missing: {sap_path}")
        sys.exit(1)

    discover_excel(rules_path)
    discover_excel(sap_path)
    discover_yaml(golden_dir)

    print("\n" + "=" * 70)
    print("SCHEMA DISCOVERY COMPLETE — Review output above before proceeding.")
    print("=" * 70)


if __name__ == "__main__":
    main()
