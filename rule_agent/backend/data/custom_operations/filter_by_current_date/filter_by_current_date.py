from pyspark.sql import functions as f
from pyspark.sql.dataframe import DataFrame
from pyspark.sql.window import Window

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig

class FilterByCurrentDateOperation(BaseOperation):
    """Filters pricing condition records to retain only those valid after the current date, keeping the latest active condition per material."""

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> DataFrame:
        assert isinstance(self._config, CustomOperationConfig)
        df_kotp499 = ctx["kotp499"]
        df_kotp499 = df_kotp499.filter(f.col("datbi") > f.current_timestamp())
        deduplication_window = Window.partitionBy("rmatp").orderBy(f.col("datbi").desc())
        df_knumh = df_kotp499.withColumn("rmatp_rank", f.row_number().over(deduplication_window)).filter(f.col("rmatp_rank") == 1).select("rmatp", "knumh").distinct()
        df_kotp499 = df_kotp499.join(df_knumh, on=["rmatp", "knumh"], how="left_semi")
        return df_kotp499
        