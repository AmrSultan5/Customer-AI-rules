"""
SQLAlchemy ORM models.

Chat workspace:
  User → Project → Conversation → Message

A conversation is bound to one persona (analyst / engineer / pm, defaulting to
"analyst") and optionally to a project; a project carries a short
standing-instructions string injected into every chat under it. Analytics
tables (chat events, feedback, token usage) live in the same database so
there is a single store.

Multi-KB: every Conversation/Project/Message/ChatEvent/FeedbackEvent/
TokenEvent row carries a `knowledge_base_id` (Phase 4) pointing at a row in
`KnowledgeBase`, so the same store can serve more than one registered KB
(backend/kb/*.yaml). `config.settings.active_kb` ("customer_sap") is the
Python-side default; a matching `server_default` keeps rows written directly
via SQL (e.g. the migration backfill) consistent. The HTTP API does not yet
accept/return this field — that lands in Phase 5.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config import settings
from db import Base

# Python-side default for every knowledge_base_id column below. Kept as a
# plain reference to config.settings so a non-default ACTIVE_KB is honored
# for rows created by the running app; the DDL-level server_default is a
# fixed literal ("customer_sap") since server-side defaults cannot reference
# runtime config.
_DEFAULT_KB_ID = settings.active_kb


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Chat workspace ───────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    projects: Mapped[list["Project"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # Short standing directive prepended to every chat in this project.
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nullable — unlike Conversation/Message, a project may span KBs (its
    # conversations each carry their own knowledge_base_id).
    knowledge_base_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=_DEFAULT_KB_ID, server_default="customer_sap"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    user: Mapped["User"] = relationship(back_populates="projects")
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="project"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Nullable: a conversation can live outside any project (a "loose" chat).
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    persona: Mapped[str] = mapped_column(String(16), default="analyst")
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    context_rule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(64), default=_DEFAULT_KB_ID, server_default="customer_sap"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    project: Mapped["Project | None"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    suggested_followups: Mapped[list | None] = mapped_column(JSON, nullable=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(64), default=_DEFAULT_KB_ID, server_default="customer_sap"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


# ── Knowledge bases ──────────────────────────────────────────────────────────


class KnowledgeBase(Base):
    """One row per registered KB descriptor (backend/kb/*.yaml), keyed by the
    descriptor's slug. Holds the user-editable custom/enhanced system-prompt
    text (Settings → custom prompt, Phase 6) — seeded at startup from the
    descriptor's id/name (see db.seed_knowledge_bases) without ever
    overwriting an already-saved prompt.
    """

    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    enhanced_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


# ── RAG storage (Phase 8a) ───────────────────────────────────────────────────
#
# One row per ingested source file (kb_documents) and one row per chunk of
# that file (kb_chunks), both scoped by kb_id so the same tables serve every
# registered KB. `embedding_json` stores the embedding vector as a JSON list
# of floats — portable across SQLite and Postgres and read directly by
# NumpyVectorStore (vector_store.py). On Postgres, migrations/m0002_rag.py
# additionally adds a native pgvector `embedding_vector` column (unmapped
# here — PgVectorStore talks to it via raw SQL) plus a cosine index; the two
# representations are populated together by ingestion.py so either backend
# can serve queries. Additive-only: no existing table/column changes.


class KbDocument(Base):
    """One row per source file ingested for a KB's RAG index. `sha256` of the
    file's raw bytes lets ingestion.ingest_kb skip re-embedding unchanged
    files on re-ingest (idempotent by content, not just by path/mtime)."""

    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    chunks: Mapped[list["KbChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KbChunk(Base):
    """One retrievable chunk of a KbDocument, with its embedding. Queried via
    vector_store.VectorStore (NumpyVectorStore reads embedding_json directly;
    PgVectorStore reads the parallel native `embedding_vector` column added
    by migrations/m0002_rag.py on Postgres)."""

    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["KbDocument"] = relationship(back_populates="chunks")


# ── Self-service Git-repo KBs (Phase 9) ─────────────────────────────────────
#
# One row per user-added "add a Git repo" knowledge base (POST /kb-repos in
# main.py). `id` doubles as the kb_id used everywhere else (kb_chunks,
# kb_documents, chat routing — see kb_repo_service.make_repo_id). `status`
# tracks the background ingestion lifecycle ("queued" -> "ingesting" ->
# "ready" | "error") so the frontend can poll GET /kb-repos/{id}; main.py's
# list_kbs filters a repo KB out of the switcher until it reaches "ready".


class KbRepo(Base):
    __tablename__ = "kb_repos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Nullable (Phase 10): a files-only KB (created via POST /kb-repos with no
    # git_url, populated purely by POST /kb-repos/{id}/files uploads) has no
    # repo to clone/resync — kb_repo_service.descriptor_from_repo's RagSource
    # then simply has nothing to clone/walk, so ingestion.ingest_kb /resync
    # is a no-op for it (uploaded chunks are untouched by a reload).
    git_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    git_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Comma-separated glob list as submitted by the caller; kb_repo_service
    # parses it into RagSource.include_globs. None/blank => a generic default.
    include_globs: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Fernet-encrypted (or, without KB_REPO_SECRET_KEY / the `cryptography`
    # package, plaintext — see kb_repo_service.py) PAT for a private repo.
    # Never returned by the API — see main.py._serialize_kb_repo.
    auth_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    documents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ── Analytics (migrated from the old SQLite analytics.db) ────────────────────


class ChatEvent(Base):
    __tablename__ = "chat_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(64), default=_DEFAULT_KB_ID, server_default="customer_sap"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=_utcnow
    )


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    rating: Mapped[str] = mapped_column(String(8))  # "up" | "down"
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(64), default=_DEFAULT_KB_ID, server_default="customer_sap"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=_utcnow
    )


class TokenEvent(Base):
    __tablename__ = "token_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    call_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(64), default=_DEFAULT_KB_ID, server_default="customer_sap"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=_utcnow
    )
