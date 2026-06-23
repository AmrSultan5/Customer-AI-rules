from typing import Optional

import re
import unicodedata

import numpy as np
import pandas as pd
from geopy.distance import geodesic
from fuzzywuzzy import fuzz
from unidecode import unidecode
from rapidfuzz.fuzz import ratio as simple_ratio
from Levenshtein import ratio as l_ratio
from postal.expand import expand_address

from pyspark.sql import DataFrame
from pyspark.sql import functions as sf
from pyspark.sql.types import (
    DoubleType,
    StringType,
    BooleanType,
    MapType,
    StructType,
)

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from datamesh_common.utils.base_utils import log_execution_time
from governance_data_quality_processes.custom_operation_configs.city_standarization.geocoords_address_conformity_config import (
    GeocoordsAddressConformityOperationConfig,
)

class TextEnricherBase:
    """
    Base class for text enrichment with various filtering options.
    """

    def __init__(self, input_filter: str = None, pattern: str = None):
        self.input_filter = input_filter
        self.pattern = pattern

    def _filter(self, text_str: str) -> str:
        text_str = str(text_str or "")

        if self.input_filter == "CUSTOM" and self.pattern:
            return re.sub(self.pattern, "", text_str)
        elif self.input_filter == "LETTERS":
            return re.sub(r"[^a-zA-Z]", "", text_str)
        elif self.input_filter == "STANDARD":
            return " ".join(text_str.split())
        else:
            return text_str

    def enrich(self, text_str: str) -> str:
        raise NotImplementedError("Subclasses should implement this method")


class TextTransliterator(TextEnricherBase):
    """
    Transliterate text to ASCII characters using the unidecode library.
    """

    def enrich(self, text_str: str) -> str:
        filtered_text = ""
        try:
            transliterated_text = unidecode(text_str)
            filtered_text = self._filter(transliterated_text)
        except Exception as e:
            print(f"Generic error: {e}")
        return filtered_text



def expand_with_libpostal(text: str) -> str:
    """
    Expand the given text using libpostal.
    """
    try:
        expansions = expand_address(text)
        return expansions[0] if expansions else text
    except Exception:
        return text



