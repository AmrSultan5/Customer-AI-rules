from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf
from pyspark.sql.types import StringType, ArrayType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
import re

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.product_mapping_tool.sales_unit_parse_config import (
    SalesUnitParseOperationConfig,
)

class SalesUnitParseOperation(BaseOperation):
    """Parses a product name text field using token-based pattern matching to extract the sales unit multiplier (e.g. '6x'), returning the unit and the cleaned product name."""

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, SalesUnitParseOperationConfig)
        df = ctx[self._config.context_name]
        column_to_transform = self._config.params.input_value
        col_name = self._config.params.output_col_name
        col_name_unit = col_name + '_sales_unit'

        # regex na liczbę i "x"
        TOKEN_REGEX = re.compile(
            r"""
            (?:^|\s|x)
            (?P<number>\d+)     # number
            (?=\s|x|$)          # followed by ws, x or eot
            |
            (?P<x>x)            # x
            (?=\s|\d|$)         # x can be followed by ws, digit or eot
            """,
            re.IGNORECASE | re.VERBOSE
        )

        def tokenize(text: str):
            tokens = []
            text_l = text.lower()
            for m in TOKEN_REGEX.finditer(text_l):
                kind = m.lastgroup
                start, end = m.start(kind), m.end(kind) 
                raw = m.group(kind)
                tokens.append((kind.upper(), raw, start, end))
            return tokens

        def parse_sales_unit(tokens, original_text: str):
            n = len(tokens)
                    
            # CASE 1: NUMBER + X  (ex. 3x, 12x)
            for i in range(n - 1):
                t1, t2 = tokens[i:i+2]
                if t1[0] == 'NUMBER' and t2[0] == 'X':
                    return f"{int(t1[1])}x", (t1[2], t2[3]), 'number+x'

            # CASE 2: X + NUMBER  (ex. x6, x 4)
            for i in range(n - 1):
                t1, t2 = tokens[i:i+2]
                if t1[0] == 'X' and t2[0] == 'NUMBER':
                    return f"{int(t2[1])}x", (t1[2], t2[3]), 'x+number'

            # CASE 3: one 'loose' integer in descrpition
            numbers = [t for t in tokens if t[0] == 'NUMBER']
            if len(numbers) == 1:
                last_number = numbers[-1]
                if last_number != 44: # not to catch monster lh44
                    return f"{int(last_number[1])}x", (last_number[2], last_number[3]), 'single_number'

            return '', None, ''

        def extract_sales_unit(text: str):
            if not text:
                return ('', text, '')
                    
            tokens = tokenize(text)
            unit, span, info = parse_sales_unit(tokens, text)

            cleaned = text
            if span:
                start, end = span
                cleaned = cleaned[:start] + cleaned[end:]
                cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()

            return unit, cleaned, info


        extract_sales_unit_udf = udf(extract_sales_unit, ArrayType(StringType()))

        result = df.withColumn("unit_and_text", extract_sales_unit_udf(col(column_to_transform))) \
                   .withColumn(col_name_unit, col("unit_and_text").getItem(0)) \
                   .withColumn('info', col("unit_and_text").getItem(2)) \
                   .withColumn(col_name, regexp_replace(col("unit_and_text").getItem(1), '\\s+', ' ')) \
                   .drop("unit_and_text")

        return result
