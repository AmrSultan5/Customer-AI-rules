from pyspark.sql.dataframe import DataFrame
from pyspark.sql.functions import col, pandas_udf
from pyspark.sql.types import StructType, StructField, StringType
from typing import Optional, List
import pandas as pd
import concurrent.futures
import time

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from governance_data_quality_processes.custom_operation_configs.verify_vat_numbers.get_from_vies_config import (
    GetFromViesOperationConfig,
)

from verify_vat_number.vies import get_from_eu_vies
from verify_vat_number.exceptions import VatNotFound, VerifyVatException, UnsupportedCountryCode

# Function to get VIES data for a batch of VAT numbers with concurrency
def get_vies_concurrent(vat_list: pd.Series) -> pd.DataFrame:
    results = []
    max_retries = 3  # Max retries for MS_MAX_CONCURRENT_REQ errors
    initial_wait = 2  # Initial wait time in seconds for backoff
    def process_vat(vat):
        retries = 0
        wait_time = initial_wait
        while retries <= max_retries:
            try:
                data = get_from_eu_vies(vat)
                return {
                    "company_name": data.company_name,
                    "address": data.address,
                    "street_and_num": data.street_and_num,
                    "city": data.city,
                    "postal_code": data.postal_code,
                    "district": data.district,
                    "country_code": data.country_code,
                    "legal_form": data.legal_form,
                    "api_result_status": 'verified'
                }
            except VatNotFound:
                return {
                    "company_name": '',
                    "address": '',
                    "street_and_num": '',
                    "city": '',
                    "postal_code": '',
                    "district": '',
                    "country_code": '',
                    "legal_form": '',
                    "api_result_status": 'VAT not found'
                }
            except UnsupportedCountryCode:
                return {
                    "company_name": '',
                    "address": '',
                    "street_and_num": '',
                    "city": '',
                    "postal_code": '',
                    "district": '',
                    "country_code": '',
                    "legal_form": '',
                    "api_result_status": 'unsupported country code'
                }
            except VerifyVatException as e:
                if 'MS_MAX_CONCURRENT_REQ' in str(e.source) and retries < max_retries:
                    # Retry on MS_MAX_CONCURRENT_REQ error
                    retries += 1
                    time.sleep(wait_time)
                    wait_time *= 2  # Exponential backoff
                else:
                    return {
                        "company_name": '',
                        "address": '',
                        "street_and_num": '',
                        "city": '',
                        "postal_code": '',
                        "district": '',
                        "country_code": '',
                        "legal_form": '',
                        "api_result_status": repr(str(e.source))
                    }
            except Exception as e:
                return {
                    "company_name": '',
                    "address": '',
                    "street_and_num": '',
                    "city": '',
                    "postal_code": '',
                    "district": '',
                    "country_code": '',
                    "legal_form": '',
                    "api_result_status": f'error: {str(e)}'
                }

    # Use ThreadPoolExecutor to handle concurrency
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # Map VAT numbers to futures
        future_to_vat = {executor.submit(process_vat, vat): vat for vat in vat_list}
        
        for future in concurrent.futures.as_completed(future_to_vat):
            try:
                result = future.result()
            except Exception as e:
                result = {
                    "company_name": '',
                    "address": '',
                    "street_and_num": '',
                    "city": '',
                    "postal_code": '',
                    "district": '',
                    "country_code": '',
                    "legal_form": '',
                    "api_result_status": f'error: {str(e)}'
                }
            results.append(result)
    
    return pd.DataFrame(results)

# Define schema for the output DataFrame
vies_schema = StructType([
    StructField("company_name", StringType(), True),
    StructField("address", StringType(), True),
    StructField("street_and_num", StringType(), True),
    StructField("city", StringType(), True),
    StructField("postal_code", StringType(), True),
    StructField("district", StringType(), True),
    StructField("country_code", StringType(), True),
    StructField("legal_form", StringType(), True),
    StructField("api_result_status", StringType(), True),    
])

class GetFromViesOperation(BaseOperation):
    """
    Find the company corresponding to a VAT number using batch processing with concurrency
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, GetFromViesOperationConfig)
        df = ctx[self._config.context_name]
        vat = self._config.params.vat
        country_code = self._config.params.country_code
        # Add the country filter before the API call
        country_filter_value = self._config.params.country_filter  # Assuming country_filter is passed in config
        
        # Apply the country filter
        df = df.filter(col(country_code) == country_filter_value)
        # Repartition the DataFrame for optimal parallelism
        # Ensure we have at least 1 partition
        num_partitions = df.rdd.getNumPartitions()
        calculated_partitions = max(1, df.count() // 500)
        optimal_partitions = max(1, min(calculated_partitions, num_partitions * 4))
        df = df.repartition(optimal_partitions)
        # Register the pandas UDF for batch processing with concurrency
        get_vies_udf = pandas_udf(get_vies_concurrent, returnType=vies_schema)
        # Apply the UDF to get VIES data for batches
        df = df.withColumn("vies", get_vies_udf(col(vat)))
        # Extract individual fields from the structured column
        df = df.withColumn("company_name", col("vies.company_name")) \
               .withColumn("address", col("vies.address")) \
               .withColumn("street_and_num", col("vies.street_and_num")) \
               .withColumn("city", col("vies.city")) \
               .withColumn("postal_code", col("vies.postal_code")) \
               .withColumn("district", col("vies.district")) \
               .withColumn("country_code", col("vies.country_code")) \
               .withColumn("legal_form", col("vies.legal_form")) \
               .withColumn("api_result_status", col("vies.api_result_status"))       
        df = df.drop("vies")
        return df
