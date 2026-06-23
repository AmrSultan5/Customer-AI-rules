# Databricks notebook source
# MAGIC %md
# MAGIC ### This notebook is called by data factory pipeline APPLICATION_DATAMESH

# COMMAND ----------

import os
import json

from datamesh_transformation import TransformationProcess
from datamesh_transformation.operations import read_dataio

# COMMAND ----------

dbutils.widgets.text("p_ETL_CONFIG_PATH", "", "")
dbutils.widgets.get("p_ETL_CONFIG_PATH")
config_path = getArgument("p_ETL_CONFIG_PATH")

dbutils.widgets.text("p_PROCESS_RUN_ID", "", "")
dbutils.widgets.get("p_PROCESS_RUN_ID")
process_run_id = getArgument("p_PROCESS_RUN_ID")

dbutils.widgets.text("p_PREVIOUS_PROCESS_RUN_ID", "", "")
dbutils.widgets.get("p_PREVIOUS_PROCESS_RUN_ID")
previous_process_run_id = getArgument("p_PREVIOUS_PROCESS_RUN_ID")

dbutils.widgets.text("p_DYNAMIC_PARAMETERS", "", "")
dbutils.widgets.get("p_DYNAMIC_PARAMETERS")
dynamic_params = json.loads(getArgument("p_DYNAMIC_PARAMETERS")) if getArgument("p_DYNAMIC_PARAMETERS") else {}

storage_id = os.getenv("DATA_IO_STORAGE_ID")
ad_id = os.getenv("DATA_IO_AD_ID")

# COMMAND ----------

if "ReadDataioOperationBase" not in dir(read_dataio):
    read_dataio.ReadDataioOperationBase = read_dataio.ReadDataioOperation


class ReadDataioOperation(read_dataio.ReadDataioOperationBase):
    def __init__(self, operation_config, spark_session, dynamic_params):
        if (
            (operation_config.params.dataio.layer not in ["application", "curated"])
            or (
                operation_config.params.dataio.layer == "application"
                and operation_config.params.module != "data_control_center"
            )
            or (
                operation_config.params.dataio.layer == "curated"
                and operation_config.params.object_name != "dim_rules_inventory"
            )
        ):
            operation_config.params.dataio.storage_id = os.getenv("DATA_IO_PROD_STORAGE_ID")
        super().__init__(operation_config, spark_session, dynamic_params)


read_dataio.ReadDataioOperation = ReadDataioOperation

# COMMAND ----------

trans_proc = TransformationProcess(
    spark_session=spark,
    config_path=config_path,
    module="governance_data_quality_processes.configs",
    jinja_params={
        "dataio": {"storage_id": storage_id, "ad_id": ad_id},
        "process_run_id": process_run_id,
        "previous_process_run_id": previous_process_run_id,
        **dynamic_params,
    },
)
trans_proc.execute()
