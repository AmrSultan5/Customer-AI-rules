"""
STEP 8 — FastAPI Application
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from data_loader import get_rules, get_yaml_rules, get_yaml_raw, find_yaml_for_rule, get_referenced_rules
from lineage_service import get_lineage
from rule_parser import extract_sap_fields
from sap_mapper import lookup_sap_field
from explanation_engine import explain_rule, build_sap_context
from schema_validator import validate_rules, validate_sap
from chat_agent import handle_message

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("[INFO] Starting up — loading data...")
    rules = get_rules()
    from data_loader import get_sap_map
    sap = get_sap_map()
    validate_rules(rules)
    validate_sap(sap)
    get_yaml_rules()
    log.info("[INFO] Data loaded. %d active Customer rules ready.", len(rules))
    yield
    log.info("[INFO] Shutting down.")


app = FastAPI(title="Rule Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- helpers ----------------------------------------------------------

def _build_rule_response(rule_id: str) -> dict:
    rules = get_rules()
    yamls = get_yaml_rules()

    match = rules[rules["rule_id"].str.upper() == rule_id.upper()]
    if match.empty:
        raise HTTPException(status_code=404, detail={"error": "Rule not found"})

    row = match.iloc[0]
    excel_logic = str(row.get("rule_logic", "") or "")

    # Prefer YAML for technical_rule — it is the source of truth
    yaml_match = find_yaml_for_rule(rule_id)
    if yaml_match:
        yaml_filename = yaml_match["yaml_file"]
        technical_rule = get_yaml_raw(yaml_filename)
        yaml_ref = yaml_filename
        log.info("[INFO] technical_rule sourced from YAML: %s", yaml_filename)
    else:
        technical_rule = excel_logic
        yaml_ref = ""
        log.info("[INFO] No YAML match for %s — falling back to Excel logic", rule_id)

    # SAP field extraction uses Excel logic (has TABLE-FIELD patterns)
    raw_fields = extract_sap_fields(excel_logic)
    mapped_fields = [lookup_sap_field(f) for f in raw_fields]
    ctx = build_sap_context(mapped_fields)
    explanation = explain_rule(excel_logic, ctx)

    lin = get_lineage(rule_id)
    workflow_steps: list[str] = lin.get("workflow_steps", [])
    if not yaml_ref:
        yaml_ref = lin.get("yaml_reference", "")
    sources: list[str] = lin.get("pipeline_sources", [])

    # Determine origin
    origin_parts = []
    for key in ("module", "group", "sub_domain", "quality_category"):
        val = str(row.get(key, "") or "").strip()
        if val and val.lower() not in ("nan", "none", ""):
            origin_parts.append(val)
    origin = " / ".join(origin_parts) if origin_parts else "Customer"

    # Build referenced rules list (explicit dependencies + logic references)
    ref_rules_raw = get_referenced_rules(rule_id)
    referenced_rules = []
    for ref in ref_rules_raw:
        referenced_rules.append({
            "rule_id":          ref["rule_id"],
            "source":           ref["source"],          # "dependent_on" or "logic"
            "active":           ref.get("active", False),
            "description":      ref.get("rule_description", ""),
            "quality_category": ref.get("quality_category", ""),
            "severity":         ref.get("severity", ""),
        })

    return {
        "rule_id": str(row.get("rule_id", "")),
        "business_explanation": explanation,
        "technical_rule": technical_rule,
        "sap_fields": mapped_fields,
        "origin": origin,
        "workflow_steps": workflow_steps,
        "yaml_reference": yaml_ref,
        "sources": sources,
        "description": str(row.get("rule_description", "") or ""),
        "quality_category": str(row.get("quality_category", "") or ""),
        "severity": str(row.get("severity", "") or ""),
        "table_checked": str(row.get("table_name_checked", "") or ""),
        "column_checked": str(row.get("column_name_checked", "") or ""),
        "referenced_rules": referenced_rules,
    }


# ---------- endpoints --------------------------------------------------------

@app.get("/health")
def health():
    rules = get_rules()
    return {"status": "ok", "rules_loaded": len(rules)}


@app.get("/rules")
def list_rules():
    rules = get_rules()
    result = []
    for _, row in rules.iterrows():
        result.append({
            "rule_id":          str(row.get("rule_id", "") or ""),
            "quality_category": str(row.get("quality_category", "") or ""),
            "table_checked":    str(row.get("table_name_checked", "") or ""),
            "description":      str(row.get("rule_description", "") or ""),
            "severity":         str(row.get("severity", "") or ""),
        })
    return result


@app.get("/rules/related/{rule_id}")
def get_related_rules(rule_id: str):
    rules = get_rules()
    match = rules[rules["rule_id"].str.upper() == rule_id.upper()]
    if match.empty:
        raise HTTPException(status_code=404, detail={"error": "Rule not found"})

    row = match.iloc[0]
    category = str(row.get("quality_category", "") or "").strip()
    table    = str(row.get("table_name_checked", "") or "").strip()

    others = rules[rules["rule_id"].str.upper() != rule_id.upper()].copy()

    masks = []
    if category:
        masks.append(others["quality_category"].fillna("").str.strip().str.lower() == category.lower())
    if table and "table_name_checked" in others.columns:
        masks.append(others["table_name_checked"].fillna("").str.strip().str.lower() == table.lower())

    if not masks:
        return []

    combined = masks[0]
    for m in masks[1:]:
        combined = combined | m

    subset = others[combined].head(4)
    return [
        {
            "rule_id":          str(r.get("rule_id", "") or ""),
            "quality_category": str(r.get("quality_category", "") or ""),
            "severity":         str(r.get("severity", "") or ""),
            "table_checked":    str(r.get("table_name_checked", "") or ""),
        }
        for _, r in subset.iterrows()
    ]


@app.get("/rule/{rule_id}")
def get_rule(rule_id: str):
    return _build_rule_response(rule_id)


class ChatMessage(BaseModel):
    role: str   # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    context_rule_id: str | None = None
    history: list[ChatMessage] = []


@app.post("/chat")
def chat(body: ChatRequest):
    history = [{"role": m.role, "content": m.content} for m in body.history] or None
    result = handle_message(body.message, body.context_rule_id, history=history)
    return result
