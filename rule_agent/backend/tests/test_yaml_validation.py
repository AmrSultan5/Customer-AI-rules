"""
Unit tests for yaml_validation.validate_pipeline_yaml (paste-back YAML check).

conftest.py stubs data_loader as a MagicMock module; the `yv_loader` fixture
configures the indexes the validator cross-checks against.
"""
import pandas as pd
import pytest

from yaml_validation import validate_pipeline_yaml, MAX_YAML_CHARS

RULES = pd.DataFrame({"rule_id": ["RCCOMP_1.1", "RCVALI_2.1"]})

YAMLS = {
    "pipe_a": {
        "name": "pipe_a",
        "yaml_file": "customer/v1/pipe_a.yaml",
        "sources": ["dm_customer_general"],
        "rule_ids_in_yaml": ["RCCOMP_1.1"],
        "custom_ops_used": [],
    },
}

CUSTOM_OPS = {
    "ops.email_check": {
        "class_name": "EmailCheckOperation",
        "docstring": "",
        "file": "custom_operations/ops/email_check.py",
    },
}

VALID_YAML = """\
transform:
  name: pipe_test
  operations:
    - kind: read_dataio
      params:
        object_name: dm_customer_general
    - kind: add
      params:
        name: rule_id
        expression: "'RCCOMP_1.1'"
"""


@pytest.fixture
def yv_loader(monkeypatch):
    import data_loader

    monkeypatch.setattr(data_loader, "get_rules", lambda: RULES)
    monkeypatch.setattr(data_loader, "get_yaml_rules", lambda: YAMLS)
    monkeypatch.setattr(data_loader, "get_custom_operations", lambda: CUSTOM_OPS)
    return data_loader


def test_valid_pipeline_passes(yv_loader):
    result = validate_pipeline_yaml(VALID_YAML)
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["summary"]["transform_name"] == "pipe_test"
    assert result["summary"]["operation_count"] == 2
    assert result["summary"]["rule_ids"] == ["RCCOMP_1.1"]
    assert result["summary"]["sources"] == ["dm_customer_general"]


def test_empty_input_is_error(yv_loader):
    result = validate_pipeline_yaml("   ")
    assert result["valid"] is False
    assert "empty" in result["errors"][0]


def test_oversized_input_is_error(yv_loader):
    result = validate_pipeline_yaml("x" * (MAX_YAML_CHARS + 1))
    assert result["valid"] is False
    assert "maximum size" in result["errors"][0]


def test_syntax_error_reports_line(yv_loader):
    result = validate_pipeline_yaml("transform:\n  name: [unclosed")
    assert result["valid"] is False
    assert "syntax error" in result["errors"][0]
    assert "line" in result["errors"][0]


def test_missing_transform_key(yv_loader):
    result = validate_pipeline_yaml("foo: bar")
    assert result["valid"] is False
    assert "transform" in result["errors"][0]


def test_non_list_operations(yv_loader):
    result = validate_pipeline_yaml("transform:\n  name: t\n  operations: notalist")
    assert result["valid"] is False
    assert any("operations" in e for e in result["errors"])


def test_empty_operations_is_warning_not_error(yv_loader):
    result = validate_pipeline_yaml("transform:\n  name: t\n  operations: []")
    assert result["valid"] is True
    assert any("empty" in w for w in result["warnings"])


def test_list_shaped_params_accepted(yv_loader):
    """Real join/add operations carry `params` as a list of mappings."""
    text = (
        "transform:\n  name: t\n  operations:\n"
        "    - kind: join\n      params:\n"
        "        - left: a\n          right: b\n"
        "        - on: id\n"
    )
    result = validate_pipeline_yaml(text)
    assert result["valid"] is True


def test_list_params_with_non_mapping_entry_is_error(yv_loader):
    text = (
        "transform:\n  name: t\n  operations:\n"
        "    - kind: join\n      params:\n        - just_a_string\n"
    )
    result = validate_pipeline_yaml(text)
    assert result["valid"] is False
    assert any("params" in e for e in result["errors"])


def test_operation_without_kind_is_error(yv_loader):
    text = "transform:\n  name: t\n  operations:\n    - params: {}\n"
    result = validate_pipeline_yaml(text)
    assert result["valid"] is False
    assert any("no `kind`" in e for e in result["errors"])


def test_unknown_custom_op_is_error(yv_loader):
    text = (
        "transform:\n  name: t\n  operations:\n"
        "    - kind: governance_data_quality_processes.custom_operations.ops.invented.FakeOperation\n"
    )
    result = validate_pipeline_yaml(text)
    assert result["valid"] is False
    assert any("ops.invented" in e for e in result["errors"])


def test_known_custom_op_passes(yv_loader):
    text = (
        "transform:\n  name: t\n  operations:\n"
        "    - kind: governance_data_quality_processes.custom_operations.ops.email_check.EmailCheckOperation\n"
    )
    result = validate_pipeline_yaml(text)
    assert result["valid"] is True
    assert result["summary"]["custom_ops"] == ["ops.email_check"]


def test_unknown_rule_id_is_warning(yv_loader):
    text = (
        "transform:\n  name: t\n  operations:\n"
        "    - kind: add\n      params:\n        name: rule_id\n"
        "        expression: \"'RCNEW_99.1'\"\n"
    )
    result = validate_pipeline_yaml(text)
    assert result["valid"] is True
    assert any("RCNEW_99.1" in w and "inventory" in w for w in result["warnings"])


def test_unknown_source_is_warning(yv_loader):
    text = (
        "transform:\n  name: t\n  operations:\n"
        "    - kind: read_dataio\n      params:\n        object_name: dm_made_up_table\n"
    )
    result = validate_pipeline_yaml(text)
    assert result["valid"] is True
    assert any("dm_made_up_table" in w for w in result["warnings"])
