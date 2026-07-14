# Business-Friendly Analyst Answer Layer — Design

**Date:** 2026-07-14
**Project:** `rule_agent` (backend only)
**Status:** Awaiting user review

## Problem

The analyst chat mode is the default persona for business users, but several
answer paths still talk like an engineer:

1. **Deterministic lookup intents bypass the LLM** and return raw technical
   strings (`chat_agent.py` stream flow, sap_table/sap_column/fields/lineage
   intents). Example: ``The SAP table checked by rule **X** is: `KNA1` ``.
   Lineage answers are a semicolon-joined dump of module/group/pipeline
   identifiers.
2. **Explanations never say why a rule matters** — no business impact, risk,
   or downstream consequence, even though severity and a deterministic impact
   graph (`impact_service.get_rule_impact`) already exist.
3. **Follow-up suggestions steer users toward technical questions** — the
   generator prompt's own example nudges toward "which SAP fields are used".
4. **Fallback/error copy teaches query syntax** ("Try: `Explain rule
   RCCOMP_103.1`") instead of natural phrasing.

## Goals

- Every analyst answer leads with plain business language; SAP/technical
  identifiers stay visible but secondary (in parentheses or labeled).
- Rule explanations end with a grounded "Why it matters" line.
- No API shape changes, no frontend changes, no new endpoints.
- Every new lookup degrades to current behavior on failure.

## Non-Goals (YAGNI)

- No business/technical UI toggle.
- No changes to the engineer or PM personas.
- No renaming of severity levels or rule IDs.

## Design

### 1. Plain-language wrappers for deterministic lookups (`chat_agent.py`)

- New module-level dict `_TABLE_BUSINESS_NAMES` mapping the SAP customer
  tables present in the catalog (KNA1, KNB1, KNVV, ADRC, …) to short business
  names (e.g. "customer master — general data"). Unknown tables fall back to
  today's format unchanged.
- **sap_table / sap_column intents:** lead with the business name, keep the
  SAP name in parentheses. Example: "This rule checks the **customer master
  (general data)** table (SAP name: KNA1)." Column answers reuse
  `sap_mapper.lookup_sap_field()` for the business name.
- **fields intent:** flip the order — business name first, SAP field in
  parentheses.
- **lineage / workflow intent:** replace the semicolon dump with a short
  bulleted markdown block using business labels first ("Owned by", "Data
  comes from", "Runs alongside N related rules"); technical identifiers kept
  but secondary. Still fully deterministic — no LLM call added.

### 2. "Why it matters" in rule explanations (`explanation_engine.py`)

- Extend `_SYSTEM_PROMPT` so every explanation ends with a one-to-two-sentence
  **Why it matters** line grounded ONLY in provided context — no invented
  business consequences.
- At the explain/show call site in `chat_agent.py`, append a compact impact
  digest to the user message built from deterministic data: severity label
  (`_SEVERITY_MAP`) plus counts from `get_rule_impact()` (e.g. "severity:
  High; 3 rules depend on this one; runs in 2 pipelines"). If the impact
  lookup fails, skip the digest silently — the explanation works as today.

### 3. Business-oriented follow-up suggestions (`_FOLLOWUPS_SYSTEM`)

- Rewrite the prompt's example steering: suggest business questions first
  ("how critical is this?", "what happens if this rule fails?", "which other
  checks relate to it?"); technical suggestions only when the user's own
  question was technical.

### 4. Friendlier fallback/error copy (`_find_rule_by_description`)

- Replace syntax-flavored suggestions with natural phrasing: "Describe what
  the rule should check, e.g. 'the rule that makes sure every customer has a
  postal code'" — keeping one rule-ID example for technical users.

## Error Handling

Every new lookup (table business names, impact digest) is wrapped so any
failure falls back to the current answer format. No new failure modes reach
the user.

## Testing

Extend `backend/tests/test_chat_routing.py` and `test_api.py`:

- sap_table answer contains both the business name and the SAP name.
- Unknown table falls back to the old format.
- Lineage answer renders as markdown bullets.
- Explain path includes the impact digest in the LLM prompt (mock the LLM).
- Impact-lookup failure still produces a normal explanation.
- Follow-up generator prompt contains the business-first steering.
