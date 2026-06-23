from pyspark.sql.dataframe import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.functions import col, udf
from pyspark.sql.types import BooleanType, StructType, StructField
from pyspark.sql.functions import when
from typing import Optional

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.operation_configs.drop_config import DropOperationConfig
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.phonenumber_validator_config import (
    PhonenumberValidatorOperationConfig,
)

import phonenumbers
from phonenumbers import NumberParseException, carrier, geocoder, timezone
from phonenumbers.phonenumberutil import number_type

phone_validation_schema = StructType([
    StructField("is_valid", BooleanType(), True),
    StructField("is_mobile", BooleanType(), True),
    StructField("is_possible", BooleanType(), True),
    StructField("is_foreign", BooleanType(), True) 
])

def is_valid_phone_number(phone_number, region):
    try:
        # Parse the phone number with the specified region
        parsed_number = phonenumbers.parse(phone_number, region)
        # Check if the number is a valid number for the region
        is_valid = phonenumbers.is_valid_number(parsed_number)
        # Check if the number is a mobile number for the region
        is_mobile = carrier._is_mobile(number_type(parsed_number))
        is_possible = phonenumbers.is_possible_number(parsed_number)
        number_region = phonenumbers.region_code_for_number(parsed_number)
        is_foreign = number_region != region.upper()  # Compare with expected region
        return {"is_valid": is_valid, "is_mobile": is_mobile, "is_possible": is_possible, "is_foreign": is_foreign}
    except NumberParseException:
        return {"is_valid": False, "is_mobile": False, "is_possible": False, "is_foreign": False}

is_valid_phone_number_udf = udf(is_valid_phone_number, phone_validation_schema)

class PhonenumberValidatorOperation(BaseOperation):
    """
    validate if there is a valid phone number in a column
    """

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, PhonenumberValidatorOperationConfig)

        df = ctx[self._config.context_name]

        columnnumber = self._config.params.column_number
        columnregion = self._config.params.column_region
        is_valid_col = columnnumber + "_IsValid"
        is_mobile_col = columnnumber + "_IsMobile"
        is_possible_col = columnnumber + "_IsPossible"
        is_foreign_col = columnnumber + "_IsForeign"

        # Apply the UDF
        df = df.withColumn("phone_validation", is_valid_phone_number_udf(col(columnnumber), col(columnregion)))

        # Extract both fields from the struct
        df = df.withColumn(is_valid_col, col("phone_validation.is_valid"))
        df = df.withColumn(is_mobile_col, col("phone_validation.is_mobile"))
        df = df.withColumn(is_possible_col, col("phone_validation.is_possible"))
        df = df.withColumn(is_foreign_col, col("phone_validation.is_foreign"))

        # Drop the intermediate struct column
        df = df.drop("phone_validation")

        return df
