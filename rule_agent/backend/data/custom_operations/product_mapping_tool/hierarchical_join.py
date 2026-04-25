from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf, max as max_spark, first, length, row_number, expr, rank, dense_rank
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from typing import Optional
from pyspark.sql.dataframe import DataFrame
from functools import reduce

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext


from governance_data_quality_processes.custom_operation_configs.product_mapping_tool.hierarchical_join_config import (
    HierarchicalJoinOperationConfig,
)


class HierarchicalJoinOperation(BaseOperation):

    """
    Hierarchical JOIN with adjustable hierarchy.
    """

    @staticmethod
    def _as_list(x):
        return x if isinstance(x, list) else [x]

    @staticmethod
    def _validate_same_length(a, b):
        if len(a) != len(b):
            raise ValueError(
                "join_col and other_join_col must have the same length"
            )

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, HierarchicalJoinOperationConfig)

        left_df = ctx[self._config.context_name]
        right_df = ctx[self._config.params.other]

        left_join_col = self._as_list(self._config.params.join_cols)
        right_join_col = self._as_list(self._config.params.other_join_cols)        
        self._validate_same_length(left_join_col, right_join_col)

        hierarchy_cols = self._config.params.join_hierarchy_list
        id_col = self._config.params.id_col
        how = self._config.params.how

        left = left_df.alias("left")
        right = right_df.alias("right")

        main_join_cond = reduce(lambda a, b: a & b, [col(f"left.{e}") == col(f"right.{s}") for e, s in zip(left_join_col, right_join_col)])

        # 1join only on main_join_cond
        joined = left.join(right, main_join_cond, how=how)

        # create match_level column
        when_expr = None

        for level, cols in enumerate(hierarchy_cols, start=1):
            if cols:
                cond = reduce(lambda a, b: a & b, [col(f"left.{c}") == col(f"right.{c}") for c in cols])
            else:
                cond = reduce(lambda a, b: a & b, [col(f"left.{e}") == col(f"right.{s}") for e, s in zip(left_join_col, right_join_col)])

            if when_expr is None:
                when_expr = when(cond, lit(level))
            else:
                when_expr = when_expr.when(cond, lit(level))

        joined = joined.withColumn("match_level", when_expr.otherwise(lit(None)))

        # best match selection per (id, token)
        w = Window.partitionBy(col(f"left.{id_col}"), *[col(f"left.{c}") for c in left_join_col]).orderBy("match_level")

        result = joined.withColumn("rn", rank().over(w)).filter(col("rn") == 1).drop("rn")

        left_cols = left_df.columns
        right_cols = [c for c in right_df.columns if c not in left_cols]

        final_cols = [col(f"left.{c}") for c in left_cols] + [col(f"right.{c}") for c in right_cols] + [col("match_level")]

        result = result.select(*final_cols)

        return result
