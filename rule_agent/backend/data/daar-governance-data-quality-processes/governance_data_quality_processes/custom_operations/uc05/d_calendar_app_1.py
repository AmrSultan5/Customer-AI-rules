from typing import Optional
from pyspark.sql.dataframe import DataFrame
from governance_data_quality_processes import *
from governance_data_quality_processes.custom_operation_configs.uc05.d_calendar_config import (
    DCalendarOperationConfig,
)
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from governance_data_quality_processes.utils.dataio import DataioUtils
import pandas as pd
from pyspark.sql.functions import to_timestamp
from pyspark.sql.functions import *


class DCalendarOperation(BaseOperation):
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, DCalendarOperationConfig)

        calendar_repo = DataioUtils.get_repository(
            config=self._config.params.src_calendar, spark_session=self._spark_session
        )
        df_calendar = calendar_repo.read()

        df_calendar.withColumn("date_id", to_timestamp(col("date_id"), "yyyyMMdd").cast("date")).withColumn(
            "week_445", lpad("week_445", 2, "0")
        ).withColumn("month_445", lpad("month_445", 2, "0")).select(
            col("date_id").alias("date"),
            col("month_445").alias("month"),
            col("week_445").alias("week"),
            col("year_445").alias("year"),
            concat("year_445", "month_445").alias("year_month"),
            concat("year_445", "week_445").alias("year_week"),
            lit("ca").alias("country"),
        )
        df_calendar.show()
        return df_calendar
