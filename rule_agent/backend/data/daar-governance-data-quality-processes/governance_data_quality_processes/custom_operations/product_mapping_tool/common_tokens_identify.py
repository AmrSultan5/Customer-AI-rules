from pyspark.sql.functions import col, collect_list, array_distinct, array_except, size, aggregate, when, array
from pyspark.sql.types import StringType, StructType, StructField, IntegerType, FloatType, ArrayType, DoubleType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
from pyspark.ml.feature import StringIndexer

import json
import re

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext


from governance_data_quality_processes.custom_operation_configs.product_mapping_tool.common_tokens_identify_config import (
    CommonTokensIdentifyOperationConfig,
)


class CommonTokensIdentifyOperation(BaseOperation):
    """
    Computes the common tokens across a set of token lists per record ID,
    then removes them from each tokens_list.
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> DataFrame:
        df: DataFrame = ctx[self._config.context_name]
        group_cols = self._config.params.group_cols
        tokens_list_col = self._config.params.tokens_list_col

        # -----------------------------------------
        # STEP 1: Compute common tokens across tokens_list
        # -----------------------------------------
        common_tokens = (
            df.groupBy(*group_cols)
              .agg(
                  aggregate(
                      array_distinct(collect_list(array_distinct(tokens_list_col))),
                      array().cast(ArrayType(StringType())),
                      lambda acc, x: when(size(acc) == 0, x).otherwise(array_except(acc, array_except(acc, x)))
                  ).alias("common_tokens")
              )
        )

        return common_tokens
