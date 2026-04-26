"""
STEP 7 — ExplanationEngine
Calls Azure OpenAI to produce plain-English rule explanations.
"""

import logging
import os
from functools import lru_cache

from openai import AzureOpenAI

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a business analyst. Explain the following data rule in plain "
    "English for a non-technical business user. Use business terminology. "
    "No code. No SAP field names. No jargon. 2-3 sentences maximum. "
    "If the rule logic is unclear or the question is ambiguous, ask the user to clarify. "
    "If specific information is not available in the rule provided, say so and suggest "
    "what related details the user could ask about instead (e.g. description, severity, SAP table, lineage)."
)

_client: AzureOpenAI | None = None


def _get_client() -> AzureOpenAI:
    global _client
    if _client is None:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        if not endpoint or not api_key:
            raise RuntimeError(
                "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set in .env"
            )
        # The SDK appends /openai/deployments/... automatically.
        # Strip a trailing /openai from the gateway URL to avoid doubling.
        base = endpoint.rstrip("/")
        if base.endswith("/openai"):
            base = base[: -len("/openai")]
        _client = AzureOpenAI(
            azure_endpoint=base,
            api_key=api_key,
            api_version=api_version,
        )
    return _client


@lru_cache(maxsize=256)
def explain_rule(rule_logic: str, sap_context: str = "") -> str:
    """Translate rule_logic into plain English via Azure OpenAI."""
    if not rule_logic or rule_logic.strip() in ("", "nan", "None"):
        return "No technical rule definition available for this rule."

    user_msg = f"Rule logic:\n{rule_logic}"
    if sap_context:
        user_msg += f"\n\nField reference (do not use these names in the explanation):\n{sap_context}"

    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "cch-gpt-4o")
    timeout = float(os.environ.get("AZURE_OPENAI_TIMEOUT", "30"))

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=deployment,
            max_tokens=1000,
            timeout=timeout,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        text = response.choices[0].message.content.strip()
        log.info("[INFO] ExplanationEngine: generated explanation (%d chars)", len(text))
        return text
    except Exception as e:
        # Log error type server-side only; do not return provider details to callers.
        log.error("[ERROR] ExplanationEngine failed: %s", type(e).__name__)
        return "Unable to generate a business explanation for this rule at this time."


def call_azure_openai(
    system_prompt: str,
    user_msg: str,
    max_tokens: int = 600,
    history: list[dict] | None = None,
) -> str:
    """Generic (non-cached) Azure OpenAI call for ad-hoc queries.

    history: optional list of prior turns as [{"role": "user"|"assistant", "content": "..."}].
    Injected between the system prompt and the current user message.
    """
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "cch-gpt-4o")
    timeout = float(os.environ.get("AZURE_OPENAI_TIMEOUT", "30"))
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_msg})
    # WARNING: user_msg may contain prompt-injection attempts via rule content or chat
    # history. The system prompt is fixed; treat all user/history content as untrusted.
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=deployment,
            max_tokens=max_tokens,
            timeout=timeout,
            messages=messages,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        # Log type only — avoid logging message content that may contain sensitive data.
        log.error("[ERROR] Azure OpenAI generic call failed: %s", type(e).__name__)
        raise


def build_sap_context(sap_fields: list[dict]) -> str:
    """Build context string for the LLM — only confirmed mappings."""
    parts = []
    for f in sap_fields:
        bn = f.get("business_name", "")
        if bn and bn != "Unknown field":
            parts.append(f"{f['field']} → {bn}")
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
