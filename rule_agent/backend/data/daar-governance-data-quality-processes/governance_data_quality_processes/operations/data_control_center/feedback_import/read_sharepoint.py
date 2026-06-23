import shutil
from typing import Optional, Tuple, List
from dataclasses import field
from marshmallow_dataclass import dataclass
from office365.runtime.client_request_exception import ClientRequestException
from pyspark.sql import Row
import pyspark.sql.functions as f
from pyspark.sql.window import Window
from pyspark.sql.dataframe import DataFrame
from pyspark.sql.types import StringType, StructType, StructField
from datamesh_transformation.operations import read_sharepoint
from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operation_configs.read_sharepoint_config import (
    ReadSharepointOperationConfig,
    ReadSharepointConfig,
)


@dataclass
class CustomReadSharepointConfig(ReadSharepointConfig):
    as_of_date: str = field(default=False)
    """execution date"""


@dataclass
class CustomReadSharepointOperationConfig(ReadSharepointOperationConfig):
    """
    Operation configuration for writing data frame into local (mounted) data lake
    """

    params: CustomReadSharepointConfig


class ReadSharepointOperation(read_sharepoint.ReadSharepointOperation):
    """
    This process read feadback data from sharepoint and write it to local path.
    Files are downloaded into as_of_date coresponding cccweek subfolder.
    """

    def _get_period_calendar_dates(self, df_calendar: DataFrame, as_of_date: str) -> Tuple[str, List[Row]]:
        """
        It calculate current week based on as_of_date from CCH calendar, and calculate list of previous dates.
        If current week is also first month week process calculate dates for whole past month
        otherwise it is only last week.

        :param df_calendar: CCH Calednar dataframe
        :type df_calendar: DataFrame
        :param as_of_date: Current date
        :type as_of_date: str
        :return: Tuple with current week and lis of days for export
        :rtype: Tuple[str, List[Row]]
        """
        week_in_month_window = Window.partitionBy("fiscper").orderBy(f.col("cccweek").asc())
        df_calendar = df_calendar.withColumn("week_in_month", f.dense_rank().over(week_in_month_window))
        df_calendar = df_calendar.withColumn(
            "first_week_of_month", f.when(f.col("week_in_month") == 1, f.lit(True)).otherwise(f.lit(False))
        )
        current_week_calendar_details = (
            df_calendar.filter(f.col("calday") == as_of_date)
            .select("cccweek", "fiscper", "first_week_of_month")
            .distinct()
            .collect()[0]
        )
        if current_week_calendar_details.first_week_of_month is True:
            df_previous_fiscper = (
                df_calendar.filter(f.col("fiscper") < current_week_calendar_details.fiscper)
                .select(f.max("fiscper").alias("fiscper"))
                .distinct()
            )
            df_previous_period = (
                df_calendar.join(df_previous_fiscper, on="fiscper", how="left_semi").select("cccweek").distinct()
            )
        else:
            df_previous_period = (
                df_calendar.filter(f.col("cccweek") < current_week_calendar_details.cccweek)
                .select(f.max("cccweek").alias("cccweek"))
                .distinct()
            )
        week_days_list = (
            df_calendar.join(df_previous_period, on="cccweek", how="left_semi")
            .select(f.replace(f.col("calday").cast("string"), f.lit("-"), f.lit("_")).alias("calday"))
            .distinct()
            .collect()
        )
        return (current_week_calendar_details.cccweek, week_days_list)

    def _clear_local_path(self) -> None:
        """
        Clear local path if it is exist. In case of rerun.

        :rtype: None
        """
        try:
            shutil.rmtree(self._config.params.local_path)
            print(f"Directory {self._config.params.local_path} cleared successfully.")
        except FileNotFoundError:
            print(f"Directory {self._config.params.local_path} does not exists.")

    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, CustomReadSharepointOperationConfig)
        df_calendar = ctx["df_calendar"]
        as_of_date = self._config.params.as_of_date
        remote_path = self._config.params.remote_path
        current_week, week_days_list = self._get_period_calendar_dates(df_calendar, as_of_date)
        self._config.params.local_path = f"{self._config.params.local_path}/{current_week}/"
        self._clear_local_path()
        df_files = None
        for day in week_days_list:
            self._config.params.remote_path = f"{remote_path}{day.calday}/"
            try:
                df_current_files = super().transform(ctx)
                if df_files:
                    df_files = df_files.unionByName(df_current_files, allowMissingColumns=False)
                else:
                    df_files = df_current_files
            except ClientRequestException as ex:
                if ex.code.split(",")[-1].lower().strip() == "system.io.filenotfoundexception":
                    print(f"Feedback not found for day {day.calday}.")
                else:
                    raise ex
        if df_files is None:
            schema = StructType([StructField("filename", StringType(), True)])
            df_files = self._spark_session.sparkContext.emptyRDD().toDF(schema)
        return df_files
