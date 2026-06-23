from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as sf

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.city_standarization.postal_country_conformity_config import (
    PostalCountryConformityOperationConfig,
)


# ===========================================================
#  Core logic
# ===========================================================

def run_postal_country_conformity(df: DataFrame) -> DataFrame:
    """
    Validation of postal code with country code.
    """

    df = df.withColumn("check_status", sf.col("valid_country"))

    df = df.withColumn(
        "check_status",
        sf.when((sf.col("value_checked").isNull()) | (sf.col("value_checked") == ""), "")
        .when(sf.col("enriched_value") == "invalid", "0")
        .when(sf.col("check_status") == False, "0")
        .otherwise("1"),
    )

    df = df.withColumn(
        "advanced_message",
        sf.when(
            (sf.col("check_status") == "0") & (sf.col("enriched_value") == "invalid"),
            sf.lit("Invalid Postal Code"),
        )
        .when(sf.col("check_status") == "", sf.lit("No Postal Code Given"))
        .when(
            (sf.col("check_status") == "0")
            & (sf.col("location_info.country_code") != ""),
            sf.concat(
                sf.lit("Invalid Country, Suggestions For Country: "),
                sf.col("location_info.country_code"),
            ),
        )
        .when(sf.col("check_status") == "0", sf.lit("Invalid Country"))
        .when(
            (sf.col("check_status") == "1")
            & (sf.col("location_info.API") == "pgeocode"),
            sf.lit("Valid Country"),
        )
        .otherwise(sf.lit("Given Country is Valid")),
    )

    df = df.drop(
        "enriched_value",
        "en_country_code",
        "city",
        "trans_city",
        "location_info",
        "valid_country",
        "valid_city",
        "location_info_Pgeocode",
        "location_info_Geolocator",
        "check_dict",
        "n_city",
        "location_info_ext",
        "location_info_ext2",
        "check_dict_country",
        "check_dict_city",
    )

    return df


# ===========================================================
#  Operation class
# ===========================================================

class PostalCountryConformityOperation(BaseOperation):
    """
    Operation wrapper for run_postal_country_conformity.
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, PostalCountryConformityOperationConfig)

        source_df: DataFrame = ctx[self._config.context_name]

        params = getattr(self._config, "params", None)
        df = source_df

        if params is not None:
            col_mapping = {
                "customer_code": getattr(params, "customer_code", "customer_code"),
                "country_code": getattr(params, "country_code", "country_code"),
                "city": getattr(params, "city", "city"),
                "value_checked": getattr(params, "value_checked", "value_checked"),
                "enriched_value": getattr(params, "enriched_value", "enriched_value"),
                "valid_country": getattr(params, "valid_country", "valid_country"),
                "location_info": getattr(params, "location_info", "location_info"),
            }

            df = (
                df.withColumn("customer_code", sf.col(col_mapping["customer_code"]))
                  .withColumn("country_code", sf.col(col_mapping["country_code"]))
                  .withColumn("city", sf.col(col_mapping["city"]))
                  .withColumn("value_checked", sf.col(col_mapping["value_checked"]))
                  .withColumn("enriched_value", sf.col(col_mapping["enriched_value"]))
                  .withColumn("valid_country", sf.col(col_mapping["valid_country"]))
                  .withColumn("location_info", sf.col(col_mapping["location_info"]))
            )

        result_df = run_postal_country_conformity(df)

        return result_df
