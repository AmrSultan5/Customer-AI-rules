import pytest
from typing import Dict
from pyspark.sql import SparkSession
from tests.utils.transformation_utils import transform


class TestCASalorgSalesOrg:
    @pytest.mark.usefixtures("spark_session")
    @pytest.mark.parametrize(
        "config_path, dynamic_params",
        [
            (
                "processes/data_quality/ca/red/l2/du_fsm001_visits/v1/du_fsm001_visits_v1.yaml",
                {},
            )
        ],
    )
    def test_ca_salorg_sales_org(self, config_path: str, dynamic_params: Dict, spark_session: SparkSession):
        transform(config_path=config_path, dynamic_params=dynamic_params, spark_session=spark_session)