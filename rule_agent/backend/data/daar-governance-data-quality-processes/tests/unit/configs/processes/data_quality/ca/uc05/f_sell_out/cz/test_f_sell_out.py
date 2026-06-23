import pytest
from typing import Dict
from pyspark.sql import SparkSession
from tests.utils.transformation_utils import transform


class TestFSellOutCz:
    @pytest.mark.usefixtures("spark_session")
    @pytest.mark.parametrize(
        "config_path, dynamic_params",
        [
            (
                "processes/data_quality/cz/uc05/l2/f_sell_out/v1/f_sell_out_v1.yaml",
                {},
            )
        ],
    )
    def test_f_sell_out_cz(self, config_path: str, dynamic_params: Dict, spark_session: SparkSession):
        transform(config_path=config_path, dynamic_params=dynamic_params, spark_session=spark_session)
