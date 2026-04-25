from typing import Optional
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from pyspark.sql.dataframe import DataFrame
from governance_data_quality_processes import *

from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext



class FSelloutCZOperation(BaseOperation):
    """Aggregates Czech sell-out data by joining raw sales, calendar, product mapping, and manufacturer reference tables into a weekly sell-out fact table."""

    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        targets = self.prepare_targets(ctx)
        return None

    def prepare_targets(self, ctx: TransformationContext):
        src_sellout_targets = ctx["src_sellout"].createOrReplaceTempView("sellout")
        src_sellout_curated_targets = ctx["src_sellout_cuarted"].select("TAG", "MANUFACTURER").distinct().createOrReplaceTempView("sellout_curated")
        src_calendar_targets = ctx["src_calendar"].withColumn("DateID", F.to_timestamp(F.col("date_id"), "yyyyMMdd").cast("string")).withColumn("day_of_week", F.dayofweek("DateID")).filter(F.col("day_of_week") == F.lit(2)).createOrReplaceTempView("calendar")


        src_product_map_targets = ctx["src_product_map"].filter(F.col("country") == F.lit("cz")).select(
            "BAN", "Vendor_Item", "Vendor").distinct().withColumn("cnt", F.count(F.col("BAN")).over(Window.partitionBy("Vendor_Item", "Vendor"))).filter(
            "cnt = 1").createOrReplaceTempView("product_map")
        src_cpl_mapping_targets = ctx["src_cpl_mapping"].filter("country = 'cz'").createOrReplaceTempView("cpl_map")

        targets = spark.sql(
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
        targets.show()
        ctx["f_sell_out_cz_target"] = targets
        return targets

