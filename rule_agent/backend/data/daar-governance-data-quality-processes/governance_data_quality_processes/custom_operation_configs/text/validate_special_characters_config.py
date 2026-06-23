from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class ValidateSpecialCharactersConfig:
    """
    set of fields for the check
    """

    value: str
    """ input column with value to check """

    country_code: str
    """ input column with country code """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class ValidateSpecialCharactersOperationConfig(CommonConfig):
    """
    Operation configuration to validate strings based on special character rules specific to each country.
    """

    params: ValidateSpecialCharactersConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
