"""
Tests for main.py's self-service Git-repo KB surface (Phase 9): POST/GET/
DELETE /kb-repos, POST /kb-repos/{id}/resync, GET /kbs filtering out
non-ready repo KBs, and the background ingestion helpers (_run_repo_ingest,
_register_and_reconcile_kb_repos).

Endpoint-shape tests stub main._run_repo_ingest (the fire-and-forget
ingestion coroutine) to an async no-op so they assert the HTTP response/DB row
deterministically without racing a real background task. _run_repo_ingest's
actual status transitions (queued -> ingesting -> ready/error) are exercised
directly via asyncio.run() against a captured reference to the real function,
with ingestion.ingest_kb mocked — no real git/network/OpenAI calls anywhere
in this file.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import db
import main
from main import app
from models import KbDocument, KbRepo

client = TestClient(app, raise_server_exceptions=False)

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# Captured before the autouse fixture below stubs main._run_repo_ingest, so the
# tests that exercise the real ingestion helper directly can still reach it.
_REAL_RUN_REPO_INGEST = main._run_repo_ingest


@pytest.fixture(autouse=True)
def _no_background_ingest(monkeypatch):
    """Replace the fire-and-forget ingestion coroutine with an async no-op so
    the endpoints under test don't race a real background clone/embed while we
    assert the response/DB row right after the HTTP call. (Patching
    _run_repo_ingest — not asyncio.create_task — leaves the event loop's own
    task machinery, which Starlette's TestClient relies on, untouched.)"""

    async def _noop(repo_id: str) -> None:
        return None

    monkeypatch.setattr(main, "_run_repo_ingest", _noop)
    yield


def _cleanup(repo_id: str) -> None:
    """Best-effort teardown mirroring DELETE /kb-repos/{id}, used directly so
    tests don't depend on that endpoint working to clean up after themselves."""
    from vector_store import get_vector_store

    get_vector_store().delete_kb(repo_id)
    main._kb_registry.unregister_descriptor(repo_id)

    async def _delete_row():
        async with db.AsyncSessionLocal() as session:
            row = await session.get(KbRepo, repo_id)
            if row is not None:
                await session.delete(row)
                await session.commit()

    asyncio.run(_delete_row())


async def _get_row(repo_id: str) -> KbRepo | None:
    async with db.AsyncSessionLocal() as session:
        return await session.get(KbRepo, repo_id)


async def _set_status(repo_id: str, status: str, **extra) -> None:
    async with db.AsyncSessionLocal() as session:
        row = await session.get(KbRepo, repo_id)
        row.status = status
        for k, v in extra.items():
            setattr(row, k, v)
        await session.commit()


# ── POST /kb-repos ───────────────────────────────────────────────────────────


def test_create_public_repo_returns_contract_shaped_response():
    r = client.post(
        "/kb-repos", headers=AUTH,
        json={"name": "Widgets Docs", "git_url": "https://example.com/widgets.git"},
    )
    try:
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {
            "id", "name", "git_url", "git_ref", "include_globs", "status",
            "status_detail", "documents", "chunks", "created_at", "updated_at",
        }
        assert body["name"] == "Widgets Docs"
        assert body["git_url"] == "https://example.com/widgets.git"
        assert body["git_ref"] is None
        assert body["include_globs"] is None
        assert body["status"] == "queued"
        assert body["status_detail"] is None
        assert body["documents"] is None
        assert body["chunks"] is None
        assert body["created_at"]
        assert body["updated_at"]

        # Registered synchronously — immediately resolvable for chat routing.
        provider = main._kb_registry.get_provider(body["id"])
        assert provider is not None
        assert provider.kb.id == body["id"]
    finally:
        _cleanup(r.json()["id"])


def test_create_private_repo_without_token_is_rejected():
    r = client.post(
        "/kb-repos", headers=AUTH,
        json={"name": "Private Repo", "git_url": "https://example.com/priv.git", "visibility": "private"},
    )
    assert r.status_code == 422


def test_create_private_repo_encrypts_token_and_never_returns_it(monkeypatch):
    pytest.importorskip("cryptography")
    from config import settings

    # With a secret key configured (and `cryptography` available), the stored
    # token is Fernet-encrypted at rest. Without a key the service falls back
    # to plaintext — covered separately in test_kb_repo_service.py.
    monkeypatch.setattr(settings, "kb_repo_secret_key", "a-test-secret-key-value")

    r = client.post(
        "/kb-repos", headers=AUTH,
        json={
            "name": "Private Repo",
            "git_url": "https://example.com/priv.git",
            "visibility": "private",
            "auth_token": "super-secret-pat",
        },
    )
    try:
        assert r.status_code == 200
        body = r.json()
        assert "auth_token" not in body
        assert "super-secret-pat" not in r.text

        row = asyncio.run(_get_row(body["id"]))
        assert row.auth_token_encrypted is not None
        assert "super-secret-pat" not in row.auth_token_encrypted
    finally:
        _cleanup(r.json()["id"])


def test_create_kb_repo_requires_auth():
    r = client.post("/kb-repos", json={"name": "X", "git_url": "https://example.com/x.git"})
    assert r.status_code == 401


# ── GET /kb-repos, GET /kb-repos/{id} ────────────────────────────────────────


def test_list_and_get_kb_repo():
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Listable", "git_url": "https://example.com/l.git"})
    repo_id = r.json()["id"]
    try:
        listed = client.get("/kb-repos", headers=AUTH)
        assert listed.status_code == 200
        ids = {row["id"] for row in listed.json()["repos"]}
        assert repo_id in ids

        got = client.get(f"/kb-repos/{repo_id}", headers=AUTH)
        assert got.status_code == 200
        assert got.json()["id"] == repo_id
    finally:
        _cleanup(repo_id)


def test_get_unknown_kb_repo_404s():
    r = client.get("/kb-repos/does-not-exist", headers=AUTH)
    assert r.status_code == 404


# ── POST /kb-repos/{id}/resync ───────────────────────────────────────────────


def test_resync_resets_status_to_queued():
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Resync Me", "git_url": "https://example.com/r.git"})
    repo_id = r.json()["id"]
    try:
        asyncio.run(_set_status(repo_id, "ready", documents=3, chunks=9))

        resynced = client.post(f"/kb-repos/{repo_id}/resync", headers=AUTH)
        assert resynced.status_code == 200
        assert resynced.json()["status"] == "queued"
        assert resynced.json()["status_detail"] is None
    finally:
        _cleanup(repo_id)


def test_resync_unknown_kb_repo_404s():
    r = client.post("/kb-repos/does-not-exist/resync", headers=AUTH)
    assert r.status_code == 404


# ── DELETE /kb-repos/{id} ─────────────────────────────────────────────────────


def test_delete_removes_row_chunks_and_descriptor():
    from vector_store import get_vector_store

    r = client.post("/kb-repos", headers=AUTH, json={"name": "Deletable", "git_url": "https://example.com/d.git"})
    repo_id = r.json()["id"]

    with db.SyncSessionLocal() as session:
        doc = KbDocument(kb_id=repo_id, path="a.md", sha256="x")
        session.add(doc)
        session.commit()
        doc_id = doc.id
    get_vector_store().upsert_chunks(repo_id, [
        {"document_id": doc_id, "chunk_index": 0, "text": "hi", "source_ref": "a.md#0", "embedding": [1.0, 0.0]},
    ])
    assert get_vector_store().count(repo_id) == 1

    deleted = client.delete(f"/kb-repos/{repo_id}", headers=AUTH)
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}

    assert get_vector_store().count(repo_id) == 0
    assert main._kb_registry.get_descriptor(repo_id) is None
    assert client.get(f"/kb-repos/{repo_id}", headers=AUTH).status_code == 404


