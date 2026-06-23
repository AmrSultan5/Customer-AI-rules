from abc import ABC
from typing import Union, Dict

from datamesh_common.config import ActiveDirectoryApplicationConfiguration
from datamesh_data_io import (
    DataMeshDataIO,
    MetadataDataLakeObject,
    StorageConfiguration,
    DataLakeLayer,
    CuratedDataLakeObject,
    ApplicationDataLakeObject,
    DataLakeRepository,
    UdmDataLakeObject,
)
from pyspark.sql import SparkSession
from datamesh_common.utils.base_utils import retry_on_error
from datamesh_transformation.operation_configs.dataio_config import DataioDataLakeObjectConfig
from datamesh_transformation.operation_configs.read_dataio_config import ReadDataioOperationConfig
from datamesh_transformation.operation_configs.read_raw_config import ReadRawOperationConfig
from datamesh_transformation.operation_configs.read_raw_req_config import ReadRawReqOperationConfig
from datamesh_transformation.operation_configs.write_dataio_config import WriteDataioOperationConfig
from datamesh_transformation.operation_configs.write_dataio_req_config import WriteDataioReqOperationConfig
from datamesh_transformation.operation_configs.delete_dataio_config import DeleteDataioOperationConfig
from datamesh_transformation.operation_configs.delete_dataio_req_config import DeleteDataioReqOperationConfig
from datamesh_transformation.operation_configs.lookup_config import LookupOperationConfig
from datamesh_transformation.operations.base import BaseOperation


class DataioOperation(BaseOperation, ABC):
    _config: Union[
        WriteDataioOperationConfig,
        WriteDataioReqOperationConfig,
        ReadDataioOperationConfig,
        ReadRawOperationConfig,
        ReadRawReqOperationConfig,
        DeleteDataioOperationConfig,
        LookupOperationConfig,
    ]

    def __init__(
        self,
        operation_config: Union[
            WriteDataioOperationConfig,
            WriteDataioReqOperationConfig,
            ReadDataioOperationConfig,
            ReadRawOperationConfig,
            ReadRawReqOperationConfig,
            DeleteDataioOperationConfig,
            DeleteDataioReqOperationConfig,
            LookupOperationConfig,
        ],
        spark_session: SparkSession,
        dynamic_params: Dict = None,
    ) -> None:
        super().__init__(
            operation_config=operation_config,
            spark_session=spark_session,
            dynamic_params=dynamic_params,
        )
        assert self._config.params.dataio
        self._layer = DataLakeLayer(self._config.params.dataio.layer)

    def get_data_io(self) -> DataMeshDataIO:
        """
        Creates new DataIO for DataIOOperation
        """
        data_io = DataMeshDataIO(
            spark_session=self._spark_session,
            storage=StorageConfiguration.load(configuration_id=self._config.params.dataio.storage_id),
            layer=self._layer,
            active_directory_application_configuration=(
                ActiveDirectoryApplicationConfiguration.load(configuration_id=self._config.params.dataio.ad_id)
                if self._config.params.dataio.ad_id
                else None
            ),
        )
        return data_io

    def get_repository(self) -> DataLakeRepository:
        """
        Creates new repository for DataIOOperation
        """
        # Repository can not be created for raw
        assert isinstance(self._config.params, DataioDataLakeObjectConfig)
        if self._layer == DataLakeLayer.CURATED:
            data_lake_obj = CuratedDataLakeObject(
                source=self._config.params.source,
                namespace=self._config.params.namespace,
                object_name=self._config.params.object_name,
                schema_version=self._config.params.schema_version,
            )
        elif self._layer == DataLakeLayer.UDM:
            data_lake_obj = UdmDataLakeObject(
                domain=self._config.params.domain,
                namespace=self._config.params.namespace,
                object_name=self._config.params.object_name,
                schema_version=self._config.params.schema_version,
            )
        elif self._layer == DataLakeLayer.METADATA:
            data_lake_obj = MetadataDataLakeObject(
                namespace=self._config.params.namespace,
                object_name=self._config.params.object_name,
                schema_version=self._config.params.schema_version,
            )
        else:
            assert self._layer == DataLakeLayer.APPLICATION
            data_lake_obj = ApplicationDataLakeObject(
                application_name=self._config.params.application_name,
                country=self._config.params.country,
                module=self._config.params.module,
                namespace=self._config.params.namespace,
                object_name=self._config.params.object_name,
                schema_version=self._config.params.schema_version,
            )
        return self.get_data_io().repository(data_lake_object=data_lake_obj)

    @retry_on_error(exception_type=BaseException, retry_limit=10, retry_wait_time=15)
    def register_repository(self, repository: DataLakeRepository) -> None:
        if not repository.is_object_registered:
            repository.register_object()
