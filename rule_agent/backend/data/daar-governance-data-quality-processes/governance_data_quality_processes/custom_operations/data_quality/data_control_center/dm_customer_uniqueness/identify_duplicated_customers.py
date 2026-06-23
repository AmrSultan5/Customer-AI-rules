"""Customer Duplicate Matching Module.

This module provides functionality for identifying potential duplicate customer records
in the Data Control Center by comparing customer attributes using Levenshtein similarity.
The matching process considers multiple dimensions including legal entity,
address, city, and name, with country-specific matching rules.

The module implements a weighted similarity scoring approach using normalized
Levenshtein distance to measure string similarities between customer records.
"""

import operator
from functools import reduce

from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operations.base import BaseOperation
from pyspark.sql import DataFrame, Column, Window
from pyspark.sql import functions as f


class IdentifyDuplicatedCustomersOperation(BaseOperation):
    """Operation for identifying and matching potential duplicate customer records.

    This operation performs customer duplicate detection by:
    1. Preprocessing customer data to normalize legal entity information
    2. Performing self-joins to identify potential duplicates based on country-specific rules
    3. Calculating similarity scores for multiple attributes (name, address, city, legal entity)
    4. Applying weighted scoring and thresholds to filter high-confidence duplicates

    The matching logic handles special cases for specific countries:
    - Nigeria (NG): Uses city-based matching (no tax information)
    - Ireland (IE): Relaxed matching rules (no tax information)
    - Other countries: Uses legal entity (tax) based matching

    """

    @staticmethod
    def _create_column_names_with_prefix(columns: list, prefix: str) -> list:
        """Create a list of column expressions with a specified prefix.

        This method is used to prepare separate column sets for the original and duplicate
        sides of the self-join operation, preventing column name conflicts.

        Args:
            columns: List of column names to prefix
            prefix: String prefix to add to each column name (e.g., 'original', 'duplicate')

        Returns:
            List of Column expressions with aliased names in format '{prefix}_{column}'

        Example:
            >>> selected_columns = ['id', 'legal_name', 'city_with_postal_code']
            >>> result = self._create_column_names_with_prefix(selected_columns, 'original')
            >>> # Returns: [col('id').alias('original_id'), col('legal_name').alias('original_legal_name'), ...]
        """
        return [f.col(column).alias(f"{prefix}_{column}") for column in columns]

    @staticmethod
    def _prepare_table_for_matching(df_customers: DataFrame) -> DataFrame:
        """Prepare customer data for duplicate matching by normalizing legal entity information.

        This method handles the different approaches to legal entity data across countries:
        - For NG and IE: Sets legal_entity to None (these countries don't use tax-based matching)
        - For other countries: Unpivots tax fields (tax, tax1, tax2) into rows, creating one
          row per valid legal entity value

        The unpivoting process transforms the wide format (multiple tax columns) into a long
        format where each customer-legal entity combination becomes a separate row, enabling
        more flexible matching logic and faster join performance.

        Args:
            df_customers: Input DataFrame containing customer records.
        Returns:
            DataFrame with normalized legal entity structure containing.

        Notes:
            - Filters out null legal entities for non-NG/IE countries (to reduce cross-join size)
            - Countries without tax-based matching (NG, IE) get single rows with null legal entity (to keep it
                consistent with other countries)
            - Other countries may have multiple rows per customer if they have multiple tax IDs
        """
        df_original_countries_with_invalid_tax = (
            df_customers.filter(f.col("country_code").isin("NG", "IE"))
            .withColumns({"legal_entity": f.lit(None), "legal_entity_source": f.lit("tax")})
            .drop("tax", "tax1", "tax2")
        )
        id_columns = list(set(df_customers.columns).difference({"tax", "tax1", "tax2"}))
        df_original_countries_with_valid_tax = (
            df_customers.filter(~f.col("country_code").isin("NG", "IE"))
            .melt(
                ids=id_columns,
                values=["tax", "tax1", "tax2"],
                variableColumnName="legal_entity_source",
                valueColumnName="legal_entity",
            )
            .filter(f.col("legal_entity").isNotNull())
        )
        df_original_preprocessed = df_original_countries_with_invalid_tax.unionByName(
            df_original_countries_with_valid_tax
        )
        return df_original_preprocessed

    def _match_customers_with_potential_duplicates(self, df_customers: DataFrame) -> DataFrame:
        """
        Performs self-join to identify potential duplicate customer pairs.

        This method implements the core matching logic by joining the customer dataset with
        itself using country-specific rules. The join produces pairs of customers that might
        be duplicates based on initial criteria.

        Join conditions:
        1. Same trade channel and country (always required)
        2. original_id < duplicate_id (prevents duplicate pairs and self-matches)
        3. Country-specific matching rules:
           - NG: Match on same city
           - IE: Match all records (most lenient)
           - Other: Match on same legal entity

        Deduplication strategy:
        - When multiple legal entity combinations match between the same customer pair,
          keeps only the first match (ordered by original_legal_entity_source; tax, tax1, tax2)
        - Uses window function with row_number to ensure one row per customer pair

        Args:
            df_customers: Preprocessed customer DataFrame from _prepare_table_for_matching
                containing normalized legal entity structure

        Returns:
            DataFrame with matched customer pairs, containing columns prefixed with:
                - 'original_': Attributes of the first customer in the pair
                - 'duplicate_': Attributes of the second customer in the pair
            Each row represents one potential duplicate pair for further similarity analysis

        Notes:
            - Repartitions data by country and trade channel for performance
            - Window partitioning by (original_id__cmd, duplicate_id__cmd) handles cases where
              the same customer pair has multiple matching legal entities - only the first is kept
        """
        w = Window.partitionBy("original_customer_code", "duplicate_customer_code").orderBy(
            f.col("original_legal_entity_source").asc()
        )
        df_customers = df_customers.repartition(200, "country_code", "trade_channel_code").alias("original")

        df_original = df_customers.select(self._create_column_names_with_prefix(df_customers.columns, "original"))
        df_duplicate = df_customers.select(self._create_column_names_with_prefix(df_customers.columns, "duplicate"))
        join_condition = (
            (f.col("original_trade_channel_code") == f.col("duplicate_trade_channel_code"))
            & (f.col("original_country_code") == f.col("duplicate_country_code"))
            & (f.col("original_customer_code") < f.col("duplicate_customer_code"))
            & (
                ((f.col("original_country_code") == "NG") & (f.col("original_city") == f.col("duplicate_city")))
                | (f.col("original_country_code") == "IE")
                | (
                    ~f.col("original_country_code").isin("NG", "IE")
                    & (f.col("original_legal_entity") == f.col("duplicate_legal_entity"))
                )
            )
        )
        df_joined = (
            df_original.join(df_duplicate, on=join_condition, how="inner")
            .withColumn("rank", f.row_number().over(w))
            .filter(f.col("rank") == 1)
            .drop("rank")
        )
        return df_joined

    @property
    def _excluded_legal_entities(self) -> list:
        """List of legal entity values considered invalid or placeholder.

        These values are commonly used as placeholders, test data, or represent
        invalid/dummy tax identification numbers that should not be used for matching.

        Returns:
            List of string values to exclude from legal entity matching

        Notes:
            Legal entities matching these values will be flagged as invalid and may be
            replaced with alternative matching attributes (name, address, postal code).
        """
        return [
            "00000000A",
            "ATU99999999",
        ]

    @property
    def _is_invalid_legal_entity_expression(self) -> Column:
        """
        Spark Column expression for identifying invalid legal entity values.

        Detects legal entities that should not be used for matching based on multiple criteria.
        Invalid legal entities may be replaced with alternative identifiers (name, address, etc.)
        to improve matching accuracy.

        Validation rules:
        1. Too short: Length <= 3 characters
        2. Country without tax: Assigned to NG or IE (countries that don't use tax matching)
        3. Excluded values: Matches known invalid/placeholder values (see _excluded_legal_entities)
        4. Repeated characters: Contains only the same character repeated (e.g., '111111', 'AAA')

        Returns:
            Spark Column expression (boolean) that evaluates to True when the
            'original_legal_entity' value is considered invalid

        """
        is_too_short = f.length(f.col("original_legal_entity")) <= 3
        is_assigned_to_country_without_tax = f.col("original_country_code").isin("NG", "IE")
        is_excluded = f.col("original_legal_entity").isin(self._excluded_legal_entities)
        is_the_same_character_repeated = f.col("original_legal_entity").rlike(r"^(.)\1*$")
        return is_too_short | is_assigned_to_country_without_tax | is_excluded | is_the_same_character_repeated

    def _adjust_legal_entity_column(self, df_duplicates: DataFrame) -> DataFrame:
        """
        Replace invalid legal entities with alternative identifying attributes.

        When a legal entity is deemed invalid, this method substitutes it with a more
        reliable identifier based on similarity scores. This improves matching accuracy
        when tax/legal entity information is unreliable.

        Replacement logic (evaluated in order):
        1. If name_similarity_score >= 0.9: Use customer name as identifier
        2. If address_similarity_score >= 0.9: Use street name as identifier
        3. Otherwise: Use postal code as identifier

        This ensures that when legal entities are unreliable, the matching process falls
        back to the most similar available attribute between the customer pair.

        Args:
            df_duplicates: DataFrame of potential duplicate pairs with similarity scores.

        Returns:
            DataFrame with adjusted original_legal_entity column, where invalid values
            have been replaced with alternative identifiers

        Notes:
            - Temporary 'is_invalid_legal_entity' column is created and then dropped
            - Only affects records where _is_invalid_legal_entity_expression evaluates to True
            - Valid legal entities remain unchanged
        """
        df_duplicates_with_legal_entity = (
            df_duplicates.withColumn("is_invalid_legal_entity", self._is_invalid_legal_entity_expression)
            .withColumn(
                "original_legal_entity",
                f.when(
                    f.col("is_invalid_legal_entity") & (f.col("legal_name_similarity_score") >= 0.9),
                    f.col("original_legal_name"),
                )
                .when(
                    f.col("is_invalid_legal_entity") & (f.col("address_similarity_score") >= 0.9),
                    f.col("original_street_1_name"),
                )
                .when(f.col("is_invalid_legal_entity"), f.col("original_post_code"))
                .otherwise(f.col("original_legal_entity")),
            )
            .drop("is_invalid_legal_entity")
        )
        return df_duplicates_with_legal_entity

    @staticmethod
    def _calculate_normalized_levenshtein_similarity_expression(original_column: str, duplicate_column: str) -> Column:
        """
        Calculate normalized Levenshtein similarity score between two string columns.

        Computes a similarity score (0-1) using the Levenshtein distance algorithm,
        normalized by the length of the longer string. This provides a measure of how
        similar two strings are, with 1.0 meaning identical and 0.0 meaning completely different.

        Algorithm:
        1. Calculate Levenshtein distance (number of single-character edits needed)
        2. Normalize by dividing by the length of the longer string
        3. Subtract from 1 to convert distance to similarity (1 - normalized_distance)
        4. Return 0 if calculation fails (e.g., both strings are null)

        Args:
            original_column: Name of the column containing the first string to compare
            duplicate_column: Name of the column containing the second string to compare

        Returns:
            Spark Column expression (float) representing similarity score between 0 and 1.

        Notes:
            - Case-sensitive comparison
            - Uses coalesce to handle null values gracefully
        """
        levenshtein_score = f.levenshtein(f.col(original_column), f.col(duplicate_column))
        normalization = f.greatest(f.length(f.col(original_column)), f.length(f.col(duplicate_column)))
        similarity_score = f.coalesce(1 - levenshtein_score / normalization, f.lit(0))
        return similarity_score

    @staticmethod
    def _weighted_similarity_score_expression(*columns: str) -> Column:
        """Calculate weighted average similarity score across multiple attributes.

        Combines individual attribute similarity scores using predefined weights to produce
        an overall similarity measure. Each attribute contributes proportionally to the
        final score based on its weight.

        Formula:
            w_sim_score = Σ(similarity_score_i × weight_i) for each attribute i

        The method expects the DataFrame to contain:
        - {column}_similarity_score: Individual similarity score (0-1) for each column
        - {column}_similarity_weight: Weight factor (0-1) for each column

        Args:
            *columns: Variable number of column base names (without suffixes)
                     e.g., 'address', 'city_with_postal_code', 'legal_name', 'legal_entity'

        Returns:
            Spark Column expression (float) representing the weighted sum of similarity scores

        Example:
            >>> # Given columns with scores and weights:
            >>> # name_similarity_score = 0.9, name_similarity_weight = 0.4
            >>> # address_similarity_score = 0.8, address_similarity_weight = 0.4
            >>> # city_similarity_score = 0.7, city_similarity_weight = 0.2
            >>> result = self._weighted_similarity_score_expression('legal_name', 'address', 'city_with_postal_code')
            >>> # Returns: (0.9 × 0.4) + (0.8 × 0.4) + (0.7 × 0.2) = 0.82
        """
        terms = [f.col(f"{column}_similarity_score") * f.col(f"{column}_similarity_weight") for column in columns]
        return reduce(operator.add, terms)

    @property
    def _customer_base_in_scope_columns(self) -> list:
        return [
            "customer_code",
            "country_code",
            "trade_channel_code",
            "legal_name",
            "street_1_name",
            "city",
            "city_with_postal_code",
            "post_code",
            "address",
            "tax",
            "tax1",
            "tax2",
        ]

    def transform(self, ctx: TransformationContext) -> DataFrame:
        """
        Execute the complete duplicate customer matching transformation.

        This is the main entry point that orchestrates the entire duplicate detection process
        by combining preprocessing, matching, similarity calculation, filtering, and adjustment
        steps into a comprehensive pipeline.

        Pipeline stages:
        1. Preprocess: Normalize legal entity data for country-specific matching
        2. Match: Perform self-join to identify potential duplicate pairs
        3. Score: Calculate similarity scores for name, address, city, and legal entity
        4. Weight: Apply country-specific weights to similarity scores
        5. Filter: Apply thresholds to ensure high-quality matches
        6. Adjust: Replace invalid legal entities with alternative identifiers

        Args:
            ctx: TransformationContext containing:
                - df_customer_base: Input DataFrame with customer records

        Returns:
            DataFrame containing confirmed duplicate pairs with similarity scores and adjusted legal entities.

        Note:
            In the original POC implementation, there was a huge overhead caused by unnecessary calculations; we do
            not need to calculate similarity scores for taxes as those will be for sure equal to 100% as it is forced
            by the join condition.
        """
        df_customer_base = ctx["df_customer_base"].select(self._customer_base_in_scope_columns)
        df_preprocessed = df_customer_base.transform(self._prepare_table_for_matching)
        df_potential_duplicates = df_preprocessed.transform(self._match_customers_with_potential_duplicates)
        df_duplicates = (
            df_potential_duplicates.withColumns(
                {
                    "address_similarity_score": self._calculate_normalized_levenshtein_similarity_expression(
                        "original_address", "duplicate_address"
                    ),
                    "city_similarity_score": f.when(
                        (f.col("original_post_code") == "") | (f.col("duplicate_post_code") == ""),
                        self._calculate_normalized_levenshtein_similarity_expression("original_city", "duplicate_city"),
                    ).otherwise(
                        self._calculate_normalized_levenshtein_similarity_expression(
                            "original_city_with_postal_code", "duplicate_city_with_postal_code"
                        )
                    ),
                    "legal_name_similarity_score": self._calculate_normalized_levenshtein_similarity_expression(
                        "original_legal_name", "duplicate_legal_name"
                    ),
                    "legal_entity_similarity_score": f.lit(1.0),
                    "address_similarity_weight": f.lit(0.4),
                    "city_similarity_weight": f.lit(0.2),
                    "legal_name_similarity_weight": f.when(
                        f.col("original_country_code").isin(["CH", "IE", "NG"]),
                        f.lit(0.4),
                    ).otherwise(f.lit(0.2)),
                    "legal_entity_similarity_weight": f.when(
                        f.col("original_country_code").isin(["CH", "IE", "NG"]),
                        f.lit(0.0),
                    ).otherwise(f.lit(0.2)),
                    "address_similarity_threshold": f.lit(0.8),
                    "city_similarity_threshold": f.lit(0.6),
                    "legal_name_similarity_threshold": f.lit(0.6),
                    "legal_entity_similarity_threshold": f.when(
                        f.col("original_country_code").isin(["CH", "IE", "NG"]),
                        f.lit(0.0),
                    ).otherwise(f.lit(0.99)),
                }
            )
            .withColumn(
                "w_sim_score",
                self._weighted_similarity_score_expression("address", "city", "legal_name", "legal_entity"),
            )
            .filter(f.col("w_sim_score").isNotNull())
            .filter(f.col("address_similarity_score") >= f.col("address_similarity_threshold"))
            .filter(f.col("city_similarity_score") >= f.col("city_similarity_threshold"))
            .filter(f.col("legal_name_similarity_score") >= f.col("legal_name_similarity_threshold"))
            .filter(f.col("legal_entity_similarity_score") >= f.col("legal_entity_similarity_threshold"))
            .transform(self._adjust_legal_entity_column)
        )
        return df_duplicates
