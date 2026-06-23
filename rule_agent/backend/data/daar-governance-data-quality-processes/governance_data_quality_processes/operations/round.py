from typing import Optional

from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operations.base import BaseOperation
from pyspark.sql import functions as F
from pyspark.sql.dataframe import DataFrame

from governance_data_quality_processes.operation_config.round_config import RoundOperationConfig
#from unified_data_model.utils.logging import log_time


class RoundOperation(BaseOperation):
    """
    Round provides way to round numeric expressions
    """

    #@log_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        """
        Rounds latest dataframe (saved on ctx) numeric columns

        :param TransformationContext ctx: shared context across transformation process,
            contains dict: each operation name to transform output
        :return DataFrame: table with converted columns rounded
        """
        assert isinstance(self._config, RoundOperationConfig)

        df = ctx[self._config.context_name]
        for column in self._config.params.columns:
            df = df.withColumn(column, F.round(F.col(column), 2))
        return df
