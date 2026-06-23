from typing import Optional, Dict, Any
import re

from pyspark.sql import DataFrame
from pyspark.sql import functions as sf
from pyspark.sql.types import StringType

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.city_standarization.geocoords_postal_conformity_config import (
    GeocoordsPostalConformityOperationConfig,
)

# ===========================================================
#  Constants / Rules
# ===========================================================

DISTANCE_THRESHOLD_M_DEFAULT = 10000

LIECHTENSTEIN_POSTAL_CODES = {
    "9485", "9486", "9487", "9488", "9489", "9490", "9491", "9492", "9493", "9494", "9495", "9496", "9497", "9498"
}

SAN_MARINO_POSTAL_CODES = {
    "47890", "47891", "47892", "47893", "47894", "47895", "47896", "47897", "47898", "47899"
}

COUNTRY_POSTAL_RULES = {
    "AM": {"regex": r"^\d{4}$", "format_rule": lambda code: code.zfill(4)},
    "AT": {"regex": r"^\d{4}$", "format_rule": lambda code: code.zfill(4)},
    "BA": {"regex": r"^\d{5}$", "format_rule": lambda code: code.zfill(5)},
    "BG": {"regex": r"^\d{4}$", "format_rule": lambda code: code.zfill(4)},
    "CH": {"regex": r"^\d{4}$", "format_rule": lambda code: code.zfill(4)},
    "CY": {"regex": r"^\d{4}$", "format_rule": lambda code: code.zfill(4)},
    "CZ": {"regex": r"^\d{5}$", "format_rule": lambda code: re.sub(r"(\d{3})(\d{2})", r"\1 \2", code)},
    "EE": {"regex": r"^\d{5}$", "format_rule": lambda code: code.zfill(5)},
    "GR": {"regex": r"^\d{5}$", "format_rule": lambda code: re.sub(r"(\d{3})(\d{2})", r"\1 \2", code)},
    "HR": {"regex": r"^\d{5}$", "format_rule": lambda code: code.zfill(5)},
    "HU": {"regex": r"^\d{4}$", "format_rule": lambda code: code.zfill(4)},
    "IE": {"regex": r"^[A-Za-z0-9]{3}\s?[A-Za-z0-9]{4}$", "format_rule": lambda code: re.sub(r"(\w{1})(\w{2})(\w{4})", r"\1\2 \3", code)},
    "IT": {"regex": r"^\d{5}$", "format_rule": lambda code: code.zfill(5)},
    "KV": {"regex": r"^\d{5}$", "format_rule": lambda code: code.zfill(5)},
    "LT": {"regex": r"^LT\d{5}$", "format_rule": lambda code: code[2:].zfill(5)},
    "LV": {"regex": r"^LV\d{4}$", "format_rule": lambda code: f"LV-{code[-4:]}"},
    "ME": {"regex": r"^\d{5}$", "format_rule": lambda code: code.zfill(5)},
    "MD": {"regex": r"^\d{4}$", "format_rule": lambda code: f"MD-{code[-4:]}"},
    "NG": {"regex": r"^\d{6}$", "format_rule": lambda code: code.zfill(6)},
    "PL": {"regex": r"^\d{5}$", "format_rule": lambda code: re.sub(r"(\w{2})(\w{3})", r"\1-\2", code)},
    "RO": {"regex": r"^\d{6}$", "format_rule": lambda code: code.zfill(6)},
    "RS": {"regex": r"^\d{5}$", "format_rule": lambda code: code.zfill(5)},
    "SI": {"regex": r"^\d{4}$", "format_rule": lambda code: re.sub(r"(\w{2})(\w{4})", r"\1-\2", code)},
    "SK": {"regex": r"^\d{5}$", "format_rule": lambda code: re.sub(r"(\d{3})(\d{2})", r"\1 \2", code)},
    "UA": {"regex": r"^\d{5}$", "format_rule": lambda code: code.zfill(5)},
    "GB": {"regex": r"^([A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2})$", "format_rule": lambda code: re.sub(r"(\w{2}\d{1,2})(\d[A-Z]{2})$", r"\1 \2", code)},
    "LI": {"regex": r"^94(8[5-9]|9[0-7])$", "format_rule": lambda code: code},
    "MK": {"regex": r"^[1-9][0-9]{3}$", "format_rule": lambda code: code.zfill(4)},
    "SM": {"regex": r"^4789[0-9]$", "format_rule": lambda code: code},
}


# ===========================================================
#  Helpers
# ===========================================================

def _apply_column_mapping(df: DataFrame, mapping: Dict[str, str]) -> DataFrame:
    for standard_col, source_col in mapping.items():
        df = df.withColumn(standard_col, sf.col(source_col))
    return df


