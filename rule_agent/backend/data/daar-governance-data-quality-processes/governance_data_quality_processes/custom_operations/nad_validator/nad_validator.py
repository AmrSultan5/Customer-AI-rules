from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.functions import col, udf, length
from pyspark.sql.types import StringType, BooleanType, StructType, StructField
from typing import Optional, Dict, Set, Tuple, List
import re
import unicodedata
import pycountry
from cleanco import countrysources

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.nad_validator.nad_validator_config import (
    NADValidatorOperationConfig,
)

COUNTRY_CODE_ALIASES = {
    "ME": "BA",
}

CCH_COUNTRIES: List[str] = [
    "AM","AT","BA","BG","CH","CY","CZ","EE","GB","GR","HR","HU","IE","IT",
    "KV","LT","LV","MD","ME","MK","NG","PL","RO","RS","SI","SK","UA"
]

def _normalize_key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.category(c).startswith("C"))
    s = re.sub(r"[^A-Za-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

NAME_TO_CODE: Dict[str, str] = {}

for c in pycountry.countries:
    code = c.alpha_2
    names = {c.name}

    if hasattr(c, "official_name"):
        names.add(getattr(c, "official_name"))
    if hasattr(c, "common_name"):
        names.add(getattr(c, "common_name"))
    for n in names:
        if isinstance(n, str):
            NAME_TO_CODE[_normalize_key(n)] = code

ALIASES = {
    "czech republic": "CZ",
    "czechia": "CZ",
    "bosnia and herzegovina": "BA",
    "bosnia herzegovina": "BA",
    "bosnia  herzegovina": "BA",
    "bosnia / herzegovina": "BA",    
    "moldova": "MD",
    "moldova republic of": "MD",
    "republic of moldova": "MD",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "kosovo": "KV",
    "north macedonia": "MK",
    "macedonia": "MK",
    "macedonia the former yugoslav republic of": "MK",
    "republic of cyprus": "CY",
    "montenegro": "ME",
    "serbia": "RS",
    "switzerland": "CH",
    "schweiz": "CH",
    "suisse": "CH",
    "svizzera": "CH",
    "u k": "GB",
}

for k, v in ALIASES.items():
    NAME_TO_CODE[_normalize_key(k)] = v

COUNTRIES_DICT = {
    c.alpha_2: c.name for c in pycountry.countries if c.alpha_2 in CCH_COUNTRIES
}
COUNTRIES_DICT.update({
    "KV": "Kosovo",
    "CZ": "Czech Republic",
    "ME": "Bosnia  Herzegovina",  
    "BA": "Bosnia  Herzegovina",
    "MD": "Moldova"
})

COUNTRIES = dict(sorted(COUNTRIES_DICT.items()))


manual_suffixes: List[Tuple[str, str]] = [
    ('Armenia', 'adz'), ('Armenia', 'kp'), ('Armenia', 'spe'), ('Armenia', 'pbe'),
    ('Armenia', 'hk'), ('Armenia', 'bbe'), ('Armenia', 'le'), ('Armenia', 'lpe'),
    ('Armenia', 'hm'), ('Armenia', 'poak'),
    ('Kosovo', 'sh.p.k.'), ('Kosovo', 'sh.a.'), ('Kosovo', 'n.t.p.'), ('Kosovo', 'o.p.'),
    ('Cyprus', 'limited'), ('Cyprus', 'llp'), ('Cyprus', 'plc'), ('Cyprus', 'lp'),
    ('Cyprus', 'ltd'), ('Cyprus', 'sole'), ('Cyprus', 'sole trader'),
    ('Cyprus', 'partnership'), ('Cyprus', 'non-profit'), ('Cyprus', 'ngo'),
    ('Cyprus', 'llc'), ('Estonia', 'ou'), ('Estonia', 'as'), ('Estonia', 'uu'),
    ('Estonia', 'tu'), ('Estonia', 'mtu'), ('Ireland', 'ltd'), ('Ireland', 'dac'),
    ('Ireland', 'plc'), ('Ireland', 'clg'), ('Ireland', 'uc'), ('Ireland', 'llp'),
    ('Ireland', 'limited'), ('Ireland', 'ulc'),
    ('Italy', 'srls'), ('Italy', 'pa'), ('Italy', 'sdf'), ('Italy', 'aimp'),
    ('Italy', 'coop'), ('Italy', 'saa'),
    ('Poland', 'pw'), ('Poland', 'fuh'), ('Poland', 'przeds. zagr.'), ('Poland', 'pphu'),
    ('Poland', 'puh'), ('Poland', 'ph'), ('Poland', 'pph'), ('Poland', 'fhu'),
    ('Poland', 'fh'), ('Poland', 'ppuh'), ('Poland', 'phu'), ('Poland', 'sp. kom.'),
    ('Moldova', 'srl'), ('Moldova', 'sa'), ('Moldova', 'ii'), ('Moldova', 'gt'),
    ('Moldova', 'cooperativa de consum productie'), ('Moldova', 'is'),
    ('Moldova', 'im'), ('Moldova', 'sucursala intreprindere straina'),
    ('Moldova', 'sc'), ('Moldova', 'cp'), ('Moldova', 'ci'),
    ('United Kingdom', 'clg'), ('United Kingdom', 'ulc'),
    ("Bulgaria", "adsits"), ("Bulgaria", "eood"), ("Bulgaria", "ood"),
    ('Czech Republic', 'osvc'), ('Czech Republic', 'se'), ('Czech Republic', 'sce'),
    ('Czech Republic', 'druzstvo'), ('Czech Republic', 'statni podnik'),
    ('Czech Republic', 'zahranicni osoba'),
    ('Slovakia', 'druzstvo'), ('Slovakia', 'statny podnik'), ('Slovakia', 'zahranicna osoba'),
    ('Slovakia', 'szco'), ('Slovakia', 'se'), ('Slovakia', 'sce'),
    ('North Macedonia', 'ad'), ('North Macedonia', 'doo'), ('North Macedonia', 'dooel'),
    ('North Macedonia', 'tp'),
    ('Switzerland', 'klg'), ('Switzerland', 'snc'), ('Switzerland', 'ag'),
    ('Switzerland', 'gen'), ('Switzerland', 'scoop'),
    ('Greece', 'ae'),           # Ανώνυμη Εταιρεία — Société Anonyme / Public Ltd
    ('Greece', 'a.e.'),         # dotted variant
    ('Greece', 'epe'),          # Εταιρεία Περιορισμένης Ευθύνης — Limited Liability Company
    ('Greece', 'e.p.e.'),       # dotted variant
    ('Greece', 'oe'),           # Ομόρρυθμη Εταιρεία — General Partnership
    ('Greece', 'o.e.'),         # dotted variant
    ('Greece', 'ee'),           # Ετερόρρυθμη Εταιρεία — Limited Partnership
    ('Greece', 'e.e.'),         # dotted variant
    ('Greece', 'i.k.e.'),       # dotted variant of existing ike
    ('Greece', 'mepe'),         # Μονοπρόσωπη ΕΠΕ — Single-member LLC
    ('Greece', 'aeee'),         # Ανώνυμη Εταιρεία Ειδικού Σκοπού — Special Purpose AE
    ('Greece', 'aebe'),         # Ανώνυμη Εμπορική & Βιομηχανική Εταιρεία
    ('Greece', 'abee'),         # Ανώνυμη Βιομηχανική & Εμπορική Εταιρεία
    ('Greece', 'ate'),          # Ανώνυμη Τεχνική Εταιρεία
    ('Greece', 'koinsep'),      # Κοινωνική Συνεταιριστική Επιχείρηση — Social Cooperative
    ('Greece', 'koinsepe'),     # variant
    ('Greece', 'ike'),          # Ιδιωτική Κεφαλαιουχική Εταιρεία
    ('Greece', 'atomiki'),      # Ατομική Επιχείρηση
    ('Greece', 'syn pe'),       # Συνεταιρισμός Περιορισμένης Ευθύνης
    ('Greece', 'npdd'),         # Νομικό Πρόσωπο Δημοσίου Δικαίου
    ('Greece', 'npid'),         # Νομικό Πρόσωπο Ιδιωτικού Δικαίου
    ('Greece', 'amke'),         # Αστική Μη Κερδοσκοπική Εταιρεία
    ('San Marino', 'srls'), ('San Marino', 'pa'), ('San Marino', 'sdf'),
    ('San Marino', 'aimp'), ('San Marino', 'coop'), ('San Marino', 'saa'),
    ('San Marino', 's.a.p.a.'), ('San Marino', 's.a.s.'), ('San Marino', 's.c.r.l.'),
    ('San Marino', 's.n.c.'), ('San Marino', 's.p.a.'), ('San Marino', 's.r.l.'),
    ('San Marino', 's.s.'),
    ('Liechtenstein', 'ab'), ('Liechtenstein', 'g.m.b.h.'), ('Liechtenstein', 'gmbh'),
    ('Liechtenstein', 'sa'), ('Liechtenstein', 'sagl'), ('Liechtenstein', 'sarl'),
    ('Liechtenstein', 'klg'), ('Liechtenstein', 'snc'), ('Liechtenstein', 'ag'),
    ('Liechtenstein', 'gen'), ('Liechtenstein', 'scoop'),
    ("Croatia", "jdoo"), ("Croatia", "ugostiteljski obrt"), ("Croatia", "trgovacki obrt"),
    ("Serbia", "ado"), ("Serbia", "fondacija"), ("Serbia", "zaduzbina"),
    ("Serbia", "jp"), ("Serbia", "jatp"), ("Serbia", "jkp"), ("Serbia", "jksp"),
    ("Serbia", "jpr"), ("Serbia", "jvp"), ("Serbia", "kjp"), ("Serbia", "srk"),
    ("Serbia", "sru"), ("Serbia", "ssu"), ("Serbia", "stk"), ("Serbia", "su"),
    ("Serbia", "au"), ("Serbia", "dp"), ("Serbia", "pr"), ("Serbia", "str"),
    ("Serbia", "sur"), ("Serbia", "stur"), ("Serbia", "stzur"), ("Serbia", "szr"),
    ("Serbia", "zz"), ("Serbia", "epz"), ("Serbia", "ozz"), ("Serbia", "zem"),
    ("Serbia", "zadruga"), ("Serbia", "zemljoradnicka zadruga"),
    ("Slovenia", "zoo"), ("Slovenia", "zavod"),
    ("Bosnia  Herzegovina", "jp"), ("Bosnia  Herzegovina", "ju"),
    ("Bosnia  Herzegovina", "od"), ("Bosnia  Herzegovina", "pr"),
    ("Bosnia  Herzegovina", "sur"), ("Bosnia  Herzegovina", "str"),
    ("Bosnia  Herzegovina", "kd"), ("Bosnia  Herzegovina", "zu"),
    ("Bosnia  Herzegovina", "szr"), ("Ukraine", "pat"), ("Ukraine", "prat")
]

classification_sources: List[Tuple[str, str]] = countrysources()
classification_sources.extend(manual_suffixes)

def _name_to_code(name: str) -> Optional[str]:
    if not isinstance(name, str):
        return None
    key = _normalize_key(name)
    return NAME_TO_CODE.get(key)

def _clean_suffix_text(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

valid_classification_sources: List[Tuple[str, str]] = []
for country, suffix in classification_sources:
    if not (isinstance(country, str) and isinstance(suffix, str)):
        continue
    code = _name_to_code(country)
    if code and code in CCH_COUNTRIES:
        valid_classification_sources.append((code, _clean_suffix_text(suffix)))

_SOURCES_BY_CODE: Dict[str, Set[str]] = {}
for code, suf in valid_classification_sources:
    if not suf:
        continue
    s = suf.lower().strip()
    S = _SOURCES_BY_CODE.setdefault(code, set())
    S.add(s)
    compact = re.sub(r"[\s\.\-_/]+", "", s)
    if compact and compact != s:
        S.add(compact)


def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.category(c).startswith("C"))
    return text

def clean_nad_with_suffix(nad: Optional[str], country_code: Optional[str]):

    if not nad or not country_code:
        return {"cleaned_nad": nad, "found_suffix": None}

    code = str(country_code).upper().strip()
    code = COUNTRY_CODE_ALIASES.get(code, code)

    suffixes = _SOURCES_BY_CODE.get(code, set())
    if not suffixes:
        return {"cleaned_nad": nad, "found_suffix": None}

    nad_norm = normalize_text(nad)

    cleaned_text = re.sub(r"[^\w\s]", " ", nad_norm, flags=re.UNICODE)
    cleaned_text = re.sub(r"_+", " ", cleaned_text)
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()

    lowered = cleaned_text.lower()
    found = None

    for suffix in sorted(suffixes, key=len, reverse=True):
        if not suffix:
            continue

        pattern_normal = r"\b" + re.escape(suffix) + r"\b"
        if re.search(pattern_normal, lowered, flags=re.UNICODE | re.IGNORECASE):
            lowered = re.sub(pattern_normal, " ", lowered, flags=re.UNICODE | re.IGNORECASE)
            found = suffix
            break

        sep = r"[\s.\-_/]*"
        tolerant_core = sep.join(list(re.escape(suffix)))
        pattern_tolerant = r"(?<!\w)" + tolerant_core + r"(?!\w)"
        if re.search(pattern_tolerant, lowered, flags=re.UNICODE | re.IGNORECASE):
            lowered = re.sub(pattern_tolerant, " ", lowered, flags=re.UNICODE | re.IGNORECASE)
            found = suffix
            break

    nocorp = re.sub(r"\s+", " ", lowered).strip()

    m = re.match(r"^(?P<x>.+?)\s+\1$", nocorp, flags=re.UNICODE | re.IGNORECASE)
    if m:
        nocorp = m.group("x").strip()

    return {"cleaned_nad": nocorp, "found_suffix": found}



nad_cleaning_schema = StructType([
    StructField("cleaned_nad", StringType(), True),
    StructField("found_suffix", StringType(), True)
])

clean_nad_with_suffix_udf = udf(clean_nad_with_suffix, nad_cleaning_schema)

class NADValidatorOperation(BaseOperation):
    """
    Removes corporate indicators (suffixes) from NAD field based on country CODE.
    Adds:
      - <nad>_Cleaned
      - <nad>_FoundSuffix
      - <nad>_NoSuffixRemoved
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, NADValidatorOperationConfig)
        df = ctx[self._config.context_name]

        nad_col = self._config.params.column_nad
        country_col = self._config.params.column_country
        cleaned_col = f"{nad_col}_Cleaned"
        suffix_col = f"{nad_col}_FoundSuffix"
        flag_col = f"{nad_col}_NoSuffixRemoved"

        df = df.withColumn("nad_struct", clean_nad_with_suffix_udf(col(nad_col), col(country_col)))
        df = df.withColumn(cleaned_col, col("nad_struct.cleaned_nad"))
        df = df.withColumn(suffix_col, col("nad_struct.found_suffix"))


        df = df.withColumn(
            flag_col,
            F.when(
                (F.upper(F.regexp_replace(col(cleaned_col), r"\s+", "")) !=
                 F.upper(F.regexp_replace(col(nad_col), r"\s+", ""))) &
                (F.abs(F.length(col(cleaned_col)) - F.length(col(nad_col))) > 1),
                F.lit(False)
            ).otherwise(F.lit(True)).cast(BooleanType())
        )

        df = df.drop("nad_struct")
        return df
