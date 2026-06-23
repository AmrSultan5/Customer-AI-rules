import pytest
from typing import Dict
from pyspark.sql import SparkSession
from tests.utils.transformation_utils import transform


class TestFProductAggregatedl1l2:
    @pytest.mark.usefixtures("spark_session")
    @pytest.mark.parametrize(
        "config_path, dynamic_params",
        [
            (
                "processes/data_quality/ca/data_control_center/golden/f_product_aggregated_l1_l2/v1/f_product_aggregated_l1_l2_v1.yaml",
                {},
            )
        ],
    )
    def test_f_product_aggregated_l1_l2(self, config_path: str, dynamic_params: Dict, spark_session: SparkSession):
        transform(config_path=config_path, dynamic_params=dynamic_params, spark_session=spark_session)