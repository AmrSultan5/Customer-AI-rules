
"""
GeoCoordsCityCheckOperation
---------------------------
Spark-native BaseOperation for city vs geocoordinates validation:

- Joins dm_customer_address with dm_customer_general.
- Attaches two extractors (dic / geonames) using already flattened fields provided by YAML.
- Country-specific normalization and transliteration (GR/CY/MD/SM/LI).
- Fuzzy city matching vs ext_ad/ext_ad2 using RapidFuzz WRatio.
- Geodesic distance (geopy) for both sources.
- check_status and advanced_check as in the original notebook.
- Returns only the final output columns for writing.

Inputs taken from the YAML context (exact names):
  ctx["select_customer_general"]
  ctx["select_customer_address"]
  ctx["add_extractor_fields_ext_dic_1"]
  ctx["add_extractor_fields_ext_dic_2"]
  ctx["select_country_validation"]
"""
from typing import Optional, List
import re
import unicodedata

from unidecode import unidecode

from pyspark.sql import DataFrame, Column
from pyspark.sql import functions as F
from pyspark.sql import types as T

from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from geopy.distance import geodesic
from rapidfuzz import fuzz


# Module-level UDF to avoid scoping issues
UNIDECODE_COL_UDF = F.udf(lambda s: unidecode(s or ""), T.StringType())


