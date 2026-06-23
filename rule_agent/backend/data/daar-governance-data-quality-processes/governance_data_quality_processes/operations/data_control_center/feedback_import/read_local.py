import os
from dataclasses import field
from marshmallow_dataclass import dataclass
import pyspark.sql.functions as f
from pyspark.sql.window import Window
from pyspark.sql.dataframe import DataFrame
from pyspark.errors.exceptions.captured import AnalysisException
from datamesh_transformation.operations import read_local
from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operation_configs.read_local_config import (
    ReadLocalOperationConfig,
    ReadLocalConfig,
)


@dataclass
class CustomReadLocalConfig(ReadLocalConfig):
    as_of_date: str = field(default=False)
    check_name: str = field(default=False)
    """execution date"""


@dataclass
class CustomReadLocalOperationConfig(ReadLocalOperationConfig):
    """
    Operation configuration for writing data frame into local (mounted) data lake
    """

    params: CustomReadLocalConfig


class ReadLocalOperation(read_local.ReadLocalOperation):
    """
    This process read current week feadback data from local storage based on as_of_date from CCH calendar.
    It combine current feedback with previous and deduplicate by primary_key using latest date.
    If there is no feedback for the current week process return empty dataframe.
    """

    def _get_current_week(self, df_calendar: DataFrame, as_of_date: str) -> str:
        """
        It calculate current week based on as_of_date from CCH calendar.

        :param df_calendar: CCH Calednar dataframe
        :type df_calendar: DataFrame
        :param as_of_date: Current date
        :type as_of_date: str
        :return: Current cccweek number
        :rtype: str
        """
        current_week = (
            df_calendar.filter(f.col("calday") == as_of_date).select("cccweek").distinct().collect()[0].cccweek
        )
        return current_week

    def _combine_feedbacks(self, df_feedback_previous: DataFrame, df_feedback: DataFrame) -> DataFrame:
        """
        It combine new feedback with previous, deduplicate by primary_key, and cast schema to the expected form.

        :param df_feedback_previous: Previous feedback data
        :type df_feedback_previous: DataFrame
        :param df_feedback: Current week feedback data
        :type df_feedback: DataFrame
        :return: Combined feedbacks
        :rtype: DataFrame
        """
        cast_types = {df_field.name: df_field.dataType for df_field in df_feedback_previous.schema.fields}
        df_feedback = df_feedback.withColumnRenamed("false_flag", "false_positive_flag")
        df_feedback = df_feedback.withColumnRenamed("comment", "feedback_reason")
        df_feedback = df_feedback.withColumn("file_name", f.element_at(f.split(f.col("file_name"), os.sep), -1))
        df_feedback = df_feedback.withColumn(
            "feedback_timestamp",
            f.to_timestamp(f.replace(f.substring("file_name", 0, 19), f.lit("T"), f.lit("_")), "yyyy_MM_dd_HH_mm_ss"),
        )
        df_feedback = df_feedback.select(list(cast_types.keys()))
        for field_name, field_type in cast_types.items():
            df_feedback = df_feedback.withColumn(field_name, f.col(field_name).cast(field_type))
        df_feedback = df_feedback.filter(f.col("primary_key").isNotNull() & ((f.col("false_positive_flag").isNotNull()) | (f.col("feedback_reason").isNotNull())))
        df_feedback = df_feedback.withColumn("new_feedback_flag", f.lit(1))
        df_feedback_previous = df_feedback_previous.withColumn("new_feedback_flag", f.lit(0))
        df_feedback = df_feedback.unionByName(df_feedback_previous, allowMissingColumns=False)
        deduplication_window = Window.partitionBy("primary_key").orderBy(
            f.col("feedback_timestamp").desc(), f.col("new_feedback_flag").desc()
        )
        df_feedback = df_feedback.withColumn("rank", f.row_number().over(deduplication_window))
        df_feedback = df_feedback.filter(f.col("rank") == 1)
        df_feedback = df_feedback.drop("rank", "new_feedback_flag")
        return df_feedback

    def transform(self, ctx: TransformationContext) -> DataFrame:
        assert isinstance(self._config, CustomReadLocalOperationConfig)
        df_feedback_previous = ctx["df_feedback_previous"]
        df_calendar = ctx["df_calendar"]
        df_feedback_files = ctx["df_feedback_files"]
        as_of_date = self._config.params.as_of_date
        check_name = self._config.params.check_name
        current_week = self._get_current_week(df_calendar, as_of_date)
        location_base = f"{self._config.params.location}/{current_week}"
        df_feedback = None
        for file in df_feedback_files.select("filename").distinct().collect():
            filename = file.filename
            self._config.params.location = f"{location_base}/{filename}"
            try:
                df_new_feedback = super().transform(ctx)
                df_new_feedback = df_new_feedback.withColumn("file_name", f.lit(filename))
                if df_feedback:
                    df_feedback = df_feedback.unionByName(df_new_feedback, allowMissingColumns=True)
                else:
                    df_feedback = df_new_feedback
            except AnalysisException as ex:
                if ex.getErrorClass().lower().strip() == "path_not_found":
                    print(f"Feedback not found for week {current_week}.")
                    return df_feedback_previous.limit(0)
                else:
                    raise ex
        if df_feedback:
            df_feedback = df_feedback.withColumn("check", f.lit(check_name))
            df_feedback = df_feedback.filter(~f.col(df_feedback.columns[0]).startswith("Applied filters"))
            df_feedback = self._combine_feedbacks(df_feedback_previous, df_feedback)
        else:
            df_feedback = df_feedback_previous.limit(0)
        return df_feedback
