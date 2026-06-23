import pytest
from typing import Dict
from pyspark.sql import SparkSession
from tests.utils.transformation_utils import transform


class TestDMCustomerGeneral:
    @pytest.mark.usefixtures("spark_session")
    @pytest.mark.parametrize(
        "config_path, dynamic_params",
        [
            (
                "processes/data_quality/ca/data_control_center/golden/dm_customer_general/v6/dm_customer_general_v6.yaml",
                {},
            )
        ],
    )
    def test_dm_customer_general(self, config_path: str, dynamic_params: Dict, spark_session: SparkSession):
        transform(config_path=config_path, dynamic_params=dynamic_params, spark_session=spark_session)