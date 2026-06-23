"""Spark-native address normalization transformations."""

from pyspark.sql import functions as F
from pyspark.sql import types as T
from pyspark.sql import Column
from unidecode import unidecode

from .transliteration_constants import (
    GREEK_TONOS_MAPPINGS,
    GREEK_DIGRAPHS,
    GREEK_MONOGRAPHS,
    UNIDECODE_COUNTRIES,
    GREEK_TONOS_COUNTRIES,
    GREEK_TRANS_COUNTRIES,
    MD_PREFIX_COUNTRIES,
    NUMBER_PATTERN,
    MD_PREFIX_PATTERN,
)


_UNIDECODE_UDF = F.udf(lambda s: unidecode(s or ""), T.StringType())


class GreekTransformations:
    """Greek-specific text transformations."""

    @staticmethod
    def strip_tonos(col: Column) -> Column:
        """Remove Greek tonos (accent marks) from text."""
        c = F.regexp_replace(col, r"[.\-]", " ")

        for src, tgt in GREEK_TONOS_MAPPINGS:
            c = F.regexp_replace(c, src, tgt)

        c = F.regexp_replace(c, r"\s+", " ")
        return F.trim(c)

    @staticmethod
    def transliterate(col: Column) -> Column:
        """Transliterate Greek text to Latin characters."""
        c = col

        for src, tgt in GREEK_DIGRAPHS:
            c = F.regexp_replace(c, src, tgt)

        for src, tgt in GREEK_MONOGRAPHS.items():
            c = F.regexp_replace(c, src, tgt)

        return c


class TextNormalizer:
    """General text normalization operations."""

    @staticmethod
    def extract_numbers_and_clean(col: Column) -> tuple[Column, Column]:
        """
        Extract numbers and return cleaned text.

        Returns:
            tuple: (numbers_array, cleaned_text)
        """
        tokens = F.split(col, r"\s+")
        numbers_col = F.filter(tokens, lambda x: x.rlike(NUMBER_PATTERN))
        clean = F.regexp_replace(col, NUMBER_PATTERN, " ")
        clean = F.trim(F.regexp_replace(clean, r"\s+", " "))

        return numbers_col, clean

    @staticmethod
    def remove_md_prefix(col: Column) -> Column:
        """Remove Moldova-specific street prefixes."""
        return F.regexp_replace(col, MD_PREFIX_PATTERN, "")

    @staticmethod
    def normalize_whitespace(col: Column) -> Column:
        """Normalize and trim whitespace."""
        return F.trim(F.regexp_replace(col, r"\s+", " "))


class CountrySpecificNormalizer:
    """Apply country-specific normalization rules."""

    @staticmethod
    def normalize_address_text(col: Column, country_col: Column) -> Column:
        """
        Apply full normalization pipeline for address text.

        Pipeline order:
        1. Greek tonos removal (GR)
        2. Unidecode transliteration (RO, RS, ME, MD, AT, SK, PL, MK)
        3. Greek transliteration (CY)
        4. MD prefix removal (MD)
        5. Whitespace normalization
        """
        c = col

        c = F.when(
            country_col.isin(*GREEK_TONOS_COUNTRIES),
            GreekTransformations.strip_tonos(c),
        ).otherwise(c)

        c = F.when(country_col.isin(*UNIDECODE_COUNTRIES), _UNIDECODE_UDF(c)).otherwise(
            c
        )

        c = F.when(
            country_col.isin(*GREEK_TRANS_COUNTRIES),
            GreekTransformations.transliterate(c),
        ).otherwise(c)

        c = F.when(
            country_col.isin(*MD_PREFIX_COUNTRIES), TextNormalizer.remove_md_prefix(c)
        ).otherwise(c)

        c = TextNormalizer.normalize_whitespace(c)

        return c
