from pyspark.sql import functions as F
from pyspark.sql.dataframe import DataFrame
from typing import Optional


from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from .transformations import CountrySpecificNormalizer, TextNormalizer


class TextNormalizationOperation(BaseOperation):
    """Normalizes customer and external address strings by extracting house numbers and applying country-specific text cleaning, producing canonical address fields for fuzzy comparison."""

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        df = ctx[self._config.context_name]

        df = self.normalize_customer_address(df)
        df = self.normalize_external_address(df)
        return df

    def normalize_customer_address(self, df: DataFrame) -> DataFrame:
        """
        Normalize customer address (street_house_number).

        Adds columns:
        - cust_numbers: array<string>
        - cust_street_clean: string
        - n_add: string (fully normalized)
        """
        cust_numbers, cust_clean = TextNormalizer.extract_numbers_and_clean(
            F.col("street_house_number")
        )

        df = df.withColumn("cust_numbers", cust_numbers)
        df = df.withColumn("cust_street_clean", cust_clean)

        df = df.withColumn(
            "n_add",
            CountrySpecificNormalizer.normalize_address_text(
                F.col("cust_street_clean"), F.col("country_code")
            ),
        )

        return df

    def normalize_external_address(self, df: DataFrame) -> DataFrame:
        """
        Normalize external address (ext_ad).

        Adds columns:
        - ext_numbers: array<string>
        - ext_street_clean: string
        - ext_n_add: string (fully normalized)
        """
        ext_numbers, ext_clean = TextNormalizer.extract_numbers_and_clean(
            F.col("ext_ad")
        )

        df = df.withColumn("ext_numbers", ext_numbers)
        df = df.withColumn("ext_street_clean", ext_clean)

        df = df.withColumn(
            "ext_n_add",
            CountrySpecificNormalizer.normalize_address_text(
                F.col("ext_street_clean"), F.col("country_code")
            ),
        )

        return df
