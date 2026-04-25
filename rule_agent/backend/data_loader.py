"""
STEP 2 — DataLoader
Loads and normalizes all data sources.
"""

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
RULES_FILE = DATA_DIR / "dim_rules_inventory.xlsx"
SAP_FILE = DATA_DIR / "MDG Official Z11.xlsx"
GOLDEN_DIR = DATA_DIR / "golden"
CUSTOM_OPS_DIR = DATA_DIR / "custom_operations"

# Matches rule IDs embedded as expression literals: expression: "'RCCOMP_12.1'"
_YAML_RULE_EXPR_RE = re.compile(
    r"expression:\s+[\"']?'(RC[A-Z]+_\d+(?:[._]\d+)?)'[\"']?",
    re.IGNORECASE,
)

# Matches class XxxOperation(... BaseOperation ...): then optional docstring
_CLASS_DOC_RE = re.compile(
    r'class\s+(\w+Operation)\s*\([^)]*\):\s*(?:"""(.*?)""")?',
    re.DOTALL,
)

# ---------- helpers ----------------------------------------------------------

def _to_snake(name: str) -> str:
    """Convert any column name to lowercase snake_case."""
    s = str(name).strip()
    s = re.sub(r"[\s\-/\\.()\[\]]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {col: _to_snake(col) for col in df.columns}
    for orig, norm in mapping.items():
        if orig != norm:
            log.info("[INFO] Normalized '%s' → '%s'", orig, norm)
    return df.rename(columns=mapping)


def _find_best_column(df: pd.DataFrame, candidates: list[str], label: str) -> str:
    """Return the first column name that exists (after normalization)."""
    cols = set(df.columns)
    for c in candidates:
        if c in cols:
            log.info("[INFO] Resolved '%s' → column '%s'", label, c)
            return c
    # Fuzzy: pick any column whose name contains any candidate fragment
    for c in candidates:
        for col in cols:
            if c in col or col in c:
                log.info("[INFO] Fuzzy-resolved '%s' → column '%s'", label, col)
                return col
    raise ValueError(
        f"[ERROR] Cannot find a column mapping to '{label}'. "
        f"Available columns: {sorted(cols)}"
    )


# ---------- rules loader -----------------------------------------------------

def load_rules() -> pd.DataFrame:
    log.info("[INFO] Loading rules from %s", RULES_FILE)
    df = pd.read_excel(RULES_FILE, sheet_name="dim_rules_inventory", dtype=str)
    df = _normalize_columns(df)

    log.info("[INFO] Shape after load: %s", df.shape)
    log.info("[INFO] Columns: %s", list(df.columns))

    # Resolve logical fields
    rule_id_col = _find_best_column(
        df,
        ["rule_code", "rule_id", "id", "code"],
        "rule_id",
    )
    domain_col = _find_best_column(
        df,
        ["domain"],
        "domain",
    )
    active_col = _find_best_column(
        df,
        ["is_active", "active", "is_active_flag"],
        "is_active",
    )
    logic_col = _find_best_column(
        df,
        ["technical_definition", "rule_logic", "logic", "definition", "expression"],
        "rule_logic",
    )

    # Standardise column aliases so downstream code uses stable names
    aliases = {
        rule_id_col: "rule_id",
        domain_col: "domain",
        active_col: "is_active",
        logic_col: "rule_logic",
    }
    for src, dst in aliases.items():
        if src != dst:
            df = df.rename(columns={src: dst})

    # Apply mandatory filter: Customer + active
    before = len(df)
    df["is_active"] = pd.to_numeric(df["is_active"], errors="coerce")
    df = df[df["domain"].str.strip().str.casefold() == "customer"]
    df = df[df["is_active"] == 1.0]
    log.info(
        "[INFO] Rows after Customer/is_active=1 filter: %d (dropped %d)",
        len(df),
        before - len(df),
    )

    df = df.reset_index(drop=True)
    return df


# ---------- SAP mapper loader ------------------------------------------------

def load_sap_map() -> pd.DataFrame:
    """Load Sheet1 from Z11 which has SAP Table + SAP Field columns."""
    log.info("[INFO] Loading SAP map from %s", SAP_FILE)
    df = pd.read_excel(SAP_FILE, sheet_name="Sheet1", dtype=str)
    df = _normalize_columns(df)

    log.info("[INFO] SAP sheet shape: %s", df.shape)
    log.info("[INFO] SAP sheet columns: %s", list(df.columns))
    return df


# ---------- YAML loader ------------------------------------------------------

def _extract_fields_from_ops(operations: list[Any]) -> list[str]:
    """Pull column names from 'select' operations inside a YAML pipeline."""
    fields: set[str] = set()
    if not isinstance(operations, list):
        return []
    for op in operations:
        if not isinstance(op, dict):
            continue
        if op.get("kind") == "select":
            cols = op.get("params", {}).get("columns", {})
            if isinstance(cols, dict):
                fields.update(cols.keys())
                fields.update(cols.values())
            elif isinstance(cols, list):
                fields.update(cols)
        # Also grab object_name values (data sources / lineage)
    return [f for f in fields if f]


def _extract_sources_from_ops(operations: list[Any]) -> list[str]:
    sources: list[str] = []
    if not isinstance(operations, list):
        return sources
    for op in operations:
        if not isinstance(op, dict):
            continue
        if op.get("kind") == "read_dataio":
            src = op.get("params", {}).get("object_name")
            if src:
                sources.append(src)
    return sources


def load_yaml_rules() -> dict[str, dict]:
    """Return dict keyed by transform.name → parsed rule metadata."""
    result: dict[str, dict] = {}
    yaml_files = sorted(GOLDEN_DIR.rglob("*.yaml"))
    log.info("[INFO] Found %d YAML files in %s", len(yaml_files), GOLDEN_DIR)

    for yf in yaml_files:
        raw_text = yf.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as e:
            log.warning("[WARNING] Skipping %s: %s", yf.name, e)
            continue

        if not isinstance(data, dict) or "transform" not in data:
            log.warning("[WARNING] Skipping %s: no 'transform' key", yf.name)
            continue

        transform = data["transform"]
        name: str = transform.get("name", yf.stem)
        operations: list = transform.get("operations") or []

        fields_used = _extract_fields_from_ops(operations)
        sources = _extract_sources_from_ops(operations)

        # Extract all rule IDs referenced as expression literals in this YAML
        rule_ids_found = list(dict.fromkeys(
            m.upper() for m in _YAML_RULE_EXPR_RE.findall(raw_text)
        ))

        # Fallback: extract SAP-style fields from any text in the YAML
        yaml_text = str(data)
        sap_fields_regex = re.findall(r"\b([A-Z][A-Z0-9]{1,9}-[A-Z][A-Z0-9_]{1,19})\b", yaml_text)

        result[name] = {
            "yaml_file": str(yf.relative_to(GOLDEN_DIR)),
            "name": name,
            "operations": operations,
            "fields_used": list(dict.fromkeys(fields_used)),
            "sources": sources,
            "sap_fields_in_yaml": list(dict.fromkeys(sap_fields_regex)),
            "custom_ops_used": _extract_custom_ops_from_ops(operations),
            "rule_ids_in_yaml": rule_ids_found,
            "description": f"Data pipeline: {name}",
        }

    log.info("[INFO] Loaded %d YAML transforms", len(result))
    return result


# ---------- yaml raw content -------------------------------------------------

@lru_cache(maxsize=256)
def get_yaml_raw(yaml_filename: str) -> str:
    """Return the raw text of a YAML file from the golden/ directory."""
    path = GOLDEN_DIR / yaml_filename
    if not path.exists():
        log.warning("[WARNING] YAML file not found: %s", path)
        return ""
    return path.read_text(encoding="utf-8")


def extract_rule_section_from_yaml(yaml_text: str, rule_id: str) -> str:
    """
    Extract the block of YAML lines that belong to a specific rule.
    Searches for the rule ID (e.g. RCCOMP_12.1) in comments and expressions,
    then returns that section plus surrounding context lines.
    Falls back to the first 3000 chars if no specific section is found.
    """
    if not yaml_text or not rule_id:
        return yaml_text[:3000] if yaml_text else ""

    # Normalise rule_id variants: RCCOMP_12.1 → rccomp_12.1, rccomp_12_1, etc.
    rid = rule_id.upper()
    rid_underscore = rid.replace(".", "_")   # RCCOMP_12_1
    rid_dot        = rid                      # RCCOMP_12.1
    patterns = [rid_dot, rid_underscore, rid.lower(), rid_underscore.lower()]

    lines = yaml_text.splitlines()
    # Find the first line containing the rule ID
    anchor = -1
    for i, line in enumerate(lines):
        if any(p in line for p in patterns):
            anchor = i
            break

    if anchor == -1:
        # No specific section found — return first 3000 chars
        return yaml_text[:3000]

    # Walk backwards to the nearest comment header (# SELECT / # ADD …)
    start = anchor
    for i in range(anchor, max(anchor - 60, -1), -1):
        if lines[i].startswith("#"):
            start = i
            break

    # Walk forward to the next rule's anchor comment or end of file
    end = min(anchor + 120, len(lines))
    for i in range(anchor + 1, len(lines)):
        if lines[i].startswith("#") and i > anchor + 5:
            # Check if the next comment belongs to a different rule
            next_comment = lines[i].upper()
            if any(p in next_comment for p in patterns):
                continue  # Still same rule, keep going
            end = i
            break

    section = "\n".join(lines[start:end])
    log.info(
        "[INFO] extract_rule_section_from_yaml: found section for %s (lines %d–%d)",
        rule_id, start, end,
    )
    return section


def find_yaml_for_rule(rule_id: str) -> dict | None:
    """
    Return the yaml metadata dict that contains rule_id in its pipeline.
    Priority:
      1. Content match — rule_id appears as an expression literal inside the YAML
      2. Name match — transform name contains the rule_id fragments (fallback)
    """
    yamls = get_yaml_rules()
    rid_upper = rule_id.upper()
    # Normalise dots/underscores for loose comparison: RCCOMP_12.1 == RCCOMP_12_1
    rid_norm = rid_upper.replace(".", "_")

    # 1. Content match: prefer the YAML that explicitly evaluates this rule
    for data in yamls.values():
        for eid in data.get("rule_ids_in_yaml", []):
            if eid.upper() == rid_upper or eid.upper().replace(".", "_") == rid_norm:
                return data

    # 2. Name heuristic fallback
    rid_lower = rule_id.lower().replace("_", "").replace(".", "").replace("-", "")
    for name, data in yamls.items():
        name_norm = name.lower().replace("_", "").replace(".", "").replace("-", "")
        if rid_lower in name_norm or name_norm in rid_lower:
            return data

    parts = [p for p in re.split(r"[_.\-]", rule_id.lower()) if len(p) > 3]
    for name, data in yamls.items():
        if any(p in name.lower() for p in parts):
            return data

    return None


# ---------- custom operations loader -----------------------------------------

def _module_key_from_path(py_file: Path) -> str:
    """Convert a .py path relative to CUSTOM_OPS_DIR to a dotted module key.
    e.g. city_standarization/geocoords_address_conformity.py
         → city_standarization.geocoords_address_conformity
    """
    rel = py_file.relative_to(CUSTOM_OPS_DIR).with_suffix("")
    return str(rel).replace("\\", "/").replace("/", ".")


def load_custom_operations() -> dict[str, dict]:
    """Scan custom_operations/ for Operation classes and extract their docstrings.
    Returns dict keyed by dotted module path fragment, e.g.:
      "city_standarization.geocoords_address_conformity" → {class_name, docstring, file}
    """
    result: dict[str, dict] = {}
    py_files = [
        f for f in CUSTOM_OPS_DIR.rglob("*.py")
        if f.name != "__init__.py"
    ]
    log.info("[INFO] Found %d custom operation source files", len(py_files))

    for py_file in py_files:
        try:
            source = py_file.read_text(encoding="utf-8")
        except Exception as e:
            log.warning("[WARNING] Could not read %s: %s", py_file, e)
            continue

        key = _module_key_from_path(py_file)
        matches = _CLASS_DOC_RE.findall(source)

        # Store the first Operation class found (usually there's only one)
        if matches:
            class_name, raw_doc = matches[0]
            docstring = " ".join(raw_doc.split()).strip() if raw_doc else ""
        else:
            # No Operation class — still index by key so YAML references resolve
            class_name = py_file.stem
            docstring = ""

        result[key] = {
            "class_name": class_name,
            "docstring": docstring,
            "file": str(py_file.relative_to(DATA_DIR)),
        }

    log.info("[INFO] Indexed %d custom operation modules", len(result))
    return result


def _extract_custom_ops_from_ops(operations: list[Any]) -> list[str]:
    """Return module-key strings for any custom operation kind found in a YAML pipeline."""
    custom_ops: list[str] = []
    if not isinstance(operations, list):
        return custom_ops
    prefix = "governance_data_quality_processes.custom_operations."
    for op in operations:
        if not isinstance(op, dict):
            continue
        kind = op.get("kind", "")
        if not isinstance(kind, str) or prefix not in kind:
            continue
        # Strip the prefix and trailing .ClassName to get the module key
        fragment = kind[kind.index(prefix) + len(prefix):]
        parts = fragment.rsplit(".", 1)
        module_key = parts[0] if len(parts) == 2 else fragment
        if module_key and module_key not in custom_ops:
            custom_ops.append(module_key)
    return custom_ops


# ---------- cached entry points ----------------------------------------------

@lru_cache(maxsize=1)
def get_rules() -> pd.DataFrame:
    return load_rules()


@lru_cache(maxsize=1)
def get_sap_map() -> pd.DataFrame:
    return load_sap_map()


@lru_cache(maxsize=1)
def get_yaml_rules() -> dict[str, dict]:
    return load_yaml_rules()


@lru_cache(maxsize=1)
def get_custom_operations() -> dict[str, dict]:
    return load_custom_operations()


# ---------- cross-rule reference resolver ------------------------------------

_RULE_REF_RE = re.compile(r"\b(RC[A-Z]+_\d+(?:[._]\d+)?)\b", re.IGNORECASE)


def get_referenced_rules(rule_id: str) -> list[dict]:
    """Return details of rules referenced by rule_id via dependent_on or rule_logic.

    Each entry: {rule_id, rule_description, rule_logic, table_name_checked,
                 column_name_checked, quality_category, source}
    where source is 'dependent_on' or 'logic'.
    """
    rules = get_rules()
    match = rules[rules["rule_id"].str.upper() == rule_id.upper()]
    if match.empty:
        return []

    row = match.iloc[0]
    rid_upper = rule_id.upper()
    seen: set[str] = set()
    refs: list[dict] = []

    def _collect(text: str, source: str) -> None:
        for m in _RULE_REF_RE.finditer(str(text or "")):
            ref_id = m.group(1).upper()
            if ref_id == rid_upper or ref_id in seen:
                continue
            seen.add(ref_id)
            ref_match = rules[rules["rule_id"].str.upper() == ref_id]
            if ref_match.empty:
                # Reference exists in text but not in active rules
                refs.append({"rule_id": ref_id, "source": source, "active": False})
            else:
                ref_row = ref_match.iloc[0]
                refs.append({
                    "rule_id": ref_id,
                    "rule_description": str(ref_row.get("rule_description", "") or ""),
                    "rule_logic": str(ref_row.get("rule_logic", "") or ""),
                    "table_name_checked": str(ref_row.get("table_name_checked", "") or ""),
                    "column_name_checked": str(ref_row.get("column_name_checked", "") or ""),
                    "quality_category": str(ref_row.get("quality_category", "") or ""),
                    "source": source,
                    "active": True,
                })

    _collect(row.get("dependent_on", ""), "dependent_on")
    _collect(row.get("rule_logic", ""), "logic")
    return refs


# ---------- sanity check -----------------------------------------------------

if __name__ == "__main__":
    rules = get_rules()
    print(f"\nRules shape: {rules.shape}")
    print(f"Columns: {list(rules.columns)}")
    print(f"\nSample rule_id values: {rules['rule_id'].head(5).tolist()}")

    sap = get_sap_map()
    print(f"\nSAP map shape: {sap.shape}")
    print(f"SAP columns: {list(sap.columns)}")

    yamls = get_yaml_rules()
    print(f"\nYAML rules loaded: {len(yamls)}")
    first_key = next(iter(yamls))
    print(f"First YAML key: {first_key}")
    print(f"First YAML fields_used (first 5): {yamls[first_key]['fields_used'][:5]}")
