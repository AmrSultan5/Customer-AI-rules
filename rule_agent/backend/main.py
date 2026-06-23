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
    # but absent from Python's bundled certifi store (otherwise all Anthropic
    # calls fail with CERTIFICATE_VERIFY_FAILED). Must run before any HTTPS
    # client is created.
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

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

import db
import conversation_service as cs
import openai_client
from db import get_session

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


async def get_current_user(
    x_user: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
):
    """Resolve the workspace user from the X-User header (lightweight identity).

    Get-or-creates the user so a fresh username transparently claims a workspace.
    """
    if not x_user or not x_user.strip():
        raise HTTPException(
            status_code=400,
            detail={"error": "X-User header required."},
        )
    user = await cs.get_or_create_user(session, x_user.strip())
    await session.commit()
    return user


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
    # Analyst-only opt-in: when true, off-catalog questions get a direct general
    # answer instead of being forced through rule search. Toggled by a button in
    # the UI; default false keeps the strict rules-only behavior.
    general: bool = False
    # max_length enforced at API schema level; frontend also caps at 20
    history: Annotated[list[ChatMessage], Field(max_length=_MAX_HISTORY)] = Field(
        default_factory=list
    )
    # When set, the conversation is loaded/persisted server-side: history comes
    # from the DB, both messages are stored, the persona is taken from the
    # conversation, and project instructions (if any) are injected.
    conversation_id: int | None = None


# ── Chat workspace request models ───────────────────────────────────────────


class UserLoginRequest(BaseModel):
    username: Annotated[str, Field(min_length=1, max_length=64)]


class ProjectCreateRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    instructions: Annotated[str | None, Field(max_length=8000)] = None


class ProjectUpdateRequest(BaseModel):
    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    instructions: Annotated[str | None, Field(max_length=8000)] = None


class ConversationCreateRequest(BaseModel):
    persona: Literal["analyst", "engineer", "pm"] = "analyst"
    project_id: int | None = None
    title: Annotated[str | None, Field(max_length=200)] = None
    context_rule_id: Annotated[str | None, Field(max_length=64)] = None


class ConversationUpdateRequest(BaseModel):
    title: Annotated[str | None, Field(max_length=200)] = None
    project_id: int | None = None


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
        await db.init_db()
        log.info("[INFO] Database schema ready.")
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
    allow_methods=["*"],
    allow_headers=["*"],
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
    """Lightweight liveness probe. Returns rules_loaded count; never calls the LLM."""
    return {"status": "ok", "rules_loaded": len(get_rules())}


@health_router.get("/ready")
def ready():
    """Readiness probe — checks config and data; does NOT call the LLM."""
    issues = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        issues.append("ANTHROPIC_API_KEY not configured")
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
        result = handle_message(
            body.message, body.context_rule_id, history=history, allow_general=body.general,
        )
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
async def chat_stream(
    request: Request,
    body: ChatRequest,
    x_user: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
):
    """Streaming SSE variant of /chat.

    Returns Server-Sent Events; each event is a JSON object on a `data:` line.
    Event types: {"type":"chunk","text":"..."}, {"type":"status","text":"..."}
    (persona modes only) and {"type":"done","rule_id":"...","suggested_followups":[...]}.
    The existing /chat endpoint is unchanged for non-streaming clients.

    When body.conversation_id is set, history is loaded from the DB, both the
    user and assistant messages are persisted, the persona is taken from the
    conversation, and any project instructions are injected as context.
    """
    message = body.message.strip()

    # ── Resolve persistence context (conversation / persona / instructions) ──
    mode = body.mode
    history = _history_for_agent(body)
    extra_context: str | None = None
    conv_id = body.conversation_id
    user_id: int | None = None
    context_rule_id = body.context_rule_id

    if conv_id is not None:
        if not x_user or not x_user.strip():
            raise HTTPException(
                status_code=400,
                detail={"error": "X-User header required for conversation persistence."},
            )
        user = await cs.get_or_create_user(session, x_user.strip())
        user_id = user.id
        conv = await cs.get_conversation(session, conv_id, user.id)
        if conv is None:
            raise HTTPException(status_code=404, detail={"error": "Conversation not found."})
        mode = conv.persona  # the conversation's persona drives the answer flow
        context_rule_id = body.context_rule_id or conv.context_rule_id
        db_hist = await cs.recent_history(session, conv_id)
        if db_hist:
            history = db_hist
        if conv.project_id is not None:
            extra_context = await cs.project_instructions(session, conv.project_id)
        # Persist the user turn before streaming.
        await cs.append_message(session, conv_id, "user", body.message)
        await session.commit()

    # Validate before starting the generator — once StreamingResponse begins,
    # the HTTP 200 header is already sent and we cannot return a 4xx.
    # Analyst mode keeps the stricter cap; persona modes accept pasted user
    # stories up to the schema cap (_MAX_PERSONA_MESSAGE_LEN, enforced by Pydantic).
    if mode == "analyst" and len(message) > _MAX_MESSAGE_LEN:
        raise HTTPException(
            status_code=400,
            detail={"detail": f"Message exceeds maximum length of {_MAX_MESSAGE_LEN} characters."},
        )

    user_message = body.message

    async def _generator():
        resolved_rule_id = context_rule_id
        assistant_text = ""
        followups: list = []
        try:
            async for event in stream_message(
                body.message, context_rule_id, history=history, mode=mode,
                allow_general=body.general, extra_context=extra_context,
            ):
                if event.startswith("data:"):
                    try:
                        payload = json.loads(event[5:].strip())
                        ptype = payload.get("type")
                        if ptype == "chunk":
                            assistant_text += payload.get("text", "")
                        elif ptype == "done":
                            if payload.get("rule_id"):
                                resolved_rule_id = payload["rule_id"]
                            followups = payload.get("suggested_followups", []) or []
                    except Exception:
                        pass
                yield event
        except Exception as exc:
            log.error("[ERROR] /chat/stream generator failed: %s", type(exc).__name__)
            assistant_text = assistant_text or "The AI service is temporarily unavailable. Please try again."
            yield f"data: {json.dumps({'type': 'chunk', 'text': assistant_text})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'rule_id': None, 'suggested_followups': []})}\n\n"
        finally:
            asyncio.create_task(track_chat_event(resolved_rule_id, None, user_id))
            if conv_id is not None and assistant_text.strip():
                # Awaited (not fire-and-forget): the `done` event has already been
                # sent, so this only briefly delays closing the stream, and it
                # guarantees the turn is saved before the request ends.
                await _persist_assistant_turn(
                    conv_id, assistant_text, resolved_rule_id, followups, user_message,
                )

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _persist_assistant_turn(
    conversation_id: int,
    assistant_text: str,
    rule_id: str | None,
    followups: list,
    user_message: str,
) -> None:
    """Save the assistant reply, bump updated_at, and auto-title on first reply.

    Runs in its own session (the request session is torn down once streaming
    ends) and is fire-and-forget — failures never affect the user's stream.
    """
    try:
        async with db.AsyncSessionLocal() as s:
            await cs.append_message(
                s, conversation_id, "assistant", assistant_text, rule_id, followups,
            )
            await cs.touch_conversation(s, conversation_id)
            if await cs.needs_title(s, conversation_id):
                title = await openai_client.generate_title_async(user_message, assistant_text)
                await cs.set_title_if_empty(s, conversation_id, title)
    except Exception as exc:
        log.warning("[chat] persist assistant turn failed: %s", type(exc).__name__)


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
    """Admin-only LLM connectivity check. Calls the Anthropic API; never used as a recurring probe."""
    from explanation_engine import probe_llm
    try:
        await probe_llm()
        return {"llm": "ok"}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"llm": "degraded", "llm_error": type(exc).__name__})


