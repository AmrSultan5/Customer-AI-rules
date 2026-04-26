"""
Rule Agent FastAPI Application
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from data_loader import (
    extract_rule_section_from_yaml,
    find_yaml_for_rule,
    get_referenced_rules,
    get_rules,
    get_yaml_raw,
    get_yaml_rules,
)
from lineage_service import get_lineage
from rule_parser import extract_sap_fields
from sap_mapper import lookup_sap_field
from explanation_engine import build_sap_context, explain_rule
from schema_validator import validate_rules, validate_sap
from chat_agent import handle_message

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ── Configuration ──────────────────────────────────────────────────────────────

_AUTH_TOKEN: str = os.environ.get("RULE_AGENT_API_TOKEN", "")
_RULE_AGENT_ENV: str = os.environ.get("RULE_AGENT_ENV", "development")
# Auth is skipped ONLY when explicitly in development mode with no token.
# Any non-development env (staging, production, …) must have a token — enforced below.
_DEV_MODE: bool = _RULE_AGENT_ENV == "development"
_REQUIRE_AUTH: bool = bool(_AUTH_TOKEN) or not _DEV_MODE

_CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]
_MAX_MESSAGE_LEN = int(os.environ.get("MAX_MESSAGE_LENGTH", "2000"))
_MAX_HISTORY = 20

if not _DEV_MODE and not _AUTH_TOKEN:
    raise RuntimeError(
        f"RULE_AGENT_API_TOKEN must be set when RULE_AGENT_ENV={_RULE_AGENT_ENV!r}. "
        'Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
    )

# ── Rate limiting ──────────────────────────────────────────────────────────────


def _chat_rate_limit() -> str:
    """Called by slowapi per-request to get the limit string; reads env at call time."""
    return f"{os.environ.get('CHAT_RATE_LIMIT', '30')}/minute"


limiter = Limiter(key_func=get_remote_address, default_limits=[])


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "Rate limit exceeded. Please wait before sending another message."},
    )


# ── Authentication ─────────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


def _check_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Require Bearer token on all non-development environments.

    Auth is skipped only when RULE_AGENT_ENV=development AND no token is set.
    Any other env value (staging, production, …) requires a valid token, and
    startup already fails if the token is missing in those environments.
    """
    if not _REQUIRE_AUTH:
        return
    if creds is None or creds.credentials != _AUTH_TOKEN:
        raise HTTPException(
            status_code=401,
            detail={"error": "Unauthorized. Provide Authorization: Bearer <token>."},
        )


# ── Pydantic models ────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(max_length=_MAX_MESSAGE_LEN)]


class ChatRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=_MAX_MESSAGE_LEN)]
    context_rule_id: str | None = None
    # max_length enforced at API schema level; frontend also caps at 20
    history: Annotated[list[ChatMessage], Field(max_length=_MAX_HISTORY)] = Field(
        default_factory=list
    )


# ── Lifespan ───────────────────────────────────────────────────────────────────


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


# ── Application ────────────────────────────────────────────────────────────────

app = FastAPI(title="Rule Agent API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_rule_response(rule_id: str) -> dict:
    rules = get_rules()
    get_yaml_rules()  # ensure cache is warm

    match = rules[rules["rule_id"].str.upper() == rule_id.upper()]
    if match.empty:
        raise HTTPException(status_code=404, detail={"error": "Rule not found"})

    row = match.iloc[0]
    excel_logic = str(row.get("rule_logic", "") or "")

    yaml_match = find_yaml_for_rule(rule_id)
    if yaml_match:
        yaml_filename = yaml_match["yaml_file"]
        raw_yaml = get_yaml_raw(yaml_filename)
        technical_rule = extract_rule_section_from_yaml(raw_yaml, rule_id)
        yaml_ref = yaml_filename
        log.info("[INFO] technical_rule sourced from YAML: %s", yaml_filename)
    else:
        technical_rule = excel_logic
        yaml_ref = ""
        log.info("[INFO] No YAML match for %s — falling back to Excel logic", rule_id)

    raw_fields = extract_sap_fields(excel_logic)
    mapped_fields = [lookup_sap_field(f) for f in raw_fields]
    ctx = build_sap_context(mapped_fields)
    explanation = explain_rule(excel_logic, ctx)

    lin = get_lineage(rule_id)
    workflow_steps: list[str] = lin.get("workflow_steps", [])
    if not yaml_ref:
        yaml_ref = lin.get("yaml_reference", "")
    sources: list[str] = lin.get("pipeline_sources", [])

    origin_parts = []
    for key in ("module", "group", "sub_domain", "quality_category"):
        val = str(row.get(key, "") or "").strip()
        if val and val.lower() not in ("nan", "none", ""):
            origin_parts.append(val)
    origin = " / ".join(origin_parts) if origin_parts else "Customer"

    ref_rules_raw = get_referenced_rules(rule_id)
    referenced_rules = [
        {
            "rule_id":          ref["rule_id"],
            "source":           ref["source"],
            "active":           ref.get("active", False),
            "description":      ref.get("rule_description", ""),
            "quality_category": ref.get("quality_category", ""),
            "severity":         ref.get("severity", ""),
        }
        for ref in ref_rules_raw
    ]

    return {
        "rule_id":              str(row.get("rule_id", "")),
        "business_explanation": explanation,
        "technical_rule":       technical_rule,
        "sap_fields":           mapped_fields,
        "origin":               origin,
        "workflow_steps":       workflow_steps,
        "yaml_reference":       yaml_ref,
        "sources":              sources,
        "description":          str(row.get("rule_description", "") or ""),
        "quality_category":     str(row.get("quality_category", "") or ""),
        "severity":             str(row.get("severity", "") or ""),
        "table_checked":        str(row.get("table_name_checked", "") or ""),
        "column_checked":       str(row.get("column_name_checked", "") or ""),
        "referenced_rules":     referenced_rules,
    }


# ── Public endpoints ───────────────────────────────────────────────────────────


@app.get("/health")
def health():
    """Lightweight liveness probe. Always public, no auth required."""
    rules = get_rules()
    return {"status": "ok", "rules_loaded": len(rules)}


@app.get("/ready")
def ready():
    """
    Readiness probe. Verifies required config and data are present.

    - Does NOT call Azure OpenAI (avoids excessive external calls on every probe).
    - Returns 503 if config is missing or no rules are loaded.
    - Use /health for liveness; use /ready for readiness (e.g. k8s readinessProbe).
    """
    issues = []
    if not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        issues.append("AZURE_OPENAI_ENDPOINT not configured")
    if not os.environ.get("AZURE_OPENAI_API_KEY"):
        issues.append("AZURE_OPENAI_API_KEY not configured")
    rule_count = 0
    try:
        rule_count = len(get_rules())
        if rule_count == 0:
            issues.append("No rules loaded")
    except Exception as exc:
        issues.append(f"Data load error: {type(exc).__name__}")
    if issues:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "issues": issues},
        )
    return {"status": "ready", "rules_loaded": rule_count}


