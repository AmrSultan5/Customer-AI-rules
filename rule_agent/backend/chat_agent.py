"""
STEP 9 — ChatAgent
Intent detection and routing for the /chat endpoint.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

log = logging.getLogger(__name__)

_RULE_ID_RE = re.compile(
    r"\b([A-Z]{2,8}_\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)

_CATEGORIES = [
    "completeness", "uniqueness", "validity", "consistency",
    "accuracy", "timeliness", "conformity",
]


def _extract_rule_id(message: str) -> str | None:
    m = _RULE_ID_RE.search(message)
    return m.group(1).upper() if m else None


def _intent(message: str) -> str:
    low = message.lower()
    # Specific field lookups — checked before generic "explain"
    if any(kw in low for kw in ["sap table", "which table", "what table", "table checked", "table for", "table used"]):
        return "sap_table"
    if any(kw in low for kw in ["sap column", "which column", "what column", "column checked", "column name", "column for"]):
        return "sap_column"
    if any(kw in low for kw in ["severity", "how severe", "priority level", "criticality"]):
        return "severity"
    if any(kw in low for kw in ["description", "rule description", "what's the description", "what is the description"]):
        return "description"
    if any(kw in low for kw in ["explain", "what does", "what is", "describe", "meaning"]):
        return "explain"
    if any(kw in low for kw in ["where does", "where do", "come from", "source", "origin", "lineage"]):
        return "lineage"
    if any(kw in low for kw in ["workflow", "steps", "pipeline", "process"]):
        return "workflow"
    if any(kw in low for kw in ["sap field", "fields used", "what field", "which field"]):
        return "fields"
    if any(kw in low for kw in ["show", "get", "display", "detail", "full rule"]):
        return "show"
    return "explain"


def _detect_category(message: str) -> str | None:
    low = message.lower()
    for cat in _CATEGORIES:
        if cat in low:
            return cat
    return None


def _safe(val) -> str:
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


_SEVERITY_MAP = {"1": "Critical", "2": "High", "3": "Medium", "4": "Low"}


# Business names for SAP tables that appear in the rule inventory. Lookup
# misses fall back to the raw technical answer format, so this list only
# needs the tables business users actually ask about.
_TABLE_BUSINESS_NAMES = {
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


def _format_sap_table_answer(rule_id: str, table: str) -> str:
    """Plain-language answer for the sap_table intent; falls back to the
    technical format for tables without a business name."""
    if not table:
        return f"No SAP table information available for rule {rule_id}."
    biz = _TABLE_BUSINESS_NAMES.get(table.strip().upper())
    if biz:
        return f"Rule **{rule_id}** checks the **{biz}** table (SAP name: `{table}`)."
    return f"The SAP table checked by rule **{rule_id}** is: `{table}`"


def _format_sap_column_answer(rule_id: str, table: str, col: str) -> str:
    """Plain-language answer for the sap_column intent; falls back to the
    technical format when no business name is known."""
    if not col:
        return f"No SAP column information available for rule {rule_id}."
    try:
        from sap_mapper import lookup_sap_field
        key = f"{table}-{col}" if table else col
        biz = lookup_sap_field(key).get("business_name", "")
    except Exception as exc:
        log.warning("[sap_column] business-name lookup failed: %s", exc)
        biz = ""
    if biz and biz != "Unknown field" and biz.upper() != col.upper():
        return f"Rule **{rule_id}** checks the **{biz}** field (SAP name: `{col}`)."
    return f"The SAP column checked by rule **{rule_id}** is: `{col}`"


def _format_fields_answer(rule_id: str, logic: str) -> str:
    """Plain-language answer for the fields intent — business names first,
    SAP identifiers in parentheses."""
    from rule_parser import extract_sap_fields
    from sap_mapper import lookup_sap_field
    raw_fields = extract_sap_fields(logic)
    names: list[str] = []
    for f in (lookup_sap_field(rf) for rf in raw_fields):
        bn = f.get("business_name", "")
        if bn and bn != "Unknown field":
            names.append(f"**{bn}** (SAP field: {f['field']})")
        else:
            names.append(f"`{f['field']}`")
    if not names:
        return f"Rule {rule_id} references these fields: none detected."
    return f"Rule **{rule_id}** looks at these fields: " + ", ".join(names) + "."


def _instructions_block(extra_context: str | None) -> str:
    """Render project standing-instructions as a prefix block for the LLM prompt."""
    if extra_context and extra_context.strip():
        return f"## Project instructions\n{extra_context.strip()}\n\n"
    return ""

_INTENT_CLASSIFIER_SYSTEM = """\
You are a router for a data quality rule assistant.
The user has an active rule open in their panel. Decide whether their message is:
- A follow-up question or request about that active rule → reply FOLLOWUP
- A search or request to find a different or new rule by description → reply SEARCH
- Anything not about the rules at all (greetings, the team's tools, processes,
  documentation, git, Databricks, SAP, general data quality concepts, or any
  other topic) → reply GENERAL

Examples of FOLLOWUP: "what table does it check?", "explain the severity", "what does this mean?", "how does it work?"
Examples of SEARCH: "find a rule that checks phone numbers", "is there a rule for email validation?", "what rule handles address conformity?"
Examples of GENERAL: "is there a wiki page that explains the git flow?", "what does conformity mean in data quality?", "how do I run a notebook in Databricks?"

