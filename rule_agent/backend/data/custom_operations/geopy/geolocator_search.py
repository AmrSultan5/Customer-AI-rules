from pyspark.sql.dataframe import DataFrame
from pyspark.sql.functions import col, pandas_udf
from pyspark.sql.types import StructType, StructField, StringType
from typing import Optional
from typing import List, Tuple
import logging
import os
import pandas as pd
import concurrent.futures
import requests
import time

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from governance_data_quality_processes.custom_operation_configs.geopy.geolocator_search_config import (
    GeolocatorSearchOperationConfig,
)

from geopy.geocoders import Nominatim
from geopy.exc import GeopyError
from geopy.adapters import RequestsAdapter

log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
# NOMINATIM_DOMAIN  — required. Hostname:port of the Nominatim geocoding service.
#                     No default; missing config raises a clear error.
# NOMINATIM_VERIFY_TLS — set to "false" only with explicit understanding of the risk.
#                        Default: true (TLS verification enabled).
# NOMINATIM_CA_BUNDLE / REQUESTS_CA_BUNDLE — path to custom CA certificate bundle
#                        for corporate PKI / internal TLS.

_NOMINATIM_DOMAIN: str = os.environ.get("NOMINATIM_DOMAIN", "")
_NOMINATIM_VERIFY_TLS: bool = os.environ.get("NOMINATIM_VERIFY_TLS", "true").lower() != "false"
_NOMINATIM_CA_BUNDLE: str = (
    os.environ.get("NOMINATIM_CA_BUNDLE") or os.environ.get("REQUESTS_CA_BUNDLE") or ""
)

if _NOMINATIM_VERIFY_TLS and _NOMINATIM_CA_BUNDLE:
    _TLS_VERIFY = _NOMINATIM_CA_BUNDLE  # use custom CA bundle
elif _NOMINATIM_VERIFY_TLS:
    _TLS_VERIFY = True                  # default OS trust store
else:
    log.warning(
        "TLS verification disabled for Nominatim (NOMINATIM_VERIFY_TLS=false). "
        "Only set this on trusted internal networks with a controlled CA."
    )
    _TLS_VERIFY = False


class CustomRequestsAdapter(RequestsAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session = requests.Session()
        self.session.verify = _TLS_VERIFY
        self.session.trust_env = True


# Function to get geocode with concurrency
def get_geocode(house_numbers: List[str], streets: List[str], cities: List[str], postcodes: List[str], country_codes: List[str]) -> List[Tuple]:
    if not _NOMINATIM_DOMAIN:
        log.error("NOMINATIM_DOMAIN environment variable is not set; geocoding is disabled.")
        return [('', '', '', '', 'config_error: NOMINATIM_DOMAIN not set')] * len(house_numbers)

    max_retries = 3  # Max retries for 'Service timed out' errors
    initial_wait = 2

    def fetch_geocode(house_number, street, city, postcode, country_code):
        retries = 0
        wait_time = initial_wait
        while retries <= max_retries:
            try:
                geolocator = Nominatim(
                    domain=_NOMINATIM_DOMAIN,
                    scheme='https',
                    timeout=10,
                    adapter_factory=CustomRequestsAdapter,
                )
                house_number_street = ", ".join(
                    filter(None, [house_number, street])
                )
                location_details = {
                    "street": house_number_street,
                    "city": city,
                    "postalcode": postcode,
                }
                geocode = geolocator.geocode(location_details, exactly_one=True, country_codes=country_code)
                if geocode is not None:
                    return (
                        str(geocode.raw.get('place_id', '')),
                        str(geocode.raw.get('lat', '')),
                        str(geocode.raw.get('lon', '')),
                        str(geocode.raw.get('importance', '')),
                        'verified',
                    )
                else:
                    return ('', '', '', '', 'no_results')
            except GeopyError as e:
                if 'Service timed out' in repr(str(e)) and retries < max_retries:
                    retries += 1
                    time.sleep(wait_time)
                    wait_time *= 2  # Exponential backoff
                else:
                    return ('', '', '', '', repr(str(e)))

    # Use a thread pool to fetch geocode concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_geocode, house_numbers, streets, cities, postcodes, country_codes))

    return results


# Define schema for geocode
geocode_schema = StructType([
    StructField("place_id", StringType(), True),
    StructField("lat", StringType(), True),
    StructField("lon", StringType(), True),
    StructField("importance", StringType(), True),
    StructField("api_search_result_status", StringType(), True),
])


# Define a batch UDF to apply the geocoding
@pandas_udf(geocode_schema)
def get_geocode_batch_udf(house_numbers: pd.Series, streets: pd.Series, cities: pd.Series, postcodes: pd.Series, country_codes: pd.Series) -> pd.DataFrame:
    results = get_geocode(
        house_numbers.tolist(),
        streets.tolist(),
        cities.tolist(),
        postcodes.tolist(),
        country_codes.tolist()
    )

    # Convert results to a DataFrame and ensure all types are strings
    return pd.DataFrame(results, columns=[field.name for field in geocode_schema.fields]).astype(str)


class GeolocatorSearchOperation(BaseOperation):
    """
    Find the coordinates corresponding to an address.
    Requires NOMINATIM_DOMAIN environment variable (no default).
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, GeolocatorSearchOperationConfig)
        df = ctx[self._config.context_name]
        house_number = self._config.params.house_number
        street = self._config.params.street
        city = self._config.params.city
        postcode = self._config.params.postcode
        country_code = self._config.params.country_code
        country_filter_value = self._config.params.country_filter

        # Apply the country filter
        df = df.filter(col(country_code) == country_filter_value)
        # Apply the batch UDF to get structured geocode
        df = df.withColumn("geocode", get_geocode_batch_udf(
            col(house_number),
            col(street),
            col(city),
            col(postcode),
            col(country_code)
        ))
        # Extract individual fields from the structured column
        df = df.withColumn("lat", col("geocode.lat")) \
               .withColumn("lon", col("geocode.lon")) \
               .withColumn("importance_api_search", col("geocode.importance")) \
               .withColumn("api_search_result_status", col("geocode.api_search_result_status"))
        df = df.drop("geocode")
        return df
