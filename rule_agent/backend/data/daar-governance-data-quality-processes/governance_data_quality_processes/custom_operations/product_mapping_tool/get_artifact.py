from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf
from pyspark.sql.types import StringType, StructType, StructField, IntegerType, FloatType, ArrayType, DoubleType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
from pyspark.ml.feature import StringIndexer

import json
import re
import mlflow.pyfunc

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext


from governance_data_quality_processes.custom_operation_configs.product_mapping_tool.get_artifact_config import (
    GetArtifactOperationConfig,
)

class GetArtifactOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, GetArtifactOperationConfig)
        
        CATALOG = self._config.params.catalog
        SCHEMA = self._config.params.schema
        REG_MODEL_NAME = self._config.params.registered_model_name
        ALIAS = self._config.params.alias
        ARTIFACT_PATH = self._config.params.artifact_path

        model_uri = f"models:/{CATALOG}.{SCHEMA}.{REG_MODEL_NAME}@{ALIAS}"

        art_path = mlflow.artifacts.download_artifacts(
            artifact_uri=f"{model_uri}/{ARTIFACT_PATH}"
        )

        with open(art_path, "r") as f:
            art_table = json.load(f)

        artifact = self.spark_session.createDataFrame(art_table)

        return artifact