Reply with exactly one word: FOLLOWUP, SEARCH, or GENERAL. Nothing else.\
"""

_GENERAL_ROUTE_SYSTEM = """\
You are a router for a data quality rule assistant.
Decide whether the user's message is about the repository's data quality rules
(finding, explaining, listing, counting, or comparing rules, their descriptions,
SAP tables/columns, categories, severity, pipelines, or lineage) → reply RULES
or about anything else (greetings, the team's tools, processes, documentation,
git, Databricks, SAP in general, data quality concepts in general, or any other
topic) → reply GENERAL

Examples of RULES: "is there a rule for email validation?", "list all completeness rules", "which rules check KNA1?"
Examples of GENERAL: "is there a wiki page that explains the git flow?", "what is a golden record?", "how do I connect to Databricks?", "hello"

Reply with exactly one word: RULES or GENERAL. Nothing else.\
"""

_GENERAL_ASSISTANT_SYSTEM = """\
You are the analyst assistant for a Customer data quality rule repository
(YAML rule pipelines under golden/, custom Python operations under
custom_operations/, rule inventory in data/dim_rules_inventory.xlsx, running
on Databricks against SAP customer data).

The user's current message is not a rule lookup — answer it directly and helpfully.

Guidelines:
- General or technical questions (data quality concepts, git, SQL, PySpark,
  Databricks, SAP, agile process, etc.): answer accurately from general knowledge.
- Questions about team-specific resources you cannot see (wiki pages, Confluence,
  dashboards, tickets, contacts, URLs, environments): say plainly that you don't
  have access to that resource, then help with what you DO know — e.g. explain
  the underlying concept yourself or suggest where teams typically document it.
  NEVER invent links, page names, document titles, or people.
- Greetings and small talk: reply briefly and naturally.
- When it fits, remind the user you can also look up and explain the repository's
  data quality rules (by rule ID, description, category, or SAP table) — but
  never force their question into a rule search.
- Match answer length to the question; prefer short, direct answers.\
"""


def _route_no_rule_message(message: str) -> str:
    """Return 'GENERAL' for off-catalog questions, 'RULES' for rule lookups.

    Falls back to 'RULES' on any failure so the original search flow is preserved.
    """
    from explanation_engine import call_openai
    try:
        result = call_openai(_GENERAL_ROUTE_SYSTEM, message, max_tokens=5, tier="fast")
        return "GENERAL" if "GENERAL" in result.upper() else "RULES"
    except Exception as e:
        log.warning("[WARN] General router failed, defaulting to RULES: %s", e)
        return "RULES"


def _answer_general(
    message: str, history: list[dict] | None = None, extra_context: str | None = None
) -> dict[str, Any]:
    """Answer a general (non-rule) question as a helpful assistant."""
    from explanation_engine import call_openai
    try:
        ai_text = call_openai(
            _GENERAL_ASSISTANT_SYSTEM,
            _instructions_block(extra_context) + message,
            max_tokens=700,
            history=history,
        )
        log.info("[INFO] _answer_general: answered general question")
        return {"response": ai_text, "rule_id": None, "suggested_followups": []}
    except Exception as e:
        log.error("[ERROR] _answer_general failed: %s", e)
        return {
            "response": "I couldn't answer that right now. Please try again.",
            "rule_id": None,
            "suggested_followups": [],
        }


_EXPLICIT_INTENT_SYSTEM = """\
You are an intent classifier for a data quality rule assistant.
Classify the user's message into exactly one of these intents:

  explain     — asking what the rule does, its purpose, or general explanation
  description — asking for the rule's official description text
  sap_table   — asking which SAP table the rule checks
  sap_column  — asking which SAP column the rule checks
  severity    — asking how critical/severe/important the rule is (e.g. "how critical", "what priority", "is it serious")
  fields      — asking which SAP fields are referenced in the rule logic
  lineage     — asking about data origin, source systems, or where data comes from
  workflow    — asking about pipeline steps, process, or how the rule runs
  show        — asking to see, display, or get full rule details

Reply with exactly one word from the list above. Nothing else.\
"""


def _classify_intent_llm(message: str, rule_id: str) -> str:
    """LLM-based intent classifier for messages that explicitly name a rule ID.

    Falls back to keyword _intent() on any exception.
    """
    from explanation_engine import call_openai
    user_msg = f"Rule mentioned: {rule_id}\nUser message: {message}"
    try:
        result = call_openai(
            _EXPLICIT_INTENT_SYSTEM, user_msg, max_tokens=15, tier="fast",
        ).strip().lower()
        valid = {"explain", "description", "sap_table", "sap_column",
                 "severity", "fields", "lineage", "workflow", "show"}
        return result if result in valid else _intent(message)
    except Exception as exc:
        log.warning("[INTENT] LLM classifier failed, falling back to keyword intent: %s", exc)
        return _intent(message)


def _classify_search_intent(message: str, context_rule_id: str) -> str:
    """Return 'SEARCH' (find a different rule), 'GENERAL' (off-catalog question),
    or 'FOLLOWUP' (about the active rule)."""
    from explanation_engine import call_openai
    user_msg = f"Active rule: {context_rule_id}\nUser message: {message}"
    try:
        result = call_openai(_INTENT_CLASSIFIER_SYSTEM, user_msg, max_tokens=5, tier="fast").upper()
        if "SEARCH" in result:
            return "SEARCH"
        if "GENERAL" in result:
            return "GENERAL"
        return "FOLLOWUP"
    except Exception as e:
        log.warning("[WARN] Intent classifier failed, defaulting to FOLLOWUP: %s", e)
        return "FOLLOWUP"


_FOLLOWUP_SYSTEM = """\
You are a data quality rule expert. The user is asking a follow-up question about a specific data quality rule.
Use the rule details provided to answer the question accurately and concisely.
Focus solely on the user's question. Match response depth to question complexity.
When the user asks about a technical term found in the rule (e.g. order blocks, dunning, credit limit, partner function),
explain it in plain business language as it applies specifically to this rule.
Never invent information not present in the rule context.

