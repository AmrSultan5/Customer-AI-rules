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

from data_loader import get_rules, get_yaml_rules
from schema_validator import validate_rules, validate_sap
from chat_agent import handle_message, stream_message
from analytics import track_chat_event, track_feedback

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
# The schema admits a larger cap than the live-input limit above so that an
# assistant answer echoed back as history (which can run longer than a user
# question) is not rejected; the stricter live-input cap is enforced
# per-request below. Env var name kept for deployment compatibility.
_MAX_MESSAGE_SCHEMA_LEN = int(os.environ.get("MAX_PERSONA_MESSAGE_LENGTH", "12000"))
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
    # Assistant answers can be long and are sent back as history next turn, so
    # the schema cap is looser than the live-input cap. Items are truncated
    # server-side to _MAX_HISTORY_ITEM_LEN before reaching the agent.
    content: Annotated[str, Field(max_length=_MAX_MESSAGE_SCHEMA_LEN)]


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    mode: Literal["analyst", "engineer", "pm"] = "analyst"
    rule_id: Annotated[str | None, Field(max_length=64)] = None


class ChatRequest(BaseModel):
    # Schema admits the larger cap; the stricter live-input cap is enforced
    # per-request in the endpoints (see _MAX_MESSAGE_LEN).
    message: Annotated[str, Field(min_length=1, max_length=_MAX_MESSAGE_SCHEMA_LEN)]
    context_rule_id: str | None = None
    # Analyst-only opt-in: when true, off-catalog questions get a direct general
    # answer instead of being forced through rule search. Toggled by a button in
    # the UI; default false keeps the strict rules-only behavior.
    general: bool = False
    # max_length enforced at API schema level; frontend also caps at 20
    history: Annotated[list[ChatMessage], Field(max_length=_MAX_HISTORY)] = Field(
        default_factory=list
    )
    # When set, the conversation is loaded/persisted server-side: history comes
    # from the DB, both messages are stored, and project instructions (if any)
    # are injected.
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
        await db.seed_knowledge_bases()
        log.info("[INFO] Knowledge base registry seeded.")
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
    Event types: {"type":"chunk","text":"..."} and
    {"type":"done","rule_id":"...","suggested_followups":[...]}.
    The existing /chat endpoint is unchanged for non-streaming clients.

    When body.conversation_id is set, history is loaded from the DB, both the
    user and assistant messages are persisted, and any project instructions
    are injected as context.
    """
    message = body.message.strip()

    # ── Resolve persistence context (conversation / instructions) ────────────
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
    if len(message) > _MAX_MESSAGE_LEN:
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
                body.message, context_rule_id, history=history,
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


# ── Admin router ───────────────────────────────────────────────────────────────

admin_router = APIRouter(prefix="/admin", dependencies=[Depends(_check_admin_auth)])


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
