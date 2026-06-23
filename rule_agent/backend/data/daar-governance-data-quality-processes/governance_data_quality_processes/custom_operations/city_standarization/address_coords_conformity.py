from __future__ import annotations

from typing import Optional, Tuple, Union, List

import re
import unicodedata

from pyspark.sql.types import BooleanType
from pyspark.sql import DataFrame
from pyspark.sql import functions as sf
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    MapType,
    StringType,
    StructType,
)

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.city_standarization.address_coords_conformity_config import (
    AddressCoordsConformityOperationConfig,
)

from geopy.distance import geodesic
from fuzzywuzzy import fuzz
from unidecode import unidecode
from rapidfuzz.fuzz import ratio as simple_ratio
from Levenshtein import ratio as l_ratio
from postal.expand import expand_address


# ===========================================================
#  Constants
# ===========================================================

DISTANCE_THRESHOLD_M_EXACT = 50
DISTANCE_THRESHOLD_M_APPROX = 3000

LIECHTENSTEIN_POSTAL_CODES = {
    "9485", "9486", "9487", "9488", "9489", "9490", "9491", "9492", "9493",
    "9494", "9495", "9496", "9497", "9498",
}

SAN_MARINO_POSTAL_CODES = {
    "47890", "47891", "47892", "47893", "47894",
    "47895", "47896", "47897", "47898", "47899",
}

TRANSLITERATE_EXT_COUNTRIES = {"RO", "RS", "ME", "MD", "AT", "SK", "PL", "MK"}


# ===========================================================
#  Helpers
# ===========================================================

class TextEnricherBase:
    def __init__(self, input_filter: str = None, pattern: str = None):
        self.input_filter = input_filter
        self.pattern = pattern

    def _filter(self, text_str: str) -> str:
        text_str = str(text_str or "")
        if self.input_filter == "CUSTOM" and self.pattern:
            return re.sub(self.pattern, "", text_str)
        if self.input_filter == "LETTERS":
            return re.sub(r"[^a-zA-Z]", "", text_str)
        if self.input_filter == "STANDARD":
            return " ".join(text_str.split())
        return text_str

    def enrich(self, text_str: str) -> str:
        raise NotImplementedError


class TextTransliterator(TextEnricherBase):
    def enrich(self, text_str: str) -> str:
        try:
            transliterated_text = unidecode(text_str)
            return self._filter(transliterated_text)
        except Exception:
            return ""


def expand_with_libpostal(text: str) -> str:
    try:
        expansions = expand_address(text)
        return expansions[0] if expansions else text
    except Exception:
        return text


