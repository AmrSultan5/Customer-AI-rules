"""
STEP 7 — ExplanationEngine
Calls OpenAI to produce plain-English rule explanations.
"""

import logging
import os
from collections.abc import AsyncGenerator
from functools import lru_cache

import asyncio

import httpx
from openai import AsyncOpenAI, OpenAI

from analytics import track_token_usage, track_token_usage_sync

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a business analyst. Explain the following data rule in plain "
    "English for a non-technical business user. Use business terminology. "
    "No code. No SAP field names. No jargon. "
    "Tailor depth to complexity — use 2-3 sentences for simple rules, "
    "and a fuller explanation for rules with multiple conditions, dependencies, or pipeline steps. "
    "If the rule logic is unclear or the question is ambiguous, ask the user to clarify. "
    "If specific information is not available in the rule provided, say so and suggest "
    "what related details the user could ask about instead (e.g. description, severity, SAP table, lineage)."
)

_client: OpenAI | None = None
_async_client: AsyncOpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY must be set in .env"
            )
        _client = OpenAI(
            api_key=api_key,
            max_retries=3,
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
    return _client


def _get_async_client() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY must be set in .env"
            )
        _async_client = AsyncOpenAI(
            api_key=api_key,
            max_retries=3,
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
    return _async_client


async def probe_llm() -> None:
    """Minimal OpenAI reachability probe. Raises on any failure.

    Uses a 5s total / 3s connect timeout so the /health endpoint fails fast.
    Called only by the /health endpoint — do not use in the hot request path.
    """
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    client = _get_async_client()
    await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
        timeout=httpx.Timeout(5.0, connect=3.0),
    )


@lru_cache(maxsize=256)
def explain_rule(rule_logic: str, sap_context: str = "") -> str:
    """Translate rule_logic into plain English via OpenAI."""
    if not rule_logic or rule_logic.strip() in ("", "nan", "None"):
        return "No technical rule definition available for this rule."

    user_msg = f"Rule logic:\n{rule_logic}"
    if sap_context:
        user_msg += f"\n\nField reference (do not use these names in the explanation):\n{sap_context}"

    model = os.environ.get("OPENAI_MODEL", "gpt-4o")

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=model,
            max_tokens=1000,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        if response.usage:
            track_token_usage_sync(
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                response.usage.total_tokens,
                model, "explain_rule",
            )
        text = response.choices[0].message.content.strip()
        log.info("[INFO] ExplanationEngine: generated explanation (%d chars)", len(text))
        return text
    except Exception as e:
        # Log error type server-side only; do not return provider details to callers.
        log.error("[ERROR] ExplanationEngine failed: %s", type(e).__name__)
        return "Unable to generate a business explanation for this rule at this time."


def call_openai(
    system_prompt: str,
    user_msg: str,
    max_tokens: int = 600,
    history: list[dict] | None = None,
) -> str:
    """Generic (non-cached) OpenAI call for ad-hoc queries.

    history: optional list of prior turns as [{"role": "user"|"assistant", "content": "..."}].
    Injected between the system prompt and the current user message.
    """
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_msg})
    # WARNING: user_msg may contain prompt-injection attempts via rule content or chat
    # history. The system prompt is fixed; treat all user/history content as untrusted.
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        if response.usage:
            track_token_usage_sync(
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                response.usage.total_tokens,
                model, "chat",
            )
        return response.choices[0].message.content.strip()
    except Exception as e:
        # Log type only — avoid logging message content that may contain sensitive data.
        log.error("[ERROR] OpenAI generic call failed: %s", type(e).__name__)
        raise


async def call_openai_async(
    system_prompt: str,
    user_msg: str,
    max_tokens: int = 600,
    history: list[dict] | None = None,
    json_mode: bool = False,
) -> str:
    """Async variant of call_openai — never blocks the event loop.

    json_mode=True forces a JSON object response (response_format json_object).
    """
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_msg})
    # WARNING: user_msg may contain prompt-injection attempts via rule content or chat
    # history. The system prompt is fixed; treat all user/history content as untrusted.
    kwargs: dict = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        client = _get_async_client()
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            **kwargs,
        )
        if response.usage:
            asyncio.create_task(track_token_usage(
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                response.usage.total_tokens,
                model, "chat",
            ))
        return response.choices[0].message.content.strip()
    except Exception as e:
        # Log type only — avoid logging message content that may contain sensitive data.
        log.error("[ERROR] OpenAI async call failed: %s", type(e).__name__)
        raise


async def call_openai_stream(
    system_prompt: str,
    user_msg: str,
    max_tokens: int = 800,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """Stream OpenAI response as text delta chunks.

    Yields individual text strings. Caller is responsible for the done event.
    """
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_msg})

    client = _get_async_client()
    stream = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        if chunk.choices:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
        # Final chunk carries usage when stream_options include_usage=True
        if getattr(chunk, "usage", None):
            asyncio.create_task(track_token_usage(
                chunk.usage.prompt_tokens,
                chunk.usage.completion_tokens,
                chunk.usage.total_tokens,
                model, "stream",
            ))


def build_sap_context(sap_fields: list[dict]) -> str:
    """Build context string for the LLM — only confirmed mappings."""
    parts = []
    for f in sap_fields:
        bn = f.get("business_name", "")
        if not bn or bn == "Unknown field":
            continue
        line = f"{f['field']} → {bn}"
        extras = []
        if f.get("required"):
            label = "Required" if f["required"].upper().startswith("R") else "Optional"
            extras.append(label)
        if f.get("field_format"):
            extras.append(f"format: {f['field_format']}")
        if f.get("reference_table"):
            extras.append(f"ref table: {f['reference_table']}")
        if f.get("mdg_validation_rules"):
            extras.append(f"MDG rule: {f['mdg_validation_rules']}")
        if extras:
            line += f" ({'; '.join(extras)})"
        # Append valid code values if available (first 8 to keep context tight)
        codes = f.get("valid_codes", [])
        if codes:
            code_strs = []
            for c in codes[:8]:
                vals = list(c.values())
                if len(vals) >= 2:
                    code_strs.append(f"{vals[0]}={vals[1]}")
                elif vals:
                    code_strs.append(str(vals[0]))
            if code_strs:
                line += f" [valid values: {', '.join(code_strs)}]"
        parts.append(line)
    return "\n".join(parts)


if __name__ == "__main__":
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")

    from data_loader import get_rules
    from rule_parser import extract_sap_fields
    from sap_mapper import lookup_sap_field

    rules = get_rules()
    row = rules[rules["rule_logic"].notna()].iloc[2]
    logic = str(row["rule_logic"])
    raw_fields = extract_sap_fields(logic)
    mapped = [lookup_sap_field(f) for f in raw_fields]
    ctx = build_sap_context(mapped)

    print(f"Logic: {logic[:200]}")
    print(f"\nExplanation:\n{explain_rule(logic, ctx)}")
