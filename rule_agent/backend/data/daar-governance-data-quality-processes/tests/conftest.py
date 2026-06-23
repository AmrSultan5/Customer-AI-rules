import os
import re
import shutil
import sys
import uuid
from collections import defaultdict
from multiprocessing import RLock
from typing import Dict

import datamesh_common.logging.loggers
import mock
import pytest
from datamesh_common.config import ActiveDirectoryApplicationConfiguration
from datamesh_data_io import DataLakeLayer
from datamesh_data_io.datalake.storage import (
    DataLakeStorage,
    StorageFactory,
    Adls2DataLakeStorage,
    LocalDataLakeStorage,
)
from datamesh_data_io.datalake.storage_config import StorageConfiguration, StorageType
from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession

from tests.constants import INPUT_DATA_ROOT_PATH, ACTUAL_DATA_ROOT_PATH, EXPECTED_DATA_ROOT_PATH

# Disable log analytics
datamesh_common.logging.loggers.common_logger = datamesh_common.logging.loggers.default_logger
datamesh_common.logging.loggers.data_io_logger = datamesh_common.logging.loggers.default_logger
datamesh_common.logging.loggers.transformation_logger = datamesh_common.logging.loggers.default_logger

# Start Storage Mock
test_storages: Dict[DataLakeLayer, Dict[StorageConfiguration, DataLakeStorage]] = defaultdict(dict)
test_storages_lock = RLock()


def get_mocked_storage(
    storage_configuration: StorageConfiguration,
    layer: DataLakeLayer,
    active_directory_application_configuration: ActiveDirectoryApplicationConfiguration = None,
) -> DataLakeStorage:
    test_storages_lock.acquire()
    try:
        if test_storages.get(layer, dict()).get(storage_configuration):
            return test_storages[layer][storage_configuration]

        storage = StorageFactory._get_storage(  # pylint: disable=protected-access # noqa
            storage_configuration=storage_configuration,
            active_directory_application_configuration=active_directory_application_configuration,
            layer=layer,
        )
        if storage_configuration.storage_type == StorageType.adls2:
            assert isinstance(storage, Adls2DataLakeStorage)
            test_storage_container_name = f"container{uuid.uuid4()}".replace("-", "")
            storage._adls2_storage._container_name = (  # pylint: disable=protected-access # noqa
                test_storage_container_name
            )
            storage._adls2_storage._file_system_client = (  # pylint: disable=protected-access # noqa
                storage._adls2_storage._get_file_system_client()  # pylint: disable=protected-access # noqa
            )
        elif storage_configuration.storage_type == StorageType.local:
            assert isinstance(storage, LocalDataLakeStorage)
            if storage.layer == DataLakeLayer.CURATED:
                storage._local_storage._root_directory = os.path.join(
                    INPUT_DATA_ROOT_PATH, "curated"
                )  # pylint: disable=protected-access # noqa
            elif storage.layer == DataLakeLayer.APPLICATION:
                storage._local_storage._root_directory = (  # pylint: disable=protected-access # noqa
                    ACTUAL_DATA_ROOT_PATH
                )
        test_storages[layer][storage_configuration] = storage
    finally:
        test_storages_lock.release()
    return storage


@pytest.fixture(scope="session", autouse=True, name="get_storage_mock")
def fixture_storage_mock():
    with mock.patch(
        "datamesh_data_io.datalake.storage.StorageFactory.get_storage",
        wraps=get_mocked_storage,
    ) as s_mock:
        yield s_mock


@pytest.fixture(scope="session", autouse=True, name="validate_write_access_mock")
def validate_write_access_mock():
    with mock.patch("datamesh_data_io.datalake.repository.DataLakeRepository._validate_write_access") as w_mock:
        yield w_mock


@pytest.fixture(scope="session", autouse=True, name="metastore_rls_query_mock")
def metastore_rls_query_mock():
    with mock.patch("datamesh_data_io.datalake.metastore.base.Metastore.rls_query") as w_mock:
        w_mock.return_value = "1=1"
        yield w_mock


