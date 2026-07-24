"""
kb_repo_service.py — self-service "add a Git repo" knowledge bases (Phase 9).

Turns one `kb_repos` row (models.KbRepo) into a runnable KBDescriptor
(descriptor_from_repo), and provides the supporting helpers main.py's
POST/GET/DELETE /kb-repos endpoints need:

  - make_repo_id(name): a URL-safe, unique kb_id slug used as both the
    kb_repos primary key and the RAG kb_id everything else (ingestion.py,
    vector_store.py, chat routing) scopes by.
  - encrypt_token / decrypt_token: at-rest protection for a private repo's
    PAT (kb_repos.auth_token_encrypted), using Fernet keyed by
    settings.kb_repo_secret_key when BOTH it is set AND the `cryptography`
    package is importable. Falls back to storing the token in plaintext
    otherwise — logging a one-time warning (never the token itself) — so the
    feature still works before a secret key is configured, while the safer
    path is what production is expected to run with.

The decrypted token is threaded through purely in memory (RagSource.
auth_token, kb._schema.py) — it is never written to a YAML file and never
logged; see ingestion._clone_git_repo, which prefers it over auth_token_env.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
from typing import Any

from config import settings
from kb._schema import KBDescriptor, Prompts, RagSource, Vocab

log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_ID_LEN = 64
_HASH_SUFFIX_HEX_CHARS = 8

_DEFAULT_INCLUDE_GLOBS = ["**/*.md"]

# Generic document-Q&A analyst prompt, in the style of kb/docs_demo.yaml's
# prompts.analyst_system — {repository_label} is substituted later by
# prompts.build_system_prompt, so this must stay a literal (not an f-string).
_ANALYST_SYSTEM_TEMPLATE = (
    "You are a helpful assistant answering questions about {repository_label}. "
    "Answer using ONLY the context provided from the knowledge base. Cite the "
    'source file (shown after "Source:") when you use it. If the answer is not '
    "contained in the provided context, say you don't have that information and "
    "suggest what the user could ask about instead. Be clear and concise; do not "
    "invent details that are not in the context."
)

# Unused by RAG (no addressable entities), but KBDescriptor requires a pattern
# — same placeholder used by kb/docs_demo.yaml.
_ID_PATTERN = r"\b([A-Z]{2,8}_\d+(?:\.\d+)?)\b"

_warned_plaintext_fallback = False


# ── kb_id slug ───────────────────────────────────────────────────────────────


def make_repo_id(name: str) -> str:
    """URL-safe, unique kb_id: a lowercase `[a-z0-9-]` slug of `name` plus a
    short random hex suffix (so two repos named e.g. "Docs" don't collide),
    capped at 64 chars total — every kb_id column (kb_repos.id, kb_chunks.
    kb_id, kb_documents.kb_id, …) is String(64)."""
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-") or "repo"
    suffix = secrets.token_hex(_HASH_SUFFIX_HEX_CHARS // 2)
    max_slug_len = _MAX_ID_LEN - len(suffix) - 1  # -1 for the joining "-"
    slug = slug[:max_slug_len].rstrip("-") or "repo"
    return f"{slug}-{suffix}"


# ── Token encryption ─────────────────────────────────────────────────────────


def _fernet_key_from_secret(secret: str) -> bytes:
    """Derive a 32-byte urlsafe-base64 Fernet key from an arbitrary secret
    string — settings.kb_repo_secret_key need not itself be a valid Fernet
    key (it's whatever secret the deployment sets, e.g. a random token)."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet():
    """Fernet instance if settings.kb_repo_secret_key is set AND
    `cryptography` is importable; None otherwise (plaintext fallback). Warns
    exactly once per process either way — never logs the secret/token."""
    global _warned_plaintext_fallback
    if not settings.kb_repo_secret_key:
        if not _warned_plaintext_fallback:
            log.warning(
                "[kb_repo_service] kb_repo_secret_key is not configured — "
                "private repo tokens will be stored in PLAINTEXT. Set "
                "KB_REPO_SECRET_KEY to encrypt them at rest."
            )
            _warned_plaintext_fallback = True
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        if not _warned_plaintext_fallback:
            log.warning(
                "[kb_repo_service] the `cryptography` package is not "
                "installed — private repo tokens will be stored in "
                "PLAINTEXT despite kb_repo_secret_key being set."
            )
            _warned_plaintext_fallback = True
        return None
    return Fernet(_fernet_key_from_secret(settings.kb_repo_secret_key))


def encrypt_token(token: str) -> str:
    """Encrypt `token` for storage in kb_repos.auth_token_encrypted. Falls
    back to returning it unchanged when encryption isn't available (see
    _get_fernet) — the token itself is never logged either way."""
    fernet = _get_fernet()
    if fernet is None:
        return token
    return fernet.encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_token(stored: str) -> str:
    """Inverse of encrypt_token. If `stored` doesn't decrypt (it was saved in
    plaintext, or the secret key changed since), returns it unchanged rather
    than raising — a stale/invalid token should surface as a git-clone auth
    failure downstream, not an unhandled exception here."""
    fernet = _get_fernet()
    if fernet is None:
        return stored
    try:
        return fernet.decrypt(stored.encode("ascii")).decode("utf-8")
    except Exception:
        return stored


# ── Descriptor construction ──────────────────────────────────────────────────


def _parse_include_globs(include_globs: str | None) -> list[str]:
    if not include_globs or not include_globs.strip():
        return list(_DEFAULT_INCLUDE_GLOBS)
    return [g.strip() for g in include_globs.split(",") if g.strip()]


def descriptor_from_repo(row: Any, token: str | None = None) -> KBDescriptor:
    """Build a runnable rag KBDescriptor for one kb_repos row.

    `token` is the already-DECRYPTED PAT (or None for a public repo / no
    token) — the caller (main.py) is responsible for decrypt_token(row.
    auth_token_encrypted) first. Threaded onto RagSource.auth_token, which is
    in-memory-only (never serialized, never logged) — see kb._schema.RagSource.

    `row.git_url` may be None (Phase 10, a files-only KB created with no
    git_url — see main.py's create_kb_repo): the resulting RagSource then has
    no git_url and no roots, so ingestion.ingest_kb (a plain reload/resync)
    finds nothing to clone or walk and is a clean no-op — it neither adds nor
    deletes anything, leaving whatever POST /kb-repos/{id}/files has uploaded
    completely untouched.
    """
    description = (
        f"A Git-repo knowledge base ingested from {row.git_url}."
        if row.git_url
        else "A files-only knowledge base populated by uploaded documents."
    )
    return KBDescriptor(
        id=row.id,
        name=row.name,
        description=description,
        adapter="rag",
        retrieval_mode="rag",
        source=RagSource(
            kind="rag",
            git_url=row.git_url,
            git_ref=row.git_ref,
            include_globs=_parse_include_globs(row.include_globs),
            auth_token=token,
        ),
        id_pattern=_ID_PATTERN,
        vocab=Vocab(entity_singular="document", entity_plural="documents"),
        prompts=Prompts(
            repository_label=row.name,
            analyst_system=_ANALYST_SYSTEM_TEMPLATE,
        ),
    )
