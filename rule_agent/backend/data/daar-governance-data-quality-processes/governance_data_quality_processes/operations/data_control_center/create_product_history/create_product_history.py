from functools import reduce
import pyspark.sql.functions as f
from pyspark.sql.dataframe import DataFrame
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operation_configs.custom_config import (
    CustomOperationConfig,
)


class CreateProductHistoryOperation(BaseOperation):
    """ """

    def transform(self, ctx: TransformationContext) -> DataFrame:
        assert isinstance(self._config, CustomOperationConfig)
        dim_product_check_results_lifecycle = ctx["dim_product_check_results_lifecycle"].drop("process_run_id")
        f_product_details_l3 = ctx["f_product_details_l3"].drop("process_run_id")

        f_product_details_l3 = f_product_details_l3.select(
            "material_code",
            "sap_cluster",
            "plant_code",
            "sales_org_code",
            "country_code",
            "rule_code",
            "check_status",
            "value_checked",
        )
        f_product_details_l3 = f_product_details_l3.alias("b")

        df_checks_historical = dim_product_check_results_lifecycle.filter(f.col("check_status_end_date").isNotNull())
        df_checks_in_progress = dim_product_check_results_lifecycle.filter(
            f.col("check_status_end_date").isNull()
        ).alias("a")

        df_new_checks = f_product_details_l3.join(df_checks_in_progress, on=self._join_condition, how="leftanti").select(
            "b.*"
        )
        df_new_checks = (
            df_new_checks.withColumn("check_status_start_date", f.current_date())
            .withColumn("check_status_end_date", f.lit(None).cast("date"))
            .withColumn("checks_count", f.lit(1).cast("long"))
        )

        df_checks_common = df_checks_in_progress.join(f_product_details_l3, on=self._join_condition, how="inner")
        df_common_not_changed = df_checks_common.filter(
            (f.col(f"a.check_status") == f.col(f"b.check_status"))
            | (f.col(f"a.value_checked") == f.col(f"b.value_checked"))
        ).select("a.*")

        df_common_changed = df_checks_common.filter(
            (f.col(f"a.check_status") != f.col(f"b.check_status"))
            | (f.col(f"a.value_checked") != f.col(f"b.value_checked"))
        )
        df_common_changed_ended = df_common_changed.select("a.*")
        df_common_changed_ended = df_common_changed_ended.withColumn("check_status_end_date", f.current_date())

        df_common_changed_new = (
            df_common_changed.select(["b.*", "a.checks_count"])
            .withColumn("check_status_start_date", f.current_date())
            .withColumn("check_status_end_date", f.lit(None).cast("date"))
            .withColumn("checks_count", f.col("checks_count") + f.lit(1))
        )

        df_checks_ended = df_checks_in_progress.join(f_product_details_l3, on=self._join_condition, how="leftanti")
        df_checks_ended = df_checks_ended.withColumn("check_status_end_date", f.current_date())

        df_checks_history_combined = (
            df_checks_historical.unionByName(df_new_checks, allowMissingColumns=False)
            .unionByName(df_common_not_changed, allowMissingColumns=False)
            .unionByName(df_common_changed_ended, allowMissingColumns=False)
            .unionByName(df_common_changed_new, allowMissingColumns=False)
            .unionByName(df_checks_ended, allowMissingColumns=False)
        )
        return df_checks_history_combined

    @property
    def _join_condition(self):
        join_columns = ["rule_code", "material_code", "sap_cluster", "country_code", "plant_code", "sales_org_code"]
        join_conditions = [f.col(f"a.{col_name}").eqNullSafe(f"b.{col_name}") for col_name in join_columns]
        return reduce(lambda a, b: a & b, join_conditions)
