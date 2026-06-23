from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class GoogleTranslateEnConfig:
    """
    translate to English from respective source language
    """

    input_value: str
    """ input column with text to be translated """

    input_country_code: str
    """ input column with source language """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class GoogleTranslateEnOperationConfig(CommonConfig):
    """
    Operation configuration for validating phone number in data frame column
    """

    params: GoogleTranslateEnConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
