from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class VolumeExtractConfig:
    """
    extract volume and weight
    """

    input_value: str
    """ input column with text from which volume/weight to be extracted """

    output_col_name: str
    """ name of output column """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class VolumeExtractOperationConfig(CommonConfig):

    params: VolumeExtractConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
