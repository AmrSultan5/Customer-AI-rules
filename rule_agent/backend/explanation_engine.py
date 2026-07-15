"""
STEP 7 — ExplanationEngine
Calls the Anthropic (Claude) API to produce plain-English rule explanations and
to power the chat / persona flows.

Model selection is tiered per use case ("perfect model for each user"):

  fast      cheap routing / classification / follow-up suggestions
  standard  rule explanations, analyst answers, PM persona stories
  deep      Engineer persona file-edit generation

Each tier resolves from an env var AT CALL TIME (so a tier can be re-pointed
without a code change — e.g. flip ANTHROPIC_MODEL_DEEP between Opus and Sonnet to
A/B Engineer mode). Call sites pass only a tier name, never a model string.

Public function names are intentionally kept (call_openai*, explain_rule); they
are provider-agnostic now and referenced across the codebase and tests.
"""

import logging
import os
from collections.abc import AsyncGenerator
from functools import lru_cache

import asyncio

import anthropic
import httpx

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
    "what related details the user could ask about instead (e.g. description, severity, SAP table, lineage). "
    "End every explanation (but not clarifying questions) with a final line starting with '**Why it matters:**' — "
    "one or two sentences on the business consequence if this rule is violated, "
    "grounded ONLY in the rule logic and any impact data provided. If impact data "
    "is provided, reflect its severity and dependency counts; never invent "
    "consequences the provided context does not support."
)

# ── Model tiers ──────────────────────────────────────────────────────────────
# Resolved from the environment on every call so a tier can be re-pointed live
# without code changes. No model string is hardcoded at any call site.
_TIER_ENV = {
    "fast":     "ANTHROPIC_MODEL_FAST",
    "standard": "ANTHROPIC_MODEL_STANDARD",
    "deep":     "ANTHROPIC_MODEL_DEEP",
}
_TIER_DEFAULT = {
    "fast":     "claude-haiku-4-5",
    "standard": "claude-sonnet-4-6",
    "deep":     "claude-opus-4-8",
}


def _model(tier: str) -> str:
    """Resolve a tier name to a concrete model id, reading the env var live."""
    tier = tier if tier in _TIER_ENV else "standard"
    return os.environ.get(_TIER_ENV[tier]) or _TIER_DEFAULT[tier]


# JSON schema for the persona Stage-1 target selector (json_mode=True).
# Structured outputs require additionalProperties:false and every key in required.
_SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "rule_ids":       {"type": "array", "items": {"type": "string"}},
        "pipelines":      {"type": "array", "items": {"type": "string"}},
        "custom_ops":     {"type": "array", "items": {"type": "string"}},
        "needs_new_rule": {"type": "boolean"},
        "rationale":      {"type": "string"},
    },
    "required": ["rule_ids", "pipelines", "custom_ops", "needs_new_rule", "rationale"],
    "additionalProperties": False,
}

_client: anthropic.Anthropic | None = None
_async_client: anthropic.AsyncAnthropic | None = None


