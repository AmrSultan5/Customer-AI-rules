from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class NadsufixValidatorConfig:
    """
    validate if a column contains a valid phone number
    """

    column_country: str
    """ input column with region """

    column_nad: str
    """ input column with phone number """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class NADValidatorOperationConfig(CommonConfig):
    """
    Operation configuration for validating phone number in data frame column
    """

    params: NadsufixValidatorConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
