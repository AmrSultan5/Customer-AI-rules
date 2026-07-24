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
from pydantic import BaseModel, Field, model_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from data_loader import (
    get_rules, get_yaml_rules, find_yaml_for_rule, get_yaml_raw,
    extract_rule_section_from_yaml, get_referenced_rules,
)
from schema_validator import validate_rules, validate_sap
from chat_agent import handle_message, stream_message
from analytics import track_chat_event, track_feedback
from lineage_service import get_lineage
from rule_parser import extract_sap_fields
from sap_mapper import lookup_sap_field

import db
import conversation_service as cs
import explanation_engine
import openai_client
import prompts
from config import settings
from db import get_session
from models import KbRepo, KnowledgeBase
from providers.registry import KnowledgeBaseRegistry

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
# Phase 6 — prompt-enhance/save. Matches the ProjectCreateRequest.instructions
# cap; a per-KB custom prompt is a similar-purpose short standing directive.
_MAX_PROMPT_LEN = int(os.environ.get("MAX_KB_PROMPT_LENGTH", "8000"))

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

# ── Knowledge base registry / resolver (Phase 5) ───────────────────────────────
#
# One module-level registry, built once at import time (same descriptors
# chat_agent.py's own lazily-built registry reads — both load
# backend/kb/*.yaml, so they always agree on which KBs exist and resolve to
# behaviorally-identical providers for a given kb_id).
_kb_registry = KnowledgeBaseRegistry()


def get_provider(kb_id: str | None = None, conversation_kb: str | None = None):
    """Resolve which KB provider a request should use.

    Precedence: explicit `kb_id` (only honored when `settings.enable_kb_switcher`
    is true) → `conversation_kb` (a conversation row's stored knowledge_base_id)
    → `settings.active_kb`. This is the single seam that gives dual-mode KB
    selection: an in-app switcher (Settings) when enabled, or a config-pinned
    single KB (`ENABLE_KB_SWITCHER=false`) that always wins regardless of what
    a caller requests.

    Raises HTTPException(404) if the resolved id has no registered KB.
    """
    resolved_id = (
        (kb_id if kb_id and settings.enable_kb_switcher else None)
        or conversation_kb
        or settings.active_kb
    )
    provider = _kb_registry.get_provider(resolved_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Unknown knowledge base: {resolved_id!r}"},
        )
    return provider


async def _repo_block_reason(
    session: AsyncSession, kb_id: str,
) -> tuple[str, str | None] | None:
    """Return (status, status_detail) when `kb_id` names a repo KB that
    cannot currently serve requests, else None (not a repo KB at all, or a
    repo KB that can serve: 'ready', or 'error' with prior content — a
    reload that failed still serves its last good ingest).

    A repo blocks only when it's 'queued'/'ingesting' (no content yet), or
    'error' with NO prior content (never successfully ingested — chunks is
    null/0). Used as a defense-in-depth 409 guard on chat/entity routes — the
    frontend already disables selection of a non-servable repo KB in the
    switcher, but a direct/stale request must still be rejected server-side
    rather than hitting an empty/stale RAG index."""
    row = await session.get(KbRepo, kb_id)
    if row is None or row.status == "ready":
        return None
    has_content = bool(row.chunks and row.chunks > 0)
    if row.status == "error" and has_content:
        return None
    return row.status, row.status_detail


def _raise_repo_not_ready(
    kb_id: str, status: str, status_detail: str | None = None, name: str | None = None,
) -> None:
    if status == "error":
        message = status_detail or (
            f"Knowledge base '{name or kb_id}' failed to update and has no usable content."
        )
    else:
        message = (
            f"Knowledge base '{name or kb_id}' is still being prepared. "
            "Try again once it's ready."
        )
    raise HTTPException(status_code=409, detail={"error": message})

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
    # Explicit KB selection (Phase 5). Only honored when settings.enable_kb_switcher
    # is true; ignored in favor of the conversation's stored KB / the active KB
    # otherwise. See get_provider() for the full precedence.
    knowledge_base_id: Annotated[str | None, Field(max_length=64)] = None


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
    # Explicit KB selection for the new conversation (Phase 5); only honored
    # when settings.enable_kb_switcher is true. Falls back to settings.active_kb
    # (see conversation_service.create_conversation).
    knowledge_base_id: Annotated[str | None, Field(max_length=64)] = None


