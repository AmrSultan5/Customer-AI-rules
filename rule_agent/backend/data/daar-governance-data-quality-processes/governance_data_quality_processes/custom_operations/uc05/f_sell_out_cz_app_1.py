from typing import Optional
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pyspark.sql.dataframe import DataFrame
from governance_data_quality_processes import *
from governance_data_quality_processes.custom_operation_configs.uc05.f_sell_out_cz_config import (
    FSelloutCZOperationConfig,
)
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from governance_data_quality_processes.utils.dataio import DataioUtils


class FSelloutCZOperation(BaseOperation):
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, FSelloutCZOperationConfig)

        sellout_repo = DataioUtils.get_repository(
            config=self._config.params.src_sellout, spark_session=self._spark_session
        )
        df_sellout = sellout_repo.read()
        print("PRINT: \n")
        print(self._config.params.src_calendar)
        calendar_repo = DataioUtils.get_repository(
            config=self._config.params.src_calendar, spark_session=self._spark_session
        )
        df_calendar = calendar_repo.read()

        sellout_curated_repo = DataioUtils.get_repository(
            config=self._config.params.src_sellout_curated, spark_session=self._spark_session
        )
        df_sellout_curated = sellout_curated_repo.read()

        product_map_repo = DataioUtils.get_repository(
            config=self._config.params.src_product_map, spark_session=self._spark_session
        )
        df_product_map = product_map_repo.read()

        cpl_mapping_repo = DataioUtils.get_repository(
            config=self._config.params.src_cpl_mapping, spark_session=self._spark_session
        )
        df_cpl_mapping = cpl_mapping_repo.read()

        df = None
        # df = df_sellout.join(df_date ...

        # df_sellout.createOrReplaceTempView("src_sellout_curated")

        df_calendar.withColumn("DateID", F.to_timestamp(F.col("DateID"), "yyyyMMdd").cast("date")).withColumn(
            "day_of_week", F.dayofweek("DateID")
        ).filter(F.col("day_of_week") == F.lit(2)).createOrReplaceTempView("calendar")

        df_sellout_curated.select("TAG", "MANUFACTURER").distinct().createOrReplaceTempView("sellout_curated")

        df_product_map.filter(F.col("country") == F.lit("cz")).select(
            "BAN", "Vendor_Item", "Vendor"
        ).distinct().withColumn("cnt", F.count(F.col("BAN")).over(Window.partitionBy("Vendor_Item", "Vendor"))).filter(
            "cnt = 1"
        ).createOrReplaceTempView(
            "product_map"
        )

        df_cpl_mapping.filter("country = 'cz'").createOrReplaceTempView("cpl_map")

        df = spark.sql(
            f"""
        SELECT mp.BAN AS ban_code
            , '530' AS company_code
            , 'cz' AS country
            , 'CZK' AS currency_code
            , dc.DateID AS date
            , CAST(NULL AS DOUBLE) AS m_sales_promo_uc
            , CAST(NULL AS DOUBLE) AS m_sales_promo_value
            , SUM(so.Total_Volume_Sales * 1000 / 5.678) AS m_sales_regular_uc
            , SUM(so.Total_Value_Sales * 1000) AS m_sales_regular_value
            , CASE WHEN soc.Manufacturer = 'COCA-COLA HBC' THEN 'CCH' ELSE soc.Manufacturer END AS manufacturer_name
            , CAST(NULL AS STRING) AS market_code
            , CAST(NULL AS STRING) AS market_name
            , CAST(NULL AS STRING) AS shop_code
            , CAST(NULL AS STRING) AS shop_name
            , so.VendorName AS vendor_name
            , CAST(1 AS INT) AS is_current_dataset
            , CAST(NULL AS STRING) AS area
        FROM sellout AS so
        LEFT JOIN calendar AS dc
            ON so.Year = dc.Year
            AND so.Week = dc.Week
        LEFT JOIN product_map AS mp
            ON ( so.Product_Name = mp.Vendor_Item
            AND LOWER(so.vendorName) = LOWER(mp.Vendor) )
        LEFT JOIN sellout_curated AS soc
            ON ( so.Product_ID = soc.TAG )

        GROUP BY mp.BAN
            , dc.DateID
            , CASE WHEN soc.Manufacturer = 'COCA-COLA HBC' THEN 'CCH' ELSE soc.Manufacturer END
            , so.VendorName
        """
        )

        return df
