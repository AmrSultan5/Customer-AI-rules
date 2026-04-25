"""
STEP 9 — ChatAgent
Intent detection and routing for the /chat endpoint.
"""

import logging
import re
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

_INTENT_CLASSIFIER_SYSTEM = """\
You are a router for a data quality rule assistant.
The user has an active rule open in their panel. Decide whether their message is:
- A follow-up question or request about that active rule → reply FOLLOWUP
- A search or request to find a different or new rule by description → reply SEARCH

Examples of FOLLOWUP: "what table does it check?", "explain the severity", "what does this mean?", "how does it work?"
Examples of SEARCH: "find a rule that checks phone numbers", "is there a rule for email validation?", "what rule handles address conformity?"

Reply with exactly one word: FOLLOWUP or SEARCH. Nothing else.\
"""


def _classify_search_intent(message: str, context_rule_id: str) -> str:
    """Return 'SEARCH' if the user is looking for a different rule, 'FOLLOWUP' if asking about the active rule."""
    from explanation_engine import call_azure_openai
    user_msg = f"Active rule: {context_rule_id}\nUser message: {message}"
    try:
        result = call_azure_openai(_INTENT_CLASSIFIER_SYSTEM, user_msg, max_tokens=5)
        return "SEARCH" if "SEARCH" in result.upper() else "FOLLOWUP"
    except Exception as e:
        log.warning("[WARN] Intent classifier failed, defaulting to FOLLOWUP: %s", e)
        return "FOLLOWUP"


