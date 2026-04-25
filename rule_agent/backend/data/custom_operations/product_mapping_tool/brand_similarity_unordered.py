from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf, expr
from pyspark.sql.types import StringType, DoubleType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
from pyspark.ml.feature import RegexTokenizer
from textdistance import jaccard

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext


from governance_data_quality_processes.custom_operation_configs.product_mapping_tool.brand_similarity_unordered_config import (
    BrandSimilarityUnorderedOperationConfig,
)


class BrandSimilarityUnorderedOperation(BaseOperation):
    """Computes an order-independent Jaccard set similarity score between two brand name columns tokenized by non-word characters."""

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, BrandSimilarityUnorderedOperationConfig)
        df = ctx[self._config.context_name]

        brand_1 = self._config.params.input_brand_1
        brand_2 = self._config.params.input_brand_2
        ouput_col_name = self._config.params.output_col_name

        df = df.fillna({brand_1: ""})
        df = df.fillna({brand_2: ""})
        df = df.withColumn("text_safe_1", regexp_replace(brand_1, "(\d+)\.(\d+)", '$1_$2'))
        df = df.withColumn("text_safe_2", regexp_replace(brand_2, "(\d+)\.(\d+)", '$1_$2'))

        tokenizer_brand_1 = RegexTokenizer(inputCol='text_safe_1', outputCol="brand_1_tokenized", pattern="\\W")
        tokenizer_brand_2 = RegexTokenizer(inputCol='text_safe_2', outputCol="brand_2_tokenized", pattern="\\W")

        df = tokenizer_brand_1.transform(df)
        df = tokenizer_brand_2.transform(df)

        df = df.withColumn("brand_1_tokenized", expr("transform(brand_1_tokenized, x -> regexp_replace(x, '_', '.'))"))
        df = df.withColumn("brand_2_tokenized", expr("transform(brand_2_tokenized, x -> regexp_replace(x, '_', '.'))"))

        # Jaccard calculated from token arrays → order-independent
        def jaccard_similarity(tokens1, tokens2):
            if tokens1 is None or tokens2 is None:
                return None

            set1 = set([t.lower() for t in tokens1 if t])
            set2 = set([t.lower() for t in tokens2 if t])

            if not set1 and not set2:
                return 0.0

            intersection = len(set1.intersection(set2))
            union = len(set1.union(set2))

            return float(intersection) / float(union)

        jaccard_similarity_udf = udf(jaccard_similarity, DoubleType())

        return df.withColumn(ouput_col_name, jaccard_similarity_udf(col("brand_1_tokenized"), col("brand_2_tokenized"))).drop('text_safe_1','text_safe_2')
    
