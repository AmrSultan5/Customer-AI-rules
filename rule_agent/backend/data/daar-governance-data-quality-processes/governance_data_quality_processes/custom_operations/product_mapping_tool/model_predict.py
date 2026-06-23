from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf, pandas_udf
from pyspark.sql.types import StringType, StructType, StructField, IntegerType, FloatType, ArrayType, DoubleType
from typing import Optional
from pyspark.sql import SparkSession, DataFrame
from pyspark.ml.feature import StringIndexer

import re
import mlflow.pyfunc
import pandas as pd

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.product_mapping_tool.model_predict_config import (
    ModelPredictOperationConfig,
)

class ModelPredictOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext):
        spark = SparkSession.builder.getOrCreate()

        spark.conf.set("spark.sql.execution.arrow.maxRecordsPerBatch", "512")

        assert isinstance(self._config, ModelPredictOperationConfig)
        df = ctx[self._config.context_name]

        column_to_predict = self._config.params.input_value
        CATALOG = self._config.params.catalog
        SCHEMA = self._config.params.schema
        REG_MODEL_NAME = self._config.params.registered_model_name
        ALIAS = self._config.params.alias

        model_uri = f"models:/{CATALOG}.{SCHEMA}.{REG_MODEL_NAME}@{ALIAS}"
        loaded_model = mlflow.pyfunc.load_model(model_uri)

        schema = StructType([
            StructField("input_value_category", StringType()),
            StructField("input_value_probability", DoubleType())
        ])

        @pandas_udf(schema)
        def predict_udf(text_series):
            preds = loaded_model.predict(text_series)

            return pd.DataFrame({
                "input_value_category": [p[0] for p in preds],
                "input_value_probability": [float(p[1]) for p in preds]
            })

        result = (
            df.withColumn("category_and_proba", predict_udf(col(column_to_predict))) \
              .select("*", "category_and_proba.*") \
              .drop("category_and_proba")
        )

        return result



















