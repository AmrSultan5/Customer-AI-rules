from typing import ClassVar, List, Type

from datamesh_transformation.operation_configs.common import CommonConfig
from marshmallow import Schema  # noqa
from marshmallow_dataclass import dataclass


@dataclass
class LowerConfig:
    """
    conversion column list
    """

    columns: List[str]

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class LowerOperationConfig(CommonConfig):
    """
    Operation configuration for converting string values to lower case
    """

    params: LowerConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
