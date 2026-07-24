"""
Tests for the file-upload -> KB ingestion feature (Phase 10):

  - POST /kb-repos with no git_url -> a files-only KB (ready, empty).
  - POST /kb-repos/{id}/files -> multipart upload, per-file extract/chunk/
    embed/persist, mixed accept/reject batches, size cap, empty-file
    handling, and the repo row's documents/chunks/status being recomputed
    from the DB afterwards.
  - Uploaded chunks coexist with, and survive a resync of, a Git-repo KB
    (ingest_kb only ever re-walks the repo, never the "uploads/" path).

Embeddings are mocked (embeddings._embed_batch_fn, see test_ingestion.py's
identical fixture); git clone is mocked (ingestion.subprocess.run) for the
one test that exercises a real resync. No real OpenAI/network/git calls are
made anywhere in this file.
"""

import asyncio
import unittest.mock as mock
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import db
import embeddings
import main
from main import app
from models import KbDocument, KbRepo

client = TestClient(app, raise_server_exceptions=False)

TOKEN = "test-secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# Captured before the autouse fixture below stubs main._run_repo_ingest, so
# the resync-survival test can still reach the real ingestion helper.
_REAL_RUN_REPO_INGEST = main._run_repo_ingest


def _fake_embed_batch(texts: list[str]) -> list[list[float]]:
    # Deterministic, cheap "embeddings" derived from text length — same
    # scheme test_ingestion.py uses, so no real embedding model is called.
    return [[float(len(t) % 7), float(len(t) % 5), 1.0] for t in texts]


@pytest.fixture(autouse=True)
def _mock_embedder(monkeypatch):
    monkeypatch.setattr(embeddings, "_embed_batch_fn", _fake_embed_batch)


@pytest.fixture(autouse=True)
def _no_background_ingest(monkeypatch):
    """POST /kb-repos with a git_url still spawns background ingestion; stub
    it to a no-op by default so tests unrelated to that flow don't race it.
    The one test that needs the real ingestion path captures/uses
    _REAL_RUN_REPO_INGEST directly, bypassing this stub."""

    async def _noop(repo_id: str) -> None:
        return None

    monkeypatch.setattr(main, "_run_repo_ingest", _noop)
    yield


def _cleanup(repo_id: str) -> None:
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


# ── POST /kb-repos with no git_url -> files-only KB ─────────────────────────


def test_create_kb_repo_without_git_url_is_a_ready_empty_files_only_kb():
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Files Only KB"})
    try:
        assert r.status_code == 200
        body = r.json()
        assert body["git_url"] is None
        assert body["status"] == "ready"
        assert body["documents"] == 0
        assert body["chunks"] == 0

        # Registered synchronously — immediately resolvable for chat routing,
        # and no background clone was spawned (the no-op stub above would
        # make this indistinguishable from a real clone anyway, so the real
        # assertion is simply that creation succeeded without a git_url).
        provider = main._kb_registry.get_provider(body["id"])
        assert provider is not None
    finally:
        _cleanup(r.json()["id"])


def test_create_kb_repo_private_without_git_url_does_not_require_token():
    r = client.post(
        "/kb-repos", headers=AUTH,
        json={"name": "Files Only Private", "visibility": "private"},
    )
    try:
        assert r.status_code == 200
    finally:
        _cleanup(r.json()["id"])


def test_create_kb_repo_still_requires_token_for_private_git_repo():
    r = client.post(
        "/kb-repos", headers=AUTH,
        json={"name": "Private Git", "git_url": "https://example.com/priv.git", "visibility": "private"},
    )
    assert r.status_code == 422


# ── POST /kb-repos/{id}/files ────────────────────────────────────────────────


def test_upload_unknown_repo_404s():
    r = client.post(
        "/kb-repos/does-not-exist/files", headers=AUTH,
        files=[("files", ("a.md", b"hello", "text/markdown"))],
    )
    assert r.status_code == 404


def test_upload_requires_auth():
    r = client.post(
        "/kb-repos/whatever/files",
        files=[("files", ("a.md", b"hello", "text/markdown"))],
    )
    assert r.status_code == 401


