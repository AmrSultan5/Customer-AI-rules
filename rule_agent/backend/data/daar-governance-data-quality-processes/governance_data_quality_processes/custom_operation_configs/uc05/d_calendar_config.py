from marshmallow_dataclass import dataclass
from typing import ClassVar, Type
from marshmallow import Schema  # noqa
from datamesh_transformation.operation_configs.read_dataio_config import ReadDataioConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class DCalendarConfig:

    src_calendar: ReadDataioConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class DCalendarOperationConfig(CustomOperationConfig):
    """
    TOD: Add description ..
    Operation configuration for ...
    """

    params: DCalendarConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