def _make_postal_enricher_udf(rules: Dict[str, Any]):
    compiled = {
        cc: {"regex": re.compile(rule["regex"]), "format_rule": rule["format_rule"]}
        for cc, rule in rules.items()
    }

    def enrich(postal_code: str, country_code: str) -> str:
        if postal_code is None or country_code is None:
            return "invalid"

        cc = str(country_code).upper()
        if cc not in compiled:
            return "invalid"

        cleaned = re.sub(r"[^\x00-\x7F]+", "", str(postal_code))
        alnum = re.sub(r"\W", "", cleaned).strip()

        rule = compiled[cc]
        if rule["regex"].fullmatch(alnum):
            try:
                return rule["format_rule"](alnum)
            except Exception:
                return "invalid"

        return "invalid"

    return sf.udf(enrich, StringType())


def _haversine_distance_m_expr(lat1, lon1, lat2, lon2):
    r = sf.lit(6371000.0)
    to_rad = lambda c: sf.radians(c.cast("double"))

    lat1r, lon1r, lat2r, lon2r = to_rad(lat1), to_rad(lon1), to_rad(lat2), to_rad(lon2)
    dlat, dlon = lat2r - lat1r, lon2r - lon1r

    a = sf.pow(sf.sin(dlat / 2), 2) + sf.cos(lat1r) * sf.cos(lat2r) * sf.pow(sf.sin(dlon / 2), 2)
    c = 2 * sf.atan2(sf.sqrt(a), sf.sqrt(1 - a))
    return r * c


# ===========================================================
#  Core logic
# ===========================================================

