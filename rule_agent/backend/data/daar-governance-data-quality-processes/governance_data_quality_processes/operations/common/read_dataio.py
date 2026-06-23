import json
import pkgutil
from typing import Optional, Dict
from marshmallow_dataclass import dataclass
from datetime import date, datetime, timedelta
from pyspark.sql.types import StructType
from pyspark.sql import functions as f
from pyspark.sql import DataFrame
from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operations.read_dataio import ReadDataioOperation
from datamesh_transformation.operation_configs.read_dataio_config import ReadDataioOperationConfig, ReadDataioConfig
from datamesh_common.exceptions import SchemaNotFoundError
from governance_data_quality_processes.utils.schema_configuration import SchemaConfiguration
from governance_data_quality_processes.utils.logging import logger


@dataclass
class CustomReadDataioConfigBase:
    schema_version: Optional[str]
    """version"""
    empty_when_not_available: Optional[bool]
    """empty_flag"""
    load_latest_schema: Optional[bool]
    """load_latest_schema_flag"""
    override_schema_version: Optional[bool]
    """override_schema_version_from_configuration"""
    check_refresh: Optional[bool]
    """execute_refresh_check_during_read"""
    refresh_interval: Optional[int]
    """specify_refresh_interval_in_days"""
    subdomain: Optional[str]
    """udm_subdomain"""


@dataclass
class CustomReadDataioConfig(ReadDataioConfig, CustomReadDataioConfigBase):
    pass


@dataclass
class CustomReadDataioOperationConfig(ReadDataioOperationConfig):
    """
    Operation configuration for reading data frame from DataIO
    """

    params: CustomReadDataioConfig