class AddressValidatorGeoLocator:
    def __init__(self, sim_threshold: int = 85) -> None:
        self.sim_threshold = sim_threshold
        self.transliterator = TextTransliterator(
            input_filter="CUSTOM",
            pattern=r"[^A-Za-z0-9\s,./\-:()'’]",
        )

        self.digraphs = [
            (r'αι', 'ai'), (r'Αι', 'Ai'), (r'ΑΙ', 'AI'),
            (r'ει', 'ei'), (r'Ει', 'Ei'), (r'ΕΙ', 'EI'),
            (r'οι', 'oi'), (r'Οι', 'Oi'), (r'ΟΙ', 'OI'),
            (r'υι', 'yi'), (r'Υι', 'Yi'), (r'ΥΙ', 'YI'),
            (r'ου', 'ou'), (r'Ου', 'Ou'), (r'ΟΥ', 'OU'),
            (r'ευ', 'eu'), (r'Ευ', 'Eu'), (r'ΕΥ', 'EU'),
            (r'αυ', 'au'), (r'Αυ', 'Au'), (r'ΑΥ', 'AU'),
            (r'μπ', 'mp'), (r'Μπ', 'Mp'), (r'ΜΠ', 'MP'),
            (r'ντ', 'nt'), (r'Ντ', 'Nt'), (r'ΝΤ', 'NT'),
            (r'γκ', 'gk'), (r'Γκ', 'Gk'), (r'ΓΚ', 'GK'),
            (r'γγ', 'ng'), (r'Γγ', 'Ng'), (r'ΓΓ', 'NG'),
            (r'τσ', 'ts'), (r'Τσ', 'Ts'), (r'ΤΣ', 'TS'),
            (r'τζ', 'tz'), (r'Τζ', 'Tz'), (r'ΤΖ', 'TZ'),
        ]
        self.letter_map = {
            'Α': 'A', 'α': 'a',
            'Β': 'V', 'β': 'v',
            'Γ': 'G', 'γ': 'g',
            'Δ': 'D', 'δ': 'd',
            'Ε': 'E', 'ε': 'e',
            'Ζ': 'Z', 'ζ': 'z',
            'Η': 'I', 'η': 'i',
            'Θ': 'Th', 'θ': 'th',
            'Ι': 'I', 'ι': 'i',
            'Κ': 'K', 'κ': 'k',
            'Λ': 'L', 'λ': 'l',
            'Μ': 'M', 'μ': 'm',
            'Ν': 'N', 'ν': 'n',
            'Ξ': 'X', 'ξ': 'x',
            'Ο': 'O', 'ο': 'o',
            'Π': 'P', 'π': 'p',
            'Ρ': 'R', 'ρ': 'r',
            'Σ': 'S', 'σ': 's', 'ς': 's',
            'Τ': 'T', 'τ': 't',
            'Υ': 'Y', 'υ': 'y',
            'Φ': 'F', 'φ': 'f',
            'Χ': 'Ch', 'χ': 'ch',
            'Ψ': 'Ps', 'ψ': 'ps',
            'Ω': 'O', 'ω': 'o',
        }

    @staticmethod
    def strip_greek_tonos(text: str) -> str:
        if text is None:
            return None
        text = "".join(
            c
            for c in unicodedata.normalize("NFD", text)
            if unicodedata.category(c) != "Mn"
        )
        text = text.replace(".", " ").replace("-", " ")
        return re.sub(r"\s+", " ", text).strip()

    def _greek_trans(self, text: str) -> str:
        for pattern, replacement in self.digraphs:
            text = re.sub(pattern, replacement, text)
        return ''.join(self.letter_map.get(char, char) for char in text)

    def _nor_text(self, text: str, use_libpostal: bool = False) -> str:
        if not text:
            return ""
        text = unicodedata.normalize("NFC", text)
        if use_libpostal:
            text = expand_with_libpostal(text)
        return text.strip()

    def extract_numbers_and_text(self, address: str) -> Tuple[List[str], str]:
        if not address:
            return [], ""

        address = self._nor_text(address)
        address = address.replace(".", " ").replace("-", " ").strip()

        first_numbers = [
            match.strip(" ,")
            for match in re.findall(
                r"(?:"  
                r"(?<!\w)[\s,]*"
                r"(?:[БB][РR]\.?\s*)?"
                r"(?:[A-Za-z\u0370-\u03FF\u0400-\u04FF\u0530-\u058F]{0,3})?"
                r"-?\d{1,5}"
                r"(?:[A-Za-z\u0370-\u03FF\u0400-\u04FF\u0530-\u058F]{1,3})?"
                r"(?:[-/][A-Za-z\u0370-\u03FF\u0400-\u04FF\u0530-\u058F]{1,3})?"
                r"(?:[-/]\d{1,5}[A-Za-z\u0370-\u03FF\u0400-\u04FF\u0530-\u058F]{0,3})?"
                r"[\s,]*(?!\w)"
                r"|(?<!\w)(?:BB|B B|NN|PN|N/N|FN|BR|БР|KB|КВ|KV|Б/Н|B/N|BŠ|B\.Š\.|B\.ŠT\.|BS|B S|B ST|SNC)(?!\w)"
                r")",
                address,
                flags=re.UNICODE | re.IGNORECASE,
            )
        ]

        # Remove numbers from text
        text = re.sub(
            r"(?:"  
            r"(?<!\w)[\s,]*"
            r"(?:[БB][РR]\.?\s*)?"
            r"(?:[A-Za-z\u0370-\u03FF\u0400-\u04FF\u0530-\u058F]{0,3})?"
            r"-?\d{1,5}"
            r"(?:[A-Za-z\u0370-\u03FF\u0400-\u04FF\u0530-\u058F]{1,3})?"
            r"(?:[-/][A-Za-z\u0370-\u03FF\u0400-\u04FF\u0530-\u058F]{1,3})?"
            r"(?:[-/]\d{1,5}[A-Za-z\u0370-\u03FF\u0400-\u04FF\u0530-\u058F]{0,3})?"
            r"[\s,]*(?!\w)"
            r"|(?<!\w)(?:BB|B B|NN|PN|N/N|FN|BR|БР|KB|КВ|KV|Б/Н|B/N|BŠ|B\.Š\.|B\.ŠT\.|BS|B S|B ST|SNC)(?!\w)"
            r")",
            "",
            address,
            flags=re.UNICODE | re.IGNORECASE,
        )

        text = re.sub(r"\s+", " ", text).strip()
        return first_numbers, text

    def compare_numbers(self, customer_numbers: list, external_numbers: list) -> bool:
        if not customer_numbers or not external_numbers:
            return False
        cset = set(str(num).upper() for num in customer_numbers)
        eset = set(str(num).upper() for num in external_numbers)
        return not cset.isdisjoint(eset)

    def _has_prefix_abbreviation_match(self, cust_text: str, ext_text: str) -> bool:
        cust_text = cust_text.upper().strip()
        ext_text = ext_text.upper().strip()
        wc = re.findall(r'\b\w+', cust_text)
        we = re.findall(r'\b\w+', ext_text)

        for w1 in wc:
            for w2 in we:
                if w1 == w2:
                    continue
                if w1 and w2.startswith(w1):
                    return True
                if w2 and w1.startswith(w2):
                    return True
        return False

    def _has_abbreviation_match(self, cust_text: str, ext_text: str) -> bool:
        def abbrev(text):
            words = re.findall(r'\b\w+', text.upper())
            return ''.join(w[0] for w in words if w)

        ac = abbrev(cust_text)
        ae = abbrev(ext_text)

        if min(len(ac), len(ae)) < 2:
            return False
        if l_ratio(ac, ae) >= 0.8:
            return True

        return (
            ac == ae
            or ac in ae.upper()
            or ae in ac.upper()
            or self._has_prefix_abbreviation_match(cust_text, ext_text)
        )

    def _is_partial_street_match(self, cust_text: str, ext_text: str, threshold: int = 85) -> bool:
        if not cust_text or not ext_text:
            return False

        cust_text = self._nor_text(cust_text)
        ext_text = self._nor_text(ext_text)

        if (
            fuzz.token_set_ratio(cust_text.upper(), ext_text.upper()) >= threshold
            or cust_text.upper() in ext_text.upper()
            or ext_text.upper() in cust_text.upper()
        ):
            return True

        if (
            fuzz.token_set_ratio(cust_text.upper(), ext_text.upper()) >= threshold
            and self._has_abbreviation_match(cust_text, ext_text)
        ):
            return True

        return False

    def _fuzzy_match_add(self, country_code: str, add: str, ext_ad: str) -> Tuple[float, bool, bool, bool]:
        highest_ratio = 0.0
        house_number_valid = False
        external_missing_number = False
        customer_missing_number = False

        if ext_ad is None or ext_ad == "" or ext_ad != ext_ad:
            return highest_ratio, house_number_valid, True, customer_missing_number

        if add is None or not add or add == "":
            return highest_ratio, house_number_valid, external_missing_number, True

        cust_numbers, cust_text = self.extract_numbers_and_text(add)
        customer_missing_number = not cust_numbers
        cust_text = self._nor_text(cust_text)

        ext_numbers_all, ext_text_all = self.extract_numbers_and_text(ext_ad)
        external_missing_number = not ext_numbers_all
        ext_text_all = self._nor_text(ext_text_all)

        # libpostal per comma chunk
        pre_split_ext = re.split(r"\s*,\s*", ext_text_all)
        pre_split_add = re.split(r"\s*,\s*", cust_text)

        expanded_parts_ext = [self._nor_text(p, use_libpostal=True) for p in pre_split_ext if p.strip()]
        expanded_parts_add = [self._nor_text(p, use_libpostal=True) for p in pre_split_add if p.strip()]

        ext_ad_all = ", ".join(expanded_parts_ext).upper()
        add_all = ", ".join(expanded_parts_add).upper()
        cust_text = add_all

        if country_code in ("GR", "CY"):
            ext_ad_all = self.strip_greek_tonos(ext_ad_all)

        if country_code in TRANSLITERATE_EXT_COUNTRIES:
            ext_ad_all = self.transliterator.enrich(ext_ad_all)

        if country_code == "CY":
            ext_ad_all = self._greek_trans(ext_ad_all)

        # split external by separators
        ext_ad_split = re.split(r"\s*[-,/\\]\s*", ext_ad_all.upper())
        ext_ads = []
        for item in ext_ad_split:
            item = item.strip('„“" ')
            if '(' in item and ')' in item:
                ext_ads.append(re.sub(r"\s*\(.*?\)", "", item).strip())
                ext_ads.extend([s.strip() for s in re.findall(r"\((.*?)\)", item)])
            else:
                ext_ads.append(item)

        for ad in ext_ads:
            ratio = 0.0
            ext_text = ad.strip()

            if not ext_text and not ext_numbers_all:
                continue

            current_house_match = self.compare_numbers(cust_numbers, ext_numbers_all)
            current_customer_missing = not cust_numbers
            current_external_missing = not ext_numbers_all

            if cust_numbers and ext_numbers_all and not current_house_match:
                current_customer_missing = False
                current_external_missing = False

            if ext_text:
                ext_text = self._nor_text(ext_text)
                simple_sim = simple_ratio(cust_text.upper(), ext_text.upper())

                if simple_sim < 60 and not (
                    self._is_partial_street_match(cust_text.upper(), ext_text.upper())
                    or self._has_abbreviation_match(cust_text, ext_text)
                ):
                    continue

                if self._is_partial_street_match(cust_text.upper(), ext_text.upper()):
                    ratio = 100.0
                elif self._has_abbreviation_match(cust_text, ext_text):
                    ratio = 90.0
                else:
                    ratio = float(fuzz.WRatio(cust_text.upper(), ext_text.upper()))

            update_match = False
            if ratio > highest_ratio:
                update_match = True
            elif ratio == highest_ratio and current_house_match and not house_number_valid:
                update_match = True

            if update_match:
                highest_ratio = ratio
                house_number_valid = current_house_match
                customer_missing_number = current_customer_missing
                external_missing_number = current_external_missing

        if highest_ratio == 0.0:
            fallback_ratio = fuzz.WRatio(cust_text.upper(), ext_ad.upper())
            if self._is_partial_street_match(
                self._nor_text(cust_text, use_libpostal=True).upper(),
                self._nor_text(ext_ad, use_libpostal=True).upper(),
            ) and fallback_ratio >= 80:
                highest_ratio = fallback_ratio
                house_number_valid = False
                customer_missing_number = not cust_numbers
                external_missing_number = not ext_numbers_all

        if highest_ratio >= self.sim_threshold and not house_number_valid and ext_numbers_all:
            if self.compare_numbers(cust_numbers, ext_numbers_all):
                house_number_valid = True
                external_missing_number = False
                customer_missing_number = False

        return highest_ratio, house_number_valid, external_missing_number, customer_missing_number

    def valid_address(self, country_code: str, add: str, ext_ad: str) -> Union[bool, str, None]:
        if ext_ad is None or ext_ad == "" or ext_ad != ext_ad:
            return "No Info from External Database"

        score, house_number_valid, external_missing_number, customer_missing_number = self._fuzzy_match_add(country_code, add, ext_ad)
        best_score = score
        best_result = (score, house_number_valid, external_missing_number, customer_missing_number)

        if (score is None or score < self.sim_threshold) and country_code.upper() == "GR":
            retry_threshold = 70
            parts = [p.strip() for chunk in ext_ad.split(",") for p in chunk.strip().split() if p.strip()]
            for part in parts:
                retry_score, hn_valid, ext_missing, cust_missing = self._fuzzy_match_add(country_code, add, part)
                if retry_score >= retry_threshold and retry_score > best_score:
                    best_score = retry_score
                    best_result = (retry_score, hn_valid, ext_missing, cust_missing)

            final_threshold = retry_threshold if best_score > score else self.sim_threshold
        else:
            final_threshold = self.sim_threshold

        score, house_number_valid, external_missing_number, customer_missing_number = best_result

        if best_score == 0.0:
            return None

        if best_score >= final_threshold:
            if house_number_valid:
                return True
            if external_missing_number and customer_missing_number:
                return "Valid Street, Missing Numbers in Both Addresses"
            if not customer_missing_number and not external_missing_number:
                return "Valid Street, but Different House Number"
            if external_missing_number:
                return "Valid Street, Missing Number in External Database"
            if customer_missing_number:
                return "Valid Street, Missing Number in Customer Address"
            return True

        return False


