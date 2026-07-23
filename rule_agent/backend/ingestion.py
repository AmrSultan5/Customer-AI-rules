"""
ingestion.py — walk a KB's RAG source, chunk + embed changed files, and
upsert them into the vector store (Phase 8a).

`ingest_kb(descriptor)` is the single entry point (also reachable via
`python -m ingest --kb <id>` and per-KB `/admin/reload`, providers/rag.py's
RagProvider.reload). It:

  1. Resolves the descriptor's rag source (RagSource directly for a rag-only
     KB, or HybridSource.rag for a hybrid one). Returns a zero-count no-op if
     there isn't one — this is how customer_sap (hybrid, `source.rag: null`
     in this phase) stays completely un-ingested and byte-identical.
  2. If the source has a `git_url` (an Azure DevOps Repos URL), shallow-clones
     it into a temp dir; for a private repo the PAT is read from
     `os.environ[auth_token_env]` and passed via the Azure-recommended
     `-c http.extraHeader="Authorization: Basic <base64(':'+PAT)>"` git
     config flag — never embedded in the URL and never logged (see
     `_clone_git_repo`). The temp clone dir is always removed in a `finally`.
     Otherwise walks the local `roots` (relative to backend/, unless a root
     is already absolute — tests point `roots` straight at a tmp dir).
  3. Walks files per `include_globs`/`exclude_globs`, loads text (md/code
     read as UTF-8, `.pdf` via pypdf), and skips any file whose sha256 has not
     changed since the last successful ingest (tracked in `kb_documents`).
  4. Chunks changed files into ~800-word overlapping windows, batch-embeds
     via `embeddings.embed_texts`, and upserts into the configured
     `VectorStore` (replacing that document's previous chunks, if any).

Returns `{"documents": <new/changed>, "chunks": <embedded+upserted>,
"skipped": <unchanged>}`.
"""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from kb._schema import HybridSource, KBDescriptor, RagSource

log = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent

# ~800-token chunks, word-count approximation (a simple char/word split is
# enough for this phase — no tokenizer dependency).
_CHUNK_WORDS = 800
_CHUNK_OVERLAP_WORDS = 100

_TEXT_SUFFIXES_HINT = {".md", ".txt", ".py", ".yaml", ".yml", ".json", ".rst", ".sql", ".cfg", ".ini", ".toml"}
_PDF_SUFFIX = ".pdf"

# Never descend into VCS metadata regardless of the descriptor's exclude_globs.
_ALWAYS_SKIP_DIR_NAMES = {".git", ".hg", ".svn"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Source resolution ───────────────────────────────────────────────────────


def _resolve_rag_source(descriptor: KBDescriptor) -> RagSource | None:
    """A rag-only KB's source *is* the RagSource; a hybrid KB's is optional
    (HybridSource.rag); a structured-only KB has none."""
    source = descriptor.source
    if isinstance(source, RagSource):
        return source
    if isinstance(source, HybridSource):
        return source.rag
    return None


def _resolve_root(root_str: str) -> Path:
    p = Path(root_str)
    return p if p.is_absolute() else (_BACKEND_DIR / p)


# ── Azure DevOps Repos clone (git subprocess, fully mockable) ──────────────


def _clone_git_repo(rag_source: RagSource, dest_dir: Path) -> None:
    """Shallow-clone `rag_source.git_url` into `dest_dir`.

    For a private Azure DevOps repo, the PAT (read from
    `os.environ[rag_source.auth_token_env]`) is sent via the Azure-recommended
    HTTP Basic auth header — `-c http.extraHeader="Authorization: Basic
    <base64(':'+PAT)>"` — rather than embedded in the clone URL. The PAT
    itself is never logged: only the repo URL/ref are, and the constructed
    `cmd` list (which does contain the base64-encoded header value, as
    git requires) is passed straight to subprocess.run — it is never printed,
    logged, or otherwise persisted.
    """
    config_args: list[str] = []
    if rag_source.auth_token_env:
        pat = os.environ.get(rag_source.auth_token_env, "")
        if pat:
            token_b64 = base64.b64encode(f":{pat}".encode("utf-8")).decode("ascii")
            config_args = ["-c", f"http.extraHeader=Authorization: Basic {token_b64}"]

    cmd = ["git"] + config_args + ["clone", "--depth", "1"]
    if rag_source.git_ref:
        cmd += ["--branch", rag_source.git_ref]
    cmd += [rag_source.git_url, str(dest_dir)]

    log.info("[ingestion] git clone %s (ref=%s)", rag_source.git_url, rag_source.git_ref or "default")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        # Deliberately do not include `cmd` (carries the auth header) or raw
        # stderr (git may echo back the failing URL) in the raised message.
        raise RuntimeError(
            f"git clone failed for {rag_source.git_url!r} (ref={rag_source.git_ref!r}), exit={exc.returncode}"
        ) from None


# ── File walking ────────────────────────────────────────────────────────────


def _is_excluded(rel_posix: str, exclude_globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel_posix, pat) for pat in exclude_globs)


