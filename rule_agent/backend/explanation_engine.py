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

# Phase 3: the module-level analyst system prompt moved to prompts.py
# (prompts.build_system_prompt), which assembles it from a KB descriptor's
# prompts/vocab instead of a hardcoded constant. explain_rule() takes the
# assembled prompt in via system_prompt; when a caller omits it, _default_
# system_prompt() below falls back to the customer_sap descriptor (loaded
# directly via kb._schema, not the provider registry, so this module stays
# decoupled from the provider seam).

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

_default_system_prompt_cache: str | None = None


def _default_system_prompt() -> str:
    """Back-compat analyst system prompt (customer_sap, no custom prompt),
    cached after first build. Used by explain_rule() when a caller doesn't
    thread a system_prompt in from a provider/descriptor."""
    global _default_system_prompt_cache
    if _default_system_prompt_cache is None:
        import prompts
        _default_system_prompt_cache = prompts.default_system_prompt()
    return _default_system_prompt_cache


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
                 impact_digest: str = "", system_prompt: str | None = None) -> str:
    """Translate rule_logic into plain English via Claude.

    system_prompt: assembled via prompts.build_system_prompt(kb, custom_prompt)
    by the caller (chat_agent, which has the active provider/descriptor). When
    omitted, falls back to the customer_sap default (see _default_system_prompt).
    """
    if not rule_logic or rule_logic.strip() in ("", "nan", "None"):
        return "No technical rule definition available for this rule."

    user_msg = f"Rule logic:\n{rule_logic}"
    if sap_context:
        user_msg += f"\n\nField reference (do not use these names in the explanation):\n{sap_context}"
    if impact_digest:
        user_msg += f"\n\nImpact data (deterministic — use only this for the 'Why it matters' line):\n{impact_digest}"

    model = _model(tier)
    system_prompt = system_prompt or _default_system_prompt()

    try:
        client = _get_client()
        response = client.messages.create(
            model=model,
            max_tokens=1000,
            system=system_prompt,
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
    call_type: str = "chat",
    knowledge_base_id: str | None = None,
) -> str:
    """Async variant of call_openai — never blocks the event loop.

    json_mode=True constrains the response to the Stage-1 selector JSON schema
    via structured outputs.

    call_type/knowledge_base_id are forwarded to the internal token-usage
    write (default "chat"/None reproduce the original behavior for existing
    callers) so a caller like the Phase 6 prompt-enhance endpoint can tag its
    usage distinctly (call_type="prompt_enhance") without a second API call.
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
                model, call_type, knowledge_base_id,
            ))
        return _text(response)
    except Exception as e:
        # Log type only — avoid logging message content that may contain sensitive data.
        log.error("[ERROR] Claude async call failed: %s", type(e).__name__)
        raise


def model_for_tier(tier: str = "standard") -> str:
    """Public accessor for the concrete model id a tier resolves to right now.

    Thin wrapper over the private _model() so callers that need to report
    which model backed a call (e.g. the Phase 6 prompt-enhance endpoint's
    response `model` field) don't reach into a private helper. Same live
    env-var resolution as every other call site — no caching.
    """
    return _model(tier)


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

    rules = get_rules()
    row = rules[rules["rule_logic"].notna()].iloc[2]
    logic = str(row["rule_logic"])

    print(f"Logic: {logic[:200]}")
    print(f"\nExplanation:\n{explain_rule(logic)}")
