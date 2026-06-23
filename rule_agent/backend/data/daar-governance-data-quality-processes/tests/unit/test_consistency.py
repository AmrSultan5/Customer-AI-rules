from glob import glob
import pytest
from pyspark.sql import SparkSession

from datamesh_transformation import TransformationProcess


class TestYamlStructure:
    @pytest.mark.usefixtures("spark_session")
    def test_yaml_structure(self, spark_session: SparkSession):

        proc_files = glob("processes/data_quality/cz/uc05/l2/f_sell_out/v1/f_sell_out_v1.yaml", recursive=True)

        jinja_params = {
            #     "country": {
            #         "name": "ca",
            #         "sales_org": "1234",
            #         "comp_code": "0123",
            #     },
            "dataio": {
                "ad_id": "test_ad",
                "storage_id": "test_storage",
            },
            #     "previous_process_run_id": "test",
            #     "process_run_id": "test",
            #     "content": "test",
        }
        for proc_f in proc_files:
            TransformationProcess(
                spark_session=spark_session, config_path=proc_f, module=None, jinja_params=jinja_params
            )
