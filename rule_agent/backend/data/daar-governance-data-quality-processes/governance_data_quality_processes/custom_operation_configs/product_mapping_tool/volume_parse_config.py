from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class VolumeParseConfig:
    """
    extract volume and weight
    """

    input_value: str
    """ input column with text from which volume/weight to be extracted """

    output_col_name: str
    """ name of output column """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class VolumeParseOperationConfig(CommonConfig):

    params: VolumeParseConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