def _require_key() -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set in .env")
    return api_key


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(
            api_key=_require_key(),
            max_retries=3,
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
    return _client


def _get_async_client() -> anthropic.AsyncAnthropic:
    global _async_client
    if _async_client is None:
        _async_client = anthropic.AsyncAnthropic(
            api_key=_require_key(),
            max_retries=3,
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
    return _async_client


def _messages(user_msg: str, history: list[dict] | None) -> list[dict]:
    """Build the Anthropic messages array (system goes in the top-level `system=`).

    Anthropic requires the first message to be from the user, so any leading
    assistant turns in the history are dropped.
    """
    msgs = list(history or []) + [{"role": "user", "content": user_msg}]
    while msgs and msgs[0].get("role") != "user":
        msgs.pop(0)
    return msgs


def _text(response) -> str:
    """Concatenate the text blocks of a non-streaming Anthropic response."""
    return "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ).strip()


async def probe_llm() -> None:
    """Minimal Anthropic reachability probe. Raises on any failure.

    Uses a short timeout so the /health-style probe fails fast. Called only by
    the admin probe endpoint — not in the hot request path.
    """
    client = _get_async_client()
    await client.with_options(timeout=httpx.Timeout(5.0, connect=3.0)).messages.create(
        model=_model("fast"),
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )


@lru_cache(maxsize=256)
def explain_rule(rule_logic: str, sap_context: str = "", tier: str = "standard",
                 impact_digest: str = "") -> str:
    """Translate rule_logic into plain English via Claude."""
    if not rule_logic or rule_logic.strip() in ("", "nan", "None"):
        return "No technical rule definition available for this rule."

    user_msg = f"Rule logic:\n{rule_logic}"
    if sap_context:
        user_msg += f"\n\nField reference (do not use these names in the explanation):\n{sap_context}"
    if impact_digest:
        user_msg += f"\n\nImpact data (deterministic — use only this for the 'Why it matters' line):\n{impact_digest}"

    model = _model(tier)

    try:
        client = _get_client()
        response = client.messages.create(
            model=model,
            max_tokens=1000,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        if response.usage:
            track_token_usage_sync(
                response.usage.input_tokens,
                response.usage.output_tokens,
                response.usage.input_tokens + response.usage.output_tokens,
                model, "explain_rule",
            )
        text = _text(response)
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
    tier: str = "standard",
) -> str:
    """Generic (non-cached) Claude call for ad-hoc queries.

    history: optional list of prior turns as [{"role": "user"|"assistant", "content": "..."}].
    Injected between the system prompt and the current user message.
    """
    model = _model(tier)
    # WARNING: user_msg may contain prompt-injection attempts via rule content or chat
    # history. The system prompt is fixed; treat all user/history content as untrusted.
    try:
        client = _get_client()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=_messages(user_msg, history),
        )
        if response.usage:
            track_token_usage_sync(
                response.usage.input_tokens,
                response.usage.output_tokens,
                response.usage.input_tokens + response.usage.output_tokens,
                model, "chat",
            )
        return _text(response)
    except Exception as e:
        # Log type only — avoid logging message content that may contain sensitive data.
        log.error("[ERROR] Claude generic call failed: %s", type(e).__name__)
        raise


async def call_openai_async(
    system_prompt: str,
    user_msg: str,
    max_tokens: int = 600,
    history: list[dict] | None = None,
    json_mode: bool = False,
    tier: str = "standard",
) -> str:
    """Async variant of call_openai — never blocks the event loop.

    json_mode=True constrains the response to the Stage-1 selector JSON schema
    via structured outputs.
    """
    model = _model(tier)
    # WARNING: user_msg may contain prompt-injection attempts via rule content or chat
    # history. The system prompt is fixed; treat all user/history content as untrusted.
    kwargs: dict = {}
    if json_mode:
        kwargs["output_config"] = {
            "format": {"type": "json_schema", "schema": _SELECTION_SCHEMA}
        }
    try:
        client = _get_async_client()
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=_messages(user_msg, history),
            **kwargs,
        )
        if response.usage:
            asyncio.create_task(track_token_usage(
                response.usage.input_tokens,
                response.usage.output_tokens,
                response.usage.input_tokens + response.usage.output_tokens,
                model, "chat",
            ))
        return _text(response)
    except Exception as e:
        # Log type only — avoid logging message content that may contain sensitive data.
        log.error("[ERROR] Claude async call failed: %s", type(e).__name__)
        raise


async def call_openai_stream(
    system_prompt: str,
    user_msg: str,
    max_tokens: int = 800,
    history: list[dict] | None = None,
    tier: str = "standard",
) -> AsyncGenerator[str, None]:
    """Stream a Claude response as text delta chunks.

    Yields individual text strings. Caller is responsible for the done event.
    """
    model = _model(tier)
    client = _get_async_client()
    async with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=_messages(user_msg, history),
    ) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()
    if final.usage:
        asyncio.create_task(track_token_usage(
            final.usage.input_tokens,
            final.usage.output_tokens,
            final.usage.input_tokens + final.usage.output_tokens,
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
