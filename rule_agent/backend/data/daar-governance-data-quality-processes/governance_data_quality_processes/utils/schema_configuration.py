import json
import pkgutil
import re
from itertools import product
from typing import Dict, List, Optional

from governance_data_quality_processes.utils.logging import logger
from governance_data_quality_processes.utils.patterns import Singleton


class SchemaConfiguration(metaclass=Singleton):
    """
    Schema configuration class created as singleton.
    """

    __schema_versions_dictionary: Optional[Dict] = None
    __schema_versions_regex_list: Optional[List] = None
    __module_name: Optional[str] = None

    def initialize_configuration(self, module_name: str, config_name: str) -> None:
        """
        Initialize configuration for selected config. This method can be used only once per its instance.

        :param module_name: Module name for configuration source.
        :type module_name: str
        :param config_name: The json config_name.
        :type config_name: str
        :rtype: None
        """
        if self.__schema_versions_dictionary:
            raise AttributeError(
                "Configuration already initialized! Only one configuration instance is allowed per Python process. "
                "To dynamically delete it (for testing in Databricks), use:\n"
                "from segmex_common.utils.patterns import Singleton\n"
                "from segmex_common.utils.schema_configuration import SchemaConfiguration\n"
                "del Singleton._Singleton__instances[SchemaConfiguration]\n"
            )
        self.__module_name = module_name
        logger.info(f"Initializing schema configuration for module {self.__module_name}")
        self.__schema_versions_dictionary = {}
        self.__schema_versions_regex_list = []
        schema_configuration = self.__load_configuration(config_name)
        version_regex = r"^v\d+$"
        for schema_path, schema_version in schema_configuration.items():
            schema_version = schema_version.lower().strip()
            if not re.match(version_regex, schema_version):
                raise ValueError(f"Wrong schema version definition for {schema_path}!")
            schema_path = self.__unify_schema_path(schema_path)
            if "*" in schema_path:
                schema_path = schema_path.replace("*", r"\w")
                schema_path = r"^" + schema_path + r"$"
                regex_definition = {"schema_path": schema_path, "schema_version": schema_version}
                self.__schema_versions_regex_list.append(regex_definition)
            else:
                if self.__schema_versions_dictionary.get(schema_path):
                    raise ValueError(f"Duplicated key {schema_path} in configuration.")
                self.__schema_versions_dictionary[schema_path] = schema_version
        self.__check_regex_overlaps()

    def get_schema_version(self, schema_path: str) -> Optional[str]:
        """
        Find for schema version for requested object if defined.

        :param schema_path: Object path definition.
        :type schema_path: str
        :return: Schema version if found.
        :rtype: Optional[str]
        """
        schema_path = self.__unify_schema_path(schema_path)
        try:
            return self.__schema_versions_dictionary[schema_path]  # type: ignore[index]
        except KeyError:
            schema_version = self.__find_in_regex_list(schema_path)
            if not schema_version:
                logger.warning(f"Can not find schema version in configuration for object {schema_path}.")
            return schema_version
        except TypeError:
            raise AttributeError("Schema configuration is not initialized!")  # pylint: disable=raise-missing-from

    def __check_regex_overlaps(self) -> None:
        """
        Checking for overlaping entries in regex definitions and raise Attribute Error in such cases.

        :rtype: None
        """
        regex_list = [regex["schema_path"] for regex in self.__schema_versions_regex_list]  # type: ignore[union-attr]
        for regex, value in product(regex_list, repeat=2):
            if id(regex) != id(value):
                if re.match(regex, value[1:-1].replace(r"\w", "_")):
                    err_message = f"Inconsistent definition in configuration, overlapping entries {regex} and {value}"
                    raise AttributeError(err_message)

    def __find_in_regex_list(self, schema_path: str) -> Optional[str]:
        """
        Check if you can find matching schema version in regex list.

        :param schema_path: Object path definition.
        :type schema_path: str
        :return: Schema version for requested object.
        :rtype: Optional[str]
        """
        for regex_schema in self.__schema_versions_regex_list:  # type: ignore[union-attr]
            if re.match(regex_schema["schema_path"], schema_path):
                return regex_schema["schema_version"]
        return None

    def __load_configuration(self, config_name: str) -> Dict:
        """
        Load configuration from json file.

        :param config_name: The json config_name.
        :type config_name: str
        :return: Configuration as dictionary.
        :rtype: Dict
        """
        schema_configuration = self.__load_json_file(config_name)
        if not schema_configuration:
            raise FileNotFoundError("Schema versions configuration not found!")
        return schema_configuration

    def __load_json_file(self, config_name: str) -> Optional[Dict]:
        """
        Load json file from assortment package json file.

        :param config_name: The json config_name.
        :type config_name: str
        :return: Configuration dictionary from package json file.
        :rtype: Optional[Dict]
        """
        try:
            pkg_json_path = self._pkg_json_path(config_name)
            json_data = pkgutil.get_data(self.__module_name, pkg_json_path)  # type: ignore[arg-type]
            logger.info(f"Successfully loaded {config_name} schema versions configuration.")
        except FileNotFoundError:
            logger.info(f"{config_name} schema versions configuration non found.")
            return None
        json_data_decoded = json_data.decode("utf-8")  # type: ignore[union-attr]
        schema_configuration = json.loads(json_data_decoded)
        return schema_configuration

    def __unify_schema_path(self, schema_path: str) -> str:
        """
        Transform path entry to the unified form.

        :param schema_path: Object path definition.
        :type schema_path: str
        :return: Unified object path string.
        :rtype: str
        """
        schema_path = schema_path.lower().strip()
        schema_path = schema_path.replace(" ", "")
        schema_path = schema_path.replace("=", ":")
        schema_path_splitted = schema_path.split(self.config_separator())
        schema_path_splitted.sort()
        schema_path = self.__create_key_and_validate_schema_path(schema_path_splitted)
        return schema_path

    def __create_key_and_validate_schema_path(self, schema_path_splitted: list) -> str:
        """
        Validate, sort and join splitted path.

        :param schema_path_splitted: Object path definition as list.
        :type schema_path_splitted: list
        :return: Validated path string.
        :rtype: str
        """
        try:
            layer = list(filter(lambda x: x.startswith("layer"), schema_path_splitted))[0]
        except IndexError as exc:
            raise ValueError("Invalid configuration - missing layer definition!") from exc
        layer = layer.replace("layer:", "")
        validators = self.__validators[layer]
        if len(validators) < len(schema_path_splitted):
            raise ValueError("Invalid configuration - too many entries!")
        if len(validators) > len(schema_path_splitted):
            raise ValueError("Invalid configuration - too few entries!")
        validated_entries: list = []
        for validator in validators:
            validator_regex = re.compile(validator)
            found_entries = list(filter(validator_regex.match, schema_path_splitted))
            if len(found_entries) != 1:
                raise ValueError("Invalid configuration - found duplicated entries!")
            validated_entries = validated_entries + found_entries
        validated_entries.sort()
        schema_path = self.config_separator().join(schema_path_splitted)
        validation_path = self.config_separator().join(validated_entries)
        if schema_path != validation_path:
            raise ValueError("Invalid configuration - validated path not match!")
        return schema_path

    def _pkg_json_path(self, config_name: str):
        """
        Return path to the requested json configuration.

        :param config_name: The json config_name.
        :type config_name: str
        :return: json configuration path.
        :rtype: str
        """
        return f"configs/schema_versions/{config_name.lower().strip()}.json"

    @property
    def __validators(self) -> Dict:
        """
        Path validatiors list for each layer as regex.

        :return: Validators dictioanry.
        :rtype: Dict
        """
        layer_validation_regex = r"^layer:[\w\*]+$"
        namespace_validation_regex = r"^namespace:[\w\*]+$"
        object_name_validation_regex = r"^object_name:[\w\*]+$"
        validators = {
            "application": [
                layer_validation_regex,
                r"^application_name:[\w\*]+$",
                r"^country:[\w\*]+$",
                r"^module:[\w\*]+$",
                namespace_validation_regex,
                r"^object_name:[\w\*]+$",
            ],
            "curated": [
                layer_validation_regex,
                r"^source:[\w\*]+$",
                namespace_validation_regex,
                object_name_validation_regex,
            ],
            "udm": [
                layer_validation_regex,
                r"^domain:[\w\*]+$",
                namespace_validation_regex,
                object_name_validation_regex,
            ],
        }
        return validators

    @staticmethod
    def config_separator() -> str:
        """
        Configuration path separator.

        :return: Path separator.
        :rtype: str
        """
        return ","
