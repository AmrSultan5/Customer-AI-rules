from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf
from pyspark.sql.types import StringType, ArrayType
from typing import Optional
from pyspark.sql.dataframe import DataFrame
import re

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.product_characteristics.volume_extract_config import (
    VolumeExtractOperationConfig,
)

class VolumeExtractOperation(BaseOperation):
    """Extracts the volume or weight measurement (e.g. '330ml', '1.5l', '250g') from a product name text field using regex, returning both the extracted value and the cleaned product name."""

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, VolumeExtractOperationConfig)
        df = ctx[self._config.context_name]
        column_to_transform = self._config.params.input_value
        col_name = self._config.params.output_col_name
        col_name_vol = col_name + '_volume'

        def extract_volume(text: str) -> str:
    
            pattern_liters = r'(\d+)(\.\d+)?\s*l'
            pattern_liters_2 = r'(\d+)(,\d+)?\s*l'
            pattern_milliliters = r'(\d+)\s*ml'
            pattern_centyliters = r'(\d+)\s*cl'

            pattern_grams = r'(\d+)(\.\d+)?\s*g'
            pattern_grams_2 = r'(\d+)(,\d+)?\s*g'
            pattern_kilograms = r'(\d+)(\.\d+)?\s*kg'
            pattern_kilograms_2 = r'(\d+)(,\d+)?\s*kg'
    
            # Check for liters
            match_liters = re.search(pattern_liters or pattern_liters_2, text)
            # Check for milliliters
            match_milliliters = re.search(pattern_milliliters, text)
            # Check for centyliters
            match_centyliters = re.search(pattern_centyliters, text)

            # Check for kilograms
            match_kilograms = re.search(pattern_kilograms or pattern_kilograms_2, text)
            # Check for grams
            match_grams = re.search(pattern_grams or pattern_grams_2, text)

            if match_milliliters:
                integer_part = match_milliliters.group(1)
                if int(integer_part) == 1000:
                    volume = "1l"
                else:
                    if int(integer_part) > 1000:
                        volume = f"{int(integer_part) / 1000}l"
                    else:
                        volume = match_milliliters.group(0)  # Return as is
                modified_text = re.sub(pattern_milliliters, '', text).strip()
                return (volume, modified_text)
    
            if match_centyliters:
                integer_part = match_centyliters.group(1)
                cl_value = int(float(integer_part) * 10)
                volume = f"{cl_value}ml"
                modified_text = re.sub(pattern_centyliters, '', text).strip()
                return (volume, modified_text)

            if match_liters:
                integer_part = match_liters.group(1)
                decimal_part = match_liters.group(2) if match_liters.group(2) else ''
                if decimal_part or (int(integer_part) < 100):
                    volume = f"{integer_part}{decimal_part}l"
                else:  # Convert to milliliters
                    ml_value = int(float(integer_part) * 1000)
                    volume = f"{ml_value}ml"
                modified_text = re.sub(pattern_liters, '', text).strip()
                return (volume, modified_text)
    
            if match_grams:
                integer_part = match_grams.group(1)
                if int(integer_part) == 1000:
                    volume = "1kg"
                else:
                    if int(integer_part) > 1000:
                        volume = f"{int(integer_part) / 1000}g"
                    else:
                        volume = match_grams.group(0)  # Return as is
                modified_text = re.sub(pattern_grams, '', text).strip()
                return (volume, modified_text)
    
            if match_kilograms:
                integer_part = match_kilograms.group(1)
                decimal_part = match_kilograms.group(2) if match_kilograms.group(2) else ''
                if decimal_part or (int(integer_part) < 100):
                    volume = f"{integer_part}{decimal_part}kg"
                else:  # Convert to grams
                    g_value = int(float(integer_part) * 1000)
                    volume = f"{g_value}g"
                modified_text = re.sub(pattern_kilograms, '', text).strip()
                return (volume, modified_text)

            return ('', text)  

        # Register the UDF
        extract_volume_udf = udf(extract_volume,  ArrayType(StringType()))

        result = df.withColumn("volume_and_text", extract_volume_udf(col(column_to_transform))) \
                   .withColumn(col_name_vol, col("volume_and_text").getItem(0)) \
                   .withColumn(col_name, regexp_replace(col("volume_and_text").getItem(1), '\\s+', ' ')) \
                   .drop("volume_and_text")

        return result
