from marshmallow_dataclass import dataclass
from typing import ClassVar, Type
from marshmallow import Schema  # noqa
from datamesh_transformation.operation_configs.read_dataio_config import ReadDataioConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class FSelloutCZConfig:

    src_sellout_curated: ReadDataioConfig

    src_calendar: ReadDataioConfig

    src_product_map: ReadDataioConfig

    src_sellout: ReadDataioConfig

    # src_cpl_mapping: ReadDataioConfig
    # """
    # TODO: Add description ...
    # """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class FSelloutCZOperationConfig(CustomOperationConfig):
    """
    TOD: Add description ..
    Operation configuration for ...
    """

    params: FSelloutCZConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
