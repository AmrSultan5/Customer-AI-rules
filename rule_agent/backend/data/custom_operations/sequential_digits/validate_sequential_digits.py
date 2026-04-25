
from pyspark.sql.dataframe import DataFrame
from pyspark.sql.functions import col, pandas_udf
from pyspark.sql.types import IntegerType
from typing import Optional
import pandas as pd

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from governance_data_quality_processes.custom_operation_configs.sequential_digits.validate_sequential_digits_config import (
    ValidateSequentialDigitsOperationConfig,
)

class ValidateSequentialDigitsOperation(BaseOperation):
    """Flags tax number columns containing ascending or descending sequential digit patterns (e.g. '12345', '98765') that indicate likely placeholder or invalid values."""

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, ValidateSequentialDigitsOperationConfig)
        df = ctx[self._config.context_name]

        # Dynamically collect the 4 column names from the config
        columns_to_validate = [
            self._config.params.tax_0_value,
            self._config.params.tax_1_value,
            self._config.params.tax_2_value,
            self._config.params.tax_3_value,
        ]

        def is_sequential_digits(s: Optional[str]) -> int:
            if not s or not s.isdigit() or len(s) < 2:
                return 0
            increasing = all(int(s[i]) + 1 == int(s[i + 1]) for i in range(len(s) - 1))
            decreasing = all(int(s[i]) - 1 == int(s[i + 1]) for i in range(len(s) - 1))
            return int(increasing or decreasing)

        @pandas_udf(returnType=IntegerType())
        def validate_udf(series: pd.Series) -> pd.Series:
            return series.apply(is_sequential_digits)

        for column in columns_to_validate:
            result_column = f"{column}_is_sequential"
            df = df.withColumn(result_column, validate_udf(col(column)))

        return df
