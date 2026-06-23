import os
from pyspark.sql.dataframe import DataFrame
from pyspark.sql import SparkSession
from typing import Optional

from pyspark.sql.functions import *
from pyspark.sql import functions as F
from pyspark.sql import *
import pandas as pd

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_common.utils.column_utils import ColumnUtils
from governance_data_quality_processes.operation_config.upper_config import UpperOperationConfig
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext


class UpperOperation(BaseOperation):
    """
    Upper provides way to convert string expressions to Upper case
    """

    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        """
        Convert latest dataframe (saved on ctx) columns string values to Upper case

        :param TransformationContext ctx: shared context across transformation process,
            contains dict: each operation name to transform output
        :return DataFrame: table with converted columns to string Uppercase
        """
        assert isinstance(self._config, UpperOperationConfig)

        df = ctx[self._config.context_name]
        for column in self._config.params.columns:
            df = df.withColumn(column, F.upper(F.col(column)))
        return df
