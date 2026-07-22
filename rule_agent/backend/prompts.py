"""
Analyst system-prompt assembly (Phase 3).

Config-driven replacement for the old module-level explanation_engine._SYSTEM_PROMPT
constant. build_system_prompt(kb, custom_prompt) starts from the KB descriptor's
analyst base template (kb.prompts.analyst_system — which already inherits the
shared kb/_defaults.yaml template when a descriptor omits it, see
kb._schema.load_descriptor), substitutes vocab placeholders, then optionally
injects the KB's custom prompt as a bounded "## Knowledge base instructions"
section *before* the template's mandatory closing "**Why it matters:**"
contract line — so injected text is always followed by (and can never
override) that structural rule.

For customer_sap with custom_prompt=None, build_system_prompt reproduces
today's explanation_engine._SYSTEM_PROMPT text character-for-character (see
tests/test_prompts.py).
"""

from pathlib import Path

from kb._schema import KBDescriptor, load_descriptor

# The base template's mandatory closing contract starts with this exact
# sentence (see kb/_defaults.yaml). When a custom_prompt is injected, the
# template is split at this marker so the contract line stays last.
_CONTRACT_MARKER = "End every explanation (but not clarifying questions)"


def build_system_prompt(kb: KBDescriptor, custom_prompt: str | None = None) -> str:
    """Assemble the analyst system prompt for a KB descriptor.

    - Substitutes vocab placeholders ({entity_singular}, {entity_plural}) plus
      {repository_label} into the base template. Placeholders absent from the
      template (e.g. a KB whose template doesn't mention repository_label) are
      simply unused — str.format ignores extra keyword arguments.
    - If custom_prompt is non-empty, inserts it as a bounded
      "## Knowledge base instructions" section immediately before the
      template's mandatory "**Why it matters:**" closing-line rule, so the
      contract rule always renders last and injected text cannot override it.
      If the template doesn't contain the expected contract marker (a custom
      KB template that doesn't follow the shared structure), the section is
      appended at the end instead.
    """
    base = kb.prompts.analyst_system.format(
        entity_singular=kb.vocab.entity_singular,
        entity_plural=kb.vocab.entity_plural,
        repository_label=kb.prompts.repository_label,
        platform_terms=", ".join(kb.vocab.platform_terms),
    )

    custom_prompt = (custom_prompt or "").strip()
    if not custom_prompt:
        return base

    injected = f"## Knowledge base instructions\n{custom_prompt}"
    idx = base.find(_CONTRACT_MARKER)
    if idx == -1:
        return f"{base}\n\n{injected}"

    head, tail = base[:idx].rstrip(), base[idx:]
    return f"{head}\n\n{injected}\n\n{tail}"


_BACKEND_DIR = Path(__file__).resolve().parent


def default_system_prompt() -> str:
    """Analyst system prompt for the default (customer_sap) KB, no custom prompt.

    Convenience helper for back-compat callers that don't have a provider/
    descriptor on hand. Loads the descriptor directly from kb/customer_sap.yaml
    via kb._schema (not the provider registry), so importing this module never
    pulls in the registry seam.
    """
    descriptor = load_descriptor(_BACKEND_DIR / "kb" / "customer_sap.yaml")
    return build_system_prompt(descriptor)