def test_delete_unknown_kb_repo_404s():
    r = client.delete("/kb-repos/does-not-exist", headers=AUTH)
    assert r.status_code == 404


# ── GET /kbs exposes status/selectable and excludes only 'error' repos ──────


def test_list_kbs_includes_loading_repo_as_unselectable():
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Switcher Test", "git_url": "https://example.com/s.git"})
    repo_id = r.json()["id"]
    try:
        # Freshly created rows are 'queued' — included, but not selectable.
        kbs = client.get("/kbs", headers=AUTH).json()["knowledge_bases"]
        entry = next(kb for kb in kbs if kb["id"] == repo_id)
        assert entry["status"] == "queued"
        assert entry["selectable"] is False

        asyncio.run(_set_status(repo_id, "ingesting"))
        kbs = client.get("/kbs", headers=AUTH).json()["knowledge_bases"]
        entry = next(kb for kb in kbs if kb["id"] == repo_id)
        assert entry["status"] == "ingesting"
        assert entry["selectable"] is False

        asyncio.run(_set_status(repo_id, "ready"))
        kbs = client.get("/kbs", headers=AUTH).json()["knowledge_bases"]
        entry = next(kb for kb in kbs if kb["id"] == repo_id)
        assert entry["status"] == "ready"
        assert entry["selectable"] is True

        # A non-repo descriptor (e.g. customer_sap) is always included,
        # regardless of the kb_repos table, and always ready/selectable.
        static_entry = next(kb for kb in kbs if kb["id"] == "customer_sap")
        assert static_entry["status"] == "ready"
        assert static_entry["selectable"] is True
    finally:
        _cleanup(repo_id)


