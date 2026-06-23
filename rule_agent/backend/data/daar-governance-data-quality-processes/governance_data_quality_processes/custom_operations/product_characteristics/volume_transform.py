from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf
from pyspark.sql.types import StringType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
import re

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.product_characteristics.volume_transform_config import (
    VolumeTransformOperationConfig,
)

class VolumeTransformOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, VolumeTransformOperationConfig)
        df = ctx[self._config.context_name]
        column_to_transform = self._config.params.input_value

        def transform_volume(product_name: str) -> str:
            match = re.search(r'(\d+(\.\d+)?\s*l)', product_name)
            if match is None:
                return product_name
            value = re.sub(r'[a-zA-Z\s]', '', match.group(0))
            value = float(value) * 1000
            if value < 1000:
                return re.sub(r'(\d+(\.\d+)?\s*l)', f'{int(value)}ml', product_name)
            else:  
                return product_name
            return product_name

        transform_volume_udf = udf(transform_volume, StringType())

        return df.withColumn("input_value_transformed", transform_volume_udf(col(column_to_transform)))
