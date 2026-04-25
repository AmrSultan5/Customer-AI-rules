from typing import Optional
import math
import pandas as pd
import networkx as nx
import jellyfish
from rapidfuzz import process, fuzz

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as sf
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructType,
    StructField,
)
from pyspark.sql.functions import udf
from pyspark.sql.window import Window

from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from datamesh_common.utils.base_utils import log_execution_time
from governance_data_quality_processes.custom_operation_configs.city_standarization.city_std_conformity_config import (
    CityStdConformityOperationConfig,
)


class CityStdConformityOperation(BaseOperation):
    """Clusters city name variants per country using fuzzy and phonetic similarity, then proposes a canonical standardized city name for each customer record."""

    SIMILARITY_THRESHOLD_FUZZY = 92
    SIMILARITY_THRESHOLD_JELLYFISH = 85
    DISTANCE_KM = 10

    DIERESIS_REPLACEMENTS = {"Ϊ": "Ι", "ϊ": "ι", "Ϋ": "Υ", "ϋ": "υ"}
    HU_REPLACEMENTS = {
        "MONORIERDÖ": "MONORIERDŐ",
        "SZENTLÖRINC": "SZENTLŐRINC",
        "ÓPUSZTASZER": "PUSZTASZER",
        "HAGYHÁTSZENTJAKAB": "HEGYHÁTSZENTJAKAB",
    }
    RS_REPLACEMENTS = {
        "BAJINA BASTA TARA": "BAJINA BASTA TARA",
        "BEOGRAD GUNCATI": "BEOGRAD GUNCATI",
        "BEOGRAD ZEMUN POLJE": "BEOGRAD ZEMUN POLJE",
        "BEOGRAD ZEMUN GALENIKA": "BEOGRAD ZEMUN GALENIKA",
        "UB BANJANI": "UB BANJANI",
        "ZASAVICA II": "ZASAVICA II",
        "MALI POZAREVAC": "MALI POZAREVAC",
        "OBRENOVAC KRTINSKA": "OBRENOVAC KRTINSKA",
        "BEOGRAD ZEMUN ALTINA": "BEOGRAD ZEMUN ALTINA",
        "OBRENOVAC DRAZEVAC": "OBRENOVAC DRAZEVAC",
        "MACVANSKI PRICINOVIC SABAC": "MACVANSKI PRICINOVIC SABAC",
        "SMEDEREVSKA PALANKA GRCAC": "SMEDEREVSKA PALANKA GRCAC",
        "RUKLADA UB": "RUKLADA UB",
        "BEOGRAD PALILULA OVCA": "BEOGRAD PALILULA OVCA",
        "NOVI KNEŻEVAC FILIĆ": "NOVI KNEŻEVAC FILIĆ",
        "MALI ZVORNIK RADALJ": "MALI ZVORNIK RADALJ",
        "JADRANSKA LESNICA LOZNICA": "JADRANSKA LESNICA LOZNICA",
    }

    @staticmethod
    def _jaro_winkler_similarity(city: str, matched_city: str) -> float:
        if city is None or matched_city is None:
            return 0.0
        return jellyfish.jaro_winkler_similarity(city, matched_city) * 100.0

    @staticmethod
    def _is_invalid(city: str) -> int:
        import re
        return 1 if city is None or bool(re.match(r".*\?", city)) else 0

    @staticmethod
    def _haversine_scalar(lat1, lon1, lat2, lon2):

        def _is_invalid(v):
            return v is None or (isinstance(v, float) and math.isnan(v))

        if (
            _is_invalid(lat1)
            or _is_invalid(lon1)
            or _is_invalid(lat2)
            or _is_invalid(lon2)
        ):
            return None

        r = 6371.0

        la1 = math.radians(lat1)
        lo1 = math.radians(lon1)
        la2 = math.radians(lat2)
        lo2 = math.radians(lon2)

        cos_val = (
            math.cos(la1) * math.cos(la2) * math.cos(lo2 - lo1)
            + math.sin(la1) * math.sin(la2)
        )

        if cos_val > 1.0:
            cos_val = 1.0
        elif cos_val < -1.0:
            cos_val = -1.0

        return r * math.acos(cos_val)


    @staticmethod
    def _normalize_country_specific(series_vals: pd.Series, cc: str) -> pd.Series:
        s = series_vals.copy()

        if cc == "GR":
            for orig, repl in CityStdConformityOperation.DIERESIS_REPLACEMENTS.items():
                s = s.str.replace(orig, repl, regex=False)

            s = s.str.replace(r"\. ", " ", regex=True)
            s = s.str.replace(r"\.(?! )", " ", regex=True)

            s = s.str.replace(r" +", " ", regex=True)
            s = s.str.strip()
            return s

        if cc == "HU":
            for orig, repl in CityStdConformityOperation.HU_REPLACEMENTS.items():
                s = s.str.replace(orig, repl, regex=False)
            return s

        if cc == "RS":
            for orig, repl in CityStdConformityOperation.RS_REPLACEMENTS.items():
                s = s.str.replace(orig, repl, regex=False)
            return s

        return s

    @staticmethod
    def _cluster_country(pdf: pd.DataFrame) -> pd.DataFrame:

        country_code = str(pdf["country_code"].iloc[0])

        names = list(pdf["city__cmd"].dropna().unique())

        changes_rows = []
        for name in names:
            others = [o for o in names if o != name]
            if not others:
                continue

            match = process.extractOne(name, others, scorer=fuzz.WRatio)
            if match is None:
                continue

            matched_name, sim_score = match[0], float(match[1])

            if sim_score >= CityStdConformityOperation.SIMILARITY_THRESHOLD_FUZZY:
                changes_rows.append(
                    {
                        "city__cmd": name,
                        "matched_city": matched_name,
                        "similarity_score_fuzzy": sim_score,
                    }
                )

        if not changes_rows:
            mapping_pdf = pdf[["country_code", "city__cmd"]].copy()
            mapping_pdf["proposed_city"] = mapping_pdf["city__cmd"]
            return mapping_pdf[["country_code", "city__cmd", "proposed_city"]]

        pairs_df = pd.DataFrame(changes_rows)

        def jaro_sim(a, b):
            if a is None or b is None:
                return 0.0
            return jellyfish.jaro_winkler_similarity(a, b) * 100.0

        pairs_df["similarity_score_jellyfish"] = [
            jaro_sim(a, b)
            for a, b in zip(pairs_df["city__cmd"], pairs_df["matched_city"])
        ]

        pairs_df = pairs_df[
            pairs_df["similarity_score_jellyfish"]
            >= CityStdConformityOperation.SIMILARITY_THRESHOLD_JELLYFISH
        ]

        if pairs_df.empty:
            mapping_pdf = pdf[["country_code", "city__cmd"]].copy()
            mapping_pdf["proposed_city"] = mapping_pdf["city__cmd"]
            return mapping_pdf[["country_code", "city__cmd", "proposed_city"]]

        geo_lookup = pdf.set_index("city__cmd")[["median_latitude", "median_longitude"]]

        def safe_lookup_latlon(city_name: str):
            if city_name in geo_lookup.index:
                row = geo_lookup.loc[city_name]
                return row["median_latitude"], row["median_longitude"]
            return (None, None)

        city_geo = [safe_lookup_latlon(c) for c in pairs_df["city__cmd"]]
        match_geo = [safe_lookup_latlon(c) for c in pairs_df["matched_city"]]

        pairs_df["city_lat"] = [lat for (lat, _lon) in city_geo]
        pairs_df["city_lon"] = [lon for (_lat, lon) in city_geo]
        pairs_df["matched_lat"] = [lat for (lat, _lon) in match_geo]
        pairs_df["matched_lon"] = [lon for (_lat, lon) in match_geo]

        def dist_km(lat1, lon1, lat2, lon2):
            return CityStdConformityOperation._haversine_scalar(lat1, lon1, lat2, lon2)

        pairs_df["distance_km"] = [
            dist_km(a, b, c, d)
            for a, b, c, d in zip(
                pairs_df["city_lat"],
                pairs_df["city_lon"],
                pairs_df["matched_lat"],
                pairs_df["matched_lon"],
            )
        ]

        pairs_df = pairs_df[
            pairs_df["distance_km"].notna()
            & (pairs_df["distance_km"] < CityStdConformityOperation.DISTANCE_KM)
        ]

        if pairs_df.empty:
            mapping_pdf = pdf[["country_code", "city__cmd"]].copy()
            mapping_pdf["proposed_city"] = mapping_pdf["city__cmd"]
            return mapping_pdf[["country_code", "city__cmd", "proposed_city"]]

        G = nx.Graph()
        G.add_edges_from(zip(pairs_df["city__cmd"], pairs_df["matched_city"]))
        components = list(nx.connected_components(G))

        cluster_rows = []
        for cluster_id, comp in enumerate(components):
            for city_name in comp:
                cluster_rows.append({"city__cmd": city_name, "cluster": cluster_id})

        cluster_pdf = pd.DataFrame(cluster_rows)

        missing = set(pdf["city__cmd"]) - set(cluster_pdf["city__cmd"])
        if missing:
            extra_rows = [
                {"city__cmd": c, "cluster": -i - 1}
                for i, c in enumerate(sorted(missing))
            ]
            cluster_pdf = pd.concat([cluster_pdf, pd.DataFrame(extra_rows)], ignore_index=True)

        cluster_pdf = cluster_pdf.merge(
            pdf[["city__cmd", "city_count"]],
            on="city__cmd",
            how="left",
        )

        def pick_representative(df_cluster: pd.DataFrame) -> Optional[str]:
            df_sorted = df_cluster.sort_values("city_count", ascending=False)
            top_cnt = df_sorted["city_count"].iloc[0]
            winners = df_sorted[df_sorted["city_count"] == top_cnt]["city__cmd"].tolist()
            if len(winners) == 1:
                return winners[0]
            return None  # remis

        rep_per_cluster = (
            cluster_pdf.groupby("cluster")
            .apply(pick_representative)
            .reset_index()
            .rename(columns={0: "proposed_city"})
        )

        cluster_pdf = cluster_pdf.merge(rep_per_cluster, on="cluster", how="left")

        concat_names = (
            cluster_pdf.groupby("cluster")["city__cmd"]
            .apply(lambda xs: ", ".join(sorted(set(xs))))
            .reset_index()
            .rename(columns={"city__cmd": "concatenated_cities"})
        )
        cluster_pdf = cluster_pdf.merge(concat_names, on="cluster", how="left")

        def fix_proposed_val(prop_val, concat_val):
            if prop_val is None:
                return concat_val
            if "?" in str(prop_val):
                return concat_val
            return prop_val

        cluster_pdf["proposed_city"] = [
            fix_proposed_val(pv, cv)
            for pv, cv in zip(
                cluster_pdf["proposed_city"],
                cluster_pdf["concatenated_cities"],
            )
        ]

        cluster_pdf["proposed_city"] = CityStdConformityOperation._normalize_country_specific(
            cluster_pdf["proposed_city"], country_code
        )

        cluster_pdf["proposed_city"] = cluster_pdf["proposed_city"].fillna(
            cluster_pdf["concatenated_cities"]
        )

        out_pdf = cluster_pdf[["city__cmd", "proposed_city"]].drop_duplicates().copy()
        out_pdf["country_code"] = country_code

        return out_pdf[["country_code", "city__cmd", "proposed_city"]]

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        spark = SparkSession.builder.getOrCreate()

        spark.conf.set("spark.databricks.delta.catalog.update.enabled", False)
        spark.conf.set(
            "spark.databricks.delta.properties.defaults.autoOptimize.optimizeWrite",
            True,
        )

        assert isinstance(self._config, CityStdConformityOperationConfig)

        source_df = ctx[self._config.context_name]
        params = getattr(self._config, "params", None)

        city_col = getattr(params, "value", "city")
        lat_col = getattr(params, "latitude", "latitude")
        lon_col = getattr(params, "longitude", "longitude")
        country_col = getattr(params, "country_code", "country_code")

        cob_col = getattr(params, "central_order_block_code", "central_order_block_code")
        cust_code_col = getattr(params, "customer_code", "customer_code")

        standardized_df = source_df.select(
            (
                sf.col(cust_code_col).alias("customer_code")
                if cust_code_col in source_df.columns
                else sf.lit(None).cast(StringType()).alias("customer_code")
            ),
            (
                sf.col(cob_col).alias("central_order_block_code")
                if cob_col in source_df.columns
                else sf.lit(None).cast(StringType()).alias("central_order_block_code")
            ),
            sf.col(city_col).alias("city__cmd"),
            sf.col(lat_col).alias("latitude"),
            sf.col(lon_col).alias("longitude"),
            sf.col(country_col).alias("country_code"),
        )

        standardized_df = standardized_df.cache()

        city_stats_df = (
            standardized_df
            .groupBy("country_code", "city__cmd")
            .agg(
                sf.approx_percentile("latitude", 0.5).alias("median_latitude"),
                sf.approx_percentile("longitude", 0.5).alias("median_longitude"),
                sf.count("city__cmd").alias("city_count"),
            )
        )

        schema_mapping = StructType(
            [
                StructField("country_code", StringType(), True),
                StructField("city__cmd", StringType(), True),
                StructField("proposed_city", StringType(), True),
            ]
        )

        proposed_mapping_df = (
            city_stats_df.groupBy("country_code")
            .applyInPandas(self._cluster_country, schema=schema_mapping)
        )

        enriched_df = standardized_df.join(
            proposed_mapping_df,
            on=["country_code", "city__cmd"],
            how="left",
        )

        detail_df = (
            enriched_df
            .drop("latitude", "longitude")
            .withColumnRenamed("city__cmd", "value_checked")
            .withColumn(
                "check_status",
                sf.when(sf.col("value_checked") == "", sf.lit(""))
                .when(sf.col("value_checked").isNull(), sf.lit(""))
                .when(
                    sf.col("value_checked").rlike(r"(?i)^praha \d{1,2}$")
                    | sf.col("value_checked").rlike(r"(?i)^bratislava - pz\d{1,2}$"),
                    sf.lit("1")
                )
                .when(sf.col("value_checked") != sf.col("proposed_city"), sf.lit("0"))
                .otherwise(sf.lit("1"))
            )
            .withColumn(
                "advanced_message",
                sf.when(
                    (
                        (sf.col("value_checked") != sf.col("proposed_city"))
                        & ~(
                            sf.col("value_checked").rlike(r"(?i)^praha \d{1,2}$")
                            | sf.col("value_checked").rlike(r"(?i)^bratislava - pz\d{1,2}$")
                        )
                    ),
                    sf.concat(
                        sf.lit("City should be standardized. Choose one of the following cities: "),
                        sf.col("proposed_city"),
                    ),
                ).otherwise(sf.lit(""))
            )
            .withColumnRenamed("country_code", "country")
        )

        ctx["city_std_accuracy_detail"] = detail_df
        return detail_df
