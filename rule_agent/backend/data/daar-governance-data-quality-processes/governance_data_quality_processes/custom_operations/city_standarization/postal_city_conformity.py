from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as sf

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.city_standarization.postal_city_conformity_config import (
    PostalCityConformityOperationConfig,
)


# ===========================================================
#  Core logic
# ===========================================================

def run_postal_city_conformity(df: DataFrame) -> DataFrame:
    """
    Expected input columns:
      - customer_code
      - country_code
      - value_checked
      - enriched_value
      - valid_country
      - valid_city
      - check_dict_city
      - location_info (struct with: place_name, state_name, county_name)
      - location_info_ext (struct with: address, municipality, region)
      - location_info_ext2 (struct with: region)
      - city
    """

    df = df.withColumn("check_status", sf.col("valid_city"))

    df = df.withColumn(
        "check_status",
        sf.when((sf.col("value_checked").isNull()) | (sf.col("value_checked") == ""), "")
        .when(
            ((sf.col("check_status") == "") | (sf.col("check_status").isNull()))
            & ((sf.col("value_checked") != "") | (sf.col("value_checked").isNotNull())),
            "0",
        )
        .when(sf.col("enriched_value") == "invalid", "0")
        .when((sf.col("check_status") == False) & (sf.col("valid_country") == False), "")
        .when(sf.col("check_status") == False, "0")
        .otherwise("1"),
    )

    df = df.withColumn(
        "advanced_message",
        sf.when(
            (sf.col("check_status") == "0") & (sf.col("enriched_value") == "invalid"),
            sf.lit("Invalid Postal Code"),
        )
        .when(
            (sf.col("check_status") == "") & (sf.col("valid_country") == False),
            sf.lit("Invalid Country"),
        )
        .when(
            (sf.col("check_status") == "")
            & (sf.col("value_checked").isNull() | (sf.col("value_checked") == "")),
            sf.lit("No Postal Code Given"),
        )
        .when(
            (sf.col("check_status") == "0")
            & (sf.col("check_dict_city") != "external")
            & (sf.col("country_code") != "GR"),
            sf.concat_ws(
                ", ",
                *[
                    sf.lit("Invalid City, Suggestions For City:"),
                    sf.when(
                        sf.col("location_info.place_name").isNotNull()
                        & (sf.col("location_info.place_name") != ""),
                        sf.col("location_info.place_name"),
                    ).otherwise(None),
                    sf.when(
                        sf.col("location_info.state_name").isNotNull()
                        & (sf.col("location_info.state_name") != ""),
                        sf.col("location_info.state_name"),
                    ).otherwise(None),
                    sf.when(
                        sf.col("location_info.county_name").isNotNull()
                        & (sf.col("location_info.county_name") != ""),
                        sf.col("location_info.county_name"),
                    ).otherwise(None),
                ],
            ),
        )
        .when(
            (sf.col("check_status") == "0")
            & (sf.col("check_dict_city") == "external")
            & (sf.col("country_code") != "GR"),
            sf.when(
                sf.col("location_info_ext").isNotNull(),
                sf.concat_ws(
                    ", ",
                    *[
                        sf.lit("Invalid City, Suggestions For City:"),
                        sf.when(
                            sf.col("location_info_ext.address").isNotNull()
                            & (sf.col("location_info_ext.address") != ""),
                            sf.col("location_info_ext.address"),
                        ).otherwise(None),
                        sf.when(
                            sf.col("location_info_ext.municipality").isNotNull()
                            & (sf.col("location_info_ext.municipality") != ""),
                            sf.col("location_info_ext.municipality"),
                        ).otherwise(None),
                        sf.when(
                            sf.col("location_info_ext.region").isNotNull()
                            & (sf.col("location_info_ext.region") != ""),
                            sf.col("location_info_ext.region"),
                        ).otherwise(None),
                    ],
                ),
            ),
        )
        .when(
            (sf.col("check_status") == "0") & (sf.col("country_code") == "GR"),
            sf.concat_ws(
                ", ",
                *[
                    sf.lit("Invalid City, Suggestions For City:"),
                    sf.when(
                        sf.col("location_info.place_name").isNotNull()
                        & (sf.col("location_info.place_name") != ""),
                        sf.col("location_info.place_name"),
                    ).otherwise(None),
                    sf.when(
                        sf.col("location_info_ext").isNotNull(),
                        sf.concat_ws(
                            ", ",
                            *[
                                sf.when(
                                    sf.col("location_info_ext.region").isNotNull()
                                    & (sf.col("location_info_ext.region") != ""),
                                    sf.col("location_info_ext.region"),
                                ).otherwise(None),
                            ],
                        ),
                    ),
                    sf.when(
                        sf.col("location_info_ext2").isNotNull(),
                        sf.concat_ws(
                            ", ",
                            *[
                                sf.when(
                                    sf.col("location_info_ext2.region").isNotNull()
                                    & (sf.col("location_info_ext2.region") != ""),
                                    sf.col("location_info_ext2.region"),
                                ).otherwise(None),
                            ],
                        ),
                    ),
                ],
            ),
        )
        .otherwise(sf.lit("Valid City")),
    )

    keep_cols = [
        "customer_code",
        "country_code",
        "value_checked",
        "city",
        "check_status",
        "advanced_message",
    ]

    existing_keep_cols = [c for c in keep_cols if c in df.columns]
    df = df.select(*[sf.col(c) for c in existing_keep_cols])

    return df


# ===========================================================
#  Operation class
# ===========================================================

class PostalCityConformityOperation(BaseOperation):
    """
    Operation wrapper for run_postal_city_conformity.
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, PostalCityConformityOperationConfig)

        source_df: DataFrame = ctx[self._config.context_name]
        params = getattr(self._config, "params", None)

        df = source_df

        if params is not None:
            col_mapping = {
                "customer_code": getattr(params, "customer_code", "customer_code"),
                "country_code": getattr(params, "country_code", "country_code"),
                "value_checked": getattr(params, "value_checked", "value_checked"),
                "enriched_value": getattr(params, "enriched_value", "enriched_value"),
                "valid_country": getattr(params, "valid_country", "valid_country"),
                "valid_city": getattr(params, "valid_city", "valid_city"),
                "check_dict_city": getattr(params, "check_dict_city", "check_dict_city"),
                "location_info": getattr(params, "location_info", "location_info"),
                "location_info_ext": getattr(params, "location_info_ext", "location_info_ext"),
                "location_info_ext2": getattr(params, "location_info_ext2", "location_info_ext2"),
                "city": getattr(params, "city", "city"),
            }

            df = (
                df.withColumn("customer_code", sf.col(col_mapping["customer_code"]))
                  .withColumn("country_code", sf.col(col_mapping["country_code"]))
                  .withColumn("value_checked", sf.col(col_mapping["value_checked"]))
                  .withColumn("enriched_value", sf.col(col_mapping["enriched_value"]))
                  .withColumn("valid_country", sf.col(col_mapping["valid_country"]))
                  .withColumn("valid_city", sf.col(col_mapping["valid_city"]))
                  .withColumn("check_dict_city", sf.col(col_mapping["check_dict_city"]))
                  .withColumn("location_info", sf.col(col_mapping["location_info"]))
                  .withColumn("location_info_ext", sf.col(col_mapping["location_info_ext"]))
                  .withColumn("location_info_ext2", sf.col(col_mapping["location_info_ext2"]))
                  .withColumn("city", sf.col(col_mapping["city"]))
                  
            )

        return run_postal_city_conformity(df)
