from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf, trim, split, sequence, expr, explode, size, array_distinct
from pyspark.sql.types import StringType, StructType, StructField, IntegerType, FloatType, ArrayType, DoubleType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
from pyspark.ml.feature import StringIndexer

import json
import re

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext


from governance_data_quality_processes.custom_operation_configs.product_mapping_tool.ngram_tokenization_config import (
    NgramTokenizationOperationConfig,
)

class NgramTokenizationOperation(BaseOperation):
    """
    Generic n-gram / word tokenization operation.
    Can be used for SAP or EP data by specifying:
    - input context name
    - output context name
    - column to tokenize
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> None:
        from pyspark.sql.functions import (
            col, lit, lower, trim, regexp_replace, split,
            sequence, expr, explode, length
        )
        from pyspark import StorageLevel

        df = ctx[self._config.context_name]

        cfg = self._config.params
        column_map = cfg.column_map

        text_col = cfg.column_to_tokenize
        ngram_sizes = cfg.ngram_sizes

        brand_col = column_map["brand_name"]
        sub_brand_col = column_map["sub_brand_name"]
        country_col = column_map["country_code"]
        flavour_col = column_map.get("flavour_name")

        # ============================================================
        # Cleaning lambdas 
        # ============================================================
        clean_words = lambda c: trim(regexp_replace(
            regexp_replace(
                regexp_replace(lower(col(c)), r"\b(\d+\s*(ml|cl|l|g|kg)|x\s*\d+|\d+\s*x\s*\d+)\b", ""),
                r"[^a-zA-Z0-9 ]",
                " "
            ), '\\s+', ' ')
        )

        clean_chars = lambda c: regexp_replace(
            regexp_replace(lower(col(c)), r"\b(\d+\s*(ml|cl|l|g|kg)|x\s*\d+|\d+\s*x\s*\d+)\b", ""),
            r"[^a-zA-Z0-9]",
            ""
        )

        # ============================================================
        # Input
        # ============================================================

        base_cols = [brand_col, sub_brand_col, country_col]

        if flavour_col and text_col == flavour_col:
            base_cols.append(flavour_col)

        token_dfs = []

        for n in ngram_sizes:
            if n < 999:
                token_df = (
                    df
                    .withColumn("clean", clean_chars(text_col))
                    .withColumn(
                        "tokens_array",
                        expr(
                            f"""
                            CASE
                                WHEN length(clean) >= {n}
                                THEN transform(
                                    sequence(1, length(clean) - {n} + 1),
                                    i -> substring(clean, i, {n})
                                )
                                ELSE array()
                            END
                            """
                        )
                    )
                    .withColumn("tokens_num", size("tokens_array"))
                    .withColumn("token", explode("tokens_array"))
                    .drop("tokens_array")
                    .withColumn("n", lit(n))
                )

            else:
                token_df = (
                    df
                    .withColumn("clean", clean_words(text_col))
                    .withColumn("tokens_array", split(col("clean"), " "))
                    .withColumn("tokens_num", size("tokens_array"))
                    .withColumn("token", explode("tokens_array"))
                    .drop("tokens_array")
                    .withColumn("n", lit(n))
                )

            token_dfs.append(token_df.drop("_clean"))

        tokens = token_dfs[0]
        for df_next in token_dfs[1:]:
            tokens = tokens.unionByName(df_next)

        return tokens