class AddressValidatorGeoLocator:
    """
    Validate addresses based on country_code, address and external address.
    """

    def __init__(self, sim_threshold: int = 85) -> None:
        self.sim_threshold = sim_threshold
        self.transliterator = TextTransliterator(
            input_filter="CUSTOM",
            pattern=r"[^A-Za-z0-9\s,./\-:()'’]",
        )

        self.digraphs = [
            (r"αι", "ai"), (r"Αι", "Ai"), (r"ΑΙ", "AI"),
            (r"ει", "ei"), (r"Ει", "Ei"), (r"ΕΙ", "EI"),
            (r"οι", "oi"), (r"Οι", "Oi"), (r"ΟΙ", "OI"),
            (r"υι", "yi"), (r"Υι", "Yi"), (r"ΥΙ", "YI"),
            (r"ου", "ou"), (r"Ου", "Ou"), (r"ΟΥ", "OU"),
            (r"ευ", "eu"), (r"Ευ", "Eu"), (r"ΕΥ", "EU"),
            (r"αυ", "au"), (r"Αυ", "Au"), (r"ΑΥ", "AU"),
            (r"μπ", "mp"), (r"Μπ", "Mp"), (r"ΜΠ", "MP"),
            (r"ντ", "nt"), (r"Ντ", "Nt"), (r"ΝΤ", "NT"),
            (r"γκ", "gk"), (r"Γκ", "Gk"), (r"ΓΚ", "GK"),
            (r"γγ", "ng"), (r"Γγ", "Ng"), (r"ΓΓ", "NG"),
            (r"τσ", "ts"), (r"Τσ", "Ts"), (r"ΤΣ", "TS"),
            (r"τζ", "tz"), (r"Τζ", "Tz"), (r"ΤΖ", "TZ"),
        ]

        self.letter_map = {
            "Α": "A", "α": "a",
            "Β": "V", "β": "v",
            "Γ": "G", "γ": "g",
            "Δ": "D", "δ": "d",
            "Ε": "E", "ε": "e",
            "Ζ": "Z", "ζ": "z",
            "Η": "I", "η": "i",
            "Θ": "Th", "θ": "th",
            "Ι": "I", "ι": "i",
            "Κ": "K", "κ": "k",
            "Λ": "L", "λ": "l",
            "Μ": "M", "μ": "m",
            "Ν": "N", "ν": "n",
            "Ξ": "X", "ξ": "x",
            "Ο": "O", "ο": "o",
            "Π": "P", "π": "p",
            "Ρ": "R", "ρ": "r",
            "Σ": "S", "σ": "s", "ς": "s",
            "Τ": "T", "τ": "t",
            "Υ": "Y", "υ": "y",
            "Φ": "F", "φ": "f",
            "Χ": "Ch", "χ": "ch",
            "Ψ": "Ps", "ψ": "ps",
            "Ω": "O", "ω": "o",
        }

    @staticmethod
    def strip_greek_tonos(text: str) -> Optional[str]:
        """
        Remove Greek tonos and unwanted characters like dots and dashes.
        """
        if text is None:
            return None

        # remove accents
        text = "".join(
            c
            for c in unicodedata.normalize("NFD", text)
            if unicodedata.category(c) != "Mn"
        )
        # replace "." and "-" with space
        text = text.replace(".", " ").replace("-", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _greek_trans(self, text: str) -> str:
        """
        Transliterate Greek characters using digraphs and letter mappings.
        """
        for pattern, replacement in self.digraphs:
            text = re.sub(pattern, replacement, text)

        return "".join(self.letter_map.get(char, char) for char in text)

    def _nor_text(self, text: str, use_libpostal: bool = False) -> str:
        if not text:
            return ""
        text = unicodedata.normalize("NFC", text)
        if use_libpostal:
            text = expand_with_libpostal(text)
        return text.strip()

    def extract_numbers_and_text(self, address: str):
        """
        Extract numbers from address and return cleaned street text.
        """
        if not address:
            return [], ""

        address = self._nor_text(address)
        address = address.replace(".", " ").replace("-", " ")
        address = address.strip()

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
                r"(?i)\b(?:BB|ББ|B\.B\.|B B|БB|NN|PN|N/N|FN|BR|БР|РR|KB|КВ|KV|Б/Н|B/N|BŠ|B\.Š\.|B\.ŠT\.|BS|B S|B ST|SNC)\b"
                r")",
                address,
                flags=re.UNICODE | re.IGNORECASE,
            )
        ]

        road_prefix_pattern = re.compile(
            r"^\s*("
            r"A|M|E|DN|D|S|EO|B|R|P|T|N|H|DK|"
            r"Α|Ε|ΕΟ|ΕΠ|"
            r"А|М|Е|ДН|Д|С|Р|П|Т|Н"
            r"\d{1,2}(Η|ΗΣ|ΑΣ|ΟΣ|ΟΥ|ΩΝ)\b"
            r"Δ\d{1,2}|"
            r"ΕΠ\d{1,2}"
            r")-?\d{1,3}([-/]\d{1,3})?\b",
            re.UNICODE,
        )

        match = road_prefix_pattern.match(address)
        road_prefix = match.group(0) if match else None

        numbers = [
            n for n in first_numbers
            if not (road_prefix and n == road_prefix)
        ]

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
            r"(?i)\b(?:BB|ББ|B\.B\.|B B|БB|NN|PN|N/N|FN|BR|БР|РR|KB|КВ|KV|Б/Н|B/N|BŠ|B\.Š\.|B\.ŠT\.|BS|B S|B ST|SNC)\b"
            r")",
            "",
            address,
            flags=re.UNICODE | re.IGNORECASE,
        )

        text = text.strip()
        if road_prefix and not text.startswith(road_prefix):
            text = f"{road_prefix} {text}".strip()

        text = re.sub(r"\s+", " ", text).strip()
        return numbers, text

    def compare_numbers(self, customer_numbers, external_numbers):
        if not customer_numbers or not external_numbers:
            return False
        customer_numbers_set = set(str(num).upper() for num in customer_numbers)
        external_numbers_set = set(str(num).upper() for num in external_numbers)
        return not customer_numbers_set.isdisjoint(external_numbers_set)

    def _has_prefix_abbreviation_match(self, cust_text: str, ext_text: str) -> bool:
        cust_text = cust_text.upper().strip()
        ext_text = ext_text.upper().strip()

        words_cust = re.findall(r"\b\w+", cust_text)
        words_ext = re.findall(r"\b\w+", ext_text)

        for w1 in words_cust:
            for w2 in words_ext:
                if w1 == w2:
                    continue
                if w1 and w2.startswith(w1):
                    return True
                if w2 and w1.startswith(w2):
                    return True
        return False

    def _has_abbreviation_match(self, cust_text: str, ext_text: str) -> bool:
        def abbrev(text):
            words = re.findall(r"\b\w+", text.upper())
            return "".join(w[0] for w in words if w)

        abbrev_cust = abbrev(cust_text)
        abbrev_ext = abbrev(ext_text)

        if min(len(abbrev_cust), len(abbrev_ext)) < 2:
            return False

        if l_ratio(abbrev_cust, abbrev_ext) >= 0.8:
            return True

        return (
            abbrev_cust == abbrev_ext
            or abbrev_cust in abbrev_ext.upper()
            or abbrev_ext in abbrev_cust.upper()
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

    def _fuzzy_match_add(self, country_code: str, add: str, ext_ad: str):
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

        pre_split_ext = re.split(r"\s*,\s*", ext_text_all)
        pre_split_add = re.split(r"\s*,\s*", cust_text)

        expanded_parts_ext = [
            self._nor_text(part, use_libpostal=True) for part in pre_split_ext if part.strip()
        ]
        expanded_parts_add = [
            self._nor_text(part, use_libpostal=True) for part in pre_split_add if part.strip()
        ]

        ext_ad_all = ", ".join(expanded_parts_ext)
        add_all = ", ".join(expanded_parts_add)
        cust_text = add_all

        ext_ad_all = ext_ad_all.upper()
        add_all = add_all.upper()

        if country_code in ("GR", "CY"):
            ext_ad_all = self.strip_greek_tonos(ext_ad_all) or ""

        if country_code in ("RO", "RS", "ME", "MD", "AT", "SK", "PL", "MK"):
            ext_ad_all = self.transliterator.enrich(ext_ad_all)

        if country_code == "CY":
            ext_ad_all = self._greek_trans(ext_ad_all)

        if country_code == "HR":
            for keyword in ["ULICA", "CESTA", "TRG"]:
                if keyword in ext_ad_all and keyword not in add_all:
                    ext_ad_all = ext_ad_all.replace(keyword, "")
            ext_ad_all = re.sub(r"\s+", " ", ext_ad_all).strip()

        if country_code == "HU":
            keywords = [
                "UTCA",
                "ÚT",
                "ÚTJA",
                "SOR",
                "KÖZ",
                "KÖRÚT",
                "TÉR",
                "SÉTÁNY",
                "PARK",
                "DŰLŐ",
                "LEJTŐ",
                "LIGET",
                "RAKPART",
                "ÁROK",
            ]
            for keyword in keywords:
                if keyword in ext_ad_all and keyword not in add_all:
                    ext_ad_all = ext_ad_all.replace(keyword, "")
            ext_ad_all = re.sub(r"\s+", " ", ext_ad_all).strip()

        if country_code == "ME":
            for keyword in ["ULICA", "TRG", "BULEVAR", "OBALA", "PUT", "ALEJA"]:
                if keyword in ext_ad_all and keyword not in add_all:
                    ext_ad_all = ext_ad_all.replace(keyword, "")
            ext_ad_all = re.sub(r"\s+", " ", ext_ad_all).strip()

        if country_code == "UA":
            ua_keywords = [
                "ВУЛИЦЯ", "ВУЛ", "ПРОСПЕКТ", "ПРОСП", "БУЛЬВАР", "БУЛ", "ШОСЕ", "НАБЕРЕЖНА",
                "ПЛОЩА", "ПРОВУЛОК", "ПРОВ", "ПРОЇЗД", "УЗВІЗ", "ДОРОГА", "МІСТ", "РАЙОН",
                "МАЙДАН", "АЛЕЯ", "БУДИНОК", "БУД.", "КВАРТИРА", "КВ.", "ОБ’ЇЗНА", "МІКРОРАЙОН",
                "СЕЛИЩЕ", "С.", "М.",
            ]
            for keyword in ua_keywords:
                if keyword in ext_ad_all and keyword not in add_all:
                    ext_ad_all = ext_ad_all.replace(keyword, "")
            ext_ad_all = re.sub(r"\s+", " ", ext_ad_all).strip()

        ext_ad_split = re.split(r"\s*[-,/\\]\s*", ext_ad_all.upper())

        ext_ads = []
        for item in ext_ad_split:
            item = item.strip('„“" ')
            if "(" in item and ")" in item:
                ext_ads.append(re.sub(r"\s*\(.*?\)", "", item).strip())
                ext_ads.extend([s.strip() for s in re.findall(r"\((.*?)\)", item)])
            else:
                ext_ads.append(item)

        for ad in ext_ads:
            ratio_val = 0.0
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
                    ratio_val = 100.0
                elif self._has_abbreviation_match(cust_text, ext_text):
                    ratio_val = 90.0
                else:
                    ratio_val = float(fuzz.WRatio(cust_text.upper(), ext_text.upper()))

            update_match = False

            if ratio_val > highest_ratio:
                update_match = True
            elif ratio_val == highest_ratio:
                if current_house_match and not house_number_valid:
                    update_match = True

            if update_match:
                highest_ratio = ratio_val
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

    def valid_address(self, country_code: str, add: str, ext_ad: str):
        if ext_ad is None or ext_ad == "" or ext_ad != ext_ad:
            return "No Info from External Database"

        score, house_number_valid, external_missing_number, customer_missing_number = self._fuzzy_match_add(
            country_code, add, ext_ad
        )
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

        final_threshold = self.sim_threshold
        if country_code.upper() == "GR" and best_score > score:
            final_threshold = retry_threshold

        score, house_number_valid, external_missing_number, customer_missing_number = best_result

        if best_score == 0.0:
            return None

        if best_score >= final_threshold:
            if house_number_valid:
                return True
            elif external_missing_number and customer_missing_number:
                return "Valid Street, Missing Numbers in Both Addresses"
            elif not customer_missing_number and not external_missing_number:
                return "Valid Street, but Different House Number"
            elif external_missing_number:
                return "Valid Street, Missing Number in External Database"
            elif customer_missing_number:
                return "Valid Street, Missing Number in Customer Address"
        else:
            return False

class DistanceMatching:
    def distance_match(
        self,
        latitude1: float,
        longitude1: float,
        latitude2: float,
        longitude2: float,
    ) -> Optional[float]:
        try:
            latitude1 = float(latitude1)
            longitude1 = float(longitude1)
            latitude2 = float(latitude2)
            longitude2 = float(longitude2)
        except (TypeError, ValueError):
            return None

        if not (-90 <= latitude1 <= 90 and -180 <= longitude1 <= 180 and
                -90 <= latitude2 <= 90 and -180 <= longitude2 <= 180):
            return None

        point1 = (latitude1, longitude1)
        point2 = (latitude2, longitude2)
        return round(geodesic(point1, point2).meters, 2)

class ValidatorAdvancedMessage:
    def evaluate_full_address_validity(
        self,
        valid_country: Optional[bool],
        valid_postal: Optional[bool],
        valid_city: Optional[bool],
        valid_address,
        valid_distance: bool,
    ) -> str:
        if not (valid_country and valid_postal and valid_city):
            parts = []
            if not valid_country:
                parts.append("Country")
            if not valid_postal:
                parts.append("Postal")
            if not valid_city:
                parts.append("City")
            core_status = f"Invalid Core Location Info: Missing {', '.join(parts)}"
        else:
            core_status = "Valid Core Location Info"

        if valid_address in (None, "No Match", False, "False"):
            return f"{core_status}, No Address Match"

        if valid_address is True or valid_address == "True":
            if valid_distance:
                return f"{core_status}, Fully Valid Address"
            else:
                return f"{core_status}, Valid Address, Distance Mismatch"

        if valid_address == "Valid Street, Missing Numbers in Both Addresses":
            if valid_distance:
                return f"{core_status}, Valid Street, Missing Numbers in Both Addresses"
            else:
                return f"{core_status}, Valid Street, Missing Numbers in Both Addresses, Distance Mismatch"

        if valid_address == "Valid Street, Missing Number in External Database":
            if valid_distance:
                return f"{core_status}, Valid Street, External Number Missing"
            else:
                return f"{core_status}, Valid Street, External Number Missing, Distance Mismatch"

        if valid_address == "Valid Street, Missing Number in Customer Address":
            if valid_distance:
                return f"{core_status}, Valid Street, Customer Number Missing"
            else:
                return f"{core_status}, Valid Street, Customer Number Missing, Distance Mismatch"

        if valid_address == "Valid Street, but Different House Number":
            if valid_distance:
                return f"{core_status}, Valid Street, Number Mismatch"
            else:
                return f"{core_status}, Valid Street, Number Mismatch, Distance Mismatch"

        return f"{core_status}, Unknown Address Validity Case"

addgeovalid = AddressValidatorGeoLocator()
transliterator = TextTransliterator(
    input_filter="CUSTOM",
    pattern=r"[^A-Za-z0-9\s,./\-:()'’]",
)
addadvmess = ValidatorAdvancedMessage()

tran_udf = sf.udf(lambda x: transliterator.enrich(x), StringType())
tonos_udf = sf.udf(lambda x: addgeovalid.strip_greek_tonos(x), StringType())
add_geo_udf = sf.udf(
    lambda x, y, w: str(addgeovalid.valid_address(x, y, w))
    if addgeovalid.valid_address(x, y, w) is not None
    else "No Match",
    StringType(),
)
distance_udf = sf.udf(
    lambda x, y, w, z: DistanceMatching().distance_match(x, y, w, z),
    DoubleType(),
)
add_advmess_udf = sf.udf(
    lambda x, y, w, z, k: addadvmess.evaluate_full_address_validity(x, y, w, z, k),
    StringType(),
)

DISTANCE_THRESHOLD_M = 50

liechtenstein_postal_codes = {
    "9485", "9486", "9487", "9488", "9489",
    "9490", "9491", "9492", "9493", "9494",
    "9495", "9496", "9497", "9498",
}

san_marino_postal_codes = {
    "47890", "47891", "47892", "47893", "47894",
    "47895", "47896", "47897", "47898", "47899",
}

def run_geocoords_address_check(df: DataFrame) -> DataFrame:

    df = (
        df
        .withColumn("ext_lat", sf.col("geocoords_extractor.latitude").cast(DoubleType()))
        .withColumn("ext_long", sf.col("geocoords_extractor.longitude").cast(DoubleType()))
        .withColumn("ext_ad", sf.lit("").cast(StringType()))
    )

    df = (
        df
        .withColumn(
            "valid_country",
            sf.when(sf.col("country_check_status") == "1", sf.lit(True).cast(BooleanType()))
             .when(sf.col("country_check_status") == "0", sf.lit(False).cast(BooleanType()))
             .otherwise(sf.lit(None).cast(BooleanType())),
        )
        .withColumn(
            "valid_postal",
            sf.when(sf.col("postal_check_status") == "1", sf.lit(True).cast(BooleanType()))
             .when(sf.col("postal_check_status") == "0", sf.lit(False).cast(BooleanType()))
             .otherwise(sf.lit(None).cast(BooleanType())),
        )
        .withColumn(
            "valid_city",
            sf.when(sf.col("city_check_status") == "1", sf.lit(True).cast(BooleanType()))
             .when(sf.col("city_check_status") == "0", sf.lit(False).cast(BooleanType()))
             .otherwise(sf.lit(None).cast(BooleanType())),
        )
        .drop("country_check_status", "postal_check_status", "city_check_status")
    )

    df = df.withColumn(
        "ext_ad",
        sf.concat_ws(
            ", ",
            sf.when(
                (sf.col("geocoords_extractor.street_name").isNotNull())
                & (sf.col("geocoords_extractor.street_name") != ""),
                sf.when(
                    (sf.col("geocoords_extractor.street_number").isNotNull())
                    & (sf.col("geocoords_extractor.street_number") != ""),
                    sf.concat(
                        sf.col("geocoords_extractor.street_name"),
                        sf.lit(" "),
                        sf.col("geocoords_extractor.street_number"),
                    ),
                ).otherwise(sf.col("geocoords_extractor.street_name")),
            ).otherwise(None),
            sf.when(
                (sf.col("geocoords_extractor.village").isNotNull())
                & (sf.col("geocoords_extractor.village") != ""),
                sf.col("geocoords_extractor.village"),
            ).otherwise(None),
            sf.when(
                (sf.col("geocoords_extractor.town").isNotNull())
                & (sf.col("geocoords_extractor.town") != ""),
                sf.col("geocoords_extractor.town"),
            ).otherwise(None),
        ),
    )

    def safe_component(colname: str):
        parts = colname.split(".")
        if len(parts) != 3:
            return None

        base, container, field = parts

        if base in df.columns:
            container_type = df.schema[base].dataType[container].dataType
            col_expr = None

            if isinstance(container_type, MapType):
                col_expr = sf.col(f"{base}.{container}")[field]
            elif isinstance(container_type, StructType) and field in container_type.names:
                col_expr = sf.col(f"{base}.{container}.{field}")
            else:
                return None

            return sf.when((col_expr.isNotNull()) & (col_expr != ""), col_expr).otherwise(None)
        return None

    component_fields = [
        "geocoords_extractor.address_full.residential",
        "geocoords_extractor.address_full.house_number",
        "geocoords_extractor.address_full.hamlet",
        "geocoords_extractor.address_full.industrial",
        "geocoords_extractor.address_full.neighbourhood",
        "geocoords_extractor.address_full.quarter",
        "geocoords_extractor.address_full.suburb",
        "geocoords_extractor.address_full.city_district",
        "geocoords_extractor.address_full.city",
    ]

    address_parts = [safe_component(col) for col in component_fields if safe_component(col) is not None]

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

    df = df.withColumn(
        "ext_ad",
        sf.when(
            (sf.col("ext_ad").isNull()) | (sf.col("ext_ad") == ""),
            sf.concat_ws(", ", *address_parts),
        ).otherwise(sf.col("ext_ad")),
    )

    df = df.withColumn(
        "en_country_code",
        sf.when(
            (sf.col("country_code") == "CH")
            & (sf.col("post_code").isin(liechtenstein_postal_codes)),
            sf.lit("LI"),
        )
        .when(
            (sf.col("country_code") == "IT")
            & (sf.col("post_code").isin(san_marino_postal_codes)),
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
        sf.when(
            sf.col("en_country_code").isin("RO", "RS", "ME", "MD", "AT", "SK", "PL", "MK"),
            tran_udf(sf.col("street_house_number")),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "MD",
            sf.regexp_replace(sf.col("n_add"), r"(?i)^(S\.|S\s+)", ""),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "MK",
            sf.regexp_replace(sf.col("n_add"), r"(?i)^\s*С\.?\s+", ""),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "KV",
            sf.regexp_replace(
                sf.col("n_add"),
                r"(?i)\b(?:N/N|NN|BB|PN|FN|NR\.?|AP\.?|APT\.?|KT\.?|HYR\.?|HYRJA|FSH\.?|FSHATI|RR\.?|PR\.?|R\.?|OB\.?|LAGJJA|MAHALA|RRETH)[\s\.,\-]*\w*\b",
                "",
            ),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "LT",
            sf.regexp_replace(
                sf.col("n_add"),
                r"(?i)\b(?:AUKŠTAS|AUK\.?|KAB\.?|KABINETAS|BUTAS)[\s\.,\-]*\w*\b",
                "",
            ),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "RO",
            sf.regexp_replace(
                sf.col("n_add"),
                r"(?i)\b(?:FN|F\.N\.?|F/N|NR\.?|BL\.?|BLOC|SC\.?|SCARA|APT\.?|AP\.?|APARTAMENT|ET\.?|ETAJ|CAM\.?|CAMERA)\b[\s\.:,\-]*\w*",
                "",
            ),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "HR",
            sf.regexp_replace(
                sf.col("n_add"),
                r"(?i)\bB[.\s]*B[\s\.,\-]*\w*\b",
                "",
            ),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "ME",
            sf.regexp_replace(
                sf.col("n_add"),
                r"(?i)\b(?:BR\.?|B\.?R\.?|V\.|V[.\s]+|BROZA|TITA|JOSIPA|UL\.?)[\s\.,\-]*\w*\b",
                "",
            ),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "AM",
            sf.regexp_replace(
                sf.col("n_add"),
                r"""(?ix)
                \b(
                    \d{1,3}ՐԴ\s*ՀԱՐԿ |
                    ՀԱՐԿ[\s․\.,\-]*\w{1,4} |
                    ԲՆԱԿԱՐԱՆ[\s․\.,\-]*\w{1,4} |
                    ԲՆ[․\.]?[\s․\.,\-]*\d{1,3} |
                    ՄՈՒՏՔ[\s․\.,\-]*\w{1,4} |
                    ԲԼՈԿ[\s․\.,\-]*\w{1,4} |
                    ՏՈՒՆ[\s․\.,\-]*\w{1,4} |
                    Տ[․\.]?[\s․\.,\-]*\d{1,3} |
                    Հ[․\.]?[\s․\.,\-]*\w{1,4}
                )\b
                """,
                "",
            ),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "n_add",
        sf.when(
            sf.col("en_country_code") == "UA",
            sf.regexp_replace(
                sf.col("n_add"),
                r"(?i)\b(?:БУД\.?|БУДИНОК|КВ\.?|КВАРТИРА|КВАРТ\.?|К\.?|АП\.?|АПАРТАМЕНТ|ПІД\.?|ПІД’ЇЗД|КІМН\.?|КІМНАТА|СЕКЦІЯ|КОРП\.?|КОРПУС|№|N)[\s\.,\-]*\w*\b",
                "",
            ),
        ).otherwise(sf.col("n_add")),
    )

    df = df.withColumn(
        "valid_address",
        add_geo_udf(sf.col("en_country_code"), sf.col("n_add"), sf.col("ext_ad")),
    )

    df = df.withColumn(
        "distance_m",
        distance_udf(
            sf.col("latitude"),
            sf.col("longitude"),
            sf.col("ext_lat"),
            sf.col("ext_long"),
        ),
    )

    df = df.withColumn(
        "valid_distance",
        sf.when(sf.col("distance_m") <= DISTANCE_THRESHOLD_M, sf.lit(True))
         .otherwise(sf.lit(False)),
    )

    df = df.withColumn(
        "checked_value",
        sf.concat_ws(", ", sf.col("latitude"), sf.col("longitude")),
    ).withColumn(
        "attribute",
        sf.concat_ws(", ", sf.lit("lat"), sf.lit("long")),
    )

    df = df.withColumn(
        "advanced_check",
        add_advmess_udf(
            sf.col("valid_country"),
            sf.col("valid_postal"),
            sf.col("valid_city"),
            sf.col("valid_address"),
            sf.col("valid_distance"),
        ),
    )

    df = df.withColumn("proposed_address", sf.col("ext_ad"))

    df = df.withColumn(
        "check_status",
        sf.when(sf.col("advanced_check").contains("Invalid Core Location Info"), "")
         .when((sf.col("ext_ad").isNull()) | (sf.col("ext_ad") == ""), "")
         .when(sf.col("valid_distance") == False, "")
         .when((sf.col("valid_address") == True) & (sf.col("valid_distance") == True), 1)
         .when(
             (sf.col("valid_address") == "Valid Street, Missing Numbers in Both Addresses")
             & (sf.col("valid_distance") == True),
             1,
         )
         .when(
             (sf.col("valid_address") == "Valid Street, Missing Number in External Database")
             & (sf.col("valid_distance") == True),
             1,
         )
         .when(
             (sf.col("valid_address") == "Valid Street, Missing Number in Customer Address")
             & (sf.col("valid_distance") == True),
             1,
         )
         .when(
             (sf.col("valid_address") == "Valid Street, but Different House Number")
             & (sf.col("valid_distance") == True),
             1,
         )
         .otherwise(0),
    )

    df = df.drop(
        "latitude",
        "longitude",
        "post_code",
        "geocoords_extractor",
        "ext_ad",
        "ext_lat",
        "ext_long",
        "valid_country",
        "valid_postal",
        "valid_city",
        "en_country_code",
        "n_add",
        "valid_address",
        "distance_m",
        "valid_distance",
    )

    return df


class GeocoordsAddressConformityOperation(BaseOperation):
    """
    Operation wrapping run_geocoords_address_check.
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, GeocoordsAddressConformityOperationConfig)

        source_df: DataFrame = ctx[self._config.context_name]

        params = getattr(self._config, "params", None)

        df = source_df

        if params is not None:
            col_mapping = {
                "customer_code": getattr(params, "customer_code", "customer_code"),
                "central_order_block_code": getattr(
                    params, "central_order_block_code", "central_order_block_code"
                ),
                "latitude": getattr(params, "latitude", "latitude"),
                "longitude": getattr(params, "longitude", "longitude"),
                "post_code": getattr(params, "post_code", "post_code"),
                "street_house_number": getattr(
                    params, "street_house_number", "street_house_number"
                ),
                "country_code": getattr(params, "country_code", "country_code"),
                "city": getattr(params, "city", "city"),
                "geocoords_extractor": getattr(
                    params, "geocoords_extractor", "geocoords_extractor"
                ),
                "country_check_status": getattr(
                    params, "country_check_status", "country_check_status"
                ),
                "postal_check_status": getattr(
                    params, "postal_check_status", "postal_check_status"
                ),
                "city_check_status": getattr(
                    params, "city_check_status", "city_check_status"
                ),
            }

            df = source_df.select(
                sf.col(col_mapping["customer_code"]).alias("customer_code"),
                sf.col(col_mapping["central_order_block_code"]).alias(
                    "central_order_block_code"
                ),
                sf.col(col_mapping["latitude"]).alias("latitude"),
                sf.col(col_mapping["longitude"]).alias("longitude"),
                sf.col(col_mapping["post_code"]).alias("post_code"),
                sf.col(col_mapping["street_house_number"]).alias("street_house_number"),
                sf.col(col_mapping["country_code"]).alias("country_code"),
                sf.col(col_mapping["city"]).alias("city"),
                sf.col(col_mapping["geocoords_extractor"]).alias("geocoords_extractor"),
                sf.col(col_mapping["country_check_status"]).alias(
                    "country_check_status"
                ),
                sf.col(col_mapping["postal_check_status"]).alias("postal_check_status"),
                sf.col(col_mapping["city_check_status"]).alias("city_check_status"),
            )

        result_df = run_geocoords_address_check(df)

        return result_df
