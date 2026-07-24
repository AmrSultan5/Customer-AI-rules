"""
Tests for ingestion.py — ingest_kb() over local files (chunk + embed +
upsert, sha256 idempotency across re-ingest) and the Azure Repos git-clone
auth path. The embedder is mocked (embeddings._embed_batch_fn) and git is
mocked (ingestion.subprocess.run) throughout — no real OpenAI/network/git
calls are made anywhere in this file.
"""

import base64
import subprocess
from pathlib import Path

import pytest

import embeddings
import ingestion
from kb._schema import KBDescriptor
from vector_store import get_vector_store


def _fake_embed_batch(texts: list[str]) -> list[list[float]]:
    # Deterministic, cheap "embeddings" derived from text length so results
    # are stable within a test run without any real embedding model.
    return [[float(len(t) % 7), float(len(t) % 5), 1.0] for t in texts]


@pytest.fixture(autouse=True)
def _mock_embedder(monkeypatch):
    monkeypatch.setattr(embeddings, "_embed_batch_fn", _fake_embed_batch)


def _rag_descriptor(kb_id: str, roots: list[str], **rag_kwargs) -> KBDescriptor:
    return KBDescriptor(
        id=kb_id,
        name="Test RAG KB",
        description="A rag-only test KB for ingestion tests.",
        adapter="rag",
        retrieval_mode="rag",
        source={"kind": "rag", "roots": roots, **rag_kwargs},
        id_pattern=r"\b([A-Z]{2,8}_\d+)\b",
        vocab={"entity_singular": "doc", "entity_plural": "docs"},
        prompts={"repository_label": "Docs"},
    )


def _structured_only_descriptor(kb_id: str) -> KBDescriptor:
    return KBDescriptor(
        id=kb_id,
        name="Structured only",
        description="No rag source at all.",
        adapter="structured",
        retrieval_mode="structured",
        source={"kind": "structured", "files": {}, "dirs": {}},
        id_pattern=r"\b([A-Z]{2,8}_\d+)\b",
        vocab={"entity_singular": "x", "entity_plural": "xs"},
        prompts={"repository_label": "X"},
    )


# ── Local-file ingestion: chunk + embed + upsert ────────────────────────────


def test_ingest_kb_chunks_embeds_and_upserts_local_files(tmp_path):
    (tmp_path / "a.md").write_text("Hello world. " * 50, encoding="utf-8")
    (tmp_path / "b.txt").write_text("Another document about testing.", encoding="utf-8")
    descriptor = _rag_descriptor("test_ingest_local", [str(tmp_path)])

    counts = ingestion.ingest_kb(descriptor)

    assert counts["documents"] == 2
    assert counts["chunks"] >= 2
    assert counts["skipped"] == 0

    store = get_vector_store()
    assert store.count(descriptor.id) == counts["chunks"]


def test_ingest_kb_no_rag_source_is_a_noop():
    descriptor = _structured_only_descriptor("test_ingest_structured_only")
    counts = ingestion.ingest_kb(descriptor)
    assert counts == {"documents": 0, "chunks": 0, "skipped": 0}


# ── sha256 idempotency across re-ingest ─────────────────────────────────────


def test_reingest_skips_unchanged_files(tmp_path):
    (tmp_path / "a.md").write_text("Stable content that does not change.", encoding="utf-8")
    descriptor = _rag_descriptor("test_ingest_idempotent", [str(tmp_path)])

    first = ingestion.ingest_kb(descriptor)
    assert first["documents"] == 1
    assert first["skipped"] == 0
    assert first["chunks"] >= 1

    second = ingestion.ingest_kb(descriptor)
    assert second["documents"] == 0
    assert second["skipped"] == 1
    assert second["chunks"] == 0

    store = get_vector_store()
    assert store.count(descriptor.id) == first["chunks"]  # nothing duplicated