# ── Chat workspace router (users, projects, conversations) ───────────────────

workspace_router = APIRouter(dependencies=[Depends(_check_auth)])


@workspace_router.post("/users/login")
async def users_login(body: UserLoginRequest, session: AsyncSession = Depends(get_session)):
    """Lightweight login — claim (or create) a workspace by username."""
    user = await cs.get_or_create_user(session, body.username)
    await session.commit()
    return {"user_id": user.id, "username": user.username}


@workspace_router.get("/projects")
async def get_projects(user=Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await cs.list_projects(session, user.id)


@workspace_router.post("/projects")
async def post_project(
    body: ProjectCreateRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await cs.create_project(session, user.id, body.name, body.instructions)


@workspace_router.patch("/projects/{project_id}")
async def patch_project(
    project_id: int,
    body: ProjectUpdateRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await cs.update_project(
        session, project_id, user.id, name=body.name, instructions=body.instructions
    )
    if result is None:
        raise HTTPException(status_code=404, detail={"error": "Project not found."})
    return result


@workspace_router.delete("/projects/{project_id}")
async def delete_project_endpoint(
    project_id: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not await cs.delete_project(session, project_id, user.id):
        raise HTTPException(status_code=404, detail={"error": "Project not found."})
    return {"ok": True}


@workspace_router.get("/conversations")
async def get_conversations(
    project_id: int | None = None,
    persona: str | None = None,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await cs.list_conversations(session, user.id, project_id, persona)


@workspace_router.post("/conversations")
async def post_conversation(
    body: ConversationCreateRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if body.project_id is not None and await cs.get_project(session, body.project_id, user.id) is None:
        raise HTTPException(status_code=404, detail={"error": "Project not found."})
    return await cs.create_conversation(
        session, user.id, persona=body.persona, project_id=body.project_id,
        title=body.title, context_rule_id=body.context_rule_id,
    )


@workspace_router.get("/conversations/{conversation_id}")
async def get_conversation_detail(
    conversation_id: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await cs.get_conversation_with_messages(session, conversation_id, user.id)
    if result is None:
        raise HTTPException(status_code=404, detail={"error": "Conversation not found."})
    return result


@workspace_router.patch("/conversations/{conversation_id}")
async def patch_conversation(
    conversation_id: int,
    body: ConversationUpdateRequest,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conv = await cs.get_conversation(session, conversation_id, user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail={"error": "Conversation not found."})
    if body.title is not None:
        await cs.rename_conversation(session, conversation_id, user.id, body.title)
    if "project_id" in body.model_fields_set:
        moved = await cs.move_conversation(session, conversation_id, user.id, body.project_id)
        if moved is None:
            raise HTTPException(status_code=400, detail={"error": "Invalid target project."})
    return await cs.get_conversation_with_messages(session, conversation_id, user.id)


@workspace_router.delete("/conversations/{conversation_id}")
async def delete_conversation_endpoint(
    conversation_id: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not await cs.delete_conversation(session, conversation_id, user.id):
        raise HTTPException(status_code=404, detail={"error": "Conversation not found."})
    return {"ok": True}


@workspace_router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: int,
    user=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await cs.get_conversation_with_messages(session, conversation_id, user.id)
    if result is None:
        raise HTTPException(status_code=404, detail={"error": "Conversation not found."})
    return result["messages"]


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
app.include_router(workspace_router)
app.include_router(
    workspace_router,
    prefix="/api",
    generate_unique_id_function=lambda route: f"api_ws_{route.name}",
)
app.include_router(admin_router)
app.include_router(
    admin_router,
    prefix="/api",
    generate_unique_id_function=lambda route: f"api_{route.name}",
)