# ── Protected router ───────────────────────────────────────────────────────────

router = APIRouter(dependencies=[Depends(_check_auth)])


@router.get("/rules")
def list_rules():
    rules = get_rules()
    return [
        {
            "rule_id":          str(row.get("rule_id", "") or ""),
            "quality_category": str(row.get("quality_category", "") or ""),
            "table_checked":    str(row.get("table_name_checked", "") or ""),
            "description":      str(row.get("rule_description", "") or ""),
            "severity":         str(row.get("severity", "") or ""),
        }
        for _, row in rules.iterrows()
    ]


@router.get("/rules/related/{rule_id}")
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
        masks.append(
            others["quality_category"].fillna("").str.strip().str.lower() == category.lower()
        )
    if table and "table_name_checked" in others.columns:
        masks.append(
            others["table_name_checked"].fillna("").str.strip().str.lower() == table.lower()
        )
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


@router.get("/rule/{rule_id}")
def get_rule(rule_id: str):
    return _build_rule_response(rule_id)


@router.post("/chat")
@limiter.limit(_chat_rate_limit)
async def chat(request: Request, body: ChatRequest):
    # async def is required for slowapi's decorator to work correctly on Python 3.12+.
    try:
        history = [{"role": m.role, "content": m.content} for m in body.history] or None
        result = handle_message(body.message, body.context_rule_id, history=history)
        return result
    except HTTPException:
        raise  # let rate-limiter and auth exceptions propagate as-is
    except Exception as exc:
        # Log the real error server-side only; return a generic message to the client
        # to avoid leaking provider error details or internal stack traces.
        log.error("[ERROR] /chat handler failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail={"error": "The AI service is temporarily unavailable. Please try again."},
        )


@router.get("/tree")
def get_rule_tree():
    df = get_rules().copy()

    def _s(val) -> str:
        s = str(val or "").strip()
        return "General" if s.lower() in ("nan", "none", "") else s

    def _sev(val) -> int:
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return 1

    df["_sub"] = df["sub_domain"].apply(_s) if "sub_domain" in df.columns else "General"
    df["_cat"] = df["quality_category"].apply(_s) if "quality_category" in df.columns else "General"

    root_children = []
    for subdomain, sd_df in df.groupby("_sub"):
        cat_children = []
        for category, cat_df in sd_df.groupby("_cat"):
            rules_list = []
            for _, row in cat_df.sort_values("rule_id").iterrows():
                desc = _s(row.get("rule_description", ""))
                desc = "" if desc == "General" else desc[:120]
                table = _s(row.get("table_name_checked", ""))
                table = "" if table == "General" else table
                rules_list.append({
                    "id":          str(row["rule_id"]),
                    "name":        str(row["rule_id"]),
                    "type":        "rule",
                    "description": desc,
                    "severity":    _sev(row.get("severity", "")),
                    "table":       table,
                })
            cat_children.append({
                "id":       f"cat__{subdomain}__{category}",
                "name":     category,
                "type":     "category",
                "count":    len(rules_list),
                "children": rules_list,
            })
        cat_children.sort(key=lambda x: x["name"])
        root_children.append({
            "id":       f"sd__{subdomain}",
            "name":     subdomain,
            "type":     "subdomain",
            "count":    len(sd_df),
            "children": cat_children,
        })

    root_children.sort(key=lambda x: x["name"])
    return {
        "id":       "root",
        "name":     "Customer Rules",
        "type":     "root",
        "count":    len(df),
        "children": root_children,
    }


# Register routes under both bare paths (dev proxy compatible) and /api prefix (production)
app.include_router(router)
app.include_router(
    router,
    prefix="/api",
    generate_unique_id_function=lambda route: f"api_{route.name}",
)
