from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig


@dataclass
class UpperConfig:
    """
    max dataframe
    """

    columns: List[str]
    """ input column """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class UpperOperationConfig(CommonConfig):
    """
    Operation configuration for Upper dataframe data
    """

    params: UpperConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
