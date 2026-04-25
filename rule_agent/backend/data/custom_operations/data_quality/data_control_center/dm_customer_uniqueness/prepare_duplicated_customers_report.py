"""Duplicated Customers Report Preparation Module.

This module provides functionality for preparing and enriching the final report
of duplicated customers identified during the customer uniqueness analysis in the
Data Control Center. The module transforms identified duplicate pairs into a
flattened structure suitable for reporting, applies business rules based on order
block codes to filter valid duplicates, and enriches the report with additional
customer attributes from the base table.

The module handles the transformation of duplicate pairs into individual customer
records, calculates aggregate similarity scores, and joins comprehensive customer
attributes to create a complete data quality check report.
"""

from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operations.base import BaseOperation
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as f


class PrepareDuplicatedCustomersReportOperation(BaseOperation):
    """Operation for preparing the final duplicated customers report for data quality checks."""

    @staticmethod
    def _order_block_code_based_filtering(df_duplicated_customers: DataFrame) -> DataFrame:
        """
        Apply order block code based filtering to duplicated customers.

        This method implements complex filtering rules based on order block codes:
        1. Order Block 'M' Rules - Both blocks must be 'M' or both must not be 'M'
        2. Exclude 'S1' - Neither order block can be 'S1'
        3. Order Block 'U' and 'G' Rules - Special handling with restricted lists
        4. Order Block 'E' Rules - Special handling with restricted lists

        Args:
            df_duplicated_customers: DataFrame with original_order_block_code and duplicate_order_block_code columns

        Returns:
            Filtered DataFrame
        """
        original_block = f.col("original_order_block_code")
        duplicate_block = f.col("duplicate_order_block_code")

        # Condition 1: Order Block 'M' Rules
        # Both must be 'M' OR both must not be 'M'
        condition_m = ((original_block == "M") & (duplicate_block == "M")) | (
            (original_block != "M") & (duplicate_block != "M")
        )

        # Condition 2: Exclude 'S1' for both order blocks
        # Neither order block can be 'S1'
        condition_s1 = (original_block != "S1") & (duplicate_block != "S1")

        # Condition 3: Order Block 'U' and 'G' Rules
        # Special handling when either block is 'U' or 'G'
        restricted_list_ug = ["E", "G", "M", "U", "S1"]
        condition_ug = (
            # If original_block is U or G, duplicate_block must not be in restricted list
            (original_block.isin(["U", "G"]) & ~duplicate_block.isin(restricted_list_ug))
            # If duplicate_block is U or G, original_block must not be in restricted list
            | (duplicate_block.isin(["U", "G"]) & ~original_block.isin(restricted_list_ug))
            # If neither is U nor G, both can be any other value
            | (~original_block.isin(["U", "G"]) & ~duplicate_block.isin(["U", "G"]))
        )

        # Condition 4: Order Block 'E' Rules
        # Special handling when either block is 'E'
        restricted_list_e = ["E", "G", "U", "S1"]
        condition_e = (
            # If original_block is E, duplicate_block must not be in restricted list
            ((original_block == "E") & ~duplicate_block.isin(restricted_list_e))
            # If duplicate_block is E, original_block must not be in restricted list
            | ((duplicate_block == "E") & ~original_block.isin(restricted_list_e))
            # If neither is E, both can be any other value
            | ((original_block != "E") & (duplicate_block != "E"))
        )

        # Combine all conditions
        combined_filter = condition_m & condition_s1 & condition_ug & condition_e

        return df_duplicated_customers.filter(combined_filter)

    @staticmethod
    def _flatten_duplicated_customers_table(df_duplicated_customers: DataFrame) -> DataFrame:
        """Flatten duplicate pairs into individual customer records.

        Transforms the duplicate pairs structure (original vs duplicate) into individual
        customer records where each customer in a duplicate pair becomes a separate row.

        Args:
            df_duplicated_customers: DataFrame containing duplicate pairs with both
                                    original and duplicate customer attributes

        Returns:
            DataFrame with one row per customer in each duplicate pair, unified by
            common column names
        """
        df_original_customer = df_duplicated_customers.select(
            f.col("original_customer_code").alias("customer_code"),
            f.col("original_country_code").alias("country_code"),
            f.col("original_address").alias("address"),
            f.col("original_legal_entity").alias("legal_entity"),
            (f.col("duplicate_sub_trade_channel_code") == f.col("original_sub_trade_channel_code")).alias(
                "is_same_sub_trade_channel"
            ),
            f.col("original_trade_channel_code").alias("_pk_trade_channel_code"),
            f.col("original_city").alias("_pk_city"),
            "w_sim_score",
        )
        df_duplicated_customer = df_duplicated_customers.select(
            f.col("duplicate_customer_code").alias("customer_code"),
            f.col("duplicate_country_code").alias("country_code"),
            f.col("duplicate_address").alias("address"),
            f.col("original_legal_entity").alias("legal_entity"),
            (f.col("duplicate_sub_trade_channel_code") == f.col("original_sub_trade_channel_code")).alias(
                "is_same_sub_trade_channel"
            ),
            f.col("duplicate_trade_channel_code").alias("_pk_trade_channel_code"),
            f.col("duplicate_city").alias("_pk_city"),
            "w_sim_score",
        )
        return df_original_customer.unionByName(df_duplicated_customer)

    @staticmethod
    def _aggregate_similarity_scores(df_duplicated_customers: DataFrame) -> DataFrame:
        """Calculate average similarity scores grouped by business context.

        Computes the average weighted similarity score within each group defined by
        legal entity, country code, and whether customers share the same sub trade
        channel.

        Args:
            df_duplicated_customers: DataFrame with individual customer records and
                                    their similarity scores

        Returns:
            DataFrame with an additional avg_w_sim_score column containing the
            group-level average similarity score
        """
        window = Window.partitionBy("legal_entity", "country_code", "is_same_sub_trade_channel")
        return df_duplicated_customers.withColumn("avg_w_sim_score", f.avg("w_sim_score").over(window))

    def transform(self, ctx: TransformationContext) -> DataFrame:
        """Execute the complete duplicated customers report preparation transformation.

        This is the main entry point that orchestrates the entire report preparation
        process by combining enrichment, filtering, flattening, aggregation, and
        attribute joining steps into a comprehensive pipeline.

        Pipeline stages:
        1. Enrich: Join duplicate pairs with order block codes from customer base table
        2. Filter: Apply order block code-based business rules to filter valid duplicates
        3. Flatten: Transform duplicate pairs into individual customer records
        4. Aggregate: Calculate average similarity scores by business context
        5. Enrich Metadata: Add check_date, primary_key, and rule_code
        6. Join Attributes: Enrich with additional customer attributes from base table
        7. Deduplicate: Remove any duplicate records

        Args:
            ctx: TransformationContext containing input DataFrames.

        Returns:
            DataFrame containing one row per customer in each duplicate pair with
            comprehensive attributes for data quality reporting
        """
        df_duplicated_customers = ctx["df_duplicated_customers"]
        df_customer_base = ctx["df_customer_base"]

        df_original_customer_order_block_code = df_customer_base.select(
            f.col("customer_code").alias("original_customer_code"),
            f.col("sub_trade_channel_code").alias("original_sub_trade_channel_code"),
            f.col("central_order_block_code").alias("original_order_block_code"),
        )
        df_duplicated_customer_order_block_code = df_customer_base.select(
            f.col("customer_code").alias("duplicate_customer_code"),
            f.col("sub_trade_channel_code").alias("duplicate_sub_trade_channel_code"),
            f.col("central_order_block_code").alias("duplicate_order_block_code"),
        )
        df_duplicated_customers = (
            df_duplicated_customers.join(df_original_customer_order_block_code, on="original_customer_code", how="left")
            .join(df_duplicated_customer_order_block_code, on="duplicate_customer_code", how="left")
            .transform(self._order_block_code_based_filtering)
            .transform(self._flatten_duplicated_customers_table)
            .transform(self._aggregate_similarity_scores)
            .withColumn("check_date", f.current_date())
            .withColumn(
                "primary_key",
                f.md5(
                    f.concat_ws(
                        '||',
                        f.coalesce(f.col('customer_code'), f.lit('')),
                        f.coalesce(f.col('country_code'), f.lit('')),
                        f.coalesce(f.col('legal_entity'), f.lit('')),
                        f.coalesce(f.col('is_same_sub_trade_channel').cast('string'), f.lit('')),
                        f.coalesce(f.col('address'), f.lit('')),
                        f.coalesce(f.col('_pk_trade_channel_code'), f.lit('')),
                        f.coalesce(f.col('_pk_city'), f.lit('')),
                    )
                ),
            )
            .drop("w_sim_score", "_pk_trade_channel_code", "_pk_city")
            .distinct()
        )
        df_customer_attributes = df_customer_base.drop(
            "tax", "sap_cluster", "tax1", "tax2", "address", "legal_name", "city_with_postal_code"
        ).withColumnsRenamed({"city_billing": "different_city", "creation_date": "customer_creation_date"})
        df_final_report = df_duplicated_customers.join(
            df_customer_attributes, on=["customer_code", "country_code"], how="left"
        )

        return df_final_report