If the question is ambiguous or unclear, ask the user to clarify what they mean before attempting an answer.
If the requested information is not present in the rule context at all, say so directly and suggest what related information IS available for this rule (e.g. description, SAP table, severity, rule logic, lineage).\
"""

_DESCRIPTION_SYSTEM = """\
You are a data quality rule expert. Given a user's description, identify the best matching rule(s) from the catalog below.

Guidelines:
- If ONE rule clearly matches: respond with "Found **RULE_ID** — [description]. [One sentence on why it matches.]"
- If 2–3 rules could match: respond with "I found a few rules that could match:\n- **RULE_ID1** — [desc]\n- **RULE_ID2** — [desc]\n\nCould you clarify [specific question to narrow it down]?"
- If no rule matches: respond with "I couldn't find a rule matching that description. [One practical suggestion to refine the search.]"

Always bold rule IDs using **RULE_ID** so the user can click them.\
"""


def _find_rule_by_description(message: str, extra_context: str | None = None) -> dict[str, Any]:
    """Call Azure OpenAI to match a natural-language description to a rule."""
    from data_loader import get_rules
    from explanation_engine import call_openai

    rules = get_rules()

    catalog_lines: list[str] = []
    for _, row in rules.iterrows():
        rid    = _safe(row.get("rule_id", ""))
        desc   = _safe(row.get("rule_description", ""))[:100]
        cat    = _safe(row.get("quality_category", ""))
        tbl    = _safe(row.get("table_name_checked", ""))
        domain = _safe(row.get("domain", ""))
        if rid:
            catalog_lines.append(f"{rid} | {domain} | {cat} | {tbl} | {desc}")

    catalog = "\n".join(catalog_lines)
    user_msg = f"{_instructions_block(extra_context)}RULE CATALOG:\n{catalog}\n\nUSER IS LOOKING FOR: {message}"

    try:
        ai_text = call_openai(_DESCRIPTION_SYSTEM, user_msg, max_tokens=600)
        found_ids = [m.group(1).upper() for m in _RULE_ID_RE.finditer(ai_text)]
        # Single confident match → auto-load the rule card
        rule_id = found_ids[0] if len(found_ids) == 1 else None
        log.info("[INFO] Description search matched rule_ids=%s", found_ids)
        followups = []
        if rule_id:
            followups = _generate_followups(rule_id, message, ai_text[:400], {
                "has_severity": True, "has_lineage": True, "has_yaml": True, "has_sap_fields": True,
            })
        return {"response": ai_text, "rule_id": rule_id, "suggested_followups": followups}
    except Exception as e:
        log.error("[ERROR] _find_rule_by_description failed: %s", e)
        return {
            "response": (
                "I couldn't search for that rule right now. Try:\n\n"
                "- **By rule ID**: `Explain rule RCCOMP_103.1`\n"
                "- **By category**: `List all completeness rules`\n"
                "- **By table**: `Which rules check KNA1?`"
            ),
            "rule_id": None,
            "suggested_followups": [],
        }


def _answer_with_context(
    message: str,
    rule_id: str,
    history: list[dict] | None = None,
    extra_context: str | None = None,
) -> dict[str, Any]:
    """Answer a follow-up question using full Excel + YAML + custom ops context for an active rule."""
    from data_loader import (
        get_rules, get_yaml_raw, find_yaml_for_rule,
        extract_rule_section_from_yaml, get_custom_operations,
        get_referenced_rules,
    )
    from explanation_engine import call_openai

    rules = get_rules()
    match = rules[rules["rule_id"].str.upper() == rule_id.upper()]
    if match.empty:
        return _find_rule_by_description(message, extra_context=extra_context)

    row = match.iloc[0]
    context_parts: list[str] = []
    for field, label in [
        ("rule_id", "Rule ID"),
        ("rule_description", "Description"),
        ("quality_category", "Quality Category"),
        ("table_name_checked", "SAP Table"),
        ("column_name_checked", "SAP Column"),
        ("severity", "Severity"),
        ("rule_logic", "Rule Logic"),
    ]:
        val = _safe(row.get(field, ""))
        if val:
            context_parts.append(f"{label}: {val}")

    # Cross-rule dependencies (dependent_on column + rule_logic references)
    ref_rules = get_referenced_rules(rule_id)
    if ref_rules:
        ref_lines: list[str] = []
        for ref in ref_rules:
            if not ref.get("active"):
                ref_lines.append(f"- {ref['rule_id']} (not in active rules)")
                continue
            parts_ref = [f"Rule ID: {ref['rule_id']}"]
            if ref.get("rule_description"):
                parts_ref.append(f"Description: {ref['rule_description']}")
            if ref.get("rule_logic"):
                parts_ref.append(f"Logic: {ref['rule_logic'][:200]}")
            if ref.get("table_name_checked"):
                parts_ref.append(f"Table: {ref['table_name_checked']}")
            via = "dependency" if ref["source"] == "dependent_on" else "referenced in logic"
            ref_lines.append(f"[{via}] " + " | ".join(parts_ref))
        context_parts.append("Referenced rules:\n" + "\n".join(ref_lines))

    yaml_match = find_yaml_for_rule(rule_id)
    if yaml_match:
        yaml_content = get_yaml_raw(yaml_match["yaml_file"])
        if yaml_content:
            section = extract_rule_section_from_yaml(yaml_content, rule_id)
            context_parts.append(f"Technical Pipeline (YAML section for {rule_id}):\n{section}")

        # Sibling rules co-evaluated in the same pipeline
        sibling_ids = [
            r for r in yaml_match.get("rule_ids_in_yaml", [])
            if r.upper() != rule_id.upper()
        ]
        if sibling_ids:
            sibling_lines: list[str] = []
            for sid in sibling_ids:
                sib_match = rules[rules["rule_id"].str.upper() == sid.upper()]
                if not sib_match.empty:
                    desc = _safe(sib_match.iloc[0].get("rule_description", ""))
                    sibling_lines.append(f"- {sid}: {desc}" if desc else f"- {sid}")
                else:
                    sibling_lines.append(f"- {sid}")
            context_parts.append(
                f"Other rules evaluated in the same pipeline ({yaml_match['name']}):\n"
                + "\n".join(sibling_lines)
            )

        # Include custom operation descriptions referenced by this pipeline
        custom_ops_index = get_custom_operations()
        custom_op_lines: list[str] = []
        for key in yaml_match.get("custom_ops_used", []):
            meta = custom_ops_index.get(key)
            if meta:
                label = meta["class_name"]
                doc = meta.get("docstring", "")
                custom_op_lines.append(f"- {label}: {doc}" if doc else f"- {label}")
        if custom_op_lines:
            context_parts.append(
                "Custom Pipeline Operations used:\n" + "\n".join(custom_op_lines)
            )

    context = "\n\n".join(context_parts)
    user_msg = f"{_instructions_block(extra_context)}RULE CONTEXT:\n{context}\n\nUSER QUESTION: {message}"

    try:
        ai_text = call_openai(_FOLLOWUP_SYSTEM, user_msg, max_tokens=800, history=history)
        log.info("[INFO] _answer_with_context: answered follow-up for rule %s", rule_id)
        followups = _generate_followups(rule_id, message, ai_text[:200], {
            "has_severity": True, "has_lineage": True, "has_yaml": True, "has_sap_fields": True,
        })
        return {"response": ai_text, "rule_id": rule_id, "suggested_followups": followups}
    except Exception as e:
        log.error("[ERROR] _answer_with_context failed: %s", e)
        return {
            "response": "I couldn't answer that right now. Please try again.",
            "rule_id": rule_id,
            "suggested_followups": [],
        }


def _handle_no_rule_id(
    message: str,
    context_rule_id: str | None = None,
    history: list[dict] | None = None,
    allow_general: bool = False,
    extra_context: str | None = None,
) -> dict[str, Any]:
    from data_loader import get_rules
    rules = get_rules()
    low = message.lower()
    category = _detect_category(message)

    # "how many [category] rules" → count
    if any(kw in low for kw in ["how many", "count", "total number", "total"]):
        if category:
            mask = rules["quality_category"].fillna("").str.strip().str.lower() == category
            count = int(mask.sum())
            return {
                "response": f"There are **{count}** active Customer rules in the **{category.title()}** category.",
                "rule_id": None,
                "suggested_followups": [],
            }
        if "quality_category" in rules.columns:
            breakdown: dict[str, int] = {}
            for val in rules["quality_category"].dropna():
                key = str(val).strip().title()
                if key and key.lower() not in ("nan", "none"):
                    breakdown[key] = breakdown.get(key, 0) + 1
            if breakdown:
                lines = [f"- **{cat}**: {cnt}" for cat, cnt in sorted(breakdown.items())]
                return {
                    "response": "**Rule counts by category:**\n" + "\n".join(lines),
                    "rule_id": None,
                    "suggested_followups": [],
                }

    # "list all [category] rules" → up to 10
    if any(kw in low for kw in ["list", "show all", "all rules", "show me"]) and category:
        mask = rules["quality_category"].fillna("").str.strip().str.lower() == category
        subset = rules[mask].head(10)
        total = int(mask.sum())
        lines = []
        for _, r in subset.iterrows():
            rid  = _safe(r.get("rule_id", ""))
            desc = _safe(r.get("rule_description", ""))[:80]
            if rid:
                lines.append(f"- **{rid}** — {desc}" if desc else f"- **{rid}**")
        response = (
            f"**{category.title()} rules** (showing {len(subset)} of {total}):\n"
            + "\n".join(lines)
        )
        followups = []
        if not subset.empty:
            sample_id = _safe(subset.iloc[0].get("rule_id", ""))
            if sample_id:
                followups = _generate_followups(sample_id, message, response[:400], {
                    "has_severity": True, "has_lineage": True, "has_yaml": True, "has_sap_fields": True,
                })
        return {"response": response, "rule_id": None, "suggested_followups": followups}

    # "which rules check [TABLE/FIELD]?" → filter by table or column
    if any(kw in low for kw in ["which rules", "rules check", "rules for", "rules that"]):
        # Extract first ALL_CAPS word (likely a SAP table/field name)
        upper_words = re.findall(r'\b([A-Z][A-Z0-9_]{2,})\b', message)
        if upper_words:
            term = upper_words[0]
            mask_table = rules["table_name_checked"].fillna("").str.upper().str.contains(term, regex=False)
            if "column_name_checked" in rules.columns:
                mask_col = rules["column_name_checked"].fillna("").str.upper().str.contains(term, regex=False)
                combined = mask_table | mask_col
            else:
                combined = mask_table
            subset = rules[combined].head(10)
            if not subset.empty:
                lines = []
                for _, r in subset.iterrows():
                    rid  = _safe(r.get("rule_id", ""))
                    desc = _safe(r.get("rule_description", ""))[:80]
                    if rid:
                        lines.append(f"- **{rid}** — {desc}" if desc else f"- **{rid}**")
                response = f"**Rules related to `{term}`** ({len(subset)} found):\n" + "\n".join(lines)
                followups = []
                sample_id = _safe(subset.iloc[0].get("rule_id", ""))
                if sample_id:
                    followups = _generate_followups(sample_id, message, response[:400], {
                        "has_severity": True, "has_lineage": True, "has_yaml": True, "has_sap_fields": True,
                    })
                return {"response": response, "rule_id": None, "suggested_followups": followups}

    # General mode only: conversational acknowledgements ("thanks", "ok") skip routing
    if allow_general and _is_conversational(message):
        return _answer_general(message, history=history, extra_context=extra_context)

    # If there's an active rule in the panel, classify intent before routing
    if context_rule_id:
        route = _classify_search_intent(message, context_rule_id)
        if route == "SEARCH":
            return _find_rule_by_description(message, extra_context=extra_context)
        if route == "GENERAL" and allow_general:
            return _answer_general(message, history=history, extra_context=extra_context)
        # GENERAL with the flag off falls back to FOLLOWUP (rules-only behavior)
        return _answer_with_context(message, context_rule_id, history=history, extra_context=extra_context)

    # No active rule — in general mode, off-catalog questions get a direct answer
    if allow_general and _route_no_rule_message(message) == "GENERAL":
        return _answer_general(message, history=history, extra_context=extra_context)
    return _find_rule_by_description(message, extra_context=extra_context)


_MAX_HISTORY = 20

_FOLLOWUPS_SYSTEM = """\
You are a follow-up question generator for a data quality rule assistant.