def test_reingest_reembeds_changed_file_and_replaces_its_chunks(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("Version one of the document.", encoding="utf-8")
    descriptor = _rag_descriptor("test_ingest_changed", [str(tmp_path)])

    first = ingestion.ingest_kb(descriptor)
    assert first["documents"] == 1

    f.write_text("Version two, with substantially different content that changes the sha256 hash.", encoding="utf-8")
    second = ingestion.ingest_kb(descriptor)

    assert second["documents"] == 1
    assert second["skipped"] == 0

    store = get_vector_store()
    # Old chunks were replaced, not accumulated alongside the new ones.
    assert store.count(descriptor.id) == second["chunks"]


# ── Azure DevOps Repos git-clone auth path (subprocess fully mocked) ───────


def test_git_clone_uses_http_extra_header_basic_auth_and_never_logs_the_pat(monkeypatch, tmp_path, caplog):
    captured: dict = {}

    def fake_run(cmd, check, capture_output, text):
        captured["cmd"] = cmd
        dest = Path(cmd[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "doc.md").write_text("Cloned content from the mocked repo.", encoding="utf-8")

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    monkeypatch.setattr(ingestion.subprocess, "run", fake_run)
    monkeypatch.setenv("TEST_REPO_PAT", "super-secret-pat-value")

    descriptor = _rag_descriptor(
        "test_ingest_git",
        roots=[],
        git_url="https://dev.azure.com/org/project/_git/repo",
        git_ref="main",
        auth_token_env="TEST_REPO_PAT",
    )

    with caplog.at_level("DEBUG"):
        counts = ingestion.ingest_kb(descriptor)

    assert counts["documents"] == 1
    assert counts["chunks"] >= 1

    cmd = captured["cmd"]

    # The bare repo URL is passed as-is — no embedded credentials.
    url_arg = next(c for c in cmd if c == descriptor.source.git_url)
    assert "super-secret-pat-value" not in url_arg
    assert "@dev.azure.com" not in url_arg

    # The PAT is sent via -c http.extraHeader="Authorization: Basic <b64>",
    # never the URL — this is the point of the mechanism, so the header
    # argument legitimately carries the (base64-encoded) token.
    header_arg = next(c for c in cmd if c.startswith("http.extraHeader="))
    token_b64 = base64.b64encode(b":super-secret-pat-value").decode("ascii")
    assert header_arg == f"http.extraHeader=Authorization: Basic {token_b64}"

    # The raw PAT must never appear in any emitted log record.
    for record in caplog.records:
        assert "super-secret-pat-value" not in record.getMessage()


def test_git_clone_without_pat_omits_auth_header(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_run(cmd, check, capture_output, text):
        captured["cmd"] = cmd
        dest = Path(cmd[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "doc.md").write_text("Public repo content.", encoding="utf-8")

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr(ingestion.subprocess, "run", fake_run)
    monkeypatch.delenv("PUBLIC_REPO_PAT", raising=False)

    descriptor = _rag_descriptor(
        "test_ingest_git_public",
        roots=[],
        git_url="https://dev.azure.com/org/project/_git/public-repo",
        auth_token_env="PUBLIC_REPO_PAT",
    )

    ingestion.ingest_kb(descriptor)

    cmd = captured["cmd"]
    assert not any(c.startswith("http.extraHeader=") for c in cmd)
    assert "-c" not in cmd


# ── classify_clone_error / is_clone_error_message (friendly classification) ─


@pytest.mark.parametrize(
    "stderr, expected",
    [
        (
            "remote: Authentication failed for 'https://dev.azure.com/org/project/_git/repo'",
            "Couldn't access the repository — check the access token (private repos require one).",
        ),
        (
            "fatal: could not read Username for 'https://dev.azure.com': terminal prompts disabled",
            "Couldn't access the repository — check the access token (private repos require one).",
        ),
        (
            "remote: TF401019: The Git repository with name or identifier does not exist",
            "Repository not found — check the Git URL and branch.",
        ),
        (
            "remote: Repository not found.",
            "Repository not found — check the Git URL and branch.",
        ),
        (
            "fatal: unable to access 'https://dev.azure.com/org/project/_git/repo/': Could not resolve host: dev.azure.com",
            "Couldn't reach the repository host — check the URL and your network.",
        ),
        (
            "fatal: unable to access 'https://dev.azure.com/x': Connection timed out",
            "Couldn't reach the repository host — check the URL and your network.",
        ),
    ],
)
def test_classify_clone_error_maps_known_keywords_to_friendly_reason(stderr, expected):
    exc = subprocess.CalledProcessError(returncode=128, cmd=["git", "clone"], output="", stderr=stderr)
    assert ingestion.classify_clone_error(exc) == expected


def test_classify_clone_error_falls_back_to_generic_message_with_exit_code():
    exc = subprocess.CalledProcessError(returncode=17, cmd=["git", "clone"], output="", stderr="some other git failure")
    message = ingestion.classify_clone_error(exc)
    assert message == "Couldn't clone the repository (git exited with code 17)."
    # The raw stderr text must never leak into the curated message.
    assert "some other git failure" not in message


def test_is_clone_error_message_recognizes_curated_and_generic_messages():
    assert ingestion.is_clone_error_message(
        "Couldn't access the repository — check the access token (private repos require one)."
    )
    assert ingestion.is_clone_error_message("Couldn't clone the repository (git exited with code 42).")
    assert not ingestion.is_clone_error_message("Some unrelated RuntimeError text.")


def test_clone_git_repo_raises_friendly_message_never_raw_stderr_or_pat(monkeypatch, tmp_path):
    def fake_run(cmd, check, capture_output, text):
        raise subprocess.CalledProcessError(
            returncode=128,
            cmd=cmd,
            output="",
            stderr="remote: Authentication failed for 'https://dev.azure.com/org/project/_git/repo'",
        )

    monkeypatch.setattr(ingestion.subprocess, "run", fake_run)
    monkeypatch.setenv("CLONE_FAIL_PAT", "super-secret-pat-value")

    from kb._schema import RagSource

    rag_source = RagSource(
        roots=[],
        git_url="https://dev.azure.com/org/project/_git/repo",
        auth_token_env="CLONE_FAIL_PAT",
    )

    with pytest.raises(RuntimeError) as exc_info:
        ingestion._clone_git_repo(rag_source, tmp_path / "dest")

    message = str(exc_info.value)
    assert message == "Couldn't access the repository — check the access token (private repos require one)."
    assert "super-secret-pat-value" not in message
    assert "Authentication failed" not in message