def run_geocoords_postcode_check(df: DataFrame, distance_threshold_m: int = DISTANCE_THRESHOLD_M_DEFAULT) -> DataFrame:
    """
    Validation of postal code with geocoords.
    """

    thr = sf.lit(float(distance_threshold_m))
    postal_udf = _make_postal_enricher_udf(COUNTRY_POSTAL_RULES)

    df = (
        df.withColumn("ext_post_code", sf.col("geocoords_extractor")["postal_code"])
          .withColumn("ext_lat", sf.col("geocoords_extractor")["latitude"].cast("double"))
          .withColumn("ext_long", sf.col("geocoords_extractor")["longitude"].cast("double"))
          .withColumn("ext_post_code2", sf.col("geocoords_extractor2")["postal_code"])
          .withColumn("ext_lat2", sf.col("geocoords_extractor2")["latitude"].cast("double"))
          .withColumn("ext_long2", sf.col("geocoords_extractor2")["longitude"].cast("double"))
    )

    df = df.withColumn(
        "en_country_code",
        sf.when(
            (sf.col("country_code") == "CH")
            & (sf.col("postal_code").isin(list(LIECHTENSTEIN_POSTAL_CODES))),
            sf.lit("LI"),
        )
        .when(
            (sf.col("country_code") == "IT")
            & (sf.col("postal_code").isin(list(SAN_MARINO_POSTAL_CODES))),
            sf.lit("SM"),
        )
        .otherwise(sf.col("country_code")),
    )

    df = df.withColumn(
        "post_code_enricher",
        postal_udf(sf.col("postal_code"), sf.col("en_country_code")),
    )

    df = df.withColumn(
        "distance_m",
        _haversine_distance_m_expr(
            sf.col("latitude"),
            sf.col("longitude"),
            sf.col("ext_lat"),
            sf.col("ext_long"),
        ),
    ).withColumn(
        "distance_m2",
        _haversine_distance_m_expr(
            sf.col("latitude"),
            sf.col("longitude"),
            sf.col("ext_lat2"),
            sf.col("ext_long2"),
        ),
    )

    has_ext1_or = (sf.col("ext_post_code").isNotNull()) | (sf.col("ext_post_code") != "")
    has_ext2_or = (sf.col("ext_post_code2").isNotNull()) | (sf.col("ext_post_code2") != "")
    no_ext2 = (sf.col("ext_post_code2").isNull()) | (sf.col("ext_post_code2") == "")
    no_ext1 = (sf.col("ext_post_code").isNull()) | (sf.col("ext_post_code") == "")
    no_postal = (sf.col("postal_code").isNull()) | (sf.col("postal_code") == "")

    is_ng_special = sf.col("postal_code").startswith("926") | sf.col("postal_code").startswith("561")

    def ng_prefix_equal(col_name: str):
        return sf.when(
            is_ng_special,
            sf.substring(sf.regexp_replace(sf.col(col_name), " ", ""), 1, 3)
            == sf.substring(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""), 1, 3),
        ).otherwise(
            sf.substring(sf.regexp_replace(sf.col(col_name), " ", ""), 1, 2)
            == sf.substring(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""), 1, 2),
        )

    def ng_prefix_not_equal(col_name: str):
        return sf.when(
            is_ng_special,
            sf.substring(sf.regexp_replace(sf.col(col_name), " ", ""), 1, 3)
            != sf.substring(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""), 1, 3),
        ).otherwise(
            sf.substring(sf.regexp_replace(sf.col(col_name), " ", ""), 1, 2)
            != sf.substring(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""), 1, 2),
        )

    def ie_prefix_equal(col_name: str):
        return (
            sf.substring(sf.upper(sf.regexp_replace(sf.col(col_name), " ", "")), 1, 3)
            == sf.substring(sf.upper(sf.regexp_replace(sf.col("post_code_enricher"), " ", "")), 1, 3)
        )

    def ie_prefix_not_equal(col_name: str):
        return (
            sf.substring(sf.upper(sf.regexp_replace(sf.col(col_name), " ", "")), 1, 3)
            != sf.substring(sf.upper(sf.regexp_replace(sf.col("post_code_enricher"), " ", "")), 1, 3)
        )

    df = df.withColumn(
        "check_status",
        sf.when(sf.col("country_validation") == "0", sf.lit(""))
          .when(sf.col("city_validation") == "0", sf.lit(""))
          .when((sf.col("ext_post_code").isNull()) | (sf.col("ext_post_code") == ""), sf.lit(""))
          .when(no_postal, sf.lit(""))
          .when(
              sf.when(sf.col("country_code") == "NG", ng_prefix_equal("ext_post_code"))
                .when(sf.col("country_code") == "IE", ie_prefix_equal("ext_post_code"))
                .otherwise(
                    sf.upper(sf.regexp_replace(sf.col("ext_post_code"), " ", ""))
                    == sf.upper(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""))
                )
              & (sf.col("distance_m") <= thr),
              sf.lit("1"),
          )
          .when(sf.col("distance_m") > thr, sf.lit(""))
          .otherwise(sf.lit("0")),
    )

    df = df.withColumn(
        "check_status",
        sf.when(has_ext1_or & (sf.col("check_status") == "0") & no_ext2, sf.lit("0"))
          .when(
              has_ext1_or & (sf.col("check_status") == "0")
              & sf.when(sf.col("country_code") == "NG", ng_prefix_equal("ext_post_code2"))
                .when(sf.col("country_code") == "IE", ie_prefix_equal("ext_post_code2"))
                  .otherwise(
                      sf.upper(sf.regexp_replace(sf.col("ext_post_code2"), " ", ""))
                      == sf.upper(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""))
                  )
              & (sf.col("distance_m2") <= thr),
              sf.lit("1"),
          )
          .when(
              has_ext1_or & (sf.col("check_status") == "0")
              & sf.when(sf.col("country_code") == "NG", ng_prefix_not_equal("ext_post_code2"))
                .when(sf.col("country_code") == "IE", ie_prefix_not_equal("ext_post_code2"))
                  .otherwise(
                      sf.upper(sf.regexp_replace(sf.col("ext_post_code2"), " ", ""))
                      != sf.upper(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""))
                  )
              & (sf.col("distance_m2") <= thr),
              sf.lit("0"),
          )
          .when(has_ext1_or & (sf.col("check_status") == "0") & (sf.col("distance_m2") > thr), sf.lit("0"))
          .when((sf.col("distance_m") > thr) & (sf.col("check_status") == "") & no_ext2, sf.lit(""))
          .when(
              (sf.col("distance_m") > thr) & (sf.col("check_status") == "")
              & sf.when(sf.col("country_code") == "NG", ng_prefix_equal("ext_post_code2"))
                .when(sf.col("country_code") == "IE", ie_prefix_equal("ext_post_code2"))
                  .otherwise(
                      sf.upper(sf.regexp_replace(sf.col("ext_post_code2"), " ", ""))
                      == sf.upper(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""))
                  )
              & (sf.col("distance_m2") <= thr),
              sf.lit("1"),
          )
          .when(
              (sf.col("distance_m") > thr) & (sf.col("check_status") == "")
              & sf.when(sf.col("country_code") == "NG", ng_prefix_not_equal("ext_post_code2"))
                .when(sf.col("country_code") == "IE", ie_prefix_not_equal("ext_post_code2"))
                  .otherwise(
                      sf.upper(sf.regexp_replace(sf.col("ext_post_code2"), " ", ""))
                      != sf.upper(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""))
                  )
              & (sf.col("distance_m2") <= thr),
              sf.lit("0"),
          )
          .when((sf.col("distance_m") > thr) & (sf.col("check_status") == "") & (sf.col("distance_m2") > thr), sf.lit(""))
          .when(
              no_ext1 & (sf.col("check_status") == "")
              & sf.when(sf.col("country_code") == "NG", ng_prefix_equal("ext_post_code2"))
                .when(sf.col("country_code") == "IE", ie_prefix_equal("ext_post_code2"))
                  .otherwise(
                      sf.upper(sf.regexp_replace(sf.col("ext_post_code2"), " ", ""))
                      == sf.upper(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""))
                  )
              & (sf.col("distance_m2") <= thr),
              sf.lit("1"),
          )
          .when(
              no_ext1 & (sf.col("check_status") == "")
              & sf.when(sf.col("country_code") == "NG", ng_prefix_not_equal("ext_post_code2"))
                .when(sf.col("country_code") == "IE", ie_prefix_not_equal("ext_post_code2"))
                  .otherwise(
                      sf.upper(sf.regexp_replace(sf.col("ext_post_code2"), " ", ""))
                      != sf.upper(sf.regexp_replace(sf.col("post_code_enricher"), " ", ""))
                  )
              & (sf.col("distance_m2") <= thr),
              sf.lit("0"),
          )
          .when(no_ext1 & (sf.col("check_status") == "") & no_ext2, sf.lit(""))
          .when(no_ext1 & (sf.col("check_status") == "") & (sf.col("distance_m2") > thr), sf.lit(""))
          .otherwise(sf.col("check_status")),
    )

    df = df.withColumn(
        "advanced_check",
        sf.when(sf.col("country_validation") == "0", sf.lit("Country Invalid"))
          .when(sf.col("city_validation") == "0", sf.lit("City Invalid"))
          .when(no_postal, sf.lit("No Given Postal Code"))
          .when(
              (sf.col("check_status") == "0") & has_ext1_or & no_ext2,
              sf.concat_ws(
                  " ",
                  sf.lit("Geocoords are associated to"),
                  sf.upper(sf.col("ext_post_code")),
                  sf.lit("Confidence (in m):"),
                  sf.round(sf.col("distance_m"), 2),
              ),
          )
          .when(
              (sf.col("check_status") == "0") & has_ext2_or & (sf.col("distance_m2") <= thr),
              sf.concat_ws(
                  " ",
                  sf.lit("Geocoords are associated to"),
                  sf.upper(sf.col("ext_post_code2")),
                  sf.lit("Confidence (in m):"),
                  sf.round(sf.col("distance_m2"), 2),
              ),
          )
          .when(sf.col("check_status") == "1", sf.lit(""))
          .when((sf.col("distance_m") > thr) & (sf.col("distance_m2") > thr), sf.lit("No reliable output from sources"))
          .otherwise(sf.lit("Geocoords are associated to a different postal code.")),
    )

    df = df.withColumn(
        "checked_value", sf.concat_ws(", ", sf.col("latitude"), sf.col("longitude"))
    ).withColumn(
        "attribute", sf.concat_ws(", ", sf.lit("lat"), sf.lit("long"))
    )

    df = df.drop(
        "post_code_enricher",
        "en_country_code",
        "distance_m",
        "distance_m2",
        "ext_lat",
        "ext_long",
        "ext_lat2",
        "ext_long2",
        "latitude",
        "longitude",
    )

    return df


