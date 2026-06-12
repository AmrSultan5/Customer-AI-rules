"""
Unit tests for impact_service (deterministic rule impact analysis).

conftest.py stubs data_loader as a MagicMock module; each test configures the
stub via the `impact_loader` fixture (same pattern as test_persona.py).
"""
import pandas as pd
import pytest

import impact_service

RULES = pd.DataFrame(
    {
        "rule_id":            ["RCCOMP_1.1", "RCCOMP_2.1", "RCVALI_3.1"],
        "rule_description":   ["Email not empty", "Email format valid", "Postal code valid"],
        "quality_category":   ["Completeness", "Validity", "Validity"],
        "table_name_checked": ["KNA1", "KNA1", "KNA1"],
        "column_name_checked":["SMTP_ADDR", "SMTP_ADDR", "PSTLZ"],
        "severity":           ["1", "2", "2"],
        "rule_logic":         ["SMTP_ADDR IS NOT NULL", "regex check", "country format"],
        "dependent_on":       ["", "RCCOMP_1.1", ""],
    }
)

YAMLS = {
    "pipe_email": {
        "name": "pipe_email",
        "yaml_file": "customer/v1/pipe_email.yaml",
        "sources": ["dm_customer_general"],
        "rule_ids_in_yaml": ["RCCOMP_1.1", "RCCOMP_2.1"],
        "custom_ops_used": ["ops.email_check"],
    },
    "pipe_other": {
        "name": "pipe_other",
        "yaml_file": "customer/v1/pipe_other.yaml",
        "sources": ["dm_customer_address"],
        "rule_ids_in_yaml": ["RCVALI_3.1"],
        "custom_ops_used": ["ops.email_check"],
    },
}

CUSTOM_OPS = {
    "ops.email_check": {
        "class_name": "EmailCheckOperation",
        "docstring": "Checks emails",
        "file": "custom_operations/ops/email_check.py",
    },
}


@pytest.fixture
def impact_loader(monkeypatch):
    import data_loader

    monkeypatch.setattr(data_loader, "get_rules", lambda: RULES)
    monkeypatch.setattr(data_loader, "get_yaml_rules", lambda: YAMLS)
    monkeypatch.setattr(data_loader, "get_custom_operations", lambda: CUSTOM_OPS)
    monkeypatch.setattr(
        data_loader, "get_referenced_rules",
        lambda rid: (
            [{"rule_id": "RCCOMP_1.1", "source": "dependent_on", "active": True,
              "rule_description": "Email not empty"}]
            if rid.upper() == "RCCOMP_2.1" else []
        ),
    )
    return data_loader


def test_unknown_rule_returns_none(impact_loader):
    assert impact_service.get_rule_impact("NOPE_999") is None


def test_dependents_found_via_dependent_on(impact_loader):
    impact = impact_service.get_rule_impact("RCCOMP_1.1")
    dep_ids = [d["rule_id"] for d in impact["dependent_rules"]]
    assert dep_ids == ["RCCOMP_2.1"]
    assert impact["dependent_rules"][0]["via"] == "dependent_on"


def test_referenced_rules_forward(impact_loader):
    impact = impact_service.get_rule_impact("RCCOMP_2.1")
    assert [r["rule_id"] for r in impact["referenced_rules"]] == ["RCCOMP_1.1"]


def test_pipelines_and_co_located_rules(impact_loader):
    impact = impact_service.get_rule_impact("RCCOMP_1.1")
    assert len(impact["pipelines"]) == 1
    pipe = impact["pipelines"][0]
    assert pipe["yaml_file"] == "golden/customer/v1/pipe_email.yaml"
    assert pipe["co_located_rules"] == ["RCCOMP_2.1"]


def test_custom_ops_include_other_users(impact_loader):
    impact = impact_service.get_rule_impact("RCCOMP_1.1")
    assert len(impact["custom_ops"]) == 1
    op = impact["custom_ops"][0]
    assert op["file"] == "data/custom_operations/ops/email_check.py"
    # pipe_other uses the same op but does not evaluate this rule
    assert op["also_used_by_pipelines"] == ["pipe_other"]


def test_same_target_rules_match_table_and_column(impact_loader):
    impact = impact_service.get_rule_impact("RCCOMP_1.1")
    # RCCOMP_2.1 shares KNA1/SMTP_ADDR; RCVALI_3.1 is on a different column
    assert [s["rule_id"] for s in impact["same_target_rules"]] == ["RCCOMP_2.1"]


def test_files_to_touch_deduped(impact_loader):
    impact = impact_service.get_rule_impact("RCCOMP_1.1")
    files = impact["files_to_touch"]
    assert files[0] == "data/dim_rules_inventory.xlsx"
    assert "golden/customer/v1/pipe_email.yaml" in files
    assert "data/custom_operations/ops/email_check.py" in files
    assert len(files) == len(set(files))


def test_dot_underscore_rule_id_variants_match(impact_loader, monkeypatch):
    """RCCOMP_1.1 in dependent_on must also be found when written RCCOMP_1_1."""
    rules = RULES.copy()
    rules.loc[rules["rule_id"] == "RCCOMP_2.1", "dependent_on"] = "RCCOMP_1_1"
    monkeypatch.setattr(impact_loader, "get_rules", lambda: rules)
    impact = impact_service.get_rule_impact("RCCOMP_1.1")
    assert [d["rule_id"] for d in impact["dependent_rules"]] == ["RCCOMP_2.1"]


def test_format_impact_for_context_mentions_dependents(impact_loader):
    text = impact_service.format_impact_for_context("RCCOMP_1.1")
    assert "IMPACT ANALYSIS" in text
    assert "RCCOMP_2.1" in text
    assert "custom_operations/ops/email_check.py" in text


def test_format_impact_for_context_empty_for_isolated_rule(impact_loader, monkeypatch):
    """A rule with no dependents/pipelines/ops/overlaps yields no impact block."""
    lonely = pd.DataFrame(
        {
            "rule_id": ["RCSOLO_9.9"], "rule_description": ["Lonely"],
            "table_name_checked": [""], "column_name_checked": [""],
            "rule_logic": ["x"], "dependent_on": [""],
        }
    )
    monkeypatch.setattr(impact_loader, "get_rules", lambda: lonely)
    monkeypatch.setattr(impact_loader, "get_yaml_rules", lambda: {})
    monkeypatch.setattr(impact_loader, "get_referenced_rules", lambda rid: [])
    assert impact_service.format_impact_for_context("RCSOLO_9.9") == ""


def test_format_impact_for_context_unknown_rule_returns_empty(impact_loader):
    assert impact_service.format_impact_for_context("NOPE_1") == ""
