from typing import Optional

from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operations.base import BaseOperation
from pyspark.sql import functions as F
from pyspark.sql.dataframe import DataFrame

from governance_data_quality_processes.operation_config.lower_config import LowerOperationConfig
#from unified_data_model.utils.logging import log_time


class LowerOperation(BaseOperation):
    """
    Lowers provides way to convert string expressions to lower case
    """

    #@log_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        """
        Convert latest dataframe (saved on ctx) columns string values to lower case

        :param TransformationContext ctx: shared context across transformation process,
            contains dict: each operation name to transform output
        :return DataFrame: table with converted columns to string lowercase
        """
        assert isinstance(self._config, LowerOperationConfig)

        df = ctx[self._config.context_name]
        for column in self._config.params.columns:
            df = df.withColumn(column, F.lower(F.col(column)))
        return df