Given the user's question and the answer they just received, suggest 2-3 short follow-up questions they are likely to ask next.

Rules:
- Each suggestion must directly build on the current question or the answer — do not suggest generic questions that could apply to any rule
- Do not repeat the user's current question in any form
- Think about what the user would naturally want to know after seeing this specific answer (e.g. if they asked about a table, they might next ask about the column or severity; if they asked for an explanation, they might want to know which SAP fields are used or how critical the rule is)
- Keep each question short (under 12 words) and phrased as a natural follow-up
- Return only a JSON array of 2-3 strings. No other text.\
"""


_CONVERSATIONAL = {
    "thank you", "thanks", "thank u", "thx", "ty",
    "ok", "okay", "k", "got it", "got that", "understood",
    "great", "awesome", "nice", "cool", "perfect", "good",
    "sounds good", "makes sense", "no worries", "alright",
    "bye", "goodbye", "see you", "cheers", "thankyou", "thankyouu",
    "okay thankyou",
}


def _is_conversational(message: str) -> bool:
    return message.strip().lower().rstrip("!.,") in _CONVERSATIONAL


def _generate_followups(
    rule_id: str,
    question: str,
    answer_snippet: str,
    available: dict,
) -> list[str]:
    """Generate 2-3 contextual follow-up suggestions. Returns [] on any failure."""
    if _is_conversational(question):
        return []
    from explanation_engine import call_openai
    user_msg = (
        f"Rule: {rule_id}\n"
        f"User question: {question}\n"
        f"Answer: {answer_snippet[:400]}\n"
        f"Available context: {available}"
    )
    try:
        result = call_openai(_FOLLOWUPS_SYSTEM, user_msg, max_tokens=120, tier="fast")
        parsed = json.loads(result)
        if isinstance(parsed, list):
            return [str(s) for s in parsed[:3]]
        return []
    except Exception as exc:
        log.warning("[FOLLOWUPS] Failed to generate follow-up suggestions: %s", exc)
        return []


async def _stream_text(text: str, words_per_chunk: int = 5) -> AsyncGenerator[str, None]:
    """Yield pre-computed text as word-group SSE chunks with a small delay between each.

    Used for non-LLM paths so the UI shows progressive output instead of a single pop-in.
    """
    words = text.split(" ")
    i = 0
    while i < len(words):
        group = words[i : i + words_per_chunk]
        chunk = " ".join(group)
        if i + words_per_chunk < len(words):
            chunk += " "
        yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
        i += words_per_chunk
        if i < len(words):
            await asyncio.sleep(0.02)


_MAX_SIBLINGS = 10


def _build_rule_context(
    rule_id: str,
    row: Any,
    logic: str,
    rules: Any,
) -> "tuple[str, list[dict], dict | None]":
    """Build full LLM context for the explain/show intent.

    Performs a second retrieval hop over sibling rules so the LLM always has
    rich metadata for co-evaluated or referenced rules, not just bare IDs.

    Returns:
        ctx        — context string ready to append to the LLM user message
        ref_rules  — list of referenced rule dicts (for the cross-rule notice)
        yaml_match — YAML metadata dict or None
    """
    from data_loader import (
        find_yaml_for_rule, get_yaml_raw, extract_rule_section_from_yaml,
        get_custom_operations, get_referenced_rules,
    )
    from rule_parser import extract_sap_fields
    from sap_mapper import lookup_sap_field
    from explanation_engine import build_sap_context

    raw_fields = extract_sap_fields(logic)
    mapped = [lookup_sap_field(f) for f in raw_fields]
    ctx = build_sap_context(mapped)

    # ── Primary cross-rule dependencies ──────────────────────────────────────
    ref_rules = get_referenced_rules(rule_id)
    if ref_rules:
        ref_lines = []
        for ref in ref_rules:
            if not ref.get("active"):
                continue
            via = "depends on" if ref["source"] == "dependent_on" else "references"
            desc = ref.get("rule_description", "")
            logic_snip = ref.get("rule_logic", "")[:150]
            ref_lines.append(
                f"This rule {via} {ref['rule_id']}: {desc}. Logic: {logic_snip}"
            )
        if ref_lines:
            ctx += "\n\nRule dependencies:\n" + "\n".join(ref_lines)

    # ── YAML pipeline section ─────────────────────────────────────────────────
    yaml_match = find_yaml_for_rule(rule_id)
    yaml_sibling_ids: list[str] = []
    if yaml_match:
        yaml_content = get_yaml_raw(yaml_match["yaml_file"])
        if yaml_content:
            section = extract_rule_section_from_yaml(yaml_content, rule_id)
            ctx += f"\n\nPipeline steps (YAML):\n{section[:1500]}"
        yaml_sibling_ids = [
            r for r in yaml_match.get("rule_ids_in_yaml", [])
            if r.upper() != rule_id.upper()
        ]
        if yaml_sibling_ids:
            sib_lines = []
            for sid in yaml_sibling_ids:
                sib_match = rules[rules["rule_id"].str.upper() == sid.upper()]
                desc = _safe(sib_match.iloc[0].get("rule_description", "")) if not sib_match.empty else ""
                sib_lines.append(f"- {sid}: {desc}" if desc else f"- {sid}")
            ctx += (
                f"\n\nThis rule is part of the '{yaml_match['name']}' pipeline "
                f"which also evaluates:\n" + "\n".join(sib_lines)
            )
        custom_ops_index = get_custom_operations()
        cop_lines = [
            f"{meta['class_name']}: {meta['docstring']}"
            for key in yaml_match.get("custom_ops_used", [])
            if (meta := custom_ops_index.get(key)) and meta.get("docstring")
        ]
        if cop_lines:
            ctx += "\n\nCustom operations: " + "; ".join(cop_lines)

    # ── Second retrieval hop: expand sibling details ──────────────────────────
    # Union both sibling sources, deduplicated, capped at _MAX_SIBLINGS.
    ref_active_ids = [r["rule_id"] for r in ref_rules if r.get("active")]
    all_sibling_ids = list(dict.fromkeys(ref_active_ids + yaml_sibling_ids))[:_MAX_SIBLINGS]

    if all_sibling_ids:
        sibling_blocks: list[str] = []
        for sid in all_sibling_ids:
            sib_match = rules[rules["rule_id"].str.upper() == sid.upper()]
            if sib_match.empty:
                continue  # skip silently
            sib_row = sib_match.iloc[0]
            desc = _safe(sib_row.get("rule_description", ""))[:200]
            cat = _safe(sib_row.get("quality_category", ""))
            sev = _safe(sib_row.get("severity", ""))
            sev_label = _SEVERITY_MAP.get(str(sev), sev)
            table = _safe(sib_row.get("table_name_checked", ""))
            sib_yaml = find_yaml_for_rule(sid)
            pipeline = sib_yaml["name"] if sib_yaml else ""
            block: list[str] = [f"Sibling Rule: {sid}"]
            if desc:
                block.append(f"Description: {desc}")
            if cat or sev_label:
                block.append(f"Category: {cat} | Severity: {sev_label}")
            if pipeline:
                block.append(f"Pipeline: {pipeline}")
            if table:
                block.append(f"Table: {table}")
            sibling_blocks.append("\n".join(block))

        if sibling_blocks:
            ctx += "\n\n## Sibling Rule Context (co-evaluated or referenced rules)\n\n"
            ctx += "\n\n".join(sibling_blocks)
            log.debug(
                "[CONTEXT] Second-hop expanded %d sibling rules for %s",
                len(sibling_blocks), rule_id,
            )

    return ctx, ref_rules, yaml_match


async def stream_message(
    message: str,
    context_rule_id: str | None = None,
    history: list[dict] | None = None,
    mode: str = "analyst",
    allow_general: bool = False,
    extra_context: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream a chat response as Server-Sent Events.

    Each yielded string is a complete SSE data line ending with \\n\\n.
    Event types:
      {"type":"chunk","text":"..."}   — one or more text chunks
      {"type":"status","text":"..."}  — transient progress (persona modes only)
      {"type":"done","rule_id":"...","suggested_followups":[...]}  — final event

    mode="engineer"/"pm" dispatches to persona_agent (length caps enforced by
    the API layer); mode="analyst" is the original rule-Q&A flow.
    """
    if mode in ("engineer", "pm"):
        from persona_agent import stream_persona_message
        async for event in stream_persona_message(
            message, mode, context_rule_id=context_rule_id, history=history,
            extra_context=extra_context,
        ):
            yield event
        return

    message = message.strip()
    if len(message) > 2000:
        raise ValueError("Message exceeds maximum length of 2000 characters.")

    from explanation_engine import _SYSTEM_PROMPT, call_openai_stream

    if history:
        history = history[-_MAX_HISTORY:]

    def _sse(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    rule_id = _extract_rule_id(message)

    # ── No rule ID in message ─────────────────────────────────────────────────
    if not rule_id:
        result = _handle_no_rule_id(
            message, context_rule_id, history=history, allow_general=allow_general,
            extra_context=extra_context,
        )
        text = result.get("response", "")
        rid = result.get("rule_id")
        async for part in _stream_text(text):
            yield part
        followups = result.get("suggested_followups", [])
        yield _sse({"type": "done", "rule_id": rid, "suggested_followups": followups})
        return

    # ── Rule ID found ─────────────────────────────────────────────────────────
    from data_loader import get_rules
    from lineage_service import get_lineage
    from explanation_engine import build_sap_context

    rules = get_rules()
    match = rules[rules["rule_id"].str.upper() == rule_id]

    if match.empty:
        async for part in _stream_text(f"Rule {rule_id} was not found in the active Customer rules."):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id, "suggested_followups": []})
        return

    row = match.iloc[0]
    logic = str(row.get("rule_logic", "") or "")
    intent = _classify_intent_llm(message, rule_id)

    available = {
        "has_severity": bool(_safe(row.get("severity", ""))),
        "has_lineage": True,
        "has_yaml": bool(logic),
        "has_sap_fields": bool(_safe(row.get("column_name_checked", ""))),
    }

    # ── Data-lookup intents (instant, no LLM streaming needed) ───────────────
    if intent == "description":
        desc = _safe(row.get("rule_description", ""))
        response = (f"**Description for {rule_id}:**\n\n{desc}"
                    if desc else f"No description available for rule {rule_id}.")
        async for part in _stream_text(response):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id,
                    "suggested_followups": _generate_followups(rule_id, message, response[:200], available)})
        return

    elif intent == "sap_table":
        response = _format_sap_table_answer(rule_id, _safe(row.get("table_name_checked", "")))
        async for part in _stream_text(response):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id,
                    "suggested_followups": _generate_followups(rule_id, message, response[:200], available)})
        return

    elif intent == "sap_column":
        response = _format_sap_column_answer(
            rule_id,
            _safe(row.get("table_name_checked", "")),
            _safe(row.get("column_name_checked", "")),
        )
        async for part in _stream_text(response):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id,
                    "suggested_followups": _generate_followups(rule_id, message, response[:200], available)})
        return

    elif intent == "severity":
        sev = _safe(row.get("severity", ""))
        sev_label = _SEVERITY_MAP.get(str(sev), sev)
        response = (f"Rule **{rule_id}** has a severity of **{sev_label}**."
                    if sev else f"No severity information available for rule {rule_id}.")
        async for part in _stream_text(response):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id,
                    "suggested_followups": _generate_followups(rule_id, message, response[:200], available)})
        return

    elif intent == "fields":
        response = _format_fields_answer(rule_id, logic)
        async for part in _stream_text(response):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id,
                    "suggested_followups": _generate_followups(rule_id, message, response[:200], available)})
        return

    elif intent in ("lineage", "workflow"):
        lin = get_lineage(rule_id)
        steps = lin.get("workflow_steps", [])
        sources = lin.get("pipeline_sources", [])
        module = lin.get("module", "")
        grp = lin.get("group", "")
        datamarts = lin.get("datamart_or_reference_table_used", "")
        responsibility = lin.get("rule_responsibility", "")
        parts = []
        if module:
            parts.append(f"Module: {module}")
        if grp:
            parts.append(f"Group: {grp}")
        if responsibility:
            parts.append(f"Responsibility: {responsibility}")
        if datamarts:
            dm_list = [d.strip() for d in datamarts.replace("\n", ",").split(",") if d.strip()]
            parts.append(f"Data sources: {', '.join(dm_list[:5])}")
        if sources:
            parts.append(f"Pipeline sources: {', '.join(sources[:5])}")
        if steps:
            parts.append(f"Pipeline steps: {', '.join(steps[:6])}")
        custom_ops = lin.get("custom_operations", [])
        if custom_ops:
            parts.append(f"Custom operations: {'; '.join(custom_ops[:5])}")
        siblings = lin.get("sibling_rules", [])
        if siblings:
            parts.append(
                f"Co-evaluated rules in same pipeline ({lin.get('pipeline_name', '')}): "
                + ", ".join(siblings[:10])
                + (f" (+{len(siblings) - 10} more)" if len(siblings) > 10 else "")
            )
        response = (f"Lineage for rule {rule_id}: " + "; ".join(parts)
                    if parts else f"No lineage information found for rule {rule_id}.")
        async for part in _stream_text(response):
            yield part
        yield _sse({"type": "done", "rule_id": rule_id,
                    "suggested_followups": _generate_followups(rule_id, message, response[:200], available)})
        return

    # ── LLM streaming: explain / show ─────────────────────────────────────────
    from data_loader import get_rules as _get_rules_inner
    ctx, ref_rules, yaml_match = _build_rule_context(rule_id, row, logic, rules)

    user_msg = f"{_instructions_block(extra_context)}Rule logic:\n{logic}"
    if ctx:
        user_msg += f"\n\nField reference (do not use these names in the explanation):\n{ctx}"

    accumulated = ""
    try:
        async for chunk_text in call_openai_stream(
            _SYSTEM_PROMPT,
            user_msg,
            max_tokens=1000,
        ):
            accumulated += chunk_text
            yield _sse({"type": "chunk", "text": chunk_text})
    except Exception as e:
        log.error("[ERROR] stream_message LLM streaming failed: %s", type(e).__name__)
        fallback = "Unable to generate a business explanation for this rule at this time."
        yield _sse({"type": "chunk", "text": fallback})
        accumulated = fallback

    # Append cross-rule reference notice
    active_refs = [r for r in ref_rules if r.get("active")]
    if active_refs:
        note_lines = ["\n\n---\n**This rule references or depends on other rules:**"]
        for ref in active_refs:
            via = "dependency" if ref["source"] == "dependent_on" else "referenced in logic"
            desc = ref.get("rule_description", "")
            desc_snip = f" — {desc[:90]}" if desc else ""
            note_lines.append(f"- **{ref['rule_id']}**{desc_snip} *({via})*")
        note_text = "\n".join(note_lines)
        accumulated += note_text
        async for part in _stream_text(note_text):
            yield part

    available["has_yaml"] = yaml_match is not None
    followups = _generate_followups(rule_id, message, accumulated[:200], available)
    yield _sse({"type": "done", "rule_id": rule_id, "suggested_followups": followups})


