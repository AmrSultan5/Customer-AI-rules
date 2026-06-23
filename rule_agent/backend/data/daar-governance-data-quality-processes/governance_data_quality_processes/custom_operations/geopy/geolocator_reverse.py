from pyspark.sql.dataframe import DataFrame
from pyspark.sql.functions import col, pandas_udf
from pyspark.sql.types import StructType, StructField, StringType
from typing import Optional
from typing import List, Tuple
import pandas as pd
import concurrent.futures
import requests
import time

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from governance_data_quality_processes.custom_operation_configs.geopy.geolocator_reverse_config import (
    GeolocatorReverseOperationConfig,
)

from geopy.geocoders import Nominatim
from geopy.point import Point
from geopy.exc import GeopyError
from geopy.adapters import RequestsAdapter

class CustomRequestsAdapter(RequestsAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session = requests.Session()
        self.session.verify = False
        self.session.trust_env = True

def get_location_name(latitudes: List[float], longitudes: List[float]) -> List[Tuple]:
    max_retries = 3  # Max retries for 'Service timed out' errors
    initial_wait = 2  # 
    def fetch_location(lat, lon):
        retries = 0
        wait_time = initial_wait
        while retries <= max_retries:
            try:
                geolocator=Nominatim(domain='vmidqqlty001.cchellenic.com:443', scheme='https', timeout=10, adapter_factory=CustomRequestsAdapter)
                location = Point(lat, lon)
                location_name = geolocator.reverse(location)
                if location_name is not None:
                    address = location_name.raw.get('address', {})
                    return (
                        str(location_name.raw.get('place_id', '')),
                        str(location_name.raw.get('osm_id', '')),
                        str(location_name.raw.get('osm_type', '')),
                        str(location_name.raw.get('addresstype', '')),
                        str(location_name.raw.get('display_name', '')),
                        str(location_name.raw.get('type', '')),
                        str(location_name.raw.get('importance', '')),
                        str(address.get('house_number', '')),
                        str(address.get('house_name', '')),
                        str(address.get('road', '')),
                        str(address.get('street', '')),
                        str(address.get('neighbourhood', '')),
                        str(address.get('suburb', '')),
                        str(address.get('city', '')),
                        str(address.get('postcode', '')),
                        str(address.get('country', '')),
                        str(address.get('country_code', '')),
                        str(address.get('state_district', '')),
                        str(address.get('county', '')),
                        str(address.get('municipality', '')),
                        str(address.get('village', '')),
                        str(address.get('town', '')),
                        str(address.get('region', '')),
                        str(address.get('district', '')),
                        str(address.get('state', '')),
                        'verified',
                    )
                else:
                    return ('', 
                        '', 
                        '',
                        '', 
                        '', 
                        '',
                        '',  
                        '', 
                        '', 
                        '', 
                        '', 
                        '', 
                        '', 
                        '',
                        '', 
                        '',
                        '', 
                        '', 
                        '', 
                        '', 
                        '', 
                        '', 
                        '', 
                        '', 
                        '', 
                        'no_results')
            except GeopyError as e:
                if 'Service timed out' in repr(str(e)) and retries < max_retries:
                    # Retry on Service timed outerror
                    retries += 1
                    time.sleep(wait_time)
                    wait_time *= 2  # Exponential backoff
                else:
                    return ('', 
                            '', 
                            '',
                            '', 
                            '', 
                            '',
                            '',  
                            '', 
                            '', 
                            '', 
                            '', 
                            '', 
                            '', 
                            '',
                            '', 
                            '',
                            '', 
                            '', 
                            '', 
                            '', 
                            '', 
                            '', 
                            '', 
                            '', 
                            '', 
                            repr(str(e)))

    # Use a thread pool to fetch locations concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_location, latitudes, longitudes))
    
    return results  
# Define schema for location details
location_schema = StructType([
    StructField("place_id", StringType(), True),
    StructField("osm_id", StringType(), True),
    StructField("osm_type", StringType(), True),
    StructField("addresstype", StringType(), True),
    StructField("display_name", StringType(), True),
    StructField("type", StringType(), True),
    StructField("importance", StringType(), True),
    StructField("house_number", StringType(), True),
    StructField("house_name", StringType(), True),
    StructField("road", StringType(), True),
    StructField("street", StringType(), True),
    StructField("neighbourhood", StringType(), True),
    StructField("suburb", StringType(), True),
    StructField("city", StringType(), True),
    StructField("postcode", StringType(), True),
    StructField("country", StringType(), True),
    StructField("country_code", StringType(), True),
    StructField("state_district", StringType(), True),
    StructField("county", StringType(), True),
    StructField("municipality", StringType(), True),
    StructField("village", StringType(), True),
    StructField("town", StringType(), True),
    StructField("region", StringType(), True),
    StructField("district", StringType(), True),
    StructField("state", StringType(), True),
    StructField("api_reverse_result_status", StringType(), True),
])

# Define a batch UDF to apply the reverse geocoding concurrently
@pandas_udf(location_schema)
def get_location_batch_udf(latitudes: pd.Series, longitudes: pd.Series) -> pd.DataFrame:
    results = get_location_name(latitudes.tolist(), longitudes.tolist())
    return pd.DataFrame(results, columns=[field.name for field in location_schema.fields])

class GeolocatorReverseOperation(BaseOperation):
    """
    find the address corresponding to a set of coordinates
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, GeolocatorReverseOperationConfig)

        df = ctx[self._config.context_name]
        lat = self._config.params.lat
        lon = self._config.params.lon
        country_code = self._config.params.country_code
        # Add the country filter before the API call
        country_filter_value = self._config.params.country_filter  # Assuming country_filter is passed in config
        
        # Apply the country filter
        df = df.filter(col(country_code) == country_filter_value)
        # Apply the batch UDF to get structured location details
        df = df.withColumn("location_details", get_location_batch_udf(col(lat), col(lon)))
        # Extract individual fields from the structured column
        df = df.withColumn("place_id", col("location_details.place_id")) \
               .withColumn("osm_id", col("location_details.osm_id")) \
               .withColumn("osm_type", col("location_details.osm_type")) \
               .withColumn("addresstype", col("location_details.addresstype")) \
               .withColumn("display_name", col("location_details.display_name")) \
               .withColumn("type", col("location_details.type")) \
               .withColumn("importance_api_reverse", col("location_details.importance")) \
               .withColumn("house_number", col("location_details.house_number")) \
               .withColumn("house_name", col("location_details.house_name")) \
               .withColumn("road", col("location_details.road")) \
               .withColumn("street", col("location_details.street")) \
               .withColumn("neighbourhood", col("location_details.neighbourhood")) \
               .withColumn("suburb", col("location_details.suburb")) \
               .withColumn("city", col("location_details.city")) \
               .withColumn("postcode", col("location_details.postcode")) \
               .withColumn("country", col("location_details.country")) \
               .withColumn("country_code", col("location_details.country_code")) \
               .withColumn("state_district", col("location_details.state_district")) \
               .withColumn("county", col("location_details.county")) \
               .withColumn("municipality", col("location_details.municipality")) \
               .withColumn("village", col("location_details.village")) \
               .withColumn("town", col("location_details.town")) \
               .withColumn("region", col("location_details.region")) \
               .withColumn("district", col("location_details.district")) \
               .withColumn("state", col("location_details.state")) \
               .withColumn("api_reverse_result_status", col("location_details.api_reverse_result_status"))       
        df = df.drop("location_details")
        return df