_FOLLOWUP_SYSTEM = """\
You are a data quality rule expert. The user is asking a follow-up question about a specific data quality rule.
Use the rule details provided to answer the question accurately and concisely.
Focus solely on the user's question. Be brief — 2-4 sentences maximum.
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


def _find_rule_by_description(message: str) -> dict[str, Any]:
    """Call Azure OpenAI to match a natural-language description to a rule."""
    from data_loader import get_rules
    from explanation_engine import call_azure_openai

    rules = get_rules()

    catalog_lines: list[str] = []
    for _, row in rules.iterrows():
        rid  = _safe(row.get("rule_id", ""))
        desc = _safe(row.get("rule_description", ""))[:100]
        cat  = _safe(row.get("quality_category", ""))
        tbl  = _safe(row.get("table_name_checked", ""))
        if rid:
            catalog_lines.append(f"{rid} | {cat} | {tbl} | {desc}")

    catalog = "\n".join(catalog_lines)
    user_msg = f"RULE CATALOG:\n{catalog}\n\nUSER IS LOOKING FOR: {message}"

    try:
        ai_text = call_azure_openai(_DESCRIPTION_SYSTEM, user_msg, max_tokens=600)
        found_ids = [m.group(1).upper() for m in _RULE_ID_RE.finditer(ai_text)]
        # Single confident match → auto-load the rule card
        rule_id = found_ids[0] if len(found_ids) == 1 else None
        log.info("[INFO] Description search matched rule_ids=%s", found_ids)
        return {"response": ai_text, "rule_id": rule_id}
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
        }


def _answer_with_context(message: str, rule_id: str, history: list[dict] | None = None) -> dict[str, Any]:
    """Answer a follow-up question using full Excel + YAML + custom ops context for an active rule."""
    from data_loader import (
        get_rules, get_yaml_raw, find_yaml_for_rule,
        extract_rule_section_from_yaml, get_custom_operations,
        get_referenced_rules,
    )
    from explanation_engine import call_azure_openai

    rules = get_rules()
    match = rules[rules["rule_id"].str.upper() == rule_id.upper()]
    if match.empty:
        return _find_rule_by_description(message)

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
            context_parts.append(
                f"Other rules evaluated in the same pipeline ({yaml_match['name']}): "
                + ", ".join(sibling_ids)
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
    user_msg = f"RULE CONTEXT:\n{context}\n\nUSER QUESTION: {message}"

    try:
        ai_text = call_azure_openai(_FOLLOWUP_SYSTEM, user_msg, max_tokens=400, history=history)
        log.info("[INFO] _answer_with_context: answered follow-up for rule %s", rule_id)
        return {"response": ai_text, "rule_id": rule_id}
    except Exception as e:
        log.error("[ERROR] _answer_with_context failed: %s", e)
        return {
            "response": "I couldn't answer that right now. Please try again.",
            "rule_id": rule_id,
        }


def _handle_no_rule_id(message: str, context_rule_id: str | None = None, history: list[dict] | None = None) -> dict[str, Any]:
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
        return {"response": response, "rule_id": None}

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
                return {
                    "response": f"**Rules related to `{term}`** ({len(subset)} found):\n" + "\n".join(lines),
                    "rule_id": None,
                }

    # If there's an active rule in the panel, classify intent before routing
    if context_rule_id:
        if _classify_search_intent(message, context_rule_id) == "SEARCH":
            return _find_rule_by_description(message)
        return _answer_with_context(message, context_rule_id, history=history)

    # No active rule — go straight to description search
    return _find_rule_by_description(message)


_MAX_HISTORY = 20


def handle_message(message: str, context_rule_id: str | None = None, history: list[dict] | None = None) -> dict[str, Any]:
    if history:
        history = history[-_MAX_HISTORY:]
    rule_id = _extract_rule_id(message)
    if not rule_id:
        return _handle_no_rule_id(message, context_rule_id, history=history)

    from data_loader import get_rules
    from rule_parser import extract_sap_fields
    from sap_mapper import lookup_sap_field
    from lineage_service import get_lineage
    from explanation_engine import explain_rule, build_sap_context

    rules = get_rules()
    match = rules[rules["rule_id"].str.upper() == rule_id]

    if match.empty:
        return {
            "response": f"Rule {rule_id} was not found in the active Customer rules.",
            "rule_id": rule_id,
        }

    row = match.iloc[0]
    logic = str(row.get("rule_logic", "") or "")
    intent = _intent(message)

    if intent == "description":
        desc = _safe(row.get("rule_description", ""))
        response = (
            f"**Description for {rule_id}:**\n\n{desc}"
            if desc else f"No description available for rule {rule_id}."
        )

    elif intent == "sap_table":
        table = _safe(row.get("table_name_checked", ""))
        response = (
            f"The SAP table checked by rule **{rule_id}** is: `{table}`"
            if table else f"No SAP table information available for rule {rule_id}."
        )

    elif intent == "sap_column":
        col = _safe(row.get("column_name_checked", ""))
        response = (
            f"The SAP column checked by rule **{rule_id}** is: `{col}`"
            if col else f"No SAP column information available for rule {rule_id}."
        )

    elif intent == "severity":
        sev = _safe(row.get("severity", ""))
        sev_label = _SEVERITY_MAP.get(str(sev), sev)
        response = (
            f"Rule **{rule_id}** has a severity of **{sev_label}**."
            if sev else f"No severity information available for rule {rule_id}."
        )

    elif intent == "fields":
        raw_fields = extract_sap_fields(logic)
        mapped = [lookup_sap_field(f) for f in raw_fields]
        names = [f"{f['field']} ({f['business_name']})" for f in mapped]
        response = (
            f"Rule {rule_id} references these fields: "
            f"{', '.join(names) if names else 'none detected'}."
        )

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
        from data_loader import (
            find_yaml_for_rule, get_yaml_raw, extract_rule_section_from_yaml,
            get_custom_operations, get_referenced_rules,
        )
        raw_fields = extract_sap_fields(logic)
        mapped = [lookup_sap_field(f) for f in raw_fields]
        ctx = build_sap_context(mapped)

        # Include cross-rule dependencies in the explanation context
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

        # Enrich context with YAML pipeline section, sibling rules, and custom op descriptions
        yaml_match = find_yaml_for_rule(rule_id)
        if yaml_match:
            yaml_content = get_yaml_raw(yaml_match["yaml_file"])
            if yaml_content:
                section = extract_rule_section_from_yaml(yaml_content, rule_id)
                ctx += f"\n\nPipeline steps (YAML):\n{section[:1500]}"
            sibling_ids = [
                r for r in yaml_match.get("rule_ids_in_yaml", [])
                if r.upper() != rule_id.upper()
            ]
            if sibling_ids:
                ctx += (
                    f"\n\nThis rule is part of the '{yaml_match['name']}' pipeline "
                    f"which also evaluates: {', '.join(sibling_ids)}"
                )
            custom_ops_index = get_custom_operations()
            cop_lines = []
            for key in yaml_match.get("custom_ops_used", []):
                meta = custom_ops_index.get(key)
                if meta and meta.get("docstring"):
                    cop_lines.append(f"{meta['class_name']}: {meta['docstring']}")
            if cop_lines:
                ctx += "\n\nCustom operations: " + "; ".join(cop_lines)

        response = explain_rule(logic, ctx)

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

    return {"response": response, "rule_id": rule_id}
