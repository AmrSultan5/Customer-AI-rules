from pyspark.sql.dataframe import DataFrame
import pyspark.sql.functions as F
from pyspark.sql import functions as sf, DataFrame
from typing import Optional

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from governance_data_quality_processes.operation_config.case_when_config import CaseWhenOperationConfig
from datamesh_transformation.common.context import TransformationContext


class CaseWhenOperation(BaseOperation):
    """
    Case When functions
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, CaseWhenOperationConfig)

        df = ctx[self._config.context_name]
        df = df.withColumn(
            "red_outlet_suppressed_check",
            sf.expr(
                "CASE WHEN bic_csup_cust IN ('C', 'DR', 'E', 'F', 'G', 'R', 'S', 'S1', 'S3', 'S4', 'SP', 'SY', 'TS','U') AND (bic_credoutlt = 'X' OR bic_credoutlt = 'W') THEN '0' ELSE '1' END"
            ),
        )
        return df
