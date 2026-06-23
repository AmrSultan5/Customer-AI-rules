from datamesh_transformation.common.context import TransformationContext
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig
from datamesh_transformation.operations.base import BaseOperation
from governance_data_quality_processes.utils.schema_configuration import SchemaConfiguration
from governance_data_quality_processes.utils.logging import logger


class InitializeSchemaConfigurationOperation(BaseOperation):
    """
    This operation initialize configuration object.
    """

    def transform(self, ctx: TransformationContext) -> None:
        assert isinstance(self._config, CustomOperationConfig)

        config_name = self._config.params["config_name"]
        module_name = self._config.params["module_name"]
        if module_name is None or module_name == "":
            raise ValueError("module_name parameter is mandatory!")
        if config_name is None or config_name == "":
            raise ValueError("config_name parameter is mandatory!")
        SchemaConfiguration().initialize_configuration(module_name, config_name)
        logger.info(f"Schema configuration {config_name} initialized")
