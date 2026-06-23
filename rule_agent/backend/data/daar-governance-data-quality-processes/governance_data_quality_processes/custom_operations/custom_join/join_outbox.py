from typing import Optional, List
from pyspark.sql import Column, DataFrame, functions as F

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from governance_data_quality_processes.custom_operation_configs.custom_join.join_outbox_config import JoinOutboxConfig, JoinOutboxOperationConfig
from datamesh_transformation.common.context import TransformationContext


class JoinOutboxOperation(BaseOperation):
    """
    Join multiple dataframes based on outbox condition
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, JoinOutboxOperationConfig)

        df = ctx[self._config.context_name].alias(self._config.context_name)
        for cfg in self._config.params:
            join_cond = self._get_join_condition(ctx, df, cfg)
            drop_cond = self._get_drop_condition(cfg)

            df = (df.hint(self._config.hint) if self._config.hint else df).join(
                ctx[cfg.other].hint(cfg.hint).alias(cfg.other)
                if cfg.hint
                else ctx[cfg.other].alias(cfg.other),
                on=join_cond,  # type: ignore
                how=cfg.how,
            )

            for c in drop_cond:
                df = df.drop(c)
        return df

    def _get_join_condition(self, ctx: TransformationContext, df: DataFrame, cfg: JoinOutboxConfig) -> List[Column]:
        """
        Create join condtition based on: latitude, longitude, city, country_code.
        """
        other_df = ctx[cfg.other]  # Pobranie drugiego DataFrame'a
        
        join_cond = [
            ((df["latitude"] < other_df["min_lat"]) | (df["latitude"] > other_df["max_lat"]) |
            (df["longitude"] < other_df["min_lon"]) | (df["longitude"] > other_df["max_lon"])) &
            (F.lower(F.split(df["city"], " ")[0]) == F.lower(other_df["bbox_city"])) &
            (df["country_code"] == other_df["bbox_country_code"])
        ]
        return join_cond

    def _get_drop_condition(self, cfg: JoinOutboxConfig) -> List[str]:
        return [
            col_left
            for col_left, col_right in cfg.columns.items()
            if col_right == col_left or not col_right
        ]
