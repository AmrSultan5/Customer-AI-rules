from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf
from pyspark.sql.types import StringType, DoubleType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
from pyspark.ml.feature import RegexTokenizer
from textdistance import jaccard

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.product_mapping_ered.brand_similarity_config import (
    BrandSimilarityOperationConfig,
)

class BrandSimilarityOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, BrandSimilarityOperationConfig)
        df = ctx[self._config.context_name]
        brand_1 = self._config.params.input_brand_1
        brand_2 = self._config.params.input_brand_2

        tokenizer_brand_1 = RegexTokenizer(inputCol=brand_1, outputCol="brand_1_tokenized", pattern="\\W")
        tokenizer_brand_2 = RegexTokenizer(inputCol=brand_2, outputCol="brand_2_tokenized", pattern="\\W")
        df = df.fillna({brand_1: ""})
        df = df.fillna({brand_2: ""})
        df = tokenizer_brand_1.transform(df)
        df = tokenizer_brand_2.transform(df)

        def jaccard_similarity_score(brand1: str, brand2: str):
            if brand1 is None or brand2 is None:
                return None  # or return -1 if you prefer a numeric fallback
            return float(jaccard.normalized_similarity(brand1.split(), brand2.split()))
        
        jaccard_similarity_udf = udf(jaccard_similarity_score, StringType())

        # def brand_similarity_score(brand1: str, brand2: str) -> str:    
        #     try:
        #         return when(col("brand_1_tokenized").getItem(0) == col("brand_2_tokenized").getItem(0), jaccard_similarity_udf(col("brand_1"), col("brand_2"))).otherwise('0')
        #     except Exception:
        #         return brand1
        
        # brand_similarity_score_udf = udf(brand_similarity_score, StringType())

        similarity_expr = when(col("brand_1_tokenized").getItem(0) == col("brand_2_tokenized").getItem(0), jaccard_similarity_udf(lower(col(brand_1)), lower(col(brand_2)))).otherwise(0.0)

        return df.withColumn("brand_similarity_score", similarity_expr)
