import pytest
from typing import Dict
from pyspark.sql import SparkSession
from tests.utils.transformation_utils import transform


class TestDCalendar:
    @pytest.mark.usefixtures("spark_session")
    @pytest.mark.parametrize(
        "config_path, dynamic_params",
        [
            (
                "processes/data_quality/ca/uc05/l2/d_calendar/v1/d_calendar.yaml",
                {},
            )
        ],
    )
    def test_d_calendar(self, config_path: str, dynamic_params: Dict, spark_session: SparkSession):
        transform(config_path=config_path, dynamic_params=dynamic_params, spark_session=spark_session)
