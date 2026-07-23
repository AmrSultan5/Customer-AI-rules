"""
embeddings.py — OpenAI embedding wrapper for RAG ingestion + query (Phase 8a).

`embed_texts(texts)` is the public entry point everything else (ingestion.py,
providers/rag.py) calls. It batches requests to the OpenAI embeddings API
(`config.settings.embeddings_model`, default text-embedding-3-small) and
tracks token usage via `analytics.track_token_usage_sync(call_type="embedding")`
best-effort (failures never break embedding).

Tests never want a real OpenAI call: `_embed_batch_fn` is a module-level
indirection point — monkeypatch it (`monkeypatch.setattr(embeddings,
"_embed_batch_fn", fake_fn)`) to swap in a fake batch embedder without
touching anything else in this module or its callers.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from config import settings

log = logging.getLogger(__name__)

# OpenAI's embeddings endpoint accepts many inputs per call; batch generously
# but stay well under its per-request item/token limits.
_BATCH_SIZE = 100

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", settings.openai_api_key))
    return _client


def _default_embed_batch(texts: list[str]) -> list[list[float]]:
    """Real OpenAI call for one batch. Not used directly by tests — see
    `_embed_batch_fn` below."""
    client = _get_client()
    resp = client.embeddings.create(model=settings.embeddings_model, input=texts)
    _track_usage(resp)
    return [d.embedding for d in resp.data]


# The indirection point tests monkeypatch. Signature: list[str] -> list[list[float]].
_embed_batch_fn: Callable[[list[str]], list[list[float]]] = _default_embed_batch


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings, batched. Returns one vector per input text,
    same order. Empty input returns []."""
    if not texts:
        return []
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        out.extend(_embed_batch_fn(batch))
    return out


def _track_usage(resp) -> None:
    try:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        from analytics import track_token_usage_sync

        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", prompt_tokens) or prompt_tokens
        track_token_usage_sync(
            prompt_tokens, 0, total_tokens,
            model=settings.embeddings_model, call_type="embedding",
        )
    except Exception as exc:
        log.debug("[embeddings] token tracking suppressed: %s", exc)
