"""Address fuzzy matching operations using rapidfuzz."""

from typing import List, Optional
from pyspark.sql import DataFrame, functions as F, types as T
from rapidfuzz import fuzz

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from .fuzzy_matching_constants import (
    MatchResult,
    MIN_SIMILARITY_THRESHOLD,
    HIGH_SIMILARITY_THRESHOLD,
)


class AddressFuzzyMatchingOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        """Main transformation pipeline."""
        df = ctx[self._config.context_name]
        df = self.apply_matching(df)
        df_valid = self.filter_valid_matches(df)
        df_street_level = self.filter_street_matches(df_valid)
        df_with_flags = self.add_match_quality_flags(df_street_level)
        return df_with_flags

    @staticmethod
    def _is_blank(s: Optional[str]) -> bool:
        """Return True if the string is None or empty after trimming."""
        return s is None or str(s).strip() == ""

    @staticmethod
    def _normalize_string_list(xs: Optional[List]) -> List[str]:
        """
        Normalize a list of strings: upper-case, strip, remove empty.

        Args:
            xs: List of strings (potentially with None values)

        Returns:
            List of normalized non-empty strings
        """
        if xs is None:
            return []

        try:
            normalized = []
            for value in xs:
                if value is None:
                    continue
                cleaned = str(value).strip().upper()
                if cleaned:
                    normalized.append(cleaned)
            return normalized
        except Exception:
            return []

    @staticmethod
    def calculate_similarity(text_a: str, text_b: str) -> float:
        """
        Compute similarity score using rapidfuzz.

        Strategy:
        1. If one string contains the other (case-insensitive), return 100
        2. Otherwise, return max of token_set_ratio and WRatio

        Args:
            text_a: First text string
            text_b: Second text string

        Returns:
            Similarity score between 0 and 100
        """
        text_a_upper = text_a.upper()
        text_b_upper = text_b.upper()

        # Strong containment boost
        if text_a_upper in text_b_upper or text_b_upper in text_a_upper:
            return 100.0

        # Two complementary measures
        token_set_score = fuzz.token_set_ratio(text_a_upper, text_b_upper)
        wratio_score = fuzz.WRatio(text_a_upper, text_b_upper)

        return float(max(token_set_score, wratio_score))

    @staticmethod
    def _classify_match_static(
        customer_street: str,
        external_street: str,
        customer_numbers: Optional[List],
        external_numbers: Optional[List],
        min_threshold: float,
        high_threshold: float,
    ) -> str:
        """
        Static classification method for use in UDF.

        Args:
            customer_street: Normalized customer street name
            external_street: Normalized external database street name
            customer_numbers: List of house numbers from customer address
            external_numbers: List of house numbers from external database
            min_threshold: Minimum similarity score to consider a match
            high_threshold: High similarity threshold for detailed classification

        Returns:
            Classification result string
        """
        # 1. Check if external address is empty
        if AddressFuzzyMatchingOperation._is_blank(external_street):
            return MatchResult.NO_INFO_EXTERNAL

        # 2. Check if customer address is empty
        if AddressFuzzyMatchingOperation._is_blank(customer_street):
            return MatchResult.NO_MATCH

        # 3. Calculate similarity score
        similarity_score = AddressFuzzyMatchingOperation.calculate_similarity(
            customer_street, external_street
        )

        # 4. Below minimum threshold => no match
        if similarity_score < min_threshold:
            return MatchResult.NO_MATCH

        # 5. High similarity => evaluate house numbers
        if similarity_score >= high_threshold:
            return AddressFuzzyMatchingOperation._classify_with_house_numbers(
                customer_numbers, external_numbers
            )

        # 6. Between thresholds => conservative no match
        return MatchResult.NO_MATCH

    @staticmethod
    def _classify_with_house_numbers(
        customer_numbers: Optional[List], external_numbers: Optional[List]
    ) -> str:
        """
        Classify match when street similarity is high, based on house numbers.

        Args:
            customer_numbers: List of house numbers from customer
            external_numbers: List of house numbers from external database

        Returns:
            Detailed classification based on house number presence/match
        """
        cust_nums = AddressFuzzyMatchingOperation._normalize_string_list(
            customer_numbers
        )
        ext_nums = AddressFuzzyMatchingOperation._normalize_string_list(
            external_numbers
        )

        has_customer_numbers = len(cust_nums) > 0
        has_external_numbers = len(ext_nums) > 0

        # Both missing numbers
        if not has_customer_numbers and not has_external_numbers:
            return MatchResult.VALID_STREET_MISSING_BOTH_NUMBERS

        # Only customer has numbers
        if has_customer_numbers and not has_external_numbers:
            return MatchResult.VALID_STREET_MISSING_EXT_NUMBER

        # Only external has numbers
        if not has_customer_numbers and has_external_numbers:
            return MatchResult.VALID_STREET_MISSING_CUST_NUMBER

        # Both have numbers => check for intersection
        customer_set = set(cust_nums)
        external_set = set(ext_nums)

        if customer_set.intersection(external_set):
            return MatchResult.VALID_ADDRESS
        else:
            return MatchResult.VALID_STREET_DIFFERENT_NUMBER

    def apply_matching(self, df: DataFrame) -> DataFrame:
        """
        Apply fuzzy matching classification to addresses.

        Expected input columns:
        - n_add: Normalized customer address (street only)
        - ext_n_add: Normalized external address (street only)
        - cust_numbers: Array of customer house numbers
        - ext_numbers: Array of external house numbers

        Adds column:
        - address_match_result: Classification result

        Args:
            df: DataFrame with normalized addresses

        Returns:
            DataFrame with match classification column added
        """
        classify_udf = F.udf(self._classify_match_static, T.StringType())

        return df.withColumn(
            "address_match_result",
            classify_udf(
                F.col("n_add"),
                F.col("ext_n_add"),
                F.col("cust_numbers"),
                F.col("ext_numbers"),
                F.lit(MIN_SIMILARITY_THRESHOLD),
                F.lit(HIGH_SIMILARITY_THRESHOLD),
            ),
        )

    def filter_valid_matches(self, df: DataFrame) -> DataFrame:
        """
        Filter to only valid address matches.

        Args:
            df: DataFrame with address_match_result column

        Returns:
            DataFrame filtered to valid matches only
        """
        return df.filter(F.col("address_match_result") == MatchResult.VALID_ADDRESS)

    def filter_street_matches(self, df: DataFrame) -> DataFrame:
        """
        Filter to street-level matches (including valid addresses).

        Args:
            df: DataFrame with address_match_result column

        Returns:
            DataFrame filtered to street-level matches
        """
        return df.filter(
            F.col("address_match_result").isin(
                [
                    MatchResult.VALID_ADDRESS,
                    MatchResult.VALID_STREET_MISSING_EXT_NUMBER,
                    MatchResult.VALID_STREET_MISSING_BOTH_NUMBERS,
                    MatchResult.VALID_STREET_MISSING_CUST_NUMBER,
                    MatchResult.VALID_STREET_DIFFERENT_NUMBER,
                ]
            )
        )

    def add_match_quality_flags(self, df: DataFrame) -> DataFrame:
        """
        Add boolean flags for different match quality levels.

        Adds columns:
        - is_exact_match: Valid address with matching house numbers
        - is_street_match: Valid street but house number issues
        - is_no_match: No match found

        Args:
            df: DataFrame with address_match_result column

        Returns:
            DataFrame with match quality flag columns
        """
        return (
            df.withColumn(
                "is_exact_match",
                F.col("address_match_result") == MatchResult.VALID_ADDRESS,
            )
            .withColumn(
                "is_street_match",
                F.col("address_match_result").isin(
                    MatchResult.VALID_STREET_MISSING_EXT_NUMBER,
                    MatchResult.VALID_STREET_MISSING_BOTH_NUMBERS,
                    MatchResult.VALID_STREET_MISSING_CUST_NUMBER,
                    MatchResult.VALID_STREET_DIFFERENT_NUMBER,
                ),
            )
            .withColumn(
                "is_no_match",
                F.col("address_match_result").isin(
                    MatchResult.NO_MATCH, MatchResult.NO_INFO_EXTERNAL
                ),
            )
        )

    def get_match_statistics(self, df: DataFrame) -> DataFrame:
        """
        Generate match statistics summary.

        Args:
            df: DataFrame with address_match_result column

        Returns:
            DataFrame with counts and percentages by match result
        """
        total_count = df.count()
        stats_df = df.groupBy("address_match_result").count()

        return stats_df.withColumn(
            "percentage", F.round((F.col("count") / total_count) * 100, 2)
        ).orderBy(F.col("count").desc())