class DistanceMatching:
    def distance_match(self, latitude1: float, longitude1: float, latitude2: float, longitude2: float) -> float:
        try:
            latitude1 = float(latitude1)
            longitude1 = float(longitude1)
            latitude2 = float(latitude2)
            longitude2 = float(longitude2)
        except (TypeError, ValueError):
            return None

        if not (
            -90 <= latitude1 <= 90
            and -180 <= longitude1 <= 180
            and -90 <= latitude2 <= 90
            and -180 <= longitude2 <= 180
        ):
            return None

        return round(geodesic((latitude1, longitude1), (latitude2, longitude2)).meters, 2)


# ===========================================================
#  UDFs
# ===========================================================

_addgeovalid = AddressValidatorGeoLocator()
_transliterator = TextTransliterator(input_filter="CUSTOM", pattern=r"[^A-Za-z0-9\s,./\-:()'’]")
_distance = DistanceMatching()

tran_udf = sf.udf(lambda x: _transliterator.enrich(x), StringType())
tonos_udf = sf.udf(lambda x: _addgeovalid.strip_greek_tonos(x), StringType())
add_geo_udf = sf.udf(
    lambda cc, a, ext: str(_addgeovalid.valid_address(cc, a, ext)) if _addgeovalid.valid_address(cc, a, ext) is not None else "No Match",
    StringType(),
)
distance_udf = sf.udf(lambda a, b, c, d: _distance.distance_match(a, b, c, d), DoubleType())


