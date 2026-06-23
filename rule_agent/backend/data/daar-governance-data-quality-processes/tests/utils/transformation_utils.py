import os
import io
import yaml
from typing import Dict
from jinja2 import Template

from datamesh_common.spark.spark_utils import normalize_schema
from datamesh_transformation import TransformationProcess
from datamesh_common.utils.column_utils import ColumnUtils
from pyspark.sql import SparkSession
from tests.constants import ACTUAL_DATA_ROOT_PATH, EXPECTED_DATA_ROOT_PATH


def get_application_path(config_path: str, jinja_params: Dict) -> str:
    with io.open(config_path, mode="r") as fp:
        config = yaml.safe_load(Template(fp.read()).render(**jinja_params or {}))
        for operation in config["transform"]["operations"]:
            if operation["kind"] in ["write_dataio", "write_dataio_req"]:
                application_path = os.path.join(
                    operation["params"]["application_name"],
                    operation["params"]["country"],
                    operation["params"]["module"],
                    operation["params"]["namespace"],
                    operation["params"]["object_name"],
                    operation["params"]["schema_version"],
                )
    assert application_path
    return application_path


def fix_expected_schema(application_path: str, spark_session: SparkSession, mapping: Dict[str, str] = None):
    # To use when we want to fix schema as it has changed. This is utility function
    expected_path = os.path.join(EXPECTED_DATA_ROOT_PATH, application_path)
    df_expected = spark_session.read.format("delta").load(expected_path)
    if not mapping:
        df_expected = ColumnUtils.standardize_column_names(df_expected)
    else:
        for current_name, new_name in mapping.items():
            df_expected = df_expected.withColumnRenamed(current_name, new_name)
    df_expected.write.format("delta").mode("overwrite").save(f"{expected_path}_fixed")


def transform(config_path: str, dynamic_params: Dict, spark_session: SparkSession):
    config_path = f"governance_data_quality_processes/configs/{config_path}"
    jinja_params = {
        "dataio": {"storage_id": "local"},
        "previous_process_run_id": "process_001",
        "process_run_id": "process_001",
        **dynamic_params,
    }
    application_path = get_application_path(config_path=config_path, jinja_params=jinja_params)
    trans_proc = TransformationProcess(
        spark_session=spark_session,
        config_path=config_path,
        jinja_params=jinja_params,
    )
    trans_proc.execute()
    assert validate(application_path=application_path, spark_session=spark_session)


def validate(application_path: str, spark_session: SparkSession):
    actual_path = os.path.join(ACTUAL_DATA_ROOT_PATH, application_path)
    expected_path = os.path.join(EXPECTED_DATA_ROOT_PATH, application_path)
    df_actual = spark_session.read.format("delta").load(actual_path).drop("process_run_id")
    df_expected = normalize_schema(
        df=spark_session.read.format("delta").load(expected_path), object_schema=df_actual.schema
    ).drop("process_run_id")
    df_diff = df_actual.subtract(df_expected)
    if not df_diff.head():
        return True
    df_diff.show()
    return False
