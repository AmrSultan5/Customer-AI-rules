"""
Test configuration. Sets env vars and stubs all heavy I/O modules
BEFORE main.py is imported, so tests run without real data files or Azure calls.
"""
import os
import sys
from unittest.mock import MagicMock

import pandas as pd

# ── Env vars must be set before importing main ─────────────────────────────────
os.environ.setdefault("RULE_AGENT_API_TOKEN", "test-secret-token")
os.environ.setdefault("CHAT_RATE_LIMIT", "1")   # very low limit for 429 tests
os.environ.setdefault("RULE_AGENT_ENV", "development")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://fake.endpoint.example.com/openai")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "fake-key-for-tests")
os.environ.setdefault("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# ── Minimal rule catalogue ─────────────────────────────────────────────────────
MOCK_RULES = pd.DataFrame(
    {
        "rule_id":            ["TEST_1", "TEST_2"],
        "rule_description":   ["Test rule 1", "Test rule 2"],
        "quality_category":   ["Completeness", "Validity"],
        "table_name_checked": ["KNA1", "KNA1"],
        "column_name_checked":["KUNNR", "NAME1"],
        "severity":           [1, 2],
        "rule_logic":         ["KUNNR IS NOT NULL", "NAME1 > 0"],
        "sub_domain":         ["Customer", "Customer"],
        "is_active":          [1, 1],
    }
)

# ── Stub heavy dependencies before any import of main ─────────────────────────
_data_loader = MagicMock()
_data_loader.get_rules.return_value = MOCK_RULES
_data_loader.get_sap_map.return_value = pd.DataFrame()
_data_loader.get_yaml_rules.return_value = {}
_data_loader.get_yaml_raw.return_value = ""
_data_loader.find_yaml_for_rule.return_value = None
_data_loader.get_referenced_rules.return_value = []
_data_loader.extract_rule_section_from_yaml.return_value = ""

_lineage = MagicMock()
_lineage.get_lineage.return_value = {
    "workflow_steps": [],
    "yaml_reference": "",
    "pipeline_sources": [],
}

_rule_parser = MagicMock()
_rule_parser.extract_sap_fields.return_value = []

_sap_mapper = MagicMock()
_sap_mapper.lookup_sap_field.return_value = {"field": "KUNNR", "business_name": "Customer"}

_explanation_engine = MagicMock()
_explanation_engine.explain_rule.return_value = "Test explanation."
_explanation_engine.build_sap_context.return_value = ""

_schema_validator = MagicMock()

_chat_agent = MagicMock()
_chat_agent.handle_message.return_value = {"response": "Test chat response.", "rule_id": None}

sys.modules["data_loader"] = _data_loader
sys.modules["lineage_service"] = _lineage
sys.modules["rule_parser"] = _rule_parser
sys.modules["sap_mapper"] = _sap_mapper
sys.modules["explanation_engine"] = _explanation_engine
sys.modules["schema_validator"] = _schema_validator
sys.modules["chat_agent"] = _chat_agent

# Add backend directory to path so `import main` works
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