# ===========================================================
#  Helpers
# ===========================================================

def _address_full_type(df: DataFrame) -> Optional[object]:
    """
    Return datatype of geocoords_extractor.address_full if present (MapType/StructType), else None.
    """
    try:
        ae_field = df.schema["geocoords_extractor"]
        if isinstance(ae_field.dataType, StructType) and "address_full" in ae_field.dataType.names:
            return ae_field.dataType["address_full"].dataType
    except Exception:
        pass
    return None


def _safe_address_full_expr(df: DataFrame, key: str) -> Optional[sf.Column]:
    """
    Build expression for geocoords_extractor.address_full.<key> regardless of MapType/StructType.
    Returns None if schema does not support it.
    """
    t = _address_full_type(df)
    if t is None:
        return None

    if isinstance(t, MapType):
        col_expr = sf.col("geocoords_extractor.address_full").getItem(key)
        return sf.when((col_expr.isNotNull()) & (col_expr != ""), col_expr).otherwise(None)

    if isinstance(t, StructType) and key in t.names:
        col_expr = sf.col(f"geocoords_extractor.address_full.{key}")
        return sf.when((col_expr.isNotNull()) & (col_expr != ""), col_expr).otherwise(None)

    return None


def _build_ext_ad(df: DataFrame) -> DataFrame:
    """
    Build ext_ad from geocoords_extractor fields (street_name/number/village/town),
    then (if still empty) fallback to concatenated address_full components.
    """
    df = df.withColumn("ext_ad", sf.lit("").cast(StringType()))

    df = df.withColumn(
        "ext_ad",
        sf.concat_ws(
            ", ",
            sf.when(
                (sf.col("geocoords_extractor.street_name").isNotNull()) & (sf.col("geocoords_extractor.street_name") != ""),
                sf.when(
                    (sf.col("geocoords_extractor.street_number").isNotNull()) & (sf.col("geocoords_extractor.street_number") != ""),
                    sf.concat(sf.col("geocoords_extractor.street_name"), sf.lit(" "), sf.col("geocoords_extractor.street_number")),
                ).otherwise(sf.col("geocoords_extractor.street_name")),
            ).otherwise(None),
            sf.when((sf.col("geocoords_extractor.village").isNotNull()) & (sf.col("geocoords_extractor.village") != ""), sf.col("geocoords_extractor.village")).otherwise(None),
            sf.when((sf.col("geocoords_extractor.town").isNotNull()) & (sf.col("geocoords_extractor.town") != ""), sf.col("geocoords_extractor.town")).otherwise(None),
        ),
    )

    component_fields = [
        "residential",
        "house_number",
        "hamlet",
        "industrial",
        "neighbourhood",
        "quarter",
        "suburb",
        "city_district",
        "city",
    ]

    address_parts = []
    for key in component_fields:
        expr = _safe_address_full_expr(df, key)
        if expr is not None:
            address_parts.append(expr)

    if isinstance(_address_full_type(df), MapType):
        address_parts.append(
            sf.when(
                (sf.col("geocoords_extractor.address_full").getItem("country_code") == "ng")
                & (sf.col("geocoords_extractor.address_full").getItem("county").isNotNull())
                & (sf.col("geocoords_extractor.address_full").getItem("county") != ""),
                sf.col("geocoords_extractor.address_full").getItem("county"),
            )
        )
        address_parts.append(
            sf.when(
                (sf.col("geocoords_extractor.address_full").getItem("country_code") == "ng")
                & (sf.col("geocoords_extractor.address_full").getItem("state").isNotNull())
                & (sf.col("geocoords_extractor.address_full").getItem("state") != ""),
                sf.col("geocoords_extractor.address_full").getItem("state"),
            )
        )

    if address_parts:
        df = df.withColumn(
            "ext_ad",
            sf.when(
                (sf.col("ext_ad").isNull()) | (sf.col("ext_ad") == ""),
                sf.concat_ws(", ", *address_parts),
            ).otherwise(sf.col("ext_ad")),
        )

    return df


