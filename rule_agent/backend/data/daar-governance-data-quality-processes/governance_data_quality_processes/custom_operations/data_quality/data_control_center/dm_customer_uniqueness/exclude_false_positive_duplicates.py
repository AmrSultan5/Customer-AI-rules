"""False Positive Duplicate Exclusion Module.

This module provides functionality for removing false positive duplicate records
from the customer uniqueness report. After excluding false-positive rows, it
re-evaluates each legal entity group and removes any group that no longer
contains more than one distinct customer — mirroring the POC's
``legal_entity_counts`` / ``legal_entity_filtered`` pattern.
"""

from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operations.base import BaseOperation
from pyspark.sql import DataFrame
from pyspark.sql import functions as f


class ExcludeFalsePositiveDuplicatesOperation(BaseOperation):
    """Operation for excluding false positive duplicates from the uniqueness report.

    This operation implements the following logic (aligned with the POC SQL):
    1. Identifies false-positive rows from feedback (rows where false_positive_flag > 0)
    2. Removes those rows from the report via a ``leftanti`` join on ``primary_key``
    3. Counts distinct ``customer_code`` per ``legal_entity`` group
    4. Keeps only groups that still have more than one distinct customer

    This ensures that:
    - Individual false-positive rows are removed precisely by primary_key
    - Legal entity groups that become singletons after removal are cleaned up
    """

    @staticmethod
    def _filter_legal_entities_with_multiple_customers(df: DataFrame) -> DataFrame:
        """Keep only rows whose legal_entity group still has >1 distinct customer.

        After false-positive rows are removed, some legal entity groups may be
        left with only a single customer.  These are no longer valid duplicate
        groups and must be excluded from the report.

        This mirrors the POC's ``legal_entity_counts`` / ``legal_entity_filtered``
        CTEs::

            legal_entity_counts AS (
              SELECT legal_entity, COUNT(DISTINCT customer_code) AS cnt
              FROM with_feedback_excluded
              GROUP BY legal_entity
            ),
            legal_entity_filtered AS (
              SELECT wfe.*
              FROM with_feedback_excluded wfe
              JOIN legal_entity_counts lec
                ON wfe.legal_entity = lec.legal_entity
              WHERE lec.cnt > 1
            )

        Args:
            df: Report DataFrame after false-positive rows have been removed.

        Returns:
            DataFrame containing only rows belonging to legal entity groups
            with more than one distinct customer.
        """
        df_legal_entity_counts = (
            df
            .groupBy("country_code", "legal_entity", "is_same_sub_trade_channel")
            .agg(f.countDistinct("customer_code").alias("distinct_customer_count"))
            .filter(f.col("distinct_customer_count") > 1)
            .select("country_code", "legal_entity", "is_same_sub_trade_channel")
        )

        return df.join(
            f.broadcast(df_legal_entity_counts),
            on=["country_code", "legal_entity", "is_same_sub_trade_channel"],
            how="inner",
        )

    def transform(self, ctx: TransformationContext) -> DataFrame:
        """Execute false positive exclusion and legal-entity re-evaluation.

        Pipeline:
        1. Extract false-positive ``primary_key`` values from feedback
        2. Anti-join the report on ``primary_key`` to remove false-positive rows
        3. Re-evaluate legal entity groups — drop any with ≤1 distinct customer

        Args:
            ctx: TransformationContext containing:
                - df_customer_uniqueness_report: The full uniqueness report
                - df_feedback: Feedback table with false_positive_flag

        Returns:
            DataFrame with false positives excluded and singleton legal entity
            groups removed.
        """
        df_report = ctx["df_customer_uniqueness_report"]
        df_feedback = ctx["df_feedback"]

        df_false_positive_pks = (
            df_feedback
            .filter(f.col("false_positive_flag") > 0)
            .select("primary_key")
            .distinct()
        )

        df_after_exclusion = df_report.join(
            f.broadcast(df_false_positive_pks),
            on="primary_key",
            how="leftanti",
        )

        df_result = self._filter_legal_entities_with_multiple_customers(df_after_exclusion)

        return df_result