class GeoCoordsCityCheckOperation(BaseOperation):
    """
    Spark-native implementation of geocoordinates vs city validation.
    Logic preserved exactly as original; only implementation changed to Spark-native.
    """

    DISTANCE_THRESHOLD_M: int = 10_000
    CITY_MATCH_THRESHOLD: float = 60.0
    RULE_CODE: str = "RCACCU_22.5"

    CCH_COUNTRIES = [
        "AM", "AT", "BA", "BG", "CH", "CY", "CZ", "EE",
        "GB", "GR", "HR", "HU", "IE", "IT", "KV", "LI", "LT", "LV",
        "MD", "ME", "MK", "NG", "PL", "RO", "RS", "SI", "SK", "SM", "UA",
    ]

    LIECHTENSTEIN_POST_CODES = {
        "9485", "9486", "9487", "9488", "9489", "9490", "9491", "9492",
        "9493", "9494", "9495", "9496", "9497", "9498"
    }

    SAN_MARINO_POST_CODES = {
        "47890", "47891", "47892", "47893", "47894", "47895", "47896",
        "47897", "47898", "47899"
    }

    GREEK_DIGRAPHS = [
        (r'αι','ai'),(r'Αι','Ai'),(r'ΑΙ','AI'),
        (r'ει','ei'),(r'Ει','Ei'),(r'ΕΙ','EI'),
        (r'οι','oi'),(r'Οι','Oi'),(r'ΟΙ','OI'),
        (r'υι','yi'),(r'Υι','Yi'),(r'ΥΙ','YI'),
        (r'ου','ou'),(r'Ου','Ou'),(r'ΟΥ','OU'),
        (r'ευ','eu'),(r'Ευ','Eu'),(r'ΕΥ','EU'),
        (r'αυ','au'),(r'Αυ','Au'),(r'ΑΥ','AU'),
        (r'μπ','mp'),(r'Μπ','Mp'),(r'ΜΠ','MP'),
        (r'ντ','nt'),(r'Ντ','Nt'),(r'ΝΤ','NT'),
        (r'γκ','gk'),(r'Γκ','Gk'),(r'ΓΚ','GK'),
        (r'γγ','ng'),(r'Γγ','Ng'),(r'ΓΓ','NG'),
        (r'τσ','ts'),(r'Τσ','Ts'),(r'ΤΣ','TS'),
        (r'τζ','tz'),(r'Τζ','Tz'),(r'ΤΖ','TZ'),
    ]

    GREEK_LETTER_MAP = {
        'Α':'A','α':'a','Β':'V','β':'v','Γ':'G','γ':'g','Δ':'D','δ':'d','Ε':'E','ε':'e',
        'Ζ':'Z','ζ':'z','Η':'I','η':'i','Θ':'Th','θ':'th','Ι':'I','ι':'i','Κ':'K','κ':'k',
        'Λ':'L','λ':'l','Μ':'M','μ':'m','Ν':'N','ν':'n','Ξ':'X','ξ':'x','Ο':'O','ο':'o',
        'Π':'P','π':'p','Ρ':'R','ρ':'r','Σ':'S','σ':'s','ς':'s','Τ':'T','τ':'t','Υ':'Y','υ':'y',
        'Φ':'F','φ':'f','Χ':'Ch','χ':'ch','Ψ':'Ps','ψ':'ps','Ω':'O','ω':'o',
    }

    # ===== UDF logic preserved for fuzzy matching and geodesic distance =====
    @staticmethod
    def _valid_city_udf(cc: str, city: Optional[str], ext_ad: Optional[str], gr_city: Optional[str] = None) -> Optional[bool]:
        score = GeoCoordsCityCheckOperation._best_wratio(cc, city, ext_ad, gr_city)
        if score == 0.0:
            return None
        return score >= GeoCoordsCityCheckOperation.CITY_MATCH_THRESHOLD

    @staticmethod
    def _best_wratio(country_code: str, city: Optional[str], ext: Optional[str], gr_city: Optional[str] = None) -> float:
        if not city or not ext:
            return 0.0

        ext_norm = GeoCoordsCityCheckOperation._normalize(ext)

        if country_code in ("RO", "RS", "MD", "ME", "PL", "AT", "SK", "MK", "UA", "AM"):
            ext_all = GeoCoordsCityCheckOperation._unidecode_filter(ext_norm)
        elif country_code == "CY":
            ext_all = GeoCoordsCityCheckOperation._greek_trans(
                GeoCoordsCityCheckOperation._strip_greek_tonos(ext_norm)
            )
        elif country_code == "GR":
            ext_all = GeoCoordsCityCheckOperation._strip_greek_tonos(ext_norm) or ""
        else:
            ext_all = ext_norm

        tokens = GeoCoordsCityCheckOperation._split_tokens(country_code, ext_all)
        tokens.extend([p.strip() for p in re.findall(r"\((.*?)\)", ext_all) if p.strip()])

        city_up = city.upper()

        def wr(a: str, b: str) -> float:
            return float(fuzz.WRatio(a, b))

        highest = 0.0

        if country_code == "SM":
            parts = city_up.split(",")
            p1 = parts[0] if len(parts) >= 1 else ""
            p2 = parts[1] if len(parts) >= 2 else ""
            for tok in tokens:
                highest = max(highest, wr(p1, tok), wr(p2, tok))
            return highest

        def _has_nomos_prefix(txt: Optional[str]) -> bool:
            return bool(re.search(r"\bΝΟΜΟΣ\b", txt or "")) or bool(re.search(r"\bΝ\b\.?", txt or ""))

        if country_code == "GR" and gr_city and _has_nomos_prefix(gr_city):
            parts = city_up.split()
            if len(parts) >= 2:
                p1, p2 = parts[-2], parts[-1]
                for tok in tokens:
                    highest = max(highest, wr(p1, tok), wr(p2, tok))
                return highest

        for tok in tokens:
            highest = max(highest, wr(city_up, tok))

        return highest

    @staticmethod
    def _geo_dist_m(lat1, lon1, lat2, lon2) -> Optional[float]:
        try:
            lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
        except (TypeError, ValueError):
            return None
        return round(geodesic((lat1, lon1), (lat2, lon2)).meters, 2)

    @staticmethod
    def _unidecode_filter(s: Optional[str], pattern: str = r"[^A-Za-z0-9,\s]+") -> str:
        try:
            txt = unidecode(s or "")
            return re.sub(pattern, "", txt)
        except Exception:
            return s or ""

    @staticmethod
    def _strip_greek_tonos(text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
        text = text.replace(".", " ").replace("-", " ")
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize(text: Optional[str]) -> str:
        if not text:
            return ""
        return unicodedata.normalize("NFC", text).strip()

    @staticmethod
    def _split_tokens(country_code: str, s: str) -> List[str]:
        if not s:
            return []
        s_up = s.upper()
        if country_code in ("GR", "MD"):
            return [t for t in re.split(r"[, ]+", s_up) if t]
        elif country_code == "CY":
            return [t for t in re.split(r"[, \-]+", s_up) if t]
        else:
            return [t.strip('„“" ') for t in re.split(r"\s*[,/\\]\s*", s_up) if t]

    @staticmethod
    def _greek_trans(text: Optional[str]) -> str:
        t = text or ""
        for (pat, rep) in GeoCoordsCityCheckOperation.GREEK_DIGRAPHS:
            t = re.sub(pat, rep, t)
        return ''.join(GeoCoordsCityCheckOperation.GREEK_LETTER_MAP.get(ch, ch) for ch in t)

    @property
    def greek_tonos_stripped_from_city(self) -> Column:
        """
        Spark-native equivalent of _strip_greek_tonos(city):
        - Replace '.' and '-' with space,
        - Map precomposed accented Greek to base letters,
        - Collapse whitespace.
        """
        c = F.coalesce(F.col("city"), F.lit(""))
        c = F.regexp_replace(c, r"[.\-]", " ")
        mapping_multi = [
            ("Ά", "Α"), ("Έ", "Ε"), ("Ή", "Η"), ("Ί", "Ι"), ("Ό", "Ο"), ("Ύ", "Υ"), ("Ώ", "Ω"),
            ("Ϊ", "Ι"), ("Ϋ", "Υ"),
            ("ά", "α"), ("έ", "ε"), ("ή", "η"), ("ί", "ι"), ("ό", "ο"), ("ύ", "υ"), ("ώ", "ω"),
            ("ϊ", "ι"), ("ΐ", "ι"), ("ϋ", "υ"), ("ΰ", "υ"),
        ]
        for src, tgt in mapping_multi:
            c = F.regexp_replace(c, src, tgt)
        c = F.regexp_replace(c, r"\s+", " ")
        return F.trim(c)
    
    @property
    def greek_loc_normalized_from_n_city(self) -> Column:
        """
        Spark-native equivalent of _normalize_greek_loc(n_city):
        - Replace '-' and '.' with space,
        - Remove 'ΝΟΜΟΣ' and solitary 'Ν',
        - Collapse whitespace.
        """
        c = F.coalesce(F.col("n_city"), F.lit(""))
        c = F.regexp_replace(c, r"[.\-]", " ")
        c = F.regexp_replace(c, r"\bΝΟΜΟΣ\b", "")
        c = F.regexp_replace(c, r"\bΝ\b", "")
        c = F.regexp_replace(c, r"\s+", " ")
        return F.trim(c)
    
    @property
    def greek_transliterated_from_n_city(self) -> Column:
        """
        Spark-native equivalent of _greek_trans(n_city):
        - Apply digraph replacements in the same order,
        - Apply single-letter replacements (including multi-char targets like 'Θ'->'Th').
        """
        c = F.coalesce(F.col("n_city"), F.lit(""))
        for (pat, rep) in self.GREEK_DIGRAPHS:
            c = F.regexp_replace(c, pat, rep)
        for src, tgt in self.GREEK_LETTER_MAP.items():
            c = F.regexp_replace(c, src, tgt)
        return c
    @property
    def _customer_address_input_columns(self) -> List[str]:
        return [
            "customer_code",
            "city",
            "post_code",
            "latitude",
            "longitude",
            "country_code",
            "sap_cluster",
        ]
    @property
    def _customer_general_input_columns(self) -> List[str]:
        return [
            "customer_code",
            "central_order_block_code",
            "sap_cluster",
        ]

    # ===== Main transform (logic unchanged) =====
    def transform(self, ctx: TransformationContext) -> DataFrame:
        df_customer_general = ctx["read_dm_customer_general"]
        df_customer_address = ctx["read_dm_customer_address"]
        df_ext_dic_1 = ctx["add_extractor_fields_ext_dic_1"]
        df_ext_dic_2 = ctx["add_extractor_fields_ext_dic_2"]
        df_country_validation = ctx["select_country_validation"]

        df_customer_address = df_customer_address.select(*self._customer_address_input_columns).distinct()
        df_customer_general = df_customer_general.select(*self._customer_general_input_columns).distinct()

        base_df = (
            df_customer_address
            .alias("a")
            .join(df_customer_general.alias("g"), on=["customer_code", "sap_cluster"], how="inner")
            .filter(F.col("a.country_code").isin(*self.CCH_COUNTRIES))
            .select(
                F.col("a.customer_code").alias("customer_code"),
                F.col("g.central_order_block_code").alias("central_order_block_code"),
                F.col("a.latitude").alias("latitude"),
                F.col("a.longitude").alias("longitude"),
                F.col("a.city").alias("city"),
                F.col("a.country_code").alias("country_code"),
                F.col("a.post_code").alias("post_code"),
            )
            .dropDuplicates(["customer_code"])
        )

        df = (
            base_df
            .join(
                df_ext_dic_1.select(
                    "customer_code", "latitude", "longitude", "ext_ad", "ext_lat", "ext_long"
                ),
                on=["customer_code", "latitude", "longitude"],
                how="left"
            )
            .join(
                df_ext_dic_2.select(
                    "customer_code", "latitude", "longitude", "place_name", "state_name", "ext_lat2", "ext_long2"
                ),
                on=["customer_code", "latitude", "longitude"],
                how="left"
            )
            .withColumn(
                "ext_ad2",
                F.when(
                    F.col("place_name").isNotNull() & F.col("state_name").isNotNull(),
                    F.concat_ws(", ", F.col("place_name"), F.col("state_name"))
                )
                .when(F.col("place_name").isNotNull(), F.col("place_name"))
                .when(F.col("state_name").isNotNull(), F.col("state_name"))
                .otherwise(F.lit(None))
            )
        )

        df = df.withColumn(
            "n_country_code",
            F.when(
                (F.col("country_code") == "CH") & F.col("post_code").isin(*self.LIECHTENSTEIN_POST_CODES),
                F.lit("LI")
            )
            .when(
                (F.col("country_code") == "IT") & F.col("post_code").isin(*self.SAN_MARINO_POST_CODES),
                F.lit("SM")
            )
            .otherwise(F.col("country_code"))
        )

        df = df.withColumn("n_city", F.col("city"))
        df = df.withColumn(
            "n_city",
            F.when(F.col("n_country_code") == "GR", self.greek_tonos_stripped_from_city).otherwise(F.col("n_city"))
        )
        df = df.withColumn(
            "n_city",
            F.when(F.col("n_country_code") == "GR", self.greek_loc_normalized_from_n_city).otherwise(F.col("n_city"))
        )
        df = df.withColumn(
            "n_city",
            F.when(
                F.col("n_country_code") == "MD",
                F.regexp_replace(F.col("city"), r"^(S\s+|OR\s+|SAT\s+|SATUL\s+)", "")
            ).otherwise(F.col("n_city"))
        )
        df = df.withColumn(
            "n_city",
            F.when(
                F.col("n_country_code").isin("RO","RS","MD","ME","PL","AT","SK","MK","UA","AM"),
                UNIDECODE_COL_UDF(F.col("n_city"))
            ).otherwise(F.col("n_city"))
        )
        df = df.withColumn(
            "n_city2",
            F.when(F.col("n_country_code") == "GR", self.greek_transliterated_from_n_city)
             .otherwise(UNIDECODE_COL_UDF(F.col("n_city")))
        )

        # Casts for coordinates prior to distance UDFs
        df = (
            df.withColumn("latitude", F.col("latitude").cast(T.DoubleType()))
              .withColumn("longitude", F.col("longitude").cast(T.DoubleType()))
              .withColumn("ext_lat", F.col("ext_lat").cast(T.DoubleType()))
              .withColumn("ext_long", F.col("ext_long").cast(T.DoubleType()))
              .withColumn("ext_lat2", F.col("ext_lat2").cast(T.DoubleType()))
              .withColumn("ext_long2", F.col("ext_long2").cast(T.DoubleType()))
        )

        valid_city_udf = F.udf(self._valid_city_udf, T.BooleanType())
        df = df.withColumn(
            "valid_city",
            valid_city_udf(F.col("n_country_code"), F.col("n_city"), F.col("ext_ad"), F.col("city"))
        )
        df = df.withColumn(
            "valid_city2",
            F.when(
                (F.col("valid_city").isNull()) | (F.col("valid_city") == F.lit(False)),
                valid_city_udf(F.col("n_country_code"), F.col("n_city2"), F.col("ext_ad2"), F.col("city"))
            )
        )

        dist_udf = F.udf(self._geo_dist_m, T.DoubleType())
        df = df.withColumn(
            "distance_m",
            dist_udf(F.col("latitude"), F.col("longitude"), F.col("ext_lat"), F.col("ext_long"))
        )
        df = df.withColumn(
            "distance_m2",
            dist_udf(F.col("latitude"), F.col("longitude"), F.col("ext_lat2"), F.col("ext_long2"))
        )

        df = df.withColumn(
            "value_checked",
            F.concat_ws(
                " | ",
                F.concat_ws("_", F.col("n_city"), F.col("ext_ad")),
                F.concat_ws("_", F.col("n_city2"), F.col("ext_ad2"))
            )
        )

        df = df.join(df_country_validation, on="customer_code", how="left")

        df = df.withColumn(
            "check_status",
            F.when(F.col("country_validation") == "0", F.lit(""))
             .when(F.col("city").isNull() | (F.col("city") == ""), F.lit(""))
             .when(
                 F.col("latitude").isNull() | (F.col("longitude").isNull()),
                 F.lit("")
             )
             .when(
                 (F.col("ext_ad").isNull() | (F.col("ext_ad") == "")) &
                 (F.col("ext_ad2").isNull() | (F.col("ext_ad2") == "")),
                 F.lit("")
             )
             .when(
                 F.col("valid_city").isNull() & F.col("valid_city2").isNull(),
                 F.lit("0")
             )
             .when(
                 (F.col("valid_city") == True) &
                 F.col("distance_m").isNotNull() &
                 (F.col("distance_m") <= self.DISTANCE_THRESHOLD_M),
                 F.lit("1")
             )
             .when(
                 (F.col("valid_city2") == True) &
                 F.col("distance_m2").isNotNull() &
                 (F.col("distance_m2") <= self.DISTANCE_THRESHOLD_M),
                 F.lit("1")
             )
             .otherwise(F.lit("0"))
        )

        df = df.withColumn("rule_code", F.lit(self.RULE_CODE))

        return df.select(
            "customer_code",
            "country_code",
            "value_checked",
            "check_status",
            "rule_code",
        )
