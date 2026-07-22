"""
StructuredTabularProvider — wraps the existing data_loader.py deterministic
retrieval (Excel/YAML/custom-ops) behind the KnowledgeProvider contract.

This is a WRAPPER, not a rewrite: for customer_sap the descriptor's paths and
field_map already match data_loader's hardcoded constants (Phase 0), so this
provider calls the same module-level data_loader functions/caches the app
already uses — it does not parameterize data_loader by source/field_map, and
does not change what data gets loaded or how it's cached. The descriptor's
field_map is used only to translate rows into Entity objects.

`build_context` (and the async `retrieve_context_for_query` wrapper around it)
is the deterministic cross-rule + YAML context assembly formerly inline in
chat_agent._build_rule_context — moved here so the provider owns context
building; chat_agent now delegates to it (see chat_agent._get_provider()).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from kb._schema import KBDescriptor
from providers.base import Entity, KnowledgeProvider

log = logging.getLogger(__name__)

# Same cap as the pre-refactor chat_agent._build_rule_context.
_MAX_SIBLINGS = 10


def _safe(val: Any) -> str:
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


class StructuredTabularProvider(KnowledgeProvider):
    """Deterministic lookup/search/context over a tabular (Excel + YAML) KB."""

    def __init__(self, descriptor: KBDescriptor):
        self.kb = descriptor
        # Same pattern + flag as the pre-refactor chat_agent._RULE_ID_RE.
        self._id_re = re.compile(descriptor.id_pattern, re.IGNORECASE)

    # ---- entity mapping -------------------------------------------------------

    def _col(self, row: Any, logical: str) -> str:
        """Resolve a logical rules-table field to its value on `row`.

        data_loader already normalizes/aliases the loaded DataFrame's columns
        to these logical names (see data_loader.load_rules), so the physical
        name from field_map is used as-is against the already-normalized row.
        """
        fm = self.kb.field_map.rules
        physical = fm[logical].physical if logical in fm else logical
        return _safe(row.get(physical, ""))

    def _row_to_entity(self, row: Any) -> Entity:
        rule_id = self._col(row, "rule_id")
        return Entity(
            id=rule_id.upper(),
            title=self._col(row, "rule_description") or None,
            domain=self._col(row, "domain") or None,
            category=self._col(row, "quality_category") or None,
            logic=self._col(row, "rule_logic") or None,
            raw=row.to_dict(),
            source_ref=rule_id or None,
        )

    # ---- entity lookup ----------------------------------------------------------

    def get_entity(self, entity_id: str) -> Entity | None:
        import data_loader

        rules = data_loader.get_rules()
        match = rules[rules["rule_id"].str.upper() == entity_id.upper()]
        if match.empty:
            return None
        return self._row_to_entity(match.iloc[0])

    # ---- search ------------------------------------------------------------------

    def search(
        self, query: str, *, limit: int = 20, category: str | None = None
    ) -> list[Entity]:
        import data_loader

        subset = data_loader.get_rules()
        if category:
            mask = (
                subset["quality_category"].fillna("").str.strip().str.lower()
                == category.strip().lower()
            )
            subset = subset[mask]
        q = query.strip().lower()
        if q:
            desc_mask = subset["rule_description"].fillna("").str.lower().str.contains(q, regex=False)
            id_mask = subset["rule_id"].fillna("").str.lower().str.contains(q, regex=False)
            subset = subset[desc_mask | id_mask]
        return [self._row_to_entity(r) for _, r in subset.head(limit).iterrows()]

    # ---- entity-id extraction -----------------------------------------------------

    def extract_entity_id(self, text: str) -> str | None:
        m = self._id_re.search(text)
        return m.group(1).upper() if m else None

    # ---- context assembly (moved from chat_agent._build_rule_context) -------------

    def build_context(
        self, rule_id: str, row: Any, logic: str, rules: Any
    ) -> tuple[str, list[dict], dict | None]:
        """Build full LLM context for the explain/show intent.

        Performs a second retrieval hop over sibling rules so the LLM always
        has rich metadata for co-evaluated or referenced rules, not just bare
        IDs. Identical algorithm to the pre-refactor
        chat_agent._build_rule_context — same signature and return shape, so
        chat_agent's call sites are unchanged.

        Returns:
            ctx        — context string ready to append to the LLM user message
            ref_rules  — list of referenced rule dicts (for the cross-rule notice)
            yaml_match — YAML metadata dict or None
        """
        import data_loader

        ctx = ""

        # ── Primary cross-rule dependencies ────────────────────────────────────
        ref_rules = data_loader.get_referenced_rules(rule_id)
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
        yaml_match = data_loader.find_yaml_for_rule(rule_id)
        yaml_sibling_ids: list[str] = []
        if yaml_match:
            yaml_content = data_loader.get_yaml_raw(yaml_match["yaml_file"])
            if yaml_content:
                section = data_loader.extract_rule_section_from_yaml(yaml_content, rule_id)
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
            custom_ops_index = data_loader.get_custom_operations()
            cop_lines = [
                f"{meta['class_name']}: {meta['docstring']}"
                for key in yaml_match.get("custom_ops_used", [])
                if (meta := custom_ops_index.get(key)) and meta.get("docstring")
            ]
            if cop_lines:
                ctx += "\n\nCustom operations: " + "; ".join(cop_lines)

        # ── Second retrieval hop: expand sibling details ────────────────────────
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
                sev_label = self.kb.vocab.severity_map.get(str(sev), sev)
                table = _safe(sib_row.get("table_name_checked", ""))
                sib_yaml = data_loader.find_yaml_for_rule(sid)
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

    async def retrieve_context_for_query(
        self, query: str, *, entity_id: str | None = None, limit: int = 8
    ) -> str:
        """KnowledgeProvider contract: deterministic context block as a string.

        Deterministic retrieval here is entity-scoped (matching the old
        _build_rule_context behavior); `query` is accepted for interface
        symmetry with future RAG providers but is not full-text searched.
        Returns "" if entity_id is missing/unknown.
        """
        if not entity_id:
            return ""
        import data_loader

        rules = data_loader.get_rules()
        match = rules[rules["rule_id"].str.upper() == entity_id.upper()]
        if match.empty:
            return ""
        row = match.iloc[0]
        logic = str(row.get("rule_logic", "") or "")
        ctx, _ref_rules, _yaml_match = self.build_context(entity_id, row, logic, rules)
        return ctx

    # ---- lifecycle ------------------------------------------------------------------

    def reload(self) -> dict:
        import data_loader

        return data_loader.reload_all(descriptor=self.kb)

    def capabilities(self) -> set[str]:
        return {"entity", "search", "context"}