def test_list_kbs_excludes_error_repo_with_no_content():
    """Never successfully ingested (chunks null/0) — not usable, so it's left
    out of /kbs entirely; still visible via GET /kb-repos (Settings)."""
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Error Repo", "git_url": "https://example.com/e.git"})
    repo_id = r.json()["id"]
    try:
        asyncio.run(_set_status(
            repo_id, "error",
            status_detail="Repository not found — check the Git URL and branch.",
            chunks=0,
        ))

        kbs = client.get("/kbs", headers=AUTH).json()["knowledge_bases"]
        assert repo_id not in {kb["id"] for kb in kbs}

        # Still visible via GET /kb-repos (Settings), just not the switcher.
        repos = client.get("/kb-repos", headers=AUTH).json()["repos"]
        assert repo_id in {r["id"] for r in repos}
    finally:
        _cleanup(repo_id)


def test_list_kbs_includes_error_repo_with_prior_content_as_selectable():
    """A repo that failed a *reload* but still has content from its last
    good ingest stays usable — included, status 'error', selectable, and its
    status_detail is surfaced so the frontend can explain why."""
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Stale Repo", "git_url": "https://example.com/stale.git"})
    repo_id = r.json()["id"]
    try:
        asyncio.run(_set_status(
            repo_id, "error",
            status_detail="Couldn't reach the repository host — check the URL and your network.",
            documents=3, chunks=9,
        ))

        kbs = client.get("/kbs", headers=AUTH).json()["knowledge_bases"]
        entry = next(kb for kb in kbs if kb["id"] == repo_id)
        assert entry["status"] == "error"
        assert entry["selectable"] is True
        assert entry["status_detail"] == "Couldn't reach the repository host — check the URL and your network."
    finally:
        _cleanup(repo_id)


def test_list_kbs_status_detail_is_null_for_ready_and_non_repo_kbs():
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Ready Repo", "git_url": "https://example.com/ready.git"})
    repo_id = r.json()["id"]
    try:
        asyncio.run(_set_status(repo_id, "ready", documents=1, chunks=2))

        kbs = client.get("/kbs", headers=AUTH).json()["knowledge_bases"]
        entry = next(kb for kb in kbs if kb["id"] == repo_id)
        assert entry["status_detail"] is None

        static_entry = next(kb for kb in kbs if kb["id"] == "customer_sap")
        assert static_entry["status_detail"] is None
    finally:
        _cleanup(repo_id)


# ── _run_repo_ingest background helper (direct, deterministic) ──────────────


def _create_row_directly(repo_id: str, git_url: str = "https://example.com/direct.git") -> None:
    from kb_repo_service import descriptor_from_repo

    async def _create():
        async with db.AsyncSessionLocal() as session:
            row = KbRepo(id=repo_id, name="Direct", git_url=git_url, status="queued")
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    row = asyncio.run(_create())
    main._kb_registry.register_descriptor(descriptor_from_repo(row))