def test_upload_mixed_batch_ingests_supported_and_rejects_unsupported():
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Upload Target"})
    repo_id = r.json()["id"]
    try:
        upload = client.post(
            f"/kb-repos/{repo_id}/files", headers=AUTH,
            files=[
                ("files", ("notes.md", b"# Title\n\nSome useful markdown content here.", "text/markdown")),
                ("files", ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png")),
            ],
        )
        assert upload.status_code == 200
        body = upload.json()

        assert set(body.keys()) == {"repo", "results"}
        assert set(body["repo"].keys()) == {
            "id", "name", "git_url", "git_ref", "include_globs", "status",
            "status_detail", "documents", "chunks", "created_at", "updated_at",
        }
        for result in body["results"]:
            assert set(result.keys()) == {"filename", "accepted", "chunks", "reason"}

        results_by_name = {res["filename"]: res for res in body["results"]}

        md_result = results_by_name["notes.md"]
        assert md_result["accepted"] is True
        assert md_result["chunks"] > 0
        assert md_result["reason"] is None

        png_result = results_by_name["photo.png"]
        assert png_result["accepted"] is False
        assert png_result["chunks"] == 0
        assert png_result["reason"] == (
            "Unsupported file type — upload documents, spreadsheets, PDFs, or text/code files."
        )

        repo = body["repo"]
        assert repo["status"] == "ready"
        assert repo["documents"] == 1
        assert repo["chunks"] == md_result["chunks"]

        # Persisted and queryable via the vector store — only the accepted
        # file's chunks were written.
        from vector_store import get_vector_store

        assert get_vector_store().count(repo_id) == md_result["chunks"]
    finally:
        _cleanup(repo_id)


def test_upload_empty_file_recorded_as_no_readable_text():
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Empty Upload Target"})
    repo_id = r.json()["id"]
    try:
        upload = client.post(
            f"/kb-repos/{repo_id}/files", headers=AUTH,
            files=[("files", ("blank.txt", b"", "text/plain"))],
        )
        assert upload.status_code == 200
        result = upload.json()["results"][0]
        assert result["accepted"] is False
        assert result["chunks"] == 0
        assert result["reason"] == "No readable text found in this file."

        # Nothing servable was written for it.
        assert upload.json()["repo"]["documents"] == 0
    finally:
        _cleanup(repo_id)


def test_upload_oversized_file_is_rejected(monkeypatch):
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Size Cap Target"})
    repo_id = r.json()["id"]
    try:
        monkeypatch.setattr(main, "_MAX_UPLOAD_BYTES", 10)  # tiny cap for the test
        upload = client.post(
            f"/kb-repos/{repo_id}/files", headers=AUTH,
            files=[("files", ("big.md", b"x" * 100, "text/markdown"))],
        )
        assert upload.status_code == 200
        result = upload.json()["results"][0]
        assert result["accepted"] is False
        assert result["chunks"] == 0
        assert result["reason"] == "File is too large (max 25 MB)."
        assert upload.json()["repo"]["documents"] == 0
    finally:
        _cleanup(repo_id)


def test_files_only_kb_becomes_populated_after_upload():
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Populate Me"})
    repo_id = r.json()["id"]
    try:
        assert r.json()["documents"] == 0

        upload = client.post(
            f"/kb-repos/{repo_id}/files", headers=AUTH,
            files=[("files", ("doc.md", b"Meaningful uploaded content for the KB.", "text/markdown"))],
        )
        repo = upload.json()["repo"]
        assert repo["documents"] == 1
        assert repo["chunks"] > 0
        assert repo["status"] == "ready"

        got = client.get(f"/kb-repos/{repo_id}", headers=AUTH)
        assert got.json()["documents"] == 1
        assert got.json()["chunks"] == repo["chunks"]
    finally:
        _cleanup(repo_id)


def test_reuploading_same_filename_replaces_rather_than_duplicates():
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Reupload Target"})
    repo_id = r.json()["id"]
    try:
        client.post(
            f"/kb-repos/{repo_id}/files", headers=AUTH,
            files=[("files", ("doc.md", b"Version one of the content.", "text/markdown"))],
        )

        second = client.post(
            f"/kb-repos/{repo_id}/files", headers=AUTH,
            files=[(
                "files",
                ("doc.md", b"Version two, a substantially different piece of content.", "text/markdown"),
            )],
        )
        second_repo = second.json()["repo"]
        # Still one document (same path) — chunks not accumulated across uploads.
        assert second_repo["documents"] == 1

        from vector_store import get_vector_store

        assert get_vector_store().count(repo_id) == second_repo["chunks"]
    finally:
        _cleanup(repo_id)


def test_multiple_uploaded_files_accumulate_as_separate_documents():
    r = client.post("/kb-repos", headers=AUTH, json={"name": "Multi Upload Target"})
    repo_id = r.json()["id"]
    try:
        upload = client.post(
            f"/kb-repos/{repo_id}/files", headers=AUTH,
            files=[
                ("files", ("one.md", b"First uploaded document content.", "text/markdown")),
                ("files", ("two.md", b"Second uploaded document content.", "text/markdown")),
            ],
        )
        repo = upload.json()["repo"]
        assert repo["documents"] == 2
        assert all(res["accepted"] for res in upload.json()["results"])
    finally:
        _cleanup(repo_id)


# ── Uploaded chunks coexist with, and survive a resync of, a repo KB ───────


def test_uploaded_chunks_survive_a_repo_resync():
    """A repo KB (git_url set) that also has uploaded files: a resync only
    re-walks the cloned repo (ingestion.ingest_kb never touches the
    "uploads/" path), so the uploaded document/chunks must still be present
    afterwards, alongside whatever the repo resync itself ingested."""
    import ingestion

    r = client.post(
        "/kb-repos", headers=AUTH,
        json={"name": "Repo Plus Uploads", "git_url": "https://example.com/repo-plus-uploads.git"},
    )
    repo_id = r.json()["id"]
    try:
        upload = client.post(
            f"/kb-repos/{repo_id}/files", headers=AUTH,
            files=[("files", ("notes.md", b"Uploaded content that must survive a resync.", "text/markdown"))],
        )
        assert upload.status_code == 200
        assert upload.json()["repo"]["documents"] == 1

        from vector_store import get_vector_store

        store = get_vector_store()
        before = store.count(repo_id)
        assert before > 0

        # Fake the git clone so ingest_kb has one real repo file to ingest,
        # then run the real resync ingestion helper directly (bypassing the
        # no-op stub this file's autouse fixture installs on POST /resync).
        def fake_run(cmd, check, capture_output, text):
            dest = Path(cmd[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "repo-doc.md").write_text("Content that actually lives in the repo.", encoding="utf-8")

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Result()

        with mock.patch.object(ingestion.subprocess, "run", fake_run):
            asyncio.run(_REAL_RUN_REPO_INGEST(repo_id))

        with db.SyncSessionLocal() as session:
            uploaded_doc = session.query(KbDocument).filter(
                KbDocument.kb_id == repo_id, KbDocument.path == "uploads/notes.md"
            ).one_or_none()
        assert uploaded_doc is not None

        after = store.count(repo_id)
        # At least the pre-resync (uploaded) chunks are still there, plus
        # whatever the repo resync itself ingested.
        assert after >= before
    finally:
        _cleanup(repo_id)