class ConversationUpdateRequest(BaseModel):
    title: Annotated[str | None, Field(max_length=200)] = None
    project_id: int | None = None


# ── Prompt enhance / save request models (Phase 6) ──────────────────────────


class PromptEnhanceRequest(BaseModel):
    # No min_length here: an empty/whitespace-only draft is rejected with a
    # 400 in the handler (not a 422) per the Phase 6 spec.
    draft: Annotated[str, Field(max_length=_MAX_PROMPT_LEN)]


class PromptSaveRequest(BaseModel):
    custom_prompt: Annotated[str | None, Field(max_length=_MAX_PROMPT_LEN)] = None
    enhanced_prompt: Annotated[str | None, Field(max_length=_MAX_PROMPT_LEN)] = None


# ── Self-service Git-repo KB request models (Phase 9) ───────────────────────


class KbRepoCreateRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    git_url: Annotated[str, Field(min_length=1, max_length=2048)]
    git_ref: Annotated[str | None, Field(max_length=200)] = None
    include_globs: Annotated[str | None, Field(max_length=2000)] = None
    visibility: Literal["public", "private"] = "public"
    auth_token: Annotated[str | None, Field(max_length=4000)] = None

    @model_validator(mode="after")
    def _private_requires_token(self) -> "KbRepoCreateRequest":
        if self.visibility == "private" and not (self.auth_token and self.auth_token.strip()):
            raise ValueError("auth_token is required when visibility is 'private'.")
        return self


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
        await _register_and_reconcile_kb_repos()
        log.info("[INFO] Git-repo knowledge bases registered/reconciled.")
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


# ── KB listing (Phase 5) ────────────────────────────────────────────────────


@router.get("/kbs")
async def list_kbs(session: AsyncSession = Depends(get_session)):
    """List every registered KB plus which one is active / whether the
    in-app switcher is enabled (drives the frontend KB chooser).

    A self-service Git-repo KB (Phase 9, see the /kb-repos section below) is
    included while it's still loading (status 'queued'/'ingesting') so the
    frontend can show it as a disabled "updating…" entry. An 'error' repo is
    included ONLY if it has prior content (chunks > 0 from a last-good
    ingest) — a failed reload keeps serving that last-good version, shown as
    status 'error' with its status_detail so the frontend can surface the
    reason without blocking use. An 'error' repo with no prior content (never
    successfully ingested) is left out entirely — visible only via
    GET /kb-repos in Settings. A descriptor id that isn't a repo id at all
    (every YAML-loaded KB) is always included with status 'ready'.
    """
    repo_info = {
        row.id: row
        for row in (await session.execute(
            select(KbRepo.id, KbRepo.status, KbRepo.status_detail, KbRepo.chunks)
        )).all()
    }
    kbs = []
    for descriptor in _kb_registry.list_descriptors():
        info = repo_info.get(descriptor.id)
        if info is None:
            status, status_detail, selectable = "ready", None, True
        else:
            has_content = bool(info.chunks and info.chunks > 0)
            if info.status == "error" and not has_content:
                continue  # never successfully ingested — Settings-only
            status = info.status
            status_detail = info.status_detail if status == "error" else None
            selectable = status == "ready" or (status == "error" and has_content)
        provider = _kb_registry.get_provider(descriptor.id)
        kbs.append({
            "id": descriptor.id,
            "name": descriptor.name,
            "description": descriptor.description,
            "adapter": descriptor.adapter,
            "retrieval_mode": descriptor.retrieval_mode,
            "capabilities": sorted(provider.capabilities()) if provider else [],
            "status": status,
            "status_detail": status_detail,
            "selectable": selectable,
        })
    return {
        "knowledge_bases": kbs,
        "active_kb": settings.active_kb,
        "switcher_enabled": settings.enable_kb_switcher,
    }