def test_run_repo_ingest_success_updates_status_and_counts(monkeypatch):
    repo_id = "test-ingest-success-repo"
    _create_row_directly(repo_id)
    try:
        monkeypatch.setattr("ingestion.ingest_kb", lambda descriptor: {"documents": 2, "chunks": 5, "skipped": 0})

        asyncio.run(_REAL_RUN_REPO_INGEST(repo_id))

        row = asyncio.run(_get_row(repo_id))
        assert row.status == "ready"
        assert row.status_detail is None
        assert row.documents == 2
        assert row.chunks == 5
    finally:
        _cleanup(repo_id)


def test_run_repo_ingest_failure_sets_error_status_with_friendly_detail(monkeypatch):
    repo_id = "test-ingest-failure-repo"
    _create_row_directly(repo_id)
    try:
        def _boom(descriptor):
            # Not one of ingestion's curated clone-failure messages — must
            # fall back to the generic "Update failed (<Type>)." form, never
            # echoing the raw exception text into status_detail.
            raise RuntimeError("some internal detail that must not leak")

        monkeypatch.setattr("ingestion.ingest_kb", _boom)

        asyncio.run(_REAL_RUN_REPO_INGEST(repo_id))

        row = asyncio.run(_get_row(repo_id))
        assert row.status == "error"
        assert row.status_detail == "Update failed (RuntimeError)."
        assert "some internal detail" not in row.status_detail
    finally:
        _cleanup(repo_id)


def test_run_repo_ingest_failure_passes_through_friendly_clone_message(monkeypatch):
    repo_id = "test-ingest-clone-failure-repo"
    _create_row_directly(repo_id)
    try:
        def _boom(descriptor):
            # This is exactly what ingestion._clone_git_repo now raises —
            # already a curated, friendly message; must pass through as-is.
            raise RuntimeError("Repository not found — check the Git URL and branch.")

        monkeypatch.setattr("ingestion.ingest_kb", _boom)

        asyncio.run(_REAL_RUN_REPO_INGEST(repo_id))

        row = asyncio.run(_get_row(repo_id))
        assert row.status == "error"
        assert row.status_detail == "Repository not found — check the Git URL and branch."
    finally:
        _cleanup(repo_id)


def test_run_repo_ingest_failure_after_prior_success_keeps_old_content_counts(monkeypatch):
    """A reload that fails must not wipe the documents/chunks recorded by the
    last successful ingest — that's the signal list_kbs/the 409 guard use to
    keep serving the old version."""
    repo_id = "test-ingest-reload-failure-repo"
    _create_row_directly(repo_id)
    asyncio.run(_set_status(repo_id, "ready", documents=3, chunks=12))
    try:
        def _boom(descriptor):
            raise RuntimeError("Couldn't reach the repository host — check the URL and your network.")

        monkeypatch.setattr("ingestion.ingest_kb", _boom)

        asyncio.run(_REAL_RUN_REPO_INGEST(repo_id))

        row = asyncio.run(_get_row(repo_id))
        assert row.status == "error"
        assert row.status_detail == "Couldn't reach the repository host — check the URL and your network."
        assert row.documents == 3
        assert row.chunks == 12
    finally:
        _cleanup(repo_id)


def test_run_repo_ingest_embeddings_failure_maps_to_friendly_message(monkeypatch):
    repo_id = "test-ingest-embeddings-failure-repo"
    _create_row_directly(repo_id)
    try:
        class FakeOpenAIError(Exception):
            pass

        FakeOpenAIError.__module__ = "openai._exceptions"

        def _boom(descriptor):
            raise FakeOpenAIError("401 invalid api key")

        monkeypatch.setattr("ingestion.ingest_kb", _boom)

        asyncio.run(_REAL_RUN_REPO_INGEST(repo_id))

        row = asyncio.run(_get_row(repo_id))
        assert row.status == "error"
        assert row.status_detail == (
            "Couldn't generate embeddings — the OpenAI API key may be missing or invalid."
        )
        assert "401" not in row.status_detail
    finally:
        _cleanup(repo_id)


