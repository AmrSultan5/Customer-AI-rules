import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd

# ── Env vars must be set before importing main ─────────────────────────────────
os.environ.setdefault("RULE_AGENT_API_TOKEN", "test-secret-token")
os.environ.setdefault("CHAT_RATE_LIMIT", "1")   # very low limit for 429 tests
os.environ.setdefault("RULE_AGENT_ENV", "development")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("ANTHROPIC_API_KEY", "fake-key-for-tests")

# Use a throwaway SQLite file for the DB layer (db.py reads this at import).
# Tests reset the schema via db.reset_db() so the starting state is always clean.
_TEST_DB = Path(tempfile.gettempdir()) / "rule_agent_test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB.as_posix()}")

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
_data_loader.get_custom_operations.return_value = {}
_data_loader.get_custom_op_source.return_value = ""
_data_loader.reload_all.return_value = {
    "rules_loaded": 2, "yaml_pipelines": 0, "custom_ops": 0, "sap_fields": 0,
}

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
# probe_llm is called by the async /health endpoint — must be an AsyncMock
# so that `await probe_llm()` resolves immediately instead of hanging.
_explanation_engine.probe_llm = AsyncMock(return_value=None)

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

import asyncio

import pytest


@pytest.fixture(scope="session", autouse=True)
def _init_test_schema():
    """Create the database schema once before any test (lifespan does not run
    for module-level TestClient instances)."""
    import db

    asyncio.run(db.reset_db())
    yield