@router.get("/kbs/{kb_id}")
async def get_kb_detail(kb_id: str, session: AsyncSession = Depends(get_session)):
    """Descriptor detail for one KB plus its current stored custom/enhanced
    prompt (Settings → custom prompt, Phase 6 populates enhanced_prompt)."""
    descriptor = _kb_registry.get_descriptor(kb_id)
    if descriptor is None:
        raise HTTPException(status_code=404, detail={"error": f"Unknown knowledge base: {kb_id!r}"})
    provider = _kb_registry.get_provider(kb_id)
    row = await session.get(KnowledgeBase, kb_id)
    return {
        "id": descriptor.id,
        "name": descriptor.name,
        "description": descriptor.description,
        "adapter": descriptor.adapter,
        "retrieval_mode": descriptor.retrieval_mode,
        "capabilities": sorted(provider.capabilities()) if provider else [],
        "custom_prompt": row.custom_prompt if row else None,
        "enhanced_prompt": row.enhanced_prompt if row else None,
    }


# ── Self-service Git-repo knowledge bases (Phase 9) ─────────────────────────
#
# Add a Git repo (public or private) as a brand-new RAG knowledge base,
# DB-persisted (models.KbRepo / kb_repos table) so it survives a Render
# restart. Ingestion (clone + chunk + embed, ingestion.ingest_kb) runs in the
# background; the frontend polls GET /kb-repos/{id} for status until it
# reaches "ready", at which point list_kbs() above starts including it and
# it's immediately usable in chat via _kb_registry.get_provider(repo_id).