# ===========================================================
#  Operation class
# ===========================================================

class GeocoordsPostalConformityOperation(BaseOperation):
    """
    Operation wrapper for run_geocoords_postcode_check.
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(
            self._config,
            GeocoordsPostalConformityOperationConfig,
        ), f"Invalid config type: {type(self._config)}"

        source_df: DataFrame = ctx[self._config.context_name]

        params = getattr(self._config, "params", None)
        distance_threshold_m = getattr(
            self._config,
            "distance_threshold_m",
            DISTANCE_THRESHOLD_M_DEFAULT,
        )

        df = source_df

        if params is not None:
            col_mapping = {
                "customer_code": getattr(params, "customer_code", "customer_code"),
                "central_order_block_code": getattr(
                    params, "central_order_block_code", "central_order_block_code"
                ),
                "country_code": getattr(params, "country_code", "country_code"),
                "postal_code": getattr(params, "postal_code", "postal_code"),
                "latitude": getattr(params, "latitude", "latitude"),
                "longitude": getattr(params, "longitude", "longitude"),

                "country_validation": getattr(
                    params, "country_validation", "country_validation"
                ),
                "city_validation": getattr(
                    params, "city_validation", "city_validation"
                ),

                "geocoords_extractor": getattr(
                    params, "geocoords_extractor", "geocoords_extractor"
                ),
                "geocoords_extractor2": getattr(
                    params, "geocoords_extractor2", "geocoords_extractor2"
                ),
            }

            df = _apply_column_mapping(df, col_mapping)

        result_df = run_geocoords_postcode_check(
            df,
            distance_threshold_m=distance_threshold_m,
        )

        return result_df
