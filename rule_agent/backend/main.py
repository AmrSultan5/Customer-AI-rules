"""
Rule Agent FastAPI Application
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

try:
    # Use the OS certificate store for TLS verification. Required on corporate
    # networks with TLS-intercepting proxies whose root CA is trusted by the OS
    # but absent from Python's bundled certifi store (otherwise all OpenAI
    # calls fail with CERTIFICATE_VERIFY_FAILED). Must run before any HTTPS
    # client is created.
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
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
from chat_agent import handle_message, stream_message
from analytics import track_rule_view, track_chat_event, track_feedback, get_dashboard_data

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ── Configuration ──────────────────────────────────────────────────────────────

_AUTH_TOKEN: str = os.environ.get("RULE_AGENT_API_TOKEN", "")
_RULE_AGENT_ENV: str = os.environ.get("RULE_AGENT_ENV", "production")
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
# Persona modes (engineer/pm) accept pasted user stories, which are longer than
# analyst questions. The Pydantic schema admits the larger cap; the analyst cap
# is enforced per-request in the endpoints.
_MAX_PERSONA_MESSAGE_LEN = int(os.environ.get("MAX_PERSONA_MESSAGE_LENGTH", "12000"))
_MAX_HISTORY = 20
_MAX_HISTORY_ITEM_LEN = 8000  # server-side truncation before passing to the agent

# Admin credentials — username/password used by the /admin/login endpoint.
# RULE_AGENT_ADMIN_TOKEN is still accepted as a Bearer token fallback.
_ADMIN_TOKEN: str    = os.environ.get("RULE_AGENT_ADMIN_TOKEN", _AUTH_TOKEN)
_ADMIN_USER: str     = os.environ.get("RULE_AGENT_ADMIN_USER", "admin")
_ADMIN_PASSWORD: str = os.environ.get("RULE_AGENT_ADMIN_PASSWORD", "")

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
        content={"detail": "Too many requests. Please wait before trying again."},
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


def _check_admin_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if not _REQUIRE_AUTH:
        return
    if creds is None or creds.credentials != _ADMIN_TOKEN:
        raise HTTPException(
            status_code=401,
            detail={"error": "Admin authorization required."},
        )


# ── Pydantic models ────────────────────────────────────────────────────────────


class AdminLoginRequest(BaseModel):
    username: Annotated[str, Field(min_length=1, max_length=64)]
    password: Annotated[str, Field(min_length=1, max_length=128)]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    # Persona-mode answers can be long and are sent back as history next turn,
    # so the schema cap matches the persona message cap. Items are truncated
    # server-side to _MAX_HISTORY_ITEM_LEN before reaching the agent.
    content: Annotated[str, Field(max_length=_MAX_PERSONA_MESSAGE_LEN)]


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    mode: Literal["analyst", "engineer", "pm"] = "analyst"
    rule_id: Annotated[str | None, Field(max_length=64)] = None


class YamlValidationRequest(BaseModel):
    # Cap matches yaml_validation.MAX_YAML_CHARS — enforced here so oversized
    # payloads are rejected by the schema before reaching the validator.
    yaml_text: Annotated[str, Field(min_length=1, max_length=600_000)]


class ChatRequest(BaseModel):
    # Schema admits the persona cap; the stricter analyst cap is enforced
    # per-request in the endpoints based on mode.
    message: Annotated[str, Field(min_length=1, max_length=_MAX_PERSONA_MESSAGE_LEN)]
    context_rule_id: str | None = None
    mode: Literal["analyst", "engineer", "pm"] = "analyst"
    # max_length enforced at API schema level; frontend also caps at 20
    history: Annotated[list[ChatMessage], Field(max_length=_MAX_HISTORY)] = Field(
        default_factory=list
    )


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("[INFO] Starting up — loading data...")
    try:
        rules = get_rules()
        from data_loader import get_sap_map
        sap = get_sap_map()
        validate_rules(rules)
        validate_sap(sap)
        get_yaml_rules()
        log.info("[INFO] Data loaded. %d active Customer rules ready.", len(rules))
    except Exception as exc:
        log.critical(
            "[CRITICAL] Startup data load failed: %s — %s",
            type(exc).__name__, exc,
        )
        raise
    if _RULE_AGENT_ENV == "production":
        raw_cors = os.environ.get("CORS_ORIGINS", "").strip()
        if raw_cors == "*":
            raise RuntimeError(
                "CORS_ORIGINS must be set to a specific origin in production. "
                "Refusing to start with wildcard CORS."
            )
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


@app.post("/admin/login")
@app.post("/api/admin/login")
async def admin_login(body: AdminLoginRequest):
    """Validate admin username/password and return a session token.

    Dev mode with no password set: any credentials accepted.
    Production: must match RULE_AGENT_ADMIN_USER / RULE_AGENT_ADMIN_PASSWORD.
    """
    import hmac as _hmac

    if _DEV_MODE and not _ADMIN_PASSWORD:
        return {"ok": True, "token": _ADMIN_TOKEN or "dev-session"}

    user_ok = _hmac.compare_digest(body.username.encode(), _ADMIN_USER.encode())
    pass_ok = _hmac.compare_digest(body.password.encode(), _ADMIN_PASSWORD.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail={"error": "Invalid username or password."})

    return {"ok": True, "token": _ADMIN_TOKEN}


# ── Health router (no auth, dual-registered under / and /api) ─────────────────

health_router = APIRouter()


@health_router.get("/health")
def health():
    """Lightweight liveness probe. Returns rules_loaded count; never calls Azure OpenAI."""
    return {"status": "ok", "rules_loaded": len(get_rules())}


@health_router.get("/ready")
def ready():
    """Readiness probe — checks config and data; does NOT call OpenAI."""
    issues = []
    if not os.environ.get("OPENAI_API_KEY"):
        issues.append("OPENAI_API_KEY not configured")
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
async def get_rule(rule_id: str):
    result = _build_rule_response(rule_id)
    asyncio.create_task(track_rule_view(rule_id))
    return result


@router.get("/rules/impact/{rule_id}")
def get_rule_impact_endpoint(rule_id: str):
    """Deterministic impact graph for a rule: dependents, pipelines, custom ops,
    same-target rules, and the file paths a change would touch. No LLM."""
    from impact_service import get_rule_impact
    impact = get_rule_impact(rule_id)
    if impact is None:
        raise HTTPException(status_code=404, detail={"error": "Rule not found"})
    return impact


@router.post("/validate/yaml")
def validate_yaml_endpoint(body: YamlValidationRequest):
    """Structural validation for a pasted pipeline YAML (engineer paste-back check)."""
    from yaml_validation import validate_pipeline_yaml
    return validate_pipeline_yaml(body.yaml_text)


@router.post("/feedback")
async def submit_feedback(body: FeedbackRequest):
    """Record a thumbs up/down on an assistant answer."""
    await track_feedback(body.rating, body.mode, body.rule_id)
    return {"ok": True}


def _history_for_agent(body: ChatRequest) -> list[dict] | None:
    """Convert validated history to agent format, truncating long items server-side."""
    return [
        {"role": m.role, "content": m.content[:_MAX_HISTORY_ITEM_LEN]}
        for m in body.history
    ] or None


@router.post("/chat")
@limiter.limit(_chat_rate_limit)
async def chat(request: Request, body: ChatRequest):
    # async def is required for slowapi's decorator to work correctly on Python 3.12+.
    if body.mode != "analyst":
        raise HTTPException(
            status_code=400,
            detail={"detail": "Persona modes are only available on /chat/stream."},
        )
    if len(body.message.strip()) > _MAX_MESSAGE_LEN:
        raise HTTPException(
            status_code=400,
            detail={"detail": f"Message exceeds maximum length of {_MAX_MESSAGE_LEN} characters."},
        )
    try:
        history = _history_for_agent(body)
        result = handle_message(body.message, body.context_rule_id, history=history)
        asyncio.create_task(track_chat_event(result.get("rule_id") or body.context_rule_id, None))
        return result
    except HTTPException:
        raise  # let rate-limiter and auth exceptions propagate as-is
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"detail": str(exc)})
    except Exception as exc:
        # Log the real error server-side only; return a generic message to the client
        # to avoid leaking provider error details or internal stack traces.
        log.error("[ERROR] /chat handler failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail={"error": "The AI service is temporarily unavailable. Please try again."},
        )


@router.post("/chat/stream")
@limiter.limit(_chat_rate_limit)
async def chat_stream(request: Request, body: ChatRequest):
    """Streaming SSE variant of /chat.

    Returns Server-Sent Events; each event is a JSON object on a `data:` line.
    Event types: {"type":"chunk","text":"..."}, {"type":"status","text":"..."}
    (persona modes only) and {"type":"done","rule_id":"...","suggested_followups":[...]}.
    The existing /chat endpoint is unchanged for non-streaming clients.
    """
    # Validate before starting the generator — once StreamingResponse begins,
    # the HTTP 200 header is already sent and we cannot return a 4xx.
    # Analyst mode keeps the stricter cap; persona modes accept pasted user
    # stories up to the schema cap (_MAX_PERSONA_MESSAGE_LEN, enforced by Pydantic).
    message = body.message.strip()
    if body.mode == "analyst" and len(message) > _MAX_MESSAGE_LEN:
        raise HTTPException(
            status_code=400,
            detail={"detail": f"Message exceeds maximum length of {_MAX_MESSAGE_LEN} characters."},
        )

    history = _history_for_agent(body)

    context_rule_id = body.context_rule_id

    async def _generator():
        resolved_rule_id = context_rule_id
        try:
            async for event in stream_message(body.message, context_rule_id, history=history, mode=body.mode):
                # Capture the rule_id from the done event for analytics
                if event.startswith("data:"):
                    try:
                        payload = json.loads(event[5:].strip())
                        if payload.get("type") == "done" and payload.get("rule_id"):
                            resolved_rule_id = payload["rule_id"]
                    except Exception:
                        pass
                yield event
        except Exception as exc:
            log.error("[ERROR] /chat/stream generator failed: %s", type(exc).__name__)
            yield f"data: {json.dumps({'type': 'chunk', 'text': 'The AI service is temporarily unavailable. Please try again.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'rule_id': None, 'suggested_followups': []})}\n\n"
        finally:
            asyncio.create_task(track_chat_event(resolved_rule_id, None))

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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


# ── Admin router ───────────────────────────────────────────────────────────────

admin_router = APIRouter(prefix="/admin", dependencies=[Depends(_check_admin_auth)])


@admin_router.get("/dashboard")
async def admin_dashboard():
    """Return aggregated analytics for the Rule Health Dashboard."""
    total = len(get_rules())
    return await get_dashboard_data(total)


@admin_router.post("/reload")
async def admin_reload():
    """Reload all data sources (Excel inventory, golden/ YAML, custom ops) from disk.

    The reload validates the fresh data BEFORE swapping caches, so a broken
    file leaves the running app serving the previous data and returns 503.
    """
    import data_loader
    try:
        counts = await asyncio.to_thread(data_loader.reload_all)
    except Exception as exc:
        log.error("[ERROR] /admin/reload failed: %s — %s", type(exc).__name__, exc)
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": f"Reload failed ({type(exc).__name__}) — previous data is still being served."},
        )
    return {"ok": True, **counts}


@admin_router.get("/probe-llm")
async def admin_probe_llm():
    """Admin-only LLM connectivity check. Calls Azure OpenAI; never used as a recurring probe."""
    from explanation_engine import probe_llm
    try:
        await probe_llm()
        return {"llm": "ok"}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"llm": "degraded", "llm_error": type(exc).__name__})


# ── Register routes ─────────────────────────────────────────────────────────

# Register routes under both bare paths (dev proxy compatible) and /api prefix (production)
app.include_router(health_router)
app.include_router(
    health_router,
    prefix="/api",
    generate_unique_id_function=lambda route: f"api_{route.name}",
)
app.include_router(router)
app.include_router(
    router,
    prefix="/api",
    generate_unique_id_function=lambda route: f"api_{route.name}",
)
app.include_router(admin_router)
app.include_router(
    admin_router,
    prefix="/api",
    generate_unique_id_function=lambda route: f"api_{route.name}",
)