def _iter_files(root_dirs: list[Path], include_globs: list[str], exclude_globs: list[str]):
    """Yield (root_dir, path, rel_label) for every file under root_dirs that
    matches include_globs and not exclude_globs. rel_label is a
    root-relative, forward-slash path used as the stable kb_documents.path
    key (so re-ingesting a freshly re-cloned repo — a new temp dir each time
    — still resolves to the same document row)."""
    seen: set[Path] = set()
    for root in root_dirs:
        if not root.exists():
            continue
        for pattern in include_globs:
            for path in root.glob(pattern):
                if not path.is_file():
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                if any(part in _ALWAYS_SKIP_DIR_NAMES for part in path.relative_to(root).parts):
                    continue
                rel = path.relative_to(root).as_posix()
                if _is_excluded(rel, exclude_globs):
                    continue
                seen.add(resolved)
                yield root, path, f"{root.name}/{rel}"


# ── Text extraction ─────────────────────────────────────────────────────────


def _load_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        log.warning("[ingestion] pypdf not installed — skipping PDF %s", path.name)
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        log.warning("[ingestion] failed reading PDF %s: %s", path.name, type(exc).__name__)
        return ""


def _load_text(path: Path) -> str:
    if path.suffix.lower() == _PDF_SUFFIX:
        return _load_pdf_text(path)
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        log.warning("[ingestion] failed reading %s: %s", path.name, type(exc).__name__)
        return ""


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


# ── Chunking ─────────────────────────────────────────────────────────────────


def _chunk_text(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    step = max(_CHUNK_WORDS - _CHUNK_OVERLAP_WORDS, 1)
    chunks: list[str] = []
    start = 0
    while start < len(words):
        window = words[start : start + _CHUNK_WORDS]
        chunks.append(" ".join(window))
        if start + _CHUNK_WORDS >= len(words):
            break
        start += step
    return chunks


# ── Ingestion ────────────────────────────────────────────────────────────────


def ingest_kb(descriptor: KBDescriptor) -> dict:
    """Ingest `descriptor`'s rag source into the vector store. See module
    docstring for the full flow. Returns {"documents", "chunks", "skipped"}."""
    rag_source = _resolve_rag_source(descriptor)
    counts = {"documents": 0, "chunks": 0, "skipped": 0}
    if rag_source is None:
        log.debug("[ingestion] kb=%s has no rag source configured — nothing to ingest", descriptor.id)
        return counts

    import db
    from models import KbChunk, KbDocument
    from sqlalchemy import select
    from vector_store import get_vector_store

    import embeddings

    store = get_vector_store()

    tmp_dir: Path | None = None
    try:
        if rag_source.git_url:
            tmp_dir = Path(tempfile.mkdtemp(prefix="rule_agent_rag_"))
            _clone_git_repo(rag_source, tmp_dir)
            root_dirs = [tmp_dir / r for r in rag_source.roots] if rag_source.roots else [tmp_dir]
        else:
            root_dirs = [_resolve_root(r) for r in rag_source.roots]

        include_globs = rag_source.include_globs or ["**/*"]
        exclude_globs = rag_source.exclude_globs or []

        with db.SyncSessionLocal() as session:
            for _root, path, rel_label in _iter_files(root_dirs, include_globs, exclude_globs):
                sha = _sha256_of_file(path)

                existing_doc = session.execute(
                    select(KbDocument).where(
                        KbDocument.kb_id == descriptor.id, KbDocument.path == rel_label
                    )
                ).scalar_one_or_none()

                if existing_doc is not None and existing_doc.sha256 == sha:
                    counts["skipped"] += 1
                    continue

                text = _load_text(path)
                chunk_texts = _chunk_text(text)

                if existing_doc is None:
                    existing_doc = KbDocument(kb_id=descriptor.id, path=rel_label, sha256=sha)
                    session.add(existing_doc)
                    session.flush()  # assign existing_doc.id
                else:
                    existing_doc.sha256 = sha
                    existing_doc.updated_at = _utcnow()
                    # Drop this document's stale chunks before re-embedding —
                    # upsert_chunks only inserts, it doesn't replace.
                    session.query(KbChunk).filter(KbChunk.document_id == existing_doc.id).delete()
                session.commit()

                counts["documents"] += 1

                if not chunk_texts:
                    continue  # e.g. an empty file — document recorded, no chunks

                vectors = embeddings.embed_texts(chunk_texts)
                chunk_dicts = [
                    {
                        "document_id": existing_doc.id,
                        "chunk_index": i,
                        "text": t,
                        "source_ref": f"{rel_label}#{i}",
                        "embedding": vec,
                    }
                    for i, (t, vec) in enumerate(zip(chunk_texts, vectors))
                ]
                store.upsert_chunks(descriptor.id, chunk_dicts)
                counts["chunks"] += len(chunk_dicts)

        return counts
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
