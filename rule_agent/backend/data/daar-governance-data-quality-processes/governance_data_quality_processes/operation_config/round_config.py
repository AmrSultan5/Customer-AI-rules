from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig


@dataclass
class RoundConfig:
    """
    max dataframe
    """

    columns: List[str]
    """ input column """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class RoundOperationConfig(CommonConfig):
    """
    Operation configuration for Upper dataframe data
    """

    params: RoundConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
