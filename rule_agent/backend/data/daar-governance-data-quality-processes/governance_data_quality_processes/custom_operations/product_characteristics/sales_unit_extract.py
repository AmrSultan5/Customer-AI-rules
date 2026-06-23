from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf
from pyspark.sql.types import StringType, ArrayType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
import re

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.product_characteristics.sales_unit_extract_config import (
    SalesUnitExtractOperationConfig,
)


class SalesUnitExtractOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, SalesUnitExtractOperationConfig)
        df = ctx[self._config.context_name]
        column_to_transform = self._config.params.input_value
        col_name = self._config.params.output_col_name
        col_name_us = col_name + '_sales_unit'

        def extract_sales_unit(text):
            # Regex pattern to match 'x6', '6x', or '6 x 200ml'
            pattern = r'(\bx\d+\b|\b\d+x\b|\b\d+\s*x\s*\b|\b\d+\s*x\b|\b\s*x\s*\d+\b|\d+x)'
            match = re.search(pattern, text)  # case insensitive search
            if match:
                unit_size = match.group(0)
                unit_size = re.sub(r'x', '', unit_size).strip()
                if unit_size != '':
                    unit_size = f'x{int(unit_size)}'
                    
                modified_text = re.sub(pattern, '', text).strip()

                return (unit_size, modified_text)
            return ('', text)

        # Register the UDF
        extract_sales_unit_udf = udf(extract_sales_unit, ArrayType(StringType()))

        result = df.withColumn("us_and_text", extract_sales_unit_udf(col(column_to_transform))) \
                   .withColumn(col_name_us, col("us_and_text").getItem(0)) \
                   .withColumn(col_name, regexp_replace(col("us_and_text").getItem(1), '\\s+', ' ')) \
                   .drop("us_and_text")

        return result
