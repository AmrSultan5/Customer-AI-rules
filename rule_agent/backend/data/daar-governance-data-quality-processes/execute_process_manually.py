# Databricks notebook source
# MAGIC %md
# MAGIC # INIT

# COMMAND ----------

import os
import json
from uuid import uuid4
from datetime import datetime

from datamesh_transformation import TransformationProcess
from datamesh_transformation.operations import read_dataio

from governance_data_quality_processes.utils.patterns import Singleton
from governance_data_quality_processes.utils.schema_configuration import SchemaConfiguration

# COMMAND ----------

# MAGIC %md
# MAGIC #CONFIG

# COMMAND ----------

config_path = "/processes/data_quality/ca/data_control_center/.../....yaml"

unique_id = str(uuid4())
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
process_run_id = f"{timestamp}_{unique_id}"

previous_process_run_id = process_run_id

dynamic_params = {}

# COMMAND ----------

# MAGIC %md
# MAGIC #MOCK READ DATAIO TO PROD

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

# MAGIC %md
# MAGIC #EXECUTE

# COMMAND ----------

try:
    del Singleton._Singleton__instances[SchemaConfiguration]
except KeyError:
    pass

trans_proc = TransformationProcess(
    spark_session=spark,
    config_path=config_path,
    module="governance_data_quality_processes.configs",
    jinja_params={
        "dataio": {
            "storage_id": os.getenv("DATA_IO_STORAGE_ID"),
            "ad_id": os.getenv("DATA_IO_AD_ID")
        },
        "process_run_id": process_run_id,
        "previous_process_run_id": previous_process_run_id,
        **dynamic_params,
    },
)
trans_proc.execute()