def _serialize_kb_repo(row: KbRepo) -> dict:
    """Repo object per the API contract. NEVER includes the token."""
    return {
        "id": row.id,
        "name": row.name,
        "git_url": row.git_url,
        "git_ref": row.git_ref,
        "include_globs": row.include_globs,
        "status": row.status,
        "status_detail": row.status_detail,
        "documents": row.documents,
        "chunks": row.chunks,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _register_and_reconcile_kb_repos() -> None:
    """Startup step (lifespan, after seed_knowledge_bases): re-register every
    persisted kb_repos descriptor into the module-level KB registry — a repo
    ingested before a restart otherwise only lives in the in-process
    registry (register_descriptor), which a restart wipes — and reconcile
    any row an interrupted process left mid-flight ('queued'/'ingesting':
    there is no background task still running to finish it) to 'error', so
    the frontend/user knows to resync rather than polling forever."""
    from kb_repo_service import decrypt_token, descriptor_from_repo

    async with db.AsyncSessionLocal() as session:
        rows = (await session.execute(select(KbRepo))).scalars().all()
        for row in rows:
            token = decrypt_token(row.auth_token_encrypted) if row.auth_token_encrypted else None
            _kb_registry.register_descriptor(descriptor_from_repo(row, token=token))
            if row.status in ("queued", "ingesting"):
                row.status = "error"
                row.status_detail = "Interrupted by restart — resync to retry."
        await session.commit()


_ZERO_FILES_DETAIL = (
    "No matching files found to ingest — check the include patterns (e.g. **/*.md)."
)


def _friendly_ingest_error(exc: Exception) -> str:
    """Map an ingest_kb() failure to a plain-English, actionable reason for
    status_detail — never the raw exception text, which may carry a PAT or
    other internal detail. A clone failure (ingestion._clone_git_repo) already
    raises RuntimeError with a curated, safe message — passed through as-is
    (see ingestion.is_clone_error_message). An OpenAI/embeddings failure
    (detected by exception module/type name) gets its own friendly reason.
    Anything else falls back to a generic "Update failed (<ExcType>)."."""
    from ingestion import is_clone_error_message

    if isinstance(exc, RuntimeError) and is_clone_error_message(str(exc)):
        return str(exc)
    module_name = (type(exc).__module__ or "").lower()
    type_name = type(exc).__name__
    if "openai" in module_name or "openai" in type_name.lower():
        return "Couldn't generate embeddings — the OpenAI API key may be missing or invalid."
    return f"Update failed ({type_name})."


async def _run_repo_ingest(repo_id: str) -> None:
    """Background ingestion for one kb_repos row: set status='ingesting',
    run ingestion.ingest_kb off-thread, then record 'ready' + counts or
    'error' + a friendly detail. Runs in its own DB session — the request
    that spawned this task (asyncio.create_task) has already returned.
    Never raises: a failure here must not crash the fire-and-forget task
    silently either, but there is no caller left to observe an exception, so
    it's caught and recorded on the row instead.

    A failed reload leaves `documents`/`chunks` untouched, so a repo that was
    previously ingested successfully keeps serving that last-good content
    (see _repo_block_reason / list_kbs) even though status is now 'error'. A
    first-ever ingest that finds no matching files at all is *also* recorded
    as 'error' (not 'ready') — see the zero-files check below — since there
    is nothing servable yet.
    """
    from kb_repo_service import decrypt_token, descriptor_from_repo
    from ingestion import ingest_kb

    async with db.AsyncSessionLocal() as session:
        row = await session.get(KbRepo, repo_id)
        if row is None:
            return  # deleted before ingestion started
        had_content = bool(row.chunks and row.chunks > 0)
        row.status = "ingesting"
        row.status_detail = None
        await session.commit()
        token = decrypt_token(row.auth_token_encrypted) if row.auth_token_encrypted else None
        descriptor = descriptor_from_repo(row, token=token)

    try:
        counts = await asyncio.to_thread(ingest_kb, descriptor)
    except Exception as exc:
        # Log the real error server-side only; only the friendly text is
        # persisted/returned so nothing internal (token, stack trace) leaks.
        log.error("[kb-repos] ingest failed for %s: %s — %s", repo_id, type(exc).__name__, exc)
        friendly = _friendly_ingest_error(exc)
        async with db.AsyncSessionLocal() as session:
            row = await session.get(KbRepo, repo_id)
            if row is not None:
                row.status = "error"
                row.status_detail = friendly
                await session.commit()
        return

    new_documents = counts.get("documents") or 0
    new_chunks = counts.get("chunks") or 0

    async with db.AsyncSessionLocal() as session:
        row = await session.get(KbRepo, repo_id)
        if row is not None:
            row.documents = new_documents
            row.chunks = new_chunks
            if new_documents == 0 and new_chunks == 0 and not had_content:
                # Nothing changed this run AND nothing servable from before —
                # a first add whose include patterns matched no files.
                row.status = "error"
                row.status_detail = _ZERO_FILES_DETAIL
            else:
                row.status = "ready"
                row.status_detail = None
            await session.commit()


# asyncio only holds a *weak* reference to a bare create_task(), so a
# long-running clone+embed could be garbage-collected mid-flight. Keep a strong
# reference until the task finishes (discarded via the done callback).
_repo_ingest_tasks: set[asyncio.Task] = set()


def _spawn_repo_ingest(repo_id: str) -> None:
    task = asyncio.create_task(_run_repo_ingest(repo_id))
    _repo_ingest_tasks.add(task)
    task.add_done_callback(_repo_ingest_tasks.discard)


@router.post("/kb-repos")
async def create_kb_repo(body: KbRepoCreateRequest, session: AsyncSession = Depends(get_session)):
    """Register a new Git-repo KB and kick off background ingestion."""
    from kb_repo_service import descriptor_from_repo, encrypt_token, make_repo_id

    is_private = body.visibility == "private"
    token = body.auth_token.strip() if is_private and body.auth_token else None

    row = KbRepo(
        id=make_repo_id(body.name),
        name=body.name,
        git_url=body.git_url,
        git_ref=body.git_ref,
        include_globs=body.include_globs,
        auth_token_encrypted=encrypt_token(token) if token else None,
        status="queued",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    _kb_registry.register_descriptor(descriptor_from_repo(row, token=token))
    _spawn_repo_ingest(row.id)

    return _serialize_kb_repo(row)


@router.get("/kb-repos")
async def list_kb_repos(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(KbRepo).order_by(KbRepo.created_at))).scalars().all()
    return {"repos": [_serialize_kb_repo(r) for r in rows]}


@router.get("/kb-repos/{repo_id}")
async def get_kb_repo(repo_id: str, session: AsyncSession = Depends(get_session)):
    row = await session.get(KbRepo, repo_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": f"Unknown repo: {repo_id!r}"})
    return _serialize_kb_repo(row)


@router.post("/kb-repos/{repo_id}/resync")
async def resync_kb_repo(repo_id: str, session: AsyncSession = Depends(get_session)):
    row = await session.get(KbRepo, repo_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": f"Unknown repo: {repo_id!r}"})
    row.status = "queued"
    row.status_detail = None
    await session.commit()
    await session.refresh(row)

    _spawn_repo_ingest(repo_id)
    return _serialize_kb_repo(row)


@router.delete("/kb-repos/{repo_id}")
async def delete_kb_repo(repo_id: str, session: AsyncSession = Depends(get_session)):
    row = await session.get(KbRepo, repo_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error": f"Unknown repo: {repo_id!r}"})

    from vector_store import get_vector_store

    await asyncio.to_thread(get_vector_store().delete_kb, repo_id)
    _kb_registry.unregister_descriptor(repo_id)
    await session.delete(row)
    await session.commit()
    return {"ok": True}


# ── Entity (rule) detail — the rule card, for entity-capable KBs only ────────


def _require_entity_kb(kb_id: str):
    """Resolve a KB and 404 unless it exposes addressable entities (rules).
    The rule card is only meaningful for structured/hybrid KBs; a rag-only KB
    has no rule to render."""
    provider = get_provider(kb_id)
    if "entity" not in provider.capabilities():
        raise HTTPException(
            status_code=404,
            detail={"error": f"Knowledge base {kb_id!r} has no addressable entities."},
        )
    return provider


def _build_rule_response(rule_id: str) -> dict:
    """Full rule-card payload: business explanation, technical YAML, SAP field
    table, lineage/workflow, origin, and cross-rule references. Restored with
    the sap_mapper/rule_parser/lineage_service modules for the rule card."""
    rules = get_rules()
    get_yaml_rules()  # warm the cache

    match = rules[rules["rule_id"].str.upper() == rule_id.upper()]
    if match.empty:
        raise HTTPException(status_code=404, detail={"error": "Rule not found"})

    row = match.iloc[0]
    excel_logic = str(row.get("rule_logic", "") or "")

    yaml_match = find_yaml_for_rule(rule_id)
    if yaml_match:
        yaml_filename = yaml_match["yaml_file"]
        technical_rule = extract_rule_section_from_yaml(get_yaml_raw(yaml_filename), rule_id)
        yaml_ref = yaml_filename
    else:
        technical_rule = excel_logic
        yaml_ref = ""

    raw_fields = extract_sap_fields(excel_logic)
    mapped_fields = [lookup_sap_field(f) for f in raw_fields]
    ctx = explanation_engine.build_sap_context(mapped_fields)
    explanation = explanation_engine.explain_rule(excel_logic, ctx)

    lin = get_lineage(rule_id)
    workflow_steps = lin.get("workflow_steps", [])
    if not yaml_ref:
        yaml_ref = lin.get("yaml_reference", "")
    sources = lin.get("pipeline_sources", [])

    origin_parts = []
    for key in ("module", "group", "sub_domain", "quality_category"):
        val = str(row.get(key, "") or "").strip()
        if val and val.lower() not in ("nan", "none", ""):
            origin_parts.append(val)
    origin = " / ".join(origin_parts)

    referenced_rules = [
        {
            "rule_id": ref["rule_id"],
            "source": ref["source"],
            "active": ref.get("active", False),
            "description": ref.get("rule_description", ""),
            "quality_category": ref.get("quality_category", ""),
            "severity": ref.get("severity", ""),
        }
        for ref in get_referenced_rules(rule_id)
    ]

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


@router.get("/kb/{kb_id}/entity/{entity_id}")
async def get_kb_entity(
    kb_id: str, entity_id: str, session: AsyncSession = Depends(get_session),
):
    """Full rule card for one entity. 409 for a repo KB still ingesting
    (checked first — a clean "still preparing" beats a confusing 404, since a
    repo KB is rag-only and would otherwise 404 on the entity-capability
    check below regardless of ingestion state); 404 for a KB without
    addressable entities (e.g. a rag-only docs KB)."""
    block = await _repo_block_reason(session, kb_id)
    if block is not None:
        descriptor = _kb_registry.get_descriptor(kb_id)
        _raise_repo_not_ready(kb_id, *block, descriptor.name if descriptor else None)
    _require_entity_kb(kb_id)
    return _build_rule_response(entity_id)


@router.get("/kb/{kb_id}/entities/related/{entity_id}")
async def get_kb_related_entities(
    kb_id: str, entity_id: str, session: AsyncSession = Depends(get_session),
):
    """Up to 4 rules sharing this rule's category or table."""
    block = await _repo_block_reason(session, kb_id)
    if block is not None:
        descriptor = _kb_registry.get_descriptor(kb_id)
        _raise_repo_not_ready(kb_id, *block, descriptor.name if descriptor else None)
    _require_entity_kb(kb_id)
    rules = get_rules()
    match = rules[rules["rule_id"].str.upper() == entity_id.upper()]
    if match.empty:
        raise HTTPException(status_code=404, detail={"error": "Rule not found"})

    row = match.iloc[0]
    category = str(row.get("quality_category", "") or "").strip()
    table = str(row.get("table_name_checked", "") or "").strip()
    others = rules[rules["rule_id"].str.upper() != entity_id.upper()]

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

    return [
        {
            "rule_id": str(r.get("rule_id", "") or ""),
            "quality_category": str(r.get("quality_category", "") or ""),
            "severity": str(r.get("severity", "") or ""),
            "table_checked": str(r.get("table_name_checked", "") or ""),
        }
        for _, r in others[combined].head(4).iterrows()
    ]


# ── Prompt enhance / save (Phase 6) ─────────────────────────────────────────


@router.post("/kb/{kb_id}/prompt/enhance")
async def enhance_kb_prompt(kb_id: str, body: PromptEnhanceRequest):
    """AI-rewrite a user's rough draft into a reviewable system-prompt
    fragment for this KB (Settings → custom prompt → "Enhance with AI").

    Non-streaming, standard tier. This is a *preview* only — it persists
    nothing; the caller reviews/edits the result and saves it separately via
    PUT /kb/{kb_id}/prompt, which is what actually makes it take effect.
    """
    descriptor = _kb_registry.get_descriptor(kb_id)
    if descriptor is None:
        raise HTTPException(status_code=404, detail={"error": f"Unknown knowledge base: {kb_id!r}"})

    draft = body.draft.strip()
    if not draft:
        raise HTTPException(status_code=400, detail={"error": "draft must not be blank."})

    system_prompt = prompts.build_enhance_system_prompt(descriptor)
    try:
        enhanced = await explanation_engine.call_openai_async(
            system_prompt,
            draft,
            max_tokens=800,
            tier="standard",
            call_type="prompt_enhance",
            knowledge_base_id=descriptor.id,
        )
    except Exception as exc:
        # Token tracking inside call_openai_async is already fire-and-forget
        # (best-effort); this only guards the generation call itself.
        log.error("[ERROR] /kb/%s/prompt/enhance failed: %s", kb_id, type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail={"error": "The AI service is temporarily unavailable. Please try again."},
        )

    return {
        "draft": body.draft,
        "enhanced": enhanced,
        "model": explanation_engine.model_for_tier("standard"),
    }


@router.put("/kb/{kb_id}/prompt")
async def save_kb_prompt(
    kb_id: str, body: PromptSaveRequest, session: AsyncSession = Depends(get_session),
):
    """Persist the reviewed custom/enhanced prompt for a KB (Settings → Save).

    Upserts the `knowledge_bases` row. No cache to clear: chat handlers read
    the saved enhanced_prompt fresh on every request via cs.get_kb_prompt()
    and inject it through prompts.build_system_prompt (Phase 5), so this
    takes effect on the very next chat call for this KB — no invalidation
    step needed.
    """
    descriptor = _kb_registry.get_descriptor(kb_id)
    if descriptor is None:
        raise HTTPException(status_code=404, detail={"error": f"Unknown knowledge base: {kb_id!r}"})

    row = await cs.save_kb_prompt(
        session, kb_id, body.custom_prompt, body.enhanced_prompt, name=descriptor.name,
    )
    return {
        "id": row.id,
        "custom_prompt": row.custom_prompt,
        "enhanced_prompt": row.enhanced_prompt,
        "prompt_updated_at": row.prompt_updated_at.isoformat() if row.prompt_updated_at else None,
    }


# ── Feedback ─────────────────────────────────────────────────────────────────


async def _feedback_handler(kb_id_path: str | None, body: FeedbackRequest) -> dict:
    """Shared body for /feedback and /kb/{kb_id}/feedback."""
    provider = get_provider(kb_id_path)
    await track_feedback(body.rating, body.mode, body.rule_id, knowledge_base_id=provider.kb.id)
    return {"ok": True}


@router.post("/feedback")
async def submit_feedback(body: FeedbackRequest):
    """Record a thumbs up/down on an assistant answer (active/default KB)."""
    return await _feedback_handler(None, body)


@router.post("/kb/{kb_id}/feedback")
async def kb_submit_feedback(kb_id: str, body: FeedbackRequest):
    """Record a thumbs up/down scoped to a specific KB."""
    return await _feedback_handler(kb_id, body)


# ── Chat (non-streaming) ─────────────────────────────────────────────────────


def _history_for_agent(body: ChatRequest) -> list[dict] | None:
    """Convert validated history to agent format, truncating long items server-side."""
    return [
        {"role": m.role, "content": m.content[:_MAX_HISTORY_ITEM_LEN]}
        for m in body.history
    ] or None


def _resolve_chat_provider(
    kb_id_path: str | None, body_kb_id: str | None, conversation_kb: str | None = None,
):
    """Explicit-selection precedence for the chat routes: a scoped route's URL
    path segment wins over the request body's knowledge_base_id, which in turn
    is the "explicit kb_id" get_provider() weighs against the conversation's
    stored KB / the active KB (see get_provider's own precedence)."""
    return get_provider(kb_id_path or body_kb_id, conversation_kb)


async def _chat_handler(
    kb_id_path: str | None, body: ChatRequest, session: AsyncSession,
) -> dict:
    """Shared body for /chat and /kb/{kb_id}/chat."""
    if len(body.message.strip()) > _MAX_MESSAGE_LEN:
        raise HTTPException(
            status_code=400,
            detail={"detail": f"Message exceeds maximum length of {_MAX_MESSAGE_LEN} characters."},
        )
    try:
        provider = _resolve_chat_provider(kb_id_path, body.knowledge_base_id)
        block = await _repo_block_reason(session, provider.kb.id)
        if block is not None:
            _raise_repo_not_ready(provider.kb.id, *block, provider.kb.name)
        custom_prompt = await cs.get_kb_prompt(session, provider.kb.id)
        history = _history_for_agent(body)
        result = handle_message(
            body.message, body.context_rule_id, history=history, allow_general=body.general,
            provider=provider, custom_prompt=custom_prompt,
        )
        asyncio.create_task(track_chat_event(
            result.get("rule_id") or body.context_rule_id, None, knowledge_base_id=provider.kb.id,
        ))
        return result
    except HTTPException:
        raise  # let rate-limiter, auth, and KB-resolution exceptions propagate as-is
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


@router.post("/chat")
@limiter.limit(_chat_rate_limit)
async def chat(request: Request, body: ChatRequest, session: AsyncSession = Depends(get_session)):
    # async def is required for slowapi's decorator to work correctly on Python 3.12+.
    return await _chat_handler(None, body, session)


@router.post("/kb/{kb_id}/chat")
@limiter.limit(_chat_rate_limit)
async def kb_chat(
    request: Request, kb_id: str, body: ChatRequest, session: AsyncSession = Depends(get_session),
):
    return await _chat_handler(kb_id, body, session)


# ── Chat (streaming) ─────────────────────────────────────────────────────────


async def _chat_stream_handler(
    kb_id_path: str | None,
    body: ChatRequest,
    x_user: str | None,
    session: AsyncSession,
) -> StreamingResponse:
    """Shared body for /chat/stream and /kb/{kb_id}/chat/stream.

    Returns Server-Sent Events; each event is a JSON object on a `data:` line.
    Event types: {"type":"chunk","text":"..."} and
    {"type":"done","rule_id":"...","suggested_followups":[...]}.

    When body.conversation_id is set, history is loaded from the DB, both the
    user and assistant messages are persisted, project instructions (if any)
    are injected as context, and the conversation's own stored KB feeds into
    KB resolution (see _resolve_chat_provider / get_provider).
    """
    message = body.message.strip()

    # ── Resolve persistence context (conversation / instructions) ────────────
    history = _history_for_agent(body)
    extra_context: str | None = None
    conv_id = body.conversation_id
    user_id: int | None = None
    context_rule_id = body.context_rule_id
    conversation_kb: str | None = None

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
        conversation_kb = conv.knowledge_base_id
        db_hist = await cs.recent_history(session, conv_id)
        if db_hist:
            history = db_hist
        if conv.project_id is not None:
            extra_context = await cs.project_instructions(session, conv.project_id)
        # Persist the user turn before streaming.
        await cs.append_message(session, conv_id, "user", body.message)
        await session.commit()

    provider = _resolve_chat_provider(kb_id_path, body.knowledge_base_id, conversation_kb)
    resolved_kb_id = provider.kb.id

    # Validate before starting the generator — once StreamingResponse begins,
    # the HTTP 200 header is already sent and we cannot return a 4xx.
    block = await _repo_block_reason(session, resolved_kb_id)
    if block is not None:
        _raise_repo_not_ready(resolved_kb_id, *block, provider.kb.name)

    custom_prompt = await cs.get_kb_prompt(session, resolved_kb_id)

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
                provider=provider, custom_prompt=custom_prompt,
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
            asyncio.create_task(
                track_chat_event(resolved_rule_id, None, user_id, knowledge_base_id=resolved_kb_id)
            )
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


@router.post("/chat/stream")
@limiter.limit(_chat_rate_limit)
async def chat_stream(
    request: Request,
    body: ChatRequest,
    x_user: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
):
    return await _chat_stream_handler(None, body, x_user, session)


@router.post("/kb/{kb_id}/chat/stream")
@limiter.limit(_chat_rate_limit)
async def kb_chat_stream(
    request: Request,
    kb_id: str,
    body: ChatRequest,
    x_user: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
):
    return await _chat_stream_handler(kb_id, body, x_user, session)


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
async def admin_reload(kb: str | None = None):
    """Reload data sources from disk for one KB (`?kb=<id>`) or, with no `kb`
    query param, every registered KB's provider.

    Each provider's reload() validates the fresh data BEFORE swapping caches,
    so a broken file leaves the running app serving the previous data and
    this returns 503.
    """
    if kb is not None:
        provider = _kb_registry.get_provider(kb)
        if provider is None:
            raise HTTPException(status_code=404, detail={"error": f"Unknown knowledge base: {kb!r}"})
        # Explicit per-KB reload runs the provider's full reload — for a RAG KB
        # that means re-ingesting (clone + embed), which is deliberate here.
        targets = {kb: provider}
    else:
        # "Reload everything" hot-reloads structured data from disk cheaply. It
        # deliberately SKIPS RAG-only KBs: their reload() re-embeds the whole
        # corpus (network + cost), which must be triggered explicitly via
        # ?kb=<id> or `python -m ingest --kb <id>`, not as a side effect.
        targets = {
            descriptor.id: provider
            for descriptor in _kb_registry.list_descriptors()
            if (provider := _kb_registry.get_provider(descriptor.id)) is not None
            and "entity" in provider.capabilities()
        }

    try:
        counts: dict[str, dict] = {}
        for kb_id, provider in targets.items():
            counts[kb_id] = await asyncio.to_thread(provider.reload)
    except Exception as exc:
        log.error("[ERROR] /admin/reload failed: %s — %s", type(exc).__name__, exc)
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": f"Reload failed ({type(exc).__name__}) — previous data is still being served."},
        )

    # A single-KB reload (explicit ?kb=, or only one KB is registered) keeps
    # the original flat {"ok": True, **counts} shape for back-compat; only a
    # true multi-KB "reload everything" response nests per-KB results.
    if len(counts) == 1:
        return {"ok": True, **next(iter(counts.values()))}
    return {"ok": True, "results": counts}


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
    kb_id: str | None = None
    if body.knowledge_base_id and settings.enable_kb_switcher:
        if _kb_registry.get_descriptor(body.knowledge_base_id) is None:
            raise HTTPException(
                status_code=404,
                detail={"error": f"Unknown knowledge base: {body.knowledge_base_id!r}"},
            )
        kb_id = body.knowledge_base_id
    return await cs.create_conversation(
        session, user.id, persona=body.persona, project_id=body.project_id,
        title=body.title, context_rule_id=body.context_rule_id,
        knowledge_base_id=kb_id,
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
