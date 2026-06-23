"""Customer Base Table Generation Module.

This module provides functionality for preparing and consolidating customer data
from multiple sources into a unified base table for customer uniqueness analysis
in the Data Control Center. The module handles country-specific data normalization,
particularly for legal entity names and tax identifiers, to create a standardized
dataset ready for duplicate matching operations.

The module aggregates data from customer general information, addresses, sales
organizations, contacts, hierarchies, and equipment, applying business rules
for scope filtering and country-specific transformations.
"""

from pyspark.sql import Column
from pyspark.sql import functions as f
from pyspark.sql.dataframe import DataFrame

from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operations.base import BaseOperation


class GenerateBaseTableForCustomerUniquenessOperation(BaseOperation):
    """Operation for generating a consolidated customer base table for uniqueness analysis.

    This operation prepares customer data by:
    1. Filtering customers to include only those in scope (account group starting with '9',
       excluding blocked orders)
    2. Aggregating supplementary information (equipment, contacts, hierarchy)
    3. Joining multiple customer data sources (general, address, sales org, contact, hierarchy, equipment)
    4. Applying country-specific transformations for legal names and tax identifiers
    5. Normalizing and standardizing fields (city, address, legal name) for matching
    """
    @staticmethod
    def _aggregate_equipment_info_per_customer(df_equipment: DataFrame) -> DataFrame:
        """Aggregate equipment information at the customer level.

        Consolidates all equipment descriptions and last scan dates associated with each
        customer into single lists, removing duplicates. This provides context about what
        equipment types are associated with each customer and when they were last scanned.

        Args:
            df_equipment: Input DataFrame containing equipment records.

        Returns:
            DataFrame with one row per customer containing equipment list and last scan dates.

        """
        df_equipment_agg = df_equipment.groupBy("customer_code", "sap_cluster").agg(
            f.array_join(f.collect_set("equipment_description"), ", ").alias("equipment_list"),
            f.array_join(f.collect_set(f.col("last_scan_date").cast("string")), ", ").alias("equip_last_scanned_date"),
        )
        return df_equipment_agg

    @staticmethod
    def _aggregate_in_scope_phone_numbers(df_customer_contact: DataFrame) -> DataFrame:
        """Aggregate in-scope telephone numbers for each customer.

        Filters and aggregates telephone contact information based on specific business
        criteria. Only includes phone numbers from S4 system with function code 'Z5'
        (specific partner function), excluding null or empty values.

        Filtering criteria:
        1. source == 's4': Only S4 system records
        2. function_of_partner == 'Z5': Specific partner function code
        3. Non-null and non-empty tel_number values

        Args:
            df_customer_contact: Input DataFrame containing customer contact records

        Returns:
            DataFrame with one row per customer containing list of phone numbers.
        """
        return (
            df_customer_contact.filter(f.col("source") == "s4")
            .filter(f.col("function_of_partner") == "Z5")
            .filter(f.col("tel_number").isNotNull())
            .filter(f.col("tel_number") != "")
            .groupBy("customer_code", "sap_cluster")
            .agg(f.array_join(f.collect_set("tel_number"), ", ").alias("tel_number"))
        )

    @staticmethod
    def _aggregate_last_visit_date(df_last_visit: DataFrame) -> DataFrame:
        """Aggregate last visit date per customer.

        Computes the most recent visit date for each customer from
        field sales activities data.

        Args:
            df_last_visit: Input DataFrame containing field sales activities records
                with 'customer' and 'calday' columns.

        Returns:
            DataFrame with one row per customer containing the last visit date.
        """
        return (
            df_last_visit
            .filter(f.col("calday").isNotNull())
            .groupBy("customer")
            .agg(f.max("calday").alias("last_visit_date"))
            .select(
                f.col("customer").alias("customer_code"),
                f.col("last_visit_date"),
            )
        )

    @staticmethod
    def _aggregate_last_order_date(df_last_order: DataFrame) -> DataFrame:
        """Aggregate last order date per customer and sales org.

        Computes the most recent order date for each customer+salesorg combination
        from perfect order data. Preserves salesorg for joining through the sales
        organization table, matching the POC behavior.

        Args:
            df_last_order: Input DataFrame containing order records
                with 'sold_to', 'salesorg', and 'bic_ccdate_or' columns.

        Returns:
            DataFrame with one row per customer+salesorg containing the last order date.
        """
        return (
            df_last_order
            .filter(f.col("bic_ccdate_or").isNotNull())
            .groupBy("salesorg", "sold_to")
            .agg(f.max("bic_ccdate_or").alias("last_order_date"))
            .select(
                f.col("sold_to").alias("customer_code"),
                f.col("salesorg").alias("sale_org_code"),
                f.col("last_order_date"),
            )
        )

    @staticmethod
    def _prepare_customer_pi(df_customer_pi: DataFrame) -> DataFrame:
        """Prepare customer PI data with relevant columns for enrichment.

        Selects credit limit, hierarchy description, business developer description,
        team leader EID, team leader PID, and payer order block from the customer PI table.

        Args:
            df_customer_pi: Input DataFrame from cacus03pi_customer_pi.

        Returns:
            DataFrame with selected and renamed columns, deduplicated by customer.
        """
        return (
            df_customer_pi
            .select(
                f.col("customer").alias("customer_code"),
                f.col("cred_limit").alias("pi_credit_limit"),
                f.col("ccusthie6_desc").alias("pi_ccusthie6_desc"),
                f.col("cbdvempl_desc").alias("pi_bd_desc"),
                f.col("cterrid_desc").alias("pi_cterrid_desc"),
                f.col("ctlm_eid_desc").alias("team_leader_eid"),
                f.col("ctlm_pid_desc").alias("team_leader_pid"),
                f.col("bic_csup_cust").alias("payer_order_block"),
            )
            .dropDuplicates(subset=["customer_code"])
        )

    @staticmethod
    def _prepare_customer_master(df_customer_master: DataFrame) -> DataFrame:
        """Prepare customer master data to extract payer and fallback enrichment fields.

        Selects the payer field and fallback columns for credit_limit, ccusthie6_desc,
        and cbdvempl_desc (business developer description) from the customer master table.
        These are used in COALESCE logic with the cacus03pi_customer_pi values,
        matching the POC behavior: COALESCE(c.col, p.col).

        Args:
            df_customer_master: Input DataFrame from ca_0_cus03_customer.

        Returns:
            DataFrame with customer_code, payer, and fallback columns, deduplicated.
        """
        return (
            df_customer_master
            .select(
                f.col("customer").alias("customer_code"),
                f.col("payer"),
                f.col("cred_limit").alias("master_credit_limit"),
                f.col("ccusthie6_desc").alias("master_ccusthie6_desc"),
                f.col("cbdvempl_desc").alias("master_bd_desc"),
                f.col("cterrid_desc").alias("master_cterrid_desc"),
            )
            .dropDuplicates(subset=["customer_code"])
        )

    @staticmethod
    def _prepare_customer_activeness(df_customer_activeness: DataFrame) -> DataFrame:
        """Prepare customer activeness data to extract active status.

        Selects the check_status field from the activeness check results.

        Args:
            df_customer_activeness: Input DataFrame from dm_customer_check_results_activeness.

        Returns:
            DataFrame with customer_code and is_active columns, deduplicated.
        """
        return (
            df_customer_activeness
            .select(
                f.col("customer_code"),
                f.col("check_status").alias("is_active"),
            )
            .dropDuplicates(subset=["customer_code"])
        )

    @staticmethod
    def _select_customers_in_scope(df_customer_general: DataFrame) -> DataFrame:
        """Filter customers to include only those in scope for uniqueness analysis.

        Applies business rules to identify customers that should be included in the
        uniqueness check. Includes customers with specific account groups and excludes
        those with certain order block codes.

        Inclusion criteria:
        1. account_group_code starts with '9': Identifies specific customer categories
        2. central_order_block_code NOT IN ('NH', 'S', 'S3', 'S4', 'SP', 'SY'):
           Excludes customers with blocked orders

        Args:
            df_customer_general: Input DataFrame containing general customer information

        Returns:
            DataFrame containing only in-scope customers with all original columns
        """
        df_customers_in_scope = df_customer_general.filter(f.col("account_group_code").startswith("9")).filter(
            ~f.col("central_order_block_code").isin("NH", "S", "S3", "S4", "SP", "SY")
        )
        return df_customers_in_scope

    @staticmethod
    def _select_rule_in_scope(df_rules_inventory: DataFrame) -> DataFrame:
        """Filter rules inventory to include only the uniqueness rule."""
        df_rules_inventory = f.broadcast(df_rules_inventory
                              .filter(f.col('is_active') == '1')
                              .filter(f.col("rule_code") == "RCUNIQ_1")
                              .select('rule_code')
                              .distinct()
                              )
        return df_rules_inventory

    @property
    def _customer_general_in_scope_columns(self) -> list:
        """List of columns to select from customer general information.

        Defines the subset of general customer attributes needed for uniqueness
        analysis, including identifiers, organization names, tax values, and
        business metadata.
        """
        return [
            "customer_code",
            "sap_cluster",
            "country_code",
            "organization_1_name",
            "organization_2_name",
            "organization_3_name",
            "organization_4_name",
            "central_order_block_code",
            "trade_channel_code",
            "trade_channel_name",
            "sub_trade_channel_code",
            "sub_trade_channel_name",
            "tax_0_value",
            "tax_1_value",
            "tax_2_value",
            "tax_3_value",
            "central_order_block_assignment_date",
            "creation_date",
            "account_group_code",
            "customer_visits_flag"
        ]

    @property
    def _customer_address_in_scope_columns(self) -> list:
        """List of columns to select from customer address information.

        Defines the address-related attributes needed for uniqueness analysis,
        including standard and billing cities, street information, and geographic
        coordinates.
        """
        return [
            "customer_code",
            "sap_cluster",
            "city",
            "city_billing",
            "street_1_name",
            "house_number",
            "post_code",
            "street_5_name",
            "street_4_name",
            "latitude",
            "longitude",
            "address_type",
        ]

    @property
    def _customer_sales_organizations_in_scope_columns(self) -> list:
        """List of columns to select from customer sales organization information.

        Defines the sales organization attributes used for customer classification
        and scope filtering in uniqueness analysis. Includes sale_org_code for
        joining with last order data.
        """
        return [
            "customer_code",
            "sap_cluster",
            "sale_org_code",
            "customer_group_4_code",
            "customer_group_4_name",
            "customer_group_code",
            "customer_group_name",
            "payer_partner_function_flag"
        ]

    @property
    def _customer_hierarchy_in_scope_columns(self) -> list:
        """List of columns to select from customer hierarchy information.

        Defines the hierarchy attributes that provide organizational context,
        mapping Level 7 customers to their Level 4 parent names.
        """
        return [
            f.col("l7_customer_code").alias("customer_code"),
            "sap_cluster",
            "l4_customer_name",
            "l4_customer_code",
            "l3_customer_code"
        ]

    @staticmethod
    def _concatenate_string_columns(*columns):
        """Concatenate multiple string columns into a single normalized string.

        Combines multiple string values (columns or expressions) into a single
        lowercase, trimmed string with spaces as separators. Handles null values
        gracefully by treating them as empty strings.

        Args:
            *columns: Variable number of column names (strings) or Column expressions
                     to concatenate

        Returns:
            Spark Column expression representing the normalized concatenated string
        """
        non_empty_columns = [
            f.coalesce(f.col(column) if isinstance(column, str) else column, f.lit("")) for column in columns
        ]
        return f.lower(f.trim(f.concat_ws(" ", *non_empty_columns)))

    @staticmethod
    def _country_value_is_in(*countries) -> Column:
        """Create a boolean expression checking if country_code matches any provided countries.

        Helper method to create case-insensitive country code matching expressions
        for use in conditional logic throughout the transformation.

        Args:
            *countries: Variable number of country code strings (e.g., 'NG', 'IE', 'CH')

        Returns:
            Spark Column expression (boolean) that evaluates to True when the
            country_code column (uppercased) matches any of the provided countries
        """
        return f.upper(f.col("country_code")).isin([country.upper() for country in countries])

    @property
    def city_expression(self) -> Column:
        """Spark Column expression for selecting the appropriate city field based on country.

        Implements country-specific logic for city selection, normalized to lowercase
        for consistent matching.

        Logic:
        - Nigeria (NG): Uses city_billing field
        - All other countries: Uses standard city field
        """
        expression = f.when(self._country_value_is_in("NG"), f.col("city_billing")).otherwise(f.col("city"))
        return self._concatenate_string_columns(expression)

    @property
    def legal_name_expression(self) -> Column:
        """Spark Column expression for constructing legal name based on country-specific rules.

        Builds the legal customer name by selecting and concatenating appropriate
        organization name and address fields based on country. Different countries
        store legal entity information in different fields, requiring this mapping logic.

        Country-specific rules:
        - AM, UA: street_4_name + street_5_name + organization_3_name
        - CZ, PL, SK, KV, ME, RS: street_4_name + street_5_name
        - HU, MK: organization_2_name
        - GB, IE: organization_3_name
        - IT: organization_1_name + organization_2_name
        - RO: organization_1_name + organization_3_name + organization_4_name
        - Default: organization_1_name

        Returns:
            Spark Column expression representing the normalized legal name
        """
        return (
            f.when(
                self._country_value_is_in("AM", "UA"),
                self._concatenate_string_columns("street_4_name", "street_5_name", "organization_3_name"),
            )
            .when(
                self._country_value_is_in("CZ", "PL", "SK", "KV", "ME", "RS"),
                self._concatenate_string_columns("street_4_name", "street_5_name"),
            )
            .when(
                self._country_value_is_in("HU", "MK"),
                self._concatenate_string_columns("organization_2_name"),
            )
            .when(
                self._country_value_is_in("GB", "IE"),
                self._concatenate_string_columns("organization_3_name"),
            )
            .when(
                self._country_value_is_in("IT"),
                self._concatenate_string_columns("organization_1_name", "organization_2_name"),
            )
            .when(
                self._country_value_is_in("RO"),
                self._concatenate_string_columns("organization_1_name", "organization_3_name", "organization_4_name"),
            )
            .otherwise(self._concatenate_string_columns("organization_1_name"))
        )

    @property
    def tax2_expression(self) -> Column:
        """Spark Column expression for mapping the appropriate tax value to the tax2 field.

        Implements country-specific logic for secondary tax identifier mapping.
        Different countries use different tax value fields for their secondary
        tax identifiers.

        Logic:
        - CZ, GR, HR, IT, MD, SK: Maps tax_1_value to tax2
        - All other countries: Maps tax_2_value to tax2

        Returns:
            Spark Column expression representing the tax2 value

        """
        return f.when(
            self._country_value_is_in("CZ", "GR", "HR", "IT", "MD", "SK"),
            f.col("tax_1_value"),
        ).otherwise(f.col("tax_2_value"))

    @property
    def tax_expression(self) -> Column:
        """Spark Column expression for mapping the appropriate tax value to the primary tax field.

        Implements country-specific logic for primary tax identifier mapping.
        Different countries use different source fields for their primary tax/VAT
        identification numbers.

        Logic:
        - NG: Maps tax_3_value to tax
        - CZ, GR, HR, IT, MD, SK: Maps tax_2_value to tax
        - All other countries: Maps tax_1_value to tax

        Returns:
            Spark Column expression representing the primary tax value
        """
        return (
            f.when(self._country_value_is_in("NG"), f.col("tax_3_value"))
            .when(
                self._country_value_is_in("CZ", "GR", "HR", "IT", "MD", "SK"),
                f.col("tax_2_value"),
            )
            .otherwise(f.col("tax_1_value"))
        )

    @property
    def customer_classification_id_expression(self) -> Column:
        """Spark Column expression for generating a unique customer classification ID."""
        return f.md5(
            f.concat_ws(
                "",
                f.coalesce(f.col("account_group_code"), f.lit("null")),
                f.coalesce(f.col("customer_group_4_code"), f.lit("null")),
                f.coalesce(f.col("l3_customer_code"), f.lit("null")),
                f.coalesce(f.col("l4_customer_code"), f.lit("null")),
                f.coalesce(f.col("central_order_block_code"), f.lit("null")),
                f.coalesce(f.col("payer_partner_function_flag"), f.lit("null")),
                f.coalesce(f.col("customer_visits_flag"), f.lit("null")),
            )
        )

    def transform(self, ctx: TransformationContext) -> DataFrame:
        """Execute the complete customer base table generation transformation.

        This is the main entry point that orchestrates the entire data preparation
        process by combining filtering, aggregation, joining, and normalization steps
        into a comprehensive pipeline.

        Pipeline stages:
        1. Aggregate: Consolidate equipment and contact information per customer
        2. Select: Choose relevant columns from each source dataset
        3. Filter: Apply scope filters (in-scope customers, account groups)
        4. Join: Combine all data sources (general, address, sales org, contact, hierarchy, equipment)
        5. Filter: Apply additional filters (default address, customer groups DI/IN)
        6. Transform: Apply country-specific normalizations (city, legal name, tax fields)
        7. Enrich: Join additional data sources (last visit, last order, customer PI, payer, activeness)
        8. Deduplicate: Remove any duplicate records

        Args:
            ctx: TransformationContext containing input DataFrames.

        Returns:
            DataFrame containing one row per in-scope customer with standardized attributes.

        """
        df_equipment = ctx["df_equipment"]
        df_customer_general = ctx["df_customer_general"]
        df_customer_address = ctx["df_customer_address"]
        df_customer_sales_organization = ctx["df_customer_sales_organization"]
        df_customer_contact = ctx["df_customer_contact"]
        df_customer_hierarchy = ctx["df_customer_hierarchy"]
        df_rules_inventory = ctx["df_rules_inventory"]
        df_last_visit = ctx["df_last_visit"]
        df_last_order = ctx["df_last_order"]
        df_customer_pi = ctx["df_customer_pi"]
        df_customer_master = ctx["df_customer_master"]
        df_customer_activeness = ctx["df_customer_activeness"]

        df_rules_inventory = df_rules_inventory.transform(self._select_rule_in_scope)
        df_equipment = df_equipment.transform(self._aggregate_equipment_info_per_customer)
        df_customer_address = df_customer_address.select(self._customer_address_in_scope_columns)
        df_customer_contact = df_customer_contact.transform(self._aggregate_in_scope_phone_numbers)
        df_customer_hierarchy = df_customer_hierarchy.select(self._customer_hierarchy_in_scope_columns)
        df_customer_sales_organization = (
            df_customer_sales_organization
            .dropDuplicates(subset=['customer_code', 'sap_cluster'])
            .select(self._customer_sales_organizations_in_scope_columns)
        )
        df_customer_general = df_customer_general.transform(self._select_customers_in_scope).select(
            self._customer_general_in_scope_columns
        )

        # Aggregate new data sources
        df_last_visit_agg = self._aggregate_last_visit_date(df_last_visit)
        df_last_order_agg = self._aggregate_last_order_date(df_last_order)
        df_customer_pi_prepared = self._prepare_customer_pi(df_customer_pi)
        df_customer_master_prepared = self._prepare_customer_master(df_customer_master)
        df_customer_activeness_prepared = self._prepare_customer_activeness(df_customer_activeness)

        df_result = (
            df_rules_inventory
            .crossJoin(df_customer_general)
            .join(df_customer_address, on=["customer_code", "sap_cluster"], how="inner")
            .join(
                df_customer_sales_organization,
                on=["customer_code", "sap_cluster"],
                how="inner",
            )
            .join(df_customer_contact, on=["customer_code", "sap_cluster"], how="left")
            .join(df_customer_hierarchy, on=["customer_code", "sap_cluster"], how="left")
            .join(df_equipment, on=["customer_code", "sap_cluster"], how="left")
            .filter(f.col("address_type") == "XXDEFAULT")
            .filter(f.col("customer_group_4_code").isin("DI", "IN"))
            .drop("address_type")
            .withColumns(
                {
                    "city": self.city_expression,
                    "city_with_postal_code": self._concatenate_string_columns(self.city_expression, f.col("post_code")),
                    "legal_name": self.legal_name_expression,
                    "address": self._concatenate_string_columns(f.col("street_1_name"), f.col("house_number")),
                    "tax": self.tax_expression,
                    "tax1": f.col("tax_0_value"),
                    "tax2": self.tax2_expression,
                    "cust_class_id": self.customer_classification_id_expression
                }
            )
            .drop('account_group_code', 'customer_visits_flag', 'l3_customer_code', 'l4_customer_code', 'payer_partner_function_flag')
            .join(df_last_visit_agg, on="customer_code", how="left")
            .join(df_last_order_agg, on=["customer_code", "sale_org_code"], how="left")
            .join(df_customer_pi_prepared, on="customer_code", how="left")
            .join(df_customer_master_prepared, on="customer_code", how="left")
            .join(df_customer_activeness_prepared, on="customer_code", how="left")
            .withColumns(
                {
                    "credit_limit": f.coalesce(f.col("master_credit_limit"), f.col("pi_credit_limit")),
                    "ccusthie6_desc": f.coalesce(f.col("master_ccusthie6_desc"), f.col("pi_ccusthie6_desc")),
                    "bd_desc": f.coalesce(f.col("master_bd_desc"), f.col("pi_bd_desc")),
                    "cterrid_desc": f.coalesce(f.col("master_cterrid_desc"), f.col("pi_cterrid_desc")),
                }
            )
            .drop("master_credit_limit", "pi_credit_limit",
                   "master_ccusthie6_desc", "pi_ccusthie6_desc",
                   "master_bd_desc", "pi_bd_desc",
                   "master_cterrid_desc", "pi_cterrid_desc", "sale_org_code")
            .distinct()
        )

        return df_result