def handle_message(
    message: str,
    context_rule_id: str | None = None,
    history: list[dict] | None = None,
    allow_general: bool = False,
    extra_context: str | None = None,
) -> dict[str, Any]:
    message = message.strip()
    if len(message) > 2000:
        raise ValueError("Message exceeds maximum length of 2000 characters.")
    if history:
        history = history[-_MAX_HISTORY:]
    rule_id = _extract_rule_id(message)
    if not rule_id:
        return _handle_no_rule_id(
            message, context_rule_id, history=history, allow_general=allow_general,
            extra_context=extra_context,
        )

    from data_loader import get_rules
    from lineage_service import get_lineage
    from explanation_engine import explain_rule, build_sap_context

    rules = get_rules()
    match = rules[rules["rule_id"].str.upper() == rule_id]

    if match.empty:
        return {
            "response": f"Rule {rule_id} was not found in the active Customer rules.",
            "rule_id": rule_id,
            "suggested_followups": [],
        }

    row = match.iloc[0]
    logic = str(row.get("rule_logic", "") or "")
    intent = _classify_intent_llm(message, rule_id)

    if intent == "description":
        desc = _safe(row.get("rule_description", ""))
        response = (
            f"**Description for {rule_id}:**\n\n{desc}"
            if desc else f"No description available for rule {rule_id}."
        )

    elif intent == "sap_table":
        response = _format_sap_table_answer(rule_id, _safe(row.get("table_name_checked", "")))

    elif intent == "sap_column":
        response = _format_sap_column_answer(
            rule_id,
            _safe(row.get("table_name_checked", "")),
            _safe(row.get("column_name_checked", "")),
        )

    elif intent == "severity":
        sev = _safe(row.get("severity", ""))
        sev_label = _SEVERITY_MAP.get(str(sev), sev)
        response = (
            f"Rule **{rule_id}** has a severity of **{sev_label}**."
            if sev else f"No severity information available for rule {rule_id}."
        )

    elif intent == "fields":
        response = _format_fields_answer(rule_id, logic)

    elif intent in ("lineage", "workflow"):
        lin = get_lineage(rule_id)
        steps = lin.get("workflow_steps", [])
        sources = lin.get("pipeline_sources", [])
        module = lin.get("module", "")
        grp = lin.get("group", "")
        datamarts = lin.get("datamart_or_reference_table_used", "")
        responsibility = lin.get("rule_responsibility", "")
        parts = []
        if module:
            parts.append(f"Module: {module}")
        if grp:
            parts.append(f"Group: {grp}")
        if responsibility:
            parts.append(f"Responsibility: {responsibility}")
        if datamarts:
            dm_list = [d.strip() for d in datamarts.replace("\n", ",").split(",") if d.strip()]
            parts.append(f"Data sources: {', '.join(dm_list[:5])}")
        if sources:
            parts.append(f"Pipeline sources: {', '.join(sources[:5])}")
        if steps:
            parts.append(f"Pipeline steps: {', '.join(steps[:6])}")
        custom_ops = lin.get("custom_operations", [])
        if custom_ops:
            parts.append(f"Custom operations: {'; '.join(custom_ops[:5])}")
        siblings = lin.get("sibling_rules", [])
        if siblings:
            parts.append(
                f"Co-evaluated rules in same pipeline ({lin.get('pipeline_name', '')}): "
                + ", ".join(siblings[:10])
                + (f" (+{len(siblings) - 10} more)" if len(siblings) > 10 else "")
            )
        response = (
            f"Lineage for rule {rule_id}: " + "; ".join(parts)
            if parts else f"No lineage information found for rule {rule_id}."
        )

    else:  # explain or show
        from explanation_engine import explain_rule
        ctx, ref_rules, yaml_match = _build_rule_context(rule_id, row, logic, rules)
        instr = _instructions_block(extra_context)
        response = explain_rule(logic, (instr + ctx) if instr else ctx)

        # Append a clear notice when the rule references other rules
        active_refs = [r for r in ref_rules if r.get("active")]
        if active_refs:
            note_lines = ["\n\n---\n**This rule references or depends on other rules:**"]
            for ref in active_refs:
                via = "dependency" if ref["source"] == "dependent_on" else "referenced in logic"
                desc = ref.get("rule_description", "")
                desc_snip = f" — {desc[:90]}" if desc else ""
                note_lines.append(f"- **{ref['rule_id']}**{desc_snip} *({via})*")
            response += "\n".join(note_lines)

    followups = _generate_followups(rule_id, message, response[:200], {
        "has_severity": bool(_safe(row.get("severity", ""))),
        "has_lineage": True,
        "has_yaml": bool(_safe(row.get("rule_logic", ""))),
        "has_sap_fields": bool(_safe(row.get("column_name_checked", ""))),
    })
    return {"response": response, "rule_id": rule_id, "suggested_followups": followups}
