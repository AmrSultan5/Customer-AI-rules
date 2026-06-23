from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf
from pyspark.sql.types import StringType, StructType, StructField, IntegerType, FloatType, ArrayType, DoubleType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
from pyspark.ml.feature import StringIndexer

import re
import mlflow.pyfunc

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.machine_learning.model_pyfunc_predict_config import (
    ModelPyfuncPredictOperationConfig,
)


class ModelPyfuncPredictOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, ModelPyfuncPredictOperationConfig)
        df = ctx[self._config.context_name]

        column_to_predict = self._config.params.input_value
        CATALOG = self._config.params.catalog
        SCHEMA = self._config.params.schema
        REG_MODEL_NAME = self._config.params.registered_model_name
        ALIAS = self._config.params.alias

        model_uri = f"models:/{CATALOG}.{SCHEMA}.{REG_MODEL_NAME}@{ALIAS}"
        loaded_model = mlflow.pyfunc.load_model(model_uri)

        # schema returned by UDF
        schema = StructType([
            StructField("input_value_category", StringType(), True),
            StructField("input_value_probability", DoubleType(), True)
        ])

        def predict(text):
            result = loaded_model.predict(text)
            return [{"input_value_category": r[0], "input_value_probability": r[1]} for r in result]

        predict_udf = udf(predict, ArrayType(schema))

        result = df.withColumn("prediction_struct", predict_udf(col(column_to_predict))) \
                   .withColumn("input_value_category", col("prediction_struct").getItem(0).getItem("input_value_category")) \
                   .withColumn("input_value_probability", col("prediction_struct").getItem(0).getItem("input_value_probability")) \
                   .drop("prediction_struct")

        return result