def _normalize_customer_address(df: DataFrame) -> DataFrame:
    """
    Builds en_country_code and n_add (normalized street_house_number) with all country-specific patches.
    """
    df = df.withColumn(
        "en_country_code",
        sf.when(
            (sf.col("country_code") == "CH") & (sf.col("post_code").isin(list(LIECHTENSTEIN_POSTAL_CODES))),
            sf.lit("LI"),
        )
        .when(
            (sf.col("country_code") == "IT") & (sf.col("post_code").isin(list(SAN_MARINO_POSTAL_CODES))),
            sf.lit("SM"),
        )
        .otherwise(sf.col("country_code")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(sf.col("en_country_code") == "GR", tonos_udf(sf.col("street_house_number")))
        .otherwise(sf.col("street_house_number")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(sf.col("en_country_code").isin(list(TRANSLITERATE_EXT_COUNTRIES)), tran_udf(sf.col("n_add")))
        .otherwise(sf.col("n_add")),
    )

    df = df.withColumn("n_add", sf.when(sf.col("en_country_code") == "MD", sf.regexp_replace(sf.col("n_add"), r"(?i)^(S\.|S\s+)", "")).otherwise(sf.col("n_add")))

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "KV",
            sf.regexp_replace(
                sf.col("n_add"),
                r"\b(?:N/N|NN|BB|PN|FN|NR\.?|AP\.?|APT\.?|KT\.?|HYR\.?|HYRJA|FSH\.?|FSHATI|RR\.?|PR\.?|R\.?|OB\.?|LAGJJA|MAHALA|RRETH|\w{1,2}[.\-]?)\b",
                "",
            ),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "LT",
            sf.regexp_replace(sf.col("n_add"), r"\b(?:AUKŠTAS|AUK\.?|KAB\.?|KABINETAS|BUTAS)\b", ""),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "RO",
            sf.regexp_replace(sf.col("n_add"), r"(?i)\b(?:FN|F\.N\.?|F/N|NR\.?|BL\.?|BLOC|SC\.?|SCARA|APT\.?|AP\.?|APARTAMENT|ET\.?|ETAJ|CAM\.?|CAMERA)\b", ""),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "HR",
            sf.regexp_replace(sf.col("n_add"), r"(?i)\bB[.\s]*B\b", ""),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "ME",
            sf.regexp_replace(sf.col("n_add"), r"(?i)\b(?:BR\.?|B\.?R\.?|V\.|V[.\s]+|BROZA|TITA|JOSIPA|UL\.?)\b", ""),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "AM",
            sf.regexp_replace(sf.col("n_add"), r"(?i)\b(?:բն[․\.]?|բնակարան|հարկ[․\.]?|հ[․\.]?|տ[․\.]?|տուն|բակ|հատված|շուկա|մուտք[․\.]?|մուտք|բլ[․\.]?|բլոկ)\b", ""),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "UA",
            sf.regexp_replace(sf.col("n_add"), r"(?i)\b(?:КВ\.?|КВАРТИРА|АП\.?|АПАРТАМЕНТ|ПІД\.?|ПІД’ЇЗД|КІМН\.?|КІМНАТА|СЕКЦІЯ|КОРП\.?|КОРПУС|№|N)\b", ""),
        ).otherwise(sf.col("n_add")),
    )

    return df


