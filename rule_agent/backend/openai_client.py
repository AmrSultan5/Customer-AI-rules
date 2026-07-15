"""
OpenAI helper — conversation title generation with gpt-4o-mini.

Kept separate from the Anthropic `explanation_engine`: titles use OpenAI
(`OPENAI_API_KEY`), while the chat/explanation pipeline uses Claude. Token usage
is recorded through `analytics` so the admin dashboard reflects this spend too.
"""

import asyncio
import logging
import os
import re

log = logging.getLogger(__name__)

_TITLE_MODEL = os.environ.get("OPENAI_TITLE_MODEL", "gpt-4o-mini")
_client = None

_TITLE_SYSTEM = (
    "You write very short titles for chat conversations. Given the first user "
    "message and the assistant's reply, respond with a concise title of at most "
    "6 words that captures the topic. Plain text only — no markdown, no "
    "asterisks, no backticks, no quotes, no trailing punctuation, no prefix "
    "like 'Title:'. Just the title."
)

# The sidebar renders titles as plain text, so markdown the model (or the
# user's own first message, via the fallback) sneaks in shows up literally.
# Underscores are kept — rule IDs like RCCOMP_103.1 legitimately contain them.
_MD_CHARS_RE = re.compile(r"[*`#>]+")


def _clean_title(title: str) -> str:
    """Strip markdown formatting and collapse whitespace for plain-text display."""
    text = _MD_CHARS_RE.sub("", title or "")
    return " ".join(text.split()).strip("\"' ")


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    return _client


def _fallback_title(first_user_msg: str) -> str:
    text = (first_user_msg or "New chat").strip().splitlines()[0] if first_user_msg else "New chat"
    return _clean_title(text[:60]) or "New chat"


def generate_title(first_user_msg: str, first_assistant_msg: str = "") -> str:
    """Generate a short conversation title via gpt-4o-mini. Synchronous.

    Falls back to a truncation of the first user message on any failure so a
    title is always produced.
    """
    fallback = _fallback_title(first_user_msg)
    try:
        resp = _get_client().chat.completions.create(
            model=_TITLE_MODEL,
            messages=[
                {"role": "system", "content": _TITLE_SYSTEM},
                {
                    "role": "user",
                    "content": f"User: {(first_user_msg or '')[:600]}\n\nAssistant: {(first_assistant_msg or '')[:600]}",
                },
            ],
            max_tokens=20,
            temperature=0.3,
        )
        title = _clean_title(resp.choices[0].message.content or "")
        _track_usage(resp)
        return title[:80] or fallback
    except Exception as exc:
        log.warning("[openai] generate_title failed (%s) — using fallback", type(exc).__name__)
        return fallback


async def generate_title_async(first_user_msg: str, first_assistant_msg: str = "") -> str:
    """Async wrapper — runs the blocking OpenAI call off the event loop."""
    return await asyncio.to_thread(generate_title, first_user_msg, first_assistant_msg)


def _track_usage(resp) -> None:
    try:
        usage = getattr(resp, "usage", None)
        if not usage:
            return
        from analytics import track_token_usage_sync

        track_token_usage_sync(
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
            getattr(usage, "total_tokens", 0) or 0,
            model=_TITLE_MODEL,
            call_type="title",
        )
    except Exception as exc:
        log.debug("[openai] title token tracking suppressed: %s", exc)