class CustomReadDataioOperation(ReadDataioOperation):
    """
    Wrapper for ReadDataioOperation to return empty dataframe if the dataset is not registered
    and load schema version from json configuration.
    """

    _config: CustomReadDataioOperationConfig

    def __read_params(self) -> Dict:
        """
        Reads the parameters from the config file and returns them as a dictionary.

        :return: A dictionary of parameters
        :rtype: dict
        """
        empty_when_not_available = self._config.params.empty_when_not_available
        load_latest_schema = self._config.params.load_latest_schema
        override_schema_version = self._config.params.override_schema_version
        check_refresh = self._config.params.check_refresh
        refresh_interval = self._config.params.refresh_interval
        empty_when_not_available = False if empty_when_not_available is None else empty_when_not_available
        load_latest_schema = False if load_latest_schema is None else load_latest_schema
        override_schema_version = False if override_schema_version is None else override_schema_version
        check_refresh = False if check_refresh is None else check_refresh
        refresh_interval = 0 if refresh_interval is None else refresh_interval
        if not isinstance(empty_when_not_available, bool):
            raise TypeError("Parameter empty_when_not_available should be boolean!")
        if not isinstance(load_latest_schema, bool):
            raise TypeError("Parameter load_latest_schema should be boolean!")
        if not isinstance(override_schema_version, bool):
            raise TypeError("Parameter override_schema_version should be boolean!")
        args = dict(
            empty_when_not_available=empty_when_not_available,
            load_latest_schema=load_latest_schema,
            override_schema_version=override_schema_version,
            check_refresh=check_refresh,
            refresh_interval=refresh_interval,
        )
        return args

    def execute(self, ctx: TransformationContext) -> TransformationContext:
        args = self.__read_params()
        empty_when_not_available = args["empty_when_not_available"]
        load_latest_schema = args["load_latest_schema"]
        override_schema_version = args["override_schema_version"]
        check_refresh = args["check_refresh"]
        refresh_interval = args["refresh_interval"]

        config_path = self.__get_schema_config_path()
        config_schema_version = SchemaConfiguration().get_schema_version(config_path)
        self.__validate_setup(config_schema_version, load_latest_schema, override_schema_version)
        self.__update_schema_version_parameter(config_path, config_schema_version, load_latest_schema, override_schema_version)

        if empty_when_not_available is False:
            ctx = super().execute(ctx)
        else:
            try:
                ctx = super().execute(ctx)
            except SchemaNotFoundError:
                logger.info(f"Dataset {self._config.name} unavailable in the datamesh. Returning empty DataFrame.")
                resource = self.__get_dataio_json_config_path()
                json_content = pkgutil.get_data(package="datamesh_data_io", resource=resource)
                schema = StructType.fromJson(json.loads(json_content.decode("utf-8")))
                df_res = self._spark_session.sparkContext.emptyRDD().toDF(schema)
                ctx.last = ctx[self._config.name] = df_res
        if check_refresh is True:
            start_date = self.__last_saturday_date
            check_date = start_date + timedelta(days=refresh_interval)
            if check_date > date.today():
                raise ValueError("You expect refresh date later than current date")
            refresh_date = self.__get_refresh_date(ctx.last)
            if refresh_date < check_date:
                raise ValueError(f"Data refreshed on {str(refresh_date)}, expected {str(check_date)}")
        return ctx

    def __get_dataio_json_config_path(self) -> str:
        """
        Returns path to the dataio json object definition.

        :return: Object path.
        :rtype: str
        """
        object_layer = self._config.params.dataio.layer.lower().strip()
        object_namespace = self._config.params.namespace.lower().strip()
        object_name = self._config.params.object_name.lower().strip()
        schema_version = self._config.params.schema_version.lower().strip()
        if object_layer == "curated":
            object_source = self._config.params.source.lower().strip()
            main_path = "/".join([object_layer, object_source, object_namespace, object_name, schema_version])
        elif object_layer == "application":
            object_application = self._config.params.application_name.lower().strip()
            object_country = self._config.params.country.lower().strip()
            object_module = self._config.params.module.lower().strip()
            main_path = "/".join([object_layer, object_application, object_country, object_module, object_namespace, object_name, schema_version])
        elif object_layer == "udm":
            object_domain = self._config.params.domain.lower().strip()
            object_subdomain = (self._config.params.subdomain or "").lower().strip()
            if object_subdomain:
                main_path = "/".join([object_layer, object_domain, object_subdomain, object_namespace, object_name, schema_version])
            else:
                main_path = "/".join([object_layer, object_domain, object_namespace, object_name, schema_version])
        else:
            raise ValueError(f"Layer {object_layer} is not not supported!")
        return f"/configs/schema/{main_path}/{object_name}_{schema_version}.json"

    def __get_schema_config_path(self) -> str:
        """
        Create string object path representation for schema version searching in configuration.

        :return: Validated path string.
        :rtype: str
        """
        object_layer = self._config.params.dataio.layer
        object_namespace = self._config.params.namespace
        object_name = self._config.params.object_name
        if object_layer == "curated":
            object_source = self._config.params.source
            config_path_splitted = [
                f"layer: {object_layer}",
                f"source: {object_source}",
                f"namespace: {object_namespace}",
                f"object_name: {object_name}",
            ]
        elif object_layer == "application":
            object_application = self._config.params.application_name
            object_country = self._config.params.country
            object_module = self._config.params.module
            config_path_splitted = [
                f"layer: {object_layer}",
                f"application_name: {object_application}",
                f"country: {object_country}",
                f"module: {object_module}",
                f"namespace: {object_namespace}",
                f"object_name: {object_name}",
            ]
        elif object_layer == "udm":
            object_domain = self._config.params.domain
            config_path_splitted = [
                f"layer: {object_layer}",
                f"domain: {object_domain}",
                f"namespace: {object_namespace}",
                f"object_name: {object_name}",
            ]
        else:
            raise ValueError(f"Layer {object_layer} is not not supported!")
        return SchemaConfiguration.config_separator().join(config_path_splitted)

    def __validate_setup(self, config_schema_version: Optional[str], load_latest_schema: bool, override_schema_version: bool) -> None:
        """
        Validate transformaton execution parameters and raise propper exceptions.

        :param config_schema_version: Schema version found in configurations
        :type config_schema_version: Optional[str]
        :param load_latest_schema: Load latest schema parameter
        :type load_latest_schema: bool
        :rtype: None
        """
        if load_latest_schema is True and (
            config_schema_version is not None or self._config.params.schema_version is not None
        ):
            raise ValueError("Specified schema version and load_latest_schema parameter!")
        elif (
            config_schema_version is None and self._config.params.schema_version is None and load_latest_schema is False
        ):
            raise ValueError("Unspecified schema version!")
        elif config_schema_version is not None and self._config.params.schema_version is not None and override_schema_version is False:
            raise ValueError("Duplicated schema version definition in configuration and yaml!")
        elif self._config.params.schema_version is None and override_schema_version is True:
            raise ValueError("Schema version not specified, override is not possible!")

    def __update_schema_version_parameter(
        self, config_path: str, config_schema_version: Optional[str], load_latest_schema: bool, override_schema_version: bool
    ) -> None:
        """
        Update schema version object parameter according to the execution setup.

        :param config_path: String object path representation
        :type config_path: str
        :param config_schema_version: Schema version found in configurations
        :type config_schema_version: Optional[str]
        :param load_latest_schema: Load latest schema parameter
        :type load_latest_schema: bool
        :rtype: None
        """
        if self._config.params.schema_version is None and load_latest_schema is False and override_schema_version is False:
            logger.info(f"Schema version for object {config_path} found in configuration - {config_schema_version}")
            self._config.params.schema_version = config_schema_version
        elif self._config.params.schema_version is not None and load_latest_schema is False and override_schema_version is True:
            logger.info(f"Schema version for object {config_path} overriden - {self._config.params.schema_version}")
        elif self._config.params.schema_version is not None:
            logger.info(f"Schema version for object {config_path} found in yaml - {self._config.params.schema_version}")
        elif load_latest_schema is True:
            logger.info(f"Loading lates available schema version for object {config_path}")

    def __get_refresh_date(self, df_input: DataFrame) -> date:
        max_date = df_input.select(f.max(f.substring("process_run_id", 1, 8))).collect()[0][0]
        date_obj = datetime.strptime(max_date, "%Y%m%d").date()
        return date_obj

    @property
    def __last_saturday_date(self) -> date:
        date_obj = date.today()
        days_since_saturday = (date_obj.weekday() - 5) % 7
        return date_obj - timedelta(days=days_since_saturday)
