from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class ValidateSequentialDigitsConfig:
    """
    set of fields for the check
    """

    tax_0_value: str
    tax_1_value: str
    tax_2_value: str
    tax_3_value: str
    
    """ input columns with value to check """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class ValidateSequentialDigitsOperationConfig(CommonConfig):
    """
    Operation configuration to validate strings based on special character rules specific to each country.
    """

    params: ValidateSequentialDigitsConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
