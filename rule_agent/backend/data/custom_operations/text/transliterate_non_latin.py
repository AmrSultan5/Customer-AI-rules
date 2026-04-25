from pyspark.sql.dataframe import DataFrame
from pyspark.sql.functions import col, pandas_udf
from pyspark.sql.types import StringType
from typing import Optional, Dict
import pandas as pd
import re
import unicodedata
from unidecode import unidecode

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from governance_data_quality_processes.custom_operation_configs.text.transliterate_non_latin_config import (
    TransliterateNonLatinOperationConfig,
)

class TransliterateNonLatinOperation(BaseOperation):
    """Converts non-Latin characters (Greek, Cyrillic, and others) in specified columns to their Latin equivalents using language-specific transliteration rules."""

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, TransliterateNonLatinOperationConfig)
        df = ctx[self._config.context_name]
        columns_to_transliterate: Dict[str, Optional[str]] = self._config.params.columns

        greek_unicode_range = re.compile(r'[\u0370-\u03FF]')

        digraphs_map = {
            'αι': 'ai', 'Αι': 'Ai', 'ΑΙ': 'AI',
            'ει': 'ei', 'Ει': 'Ei', 'ΕΙ': 'EI',
            'οι': 'oi', 'Οι': 'Oi', 'ΟΙ': 'OI',
            'υι': 'yi', 'Υι': 'Yi', 'ΥΙ': 'YI',
            'ου': 'ou', 'Ου': 'Ou', 'ΟΥ': 'OU',
            'ευ': 'eu', 'Ευ': 'Eu', 'ΕΥ': 'EU',
            'αυ': 'au', 'Αυ': 'Au', 'ΑΥ': 'AU',
            'μπ': 'mp', 'Μπ': 'Mp', 'ΜΠ': 'MP',
            'ντ': 'nt', 'Ντ': 'Nt', 'ΝΤ': 'NT',
            'γκ': 'gk', 'Γκ': 'Gk', 'ΓΚ': 'GK',
            'γγ': 'ng', 'Γγ': 'Ng', 'ΓΓ': 'NG',
            'τσ': 'ts', 'Τσ': 'Ts', 'ΤΣ': 'TS',
            'τζ': 'tz', 'Τζ': 'Tz', 'ΤΖ': 'TZ',
        }

        digraph_pattern = re.compile('|'.join(re.escape(k) for k in digraphs_map.keys()))

        letter_map = {
            'Α': 'A', 'α': 'a', 'Β': 'V', 'β': 'v',
            'Γ': 'G', 'γ': 'g', 'Δ': 'D', 'δ': 'd',
            'Ε': 'E', 'ε': 'e', 'Ζ': 'Z', 'ζ': 'z',
            'Η': 'I', 'η': 'i', 'Θ': 'Th', 'θ': 'th',
            'Ι': 'I', 'ι': 'i', 'Κ': 'K', 'κ': 'k',
            'Λ': 'L', 'λ': 'l', 'Μ': 'M', 'μ': 'm',
            'Ν': 'N', 'ν': 'n', 'Ξ': 'X', 'ξ': 'x',
            'Ο': 'O', 'ο': 'o', 'Π': 'P', 'π': 'p',
            'Ρ': 'R', 'ρ': 'r', 'Σ': 'S', 'σ': 's', 'ς': 's',
            'Τ': 'T', 'τ': 't', 'Υ': 'Y', 'υ': 'y',
            'Φ': 'F', 'φ': 'f', 'Χ': 'Ch', 'χ': 'ch',
            'Ψ': 'Ps', 'ψ': 'ps', 'Ω': 'O', 'ω': 'o',
        }

        def remove_greek_diacritics(text: str) -> str:
            normalized = unicodedata.normalize("NFKD", text)
            return ''.join(c for c in normalized if unicodedata.category(c) != "Mn")

        def transliterate_text(text: Optional[str]) -> str:
            if not text or not isinstance(text, str):
                return text
            if not greek_unicode_range.search(text):
                return unidecode(text)

            text = remove_greek_diacritics(text)
            text = digraph_pattern.sub(lambda m: digraphs_map[m.group(0)], text)
            return ''.join(letter_map.get(ch, ch) for ch in text)

        @pandas_udf(StringType())
        def transliterate_udf(col_series: pd.Series) -> pd.Series:
            return col_series.apply(transliterate_text)

        for source_col, suffix_or_name in columns_to_transliterate.items():
            target_col = suffix_or_name or f"{source_col}_translit"
            df = df.withColumn(target_col, transliterate_udf(col(source_col)))

        return df