# ===========================================================
#  Core logic
# ===========================================================

def run_address_coords_conformity(df: DataFrame) -> DataFrame:
    """
    Validates address similarity vs external dictionary address + checks geo distance.
    Expects input DF already enriched with `geocoords_extractor` and `postal_check_status` (boolean) or equivalent.
    """
    df = _build_ext_ad(df)

    df = _normalize_customer_address(df)

    df = df.withColumn(
        "valid_address",
        add_geo_udf(sf.col("en_country_code"), sf.col("n_add"), sf.col("ext_ad")),
    )

    df = df.withColumn("proposed_address", sf.upper(sf.col("ext_ad")))

    # External coordinates
    df = (
        df.withColumn("ext_lat", sf.col("geocoords_extractor")["latitude"].cast(DoubleType()))
          .withColumn("ext_long", sf.col("geocoords_extractor")["longitude"].cast(DoubleType()))
    )

    df = df.withColumn(
        "distance_m",
        distance_udf(sf.col("latitude"), sf.col("longitude"), sf.col("ext_lat"), sf.col("ext_long")),
    )

    # ---- check_status ----
    df = df.withColumn(
        "check_status",
        sf.when(sf.col("postal_check_status") == sf.lit(False), sf.lit(""))  # invalid postal -> blank
        .when(sf.col("valid_address").contains("No Info from External Database"), sf.lit(""))
        .when(sf.col("valid_address").contains("No Match"), sf.lit(""))
        .when(sf.col("valid_address") == sf.lit(False), sf.lit(""))
        .when(
            (sf.col("valid_address") == sf.lit(True))
            & (
                (sf.col("latitude").isNull()) | (sf.col("latitude") == 0.0)
                | (sf.col("longitude").isNull()) | (sf.col("longitude") == 0.0)
            ),
            sf.lit("0"),
        )
        .when(
            (sf.col("valid_address").contains("Valid Street, Missing Numbers in Both Addresses"))
            & (
                (sf.col("latitude").isNull()) | (sf.col("latitude") == 0.0)
                | (sf.col("longitude").isNull()) | (sf.col("longitude") == 0.0)
            ),
            sf.lit("0"),
        )
        .when(
            (sf.col("valid_address") == sf.lit(True))
            & (sf.col("distance_m") <= sf.lit(DISTANCE_THRESHOLD_M_EXACT)),
            sf.lit("1"),
        )
        .when(
            (sf.col("valid_address").contains("Valid Street, Missing Numbers in Both Addresses"))
            & (sf.col("distance_m") <= sf.lit(DISTANCE_THRESHOLD_M_EXACT)),
            sf.lit("1"),
        )
        .when(sf.col("distance_m") <= sf.lit(DISTANCE_THRESHOLD_M_APPROX), sf.lit("1"))
        .otherwise(sf.lit("0")),
    )

    # ---- advanced_message ----
    df = df.withColumn(
        "advanced_message",
        sf.when(sf.col("postal_check_status") == sf.lit(False), sf.lit("Invalid postal code"))
        .when(sf.col("valid_address").contains("No Info from External Database"), sf.lit("No external validation"))
        .when(sf.col("valid_address") == sf.lit(False), sf.lit("No external validation"))
        .when(sf.col("valid_address").contains("No Match"), sf.lit("No external validation"))
        .when(
            (sf.col("valid_address") == sf.lit(True))
            & (sf.col("distance_m") <= sf.lit(DISTANCE_THRESHOLD_M_EXACT)),
            sf.lit(""),
        )
        .when(
            (sf.col("valid_address").contains("Valid Street, Missing Numbers in Both Addresses"))
            & (sf.col("distance_m") <= sf.lit(DISTANCE_THRESHOLD_M_EXACT)),
            sf.lit(""),
        )
        .when(
            (sf.col("valid_address") == sf.lit(True))
            & (
                (sf.col("latitude").isNull()) | (sf.col("latitude") == 0.0)
                | (sf.col("longitude").isNull()) | (sf.col("longitude") == 0.0)
            ),
            sf.concat_ws(
                " ",
                sf.lit("Latitude:"), sf.col("ext_lat").cast(StringType()),
                sf.lit("Longitude:"), sf.col("ext_long").cast(StringType()),
                sf.lit("- Matching info:"), sf.col("valid_address"),
            ),
        )
        .when(sf.col("distance_m") <= sf.lit(DISTANCE_THRESHOLD_M_APPROX), sf.lit(""))
        .otherwise(
            sf.concat_ws(
                " ",
                sf.lit("Latitude:"), sf.col("ext_lat").cast(StringType()),
                sf.lit("Longitude:"), sf.col("ext_long").cast(StringType()),
                sf.lit("- Matching info:"), sf.col("valid_address"),
            )
        ),
    )

    df = df.drop(
        "en_country_code",
        "n_add",
        "ext_ad",
        "valid_address",
    )

    return df


