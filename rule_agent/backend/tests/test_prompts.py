"""
Snapshot tests for the Phase 3 prompt-assembly layer: prompts.py and the
vocab now owned by the KB descriptor (kb/customer_sap.yaml).

_OLD_SYSTEM_PROMPT below is a literal copy of explanation_engine._SYSTEM_PROMPT
as it existed before Phase 3 deleted the module-level constant — copied here
BEFORE deletion so build_system_prompt(customer_sap, None) can be proven
byte-identical to the historical wording. _OLD_CATEGORIES/_OLD_SEVERITY_MAP/
_OLD_TABLE_BUSINESS_NAMES are the same kind of golden copy of chat_agent's
former _CATEGORIES/_SEVERITY_MAP/_TABLE_BUSINESS_NAMES constants.

conftest.py stubs chat_agent/data_loader/explanation_engine/schema_validator in
sys.modules for the main.py test suite. This file only needs kb._schema and
prompts, neither of which is stubbed, so plain imports are fine (same
reasoning as tests/test_kb_descriptor.py).
"""

from pathlib import Path

import prompts
from kb._schema import load_descriptor

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_KB_DIR = _BACKEND_DIR / "kb"

# ── Golden copy of explanation_engine._SYSTEM_PROMPT, pre-Phase-3 ─────────────
_OLD_SYSTEM_PROMPT = (
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

# ── Golden copy of chat_agent._CATEGORIES, pre-Phase-3 ────────────────────────
_OLD_CATEGORIES = [
    "completeness", "uniqueness", "validity", "consistency",
    "accuracy", "timeliness", "conformity",
]

# ── Golden copy of chat_agent._SEVERITY_MAP, pre-Phase-3 ──────────────────────
_OLD_SEVERITY_MAP = {"1": "Critical", "2": "High", "3": "Medium", "4": "Low"}

# ── Golden copy of chat_agent._TABLE_BUSINESS_NAMES, pre-Phase-3 ──────────────
_OLD_TABLE_BUSINESS_NAMES = {
    "KNA1": "customer master — general data",
    "KNB1": "customer master — company code data",
    "KNB5": "customer master — dunning data",
    "KNVV": "customer master — sales area data",
    "KNVP": "customer master — partner functions",
    "KNVA": "customer master — unloading points",
    "KNVH": "customer hierarchy",
    "KNVI": "customer master — tax indicators",
    "ADRC": "central address data",
    "ADR2": "telephone numbers",
    "ADR3": "fax numbers",
    "ADR6": "email addresses",
    "BUT000": "business partner — general data",
    "BUT050": "business partner relationships",
    "BUT051": "business partner contact persons",
    "BUT0BK": "business partner bank details",
    "BUT0IS": "business partner industry sectors",
    "CVI_CUST_LINK": "customer / business-partner link",
    "DFKKBPTAXNUM": "business partner tax numbers",
    "UKMBP_CMS": "credit management profile",
    "UKMBP_CMS_SGM": "credit management segment",
    "LFA1": "vendor master — general data",
    "LFB1": "vendor master — company code data",
    "LFM1": "vendor master — purchasing data",
    "MARA": "material master — general data",
    "MARC": "material master — plant data",
    "MAKT": "material descriptions",
    "MVKE": "material master — sales data",
    "MBEW": "material valuation",
    "MARM": "material units of measure",
    "MLAN": "material tax classifications",
    "MLGN": "material master — warehouse data",
    "SKA1": "G/L account master — chart of accounts",
    "SKAT": "G/L account descriptions",
    "SKB1": "G/L account master — company code",
    "CSKS": "cost center master",
    "CSKB": "cost element master",
    "CEPC": "profit center master",
    "ANLA": "asset master",
}


def _customer_sap():
    return load_descriptor(_KB_DIR / "customer_sap.yaml")


# ── build_system_prompt: customer_sap byte-identity ────────────────────────────


def test_build_system_prompt_customer_sap_matches_old_system_prompt():
    descriptor = _customer_sap()
    assembled = prompts.build_system_prompt(descriptor)
    assert assembled == _OLD_SYSTEM_PROMPT


def test_build_system_prompt_customer_sap_none_custom_prompt_matches_default():
    """Explicit custom_prompt=None is equivalent to the default (also None)."""
    descriptor = _customer_sap()
    assert prompts.build_system_prompt(descriptor, None) == prompts.build_system_prompt(descriptor)


def test_build_system_prompt_customer_sap_blank_custom_prompt_is_ignored():
    descriptor = _customer_sap()
    assert prompts.build_system_prompt(descriptor, "   ") == _OLD_SYSTEM_PROMPT


def test_default_system_prompt_helper_matches():
    assert prompts.default_system_prompt() == _OLD_SYSTEM_PROMPT


# ── build_system_prompt: custom prompt injection ────────────────────────────────


def test_custom_prompt_injected_before_contract_line():
    descriptor = _customer_sap()
    custom = "Always mention the rule's severity if known."
    assembled = prompts.build_system_prompt(descriptor, custom)

    assert "## Knowledge base instructions" in assembled
    assert custom in assembled

    kb_idx = assembled.index("## Knowledge base instructions")
    contract_idx = assembled.index("**Why it matters:**")
    assert kb_idx < contract_idx, "contract line must render after injected instructions"

    # The injected block sits immediately after that heading, and the custom
    # text still precedes the contract clause.
    custom_idx = assembled.index(custom)
    assert kb_idx < custom_idx < contract_idx


def test_custom_prompt_injection_preserves_base_wording():
    """The text before and after the injected block is untouched — the base
    template is split at the contract marker (not rewritten), so both halves
    still match the corresponding slice of the byte-identical base prompt."""
    descriptor = _customer_sap()
    custom = "Prefer bullet points."
    assembled = prompts.build_system_prompt(descriptor, custom)

    marker_idx = _OLD_SYSTEM_PROMPT.index(prompts._CONTRACT_MARKER)
    old_head, old_tail = _OLD_SYSTEM_PROMPT[:marker_idx].rstrip(), _OLD_SYSTEM_PROMPT[marker_idx:]

    assert assembled.startswith(old_head)
    assert assembled.endswith(old_tail)
    assert f"## Knowledge base instructions\n{custom}" in assembled


# ── vocab parity (descriptor vs. pre-Phase-3 chat_agent constants) ────────────


def test_vocab_categories_matches_old_constant():
    assert _customer_sap().vocab.categories == _OLD_CATEGORIES


def test_vocab_severity_map_matches_old_constant():
    assert _customer_sap().vocab.severity_map == _OLD_SEVERITY_MAP


def test_vocab_business_names_matches_old_constant():
    assert _customer_sap().vocab.business_names == _OLD_TABLE_BUSINESS_NAMES
