from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf
from pyspark.sql.types import StringType, DoubleType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
from pyspark.ml.feature import RegexTokenizer
from textdistance import jaccard
from fuzzywuzzy import fuzz

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.product_mapping_ered.matching_score_fuzzy_config import (
    MatchingScoreFuzzyOperationConfig,
)

class MatchingScoreFuzzyOperation(BaseOperation):
    """Computes a symmetric fuzzy word-level similarity score between two product description columns, averaging the best per-word matches in both directions."""

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, MatchingScoreFuzzyOperationConfig)
        df = ctx[self._config.context_name]
        desc_1 = self._config.params.input_desc_1
        desc_2 = self._config.params.input_desc_2

        def fuzzy_match_strings(str1, str2):
            if not str1 or not str2:
                return 0.0
            
            # Tokenize the strings into words (using space as delimiter)
            words1 = str1.lower().split()
            words2 = str2.lower().split()

            # We'll store the total similarity score here
            total_similarity = 0
            count = 0

            # For each word in the first string, compare it to the most similar word in the second string
            for word1 in words1:
                best_similarity = 0
                for word2 in words2:
                    similarity = fuzz.ratio(word1, word2)  # Get fuzzy similarity for each word pair
                    best_similarity = max(best_similarity, similarity)  # Keep the best match
                total_similarity += best_similarity
                count += 1

            # Calculate the average similarity of the words
            average_similarity = (total_similarity / count if count > 0 else 0) / 100
            
            return average_similarity
        
        def fuzzy_match_strings_symmetric(str1, str2):
            return round(max([fuzzy_match_strings(str1, str2), fuzzy_match_strings(str2, str1)]), 6)
        
        fuzzy_match_strings_symmetric_udf = udf(fuzzy_match_strings_symmetric, DoubleType())

        return df.withColumn("fuzzy_match_score", fuzzy_match_strings_symmetric_udf(col(desc_1), col(desc_2)))