# ===========================================================
#  Operation class
# ===========================================================

class AddressCoordsConformityOperation(BaseOperation):
    """
    Operation wrapper for run_address_coords_conformity.
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, AddressCoordsConformityOperationConfig)

        source_df: DataFrame = ctx[self._config.context_name]
        df = source_df

        params = getattr(self._config, "params", None)
        if params is not None:
            col_mapping = {
                "customer_code": getattr(params, "customer_code", "customer_code"),
                "country_code": getattr(params, "country_code", "country_code"),
                "street_house_number": getattr(params, "street_house_number", "street_house_number"),
                "city": getattr(params, "city", "city"),
                "post_code": getattr(params, "post_code", "post_code"),
                "latitude": getattr(params, "latitude", "latitude"),
                "longitude": getattr(params, "longitude", "longitude"),
                "geocoords_extractor": getattr(params, "geocoords_extractor", "geocoords_extractor"),
                "postal_check_status": getattr(params, "postal_check_status", "postal_check_status"),
            }

            df = (
                df.withColumn("customer_code", sf.col(col_mapping["customer_code"]))
                .withColumn("country_code", sf.col(col_mapping["country_code"]))
                .withColumn("street_house_number", sf.col(col_mapping["street_house_number"]))
                .withColumn("city", sf.col(col_mapping["city"]))
                .withColumn("post_code", sf.col(col_mapping["post_code"]))
                .withColumn("latitude", sf.col(col_mapping["latitude"]))
                .withColumn("longitude", sf.col(col_mapping["longitude"]))
                .withColumn("geocoords_extractor", sf.col(col_mapping["geocoords_extractor"]))
                .withColumn(
                    "postal_check_status",
                    sf.when(sf.col(col_mapping["postal_check_status"]) == sf.lit("1"), sf.lit(True))
                    .when(sf.col(col_mapping["postal_check_status"]) == sf.lit("0"), sf.lit(False))
                    .when(sf.col(col_mapping["postal_check_status"]) == sf.lit(1), sf.lit(True))
                    .when(sf.col(col_mapping["postal_check_status"]) == sf.lit(0), sf.lit(False))
                    .otherwise(sf.col(col_mapping["postal_check_status"]).cast(BooleanType()))
                )
            )

        return run_address_coords_conformity(df)
