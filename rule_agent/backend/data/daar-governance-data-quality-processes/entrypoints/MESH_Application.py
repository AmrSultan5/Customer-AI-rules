# Databricks notebook source
# MAGIC %md
# MAGIC ### This notebook is called by data factory pipeline APPLICATION_DATAMESH

# COMMAND ----------

import os
import json

from datamesh_transformation import TransformationProcess

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
