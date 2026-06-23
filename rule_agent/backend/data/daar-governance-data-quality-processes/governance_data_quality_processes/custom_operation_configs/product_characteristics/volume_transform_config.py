from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class VolumeTransformConfig:
    """
    transform volume like 0.*l to ml
    """

    input_value: str
    """ input column with text to be transformed """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class VolumeTransformOperationConfig(CommonConfig):

    params: VolumeTransformConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
