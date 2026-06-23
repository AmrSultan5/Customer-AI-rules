from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class SalesUnitExtractConfig:
    """
    extract sales unit and description without it
    """

    input_value: str
    """ input column with text from which sales unit to be extracted """

    output_col_name: str
    """ name of output column """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class SalesUnitExtractOperationConfig(CommonConfig):

    params: SalesUnitExtractConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