@pytest.fixture(scope="session", name="spark_session")
@pytest.mark.usefixtures("worker_id")
def fixture_spark_session(request, worker_id) -> SparkSession:

    if sys.version_info[1] == 9:
        extra_packages = ["org.apache.hadoop:hadoop-azure:3.3.4"]
    else:
        extra_packages = ["org.apache.hadoop:hadoop-azure:3.3.6"]

    spark_builder = (
        SparkSession.builder.master("local[2]")
        .appName("LocalSparkSessionForTests")
        .config("spark.master.hostname", "localhost")
        .config("spark.driver.hostname", "localhost")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.driver.memory", "4g")
        .config("spark.executor.memory", "4g")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.default.parallelism", "1")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.parquet.datetimeRebaseModeInWrite", "CORRECTED")
        .config("spark.sql.parquet.int96RebaseModeInWrite", "CORRECTED")
        .config("spark.jars.ivy", f"/tmp/ivy/{worker_id}")
        .config("spark.jars.packages", "com.databricks:spark-xml_2.12:0.15.0")
    )
    spark_builder = configure_spark_with_delta_pip(spark_builder, extra_packages=extra_packages)

    spark_session_for_tests = spark_builder.getOrCreate()

    spark_session_for_tests.sparkContext.setLogLevel("WARN")
    request.addfinalizer(spark_session_for_tests.stop)
    return spark_session_for_tests


@pytest.fixture(scope="session", autouse=True, name="mock_local_mnt_path")
def mock_local_mnt_path():
    """replace actual mnt path with local input root"""
    with mock.patch(
        "datamesh_transformation.main.TransformationProcess.get_default_variables",
    ) as r_mock:
        r_mock.return_value = {
            "mnt_path": "tests/data/input/",
        }
        yield r_mock


@pytest.fixture(scope="session", autouse=True, name="cleanup_curated")
def fixture_cleanup_curated(request):
    """Remove curation actual data before tests start and after tests finish"""
    remove_actual_data()
    request.addfinalizer(remove_actual_data)


def remove_actual_data():
    if os.path.exists(ACTUAL_DATA_ROOT_PATH):
        shutil.rmtree(ACTUAL_DATA_ROOT_PATH)


def get_data_from_metadata_db_side_effect():
    def get_db_info_for_request(**kwargs):
        res = []
        query = kwargs.get("query")
        if "[tb_ohd_requests_in_dl]" in query:
            parameters = [request.replace("'", "") for request in re.findall(r"'\w+'", query, flags=re.IGNORECASE)]
            return [
                {
                    "DTP_Request_ID": parameter,
                    "OHD_Table_Name": parameters[len(parameters) - 1],
                    "Load_Type": "D",
                    "Status": "SUCCESS",
                    "Target_State": "2",
                    "Lines_Written": 17,
                }
                for parameter in parameters[:-1]
            ]
        elif "[tb_ohd_config]" in query:
            res = [
                {
                    "Target_Table_Name": ohd.replace("'", ""),
                    "delete_overlapping": "0",
                    "columns_to_overlap": "",
                }
                for ohd in re.findall(r"'\w+'", query, flags=re.IGNORECASE)
            ]
        return res

    return get_db_info_for_request


@pytest.fixture(scope="session", autouse=True, name="mock_get_data_from_metadata_db_for_read")
def mock_get_data_from_metadata_db():
    with mock.patch("datamesh_transformation.common.sap_bw_metadata.get_data_from_metadata_db") as r_mock:
        r_mock.side_effect = get_data_from_metadata_db_side_effect()
        yield r_mock


@pytest.fixture(scope="session", autouse=True, name="mock_execute_metadata_db_query")
def mock_execute_metadata_db_query():
    with mock.patch("datamesh_transformation.common.sap_bw_metadata.execute_metadata_db_query") as r_mock:
        yield r_mock
