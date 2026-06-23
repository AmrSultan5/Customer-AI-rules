from deep_translator import GoogleTranslator
from pyspark.sql.functions import lit, col, when, current_timestamp, regexp_replace, lower, udf
from pyspark.sql.types import StringType
from typing import Optional
from pyspark.sql.dataframe import DataFrame

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.text.google_translate_en_config import (
    GoogleTranslateEnOperationConfig,
)


class GoogleTranslateEnOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, GoogleTranslateEnOperationConfig)
        df = ctx[self._config.context_name]
        column_to_translate = self._config.params.input_value
        country_column = self._config.params.input_country_code

        def translate_text(text: str, lang_code: str) -> str:
            try:
                return GoogleTranslator(source=lang_code, target='en').translate(text)
            except Exception:
                return text
        
        translate_udf = udf(translate_text, StringType())

        return df.withColumn("input_value_translated", translate_udf(col(column_to_translate), col(country_column)))
