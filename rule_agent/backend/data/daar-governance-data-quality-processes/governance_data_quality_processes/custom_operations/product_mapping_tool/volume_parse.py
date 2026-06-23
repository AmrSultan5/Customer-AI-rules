from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf
from pyspark.sql.types import StringType, ArrayType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
import re

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.product_mapping_tool.volume_parse_config import (
    VolumeParseOperationConfig,
)

class VolumeParseOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, VolumeParseOperationConfig)
        df = ctx[self._config.context_name]
        column_to_transform = self._config.params.input_value
        col_name = self._config.params.output_col_name
        col_name_vol = col_name + '_volume'

        UNIT_MAP = {
                    'ml': ('ml', 1),
                    'mls': ('ml', 1),
                    'mililitre': ('ml', 1),
                    'mililiter': ('ml', 1),
                    'mililiters': ('ml', 1),
                    'millilitre': ('ml', 1),
                    'milliliter': ('ml', 1),
                    'milliliters': ('ml', 1),
                    'l': ('ml', 1000),
                    'lt': ('ml', 1000),
                    'ltr': ('ml', 1000),
                    'ltrs': ('ml', 1000),
                    'liter': ('ml', 1000),
                    'liters': ('ml', 1000),
                    'litre': ('ml', 1000),
                    'litres': ('ml', 1000),
                    'cl': ('ml', 10),
                    'gram': ('g', 1),
                    'grams': ('g', 1),
                    'gr': ('g', 1),
                    'g': ('g', 1),
                    'kg': ('g', 1000),
                }

        TOKEN_REGEX = re.compile(
                    r"""
                    (?P<number>\d+(?:[.,]\d+)?)
                    |
                    (?P<unit>(?<![a-zA-Z])(mls?|mill?ilitre|mill?iliter|ltrs?|litres?|liters?|lt|l|cl|kg|grams?|gr|g)\b)
                    |
                    (?P<x>(?<=\d)x(?=\d)|\bx\b)
                    """,
                    re.IGNORECASE | re.VERBOSE
                )

        def tokenize(text: str):
            tokens = []
            text_l = text.lower()

            for m in TOKEN_REGEX.finditer(text_l):
                kind = m.lastgroup
                start, end = int(m.start()), int(m.end())
                raw = m.group()

                if kind == 'number':
                    value = float(raw.replace(',', '.'))
                    tokens.append(('NUMBER', value, start, end))

                elif kind == 'unit':
                    tokens.append(('UNIT', raw, start, end))

                elif kind == 'x':
                    tokens.append(('X', 'x', start, end))

            return tokens
            
        def format_volume(unit, value):
            def fmt(v):
                return str(int(v)) if v.is_integer() else str(v).rstrip('0').rstrip('.')

            if unit == 'ml':
                return f"{fmt(value)}ml"

            if unit == 'g':
                return f"{fmt(value)}g"

        def parse_volume(tokens, original_text: str):
            n = len(tokens)

            # NUMBER + X + NUMBER + UNIT   (ex. 6 x 330 ml)
            for i in range(n - 3):
                t1, t2, t3, t4 = tokens[i:i+4]
                if t1[0] == 'NUMBER' and t2[0] == 'X' and t3[0] == 'NUMBER' and t4[0] == 'UNIT':
                    unit, factor = UNIT_MAP.get(t4[1], (None, None))
                    if unit:
                        value = t3[1] * factor
                        span = (t3[2], t4[3])
                        return format_volume(unit, value), f"{int(t1[1])}x", 'number+x+number+unit', span

            # NUMBER + UNIT + X + NUMBER   (ex. 2l x 3)
            for i in range(n - 3):
                t1, t2, t3, t4 = tokens[i:i+4]
                if t1[0] == 'NUMBER' and t2[0] == 'UNIT' and t3[0] == 'X' and t4[0] == 'NUMBER':
                    unit, factor = UNIT_MAP.get(t2[1], (None, None))
                    if unit:
                        value = t1[1] * factor
                        span = (t1[2], t2[3])
                        return format_volume(unit, value), f"{int(t4[1])}x", 'number+unit+x+number', span
                    
            # NUMBER X NUMBER multipack
            for i in range(n - 2):
                t1, t2, t3 = tokens[i:i+3]
                if t1[0] == 'NUMBER' and t2[0] == 'X':
                    # t3 with UNIT case → ex. 6x1.75l
                    if t3[0] == 'NUMBER' and i+3 < n and tokens[i+3][0] == 'UNIT':
                        t4 = tokens[i+3]
                        unit, factor = UNIT_MAP.get(t4[1], (None, None))
                        if unit:
                            value = t3[1] * factor
                            span = (t1[2], t4[3])
                            return format_volume(unit, value), f"{int(t1[1])}x", 'number x number+unit', span

                    # t3 w/o unit case
                    elif t3[0] == 'NUMBER':
                        # standard multipack (t3 >=50) or reversed (t1 >=50)
                        if t3[1] >= 50:
                            # standard: t1 = pack, t3 = volume (ex. 6x330)
                            volume = format_volume('ml', t3[1])
                            sales_unit = f"{int(t1[1])}x"
                            span = (t3[2], t3[3])
                        elif t1[1] >= 50:
                            # reversed: t1 = volume, t3 = pack (ex. 330x6)
                            volume = format_volume('ml', t1[1])
                            sales_unit = f"{int(t3[1])}x"
                            span = (t1[2], t1[3])
                        else:
                            # lower numbers: t1 = volume in liters, t3 = pack
                            volume = format_volume('ml', t1[1]*1000)
                            sales_unit = f"{int(t3[1])}x"
                            span = (t1[2], t1[3])

                        return volume, sales_unit, 'number x number', span

            # NUMBER + UNIT
            for i in range(n - 1):
                t1, t2 = tokens[i:i+2]
                if t1[0] == 'NUMBER' and t2[0] == 'UNIT':
                    unit, factor = UNIT_MAP.get(t2[1], (None, None))
                    if unit:
                        value = t1[1] * factor
                        span = (t1[2], t2[3])
                        return format_volume(unit, value), '', 'number+unit', span

            # NUMBER + X → only pack, no volume (ex. 6x)
            for i in range(n - 1):
                t1, t2 = tokens[i:i+2]
                if t1[0] == 'NUMBER' and t2[0] == 'X':
                    pack = int(t1[1])
                    span = (t1[2], t2[3])
                    return '', f"{pack}x", 'pack_only', span
                
            # suffix heuristic
            suffix_numbers = list(re.finditer(r'\d+(?:[.,]\d+)?', original_text))
            print(suffix_numbers)

            if suffix_numbers:
                last_match = suffix_numbers[-1] # last number in text
                volume_str = last_match.group().replace(',', '.')
                volume = float(volume_str)
                span = (last_match.start(), last_match.end())

                if 0.1 <= volume <= 5:
                    return format_volume('ml', volume * 1000), '', 'number_suffix', span
                return format_volume('ml', volume), '', 'number_suffix', span

            return '', '', '', None
        
        def extract_volume(text: str):
            if not text:
                return ('', text, '')

            tokens = tokenize(text)
            volume, sales_unit, info, span = parse_volume(tokens, text)

            cleaned = text
            if span:
                start, end = span
                cleaned = cleaned[:start] + cleaned[end:]
                cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()

            return (volume, cleaned, info)

        # Register the UDF
        extract_volume_udf = udf(extract_volume,  ArrayType(StringType()))

        result = df.withColumn("volume_and_text", extract_volume_udf(col(column_to_transform))) \
                   .withColumn(col_name_vol, col("volume_and_text").getItem(0)) \
                   .withColumn('info', col("volume_and_text").getItem(2)) \
                   .withColumn(col_name, regexp_replace(col("volume_and_text").getItem(1), '\\s+', ' ')) \
                   .drop("volume_and_text")

        return result
