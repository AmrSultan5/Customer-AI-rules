# Databricks notebook source
from datetime import datetime
from typing import Optional
from itertools import chain
import pyspark.sql.functions as F
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from pyspark.sql.dataframe import DataFrame
from pyspark.sql.functions import *


class DCalendarOperation(BaseOperation):
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        targets = self.prepare_targets(ctx)
        return None

    def prepare_targets(self, ctx: TransformationContext):
        src_calendar_targets = ctx["src_calendar"]
        targets = (
            src_calendar_targets.withColumn("date_id", to_timestamp(col("date_id"), "yyyyMMdd").cast("string"))
            .withColumn("week_445", lpad("week_445", 2, "0"))
            .withColumn("month_445", lpad("month_445", 2, "0"))
            .select(
                col("date_id").alias("date"),
                col("month_445").alias("month"),
                col("week_445").cast("string").alias("week"),
                col("year_445").alias("year"),
                concat("year_445", "month_445").alias("year_month"),
                concat("year_445", "week_445").alias("year_week"),
                col("country").alias("openhub"),
                
            )
        )
        targets.show()
        ctx["src_calendar_target"] = targets
        return targets
