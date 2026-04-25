"""Postal code validation, enrichment, and matching operations."""

import re
from typing import Optional
from pyspark.sql import DataFrame, functions as F, types as T

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from .postal_code_constants import (
    LIECHTENSTEIN_POSTAL_CODES,
    SAN_MARINO_POSTAL_CODES,
    POSTAL_CODE_RULES,
)


class PostalCodeEnrichOperation(BaseOperation):
    """Validates and formats customer postal codes against country-specific rules, then compares them to external reference postal codes to produce a match status."""

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        """Main transformation pipeline."""
        df = ctx[self._config.context_name]
        df = self.enrich_country_code(df)
        df = self.enrich_postal_code(df)
        df = self.add_match_status(df)
        df = self.add_validation_message(df)
        return df

    @staticmethod
    def enrich_country_code(df: DataFrame) -> DataFrame:
        """
        Enrich country code for special cases.

        - CH postal codes in Liechtenstein range -> LI
        - IT postal codes in San Marino range -> SM

        Adds column:
        - en_country_code: Enriched country code
        """
        return df.withColumn(
            "en_country_code",
            F.when(
                (F.col("country_code") == "CH")
                & (F.col("post_code").isin(LIECHTENSTEIN_POSTAL_CODES)),
                F.lit("LI"),
            )
            .when(
                (F.col("country_code") == "IT")
                & (F.col("post_code").isin(SAN_MARINO_POSTAL_CODES)),
                F.lit("SM"),
            )
            .otherwise(F.col("country_code")),
        )

    @staticmethod
    def _validate_and_format_postal_code(postal_code: str, country_code: str) -> str:
        """
        Validate and format postal code according to country rules.

        Args:
            postal_code: Raw postal code string
            country_code: Two-letter country code

        Returns:
            Formatted postal code if valid, "invalid" otherwise
        """
        if not postal_code or not country_code:
            return "invalid"

        country_upper = country_code.upper()

        # Check if country has rules defined
        if country_upper not in POSTAL_CODE_RULES:
            return "invalid"

        # Clean postal code: remove non-ASCII and non-alphanumeric characters
        cleaned_code = re.sub(r"[^\x00-\x7F]+", "", postal_code)
        alphanumeric_code = re.sub(r"\W", "", cleaned_code).strip()

        # Get country-specific rules
        rule = POSTAL_CODE_RULES[country_upper]["format_rule"]
        regex = POSTAL_CODE_RULES[country_upper]["regex"]

        # Validate and format
        if re.fullmatch(regex, alphanumeric_code):
            return rule(alphanumeric_code)
        else:
            return "invalid"

    @staticmethod
    def enrich_postal_code(df: DataFrame) -> DataFrame:
        """
        Apply postal code validation and formatting.

        Adds column:
        - post_code_enricher: Validated and formatted postal code
        """
        enrich_udf = F.udf(
            PostalCodeEnrichOperation._validate_and_format_postal_code,
            T.StringType(),
        )

        return df.withColumn(
            "post_code_enricher",
            enrich_udf(F.col("post_code"), F.col("en_country_code")),
        )

    @staticmethod
    def _get_skip_validation_condition():
        """
        Get Spark Column expression for skip validation condition.

        Validation is skipped when:
        - No info from external database
        - No match found
        - Valid address is False

        Returns:
            Column expression for skip condition
        """
        return (
            F.col("address_match_result").contains("No Info from External Database")
            | F.col("address_match_result").contains("No Match")
            | (F.col("address_match_result") == False)
        )

    @staticmethod
    def add_match_status(df: DataFrame) -> DataFrame:
        """
        Add postal code match status.

        Logic:
        - Empty string if validation should be skipped or no external postal code
        - "1" if postal codes match (ignoring spaces, case-insensitive)
        - "0" if postal codes don't match

        Adds column:
        - check_status: Match status indicator
        """
        skip_condition = PostalCodeEnrichOperation._get_skip_validation_condition()

        return df.withColumn(
            "check_status",
            F.when(skip_condition, F.lit(""))
            .when(
                (F.col("ext_post_code").isNull()) | (F.col("ext_post_code") == ""),
                F.lit(""),
            )
            .when(
                F.upper(F.regexp_replace(F.col("ext_post_code"), " ", ""))
                == F.upper(F.regexp_replace(F.col("post_code_enricher"), " ", "")),
                F.lit("1"),
            )
            .otherwise(F.lit("0")),
        )

    @staticmethod
    def add_validation_message(df: DataFrame) -> DataFrame:
        """
        Add human-readable validation message.

        Logic:
        - "No external validation" if validation skipped or no external postal code
        - Empty string if postal codes match
        - Descriptive message if postal codes don't match

        Adds column:
        - advanced_message: Validation message
        """
        skip_condition = PostalCodeEnrichOperation._get_skip_validation_condition()

        return df.withColumn(
            "advanced_message",
            F.when(skip_condition, F.lit("No external validation"))
            .when(
                (F.col("ext_post_code").isNull()) | (F.col("ext_post_code") == ""),
                F.lit("No external validation"),
            )
            .when(
                F.upper(F.regexp_replace(F.col("ext_post_code"), " ", ""))
                == F.upper(F.regexp_replace(F.col("post_code_enricher"), " ", "")),
                F.lit(""),
            )
            .otherwise(
                F.concat_ws(
                    " ",
                    F.lit("Address is associated to"),
                    F.upper(F.col("ext_post_code")),
                    F.lit("- Matching info:"),
                    F.col("address_match_result"),
                )
            ),
        )
