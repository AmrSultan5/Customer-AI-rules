from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf, max as max_spark, first, length, row_number, expr, size, aggregate
from pyspark.sql.types import StringType, DoubleType
from pyspark.sql.window import Window
from typing import Optional
from pyspark.sql.dataframe import DataFrame
from pyspark.ml.feature import RegexTokenizer, HashingTF, MinHashLSH

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext


from governance_data_quality_processes.custom_operation_configs.product_mapping_tool.minhash_lsh_similarity_config import (
    MinHashLSHSimilarityOperationConfig,
)


class MinHashLSHSimilarityOperation(BaseOperation):

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, MinHashLSHSimilarityOperationConfig)

        left_df = ctx[self._config.context_name]
        right_df = ctx[self._config.params.context_right]

        left_col = self._config.params.left_text_col
        right_col = self._config.params.right_text_col
        threshold = self._config.params.jaccard_threshold
        prefix = self._config.params.output_prefix

        left_df = left_df.fillna({left_col: ""})
        left_df = left_df.withColumn("text_safe", regexp_replace(left_col, "(\d+)\.(\d+)", '$1_$2'))

        right_df = right_df.fillna({right_col: ""})
        right_df = right_df.withColumn("text_safe", regexp_replace(right_col, "(\d+)\.(\d+)", '$1_$2'))

        tokenizer = RegexTokenizer(pattern="\\W+", toLowercase=True)

        left_tok = tokenizer.setInputCol("text_safe").setOutputCol("tokens").transform(left_df)
        right_tok = tokenizer.setInputCol("text_safe").setOutputCol("tokens").transform(right_df)

        left_tok = left_tok.withColumn("tokens", expr("transform(tokens, x -> regexp_replace(x, '_', '.'))"))
        right_tok = right_tok.withColumn("tokens", expr("transform(tokens, x -> regexp_replace(x, '_', '.'))"))

        # Filter out rows with empty tokens before hashing
        right_tok = right_tok.filter(size(col("tokens")) > 0)
        left_tok = left_tok.filter(size(col("tokens")) > 0)

        hashing_tf = HashingTF(inputCol="tokens", outputCol="features", numFeatures=1 << 18)

        left_fe = hashing_tf.transform(left_tok)
        right_fe = hashing_tf.transform(right_tok)

        # MinHashLSH
        lsh = MinHashLSH(inputCol="features", outputCol="hashes", numHashTables=5)

        lsh_model = lsh.fit(right_fe)
        
        # similarity join 
        distance_threshold = 1.0 - threshold

        pairs = lsh_model.approxSimilarityJoin(datasetA=left_fe, datasetB=right_fe, threshold=distance_threshold, distCol="jaccard_distance" )

        # Similarity + aggregation
        scored = pairs.select(col(f"datasetA.{left_col}").alias(left_col), col(f"datasetB.{right_col}").alias(right_col), (1.0 - col("jaccard_distance")).alias("jaccard")) \
                      .withColumn("brand_length", length(col(right_col)))

        window = Window.partitionBy(left_col).orderBy(col("jaccard").desc(), col("brand_length").desc())

        ranked = scored.withColumn("rn", row_number().over(window))

        best_match = ranked.filter(col("rn") == 1).select(left_col, col("jaccard").alias(f"{prefix}_max_jaccard"), col(right_col).alias(f"{prefix}_matched_value")) \
                           .withColumn(f"{prefix}_has_match", lit(True))

        return left_df.join(best_match, on=left_col, how="left").fillna({f"{prefix}_has_match": False})
