"""
Tests for kb_repo_service.py — make_repo_id slug/uniqueness, descriptor_from_
repo building a valid KBDescriptor, and the token encrypt/decrypt roundtrip
(Fernet when `cryptography` + a secret key are available, plaintext fallback
otherwise). No network/DB access anywhere in this file.
"""

import re
from types import SimpleNamespace

import pytest

import kb_repo_service as svc
from kb._schema import KBDescriptor
from config import settings

_SLUG_CHARS = re.compile(r"^[a-z0-9-]{1,64}$")


def _row(**overrides):
    defaults = dict(
        id="doesnt-matter",
        name="Acme Widgets Docs",
        git_url="https://github.com/example/widgets.git",
        git_ref=None,
        include_globs=None,
        auth_token_encrypted=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── make_repo_id ─────────────────────────────────────────────────────────────


def test_make_repo_id_is_a_valid_slug():
    repo_id = svc.make_repo_id("Acme Widgets Docs!")
    assert _SLUG_CHARS.match(repo_id)
    assert len(repo_id) <= 64


def test_make_repo_id_is_unique_for_the_same_name():
    a = svc.make_repo_id("Same Name")
    b = svc.make_repo_id("Same Name")
    assert a != b


def test_make_repo_id_truncates_long_names_to_64_chars():
    long_name = "x" * 200
    repo_id = svc.make_repo_id(long_name)
    assert len(repo_id) <= 64
    assert _SLUG_CHARS.match(repo_id)


def test_make_repo_id_handles_empty_or_symbol_only_name():
    repo_id = svc.make_repo_id("!!!")
    assert _SLUG_CHARS.match(repo_id)
    assert repo_id.startswith("repo-")


# ── descriptor_from_repo ─────────────────────────────────────────────────────


def test_descriptor_from_repo_builds_a_valid_kbdescriptor():
    row = _row(id="widgets-docs-abcd1234", name="Widgets Docs", git_ref="main")
    descriptor = svc.descriptor_from_repo(row, token=None)

    assert isinstance(descriptor, KBDescriptor)
    assert descriptor.id == row.id
    assert descriptor.name == "Widgets Docs"
    assert descriptor.adapter == "rag"
    assert descriptor.retrieval_mode == "rag"
    assert descriptor.source.kind == "rag"
    assert descriptor.source.git_url == row.git_url
    assert descriptor.source.git_ref == "main"
    assert descriptor.source.auth_token is None
    assert descriptor.vocab.entity_singular == "document"
    assert descriptor.vocab.entity_plural == "documents"
    assert descriptor.prompts.repository_label == "Widgets Docs"
    assert "{repository_label}" in descriptor.prompts.analyst_system


def test_descriptor_from_repo_threads_the_decrypted_token_in_memory_only():
    row = _row()
    descriptor = svc.descriptor_from_repo(row, token="plain-pat-value")
    # Carried purely in memory on the RagSource for the clone (ingestion.
    # _clone_git_repo), and defaults back to None when no token is supplied.
    assert descriptor.source.auth_token == "plain-pat-value"
    assert svc.descriptor_from_repo(row).source.auth_token is None


def test_descriptor_from_repo_parses_comma_separated_include_globs():
    row = _row(include_globs=" **/*.md, **/*.txt ,,")
    descriptor = svc.descriptor_from_repo(row)
    assert descriptor.source.include_globs == ["**/*.md", "**/*.txt"]


def test_descriptor_from_repo_defaults_include_globs_when_blank():
    row = _row(include_globs=None)
    descriptor = svc.descriptor_from_repo(row)
    assert descriptor.source.include_globs == svc._DEFAULT_INCLUDE_GLOBS

    row_blank = _row(include_globs="   ")
    descriptor_blank = svc.descriptor_from_repo(row_blank)
    assert descriptor_blank.source.include_globs == svc._DEFAULT_INCLUDE_GLOBS


# ── Token encryption ──────────────────────────────────────────────────────────


def test_plaintext_fallback_when_no_secret_key_configured(monkeypatch):
    monkeypatch.setattr(settings, "kb_repo_secret_key", "")
    encrypted = svc.encrypt_token("my-pat")
    assert encrypted == "my-pat"
    assert svc.decrypt_token(encrypted) == "my-pat"


def test_encrypt_decrypt_roundtrip_with_cryptography(monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setattr(settings, "kb_repo_secret_key", "a-test-secret-key-value")

    encrypted = svc.encrypt_token("super-secret-pat")
    assert encrypted != "super-secret-pat"
    assert "super-secret-pat" not in encrypted

    decrypted = svc.decrypt_token(encrypted)
    assert decrypted == "super-secret-pat"


def test_decrypt_token_returns_unchanged_on_bad_ciphertext(monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setattr(settings, "kb_repo_secret_key", "a-test-secret-key-value")
    # Not valid Fernet ciphertext (e.g. stored in plaintext previously, or a
    # secret-key rotation) — must not raise.
    assert svc.decrypt_token("not-actually-encrypted") == "not-actually-encrypted"


def test_encrypt_token_without_cryptography_installed_falls_back(monkeypatch):
    """Simulate `cryptography` being unavailable even with a secret key set —
    _get_fernet must degrade to plaintext rather than raising ImportError."""
    monkeypatch.setattr(settings, "kb_repo_secret_key", "a-test-secret-key-value")

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "cryptography.fernet" or name.startswith("cryptography"):
            raise ImportError("simulated: cryptography not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    encrypted = svc.encrypt_token("my-pat")
    assert encrypted == "my-pat"