# ── _friendly_ingest_error (unit) ────────────────────────────────────────────


def test_friendly_ingest_error_passes_through_curated_clone_message():
    exc = RuntimeError("Couldn't access the repository — check the access token (private repos require one).")
    assert main._friendly_ingest_error(exc) == (
        "Couldn't access the repository — check the access token (private repos require one)."
    )


def test_friendly_ingest_error_detects_openai_exception_by_module():
    class FakeAuthError(Exception):
        pass

    FakeAuthError.__module__ = "openai"
    assert main._friendly_ingest_error(FakeAuthError("bad key")) == (
        "Couldn't generate embeddings — the OpenAI API key may be missing or invalid."
    )


def test_friendly_ingest_error_generic_fallback_never_echoes_raw_text():
    exc = ValueError("connection string contains secret=abc123")
    message = main._friendly_ingest_error(exc)
    assert message == "Update failed (ValueError)."
    assert "secret=abc123" not in message


# ── Zero-files ingest → error, not ready ─────────────────────────────────────


def test_run_repo_ingest_zero_files_on_first_add_sets_error(monkeypatch):
    repo_id = "test-ingest-zero-files-repo"
    _create_row_directly(repo_id)
    try:
        monkeypatch.setattr(
            "ingestion.ingest_kb", lambda descriptor: {"documents": 0, "chunks": 0, "skipped": 0}
        )

        asyncio.run(_REAL_RUN_REPO_INGEST(repo_id))

        row = asyncio.run(_get_row(repo_id))
        assert row.status == "error"
        assert row.status_detail == (
            "No matching files found to ingest — check the include patterns (e.g. **/*.md)."
        )
    finally:
        _cleanup(repo_id)


def test_run_repo_ingest_zero_new_files_on_reload_with_prior_content_stays_ready(monkeypatch):
    """A reload that legitimately finds nothing changed (but the repo already
    has content from a prior successful ingest) must stay 'ready', not flip
    to 'error' — only a first-ever ingest with zero matches is an error."""
    repo_id = "test-ingest-zero-new-reload-repo"
    _create_row_directly(repo_id)
    asyncio.run(_set_status(repo_id, "ready", documents=2, chunks=6))
    try:
        monkeypatch.setattr(
            "ingestion.ingest_kb", lambda descriptor: {"documents": 0, "chunks": 0, "skipped": 2}
        )

        asyncio.run(_REAL_RUN_REPO_INGEST(repo_id))

        row = asyncio.run(_get_row(repo_id))
        assert row.status == "ready"
        assert row.status_detail is None
    finally:
        _cleanup(repo_id)


def test_run_repo_ingest_noop_if_row_deleted_before_it_runs():
    # No row created at all — must return quietly, not raise.
    asyncio.run(main._run_repo_ingest("no-such-repo-row"))


# ── Startup reconciliation ───────────────────────────────────────────────────


def test_register_and_reconcile_marks_interrupted_rows_as_error_and_reregisters():
    repo_id = "test-reconcile-repo"
    _create_row_directly(repo_id)
    asyncio.run(_set_status(repo_id, "ingesting"))
    try:
        main._kb_registry.unregister_descriptor(repo_id)  # simulate a fresh process

        asyncio.run(main._register_and_reconcile_kb_repos())

        assert main._kb_registry.get_descriptor(repo_id) is not None

        row = asyncio.run(_get_row(repo_id))
        assert row.status == "error"
        assert "restart" in row.status_detail.lower()
    finally:
        _cleanup(repo_id)


def test_register_and_reconcile_leaves_ready_rows_untouched():
    repo_id = "test-reconcile-ready-repo"
    _create_row_directly(repo_id)
    asyncio.run(_set_status(repo_id, "ready", documents=1, chunks=4))
    try:
        asyncio.run(main._register_and_reconcile_kb_repos())

        row = asyncio.run(_get_row(repo_id))
        assert row.status == "ready"
        assert row.documents == 1
        assert row.chunks == 4
    finally:
        _cleanup(repo_id)
