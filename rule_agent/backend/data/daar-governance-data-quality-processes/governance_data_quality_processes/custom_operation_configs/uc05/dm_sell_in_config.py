from marshmallow_dataclass import dataclass
from typing import ClassVar, Type
from marshmallow import Schema  # noqa
from datamesh_transformation.operation_configs.read_dataio_config import ReadDataioConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class DmSellinConfig:

    src_f_sellin: ReadDataioConfig

    src_d_calendar: ReadDataioConfig

    src_d_product: ReadDataioConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class DmSellinOperationConfig(CustomOperationConfig):
    """
    TOD: Add description ..
    Operation configuration for ...
    """

    params: DmSellinConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
