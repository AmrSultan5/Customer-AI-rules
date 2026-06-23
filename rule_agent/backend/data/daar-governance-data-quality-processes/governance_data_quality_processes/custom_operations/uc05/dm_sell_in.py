from typing import Optional
from pyspark.sql.dataframe import DataFrame
from governance_data_quality_processes import *
from governance_data_quality_processes.custom_operation_configs.uc05.dm_sell_in_config import (
    DmSellinOperationConfig,
)
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from governance_data_quality_processes.utils.dataio import DataioUtils


class DmSellinOperation(BaseOperation):
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, DmSellinOperationConfig)

        df = None
        return df